#!/usr/bin/env python
"""What the VeloxQ samples are worth before any repair (VeloxQ campaign, 13.10.2026).

Reads what ``scripts/veloxq_batch.py`` saved (``artifacts/campaign/veloxq/<setting>/``)
and writes to ``artifacts/campaign/veloxq/analysis/``:

``calls.csv``
    one row per call (setting, instance, repetition): matrix size and largest
    coefficient, the smallest ratio of a configured penalty to what it must
    exceed on the instance (below 1: not sufficient), upload, queue and solver
    times, and the best sample's verdicts: V and its families, lessons placed
    of those the instance needs, the 15-minute-break and PR5 pairs, the exact
    room assignment, all checks, and the weighted MILP objective of the
    decoded timetable (the repair's second key).
``tiers.csv``
    per setting and tier: calls, share of calls whose best sample has V = 0 and
    passes every check, share of instances with V = 0 in at least one call,
    medians of V, of the share of lessons placed and of the times.
``paired.csv``
    per instance, the settings side by side (best of the calls: lowest V, then
    most lessons placed), when more than one setting has results.
``topk.csv`` (with ``--top-k K``)
    per call, the K lowest-energy distinct samples decoded and checked (V with
    the room rows, without the exact room assignment; lessons placed): the V of
    the lowest-energy sample, the lowest V among the K and its energy rank,
    how many of the K have V = 0, and the rank correlation of energy and V.
    This shows whether the repair would start better from a sample other
    than the solver's answer (its lowest-energy sample).
``breakdown.csv`` (with ``--top-k K``)
    how two samples of each call break: the lowest-energy sample and the
    sample with the fewest violations among the K lowest (the lowest-energy
    one among those with that V). Per rule family the number of violations;
    the course-hour violations (PR1) split into courses given too many and
    too few 45-minute units (with the units over and under, and the courses
    given none); lesson blocks over the course's limit (MC). Then every
    check (V, exact room assignment, 15-minute break, PR5): on the sample as
    returned when it has V = 0, and after deleting its surplus lessons (per
    over-placed course one lesson whose length equals the excess; a deletion
    cannot break another rule) when it places too many.
``breakdown_tiers.csv`` (with ``--top-k K``)
    per setting, tier and sample: the share of calls breaking each rule
    family, the mean number of violations per call, and the share of calls
    passing every check as returned and after the deletion.
``tier_view.csv`` (with ``--top-k K``)
    per tier, the settings side by side: instances with a feasible sample in
    some call (lowest-energy sample; fewest violations among the K lowest),
    instances with a sample passing every check (as returned; after the
    deletion), the median V of both samples, and the median weighted MILP
    objective of the feasible lowest-energy samples.

Energies are compared within a call only: each setting is a different
Hamiltonian. Read-only: nothing VeloxQ-side, no change to the campaign's files.

``--root`` reads another copy of the campaign's files laid out the same way,
such as the deposit ``repository_ready/veloxq_synthetic``; ``--out`` writes
the tables elsewhere (default: ``<root>/analysis``).

Usage:
    python scripts/analyze_veloxq_campaign.py
    python scripts/analyze_veloxq_campaign.py --settings S0 --top-k 16
    python scripts/analyze_veloxq_campaign.py --root repository_ready/veloxq_synthetic --out my_rerun --top-k 16
"""
from __future__ import annotations

import argparse
import json
import sys
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

import pandas as pd  # noqa: E402
import yaml  # noqa: E402

ROOT = REPO / "artifacts" / "campaign" / "veloxq"
REGISTRY = REPO / "repository_ready" / "instances" / "registry.json"
INSTANCES = REPO / "repository_ready" / "instances" / "synthetic"
TIER_ORDER = ["easy", "medium", "hard", "extreme"]
FAMILIES = ("PR1_course_minutes", "MC_max_chunks", "PR3_PR4_lecturer_overlap", "PR3_PR4_group_overlap",
            "RU2_lecturer_availability", "PR2_lecturer_assigned", "CONJ_PHASE3_room_count",
            "CONJ_PHASE3_room_capacity")
PR1_DETAIL = ("PR1_courses_over", "PR1_units_over", "PR1_courses_under", "PR1_units_under",
              "PR1_courses_absent", "MC_blocks_over")


def lessons_needed() -> Dict[str, int]:
    """Lessons of each instance's certificate (a complete timetable)."""
    return {Path(r["instance"]).stem: int(r["lessons"])
            for r in json.loads(REGISTRY.read_text(encoding="utf-8")) if r.get("cohort") == "synthetic"}


def timeline_seconds(timeline: Any, name: str) -> Optional[float]:
    for item in timeline or []:
        if isinstance(item, dict) and item.get("name") == name and isinstance(item.get("value"), (int, float)):
            return float(item["value"])
    return None


def penalty_margin(config: Dict[str, Any], required: Dict[str, Any]) -> tuple:
    """Smallest configured/required ratio over the penalties that can bind."""
    worst, which = None, None
    for key, need in (required or {}).items():
        if not need or key not in (config or {}):
            continue
        ratio = float(config[key]) / float(need)
        if worst is None or ratio < worst:
            worst, which = ratio, key
    return worst, which


def soft_objective(solution: Path, setting: str, stem: str) -> Optional[float]:
    """The weighted MILP objective of a saved timetable (the repair's tie-break)."""
    from run_local_search import _load_pi_and_qubo
    from etpmachine.ETPMachine_Schedule import Schedule
    cache = ROOT / setting / "caches" / f"{stem}.qubo_cache.h5"
    try:
        pi, qubo = _load_pi_and_qubo(INSTANCES / f"{stem}.yaml", cache, None, skip_qubo_energy=True)
        sched = Schedule.from_yaml(solution, pi, qubo=qubo, skip_energy=True,
                                   tie_break="soft_objective", count_extra_rules=True, pr5=True)
        return float(sched.soft_cost)
    except Exception as exc:  # reported, not fatal: one bad file must not stop the analysis
        print(f"  [warn] soft objective of {solution.name}: {exc!r}")
        return None


def calls_table(settings: List[str], with_soft: bool) -> pd.DataFrame:
    needed = lessons_needed()
    rows = []
    for setting in settings:
        for sol in sorted((ROOT / setting).glob("rep_*/*_velox_solution.yaml")):
            stem = sol.name[: -len("_velox_solution.yaml")]
            md = (yaml.safe_load(open(sol, encoding="utf-8")) or {}).get("metadata") or {}
            p2, ver = md.get("phase2") or {}, md.get("verifier") or {}
            status, extra = ver.get("statuses") or {}, ver.get("extra_violations_by_rule") or {}
            qm = p2.get("qubo_matrix") or {}
            margin, which = penalty_margin(p2.get("qubo_config") or {}, p2.get("qubo_penalty_requirements") or {})
            ra = ver.get("room_assignment") or {}
            row = {
                "setting": setting, "instance": stem, "tier": stem.split("_")[0],
                "rep": int(sol.parent.name.split("_")[1]), "job_id": p2.get("veloxq_job_id"),
                "n_vars": p2.get("n_vars"), "n_q_entries": p2.get("n_q_entries"),
                "max_abs_coefficient": max(((qm.get("qubo_diagonal") or {}).get("max_abs") or 0),
                                           ((qm.get("qubo_off_diagonal") or {}).get("max_abs") or 0)) or None,
                "smallest_penalty_ratio": margin, "smallest_ratio_penalty": which,
                "upload_s": p2.get("upload_seconds"),
                "queue_s": timeline_seconds(p2.get("veloxq_job_timeline"), "pending"),
                "running_s": timeline_seconds(p2.get("veloxq_job_timeline"), "running"),
                "solver_s": p2.get("veloxq_solver_time_seconds"),
                "energy": p2.get("energy"), "lessons_placed": p2.get("lessons_planned"),
                "lessons_needed": needed.get(stem),
                "V": ver.get("n_violations"),
                "time_core": status.get("time_core"), "room_rows": status.get("room_rows"),
                "rooms": status.get("rooms"), "policy_rules": status.get("policy_rules"), "full": status.get("full"),
                "break_pairs": sum(v for k, v in extra.items() if k.startswith("BREAK")),
                "pr5_pairs": sum(v for k, v in extra.items() if k.startswith("PR5")),
                "in_person_roomed": ra.get("n_roomed"), "in_person": ra.get("n_in_person"),
                "distinct_samples": (p2.get("veloxq_samples_file") or {}).get("n_distinct_samples"),
                "reads": (p2.get("veloxq_samples_file") or {}).get("n_reads"),
            }
            for family, n in (ver.get("violations_by_constraint") or {}).items():
                row[f"V_{family}"] = n
            if with_soft:
                row["soft_objective"] = soft_objective(sol, setting, stem)
            rows.append(row)
    df = pd.DataFrame(rows)
    if not df.empty:
        df["share_placed"] = df["lessons_placed"] / df["lessons_needed"]
        df["tier"] = pd.Categorical(df["tier"], TIER_ORDER, ordered=True)
        df = df.sort_values(["setting", "tier", "instance", "rep"])
    return df


def tiers_table(calls: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (setting, tier), g in calls.groupby(["setting", "tier"], observed=True):
        per_instance = g.groupby("instance")["V"].min()
        rows.append({
            "setting": setting, "tier": tier, "calls": len(g), "instances": g["instance"].nunique(),
            "share_calls_V0": round(float((g["V"] == 0).mean()), 3),
            "share_calls_all_checks": round(float((g["full"] == True).mean()), 3),  # noqa: E712
            "share_instances_V0_in_some_call": round(float((per_instance == 0).mean()), 3),
            "median_V": float(g["V"].median()), "median_share_placed": round(float(g["share_placed"].median()), 3),
            "median_solver_s": float(g["solver_s"].median()), "median_queue_s": float(g["queue_s"].median()),
            "median_n_vars": float(g["n_vars"].median()),
            "median_smallest_penalty_ratio": float(g["smallest_penalty_ratio"].median()),
        })
    return pd.DataFrame(rows)


def paired_table(calls: pd.DataFrame) -> pd.DataFrame:
    best = (calls.sort_values(["V", "lessons_placed"], ascending=[True, False])
                 .groupby(["setting", "instance"], observed=True).first().reset_index())
    wide = best.pivot(index="instance", columns="setting", values=["V", "lessons_placed", "full"])
    wide.columns = [f"{a}_{b}" for a, b in wide.columns]
    return wide.reset_index()


def violation_breakdown(report: Any) -> Dict[str, Any]:
    """How a timetable breaks: the violations of each rule family; the
    course-hour violations (PR1) split into courses given too many and too few
    45-minute units, with the units over and under and the courses given no
    lesson at all; the lesson blocks over the courses' limits (MC)."""
    hv = report.hard_violations
    out: Dict[str, Any] = {f: len(hv.get(f, [])) for f in FAMILIES}
    pr1 = hv.get("PR1_course_minutes", [])
    over = [v for v in pr1 if v["scheduled_minutes"] > v["required_minutes"]]
    under = [v for v in pr1 if v["scheduled_minutes"] < v["required_minutes"]]
    out.update({
        "PR1_courses_over": len(over),
        "PR1_units_over": sum(v["scheduled_minutes"] - v["required_minutes"] for v in over) / 45,
        "PR1_courses_under": len(under),
        "PR1_units_under": sum(v["required_minutes"] - v["scheduled_minutes"] for v in under) / 45,
        "PR1_courses_absent": sum(1 for v in under if v["scheduled_minutes"] == 0),
        "MC_blocks_over": sum(v["scheduled_chunks"] - v["max_chunks"] for v in hv.get("MC_max_chunks", [])),
    })
    return out


def delete_surplus(pi: Any, L: Dict[int, Dict[str, Any]], report: Any) -> tuple:
    """For each course given more minutes than it needs (PR1 over), delete one
    of its lessons whose length equals the excess (the last such lesson by
    index). A deletion cannot create an overlap, a room-row violation, a break
    or PR5 pair. Returns (timetable, lessons deleted, over-placed courses with
    no lesson of that length)."""
    from etpmachine import ETPMachine_Verifier as Verifier
    L2, deleted, unmatched = dict(L), 0, 0
    for v in report.hard_violations.get("PR1_course_minutes", []):
        excess = v["scheduled_minutes"] - v["required_minutes"]
        if excess <= 0:
            continue
        c = pi.C_list.index(v["course"])
        cand = [l for l, info in L2.items()
                if info["c"] == c and Verifier._len_minutes_clean(info["slot"]) == excess]
        if cand:
            del L2[cand[-1]]
            deleted += 1
        else:
            unmatched += 1
    return L2, deleted, unmatched


def checks_after_deletion(pi: Any, L: Dict[int, Dict[str, Any]], report: Any) -> Dict[str, Any]:
    """Every check (V, exact room assignment, 15-minute break, PR5) on the
    sample as returned when it has V = 0, and after :func:`delete_surplus`
    when it places surplus lessons; other samples stay as they are."""
    from etpmachine import ETPMachine_Verifier as Verifier
    over = any(v["scheduled_minutes"] > v["required_minutes"]
               for v in report.hard_violations.get("PR1_course_minutes", []))
    V = report.total_violations()
    if not over and V > 0:
        return {"full": False, "surplus_deleted": 0, "surplus_unmatched": 0,
                "V_after_deletion": V, "full_after_deletion": False}
    L2, deleted, unmatched = delete_surplus(pi, L, report) if over else (L, 0, 0)
    after = Verifier.verify_solution(pi, L2, include_per_lesson=False, check_rooms=True)
    full_after = after.statuses()["full"] is True
    return {"full": full_after if not over else False, "surplus_deleted": deleted,
            "surplus_unmatched": unmatched, "V_after_deletion": after.total_violations(),
            "full_after_deletion": full_after}


def topk_table(calls: pd.DataFrame, k: int) -> tuple:
    """The K lowest-energy distinct samples of each call, decoded and checked;
    and how the lowest-energy one and the one with the fewest violations
    among them break (:func:`violation_breakdown`)."""
    import numpy as np
    from scipy.stats import spearmanr
    import benchmark_pipeline as BP
    from etpmachine import ETPMachine_QUBO as QUBOModule
    from etpmachine import ETPMachine_Verifier as Verifier
    from etpmachine.qubo_io import load_qubo_headline_from_h5, load_x_index_from_h5
    rows, breakdown, models = [], [], {}
    for n, r in enumerate(calls.itertuples(index=False), 1):
        key = (r.setting, r.instance)
        if key not in models:
            cache = ROOT / r.setting / "caches" / f"{r.instance}.qubo_cache.h5"
            pi = BP.setup_instance(str(INSTANCES / f"{r.instance}.yaml"))
            head = load_qubo_headline_from_h5(cache)
            shell = QUBOModule.QUBO()
            shell.Q, shell.n_vars, shell.constant = {}, head["n_vars"], head["constant"]
            models = {key: (pi, QUBOModule.TimeAllocationQUBO.from_cache(pi, shell, load_x_index_from_h5(cache)),
                            head["n_vars"])}
        pi, model, n_vars = models[key]
        prefix = ROOT / r.setting / f"rep_{r.rep}" / r.instance
        data = QUBOModule.load_sampleset(f"{prefix}_veloxq_samples_phase2.npz")
        order = np.argsort(data["energy"], kind="stable")[:k]
        index = np.array([int(label) for label in data["labels"]])
        found, reports, timetables = [], [], []
        for rank, i in enumerate(order, 1):
            state = np.zeros(n_vars, dtype=np.int8)
            state[index] = data["states"][i]
            L = model.decode(state.tolist())
            rep = Verifier.verify_solution(pi, L, include_per_lesson=False, check_rooms=False)
            found.append((rank, float(data["energy"][i]), int(rep.total_violations()), len(L)))
            reports.append(rep)
            timetables.append(L)
        ranks, energies, vs, placed = zip(*found)
        best_v = min(vs)
        best = vs.index(best_v)
        rho = spearmanr(energies, vs).correlation if len(set(vs)) > 1 else None
        rows.append({"setting": r.setting, "instance": r.instance, "tier": r.tier, "rep": r.rep,
                     "k": len(found), "V_lowest_energy": vs[0], "lessons_lowest_energy": placed[0],
                     "lowest_V_in_k": best_v, "rank_of_lowest_V": ranks[best],
                     "lessons_at_lowest_V": placed[best],
                     "n_V0_in_k": sum(1 for v in vs if v == 0),
                     "rank_correlation_energy_V": None if rho is None else round(float(rho), 3)})
        for sample, j in (("lowest energy", 0), (f"fewest violations among the {k} lowest", best)):
            breakdown.append({"setting": r.setting, "instance": r.instance, "tier": r.tier, "rep": r.rep,
                              "sample": sample, "rank": ranks[j], "V": vs[j], "lessons_placed": placed[j],
                              "lessons_needed": r.lessons_needed, **violation_breakdown(reports[j]),
                              **checks_after_deletion(pi, timetables[j], reports[j])})
        if n % 25 == 0:
            print(f"  top-{k}: {n}/{len(calls)} calls", flush=True)
    return pd.DataFrame(rows), pd.DataFrame(breakdown)


def breakdown_tiers(breakdown: pd.DataFrame) -> pd.DataFrame:
    """Per setting, tier and sample: the share of calls breaking each rule
    family and the mean number of its violations per call."""
    rows = []
    for (setting, tier, sample), g in breakdown.groupby(["setting", "tier", "sample"], observed=True, sort=False):
        row = {"setting": setting, "tier": tier, "sample": sample, "calls": len(g),
               "share_V0": round(float((g["V"] == 0).mean()), 3), "median_V": float(g["V"].median()),
               "share_all_checks": round(float(g["full"].mean()), 3),
               "share_all_checks_after_deletion": round(float(g["full_after_deletion"].mean()), 3),
               "mean_surplus_deleted": round(float(g["surplus_deleted"].mean()), 2)}
        for f in FAMILIES:
            row[f"share_{f}"] = round(float((g[f] > 0).mean()), 3)
        row["share_PR1_over"] = round(float((g["PR1_courses_over"] > 0).mean()), 3)
        row["share_PR1_under"] = round(float((g["PR1_courses_under"] > 0).mean()), 3)
        for f in FAMILIES + PR1_DETAIL:
            row[f"mean_{f}"] = round(float(g[f].mean()), 2)
        rows.append(row)
    table = pd.DataFrame(rows)
    table["tier"] = pd.Categorical(table["tier"], TIER_ORDER, ordered=True)
    return table.sort_values(["sample", "tier", "setting"], ascending=[False, True, True])


def tier_view(calls: pd.DataFrame, topk: pd.DataFrame, breakdown: pd.DataFrame) -> pd.DataFrame:
    """Per tier, the settings side by side (see the module docstring)."""
    rows = []
    for (setting, tier), g in calls.groupby(["setting", "tier"], observed=True):
        t = topk[(topk["setting"] == setting) & (topk["tier"] == tier)]
        b = breakdown[(breakdown["setting"] == setting) & (breakdown["tier"] == tier)]
        feasible = g[g["V"] == 0]

        def valid(sample: str, column: str) -> int:
            s = b[b["sample"].str.startswith(sample)]
            return int(s.groupby("instance")[column].max().sum())

        rows.append({
            "tier": tier, "setting": setting, "instances": g["instance"].nunique(),
            "instances_V0_lowest_energy": int((g.groupby("instance")["V"].min() == 0).sum()),
            "instances_V0_fewest_violations_in_k": int((t.groupby("instance")["lowest_V_in_k"].min() == 0).sum()),
            "instances_all_checks_lowest_energy": valid("lowest", "full"),
            "instances_all_checks_lowest_energy_after_deletion": valid("lowest", "full_after_deletion"),
            "instances_all_checks_fewest_violations_after_deletion": valid("fewest", "full_after_deletion"),
            "median_V_lowest_energy": float(g["V"].median()),
            "median_V_fewest_violations_in_k": float(t["lowest_V_in_k"].median()),
            "median_objective_feasible": (float(feasible["soft_objective"].median())
                                          if "soft_objective" in g and len(feasible) else None),
        })
    view = pd.DataFrame(rows)
    view["tier"] = pd.Categorical(view["tier"], TIER_ORDER, ordered=True)
    return view.sort_values(["tier", "setting"])


def main() -> int:
    global ROOT      # --root: the tables' functions read the files from ROOT
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--settings", nargs="*", help="default: every setting with results")
    ap.add_argument("--top-k", type=int, default=0, help="decode and check the K lowest-energy samples per call")
    ap.add_argument("--no-soft-objective", action="store_true",
                    help="skip the weighted MILP objective of the decoded timetables (faster)")
    ap.add_argument("--root", type=Path, default=ROOT, help="the campaign's files (default: %(default)s)")
    ap.add_argument("--out", type=Path, help="where to write the tables (default: <root>/analysis)")
    args = ap.parse_args()
    ROOT = args.root.resolve()
    settings = args.settings or sorted(p.name for p in ROOT.iterdir() if p.is_dir() and p.name.startswith("S"))
    out = args.out or ROOT / "analysis"
    out.mkdir(parents=True, exist_ok=True)
    calls = calls_table(settings, with_soft=not args.no_soft_objective)
    if calls.empty:
        print("no saved VeloxQ timetable yet")
        return 0
    calls.to_csv(out / "calls.csv", index=False)
    tiers = tiers_table(calls)
    tiers.to_csv(out / "tiers.csv", index=False)
    print(tiers.to_string(index=False))
    if calls["setting"].nunique() > 1:
        paired_table(calls).to_csv(out / "paired.csv", index=False)
    if args.top_k > 0:
        topk, breakdown = topk_table(calls, args.top_k)
        topk.to_csv(out / "topk.csv", index=False)
        breakdown.to_csv(out / "breakdown.csv", index=False)
        by_tier = breakdown_tiers(breakdown)
        by_tier.to_csv(out / "breakdown_tiers.csv", index=False)
        view = tier_view(calls, topk, breakdown)
        view.to_csv(out / "tier_view.csv", index=False)
        better = (topk["lowest_V_in_k"] < topk["V_lowest_energy"]).mean()
        print(f"top-{args.top_k}: in {better:.0%} of the calls a sample other than the lowest-energy one has "
              f"fewer violations; median rank correlation of energy and V "
              f"{topk['rank_correlation_energy_V'].dropna().median()}")
        print("\nPer tier, the settings side by side:")
        print(view.to_string(index=False))
        print("\nShare of calls breaking each rule family (lowest-energy sample):")
        cols = [f"share_{f}" for f in FAMILIES] + ["share_PR1_over", "share_PR1_under"]
        low = by_tier[by_tier["sample"] == "lowest energy"].set_index(["tier", "setting"])[cols]
        print(low.rename(columns=lambda c: c[len("share_"):]).to_string())
    print(f"written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
