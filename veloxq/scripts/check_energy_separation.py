#!/usr/bin/env python
"""Where the VeloxQ samples lie relative to the best legal timetable (16.10.2026).

For every instance whose weighted MILP was solved to proven optimality (the campaign of
``scripts/run_milp_campaign.py``) and every setting of the VeloxQ campaign, the optimal
timetable's QUBO energy E_opt: its decision bits with every auxiliary bit (slack, linking,
idle-time markers) at the value that minimises the energy, on the matrix VeloxQ solved. A legal
timetable pays no penalty, so E_opt equals its weighted MILP objective (checked), and no legal
timetable lies below E_opt. Written to ``<out>/``:

``energy_separation.csv``
    per call: E_opt; the lowest sample's energy as returned (E_best) and with its auxiliary bits
    at their best (E_best_completed); their difference (the energy VeloxQ left in the
    auxiliary bits); E_best_completed - E_opt; the verdicts of the lowest sample; and how many
    of the call's samples have an energy below E_opt (none can be a legal timetable).
``optimum_neighbours.csv`` (``--neighbours``)
    per instance and setting: every timetable one move from the optimum -- one candidate lesson
    added (illegal: every course already has its hours) or one of its lessons moved to another
    candidate placement -- classified by every check of the verifier, exact room assignment
    included, with its energy above E_opt: the legal ones' range, the cheapest illegal one, how
    many illegal ones lie below the most expensive legal one, and how many below E_opt.

Read-only on the campaign's files. Needs the project's code (decoder, compiler, verifier, Gurobi
for the exact room assignment).

Usage:
    python scripts/check_energy_separation.py
    python scripts/check_energy_separation.py --neighbours easy_003_seed_1030 medium_005_seed_1050
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

import benchmark_pipeline as BP  # noqa: E402,F401  (loads the environment)
import h5py  # noqa: E402
from analyze_veloxq_campaign import delete_surplus  # noqa: E402,F401
from run_penalty_scenarios import SCENARIOS  # noqa: E402
from etpmachine import ETPMachine_DataLoader as DataLoader  # noqa: E402
from etpmachine import ETPMachine_QUBO as QUBOModule  # noqa: E402
from etpmachine import ETPMachine_Verifier as Verifier  # noqa: E402
from etpmachine.ETPMachine_ProblemInstance import ProblemInstance  # noqa: E402
from etpmachine.ETPMachine_Schedule import Schedule  # noqa: E402

INSTANCES = REPO / "repository_ready" / "instances" / "synthetic"
TIERS = ("easy", "medium", "hard", "extreme")


def milp_optima(root: Path) -> Dict[str, Path]:
    """The optimal timetables, by instance; runs repeated at the tag come first, the superseded
    first runs (same code, an earlier commit of the notes) fill the rest."""
    out: Dict[str, Path] = {}
    for tier in TIERS:
        for p in sorted((root / tier).glob("*_MIP_solution.yaml")) + \
                sorted((root / "superseded" / tier).glob("*_MIP_solution.yaml")):
            out.setdefault(p.name[: -len("_MIP_solution.yaml")], p)
    return out


def qubo_arrays(cache: Path) -> tuple:
    with h5py.File(cache, "r") as f:
        g = f["qubo"]
        return (int(g.attrs["n_vars"]), float(g.attrs["constant"]), g["Q_i"][:].astype(np.int64),
                g["Q_j"][:].astype(np.int64), g["Q_v"][:])


def energy(arr: tuple, x: np.ndarray) -> float:
    return float(np.dot(arr[4], x[arr[2]] * x[arr[3]]) + arr[1])


def energies_of(arr: tuple, X: np.ndarray) -> np.ndarray:
    E = np.full(X.shape[0], arr[1])
    for k in range(0, len(arr[4]), 20000):
        E += (X[:, arr[2][k:k + 20000]] * X[:, arr[3][k:k + 20000]]) @ arr[4][k:k + 20000]
    return E


def build(stem: str, overlay: Dict[str, Any]):
    """The setting's model, built as ``scripts/veloxq_batch.py prepare`` built the matrix VeloxQ
    received (auxiliary completion needs a built model, not one read from the file)."""
    pi = ProblemInstance.from_yaml(str(INSTANCES / f"{stem}.yaml"))
    pi.rebuild_derived()
    pi.apply_to_data_loader(DataLoader, ensure_derived=False)
    model = QUBOModule.TimeAllocationQUBO(pi, config=dict(overlay))
    model.build(verbose=False)
    return pi, model


def completed(model: Any, x: np.ndarray) -> np.ndarray:
    return np.array(model.complete_auxiliaries([int(b) for b in x]), dtype=np.float64)


def setup(root: Path, setting: str, stem: str, plan: Path) -> tuple:
    arr = qubo_arrays(root / setting / "caches" / f"{stem}.qubo_cache.h5")
    pi, model = build(stem, SCENARIOS[setting][1])
    if model.qubo.n_vars != arr[0] or len(model.qubo.Q) != len(arr[4]):
        raise SystemExit(f"{setting} {stem}: the rebuilt model differs from the matrix VeloxQ solved")
    sched = Schedule.from_yaml(plan, pi, qubo=model, skip_energy=True, tie_break="soft_objective",
                               count_extra_rules=True, pr5=True)
    x = np.array(sched.to_bitvector(model.x_index, n_vars=arr[0]), dtype=np.float64)
    if int(x.sum()) != len(sched._placements):
        raise SystemExit(f"{setting} {stem}: a lesson of the optimal timetable has no QUBO bit")
    e_opt = energy(arr, completed(model, x))
    if abs(e_opt - float(sched.soft_cost)) > 1e-6:
        raise SystemExit(f"{setting} {stem}: the optimum pays a penalty ({e_opt} vs objective {sched.soft_cost})")
    return arr, pi, model, x, e_opt


def per_call(root: Path, setting: str, stem: str, plan: Path, calls: Dict[tuple, dict]) -> List[dict]:
    arr, pi, model, x, e_opt = setup(root, setting, stem, plan)
    dec = sorted(model.x_index.values())
    diag = arr[2] == arr[3]
    offset = arr[1] + arr[4][diag].sum() / 2 + arr[4][~diag].sum() / 4     # binary -> spin constant
    rows = []
    for rep in sorted({k[2] for k in calls if k[0] == setting and k[1] == stem}):
        prefix = root / setting / f"rep_{rep}" / stem
        with np.load(f"{prefix}_veloxq_samples_phase2.npz") as z:
            reported = z["energy"].astype(np.float64)
            bits = np.unpackbits(z["bits"], axis=1)[:, : int(z["n_vars"])]
            labels = np.array([int(v) for v in z["labels"]])
        approx = reported + offset                    # VeloxQ reports single-precision spin energies
        margin = np.maximum(8 * 6e-8 * np.abs(reported), 8.0)
        below = int((approx < e_opt - margin).sum())
        band = np.abs(approx - e_opt) <= margin
        if band.any():                                # exact energies where the rounding could decide
            X = np.zeros((int(band.sum()), arr[0]))
            X[:, labels] = bits[band]
            below += int((energies_of(arr, X) < e_opt - 1e-6).sum())
        with np.load(f"{prefix}_veloxq_best_state_phase2.npz") as b:
            xs = np.unpackbits(b["bits"])[: int(b["n_vars"])].astype(np.float64)
        xd = np.zeros(arr[0])
        xd[dec] = xs[dec]
        e_completed = energy(arr, completed(model, xd))
        c = calls[(setting, stem, rep)]
        row = {"setting": setting, "instance": stem, "tier": stem.split("_")[0], "rep": rep,
               "E_opt": e_opt, "E_best": float(c["energy"]), "E_best_completed": e_completed,
               "energy_in_auxiliaries": float(c["energy"]) - e_completed,
               "best_completed_above_opt": e_completed - e_opt,
               "best_V": int(float(c["V"])), "best_all_checks": c["full"] == "True",
               "samples": len(reported), "samples_below_opt": below,
               "reported_energy_step": abs(float(np.spacing(np.float32(reported.min())))),
               "surplus_lessons": 0, "deletion_change_bits_only": None, "deletion_change_completed": None}
        # Surplus lessons of the lowest sample: the energy change of deleting them with every other
        # bit as VeloxQ returned it, and with the auxiliary bits reset to their best.
        L = model.decode(xs.astype(int).tolist())
        L2, deleted, _ = delete_surplus(pi, L, Verifier.verify_solution(pi, L, include_per_lesson=False,
                                                                        check_rooms=False))
        if deleted:
            order = [idx for _k, idx in model.x_index.items() if xs[idx] > 0]    # decode's numbering
            gone = [idx for l, idx in enumerate(order) if l not in L2]
            y = xs.copy()
            y[gone] = 0
            yd = xd.copy()
            yd[gone] = 0
            row.update({"surplus_lessons": deleted, "deletion_change_bits_only": energy(arr, y) - float(c["energy"]),
                        "deletion_change_completed": energy(arr, completed(model, yd)) - e_completed})
        rows.append(row)
    return rows


def neighbours(root: Path, stem: str, plan: Path, settings: List[str]) -> List[dict]:
    verdict: Dict[tuple, dict] = {}          # a move's legality depends on the timetable only
    rows = []
    for setting in settings:
        arr, pi, model, x, e_opt = setup(root, setting, stem, plan)
        keys = list(model.x_index.items())
        by_course: Dict[int, List[int]] = {}
        for (c, _p, _t), i in keys:
            by_course.setdefault(c, []).append(i)
        moves = [("add", None, j) for _k, j in keys if x[j] == 0]
        moves += [("move", i, j) for (c, _p, _t), i in keys if x[i] == 1 for j in by_course[c] if j != i and x[j] == 0]
        legal, illegal = [], []
        for kind, i, j in moves:
            y = x.copy()
            if i is not None:
                y[i] = 0
            y[j] = 1
            if (kind, i, j) not in verdict:
                L = model.decode(y.astype(int).tolist())
                r = Verifier.verify_solution(pi, L, include_per_lesson=False, check_rooms=False)
                fam = {k: len(v) for k, v in {**r.hard_violations, **r.extra_violations}.items() if v}
                if not fam and Verifier.verify_solution(pi, L, include_per_lesson=False,
                                                        check_rooms=True).statuses()["rooms"] is not True:
                    fam = {"no exact room assignment": 1}
                verdict[(kind, i, j)] = fam
            e = energy(arr, completed(model, y)) - e_opt
            (illegal if verdict[(kind, i, j)] else legal).append((e, kind, verdict[(kind, i, j)]))
        legal_e = [m[0] for m in legal]
        illegal.sort(key=lambda m: m[0])
        worst = max(legal_e) if legal_e else float("nan")
        rows.append({"setting": setting, "instance": stem, "tier": stem.split("_")[0], "E_opt": e_opt,
                     "legal": len(legal), "legal_min_above_opt": min(legal_e) if legal_e else None,
                     "legal_max_above_opt": worst if legal_e else None, "illegal": len(illegal),
                     "cheapest_illegal_above_opt": illegal[0][0], "cheapest_illegal_move": illegal[0][1],
                     "cheapest_illegal_breaks": ";".join(f"{k}={v}" for k, v in illegal[0][2].items()),
                     "cheapest_addition_above_opt": min(m[0] for m in illegal if m[1] == "add"),
                     "illegal_below_worst_legal": sum(1 for m in illegal if m[0] < worst),
                     "illegal_below_opt": sum(1 for m in illegal if m[0] < 0)})
        print(f"[neighbours] {setting} {stem}: {len(legal)} legal, {len(illegal)} illegal, cheapest illegal "
              f"{illegal[0][0]:+.1f}, below the worst legal {rows[-1]['illegal_below_worst_legal']}, below the "
              f"optimum {rows[-1]['illegal_below_opt']}", flush=True)
    return rows


def write_csv(path: Path, rows: List[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=REPO / "artifacts" / "campaign" / "veloxq",
                    help="the VeloxQ campaign's files (default: %(default)s)")
    ap.add_argument("--milp", type=Path, default=REPO / "artifacts" / "campaign" / "milp_weighted",
                    help="the MILP campaign's outputs (default: %(default)s)")
    ap.add_argument("--settings", nargs="*", default=sorted(SCENARIOS))
    ap.add_argument("--neighbours", nargs="*", default=[], help="instances for optimum_neighbours.csv")
    ap.add_argument("--out", type=Path, help="default: <root>/analysis")
    args = ap.parse_args()
    out = args.out or args.root / "analysis"
    out.mkdir(parents=True, exist_ok=True)
    plans = milp_optima(args.milp)
    calls = {(r["setting"], r["instance"], int(r["rep"])): r
             for r in csv.DictReader(open(args.root / "analysis" / "calls.csv", encoding="utf-8"))}
    rows = []
    for setting in args.settings:
        for stem, plan in plans.items():
            rows += per_call(args.root, setting, stem, plan, calls)
        print(f"[separation] {setting}: {len([r for r in rows if r['setting'] == setting])} calls on "
              f"{len(plans)} instances; samples below the optimum: "
              f"{sum(r['samples_below_opt'] for r in rows if r['setting'] == setting)}", flush=True)
    write_csv(out / "energy_separation.csv", rows)
    if args.neighbours:
        nrows = []
        for stem in args.neighbours:
            nrows += neighbours(args.root, stem, plans[stem], args.settings)
        write_csv(out / "optimum_neighbours.csv", nrows)
    print(f"written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
