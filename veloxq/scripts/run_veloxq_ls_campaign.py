#!/usr/bin/env python
"""Local search on the pulled VeloxQ samples, setting by setting (second step
of the VeloxQ campaign, 13.10.2026).

For every timetable ``scripts/veloxq_batch.py`` saved for a setting
(``artifacts/campaign/veloxq/<setting>/rep_<r>/<instance>_velox_solution.yaml``)
this runs, each in its own process:

1. ``scripts/run_local_search.py``: the greedy repair (H1) and the k-OPT
   moves (H2), with the cost of 07.10.2026 (time-core violations plus the
   15-minute-break and PR5 pairs first, then the weighted MILP objective), on
   the setting's QUBO cache;
2. the verifier on the repaired timetable, exact room assignment included
   (``_verify``), written next to it as ``<instance>_postLS_verdict.json``.

Outputs: ``artifacts/campaign/veloxq_ls/<setting>/rep_<r>/<instance>_postLS.yaml``
(the repaired timetable with its run record), ``_stats.json`` (every cycle),
``_log.txt``, ``_postLS_verdict.json``, the process log ``<instance>.log``,
``calls.json`` and ``summary.csv`` per setting.

No default budget: --ks, --candidate-shortlist-k, --max-outer-passes and
--max-wall-seconds-per-pass are required ("none" means no cap). A run whose
verdict file exists is skipped, so an interrupted campaign resumes. Refuses
uncommitted changes in the code the runs use.

A rerun of some calls with other repair options goes to its own folder:
--output-name names it (instead of the setting), --calls-file lists the calls
(``rep_<r>/<instance>``, one per line), and the options follow --extra.
--input-run continues an earlier run instead of starting from the VeloxQ
timetables: each call starts from that run's repaired timetable
(``veloxq_ls/<input run>/rep_<r>/<instance>_postLS.yaml``).

Example:
    python scripts/run_veloxq_ls_campaign.py --settings S0 --ks 1 2 --candidate-shortlist-k 10 \\
        --max-outer-passes none --max-wall-seconds-per-pass none
    python scripts/run_veloxq_ls_campaign.py --settings S3 --output-name S3_room_set_rows \\
        --calls-file calls.txt --ks 1 2 --candidate-shortlist-k 10 --max-outer-passes none \\
        --max-wall-seconds-per-pass none --extra --room-set-rows
    python scripts/run_veloxq_ls_campaign.py --settings S3 --input-run S3_room_set_rows \\
        --output-name S3_room_set_rows_k3_targeted --calls-file stuck.txt --ks 3 \\
        --candidate-shortlist-k 10 --max-outer-passes none --max-wall-seconds-per-pass none \\
        --extra --room-set-rows --targeted-k-opt-only
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

IN_ROOT = REPO / "artifacts" / "campaign" / "veloxq"
OUT_ROOT = REPO / "artifacts" / "campaign" / "veloxq_ls"
INSTANCES = REPO / "repository_ready" / "instances" / "synthetic"
TIER_ORDER = ("easy", "medium", "hard", "extreme")
CODE_PATHS = ("src", "cfg", "scripts/run_local_search.py", "scripts/_pipeline_helpers.py",
              "scripts/run_veloxq_ls_campaign.py")


def uncommitted_code() -> List[str]:
    out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no", "--", *CODE_PATHS],
                         cwd=REPO, capture_output=True, text=True).stdout
    return [line[3:] for line in out.splitlines() if line.strip()]


def inputs(setting: str, tiers: Optional[List[str]], only: Optional[List[str]],
           out_dir: Path, calls: Optional[List[str]] = None,
           input_run: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every saved VeloxQ timetable of the setting (or the listed calls), in tier order;
    with ``input_run``, each call starts from that run's repaired timetable instead."""
    out = []
    for sol in (IN_ROOT / setting).glob("rep_*/*_velox_solution.yaml"):
        stem = sol.name[: -len("_velox_solution.yaml")]
        tier = stem.split("_")[0]
        if tiers and tier not in tiers:
            continue
        if only and stem not in only:
            continue
        if calls is not None and f"{sol.parent.name}/{stem}" not in calls:
            continue
        rep = int(sol.parent.name.split("_")[1])
        if input_run is not None:
            sol = OUT_ROOT / input_run / f"rep_{rep}" / f"{stem}_postLS.yaml"
            if not sol.exists():
                raise SystemExit(f"{input_run}: no repaired timetable for rep_{rep}/{stem}")
        out.append({"setting": setting, "stem": stem, "tier": tier, "rep": rep, "solution": sol,
                    "instance": INSTANCES / f"{stem}.yaml",
                    "cache": IN_ROOT / setting / "caches" / f"{stem}.qubo_cache.h5",
                    "prefix": out_dir / f"rep_{rep}" / stem})
    return sorted(out, key=lambda e: (TIER_ORDER.index(e["tier"]), e["stem"], e["rep"]))


def read_calls(path: Optional[str]) -> Optional[List[str]]:
    """The calls listed in ``path`` (``rep_<r>/<instance>``, one per line), or None."""
    if path is None:
        return None
    calls = [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    if not calls:
        raise SystemExit(f"{path}: no calls listed")
    return calls


def cap(value: str) -> Optional[str]:
    return None if value.lower() == "none" else value


def command(e: Dict[str, Any], args: argparse.Namespace) -> List[str]:
    cmd = [sys.executable, str(REPO / "scripts" / "run_local_search.py"),
           "--instance-yaml", str(e["instance"]), "--input-solution", str(e["solution"]),
           "--output-prefix", str(e["prefix"]), "--qubo-cache", str(e["cache"]),
           "--ks", *[str(k) for k in args.ks], "--candidate-shortlist-k", str(args.candidate_shortlist_k)]
    if cap(args.max_outer_passes) is not None:
        cmd += ["--max-outer-passes", str(int(args.max_outer_passes))]
    if cap(args.max_wall_seconds_per_pass) is not None:
        cmd += ["--max-wall-seconds-per-pass", str(float(args.max_wall_seconds_per_pass))]
    return cmd + list(args.extra or [])


def verify(instance: str, solution: str, out: str) -> int:
    """The verifier's verdicts on one repaired timetable (exact rooms included)."""
    from _pipeline_helpers import setup_environment
    setup_environment(REPO)
    from etpmachine.ETPMachine_ProblemInstance import ProblemInstance
    from etpmachine.ETPMachine_SolutionIO import decode_solution, load_solution_yaml
    from etpmachine.ETPMachine_Verifier import verify_solution
    from etpmachine.utils import run_record
    pi = ProblemInstance.from_yaml(instance)
    pi.rebuild_derived()
    L = decode_solution(load_solution_yaml(solution), pi)
    rep = verify_solution(pi, L, include_per_lesson=False, check_rooms=True)
    verdict = {
        "solution_file": run_record.file_identity(solution),
        "instance_file": run_record.file_identity(instance),
        "lessons": len(L),
        "feasible_time_core": bool(rep.is_feasible()),
        "n_violations": int(rep.total_violations()),
        "violations_by_constraint": {k: len(v) for k, v in rep.hard_violations.items()},
        "extra_violations_by_rule": {k: len(v) for k, v in rep.extra_violations.items()},
        "statuses": rep.statuses(),
        "room_assignment": run_record.json_safe(rep.room_assignment),
        "soft_metrics": run_record.json_safe(rep.soft_metrics),
        "environment": run_record.environment(REPO),
    }
    Path(out).write_text(json.dumps(verdict, indent=1), encoding="utf-8")
    print(f"verdict: time core {verdict['statuses'].get('time_core')}, rooms {verdict['statuses'].get('rooms')}, "
          f"full {verdict['statuses'].get('full')}")
    return 0


# ---------------------------------------------------------------- summary

COLUMNS = ["setting", "instance", "tier", "rep", "veloxq_energy", "veloxq_lessons", "veloxq_solver_s",
           "veloxq_time_core", "violations_before", "violations_after", "soft_before", "soft_after",
           "ls_wall_s", "ls_time_to_zero_s", "ls_cycles", "ls_converged", "time_core", "room_rows", "rooms",
           "policy_rules", "full", "call_wall_s"]


def _yaml_meta(path: Path) -> Dict[str, Any]:
    import yaml
    with open(path, "r", encoding="utf-8") as fh:
        return (yaml.safe_load(fh) or {}).get("metadata") or {}


def row(e: Dict[str, Any], calls: Dict[str, float]) -> Optional[Dict[str, Any]]:
    verdict_file = Path(f"{e['prefix']}_postLS_verdict.json")
    post = Path(f"{e['prefix']}_postLS.yaml")
    if not verdict_file.exists() or not post.exists():
        return None
    verdict = json.loads(verdict_file.read_text(encoding="utf-8"))
    status = verdict.get("statuses") or {}
    meta = _yaml_meta(post)
    src = _yaml_meta(e["solution"])
    p2 = src.get("phase2") or {}
    stats_file = Path(f"{e['prefix']}_stats.json")
    stats = json.loads(stats_file.read_text(encoding="utf-8")) if stats_file.exists() else {}
    elapsed, to_zero = 0.0, None
    for c in stats.get("cycles") or []:
        elapsed += float(c.get("wall_seconds") or 0.0)
        if to_zero is None and (c.get("cost_out") or [None])[0] == 0:
            to_zero = round(elapsed, 3)
    if to_zero is None and (stats.get("initial_cost") or [None])[0] == 0:
        to_zero = 0.0
    key = f"rep_{e['rep']}/{e['stem']}"
    return {
        "setting": e["setting"], "instance": e["stem"], "tier": e["tier"], "rep": e["rep"],
        "veloxq_energy": p2.get("energy"), "veloxq_lessons": p2.get("lessons_planned"),
        "veloxq_solver_s": p2.get("veloxq_solver_time_seconds"),
        "veloxq_time_core": (src.get("verifier") or {}).get("feasible"),
        "violations_before": (meta.get("initial_cost") or [None])[0],
        "violations_after": (meta.get("final_cost") or [None])[0],
        "soft_before": (meta.get("initial") or {}).get("soft_objective"),
        "soft_after": (meta.get("final") or {}).get("soft_objective"),
        "ls_wall_s": stats.get("total_wall_seconds"), "ls_time_to_zero_s": to_zero,
        "ls_cycles": stats.get("n_cycles"), "ls_converged": stats.get("converged"),
        "time_core": status.get("time_core"), "room_rows": status.get("room_rows"), "rooms": status.get("rooms"),
        "policy_rules": status.get("policy_rules"), "full": status.get("full"), "call_wall_s": calls.get(key),
    }


def write_summary(out: Path, entries: List[Dict[str, Any]]) -> int:
    out.mkdir(parents=True, exist_ok=True)
    calls_file = out / "calls.json"
    calls = json.loads(calls_file.read_text(encoding="utf-8")) if calls_file.exists() else {}
    rows = [r for r in (row(e, calls) for e in entries) if r is not None]
    with open(out / "summary.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def record_call(out: Path, key: str, seconds: float) -> None:
    calls_file = out / "calls.json"
    calls = json.loads(calls_file.read_text(encoding="utf-8")) if calls_file.exists() else {}
    calls[key] = seconds
    calls_file.write_text(json.dumps(calls, indent=1), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--settings", nargs="+")
    ap.add_argument("--ks", type=int, nargs="+", help="k-OPT neighbourhoods (required)")
    ap.add_argument("--candidate-shortlist-k", type=int, help="(required)")
    ap.add_argument("--max-outer-passes", help="an integer or none (required)")
    ap.add_argument("--max-wall-seconds-per-pass", help="seconds or none (required)")
    ap.add_argument("--extra", nargs=argparse.REMAINDER, help="further run_local_search.py arguments, last")
    ap.add_argument("--tiers", nargs="*", choices=TIER_ORDER)
    ap.add_argument("--only", nargs="*", help="instance names")
    ap.add_argument("--calls-file", help="only the calls listed in this file (rep_<r>/<instance>, one per line)")
    ap.add_argument("--output-name", help="folder under artifacts/campaign/veloxq_ls for the outputs "
                                          "(default: the setting's name; one setting only)")
    ap.add_argument("--input-run", help="start each call from this earlier run's repaired timetable "
                                        "(a folder under artifacts/campaign/veloxq_ls; one setting only)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--summarize-only", action="store_true")
    ap.add_argument("--allow-uncommitted", action="store_true", help="(smoke tests only)")
    ap.add_argument("--_verify", nargs=3, metavar=("INSTANCE", "SOLUTION", "OUT"), help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args._verify:
        return verify(*args._verify)
    if not args.settings:
        ap.error("--settings is required")
    if (args.output_name or args.input_run) and len(args.settings) > 1:
        ap.error("--output-name and --input-run take one setting")
    if args.input_run and (args.output_name or args.settings[0]) == args.input_run:
        ap.error("--input-run must differ from the output folder")
    calls = read_calls(args.calls_file)

    def out_dir(setting: str) -> Path:
        return OUT_ROOT / (args.output_name or setting)

    if args.summarize_only:
        for s in args.settings:
            n = write_summary(out_dir(s), inputs(s, args.tiers, args.only, out_dir(s), calls, args.input_run))
            print(f"[{s}] summary.csv: {n} runs")
        return 0
    if None in (args.ks, args.candidate_shortlist_k, args.max_outer_passes, args.max_wall_seconds_per_pass):
        ap.error("--ks, --candidate-shortlist-k, --max-outer-passes and --max-wall-seconds-per-pass are required "
                 "(no defaults: each experiment sets them; 'none' means no cap)")
    dirty = uncommitted_code()
    if dirty and not args.allow_uncommitted and not args.dry_run:
        raise SystemExit("uncommitted changes in the code the runs use: " + ", ".join(dirty))
    for setting in args.settings:
        out = out_dir(setting)
        entries = inputs(setting, args.tiers, args.only, out, calls, args.input_run)
        if calls is not None and len(entries) != len(calls):
            found = {f"rep_{e['rep']}/{e['stem']}" for e in entries}
            raise SystemExit(f"{args.calls_file}: no VeloxQ timetable of {setting} for "
                             + ", ".join(sorted(set(calls) - found)))
        print(f"[{setting}] {len(entries)} VeloxQ timetables to repair -> {out}", flush=True)
        if args.dry_run:
            if entries:
                print("  first command: " + " ".join(command(entries[0], args)))
            continue
        out.mkdir(parents=True, exist_ok=True)
        (out / "settings.json").write_text(json.dumps(
            {"setting": setting, "ks": args.ks, "candidate_shortlist_k": args.candidate_shortlist_k,
             "max_outer_passes": args.max_outer_passes,
             "max_wall_seconds_per_pass": args.max_wall_seconds_per_pass, "extra": args.extra or [],
             "calls": calls, "input_run": args.input_run},
            indent=1), encoding="utf-8")
        for k, e in enumerate(entries, 1):
            verdict = Path(f"{e['prefix']}_postLS_verdict.json")
            if verdict.exists():
                continue
            e["prefix"].parent.mkdir(parents=True, exist_ok=True)
            t0 = time.time()
            with open(f"{e['prefix']}.log", "w", encoding="utf-8") as log:
                env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
                rc = subprocess.run(command(e, args), cwd=REPO, stdout=log, stderr=subprocess.STDOUT,
                                    env=env).returncode
                if rc == 0:
                    log.flush()
                    rc = subprocess.run([sys.executable, str(Path(__file__)), "--_verify", str(e["instance"]),
                                         f"{e['prefix']}_postLS.yaml", str(verdict)], cwd=REPO, stdout=log,
                                        stderr=subprocess.STDOUT, env=env).returncode
            seconds = round(time.time() - t0, 3)
            record_call(out, f"rep_{e['rep']}/{e['stem']}", seconds)
            r = row(e, json.loads((out / "calls.json").read_text(encoding="utf-8")))
            if rc != 0 or r is None:
                print(f"[{setting} {k}/{len(entries)}] {e['stem']} rep {e['rep']}: FAILED (exit {rc}); "
                      f"see {e['prefix']}.log", flush=True)
            else:
                print(f"[{setting} {k}/{len(entries)}] {e['stem']} rep {e['rep']}: violations "
                      f"{r['violations_before']} -> {r['violations_after']}, all checks {r['full']}, "
                      f"{seconds} s", flush=True)
            write_summary(out, entries)
    return 0


if __name__ == "__main__":
    sys.exit(main())
