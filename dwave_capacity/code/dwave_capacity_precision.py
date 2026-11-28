#!/usr/bin/env python
"""How much of a compiled QUBO a D-Wave QPU could represent: the Ising
coefficients after the QPU's scaling, against a given control-error level.

A QPU scales the whole problem by one factor so that the fields fit the h range
and the couplings the J range. With the example ranges of D-Wave's documentation
("General QPU Solver Properties": h_range [-4.0, 4.0], j_range [-1.0, 1.0]) the
factor is max(max|h| / 4, max|J| / 1). The script reports, per instance and
encoding, the Ising dynamic range (largest over smallest nonzero |h| or |J|),
the smallest coefficient after scaling, and the share of nonzero coefficients
that fall below the error level (default 0.01: D-Wave's "Errors and Error
Correction" documentation gives integrated control errors of about that size,
for data representative of earlier systems). The QUBO comes from
``scripts/dwave_capacity.py`` (same encodings; ``--qubo-config`` as there).

Run:
  python scripts/dwave_capacity_precision.py --instance repository_ready/instances/synthetic/easy_000_seed_1000.yaml --csv precision.csv
  python scripts/dwave_capacity_precision.py --instance ... --qubo-config penalty_profile=sufficient --csv precision_sufficient.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dwave_capacity as cap  # noqa: E402

H_MAX, J_MAX = 4.0, 1.0


def ising_coefficients(model) -> tuple:
    """Fields h and nonzero couplings J of the Ising form of the model's QUBO
    (x = (1 + s) / 2)."""
    n = model.qubo.n_vars
    h = np.zeros(n)
    J = []
    for (i, j), v in model.qubo.Q.items():
        if i == j:
            h[i] += v / 2.0
        else:
            h[i] += v / 4.0
            h[j] += v / 4.0
            J.append(v / 4.0)
    return h, np.array(J, dtype=float)


def precision_row(model, level: float) -> dict:
    h, J = ising_coefficients(model)
    h_abs = np.abs(h[h != 0.0])
    J_abs = np.abs(J[J != 0.0])
    both = np.concatenate([h_abs, J_abs])
    scale = max(h_abs.max(initial=0.0) / H_MAX, J_abs.max(initial=0.0) / J_MAX)
    scaled = both / scale
    return {
        "nonzero_h": int(h_abs.size), "nonzero_J": int(J_abs.size),
        "ising_dynamic_range": float(both.max() / both.min()),
        "scale_factor": float(scale),
        "smallest_scaled_coefficient": float(scaled.min()),
        "error_level": level,
        "share_below_error_level": float(np.mean(scaled < level)),
        "share_of_J_below_error_level": float(np.mean(J_abs / scale < level)) if J_abs.size else 0.0,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--instance", type=Path, action="append", required=True)
    p.add_argument("--encoding", choices=sorted(cap.ENCODINGS), action="append", default=None)
    p.add_argument("--qubo-config", action="append", default=[], metavar="KEY=VALUE")
    p.add_argument("--error-level", type=float, default=0.01)
    p.add_argument("--csv", type=Path, required=True)
    args = p.parse_args()
    overrides = cap._parse_settings(args.qubo_config)
    encodings = args.encoding or ["default", "presolved", "feasibility"]
    rows = []
    for path in args.instance:
        for encoding in encodings:
            model = cap.compile_qubo(path, encoding, overrides)
            row = {"instance": path.stem, "encoding": encoding,
                   "qubo_config": ";".join(f"{k}={v}" for k, v in overrides.items()),
                   **precision_row(model, args.error_level)}
            rows.append(row)
            print(f"{path.stem} [{encoding}] dynamic range {row['ising_dynamic_range']:.3g}, "
                  f"smallest scaled {row['smallest_scaled_coefficient']:.3g}, "
                  f"below {args.error_level:g}: {row['share_below_error_level']:.1%}", flush=True)
    with open(args.csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"written {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
