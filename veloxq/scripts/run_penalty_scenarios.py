#!/usr/bin/env python
"""VeloxQ runs of the penalty scenarios (penalty re-check and review R1).

Every scenario is a QUBO config: the suite's base config (cfg/qubo_cfg.yaml for
the synthetic suite, cfg/qubo_cfg_3_studies.yaml for 3_studies) with an
overlay on its time_allocation section:

  S0  as configured: room rows per 15-minute cell, every row kept, the base penalties
  S1  R1 as the review states it: room_presolve "implied" (rows that cannot be
      exceeded and signature capacity rows implied by their count rows are
      dropped; the clean-room seat rows stay) + room-count coefficient 100
  S2  room_presolve "counts" (also the seat rows dropped: seats left to the
      room stage) + every penalty raised to 1.5 x its requirement where below
  S3  "counts" + sufficient penalties: every penalty = 1.5 x its requirement
  S4  every row kept + sufficient penalties (margin 1.5) except the capacity
      rows, which keep the base coefficient (a sufficient seat-row penalty
      would raise the largest coefficient to ~1e10)
  S5  "counts" + base penalties
  S6  "counts" + sufficient penalties, margin 5

The 2 x 2 core is {S0, S5} x {S4, S3}: rows as configured or presolved, base
or sufficient penalties. (Requirements: etpmachine/utils/penalty_bounds.py,
computed per instance; presolve levels: room_presolve of ETPMachine_QUBO.)

Modes (exactly one):
  --dry-run       the plan: scenarios x instances x repetitions, with the
                  VeloxQ solver time estimated from the archived runs.
                  Touches nothing.
  --build-caches  build the scenarios' QUBO caches locally (no VeloxQ) and
                  print their sizes; writes each scenario's config.
  --launch        submit to VeloxQ: per scenario, instance and repetition,
                  scripts/benchmark_pipeline.py --run-qubo-veloxq with
                  CONFIG_QUBO_PATH set to the scenario's config and the
                  scenario's cache; the job id goes to a sidecar file at
                  submission. A run whose solution file exists is skipped, so
                  an interrupted launch resumes.

Outputs: artifacts/penalty_scenarios/<suite>/<scenario>/config.yaml,
caches/<instance>.qubo_cache.h5, rep_<r>/<instance>_velox_solution.yaml (with
the run record), rep_<r>/<instance>_veloxq_job_id_phase2.txt, rep_<r>/<instance>.log.

Examples:
  python scripts/run_penalty_scenarios.py --suite synthetic --scenarios S0 S3 S4 S5 --reps 3 --dry-run
  python scripts/run_penalty_scenarios.py --suite 3studies --scenarios S0 S3 --build-caches
  python scripts/run_penalty_scenarios.py --suite synthetic --scenarios S3 --tiers easy --reps 3 \\
      --num-steps 10000 --num-rep 4096 --launch
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
OUT_ROOT = REPO / "artifacts" / "penalty_scenarios"
SUITES = {
    "synthetic": dict(config="cfg/qubo_cfg.yaml", instances="artifacts/generated_instances/*.yaml"),
    "3studies": dict(config="cfg/qubo_cfg_3_studies.yaml", instances="artifacts/3studies/3_studies_instance.yaml"),
}
SCENARIOS = {
    "S0": ("as configured", {}),
    "S1": ("presolve (implied) + room-count coefficient 100",
           {"room_presolve": "implied", "Lambda_room_count": 100.0}),
    "S2": ("presolve (counts) + penalties raised to 1.5 x requirement",
           {"room_presolve": "counts", "penalty_profile": "raised", "penalty_margin": 1.5}),
    "S3": ("presolve (counts) + sufficient penalties (margin 1.5)",
           {"room_presolve": "counts", "penalty_profile": "sufficient", "penalty_margin": 1.5}),
    "S4": ("all rows + sufficient penalties (margin 1.5), seat rows base",
           {"penalty_profile": "sufficient", "penalty_margin": 1.5,
            "penalty_profile_keep": ["Lambda_room_capacity"]}),
    "S5": ("presolve (counts), base penalties", {"room_presolve": "counts"}),
    "S6": ("presolve (counts) + sufficient penalties (margin 5)",
           {"room_presolve": "counts", "penalty_profile": "sufficient", "penalty_margin": 5.0}),
}
# Time estimate. VeloxQ's solver time on the archived runs grows with the
# matrix entries: about 4.3e-12 (extreme) to 5.5e-12 (easy) seconds per
# entry x step x replica (median per tier over 2,361 synthetic calls in
# artifacts/velox_recalibrated_75instances and artifacts/velox_param_sweep);
# 3_studies, 274 s for 14.7 M entries at (10000, 512), gives 3.6e-12.
SECONDS_PER_ENTRY_STEP_REP = {"easy": 5.5e-12, "medium": 4.7e-12, "hard": 4.4e-12,
                              "extreme": 4.3e-12, "3_studies": 3.6e-12}
SIZES = REPO / "artifacts" / "penalty_recheck"
# Scenarios that drop every capacity row ("counts") have the size of the
# encoding checks/penalty_sufficiency.py --matrix records as r1_sufficient.
COUNTS_PRESOLVE = {"S2", "S3", "S5", "S6"}


def instances(suite, tiers, names):
    pattern = SUITES[suite]["instances"]
    files = sorted(REPO.glob(pattern)) if "*" in pattern else [REPO / pattern]
    if tiers:
        files = [f for f in files if f.stem.split("_")[0] in tiers]
    if names:
        files = [f for f in files if f.stem in names]
    return files


def scenario_dir(suite, name):
    return OUT_ROOT / suite / name


def write_config(suite, name):
    with open(REPO / SUITES[suite]["config"], encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    description, overlay = SCENARIOS[name]
    cfg["time_allocation"].update(overlay)
    path = scenario_dir(suite, name) / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"# Penalty scenario {name} ({description}); written by scripts/run_penalty_scenarios.py\n"
                 f"# from {SUITES[suite]['config']} + overlay {overlay}\n")
        yaml.safe_dump(cfg, fh, allow_unicode=True, sort_keys=False)
    return path


def matrix_entries(suite, name, stem):
    """Entries of the scenario's matrix: from its cache if built, else from
    the size checks (an upper bound for S1, which keeps the seat rows)."""
    cache = scenario_dir(suite, name) / "caches" / f"{stem}.qubo_cache.h5"
    if cache.exists():
        sys.path.insert(0, str(REPO / "src"))
        from etpmachine.qubo_io import load_qubo_headline_from_h5
        n = load_qubo_headline_from_h5(cache)["metadata"].get("n_q_entries")
        if n:
            return float(n)
    if suite == "3studies":
        log = SIZES / "room_presolve_sizes_3studies.log"
        if log.exists():
            for line in log.read_text(encoding="utf-8").splitlines():
                if line.startswith("matrix entries"):
                    none, _exact, _implied, counts = (float(x.replace(",", "")) for x in line.split()[2:6])
                    return counts if name in COUNTS_PRESOLVE else none
        return None
    table = SIZES / "penalty_sufficiency.csv"
    if table.exists():
        with open(table, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row["instance"] == stem and row.get("current_entries"):
                    key = "r1_sufficient_entries" if name in COUNTS_PRESOLVE else "current_entries"
                    return float(row[key])
    return None


def estimate(suite, name, stem, steps, reps):
    entries = matrix_entries(suite, name, stem)
    if entries is None:
        return None
    tier = "3_studies" if suite == "3studies" else stem.split("_")[0]
    return SECONDS_PER_ENTRY_STEP_REP[tier] * entries * steps * reps


def dry_run(args, files):
    total = 0.0
    print(f"suite {args.suite}: {len(files)} instance(s), {len(args.scenarios)} scenario(s), "
          f"{args.reps} repetition(s), num_steps {args.num_steps}, num_rep {args.num_rep}")
    for name in args.scenarios:
        per_call = [estimate(args.suite, name, f.stem, args.num_steps, args.num_rep) for f in files]
        known = [x for x in per_call if x is not None]
        secs = sum(known) * args.reps
        total += secs
        missing = f"  ({len(per_call) - len(known)} instance(s) without a size: build the caches)" \
            if len(known) < len(per_call) else ""
        print(f"  {name}  {SCENARIOS[name][0]:58s} {len(files) * args.reps:5d} calls  "
              f"~{secs / 60:7.1f} min solver time{missing}")
    print(f"total ~{total / 3600:.1f} h VeloxQ solver time; uploads and queueing come on top")


def build_caches(args, files):
    sys.path.insert(0, str(REPO / "src"))
    from etpmachine.qubo_io import load_qubo_headline_from_h5
    for name in args.scenarios:
        config = write_config(args.suite, name)
        cache_dir = scenario_dir(args.suite, name) / "caches"
        env = {**os.environ, "CONFIG_QUBO_PATH": str(config), "PYTHONIOENCODING": "utf-8"}
        cmd = [sys.executable, str(REPO / "scripts" / "build_qubo_cache.py"),
               *[str(f) for f in files], "--output-dir", str(cache_dir)]
        print(f"[{name}] building {len(files)} cache(s) ...", flush=True)
        subprocess.run(cmd, env=env, cwd=str(REPO), check=True,
                       stdout=subprocess.DEVNULL if not args.verbose else None)
        for f in files:
            head = load_qubo_headline_from_h5(cache_dir / f"{f.stem}.qubo_cache.h5")
            md = head["metadata"]
            print(f"  {name} {f.stem:28s} n_vars {head['n_vars']:9,d}  |Q| {md.get('n_q_entries', 0):12,}",
                  flush=True)


def launch(args, files):
    for name in args.scenarios:
        config = write_config(args.suite, name)
        cache_dir = scenario_dir(args.suite, name) / "caches"
        env = {**os.environ, "CONFIG_QUBO_PATH": str(config), "PYTHONIOENCODING": "utf-8"}
        for rep in range(1, args.reps + 1):
            out_dir = scenario_dir(args.suite, name) / f"rep_{rep}"
            out_dir.mkdir(parents=True, exist_ok=True)
            for f in files:
                prefix = out_dir / f.stem
                if Path(f"{prefix}_velox_solution.yaml").exists():
                    print(f"[{name} rep {rep}] {f.stem}: done, skipping", flush=True)
                    continue
                cache = cache_dir / f"{f.stem}.qubo_cache.h5"
                cmd = [sys.executable, str(REPO / "scripts" / "benchmark_pipeline.py"), str(f),
                       "--run-qubo-veloxq", "--solve-time-stage", "--verify",
                       "--veloxq-backend", args.backend,
                       "--veloxq-num-steps", str(args.num_steps), "--veloxq-num-rep", str(args.num_rep),
                       "--veloxq-problem-name-suffix", f"_{args.suite}_{name}_rep{rep}",
                       "--output-prefix", str(prefix)]
                if cache.exists():
                    cmd += ["--qubo-cache", str(cache)]
                t0 = time.time()
                print(f"[{name} rep {rep}] {f.stem}: submitting ...", flush=True)
                with open(f"{prefix}.log", "w", encoding="utf-8") as log:
                    result = subprocess.run(cmd, env=env, cwd=str(REPO), stdout=log, stderr=subprocess.STDOUT)
                print(f"[{name} rep {rep}] {f.stem}: exit {result.returncode} after {time.time() - t0:.0f} s",
                      flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--suite", choices=sorted(SUITES), required=True)
    parser.add_argument("--scenarios", nargs="+", choices=sorted(SCENARIOS), required=True)
    parser.add_argument("--tiers", nargs="*", default=None, help="synthetic tiers to include (default: all)")
    parser.add_argument("--instances", nargs="*", default=None, help="instance stems to include (default: all)")
    parser.add_argument("--reps", type=int, default=None, help="VeloxQ calls per scenario and instance")
    parser.add_argument("--num-steps", type=int, default=None)
    parser.add_argument("--num-rep", type=int, default=None)
    parser.add_argument("--backend", default="h100-1")
    parser.add_argument("--verbose", action="store_true")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--build-caches", action="store_true")
    mode.add_argument("--launch", action="store_true")
    args = parser.parse_args()
    if (args.dry_run or args.launch) and None in (args.reps, args.num_steps, args.num_rep):
        parser.error("--reps, --num-steps and --num-rep must be given (no defaults: each experiment sets them)")
    files = instances(args.suite, args.tiers, args.instances)
    if not files:
        parser.error("no instance matched")
    if args.dry_run:
        dry_run(args, files)
    elif args.build_caches:
        build_caches(args, files)
    else:
        launch(args, files)


if __name__ == "__main__":
    main()
