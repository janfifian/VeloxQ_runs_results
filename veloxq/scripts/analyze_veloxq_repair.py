#!/usr/bin/env python
"""Tables of the repair (H1 + k-OPT) on the VeloxQ answers (17.10.2026).

Reads a repair run of ``scripts/run_veloxq_ls_campaign.py`` (default:
``S3_room_set_rows``, the repair with the MILP's room-set rows on every S3
call), its continuation of the calls left invalid (default:
``S3_room_set_rows_k3_targeted``, the targeted k = 3 moves), the exhaustive
check of those calls (``two_move_neighbourhood.json``, written by
``checks/two_move_neighbourhood.py --out``) and the MILP optima
(``analysis/energy_separation.csv``: E_opt, the weighted objective of the
proven optimum). Needs only PyYAML: everything comes from the files the
repair wrote (the verifier's verdicts, with the exact room assignment, and
the run records), so the tables can be recomputed from the deposit without
the project's code.

The weighted objective is reported only for timetables that pass every
check (time core, room rows, exact room assignment, 15-minute break, PR5):
the objective of a timetable that breaks a rule is no result.

Writes to ``--out`` (default: the analysis folder of ``--root``):
  repair_calls.csv   per call: the repair's cost before and after, the
                     verifier's statuses, lessons and rooms, what is left,
                     the objective and its gap to the MILP optimum (valid
                     timetables only), search time, cycles, code commit;
  repair_tiers.csv   per tier: valid calls and instances, calls at the
                     optimum, gap median and maximum, best call per instance,
                     search time;
  repair_stuck.csv   per call left invalid: the course short of its minutes,
                     what blocks its places, the 1- and 2-moves that give a
                     valid timetable (none, if the repair stopped where it
                     should), and the continuation's verdict.

Usage:
  python scripts/analyze_veloxq_repair.py                      (artifacts/campaign)
  python scripts/analyze_veloxq_repair.py --root repository_ready/veloxq_synthetic --out <folder>
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import median

import yaml

REPO = Path(__file__).resolve().parents[1]
TIERS = ("easy", "medium", "hard", "extreme")
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

CALL_COLUMNS = ["setting", "instance", "tier", "rep", "violations_before", "violations_after",
                "room_set_rows_exceeded", "time_core", "room_rows", "rooms", "policy_rules", "full",
                "lessons", "in_person", "roomed", "left", "objective", "milp_optimum", "gap_percent",
                "repair_seconds", "cycles", "converged", "commit"]
TIER_COLUMNS = ["tier", "calls", "calls_valid", "instances", "instances_valid", "instances_with_optimum",
                "valid_calls_with_optimum", "calls_at_optimum", "gap_median", "gap_max",
                "instances_best_at_optimum", "best_gap_median", "best_gap_max",
                "repair_seconds_median", "repair_seconds_max", "calls_converged"]
STUCK_COLUMNS = ["setting", "instance", "rep", "course", "missing_minutes", "lessons_now", "groups", "students",
                 "places", "places_by_clashing_lessons", "places_room_rules_broken", "valid_1_moves",
                 "lessons_freeing_a_place", "valid_2_moves", "valid_2_moves_on_shortlists",
                 "other_calls_valid", "continued_violations_after", "continued_full"]


def default_root() -> Path:
    here = Path(__file__).resolve().parents[1]
    if (here / "SHA256SUMS").exists():                  # run from inside the deposit
        return here
    return REPO / "artifacts" / "campaign" / "veloxq"


def metadata(path: Path) -> dict:
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    with open(path, encoding="utf-8") as fh:
        return (yaml.load(fh, Loader=loader) or {}).get("metadata") or {}


def read_csv(path: Path) -> list:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, columns: list, rows: list) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def calls_of(run: Path, optima: dict) -> list:
    """One row per call of a repair run, from its verdict files and run records."""
    rows = []
    for verdict_file in sorted(run.glob("rep_*/*_postLS_verdict.json")):
        stem = verdict_file.name[: -len("_postLS_verdict.json")]
        rep = int(verdict_file.parent.name.split("_")[1])
        v = json.loads(verdict_file.read_text(encoding="utf-8"))
        md = metadata(verdict_file.with_name(f"{stem}_postLS.yaml"))
        stats = json.loads(verdict_file.with_name(f"{stem}_stats.json").read_text(encoding="utf-8"))
        st = v["statuses"]
        ra = v.get("room_assignment") or {}
        left = {k: n for k, n in v["violations_by_constraint"].items() if n}
        left.update({k: n for k, n in v["extra_violations_by_rule"].items() if n})
        full = st.get("full") is True
        objective = float(md["final"]["soft_objective"]) if full else None
        opt = optima.get(stem)
        gap = 100.0 * (objective - opt) / abs(opt) if (full and opt is not None) else None
        rows.append({
            "setting": json.loads((run / "settings.json").read_text(encoding="utf-8")).get("setting") or run.name,
            "instance": stem, "tier": stem.split("_")[0], "rep": rep,
            "violations_before": int(md["initial_cost"][0]), "violations_after": int(md["final_cost"][0]),
            "room_set_rows_exceeded": sum((md["final"].get("room_set_rows_exceeded") or {}).values()),
            "time_core": st.get("time_core"), "room_rows": st.get("room_rows"), "rooms": st.get("rooms"),
            "policy_rules": st.get("policy_rules"), "full": full,
            "lessons": v.get("lessons"), "in_person": ra.get("n_in_person"), "roomed": ra.get("n_roomed"),
            "left": " ".join(f"{k}={n}" for k, n in sorted(left.items())),
            "objective": objective, "milp_optimum": opt, "gap_percent": gap,
            "repair_seconds": stats.get("total_wall_seconds"), "cycles": stats.get("n_cycles"),
            "converged": stats.get("converged"),
            "commit": ((md.get("environment") or {}).get("code") or {}).get("commit"),
        })
    return sorted(rows, key=lambda r: (TIERS.index(r["tier"]), r["instance"], r["rep"]))


def tiers_of(calls: list) -> list:
    out = []
    for tier in TIERS:
        g = [c for c in calls if c["tier"] == tier]
        if not g:
            continue
        valid = [c for c in g if c["full"]]
        known = [c for c in valid if c["gap_percent"] is not None]
        best = defaultdict(lambda: None)
        for c in known:
            b = best[c["instance"]]
            best[c["instance"]] = c["gap_percent"] if b is None else min(b, c["gap_percent"])
        with_opt = {c["instance"] for c in g if c["milp_optimum"] is not None}
        secs = [c["repair_seconds"] for c in g]
        out.append({
            "tier": tier, "calls": len(g), "calls_valid": len(valid),
            "instances": len({c["instance"] for c in g}), "instances_valid": len({c["instance"] for c in valid}),
            "instances_with_optimum": len(with_opt), "valid_calls_with_optimum": len(known),
            "calls_at_optimum": sum(1 for c in known if abs(c["objective"] - c["milp_optimum"]) < 1e-6),
            "gap_median": median(c["gap_percent"] for c in known) if known else None,
            "gap_max": max(c["gap_percent"] for c in known) if known else None,
            "instances_best_at_optimum": sum(1 for b in best.values() if abs(b) < 1e-9),
            "best_gap_median": median(best.values()) if best else None,
            "best_gap_max": max(best.values()) if best else None,
            "repair_seconds_median": median(secs), "repair_seconds_max": max(secs),
            "calls_converged": sum(1 for c in g if c["converged"]),
        })
    return out


def stuck_of(calls: list, two_move: list, continued: dict) -> list:
    by_call = {c["call"]: c for c in two_move}
    out = []
    for c in calls:
        if c["full"]:
            continue
        key = f"rep_{c['rep']}/{c['instance']}"
        tm = by_call.get(key)
        if tm is None or "skipped" in tm:
            raise SystemExit(f"{key}: not in two_move_neighbourhood.json, or skipped there "
                             "(run checks/two_move_neighbourhood.py --run <run> --out <run>/two_move_neighbourhood.json)")
        if len(tm["short"]) != 1:
            raise SystemExit(f"{key}: {len(tm['short'])} courses short; the table holds one per call")
        s = tm["short"][0]
        k = continued.get((c["instance"], c["rep"]))
        out.append({
            "setting": c["setting"], "instance": c["instance"], "rep": c["rep"], "course": s["course"],
            "missing_minutes": s["missing_minutes"], "lessons_now": s["lessons_now"], "groups": s["groups"],
            "students": s["students"], "places": s["places"],
            "places_by_clashing_lessons": " ".join(f"{n}:{m}" for n, m in sorted(
                (int(n), m) for n, m in s["places_by_clashing_lessons"].items())),
            "places_room_rules_broken": s["places_with_room_rules_broken"],
            "valid_1_moves": tm["valid_after_1_move"],
            "lessons_freeing_a_place": tm["lessons_whose_removal_frees_a_place"],
            "valid_2_moves": tm["valid_after_2_moves"],
            "valid_2_moves_on_shortlists": tm["of_them_on_the_repair_shortlists"],
            "other_calls_valid": sum(1 for o in calls if o["instance"] == c["instance"] and o["rep"] != c["rep"]
                                     and o["full"]),
            "continued_violations_after": None if k is None else k["violations_after"],
            "continued_full": None if k is None else k["full"],
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=default_root(),
                    help="the VeloxQ campaign folder or deposit (its analysis/energy_separation.csv)")
    ap.add_argument("--repair", type=Path, help="folder of the repair runs (default: <root>/repair in the "
                                                "deposit, artifacts/campaign/veloxq_ls otherwise)")
    ap.add_argument("--run", default="S3_room_set_rows")
    ap.add_argument("--continuation", default="S3_room_set_rows_k3_targeted")
    ap.add_argument("--out", type=Path, help="default: <root>/analysis")
    args = ap.parse_args()
    root = args.root.resolve()
    repair = (args.repair or (root / "repair" if (root / "repair").is_dir()
                              else REPO / "artifacts" / "campaign" / "veloxq_ls")).resolve()
    out = (args.out or root / "analysis").resolve()
    optima = {}
    for r in read_csv(root / "analysis" / "energy_separation.csv"):
        optima.setdefault(r["instance"], float(r["E_opt"]))
    calls = calls_of(repair / args.run, optima)
    continued = {(c["instance"], c["rep"]): c for c in calls_of(repair / args.continuation, optima)}
    two_move = json.loads((repair / args.run / "two_move_neighbourhood.json").read_text(encoding="utf-8"))
    tiers, stuck = tiers_of(calls), stuck_of(calls, two_move, continued)
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "repair_calls.csv", CALL_COLUMNS, calls)
    write_csv(out / "repair_tiers.csv", TIER_COLUMNS, tiers)
    write_csv(out / "repair_stuck.csv", STUCK_COLUMNS, stuck)
    print(f"{args.run}: {len(calls)} calls, {sum(c['full'] for c in calls)} pass every check; "
          f"{len(stuck)} left invalid, {sum(1 for s in stuck if s['continued_full'])} valid after "
          f"{args.continuation}; tables in {out}")
    for t in tiers:
        print(f"  {t['tier']:8s} valid {t['calls_valid']}/{t['calls']} calls, {t['instances_valid']}/{t['instances']} "
              f"instances; at the optimum {t['calls_at_optimum']} of {t['valid_calls_with_optimum']}; gap median "
              f"{t['gap_median']}, max {t['gap_max']}; search s median {t['repair_seconds_median']:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
