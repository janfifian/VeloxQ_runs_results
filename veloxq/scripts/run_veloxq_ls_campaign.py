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

Other VeloxQ runs (19.10.2026): --in-name names the folder under
artifacts/campaign that ``veloxq_batch.py --out-name`` wrote (default
``veloxq``); the outputs then go to ``artifacts/campaign/<in name>_ls``.
--instance-files gives the instance files of instances outside
repository_ready/instances/synthetic (e.g. 3_studies); such an instance has
the tier ``production``.

--empty-start runs the same repair from an empty timetable instead, once per
instance of the setting's saved timetables (a control: what the repair reaches
without the solver). The empty timetable is written to
``<output>/inputs/<instance>_empty.yaml`` and the outputs to
``<output>/rep_0/``; --output-name is required. --input-run continues such a
run too (21.10.2026): its calls are ``rep_0/<instance>``.

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
    python scripts/run_veloxq_ls_campaign.py --in-name veloxq_3studies --settings S3 \\
        --instance-files artifacts/3studies/3_studies_instance.yaml --output-name S3_room_set_rows \\
        --ks 1 2 --candidate-shortlist-k 10 --max-outer-passes none --max-wall-seconds-per-pass none \\
        --extra --room-set-rows
    (the same with --empty-start --output-name S3_room_set_rows_empty_start)
    python scripts/run_veloxq_ls_campaign.py --settings S3 --input-run S3_room_set_rows_empty_start \\
        --output-name S3_room_set_rows_empty_start_k3_targeted --calls-file stuck.txt --ks 3 \\
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

CAMPAIGN = REPO / "artifacts" / "campaign"
IN_ROOT = CAMPAIGN / "veloxq"            # --in-name
OUT_ROOT = CAMPAIGN / "veloxq_ls"        # <in name>_ls
INSTANCES = REPO / "repository_ready" / "instances" / "synthetic"
INSTANCE_FILES: Dict[str, Path] = {}     # --instance-files, by instance name
TIER_ORDER = ("easy", "medium", "hard", "extreme")
PRODUCTION = "production"                # the tier of any other instance
CODE_PATHS = ("src", "cfg", "scripts/run_local_search.py", "scripts/_pipeline_helpers.py",
              "scripts/run_veloxq_ls_campaign.py")


def uncommitted_code() -> List[str]:
    out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no", "--", *CODE_PATHS],
                         cwd=REPO, capture_output=True, text=True).stdout
    return [line[3:] for line in out.splitlines() if line.strip()]


def tier_of(stem: str) -> str:
    head = stem.split("_")[0]
    return head if head in TIER_ORDER else PRODUCTION


def started_empty(run: str) -> bool:
    """Whether an earlier repair run started from empty timetables (--empty-start)."""
    settings = OUT_ROOT / run / "settings.json"
    return settings.exists() and bool(json.loads(settings.read_text(encoding="utf-8")).get("empty_start"))


def inputs(setting: str, tiers: Optional[List[str]], only: Optional[List[str]],
           out_dir: Path, calls: Optional[List[str]] = None,
           input_run: Optional[str] = None, empty_start: bool = False) -> List[Dict[str, Any]]:
    """Every saved VeloxQ timetable of the setting (or the listed calls), in tier order;
    with ``input_run``, each call starts from that run's repaired timetable instead;
    with ``empty_start``, one call per instance, from an empty timetable (rep 0), and
    the same when ``input_run`` is such a run (each call continues its rep 0)."""
    per_instance = empty_start or (input_run is not None and started_empty(input_run))
    out, seen = [], set()
    for sol in (IN_ROOT / setting).glob("rep_*/*_velox_solution.yaml"):
        stem = sol.name[: -len("_velox_solution.yaml")]
        tier = tier_of(stem)
        if tiers and tier not in tiers:
            continue
        if only and stem not in only:
            continue
        key = f"rep_0/{stem}" if per_instance else f"{sol.parent.name}/{stem}"
        if calls is not None and key not in calls:
            continue
        rep = 0 if per_instance else int(sol.parent.name.split("_")[1])
        if per_instance:
            if stem in seen:
                continue
            seen.add(stem)
        if empty_start:
            sol = out_dir / "inputs" / f"{stem}_empty.yaml"
        if input_run is not None:
            sol = OUT_ROOT / input_run / f"rep_{rep}" / f"{stem}_postLS.yaml"
            if not sol.exists():
                raise SystemExit(f"{input_run}: no repaired timetable for rep_{rep}/{stem}")
        out.append({"setting": setting, "stem": stem, "tier": tier, "rep": rep, "solution": sol,
                    "instance": INSTANCE_FILES.get(stem, INSTANCES / f"{stem}.yaml"),
                    "cache": IN_ROOT / setting / "caches" / f"{stem}.qubo_cache.h5",
                    "prefix": out_dir / f"rep_{rep}" / stem})
    order = TIER_ORDER + (PRODUCTION,)
    return sorted(out, key=lambda e: (order.index(e["tier"]), e["stem"], e["rep"]))


def write_empty_start(e: Dict[str, Any]) -> None:
    """The empty timetable an --empty-start call begins from (kept if it exists)."""
    from _pipeline_helpers import setup_environment
    setup_environment(REPO)
    from etpmachine.ETPMachine_SolutionIO import TimetableSolution, save_solution_yaml
    from etpmachine.utils import run_record
    if e["solution"].exists():
        return
    save_solution_yaml(e["solution"], TimetableSolution(lessons=[], room_assignments=[], metadata={
        "empty_start": True,
        "note": "no lessons: the start of the empty-start control of run_veloxq_ls_campaign.py",
        "instance_file": run_record.file_identity(e["instance"]),
    }))


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
    ap.add_argument("--in-name", default="veloxq",
                    help="the VeloxQ run folder under artifacts/campaign (veloxq_batch.py --out-name); "
                         "outputs go to artifacts/campaign/<in name>_ls")
    ap.add_argument("--instance-files", nargs="+", type=Path, default=[],
                    help="instance files outside repository_ready/instances/synthetic, e.g. 3_studies")
    ap.add_argument("--empty-start", action="store_true",
                    help="start each instance once from an empty timetable instead (needs --output-name)")
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
    if args.empty_start and (not args.output_name or args.input_run or args.calls_file):
        ap.error("--empty-start needs --output-name and takes neither --input-run nor --calls-file")
    global IN_ROOT, OUT_ROOT
    IN_ROOT, OUT_ROOT = CAMPAIGN / args.in_name, CAMPAIGN / f"{args.in_name}_ls"
    for f in args.instance_files:
        INSTANCE_FILES[f.stem] = f if f.is_absolute() else REPO / f
    calls = read_calls(args.calls_file)

    def out_dir(setting: str) -> Path:
        return OUT_ROOT / (args.output_name or setting)

    def entries_of(setting: str) -> List[Dict[str, Any]]:
        found = inputs(setting, args.tiers, args.only, out_dir(setting), calls, args.input_run,
                       args.empty_start)
        missing = sorted({str(e["instance"]) for e in found if not e["instance"].exists()})
        if missing:
            raise SystemExit("no instance file (see --instance-files): " + ", ".join(missing))
        return found

    if args.summarize_only:
        for s in args.settings:
            n = write_summary(out_dir(s), entries_of(s))
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
        entries = entries_of(setting)
        if calls is not None and len(entries) != len(calls):
            found = {f"rep_{e['rep']}/{e['stem']}" for e in entries}
            raise SystemExit(f"{args.calls_file}: no VeloxQ timetable of {setting} for "
                             + ", ".join(sorted(set(calls) - found)))
        start = "empty timetables" if args.empty_start else "VeloxQ timetables"
        print(f"[{setting}] {len(entries)} {start} to repair -> {out}", flush=True)
        if args.dry_run:
            if entries:
                print("  first command: " + " ".join(command(entries[0], args)))
            continue
        out.mkdir(parents=True, exist_ok=True)
        (out / "settings.json").write_text(json.dumps(
            {"setting": setting, "ks": args.ks, "candidate_shortlist_k": args.candidate_shortlist_k,
             "max_outer_passes": args.max_outer_passes,
             "max_wall_seconds_per_pass": args.max_wall_seconds_per_pass, "extra": args.extra or [],
             "calls": calls, "input_run": args.input_run, "in_name": args.in_name,
             "instance_files": [str(f) for f in args.instance_files], "empty_start": args.empty_start},
            indent=1), encoding="utf-8")
        for k, e in enumerate(entries, 1):
            verdict = Path(f"{e['prefix']}_postLS_verdict.json")
            if verdict.exists():
                continue
            if args.empty_start:
                write_empty_start(e)
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
