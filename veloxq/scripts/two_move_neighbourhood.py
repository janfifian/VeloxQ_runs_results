#!/usr/bin/env python
"""Is a repaired timetable stuck for every 2-move, or only for the repair's shortlist?

The repair (scripts/run_local_search.py: H1, then k-OPT at k = 1, 2) stops when
a full pass leaves its cost unchanged. Its k = 2 pass takes every pair of items
(a lesson, or a course short of its minutes), removes the lessons of the pair,
lists for each item its 10 best places -- best by the cost after that one
placement, with the pair's lessons removed -- plus "leave it out", and tries
every combination. A combination that would reach a valid timetable is missed
when one of its places lies outside these lists.

For a repaired timetable whose only violations are courses short of their
minutes (PR1), this script tries, for each such course D,
  * every 1-move: one more lesson of D at any place the repair's candidate
    filter allows (a place that breaks no rule; others cannot help);
  * every 2-move: remove one lesson P, put a lesson of D at any allowed place,
    and either leave P out or put P's lesson back at any allowed place;
and counts the moves after which the repair's cost has no violation left. Two
lessons moved without D cannot add D's minutes, so no other 2-move can give a
valid timetable. Each such move is then compared with the shortlists the
repair builds for the pair (P, D): if both of its places are on them, the
repair would have taken it, so its stop there would be a bug.

It also says why D has no place: for each of D's candidate places, the lessons
that clash with it (same lecturer or one of D's groups, overlapping or closer
than the 15-minute break or the PR5 break) and whether the room rules (the
pooled screen of the verifier, and the room-set rows if the run used them)
would be broken by D there.

The cost is the run's (time core, 15-minute break, PR5 and, if the run had
--room-set-rows, the MILP's room-set rows), read from the run folder's
settings.json. Only the final timetable is used; nothing is written back.

Usage:
  python checks/two_move_neighbourhood.py --run artifacts/campaign/veloxq_ls/S3_room_set_rows
      (every call of the run's summary.csv that fails a check and has only
      PR1 left; or name calls with --calls rep_3/extreme_014_seed_1142 ...)
  python checks/two_move_neighbourhood.py --run repository_ready/veloxq_synthetic/repair/S3_room_set_rows \\
      --caches repository_ready/veloxq_synthetic          (on the deposit)
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import REPO, quietly  # noqa: E402

SYNTHETIC = REPO / "repository_ready" / "instances" / "synthetic"
CACHES = REPO / "artifacts" / "campaign" / "veloxq"


def place_blockers(sched, c: int, p: int, t: int):
    """(lessons clashing with a lesson of course ``c`` by lecturer ``p`` at slot ``t``, whether the
    room rules would be broken by it) in the current timetable."""
    overlap = sched._slot_overlap.get(t, frozenset())
    clash = {pid for pid in sched._placements_by_p.get(p, ())
             if sched.placements[pid].t == t or sched.placements[pid].t in overlap}
    for g in sched._groups_of_c.get(c, []):
        clash |= {pid for pid in sched._placements_by_g.get(g, ())
                  if sched.placements[pid].t == t or sched.placements[pid].t in overlap}
    if sched.count_extra_rules:
        clash |= set(sched.extra_rule_conflicts(c, p, t))
    rooms = sched._room_rules_would_break(t, sched._eligible_rooms_for_c.get(c, frozenset()),
                                          sched._students_of_c.get(c, 0))
    rooms = rooms or (sched.room_set_rows and sched._room_set_rows_would_break(c, t))
    return clash, rooms


def check_call(run: Path, setting: str, key: str, room_set_rows: bool, shortlist_k: int,
               caches: Path = CACHES) -> dict:
    import run_local_search as rls
    from etpmachine.ETPMachine_LocalSearch import _score_candidates
    from etpmachine.ETPMachine_Schedule import Schedule

    rep, stem = key.split("/")
    pi, qubo = quietly(rls._load_pi_and_qubo, SYNTHETIC / f"{stem}.yaml",
                       caches / setting / "caches" / f"{stem}.qubo_cache.h5", None, skip_qubo_energy=True)
    sched = Schedule.from_yaml(run / rep / f"{stem}_postLS.yaml", pi, qubo=qubo, skip_energy=True,
                               room_set_rows=room_set_rows)
    out = {"call": key, "first_key": sched.n_hard_violations,
           "rules": {k: v for k, v in sched.hard_violations_by_rule.items() if v}}
    deficits = list(sched.deficits())
    if not deficits or out["first_key"] != sum(1 for _ in deficits) or set(out["rules"]) != {"PR1_course_minutes"}:
        out["skipped"] = "not only courses short of their minutes"
        return out
    sched._build_pt_for_c()
    out["short"] = []
    for c, m in deficits:
        places = []
        for p, t in sched._pt_for_c.get(c, []):
            clash, rooms = place_blockers(sched, c, p, t)
            places.append({"lecturer": p, "slot": t, "clashing_lessons": len(clash), "room_rules": rooms})
        out["short"].append({
            "course": c, "missing_minutes": m, "lessons_now": len(sched.placements_of_course(c)),
            "groups": len(sched._groups_of_c.get(c, [])), "students": sched._students_of_c.get(c, 0),
            "places": len(places),
            "places_by_clashing_lessons": dict(sorted(Counter(x["clashing_lessons"] for x in places).items())),
            "places_with_room_rules_broken": sum(x["room_rules"] for x in places)})
    one_moves = two_moves = in_shortlists = opening = 0
    examples = []
    lessons = sorted(sched.placements)
    for d_course, _missing in deficits:
        for p, t in list(sched.candidates_for_course(d_course)):
            pid = sched.add(d_course, p, t)
            one_moves += sched.n_hard_violations == 0
            sched.remove(pid)
        for lesson in lessons:
            pl = sched.placements[lesson]
            snap = sched.snapshot()
            sched.remove(lesson)
            places_d = list(sched.candidates_for_course(d_course))
            opening += bool(places_d)
            shortlist_d = shortlist_p = None
            for p, t in places_d:
                pid_d = sched.add(d_course, p, t)
                if sched.n_hard_violations == 0:          # P left out
                    two_moves += 1
                    if len(examples) < 3:
                        examples.append({"leave_out": [pl.c, pl.p, pl.t], "add": [d_course, p, t]})
                for q, u in list(sched.candidates_for_course(pl.c)):
                    pid_q = sched.add(pl.c, q, u)
                    if sched.n_hard_violations == 0:
                        two_moves += 1
                        sched.remove(pid_q)
                        sched.remove(pid_d)
                        if shortlist_d is None:     # the repair's lists for the pair (P, D)
                            shortlist_d = set(_score_candidates(sched, d_course, shortlist_k))
                            shortlist_p = set(_score_candidates(sched, pl.c, shortlist_k))
                        listed = (p, t) in shortlist_d and (q, u) in shortlist_p
                        in_shortlists += listed
                        if len(examples) < 3:
                            examples.append({"move_lesson": [pl.c, pl.p, pl.t], "add": [d_course, p, t],
                                             "put_back": [pl.c, q, u], "on_the_shortlists": listed})
                        pid_d = sched.add(d_course, p, t)
                    else:
                        sched.remove(pid_q)
                sched.remove(pid_d)
            sched.restore(snap)
    out.update({"lessons": len(lessons), "valid_after_1_move": one_moves,
                "lessons_whose_removal_frees_a_place": opening, "valid_after_2_moves": two_moves,
                "of_them_on_the_repair_shortlists": in_shortlists, "examples": examples})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=Path, required=True, help="run folder of scripts/run_veloxq_ls_campaign.py")
    ap.add_argument("--calls", nargs="*", help="rep_<r>/<instance> (default: failed calls with only PR1 left)")
    ap.add_argument("--out", type=Path, help="write the results as JSON here")
    ap.add_argument("--caches", type=Path, default=CACHES,
                    help="folder with <setting>/caches/<instance>.qubo_cache.h5 (default: artifacts/campaign/veloxq)")
    args = ap.parse_args()
    run = args.run if args.run.is_absolute() else REPO / args.run
    caches = args.caches if args.caches.is_absolute() else REPO / args.caches
    settings = json.loads((run / "settings.json").read_text(encoding="utf-8"))
    setting = settings.get("setting") or run.name
    room_set_rows = "--room-set-rows" in (settings.get("extra") or [])
    calls = args.calls
    if not calls:
        rows = list(csv.DictReader(open(run / "summary.csv", encoding="utf-8")))
        calls = [f"rep_{r['rep']}/{r['instance']}" for r in rows if r["full"] != "True"]
    print(f"{run.name}: setting {setting}, room-set rows {'on' if room_set_rows else 'off'}, "
          f"shortlist {settings['candidate_shortlist_k']}; {len(calls)} call(s)")
    results = []
    for key in calls:
        r = check_call(run, setting, key, room_set_rows, int(settings["candidate_shortlist_k"]), caches)
        results.append(r)
        if "skipped" in r:
            print(f"  {key}: first key {r['first_key']} {r['rules']} -- skipped ({r['skipped']})")
            continue
        for s in r["short"]:
            print(f"  {key}: course {s['course']} short by {s['missing_minutes']} min ({s['lessons_now']} lessons now; "
                  f"{s['groups']} groups, {s['students']} students); its {s['places']} places by number of "
                  f"clashing lessons {s['places_by_clashing_lessons']}, room rules broken at "
                  f"{s['places_with_room_rules_broken']}")
        print(f"  {key}: {r['lessons']} lessons; "
              f"valid after a 1-move {r['valid_after_1_move']}; removing one of "
              f"{r['lessons_whose_removal_frees_a_place']} lessons frees a place; valid after a 2-move "
              f"{r['valid_after_2_moves']} (on the repair's shortlists {r['of_them_on_the_repair_shortlists']})")
        for ex in r["examples"]:
            print(f"      e.g. {ex}")
    if args.out:
        args.out.write_text(json.dumps(results, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
