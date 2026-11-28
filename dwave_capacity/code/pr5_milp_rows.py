#!/usr/bin/env python
"""How many rows PR5 (mixed modality) adds to the time-allocation MILP, without
building the model.

The MILP (ETPMachine_autoplanner.calculate_model_phase2, MIXED-MODALITY-STUDENTS
and MIXED-MODALITY-LECTURERS) writes one row x_i + x_j <= 1 per pair of
candidate placements of a group (once per group that attends both courses) and
per pair of a lecturer's candidates, on the same day, one online and one
in person, with the break (start of the later minus end of the earlier, negative
for overlaps) under 120 minutes. This script builds the candidate placements as
the builders do (lecturer assigned to the course, lecturer available, slot not
longer than the course's weekly hours, an admissible room free in the slot) and
counts those pairs with the same sweep, vectorised.

Expected (08.10.2026): Corrected_lato_3fix -- most of the 131,064,533 rows of
the certification MILP that ran out of memory; 3_studies -- a small share of
its model.

Run:  python checks/pr5_milp_rows.py [instance.yaml ...]   (LATO about 5 min)
"""
from __future__ import annotations

import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from _common import REPO, load_instance

from etpmachine.ETPMachine_QUBO import _all_slots_in_T_indeces_order, _course_allowed_lecturers, clean_length_of_slot

DEFAULT = ["artifacts/3studies/3_studies_instance.yaml", "artifacts/Corrected_lato_3fix.yaml"]
THRESHOLD = 120.0


def candidates(pi):
    slots = _all_slots_in_T_indeces_order(pi)
    allowed = _course_allowed_lecturers(pi)
    available = {}
    for p in pi.P_indeces:
        calendar = pi.P[pi.P_list[p]].weekCalendar
        for t, slot in enumerate(slots):
            available[(p, t)] = bool(calendar.is_available(slot)[0][0])
    free_rooms = [{r for r in pi.R_indeces if pi.R[pi.R_list[r]].weekCalendar.is_available(slot)[0][0]}
                  for slot in slots]
    out = []
    for c in pi.C_indeces:
        hours = pi.C[pi.C_list[c]][0]
        rooms = set(pi.possible_rooms[c])
        for p in allowed.get(c, []):
            for t, slot in enumerate(slots):
                if not available[(p, t)] or hours < clean_length_of_slot(slot.length):
                    continue
                if not (rooms & free_rooms[t]):
                    continue
                out.append((c, p, t))
    return slots, out


def pairs_in(starts, ends, days, remote):
    """Mixed pairs (i < j in start order, same day, break < THRESHOLD)."""
    order = np.lexsort((starts, days))
    s, e, d, r = starts[order], ends[order], days[order], remote[order].astype(np.int64)
    n = len(s)
    if n < 2:
        return 0
    key = d * 10_000.0 + s                   # start order within the day, days apart
    limit = np.searchsorted(key, d * 10_000.0 + e + THRESHOLD, side="left")
    day_end = np.searchsorted(d, d, side="right")
    k = np.minimum(limit, day_end)
    prefix = np.concatenate([[0], np.cumsum(r)])
    lo = np.arange(n) + 1
    hi = np.maximum(k, lo)
    remote_in = prefix[hi] - prefix[lo]
    in_person_in = (hi - lo) - remote_in
    return int(np.where(r == 1, in_person_in, remote_in).sum())


def count(rel):
    t0 = time.time()
    pi = load_instance(rel)
    slots, triples = candidates(pi)
    minute = lambda dt: dt.hour * 60 + dt.minute
    remote_courses = set(pi.C_zdalne or [])
    by_group = defaultdict(list)
    by_lecturer = defaultdict(list)
    groups_of = defaultdict(list)
    for g in pi.G_indeces:
        for c in pi.subjects_from_C_for_g(pi.G[g]):
            groups_of[c].append(g)
    for (c, p, t) in triples:
        row = (minute(slots[t].start_datetime), minute(slots[t].end_datetime),
               slots[t].daynr_start, c in remote_courses)
        by_lecturer[p].append(row)
        for g in groups_of[c]:
            by_group[g].append(row)

    def total(buckets):
        n = 0
        for rows in buckets.values():
            a = np.array(rows, dtype=np.float64)
            n += pairs_in(a[:, 0], a[:, 1], a[:, 2], a[:, 3])
        return n

    n_g, n_p = total(by_group), total(by_lecturer)
    print(f"{rel}: {len(triples):,} candidate placements, {len(remote_courses)} online courses; "
          f"PR5 rows: groups {n_g:,} + lecturers {n_p:,} = {n_g + n_p:,}  ({time.time() - t0:.0f} s)",
          flush=True)


def main():
    for rel in sys.argv[1:] or DEFAULT:
        count(rel)


if __name__ == "__main__":
    main()
