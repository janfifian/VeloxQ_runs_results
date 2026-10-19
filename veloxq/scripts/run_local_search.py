"""
CLI driver for the LocalSearch heuristic (H1 + H2).

Two operating modes:

1. **Single-instance mode** — one ``--instance-yaml`` + one
   ``--input-solution`` → improved ``<output-prefix>_postLS.yaml`` +
   ``<output-prefix>_stats.json`` + ``<output-prefix>_log.txt``.

   ::

       python scripts/run_local_search.py \\
           --instance-yaml artifacts/3studies/3_studies_instance.yaml \\
           --input-solution artifacts/real_instance_velox_run/nsteps20000_nreps4096/3_studies_instance_velox_solution.yaml \\
           --qubo-cache       artifacts/3studies/3_studies_instance.qubo_cache.h5 \\
           --output-prefix    artifacts/local_search_results/3studies_velox_n20k_r4k \\
           --ks 2 --max-outer-passes 5 --max-wall-seconds-per-pass 300 \\
           --candidate-shortlist-k 10 --verbose

2. **Sweep mode** — walk every ``*_solution.yaml`` (suffix configurable)
   in ``--solution-dir``, match it against the matching ``*.yaml`` in
   ``--instance-dir`` by basename, write per-pair outputs into
   ``--output-dir``, plus an aggregate ``sweep_summary.csv`` at the
   output-dir root.

   ::

       python scripts/run_local_search.py \\
           --instance-dir   artifacts/generated_instances \\
           --solution-dir   artifacts/velox_param_sweep/nsteps10000_nreps4096 \\
           --output-dir     artifacts/local_search_results/velox_n10k_r4k \\
           --ks 2 --max-outer-passes 3 --max-wall-seconds-per-pass 120

Both modes write the same per-pair outputs:

  * ``<prefix>_postLS.yaml``  — improved schedule (SolutionIO YAML).
  * ``<prefix>_stats.json``   — full per-cycle stats trajectory.
  * ``<prefix>_log.txt``      — wall log of the run.

Sweep mode additionally writes ``sweep_summary.csv`` aggregating
(instance, pre_cost, post_cost, improvement, wall_s) across every pair.

The cost is ``Schedule.cost``: (hard violations, tie-break). By default the
hard violations include the 15-min break and PR5 pairs and the tie-break is the
weighted MILP objective (``--tie-break soft_objective``); ``--tie-break
qubo_energy --no-extra-rules`` gives the cost used before 07.10.2026.
``--room-set-rows`` adds the MILP's room rows per 15-minute cell and room set to
the hard violations (16.10.2026). The settings, the soft objective and the QUBO
decision energy before and after go into the post-LS YAML's metadata and the
summary CSV.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Boot REPOROOT and friends BEFORE importing etpmachine.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pipeline_helpers import setup_environment

REPO_ROOT = Path(__file__).resolve().parent.parent
setup_environment(REPO_ROOT)

from etpmachine.ETPMachine_ProblemInstance import ProblemInstance
from etpmachine.ETPMachine_QUBO import TimeAllocationQUBO, QUBO
from etpmachine.ETPMachine_Schedule import Schedule
from etpmachine.ETPMachine_LocalSearch import local_search, LocalSearchStats
from etpmachine.utils import run_record
from etpmachine.qubo_io import (
    load_qubo_cache,
    load_x_index_from_h5,
    load_qubo_headline_from_h5,
)


# ============================================================================
# Helpers
# ============================================================================

SOLUTION_SUFFIX_RE = re.compile(
    r"_(?:velox_solution|QUBO_solution|MIP_solution|postLS)$"
)


def _solution_to_instance_basename(stem: str) -> str:
    """Strip the standard solver/output suffixes so we can map a solution
    file back to its instance YAML. E.g.

      ``easy_000_seed_1000_velox_solution`` → ``easy_000_seed_1000``
      ``easy_000_seed_1000_QUBO_solution``  → ``easy_000_seed_1000``
      ``easy_000_seed_1000_postLS``         → ``easy_000_seed_1000``

    Returns the stem unchanged when no known suffix matches (so we
    silently support unknown layouts; the lookup may simply not find an
    instance and we surface that as a warning).
    """
    return SOLUTION_SUFFIX_RE.sub("", stem)


def _load_qubo_config_yaml(path: Path) -> dict:
    """Load a YAML file like ``cfg/qubo_cfg_3_studies.yaml`` and return
    its ``time_allocation`` section as a plain dict.

    The returned dict is suitable to pass as the ``config=`` kwarg of
    :class:`TimeAllocationQUBO`, which merges it onto the in-code
    fallbacks. So a partial override is fine — the fallbacks fill in
    anything you don't override.
    """
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(
            f"QUBO config at {path}: top-level YAML must be a mapping, "
            f"got {type(data).__name__}"
        )
    return dict(data.get("time_allocation") or {})


def _load_pi_and_qubo(
    instance_path: Path,
    qubo_cache_path: Optional[Path],
    qubo_config_path: Optional[Path] = None,
    *,
    skip_qubo_energy: bool = False,
) -> Tuple[ProblemInstance, TimeAllocationQUBO]:
    """Common loader.

    Three modes, in order of precedence:

    1. ``qubo_config_path`` given — rebuild the QUBO from scratch under
       the YAML config at that path. **Ignores** ``qubo_cache_path``: a
       cache file is bound to whatever config was active when it was
       built, so we can't safely re-use it under a different
       calibration. Slow on large instances (~10-30 s on 3_studies),
       but the only way to evaluate against a different Q matrix.
    2. ``qubo_cache_path`` given and exists — load Q + ``x_index`` from
       the cache. Config used is whatever was active at cache-build time.
    3. Neither given — build the QUBO from scratch with the
       environment-default config (``$CONFIG_QUBO_PATH`` or the in-code
       fallbacks).
    """
    pi = ProblemInstance.from_yaml(str(instance_path))
    pi.rebuild_derived()

    # ---- Feasibility-only shortcut: don't materialise the full Q dict. ----
    # LATO's cache has 449 M edges; the {(int,int): float} form is ~40 GB and
    # OOMs a typical workstation. When the caller only needs violation
    # counts (not energy), we load ONLY the x_index and hand LS a stub
    # QUBO with Q={}. Schedule.skip_energy=True guarantees Q is never touched.
    if skip_qubo_energy:
        if qubo_cache_path is None or not qubo_cache_path.exists():
            raise FileNotFoundError(
                f"--no-qubo-energy requires --qubo-cache to point at an "
                f"existing .h5 with the x_index (needed to decode the "
                f"input solution). Got: {qubo_cache_path}"
            )
        print(f"  [no-qubo-energy] loading x_index only from {qubo_cache_path.name} "
              f"(streaming; ~seconds, not gigabytes) ...", flush=True)
        x_index = load_x_index_from_h5(str(qubo_cache_path))
        headline = load_qubo_headline_from_h5(str(qubo_cache_path))
        n_vars = int(headline["n_vars"])
        stub = QUBO()
        stub.Q = {}
        stub.constant = 0.0
        stub.n_vars = n_vars
        qubo = TimeAllocationQUBO.from_cache(pi, stub, x_index)
        print(f"  [no-qubo-energy] x_index={len(x_index):,d}  "
              f"n_vars={n_vars:,d}  (Q left empty; feasibility-only mode)",
              flush=True)
        return pi, qubo

    if qubo_config_path is not None:
        cfg = _load_qubo_config_yaml(qubo_config_path)
        qubo = TimeAllocationQUBO(pi, config=cfg)
        qubo.build(verbose=False)
        if qubo_cache_path is not None:
            print(f"  [info] --qubo-config given; --qubo-cache "
                  f"({qubo_cache_path.name}) ignored — the cached Q matrix "
                  f"was built under a different config.")
        return pi, qubo

    if qubo_cache_path is not None and qubo_cache_path.exists():
        cached_qubo, cached_x_index, _md = load_qubo_cache(str(qubo_cache_path))
        qubo = TimeAllocationQUBO.from_cache(pi, cached_qubo, cached_x_index)
        return pi, qubo

    qubo = TimeAllocationQUBO(pi)
    qubo.build(verbose=False)
    return pi, qubo


def _write_log(
    log_path: Path,
    instance_path: Path,
    solution_path: Path,
    args: argparse.Namespace,
    stats: LocalSearchStats,
) -> None:
    """Emit a human-readable per-run log alongside the JSON stats."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# LocalSearch run — {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"#",
        f"# instance : {instance_path}",
        f"# solution : {solution_path}",
        f"# args     : {vars(args)}",
        "",
        stats.short_summary(),
        "",
        "Per-cycle trajectory:",
    ]
    for cyc in stats.cycles:
        lines.append(cyc.one_line())
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _cost_report(sched: Schedule) -> dict:
    """The parts of the cost of ``sched``, for the run metadata."""
    out = {
        "violations_time_core": int(sched.n_violations),
        "extra_rule_pairs": dict(sched.extra_violations_by_rule),
        "soft_objective": float(sched.soft_cost),
        "soft_objective_terms": {k: float(v) for k, v in sched.soft_objective_terms.items()},
    }
    if sched.room_set_rows:
        out["room_set_rows_exceeded"] = dict(sched.room_set_violations_by_rule)
    return out


def _decision_energy(sched: Schedule, qubo: TimeAllocationQUBO,
                     skip_qubo_energy: bool) -> Optional[float]:
    """QUBO energy of the decision bits (auxiliary and slack bits 0), or None
    when the Q matrix was not loaded."""
    if skip_qubo_energy:
        return None
    x = sched.to_bitvector(qubo.x_index, n_vars=qubo.qubo.n_vars)
    return float(qubo.qubo.energy(x))


# ============================================================================
# Single-pair runner
# ============================================================================

@dataclass
class PairResult:
    """One row of the sweep summary CSV."""
    instance_stem: str
    instance_path: Path
    solution_path: Path                       # the WINNING candidate after best-of-N selection
    output_prefix: Path
    pre_violations: int                       # first key of the cost (hard violations)
    post_violations: int
    pre_energy: Optional[float]               # QUBO energy of the decision bits (None with --no-qubo-energy)
    post_energy: Optional[float]
    pre_soft_cost: float                      # weighted MILP objective
    post_soft_cost: float
    tie_break: str
    count_extra_rules: bool
    wall_seconds: float
    n_cycles: int
    converged: bool
    # New (P5b): when multiple candidates were considered, this is the
    # full list (not just the winner). Empty list / single-element list
    # when only one candidate was given.
    candidate_count: int = 1
    candidate_paths: List[Path] = field(default_factory=list)


def _pick_best_candidate(
    pi: ProblemInstance,
    qubo: TimeAllocationQUBO,
    sol_paths: List[Path],
    *,
    skip_energy: bool = False,
    schedule_options: Optional[dict] = None,
) -> Tuple[Path, Tuple[int, float], List[Tuple[Path, Tuple[int, float]]]]:
    """For each candidate solution YAML, decode into a Schedule under
    ``qubo`` and read its lex cost (the same cost the search uses). Return
    ``(best_path, best_cost, all_scores)`` where ``all_scores`` is the
    per-candidate ledger.

    Tie-breaks within the lex order are: lexicographic on the
    ``Schedule.cost`` pair, with the FIRST file in the input
    order winning under perfect equality (so call ordering is
    reproducible).
    """
    scored: List[Tuple[Path, Tuple[int, float]]] = []
    for sp in sol_paths:
        sched = Schedule.from_yaml(sp, pi, qubo=qubo, skip_energy=skip_energy,
                                   **(schedule_options or {}))
        scored.append((sp, sched.cost))
    # Sort lex on cost, keep stable order for ties.
    scored_sorted = sorted(scored, key=lambda x: x[1])
    best_path, best_cost = scored_sorted[0]
    return best_path, best_cost, scored


def run_pair(
    pi_path: Path,
    sol_paths: List[Path],
    output_prefix: Path,
    *,
    qubo_cache_path: Optional[Path],
    qubo_config_path: Optional[Path],
    args: argparse.Namespace,
) -> PairResult:
    """Load (instance, candidate-solutions), pick the lex-best
    candidate, run local_search on it, write artefacts.

    ``sol_paths`` is a non-empty list. With a single entry this matches
    the original "process one solution" behaviour; with multiple entries
    the lex-best (lowest hard violations, then lowest tie-break) is
    selected, with the rest noted in the metadata for audit.

    Returns a compact summary row.
    """
    if not sol_paths:
        raise ValueError("run_pair: sol_paths must be non-empty")

    print(f"\n[run_pair] instance     = {pi_path}")
    print(f"[run_pair] candidates    = {len(sol_paths)}")
    print(f"[run_pair] output prefix = {output_prefix}_*")
    if qubo_config_path is not None:
        print(f"[run_pair] qubo cfg      = {qubo_config_path}")

    skip_qubo_energy = bool(getattr(args, "no_qubo_energy", False))
    schedule_options = {
        "tie_break": getattr(args, "tie_break", "soft_objective"),
        "count_extra_rules": not getattr(args, "no_extra_rules", False),
        # PR5 switched off for this run (--no-pr5; LATO).
        "pr5": not getattr(args, "no_pr5", False),
        # The MILP's room-set rows in the first key (--room-set-rows).
        "room_set_rows": bool(getattr(args, "room_set_rows", False)),
    }
    print(f"[run_pair] cost          = (hard violations"
          f"{' incl. break and PR5' if schedule_options['count_extra_rules'] else ''}"
          f"{' and the MILP room-set rows' if schedule_options['room_set_rows'] else ''}, "
          f"{schedule_options['tie_break']})")
    pi, qubo = _load_pi_and_qubo(pi_path, qubo_cache_path, qubo_config_path,
                                 skip_qubo_energy=skip_qubo_energy)

    # ---- Best-of-N candidate selection. ----
    if len(sol_paths) > 1:
        sol_path, _best_cost, scored = _pick_best_candidate(
            pi, qubo, sol_paths, skip_energy=skip_qubo_energy,
            schedule_options=schedule_options,
        )
        # Show top-3 for transparency.
        for i, (p, c) in enumerate(sorted(scored, key=lambda x: x[1])[:3]):
            marker = "★" if p == sol_path else " "
            print(f"  {marker} candidate {p.name:60s}  cost={c}")
        if len(scored) > 3:
            print(f"    … and {len(scored) - 3} more")
        print(f"[run_pair] selected      = {sol_path.name}")
    else:
        sol_path = sol_paths[0]
        scored = [(sol_path, None)]
        print(f"[run_pair] solution      = {sol_path}")

    sched = Schedule.from_yaml(sol_path, pi, qubo=qubo,
                               skip_energy=skip_qubo_energy, **schedule_options)
    pre_cost = sched.cost
    pre_soft = sched.soft_cost
    pre_report = _cost_report(sched)
    # Energy from the bit vector, not `sched.energy`: reading that would build
    # the Q-adjacency view and make every move of the search update it.
    pre_energy = _decision_energy(sched, qubo, skip_qubo_energy)

    # Optional per-cycle YAML dumps: <prefix>_after_<n>_<name>.yaml after
    # every H1/H2 cycle. Useful for LATO-scale debugging when we want to
    # see which specific classes moved between cycles.
    on_cycle_complete = None
    if getattr(args, "dump_per_cycle", False):
        _dump_counter = {"n": 0}

        def _sanitize(name: str) -> str:
            return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)

        def _dump(sched_ref, cyc_ref) -> None:
            _dump_counter["n"] += 1
            idx = _dump_counter["n"]
            fname = (
                output_prefix.with_suffix("").as_posix()
                + f"_after_{idx:02d}_{_sanitize(cyc_ref.name)}.yaml"
            )
            md = {
                "cycle": cyc_ref.to_dict(),
                "note":  "per-cycle intermediate dump (--dump-per-cycle)",
                "source_solution": str(sol_path),
                "source_instance": str(pi_path),
            }
            try:
                sched_ref.to_yaml(fname, metadata=md)
                print(f"  [dump] wrote {Path(fname).name}", flush=True)
            except Exception as exc:                # noqa: BLE001
                print(f"  [dump] failed for {fname}: {exc!r}", flush=True)

        on_cycle_complete = _dump

    sched, stats = local_search(
        pi, sched,
        ks                       = tuple(args.ks),
        max_outer_passes         = args.max_outer_passes,
        max_wall_seconds_per_pass= args.max_wall_seconds_per_pass,
        candidate_shortlist_k    = args.candidate_shortlist_k,
        disable_unschedule       = args.disable_unschedule,
        first_improvement        = not args.no_first_improvement,
        skip_h1                  = args.skip_h1,
        skip_k_opt               = args.skip_k_opt,
        enable_pr3_pr4_purge     = args.enable_pr3_pr4_purge,
        targeted_first           = bool(getattr(args, "targeted_k_opt_first", False)),
        targeted_only            = bool(getattr(args, "targeted_k_opt_only", False)),
        targeted_max_per_violation
            = int(getattr(args, "targeted_max_per_violation", 50)),
        targeted_max_blockers_per_deficit
            = int(getattr(args, "targeted_max_blockers_per_deficit", 10)),
        verbose                  = args.verbose,
        return_stats             = True,
        on_cycle_complete        = on_cycle_complete,
    )

    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    post_report = _cost_report(sched)
    post_energy = _decision_energy(sched, qubo, skip_qubo_energy)

    # 1. Improved schedule.
    sched_yaml = output_prefix.with_suffix("").as_posix() + "_postLS.yaml"
    candidate_audit = [
        {"path": str(p), "pre_cost": ([int(c[0]), float(c[1])] if c is not None else None)}
        for (p, c) in scored
    ]
    metadata = {
        "applied_local_search": True,
        "source_instance":      str(pi_path),
        "source_instance_file": run_record.file_identity(pi_path),        # review R16
        "source_solution_file": run_record.file_identity(sol_path),
        "source_solution":      str(sol_path),
        "candidate_count":      len(sol_paths),
        "candidates_considered": candidate_audit,
        "qubo_config":          (str(qubo_config_path) if qubo_config_path else None),
        "qubo_cache":           (str(qubo_cache_path) if qubo_cache_path else None),
        # Code version and every setting of the run (review K10): the
        # command-line arguments include the targeted k-opt limits,
        # shortlist, pass and wall limits, acceptance mode and fallback.
        "environment":          run_record.environment(REPO_ROOT),
        "cli_args":             run_record.json_safe(args),
        "initial_cost":         [int(pre_cost[0]), float(pre_cost[1])],
        "final_cost":           [int(sched.cost[0]), float(sched.cost[1])],
        "cost_definition": {
            "first_key": " + ".join(
                ["time-core violations"]
                + (["break and PR5 pairs"] if schedule_options["count_extra_rules"] else [])
                + (["exceeded MILP room-set rows"] if schedule_options["room_set_rows"] else [])),
            "tie_break": schedule_options["tie_break"],
            "pr5": schedule_options["pr5"],
            "room_set_rows": schedule_options["room_set_rows"],
        },
        "initial": {**pre_report, "qubo_decision_energy": pre_energy},
        "final": {**post_report, "qubo_decision_energy": post_energy},
        "local_search_args":    {
            "ks": list(args.ks),
            "max_outer_passes": args.max_outer_passes,
            "max_wall_seconds_per_pass": args.max_wall_seconds_per_pass,
            "candidate_shortlist_k": args.candidate_shortlist_k,
            "disable_unschedule": args.disable_unschedule,
            "first_improvement": not args.no_first_improvement,
        },
    }
    sched.to_yaml(sched_yaml, metadata=metadata)

    # 2. JSON stats trajectory.
    stats_json = output_prefix.with_suffix("").as_posix() + "_stats.json"
    stats.to_json(stats_json)

    # 3. Plain-text log.
    log_path = Path(output_prefix.with_suffix("").as_posix() + "_log.txt")
    _write_log(log_path, pi_path, sol_path, args, stats)

    print(stats.short_summary())

    return PairResult(
        instance_stem   = pi_path.stem,
        instance_path   = pi_path,
        solution_path   = sol_path,
        output_prefix   = output_prefix,
        pre_violations  = int(pre_cost[0]),
        post_violations = int(sched.cost[0]),
        pre_energy      = pre_energy,
        post_energy     = post_energy,
        pre_soft_cost   = float(pre_soft),
        post_soft_cost  = float(sched.soft_cost),
        tie_break       = schedule_options["tie_break"],
        count_extra_rules = schedule_options["count_extra_rules"],
        wall_seconds    = stats.total_wall_seconds,
        n_cycles        = len(stats.cycles),
        converged       = stats.converged,
        candidate_count = len(sol_paths),
        candidate_paths = list(sol_paths),
    )


# ============================================================================
# Sweep runner
# ============================================================================

def run_sweep(args: argparse.Namespace) -> None:
    """Sweep mode supports ONE or MORE solution dirs.

    With multiple dirs (e.g. one per VeloxQ param combo), all candidate
    solutions for each instance are gathered, the lex-best is picked,
    and local_search runs on the winner. The `candidates_considered`
    list is preserved in the post-LS YAML's metadata for audit.
    """
    inst_dir = args.instance_dir
    sol_dirs = args.solution_dir if isinstance(args.solution_dir, list) else [args.solution_dir]
    out_dir  = args.output_dir
    if not inst_dir.is_dir():
        raise FileNotFoundError(f"--instance-dir not found: {inst_dir}")
    for sd in sol_dirs:
        if not sd.is_dir():
            raise FileNotFoundError(f"--solution-dir not found: {sd}")

    inst_index = {p.stem: p for p in inst_dir.glob("*.yaml")}
    print(f"[sweep] {len(inst_index)} instance(s) found in {inst_dir}")
    print(f"[sweep] {len(sol_dirs)} solution-dir(s) — best-of-N selection per instance "
          f"({'on' if len(sol_dirs) > 1 else 'trivial (single dir)'})")

    # Group candidate solutions by instance basename, across all sol_dirs.
    from collections import defaultdict
    candidates_per_instance: Dict[str, List[Path]] = defaultdict(list)
    n_total = 0
    for sd in sol_dirs:
        matched = sorted(sd.glob(args.solution_glob))
        n_total += len(matched)
        for sol_path in matched:
            inst_basename = _solution_to_instance_basename(sol_path.stem)
            if inst_basename in inst_index:
                candidates_per_instance[inst_basename].append(sol_path)
            else:
                print(f"  [skip] no instance named {inst_basename!r} for "
                      f"{sol_path.name}")
    print(f"[sweep] {n_total} solution file(s) total, "
          f"grouped into {len(candidates_per_instance)} instance(s)")
    if not candidates_per_instance:
        raise FileNotFoundError(
            f"no solutions match {args.solution_glob} under any of {sol_dirs}"
        )

    pairs: List[PairResult] = []
    for inst_basename in sorted(candidates_per_instance):
        sol_paths = sorted(candidates_per_instance[inst_basename])
        inst_path = inst_index[inst_basename]

        output_prefix = out_dir / inst_basename
        cache_guess = inst_dir / f"{inst_basename}.qubo_cache.h5"
        qubo_cache_path = cache_guess if cache_guess.exists() else None

        try:
            pair = run_pair(inst_path, sol_paths, output_prefix,
                            qubo_cache_path=qubo_cache_path,
                            qubo_config_path=args.qubo_config,
                            args=args)
            pairs.append(pair)
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"  [FAILED] pair ({inst_basename}): {exc!r}")

    # Aggregate CSV — extended with candidate_count for best-of-N visibility.
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "sweep_summary.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "instance_stem", "tie_break", "count_extra_rules",
            "pre_violations", "post_violations",
            "pre_soft_cost", "post_soft_cost",
            "pre_energy", "post_energy", "improvement_violations",
            "improvement_soft_cost", "wall_seconds", "n_cycles", "converged",
            "candidate_count", "selected_solution",
            "instance_path", "output_prefix",
        ])
        for r in pairs:
            w.writerow([
                r.instance_stem, r.tie_break, int(r.count_extra_rules),
                r.pre_violations,  r.post_violations,
                r.pre_soft_cost,   r.post_soft_cost,
                r.pre_energy,      r.post_energy,
                r.pre_violations - r.post_violations,
                round(r.pre_soft_cost - r.post_soft_cost, 3),
                round(r.wall_seconds, 3),
                r.n_cycles,
                int(r.converged),
                r.candidate_count, str(r.solution_path),
                str(r.instance_path), str(r.output_prefix),
            ])
    print(f"\n[sweep] aggregate summary: {csv_path}  ({len(pairs)} pairs)")


# ============================================================================
# Argparse and main
# ============================================================================

def _make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_local_search",
        description="Apply LocalSearch (greedy_repair + k_opt) to an existing schedule.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    # ---- Mode: single OR sweep. ----
    p.add_argument("--instance-yaml",  type=Path, default=None,
                   help="(single mode) Path to the ProblemInstance YAML.")
    p.add_argument("--input-solution", type=Path, nargs="+", default=None,
                   help="(single mode) One OR MORE paths to candidate SolutionIO "
                        "YAMLs. When more than one is given, the LEX-BEST candidate "
                        "(lowest violations, then lowest energy under the active "
                        "QUBO) is selected and used as the starting point for "
                        "LocalSearch. The full candidate list is recorded in the "
                        "post-LS YAML's metadata for audit.")
    p.add_argument("--output-prefix",  type=Path, default=None,
                   help="(single mode) Prefix for output files "
                        "(<prefix>_postLS.yaml, <prefix>_stats.json, <prefix>_log.txt).")
    p.add_argument("--qubo-cache",     type=Path, default=None,
                   help="(single mode) Optional .qubo_cache.h5 — avoids rebuilding "
                        "the QUBO from scratch on large instances. NOTE: a cache "
                        "is bound to the config used at cache-build time. To use "
                        "a different calibration, pass --qubo-config instead "
                        "(rebuilds Q on the fly; --qubo-cache is then ignored).")
    p.add_argument("--qubo-config",    type=Path, default=None,
                   help="Path to a QUBO config YAML (e.g. "
                        "cfg/qubo_cfg_3_studies.yaml). When given, the Q matrix "
                        "is rebuilt from scratch using this config — overrides "
                        "the env-default $CONFIG_QUBO_PATH and renders any "
                        "--qubo-cache moot (a cached Q is bound to the config "
                        "active at cache-build time). Works in single AND "
                        "sweep modes; in sweep mode the SAME config is applied "
                        "to every (instance, solution) pair.")

    p.add_argument("--instance-dir",   type=Path, default=None,
                   help="(sweep mode) Directory of *.yaml ProblemInstance files.")
    p.add_argument("--solution-dir",   type=Path, nargs="+", default=None,
                   help="(sweep mode) ONE OR MORE directories of *_solution.yaml "
                        "files. When more than one is given (e.g. one per VeloxQ "
                        "(num_steps, num_rep) param combo), candidate solutions "
                        "for each instance are collected across all directories "
                        "and the lex-best is picked per instance. The CSV column "
                        "`candidate_count` reports how many candidates each "
                        "instance had.")
    p.add_argument("--output-dir",     type=Path, default=None,
                   help="(sweep mode) Per-pair outputs land here + sweep_summary.csv "
                        "at the root.")
    p.add_argument("--solution-glob",  type=str, default="*_solution.yaml",
                   help="(sweep mode) Glob for solution files. Default: "
                        "'*_solution.yaml' matches every solver output.")

    # ---- Algorithm parameters. ----
    p.add_argument("--ks", type=int, nargs="+", default=[1, 2],
                   help="k-OPT neighborhoods to alternate through. "
                        "Default: [1, 2]. The k=1 warmup strips cheap "
                        "single-flip improvements before k=2 attacks the "
                        "harder interaction-driven moves. Pass '--ks 1 2 3' "
                        "to include k=3 as well (slow on production-size "
                        "instances; shrink --candidate-shortlist-k accordingly).")
    p.add_argument("--max-outer-passes", type=int, default=None,
                   help="Cap on outer-loop passes. Default: run until cost "
                        "stops changing.")
    p.add_argument("--max-wall-seconds-per-pass", type=float, default=None,
                   help="Per-k_opt-pass wall budget. Default: no cap.")
    p.add_argument("--candidate-shortlist-k", type=int, default=10,
                   help="Best-K candidates per item in k_opt's Cartesian search. "
                        "Default: 10.")
    p.add_argument("--disable-unschedule", action="store_true",
                   help="Forbid k_opt from leaving a placement un-replaced. "
                        "Default: allow (k_opt can decide a placement is "
                        "better removed than relocated).")
    p.add_argument("--no-first-improvement", action="store_true",
                   help="Use best-improvement instead of first-improvement "
                        "in k_opt's inner Cartesian loop.")
    p.add_argument("--skip-h1", action="store_true",
                   help="Skip greedy_repair. Useful when the caller has "
                        "already invoked it.")
    p.add_argument("--skip-k-opt", action="store_true",
                   help="Skip every k_opt cycle. local_search degenerates to "
                        "an H1-only call.")
    p.add_argument("--enable-pr3-pr4-purge", action="store_true",
                   help="After the H1+H2 loop converges, attempt a "
                        "PR3/PR4 purge-and-refill: remove every placement "
                        "involved in a residual group/lecturer overlap, "
                        "then re-run greedy_repair to fill the resulting "
                        "deficits. Trade-or-revert on lex cost. Targets the "
                        "stuck cases diagnosed in notebook §8 where k=2 / "
                        "k=3 cannot find the 3-cycle rotation needed to "
                        "break a pair-collision. No-op when the post-H2 "
                        "schedule has zero PR3/PR4 violations.")

    p.add_argument("--tie-break", choices=["soft_objective", "qubo_energy"],
                   default="soft_objective", dest="tie_break",
                   help="Second key of the cost. soft_objective (default): the "
                        "weighted-sum objective of the time-allocation MILP "
                        "(cfg/planning_cfg.yaml). qubo_energy: the QUBO energy "
                        "of the decision bits with auxiliary and slack bits at "
                        "0, the tie-break used before 07.10.2026.")
    p.add_argument("--no-extra-rules", action="store_true", dest="no_extra_rules",
                   help="Leave the 15-min break and PR5 pairs out of the first "
                        "key and out of the candidate filter (the cost used "
                        "before 07.10.2026). They are still reported.")
    p.add_argument("--no-pr5", action="store_true", dest="no_pr5",
                   help="Switch PR5 off for this run: its pairs are neither counted "
                        "nor avoided (LATO, whose routes run without PR5).")
    p.add_argument("--room-set-rows", action="store_true", dest="room_set_rows",
                   help="Add the room rows of the time-allocation MILP to the first "
                        "key and to the candidate filter: per 15-minute cell and "
                        "room set, the lessons that can only use rooms of the set "
                        "fit in it in number and in seats (Schedule(room_set_rows="
                        "True)). The verifier's room screen pools the rooms of a "
                        "cell and misses these limits. Off by default.")
    p.add_argument("--no-qubo-energy", action="store_true", dest="no_qubo_energy",
                   help="DO NOT materialise the Q matrix from the cache "
                        "(LATO's is ~40 GB as a Python dict). Only `x_index` "
                        "is loaded and `Schedule.energy` returns 0.0. The "
                        "soft-objective tie-break does not need Q; with "
                        "--tie-break qubo_energy, LS accepts only moves that "
                        "strictly decrease the hard violations. Use for very "
                        "large caches that OOM under load_qubo_cache.")
    p.add_argument("--dump-per-cycle", action="store_true", dest="dump_per_cycle",
                   help="After every H1/H2 cycle, dump the current schedule "
                        "as <prefix>_after_NN_<cycle_name>.yaml. Enables "
                        "per-class diffing between cycles for debugging "
                        "where LS decisions differ from what was expected.")
    p.add_argument("--targeted-k-opt-first", action="store_true",
                   dest="targeted_k_opt_first",
                   help="In each k_opt pass, run a violation-aware targeted "
                        "enumerator BEFORE the blind combinations pass. "
                        "Targeted tuples are guaranteed to touch a residual "
                        "violation participant, so they explore the neighbourhood "
                        "that matters first. Any remaining wall budget still goes "
                        "to the blind pass.")
    p.add_argument("--targeted-k-opt-only", action="store_true",
                   dest="targeted_k_opt_only",
                   help="Skip the blind combinations pass entirely; only "
                        "targeted tuples are tried. Fastest option when we "
                        "believe residual violations are exclusively 3-cycle "
                        "shaped and the blind pass adds nothing.")
    p.add_argument("--targeted-max-per-violation", type=int, default=50,
                   dest="targeted_max_per_violation",
                   help="Cap on targeted tuples enumerated PER violation "
                        "participant (default: 50). Bounds enumeration on "
                        "high-V states.")
    p.add_argument("--targeted-max-blockers-per-deficit", type=int, default=10,
                   dest="targeted_max_blockers_per_deficit",
                   help="Cap on candidate BLOCKERS enumerated per PR1 deficit "
                        "course (default: 10). Bounds the (deficit, blocker) "
                        "and (deficit, blocker, blocker) pair/triple counts.")

    p.add_argument("--verbose", action="store_true",
                   help="One-line per-cycle progress to stdout.")
    return p


def main() -> int:
    parser = _make_parser()
    args = parser.parse_args()

    # Resolve which mode the caller picked.
    single_mode = (
        args.instance_yaml is not None
        and args.input_solution is not None
        and args.output_prefix is not None
    )
    sweep_mode = (
        args.instance_dir is not None
        and args.solution_dir is not None
        and args.output_dir is not None
    )
    if single_mode == sweep_mode:
        parser.error(
            "must pass EITHER (--instance-yaml, --input-solution, --output-prefix) "
            "OR (--instance-dir, --solution-dir, --output-dir); got both or neither"
        )

    if single_mode:
        result = run_pair(
            args.instance_yaml,
            args.input_solution,
            args.output_prefix,
            qubo_cache_path=args.qubo_cache,
            qubo_config_path=args.qubo_config,
            args=args,
        )
        # Δ uses the physics convention (final − initial); negative = improvement.
        d_v = result.post_violations - result.pre_violations
        d_s = result.post_soft_cost  - result.pre_soft_cost
        print(
            f"\nimprovement: violations {result.pre_violations} → "
            f"{result.post_violations}  (Δ {d_v:+d}), "
            f"soft objective {result.pre_soft_cost:g} → {result.post_soft_cost:g}  "
            f"(Δ {d_s:+g})  — negative Δ = improvement"
        )
    else:
        run_sweep(args)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
