#!/usr/bin/env python3
"""
Single source of truth for the paper's generated figures and tables.

Every number that appears in a generated float comes from a CSV under
``artifacts/``; nothing is transcribed by hand. Run from the repo root::

    python3 paper/figures/make_figures.py

Outputs (all written next to this file):

  fig_effort_sweep.pdf        VeloxQ-only feasibility vs solver effort
  fig_frustration.pdf         corrected balance / cycle-frustration profile
  tab_frustration.tex         corrected structural profile (per-tier medians)
  tab_soft_terms.tex          repaired S3 timetables against the MILP optima, term by term
  generated_numbers.tex       \\newcommand macros for in-text numbers
  tab_veloxq_settings.tex     VeloxQ campaign: valid timetables per penalty setting
  tab_veloxq_breakdown.tex    VeloxQ campaign: how the solver's answers break
  tab_veloxq_repair.tex       VeloxQ campaign: the repair of the S3 answers
  tab_veloxq_3studies.tex     S3 on 3_studies: the VeloxQ answers and their repair
                              (artifacts/campaign/veloxq_3studies and _ls)
  generated_numbers_veloxq.tex  in-text numbers of the VeloxQ campaign; these four
                              come from repository_ready/veloxq_synthetic/analysis
                              (alone: make_figures.py --only veloxq-settings)

Consistency guards (the script aborts rather than emitting a stale float):
  * instance sets must agree across sweep configurations;
  * per-tier counts must match the declared manifest;
  * no two columns describing different metrics may be numerically identical.

House style: Okabe-Ito colour-blind-safe palette, vector PDF, serif text
sized to the body font, no chartjunk, direct labelling where it fits.
"""
from __future__ import annotations

import collections
import csv
import json
import statistics as stats
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
ART = ROOT / "artifacts"

TIERS = ("easy", "medium", "hard", "extreme")
MANIFEST = {"easy": 20, "medium": 15, "hard": 20, "extreme": 9}
# The matrices the VeloxQ runs of Section 7.6 submitted, as deposited.
S0_CACHES = ROOT / "repository_ready" / "veloxq_synthetic" / "S0" / "caches"
S3_CACHES = ROOT / "repository_ready" / "veloxq_synthetic" / "S3" / "caches"

# ----------------------------------------------------------------- style
OKABE = {
    "blue":   "#0072B2",
    "orange": "#E69F00",
    "green":  "#009E73",
    "red":    "#D55E00",
    "purple": "#CC79A7",
    "sky":    "#56B4E9",
    "yellow": "#F0E442",
    "grey":   "#666666",
}

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["DejaVu Serif"],
    "font.size": 8.5,
    "axes.titlesize": 9,
    "axes.labelsize": 8.5,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.linewidth": 0.7,
    "xtick.major.width": 0.7,
    "ytick.major.width": 0.7,
    "xtick.direction": "out",
    "ytick.direction": "out",
    "axes.grid": True,
    "grid.color": "#DDDDDD",
    "grid.linewidth": 0.5,
    "grid.alpha": 1.0,
    "axes.axisbelow": True,
    "figure.dpi": 150,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.02,
    "pdf.fonttype": 42,
})

TEXTWIDTH_IN = 4.80  # llncs \textwidth = 347.12pt = 4.80in.
                     # Change this one number when switching document class,
                     # then re-run: the figures resize without restyling.


def die(msg: str) -> None:
    print(f"[make_figures] ABORT: {msg}", file=sys.stderr)
    sys.exit(1)


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        die(f"missing input {path.relative_to(ROOT)}")
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def tier_of(name: str) -> str:
    return name.split("_", 1)[0]


def by_tier(rows, key="instance"):
    out = collections.defaultdict(list)
    for r in rows:
        out[tier_of(r[key])].append(r)
    return out


def med(rows, col):
    return stats.median(float(r[col]) for r in rows)


def iqr(rows, col):
    v = sorted(float(r[col]) for r in rows)
    return np.percentile(v, 25), np.percentile(v, 75)


def fmt(x, nd=0):
    """Half-up rounding (Python's round() is banker's: round(10.5) == 10)."""
    import decimal
    q = decimal.Decimal(1) if nd == 0 else decimal.Decimal(1).scaleb(-nd)
    v = decimal.Decimal(float(x)).quantize(q, rounding=decimal.ROUND_HALF_UP)
    return f"{v:,}".replace(",", "{,}")


def row_decimals(vals):
    """0 decimals if every value is integral, else 1."""
    return 0 if all(abs(v - round(v)) < 1e-9 for v in vals) else 1


# ===================================================================== 1
def load_sweep():
    """VeloxQ parameter sweep -> {(steps, reps): {instance: row}}."""
    files = sorted((ART / "velox_param_sweep").glob("velox_run_nsteps*_nreps*.csv"))
    if not files:
        die("no velox_param_sweep CSVs found")
    grid = {}
    for f in files:
        stem = f.stem
        steps = int(stem.split("nsteps")[1].split("_")[0])
        reps = int(stem.split("nreps")[1])
        grid[(steps, reps)] = {r["preset"]: r for r in read_csv(f)}

    # Guard: use only the instance set common to every configuration, and
    # say out loud what was dropped. Raw per-file sums are not comparable.
    common = set.intersection(*(set(d) for d in grid.values()))
    allnames = set.union(*(set(d) for d in grid.values()))
    dropped = sorted(allnames - common)
    if dropped:
        print(f"[make_figures] sweep: {len(dropped)} instance(s) absent from at "
              f"least one configuration, excluded from all curves: {dropped}")
    # Restrict to the 64-instance paper suite present in generated_instances/
    suite = {p.stem for p in (ART / "generated_instances").glob("*.yaml")}
    if suite:
        common &= suite
    counts = collections.Counter(tier_of(n) for n in common)
    print(f"[make_figures] sweep common instance set: {len(common)} "
          f"({dict(counts)})")
    return grid, sorted(common)


def fig_effort_sweep(grid, names):
    steps_vals = sorted({s for s, _ in grid})
    reps_vals = sorted({r for _, r in grid})
    n = len(names)

    fig, axes = plt.subplots(1, 2, figsize=(TEXTWIDTH_IN, 2.35),
                             gridspec_kw={"width_ratios": [1.15, 1]})

    # -- (a) feasibility vs effort, one curve per num_rep
    ax = axes[0]
    shades = [OKABE["sky"], OKABE["blue"], OKABE["purple"], OKABE["red"]]
    for k, reps in enumerate(reps_vals):
        ys = []
        for s in steps_vals:
            d = grid.get((s, reps))
            ys.append(100.0 * sum(
                1 for nm in names if d[nm]["verifier_feasible"] == "True") / n)
        ax.plot(steps_vals, ys, marker="o", ms=3.2, lw=1.3,
                color=shades[k % len(shades)], label=f"{reps}")
    ax.set_xscale("log")
    ax.set_xlabel(r"solver effort $\mathtt{num\_steps}$ (log)")
    ax.set_ylabel("instances feasible [%]")
    ax.set_ylim(-2, 52)
    ax.set_title("(a) solver-only feasibility vs effort", loc="left")
    leg = ax.legend(title=r"$\mathtt{num\_rep}$", frameon=False,
                    loc="upper left", handlelength=1.4, labelspacing=0.25,
                    borderpad=0.2)
    leg.get_title().set_fontsize(7.5)

    # -- (b) per-tier feasibility at the configuration used in the paper
    ax = axes[1]
    ref = (5000, 4096)
    d = grid[ref]
    tb = collections.defaultdict(lambda: [0, 0])
    for nm in names:
        t = tier_of(nm)
        tb[t][1] += 1
        if d[nm]["verifier_feasible"] == "True":
            tb[t][0] += 1
    xs = np.arange(len(TIERS))
    pct = [100.0 * tb[t][0] / tb[t][1] if tb[t][1] else 0 for t in TIERS]
    bars = ax.bar(xs, pct, width=0.62, color=OKABE["blue"], edgecolor="none")
    for x, t, p in zip(xs, TIERS, pct):
        ax.text(x, p + 2.5, f"{tb[t][0]}/{tb[t][1]}", ha="center",
                va="bottom", fontsize=7.5)
    ax.set_xticks(xs)
    ax.set_xticklabels(TIERS)
    ax.set_ylim(0, 108)
    ax.set_ylabel("instances feasible [%]")
    ax.set_title(r"(b) per tier at $(\mathtt{5000},\mathtt{4096})$", loc="left")

    fig.tight_layout(pad=0.3, w_pad=1.4)
    fig.savefig(HERE / "fig_effort_sweep.pdf")
    plt.close(fig)
    print("[make_figures] wrote fig_effort_sweep.pdf")
    return {t: tuple(tb[t]) for t in TIERS}, steps_vals, reps_vals


# ===================================================================== 2
def fig_and_tab_frustration(rows, rows_s3, prod):
    """``rows`` and ``rows_s3``: the structural profile of the S0 and the S3
    matrices of the 64 synthetic instances; ``prod``: the 3_studies matrix of
    the S3 runs (checks/frustration_from_cache.py)."""
    T = by_tier(rows)
    T3 = by_tier(rows_s3)
    for name, tiers in (("S0", T), ("S3", T3)):
        for t in TIERS:
            if len(tiers[t]) != MANIFEST[t]:
                die(f"frustration: {name} tier {t} has {len(tiers[t])} rows, manifest says "
                    f"{MANIFEST[t]}")

    # Guard: the old bug was a column silently equal to another one.
    for r in rows + rows_s3:
        if abs(float(r["minority_sign_frac"]) - float(r["F_UB_ratio"])) < 1e-12:
            die("minority_sign_frac is identical to F_UB_ratio -- "
                "two different metrics must not coincide")
    if prod.get("setting") != "S3":
        die(f"frustration: the 3_studies row comes from setting {prod.get('setting')}, the "
            "table labels it S3")

    n_bal = sum(1 for r in rows if r["is_balanced"] == "True")

    # ---- figure
    # One panel only: the spanning-tree-gauge residual F_UB is a valid but weak
    # upper bound on the frustration index (weaker than floor(m/2) on every
    # instance), so it is not plotted as a measure.
    fig, ax = plt.subplots(1, 1, figsize=(0.62 * TEXTWIDTH_IN, 2.2))
    xs = np.arange(len(TIERS))

    for i, t in enumerate(TIERS):
        v = [float(r["RF_C"]) for r in T[t]]
        ax.scatter([i] * len(v), v, s=9, color=OKABE["orange"],
                   alpha=0.55, edgecolors="none", zorder=3)
        ax.plot([i - 0.28, i + 0.28], [np.median(v)] * 2, color=OKABE["red"],
                lw=1.8, zorder=4)
    ax.axhline(0.0, color=OKABE["grey"], lw=0.9, ls=":", zorder=2)
    ax.text(3.42, 0.03, "balanced", fontsize=6.8, ha="right",
            va="bottom", color=OKABE["grey"])
    ax.set_xticks(xs)
    ax.set_xticklabels(TIERS)
    ax.set_ylim(-0.06, 1.04)
    ax.set_ylabel(r"$R_F^C$ (breadth-first tree)")
    ax.set_title(r"frustrated fundamental cycles", loc="left")

    fig.tight_layout(pad=0.3)
    fig.savefig(HERE / "fig_frustration.pdf")
    plt.close(fig)
    print("[make_figures] wrote fig_frustration.pdf")

    # ---- table: the S0 tiers, the S3 tiers, then 3_studies (S3)
    L = [r"\begin{tabular}{lrrrrrr}", r"\toprule",
         r"tier & $n$ & $|x|$ & $|Q|_{\mathrm{off}}$ & minority-sign "
         r"& $R_F^C$ (BFS) & balanced \\"]
    for title, tiers in ((r"S0: configured encoding", T),
                         (r"S3: presolve and sufficient penalties", T3)):
        L += [r"\midrule", rf"\multicolumn{{7}}{{@{{}}l}}{{\emph{{{title}}}}} \\"]
        for t in TIERS:
            r = tiers[t]
            nb = sum(1 for x in r if x["is_balanced"] == "True")
            L.append(
                f"{t} & ${len(r)}$ & ${fmt(med(r,'n_vars'))}$ & "
                f"${fmt(med(r,'n_quadratic'))}$ & ${med(r,'minority_sign_frac'):.3f}$ & "
                f"${med(r,'RF_C'):.3f}$ & "
                f"${nb}/{len(r)}$ \\\\")
    L.append(r"\midrule")
    L.append(
        f"\\texttt{{3\\_studies}} (S3) & $1$ & ${fmt(float(prod['n_vars']))}$ & "
        f"${fmt(float(prod['n_edges']))}$ & "
        f"${float(prod['minority_sign_frac']):.3f}$ & "
        f"${float(prod['rfc_bfs_root0']):.3f}$ & "
        f"${1 if prod['is_balanced'] == 'True' else 0}/1$ \\\\")
    L += [r"\bottomrule", r"\end{tabular}"]
    (HERE / "tab_frustration.tex").write_text("\n".join(L) + "\n")
    print("[make_figures] wrote tab_frustration.tex")

    return {
        "prod_afm": float(prod["frac_afm"]),
        "prod_fm": float(prod["frac_fm"]),
        "prod_rfc": float(prod["rfc_bfs_root0"]),
        "prod_balanced": prod["is_balanced"] == "True",
        "n_balanced": n_bal,
        "n_total": len(rows),
        "rfc_lo": min(float(r["RF_C"]) for r in rows),
        "rfc_hi": max(float(r["RF_C"]) for r in rows),
        "fub_lo": min(float(r["F_UB_ratio"]) for r in rows),
        "fub_hi": max(float(r["F_UB_ratio"]) for r in rows),
        "per_tier": {t: (med(T[t], "RF_C"), med(T[t], "F_UB_ratio"))
                     for t in TIERS},
    }


UPLOADED_3STUDIES = "campaign/veloxq_3studies/S3"   # under artifacts/: the S3 runs on 3_studies


def uploaded_cache_sha256(run_dir: Path) -> set:
    """sha256 of the QUBO cache each VeloxQ run record under ``run_dir`` names
    (``qubo_cache_file``): the matrix the solver received."""
    import yaml
    found = set()
    for path in sorted(run_dir.glob("rep_*/*_velox_solution.yaml")):
        with open(path, encoding="utf-8") as fh:
            stack = [(yaml.safe_load(fh) or {}).get("metadata") or {}]
        while stack:
            o = stack.pop()
            if isinstance(o, dict):
                if isinstance(o.get("qubo_cache_file"), dict):
                    found.add(o["qubo_cache_file"].get("sha256"))
                stack.extend(o.values())
            elif isinstance(o, list):
                stack.extend(o)
    return found


def check_uploaded(sha256: str, what: str) -> None:
    """``sha256`` must be the matrix of the S3 runs on 3_studies; without their
    run records (another machine) say so and go on."""
    records = uploaded_cache_sha256(ART / UPLOADED_3STUDIES)
    if not records:
        print(f"[make_figures] {what}: no run records under artifacts/{UPLOADED_3STUDIES}; "
              "not matched against the matrix the solver received")
    elif records != {sha256}:
        die(f"{what}: matrix {sha256[:12]} is not the one the 3_studies runs received "
            f"({', '.join(sorted(s[:12] for s in records))})")


def _frustration_inputs_agree(label, rows, interval, convention):
    """The profile, the interval and the sign census describe the same matrices."""
    prof = {r["instance"]: r for r in rows}
    inter = {r["instance"]: r for r in interval}
    conv = {r["instance"]: r for r in convention}
    if not set(prof) == set(inter) == set(conv):
        die(f"frustration {label}: the profile, the interval and the sign census cover "
            "different instances")
    for name, r in prof.items():
        sizes = {(int(float(r["n_vars"])), int(float(r["n_quadratic"]))),
                 (int(inter[name]["n_vars"]), int(inter[name]["n_edges"])),
                 (int(conv[name]["n_vars"]), int(conv[name]["n_edges"]))}
        if len(sizes) != 1:
            die(f"frustration {label}: {name} has different matrix sizes in the three inputs: {sizes}")
        if (r["is_balanced"] == "True") != (conv[name]["balanced_sigma"] == "True"):
            die(f"frustration {label}: the profile and the sign census disagree on the balance "
                f"of {name}")
        # The prose names the sources of the ferromagnetic couplings.
        if int(conv[name]["fm_other"]):
            die(f"frustration {label}: {name} has ferromagnetic couplings the prose does not name")
    return prof, conv


def frustration_numbers(rows, interval, convention, rows_s3, interval_s3, convention_s3,
                        prod):
    """In-text numbers of the frustration section. ``rows``, ``interval``,
    ``convention``: the structural profile (scripts/run_frustration_analysis_paper.py),
    checks/frustration_interval.py and checks/frustration_convention.py on the S0
    matrices; the ``_s3`` arguments the same on the S3 matrices; ``prod``: the
    3_studies matrix of the S3 runs (checks/frustration_from_cache.py).
    Returns {macro name: value}."""
    import ast
    import math
    prof, conv = _frustration_inputs_agree("S0", rows, interval, convention)
    prof3, conv3 = _frustration_inputs_agree("S3", rows_s3, interval_s3, convention_s3)
    if set(prof) != set(prof3):
        die("frustration: S0 and S3 cover different instances")
    # The prose: S3 keeps the lesson variables and every ferromagnetic coupling
    # (same number from the same sources) and drops antiferromagnetic ones.
    fm_cols = ("fm_lesson_group_slot", "fm_group_slot_group_day", "fm_marker_lesson",
               "fm_marker_marker")
    for name in prof:
        if prof[name]["n_x_decision"] != prof3[name]["n_x_decision"]:
            die(f"frustration: {name} has other lesson variables in S3 than in S0")
        if any(conv[name][c] != conv3[name][c] for c in fm_cols):
            die(f"frustration: {name} has other ferromagnetic couplings in S3 than in S0")
        if int(conv3[name]["n_edges"]) >= int(conv[name]["n_edges"]):
            die(f"frustration: {name} has no fewer couplings in S3 than in S0")
    check_uploaded(prod["cache_sha256"], "frustration, 3_studies row")
    census = [r for r in convention if r["triangles"]]
    if len(census) != 1:
        die(f"frustration: the prose quotes one triangle census, the input has {len(census)}")
    c = census[0]
    tri, frus = int(c["triangles"]), int(c["triangles_frustrated"])
    # The prose says every unfrustrated triangle contains an idle-time marker.
    if int(c["triangles_unfrustrated_with_marker"]) != tri - frus:
        die("frustration: an unfrustrated triangle without an idle-time marker")
    # Section 9 says R_F^C (breadth-first) is highest on easy and lowest on extreme.
    T = by_tier(rows)
    tier_rfc = {t: med(T[t], "RF_C") for t in TIERS}
    if (max(tier_rfc, key=tier_rfc.get), min(tier_rfc, key=tier_rfc.get)) != ("easy", "extreme"):
        die(f"frustration: per-tier R_F^C medians {tier_rfc}; the prose says highest on "
            "easy, lowest on extreme")
    other_trees = [v for r in interval for k, v in ast.literal_eval(r["rfc_by_tree"]).items()
                   if not k.startswith("breadth-first")]
    lower = [float(r["lower_ratio"]) for r in interval]
    upper = [float(r["upper_ratio"]) for r in interval]
    afm = [float(r["frac_afm"]) for r in rows]
    marker = [(int(r["fm_marker_lesson"]) + int(r["fm_marker_marker"])) / int(r["fm_edges"])
              for r in convention]
    lower3 = [float(r["lower_ratio"]) for r in interval_s3]
    upper3 = [float(r["upper_ratio"]) for r in interval_s3]
    vars3 = [float(prof3[n]["n_vars"]) / float(prof[n]["n_vars"]) for n in prof]
    edges3 = [float(prof3[n]["n_quadratic"]) / float(prof[n]["n_quadratic"]) for n in prof]
    return {
        # Certified bounds rounded outwards: the lower bound down, the upper bound up.
        "FrustIdxLowLo": f"{math.floor(100 * min(lower)) / 100:.2f}",
        "FrustIdxLowHi": f"{max(lower):.2f}",
        "FrustIdxUpLo": f"{min(upper):.2f}",
        "FrustIdxUpHi": f"{math.ceil(100 * max(upper)) / 100:.2f}",
        "FrustRFCOtherLo": f"{min(other_trees):.2f}",
        "FrustRFCOtherHi": f"{max(other_trees):.2f}",
        "FrustAFMPctLo": fmt(100 * min(afm)),
        "FrustAFMPctHi": fmt(100 * max(afm)),
        "FrustFMMarkerPctLo": fmt(100 * min(marker)),
        "FrustFMMarkerPctHi": fmt(100 * max(marker)),
        "FrustTriInstance": r"\texttt{" + c["instance"].replace("_", r"\_") + "}",
        "FrustTriTotal": fmt(tri),
        "FrustTriAllAFM": fmt(int(c["triangles_all_afm"])),
        "FrustTriFrustrated": fmt(frus),
        "FrustTriOther": fmt(tri - frus),
        # S3 against S0, and the 3_studies matrix of the S3 runs.
        "FrustSThreeBalanced": str(sum(r["is_balanced"] == "True" for r in rows_s3)),
        "FrustSThreeRFCLo": f"{min(float(r['RF_C']) for r in rows_s3):.2f}",
        "FrustSThreeRFCHi": f"{max(float(r['RF_C']) for r in rows_s3):.2f}",
        "FrustSThreeAFMPctLo": fmt(100 * min(float(r["frac_afm"]) for r in rows_s3)),
        "FrustSThreeAFMPctHi": fmt(100 * max(float(r["frac_afm"]) for r in rows_s3)),
        "FrustSThreeIdxLowLo": f"{math.floor(100 * min(lower3)) / 100:.2f}",
        "FrustSThreeIdxLowHi": f"{max(lower3):.2f}",
        "FrustSThreeIdxUpLo": f"{min(upper3):.2f}",
        "FrustSThreeIdxUpHi": f"{math.ceil(100 * max(upper3)) / 100:.2f}",
        "FrustSThreeVarsPctLo": fmt(100 * min(vars3)),
        "FrustSThreeVarsPctHi": fmt(100 * max(vars3)),
        "FrustSThreeEdgesPctLo": fmt(100 * min(edges3)),
        "FrustSThreeEdgesPctHi": fmt(100 * max(edges3)),
        "ProdVars": fmt(int(prod["n_vars"])),
        "ProdIdxLow": f"{math.floor(100 * float(prod['lower_ratio'])) / 100:.2f}",
        "ProdIdxUp": f"{math.ceil(100 * float(prod['upper_ratio'])) / 100:.2f}",
    }


# ===================================================================== 3
# Soft-cost quality (Section "Soft-cost quality against the MILP optimum"): the
# repaired S3 timetables that pass every check against the MILP optimum of their
# instance, term by term, and the solver's own valid answers before the repair.
# The terms are rebuilt from the verifier's soft metrics with the objective
# weights recorded in the deposited S0 matrices, and must add up to the
# objective that each run recorded.

SOFT_TERMS = [  # (row of the table, key)
    ("lecturer satisfaction", "satisfaction"),
    ("idle minutes", "idle"),
    ("active group-days", "days"),
    ("time of day", "time_of_day"),
]
# The verifier's satisfaction levels and the configuration's names for them.
SATISFACTION_LEVEL = {"high_pref": "preferred", "low_pref": "undesired",
                      "neutral": "neutral", "not_available": "not_available"}
MILP_DEPOSIT = ROOT / "repository_ready" / "milp_synthetic_weighted"


def _soft_terms(metrics: dict, weights: dict) -> dict:
    """The terms of the weighted objective of a timetable (lower is better)."""
    days = metrics["days_per_group"].get("by_group") or {}
    return {
        "satisfaction": -sum(weights["satisfaction_weights"][SATISFACTION_LEVEL[k]] * n
                             for k, n in metrics["lecturer_satisfaction_counts"].items()),
        "idle": float(weights["gamma_gap_per_minute"]) * float(metrics["total_student_gap_minutes"]),
        "days": float(weights["delta_days_per_group"]) * sum(days.values()),
        "time_of_day": sum(float(weights["tod_weights"][k]) * n
                           for k, n in metrics["time_of_day_counts"].items()),
    }


def _objective_weights() -> dict:
    """The weights of the objective, the same in every deposited S0 matrix."""
    keys = ("satisfaction_weights", "tod_weights", "gamma_gap_per_minute",
            "delta_days_per_group", "reward_unit")
    seen = {json.dumps({k: _cache_metadata(f)["config"][k] for k in keys}, sort_keys=True)
            for f in S0_CACHES.glob("*.qubo_cache.h5")}
    if len(seen) != 1:
        die("soft terms: the S0 matrices record different objective weights")
    weights = json.loads(seen.pop())
    if weights["reward_unit"] != "lesson":
        die("soft terms: the rewards are not per lesson, so the verifier's counts do not give them")
    return weights


def _signed(x: float) -> str:
    if x == 0:
        return "$0$"
    text = fmt(abs(x), 0 if float(x).is_integer() else 1)
    return f"${'+' if x > 0 else '-'}{text}$"


def tab_soft_terms() -> dict:
    """Table tab:soft-terms and the numbers of its subsection."""
    import yaml
    weights = _objective_weights()

    def checked(terms, objective, what):
        if abs(sum(terms.values()) - objective) > 1e-6:
            die(f"soft terms: {what}: the terms add up to {sum(terms.values())}, "
                f"the recorded objective is {objective}")
        return terms

    optimum = {}
    files = sorted(MILP_DEPOSIT.glob("*/*_MIP_solution.yaml")) + \
        sorted((MILP_DEPOSIT / "superseded").rglob("*_MIP_solution.yaml"))
    for f in files:
        with open(f, encoding="utf-8") as fh:
            md = yaml.safe_load(fh)["metadata"]
        stem = f.name[: -len("_MIP_solution.yaml")]
        if stem in optimum:
            die(f"soft terms: two MILP optima for {stem}")
        if md["phase2"]["solve_summary"]["status"] != "OPTIMAL":
            die(f"soft terms: {stem} is not solved to optimality")
        optimum[stem] = checked(_soft_terms(md["verifier"]["soft_metrics"], weights),
                                float(md["phase2"]["solve_summary"]["objective"]), stem)
    if set(optimum) != {r["instance"] for r in read_csv(VELOXQ / "analysis" / "energy_separation.csv")}:
        die("soft terms: the MILP optima are not those of the energy separation")

    # Repaired timetables that pass every check, on instances with an optimum.
    repair = read_csv(VELOXQ / "analysis" / "repair_calls.csv")
    diff = collections.defaultdict(lambda: collections.defaultdict(list))
    repaired = {}
    for r in repair:
        if r["setting"] != "S3":
            die(f"soft terms: repair_calls.csv has setting {r['setting']}")
        if r["full"] != "True":
            continue
        repaired[(r["instance"], r["rep"])] = float(r["objective"])
        if r["instance"] not in optimum:
            continue
        verdict = json.loads((VELOXQ / "repair" / "S3_room_set_rows" / f"rep_{r['rep']}"
                              / f"{r['instance']}_postLS_verdict.json").read_text(encoding="utf-8"))
        if verdict["statuses"]["full"] is not True:
            die(f"soft terms: {r['instance']} rep {r['rep']} fails a check in its verdict")
        terms = checked(_soft_terms(verdict["soft_metrics"], weights), float(r["objective"]),
                        f"{r['instance']} rep {r['rep']}")
        opt = optimum[r["instance"]]
        tier = tier_of(r["instance"])
        for key in terms:
            diff[tier][key].append(terms[key] - opt[key])
        diff[tier]["total"].append(sum(terms.values()) - sum(opt.values()))
    tiers = [t for t in TIERS if diff[t]["total"]]
    if tiers != ["easy", "medium", "hard"]:
        die(f"soft terms: tiers with an optimum {tiers}")
    if any(x < 0 for t in tiers for x in diff[t]["total"]):
        die("soft terms: a repaired timetable lies below the MILP optimum")

    L = [r"\setlength{\tabcolsep}{4pt}\small",
         r"\begin{tabular}{@{}l" + "rr" * len(tiers) + "@{}}", r"\toprule",
         " & " + " & ".join(rf"\multicolumn{{2}}{{c}}{{{t} ({len(diff[t]['total'])} calls)}}"
                            for t in tiers) + r" \\",
         "".join(rf"\cmidrule(lr){{{2 + 2 * i}-{3 + 2 * i}}}" for i in range(len(tiers))),
         "term & " + " & ".join(r"$\Delta$ & worse/better" for _ in tiers) + r" \\",
         r"\midrule"]
    for label, key in SOFT_TERMS + [(r"total, $\mathcal{O}$", "total")]:
        if key == "total":
            L.append(r"\midrule")
        cells = []
        for t in tiers:
            v = diff[t][key]
            cells += [_signed(stats.median(v)), f"${sum(x > 0 for x in v)}/{sum(x < 0 for x in v)}$"]
        L.append(f"{label} & " + " & ".join(cells) + r" \\")
    L += [r"\bottomrule", r"\end{tabular}"]
    (HERE / "tab_soft_terms.tex").write_text("\n".join(L) + "\n")
    print("[make_figures] wrote tab_soft_terms.tex")

    # The prose: on the easy tier the calls off the optimum differ only in time of
    # day; on the medium and hard tiers no repaired timetable has more lecturer
    # satisfaction than the optimum.
    for i, total in enumerate(diff["easy"]["total"]):
        if total != 0 and any(diff["easy"][k][i] != 0 for k in ("satisfaction", "idle", "days")):
            die("soft terms: an easy call off the optimum differs in more than time of day")
    if any(x < 0 for t in ("medium", "hard") for x in diff[t]["satisfaction"]):
        die("soft terms: a repaired timetable has more lecturer satisfaction than the optimum")
    if any(x == 0 for x in diff["hard"]["total"]):
        die("soft terms: a hard call reaches the optimum; the text says none does")
    if not all(x > 0 for x in diff["hard"]["satisfaction"]):
        die("soft terms: the text says every hard call has less lecturer satisfaction than the optimum")

    # The solver's own valid answers (S3) before the repair: how far above the
    # optimum, and whether the repair improved every one of them.
    gap = collections.defaultdict(list)
    for c in read_csv(VELOXQ / "analysis" / "calls.csv"):
        if c["setting"] != "S3" or c["full"] != "True" or c["instance"] not in optimum:
            continue
        o = sum(optimum[c["instance"]].values())
        a = float(c["soft_objective"])
        if a < o:
            die(f"soft terms: a valid answer of {c['instance']} lies below the optimum")
        after = repaired.get((c["instance"], c["rep"]))
        if after is None or after >= a:
            die(f"soft terms: the repair did not improve the valid answer {c['instance']} rep {c['rep']}")
        gap[tier_of(c["instance"])].append(100 * (a - o) / abs(o))
    if sorted(gap) != ["easy", "medium"]:
        die(f"soft terms: valid answers on instances with an optimum in tiers {sorted(gap)}")

    count = lambda t, key, sign: sum((x > 0) if sign > 0 else (x < 0) for x in diff[t][key])
    med = lambda t, key: stats.median(diff[t][key])
    return {
        "SoftCallsEasy": str(len(diff["easy"]["total"])),
        "SoftCallsMedium": str(len(diff["medium"]["total"])),
        "SoftCallsHard": str(len(diff["hard"]["total"])),
        "SoftAtOptEasy": str(sum(x == 0 for x in diff["easy"]["total"])),
        "SoftAtOptMedium": str(sum(x == 0 for x in diff["medium"]["total"])),
        "SoftSatWorseMedium": str(count("medium", "satisfaction", 1)),
        "SoftSatMedianMedium": fmt(med("medium", "satisfaction")),
        "SoftSatMedianHard": fmt(med("hard", "satisfaction")),
        "SoftIdleWorseMedium": str(count("medium", "idle", 1)),
        "SoftIdleWorseHard": str(count("hard", "idle", 1)),
        "SoftDaysFewerMedium": str(count("medium", "days", -1)),
        "SoftDaysFewerHard": str(count("hard", "days", -1)),
        "SoftTodBetterHard": str(count("hard", "time_of_day", -1)),
        "SoftAnswerCallsEasy": str(len(gap["easy"])),
        "SoftAnswerCallsMedium": str(len(gap["medium"])),
        "SoftAnswerGapEasy": fmt(stats.median(gap["easy"])),
        "SoftAnswerGapMedium": fmt(stats.median(gap["medium"])),
    }


# ===================================================================== main
def main() -> int:
    grid, names = load_sweep()
    tier_feas, steps_vals, reps_vals = fig_effort_sweep(grid, names)

    frows = read_csv(ART / "qubo_frustration_paper_synth.csv")
    frows_s3 = read_csv(ART / "qubo_frustration_paper_synth_S3.csv")
    prod = read_csv(ART / "frustration_3studies_S3.csv")[0]
    fr = fig_and_tab_frustration(frows, frows_s3, prod)
    fnum = frustration_numbers(frows, read_csv(ART / "frustration_interval_synth.csv"),
                               read_csv(ART / "frustration_convention_synth.csv"),
                               frows_s3, read_csv(ART / "frustration_interval_synth_S3.csv"),
                               read_csv(ART / "frustration_convention_synth_S3.csv"), prod)

    # ---- in-text macros so prose numbers cannot drift from the floats
    ref = (5000, 4096)
    d = grid[ref]
    tot_feas = sum(1 for nm in names if d[nm]["verifier_feasible"] == "True")
    best = max(
        (sum(1 for nm in names if grid[k][nm]["verifier_feasible"] == "True"), k)
        for k in grid if all(nm in grid[k] for nm in names))
    M = [
        r"%% Auto-generated by paper/figures/make_figures.py -- do not edit.",
        rf"\newcommand{{\SweepNInstances}}{{{len(names)}}}",
        rf"\newcommand{{\SweepNConfigs}}{{{len(grid)}}}",
        rf"\newcommand{{\SweepStepsMin}}{{{min(steps_vals)}}}",
        rf"\newcommand{{\SweepStepsMax}}{{{max(steps_vals)}}}",
        rf"\newcommand{{\SweepRepsMin}}{{{min(reps_vals)}}}",
        rf"\newcommand{{\SweepRepsMax}}{{{max(reps_vals)}}}",
        rf"\newcommand{{\AnnealerFeasRef}}{{{tot_feas}}}",
        rf"\newcommand{{\AnnealerFeasBest}}{{{best[0]}}}",
        rf"\newcommand{{\AnnealerFeasBestCfg}}{{({best[1][0]},{best[1][1]})}}",
    ]
    for t in TIERS:
        k, n = tier_feas[t]
        M.append(rf"\newcommand{{\AnnealerFeas{t.capitalize()}}}{{{k}/{n}}}")
    # Failure mode of the raw synthetic samples at the reference configuration.
    # The prose says every course's minutes are scheduled and every remaining
    # violation is a lecturer or student-group clash; fail loudly if not.
    clash_cols = ("viol_PR3_PR4_lecturer_overlap", "viol_PR3_PR4_group_overlap")
    for nm in names:
        v = int(float(d[nm]["verifier_n_violations"]))
        c = sum(int(float(d[nm][col])) for col in clash_cols)
        if int(float(d[nm]["viol_PR1_course_minutes"])) != 0 or v != c:
            die(f"raw sample of {nm} at {ref} is not clash-only (V={v}, clashes={c})")
    for t in ("hard", "extreme"):
        vs = [int(float(d[nm]["verifier_n_violations"])) for nm in names
              if tier_of(nm) == t]
        med = stats.median(vs)
        if med != int(med):
            die(f"median raw V on {t} tier is not an integer: {med}")
        M.append(rf"\newcommand{{\RawClash{t.capitalize()}}}{{{int(med)}}}")
    M += [
        rf"\newcommand{{\FrustBalanced}}{{{fr['n_balanced']}}}",
        rf"\newcommand{{\FrustTotal}}{{{fr['n_total']}}}",
        rf"\newcommand{{\FrustRFCLo}}{{{fr['rfc_lo']:.2f}}}",
        rf"\newcommand{{\FrustRFCHi}}{{{fr['rfc_hi']:.2f}}}",
        rf"\newcommand{{\FrustFUBLo}}{{{fr['fub_lo']:.2f}}}",
        rf"\newcommand{{\FrustFUBHi}}{{{fr['fub_hi']:.2f}}}",
    ]
    M += [rf"\newcommand{{\{k}}}{{{v}}}" for k, v in fnum.items()]
    # The prose says the production instance is not balanced either.
    if fr["prod_balanced"]:
        die("frustration: the 3_studies matrix is balanced; the prose says it is not")
    M += [
        rf"\newcommand{{\ProdAFM}}{{{fr['prod_afm']:.3f}}}",
        rf"\newcommand{{\ProdFM}}{{{fr['prod_fm']:.3f}}}",
        rf"\newcommand{{\ProdRFC}}{{{fr['prod_rfc']:.2f}}}",
    ]
    # Soft-cost quality of the repaired timetables against the MILP optima.
    M += [rf"\newcommand{{\{k}}}{{{v}}}" for k, v in tab_soft_terms().items()]
    # Main benchmark run (seeds handed to the repair stage), kept apart from the
    # effort-sweep numbers above.
    n_main, pre_main, post_main = fig_synth_feasibility()
    M.append(rf"\newcommand{{\MainFeasPre}}{{{sum(pre_main.values())}}}")
    M.append(rf"\newcommand{{\MainFeasPost}}{{{sum(post_main.values())}}}")
    for t in TIERS:
        M.append(rf"\newcommand{{\MainFeas{t.capitalize()}}}{{{pre_main[t]}/{n_main[t]}}}")
    M += [rf"\newcommand{{\{k}}}{{{v}}}" for k, v in tab_veloxq_3studies().items()]
    # Sections 4 and 6: matrices of the VeloxQ runs, Table 2 and the census.
    census = read_csv(ART / "qubo_family_census.csv")
    for numbers in (tab_penalty_sufficiency(), section4_numbers(), census_numbers(census),
                    milp_campaign_numbers(), prod_presolve_numbers(),
                    prod_pr5_numbers(), qpu_numbers(), margin_numbers()):
        M += [rf"\newcommand{{\{k}}}{{{v}}}" for k, v in numbers.items()]
    (HERE / "generated_numbers.tex").write_text("\n".join(M) + "\n")
    fig_family_census(census)
    fig_sparsity()
    tab_lambdas()
    tab_veloxq_settings()
    fig_vqls_vs_milp()
    fig_lato_time_of_day()
    print("[make_figures] wrote generated_numbers.tex")
    print("[make_figures] done.")
    return 0




# ===================================================================== 5b
# Penalty sufficiency: the configured penalty over the value it must exceed,
# smallest over each tier's instances. Both are read from the matrices of the
# VeloxQ runs, whose metadata records the configuration and the requirements of
# etpmachine.utils.penalty_bounds: on the synthetic suite the deposited S0
# matrices; on 3_studies the requirements in the matrix of its S3 runs, against
# the configured coefficients of the base configuration those runs name
# (setting.json). A clash pays the non-overlap penalty once per grid cell the
# two lessons share, at least as many as checks/clash_cells.py finds, while the
# requirement is stated for one cell; the table gives the cost of a clash.

SUFFICIENCY_ROWS = [
    (r"$\Lambda_1$", "PR1 course hours", "Lambda_PR1"),
    (r"$\Lambda_2$", "MC chunk limit", "Lambda_MC"),
    (r"$\Lambda_3$", "PR3/PR4 non-overlap, per clash", "Lambda_nonoverlap"),
    (r"$\Lambda_4$", "PR5 mixed modality", "Lambda_mix"),
    (r"$\Lambda_5$", "ST room count", "Lambda_room_count"),
    (r"$\Lambda_5$", "ST room capacity (per seat)", "Lambda_room_capacity"),
    (r"$\Lambda_y$", r"$y$-linking", "Lambda_y"),
    (r"$\Lambda_z$", r"$z$-linking", "Lambda_z"),
    (r"$\Lambda_{\mathrm{idle}}$", "RU9 idle-time markers", "Lambda_idle_marker"),
]


def _ratio_cell(v):
    if v is None:
        return "--"
    if v >= 100:
        text = fmt(v, 0)
    elif v >= 10:
        text = fmt(v, 0)
    elif v >= 1:
        text = fmt(v, 1)
    elif v >= 0.01:
        text = fmt(v, 2)
    else:
        text = fmt(v, 3)
    return f"${text}$" if v >= 1 else rf"$\mathbf{{{text}}}$"


def _cache_metadata(path: Path) -> dict:
    import h5py
    with h5py.File(path, "r") as h:
        return json.loads(h.attrs["metadata"])


def _penalty(config: dict, key: str) -> float:
    """A configured penalty as the compiler reads it: the room rows fall back to Lambda_room."""
    if key in ("Lambda_room_count", "Lambda_room_capacity") and config.get(key) is None:
        return float(config["Lambda_room"])
    return float(config[key])


def _base_penalties(path: Path) -> dict:
    """The block of a QUBO configuration file that holds the penalties."""
    import yaml
    stack = [yaml.safe_load(path.read_text(encoding="utf-8"))]
    while stack:
        d = stack.pop()
        if isinstance(d, dict):
            if "Lambda_PR1" in d:
                return d
            stack.extend(d.values())
    die(f"{path}: no penalty block")


def sufficiency_ratios():
    """[(column, instance, key, configured penalty / requirement, requirement)] for
    every penalty whose rule can be broken alone (the non-overlap one per clash),
    and {instance: smallest number of cells a clash shares}."""
    cells = {r["instance"]: int(r["min_shared_cells"]) for r in read_csv(ART / "clash_cells.csv")}
    files = sorted(S0_CACHES.glob("*.qubo_cache.h5"))
    if len(files) != sum(MANIFEST.values()):
        die(f"penalty sufficiency: {len(files)} S0 matrices, expected {sum(MANIFEST.values())}")
    sources = [(tier_of(f.name), f.name.split(".")[0], _cache_metadata(f), None) for f in files]
    run = ART / UPLOADED_3STUDIES
    setting = json.loads((run / "setting.json").read_text(encoding="utf-8"))
    sources.append(("3_studies", "3_studies_instance",
                    _cache_metadata(run / "caches" / "3_studies_instance.qubo_cache.h5"),
                    _base_penalties(ROOT / setting["base_config"])))
    out = []
    for col, inst, md, base in sources:
        extra = md["extra"]
        if base is None and (extra["setting"] != "S0" or extra["penalty_profile_set_penalties"]):
            die(f"penalty sufficiency: {inst} is not an S0 matrix with its configured penalties")
        if inst not in cells:
            die(f"penalty sufficiency: {inst} missing from artifacts/clash_cells.csv")
        config = md["config"] if base is None else base
        for _, _, key in SUFFICIENCY_ROWS:
            requirement = float(extra["penalty_requirements"][key])
            if requirement == 0:
                continue   # the rule cannot be broken without breaking another one
            ratio = _penalty(config, key) / requirement
            out.append((col, inst, key, ratio * (cells[inst] if key == "Lambda_nonoverlap" else 1),
                        requirement))
    return out, cells


def tab_penalty_sufficiency() -> dict:
    """Table 2 and the numbers of the text around it."""
    ratios, cells = sufficiency_ratios()
    cols = [*TIERS, "3_studies"]
    worst = {}
    for col, _, key, ratio, _ in ratios:
        worst[(key, col)] = min(worst.get((key, col), float("inf")), ratio)
    L = [r"\setlength{\tabcolsep}{4pt}\small",
         r"\begin{tabular}{@{}ll" + "r" * len(cols) + "@{}}", r"\toprule",
         r"symbol & rule & " + " & ".join(c.replace("_", r"\_") for c in cols) + r" \\",
         r"\midrule"]
    for sym, rule, key in SUFFICIENCY_ROWS:
        L.append(f"{sym} & {rule} & " + " & ".join(_ratio_cell(worst.get((key, c))) for c in cols) + r" \\")
    L += [r"\bottomrule", r"\end{tabular}"]
    (HERE / "tab_penalty_sufficiency.tex").write_text("\n".join(L) + "\n")
    print("[make_figures] wrote tab_penalty_sufficiency.tex")

    synth_cells = {n for i, n in cells.items() if not i.startswith("3_studies")}
    prod_cells = cells["3_studies_instance"]
    clash = {c: worst[("Lambda_nonoverlap", c)] for c in cols}
    if min(clash.values()) < 1:
        die("penalty sufficiency: a clash costs less than its requirement; the text says "
            "the non-overlap penalty is sufficient everywhere")
    pr1 = [worst[("Lambda_PR1", c)] for c in cols]
    linking = {worst[(k, c)] for k in ("Lambda_y", "Lambda_z") for c in cols}
    if len(linking) != 1:
        die(f"penalty sufficiency: the linking penalties exceed their requirements {linking} times; "
            "the text gives one value")
    requirement = lambda col, key: max(r[4] for r in ratios if r[0] == col and r[2] == key)
    margin = float(json.loads((VELOXQ / "S3" / "setting.json").read_text(encoding="utf-8"))
                   ["overrides"]["penalty_margin"])
    return {
        "SuffPROneLo": fmt(min(pr1)),
        "SuffPROneHi": fmt(max(pr1)),
        "SuffLinking": fmt(linking.pop()),
        "BMoveExtreme": fmt(requirement("extreme", "Lambda_nonoverlap")),
        "BMoveProd": fmt(requirement("3_studies", "Lambda_nonoverlap")),
        "ClashCellsSynth": str(min(synth_cells)),
        "ClashCellsProd": str(prod_cells),
        "ClashSThreeSynth": fmt(margin * min(synth_cells), 1),
        "ClashSThreeProd": fmt(margin * prod_cells, 1 if margin * prod_cells % 1 else 0),
    }


def section4_numbers() -> dict:
    """Sizes, largest coefficients and sparsity of the matrices of the VeloxQ runs
    (Sections 4 and 6), the soft objective of the first and the optimal solution
    of the MILP runs, and the room verdicts of the answers that pass the pooled
    room screens. Everything from the deposits and the 3_studies S3 run."""
    import h5py
    calls = read_csv(VELOXQ / "analysis" / "calls.csv")
    size = {}
    for r in calls:
        v = (int(r["n_vars"]), int(r["n_q_entries"]), float(r["max_abs_coefficient"]))
        if size.setdefault((r["setting"], r["instance"]), v) != v:
            die(f"calls.csv: {r['setting']} {r['instance']} has two matrix sizes")
    get = lambda s, i: [v[i] for (st, _), v in size.items() if st == s]
    for s in ("S0", "S3"):
        if len(get(s, 0)) != sum(MANIFEST.values()):
            die(f"calls.csv: {s} covers {len(get(s, 0))} instances")
    reduction = {t: stats.median(size[("S0", i)][2] / size[("S3", i)][2]
                                 for (s, i) in size if s == "S0" and tier_of(i) == t) for t in TIERS}
    # Share of the variable pairs that interact, tier medians, and build times.
    dens, builds = {}, []
    for s, d in (("S0", S0_CACHES), ("S3", S3_CACHES)):
        per = collections.defaultdict(list)
        for f in sorted(d.glob("*.qubo_cache.h5")):
            with h5py.File(f, "r") as h:
                n = int(h["qubo"].attrs["n_vars"])
                off = int((np.asarray(h["qubo"]["Q_i"]) != np.asarray(h["qubo"]["Q_j"])).sum())
                builds.append(float(json.loads(h.attrs["metadata"])["extra"]["build_time_seconds"]))
            per[tier_of(f.name)].append(100 * off / (n * (n - 1) / 2))
        dens[s] = [stats.median(per[t]) for t in TIERS]
    prod_file = ART / UPLOADED_3STUDIES / "caches" / "3_studies_instance.qubo_cache.h5"
    with h5py.File(prod_file, "r") as h:
        n = int(h["qubo"].attrs["n_vars"])
        prod_off = int((np.asarray(h["qubo"]["Q_i"]) != np.asarray(h["qubo"]["Q_j"])).sum())
        prod_coef = np.abs(np.asarray(h["qubo"]["Q_v"], dtype=float))
        prod_md = json.loads(h.attrs["metadata"])
    prod_coef = prod_coef[prod_coef != 0]
    # Soft objective S of the MILP runs (Section 7.6): first feasible solution and
    # optimum, every instance with a proven optimum (summary + superseded runs).
    import yaml
    milp = ROOT / "repository_ready" / "milp_synthetic_weighted"
    first, optimum = [], []
    for r in read_csv(milp / "summary.csv"):
        if r["status"] != "OPTIMAL":
            die(f"MILP summary: {r['instance']} is not optimal")
        first.append(float(r["first_objective"]))
        optimum.append(float(r["objective"]))
    for f in sorted((milp / "superseded").rglob("*_MIP_solution.yaml")):
        with open(f, encoding="utf-8") as fh:
            summary = yaml.safe_load(fh)["metadata"]["phase2"]["solve_summary"]
        if summary["status"] != "OPTIMAL":
            die(f"MILP superseded: {f.name} is not optimal")
        first.append(float(summary["first_incumbent_objective"]))
        optimum.append(float(summary["objective"]))
    sep = {r["instance"] for r in read_csv(VELOXQ / "analysis" / "energy_separation.csv")}
    if len(first) != len(sep):
        die(f"MILP: {len(first)} optima, energy separation has {len(sep)} instances")
    # Answers that pass the time core and the pooled room screens (V = 0) but
    # admit no exact room assignment: the text says there are two, both under S1.
    v0 = [r for r in calls if r["V"] == "0"]
    no_rooms = [r for r in v0 if r["rooms"] != "True"]
    if len(no_rooms) != 2 or {r["setting"] for r in no_rooms} != {"S1"}:
        die(f"V = 0 without rooms: {[(r['setting'], r['instance']) for r in no_rooms]}; "
            "the text says two, both under S1")
    sci = lambda x: _sci(x).strip("$")
    return {
        "SizeSZeroVarsLo": fmt(min(get("S0", 0))), "SizeSZeroVarsHi": fmt(max(get("S0", 0))),
        "SizeSZeroEntriesLo": fmt(min(get("S0", 1))), "SizeSZeroEntriesHi": fmt(max(get("S0", 1))),
        "SizeSThreeVarsLo": fmt(min(get("S3", 0))), "SizeSThreeVarsHi": fmt(max(get("S3", 0))),
        "SizeSThreeEntriesLo": fmt(min(get("S3", 1))), "SizeSThreeEntriesHi": fmt(max(get("S3", 1))),
        "PresolveVarsSZero": fmt(sum(get("S0", 0))), "PresolveVarsSThree": fmt(sum(get("S3", 0))),
        "PresolveVarsPct": fmt(100 * (1 - sum(get("S3", 0)) / sum(get("S0", 0)))),
        "PresolveEntriesPct": fmt(100 * (1 - sum(get("S3", 1)) / sum(get("S0", 1)))),
        "CoefSZeroLo": sci(min(get("S0", 2))), "CoefSZeroHi": sci(max(get("S0", 2))),
        "CoefSThreeLo": sci(min(get("S3", 2))), "CoefSThreeHi": sci(max(get("S3", 2))),
        "CoefReductionEasy": fmt(reduction["easy"]), "CoefReductionExtreme": fmt(reduction["extreme"]),
        "DensSZeroLo": fmt(min(dens["S0"]), 1), "DensSZeroHi": fmt(max(dens["S0"]), 1),
        "DensSThreeLo": fmt(min(dens["S3"]), 1), "DensSThreeHi": fmt(max(dens["S3"]), 1),
        "DensProdSThree": fmt(100 * prod_off / (n * (n - 1) / 2), 2),
        "ProdDecisionBits": fmt(prod_md["n_x_index"]),
        "ProdSThreeEntriesM": fmt(prod_md["n_q_entries"] / 1e6, 1),
        "ProdSThreeBuildSec": fmt(prod_md["extra"]["build_time_seconds"]),
        "ProdSThreeCoefMin": fmt(prod_coef.min()) if float(prod_coef.min()).is_integer()
        else sci(prod_coef.min()),
        "ProdSThreeCoefMax": sci(prod_coef.max()),
        "SynthBuildMaxSec": fmt(max(builds), 1),
        "SoftFirstLo": fmt(min(first)), "SoftFirstHi": fmt(max(first)),
        "SoftOptLo": fmt(min(optimum)), "SoftOptHi": fmt(max(optimum)),
        "VzeroAnswers": fmt(len(v0)), "VzeroNoRooms": str(len(no_rooms)),
    }


def census_numbers(rows) -> dict:
    """Caption of Fig. qubo-census: the family shares on its instance and how much
    of that instance's matrix the presolve removes (its S3 matrix)."""
    ref = "extreme_011_seed_1110"
    sub = [r for r in rows if r["instance"] == ref]
    total = sum(int(r["delta_nnz"]) for r in sub)
    share = {r["family"]: int(r["delta_nnz"]) / total for r in sub}
    top = sorted(share, key=share.get, reverse=True)[:4]
    if top != ["CONJ_PHASE3", "PR1", "PR4_students", "gap"]:
        die(f"census: largest families {top}; the caption names stage transition, course "
            "hours, student non-overlap and the idle-time markers, in that order")
    calls = read_csv(VELOXQ / "analysis" / "calls.csv")
    entries = {r["setting"]: int(r["n_q_entries"]) for r in calls if r["instance"] == ref}
    if entries["S0"] != total:
        die(f"census: {total} entries, the deposited S0 matrix {entries['S0']}")
    return {
        "CensusInstance": r"\texttt{" + ref.replace("_", r"\_") + "}",
        "CensusEntries": fmt(total),
        "CensusSTPct": fmt(100 * share["CONJ_PHASE3"]),
        "CensusPROnePct": fmt(100 * share["PR1"]),
        "CensusStudentsPct": fmt(100 * share["PR4_students"]),
        "CensusIdlePct": fmt(100 * share["gap"]),
        "CensusPresolvePct": fmt(100 * (1 - entries["S3"] / entries["S0"])),
    }


# ===================================================================== 5d
# Numbers of the text that were typed by hand before (review round 4, item 3.5),
# each read from the run records or outputs it describes and checked against them.

PRESOLVE_LOG_3STUDIES = ART / "penalty_recheck" / "room_presolve_sizes_3studies.log"
PR5_PAIRS_3STUDIES = ART / "pr5_pairs_3studies.json"
DWAVE_RESULTS = ROOT / "repository_ready" / "dwave_capacity" / "results"


def milp_campaign_numbers() -> dict:
    """The MILP runs behind the optima: settings, what was solved, the first
    incumbent and the longest proof (summary + superseded runs of the deposit)."""
    import math
    import yaml
    rows = read_csv(MILP_DEPOSIT / "summary.csv")
    done = collections.Counter(r["tier"] for r in rows)
    first, full, proof = [], [], []
    for r in rows:
        if r["status"] != "OPTIMAL" or float(r["mip_gap"]) != 0:
            die(f"MILP: {r['instance']} is not solved to a proven optimum")
        first.append(float(r["first_runtime_s"]))
        full.append(r["first_full"] == "True")
        proof.append((float(r["time_solve_s"]), r["tier"]))
    settings = {(r["threads"], r["gurobi"], float(r["mip_gap_setting"])) for r in rows}
    if len(settings) != 1:
        die(f"MILP: the runs have different settings {settings}")
    threads, gurobi, gap = settings.pop()
    for f in sorted((MILP_DEPOSIT / "superseded").rglob("*_MIP_solution.yaml")):
        with open(f, encoding="utf-8") as fh:
            phase2 = yaml.safe_load(fh)["metadata"]["phase2"]
        summary, solver = phase2["solve_summary"], phase2["solver_settings"]
        if summary["status"] != "OPTIMAL" or float(summary["mip_gap"]) != 0:
            die(f"MILP: {f.name} is not solved to a proven optimum")
        if str(solver["Threads"]) != threads or float(solver["MIPGap"]) != gap or solver["TimeLimit"] is not None:
            die(f"MILP: {f.name} ran with other settings")
        done[tier_of(f.name)] += 1
        first.append(float(summary["time_to_first_incumbent_s"]))
        full.append(phase2["first_incumbent"]["verifier"]["statuses"]["full"] is True)
        proof.append((float(summary["runtime_s"]), tier_of(f.name)))
    campaign = json.loads((MILP_DEPOSIT / "CAMPAIGN.json").read_text(encoding="utf-8"))["settings"]
    if campaign["time_limit"] is not None or gap != 0:
        die("MILP: the text says a MIPGap of 0 and no time limit")
    if not all(full):
        die("MILP: a first incumbent fails a check; the text says every one passes")
    if done["easy"] != MANIFEST["easy"] or done["medium"] != MANIFEST["medium"]:
        die("MILP: the text says every easy and medium instance is solved")
    longest, tier = max(proof)
    if tier != "hard":
        die("MILP: the text says the longest proof is on the hard tier")
    # The text: the run on one more hard instance was interrupted by the pause
    # (its log is kept in the deposit), and the other hard instances never ran.
    interrupted = sorted((MILP_DEPOSIT / "hard").glob("*.interrupted-*.log"))
    if len(interrupted) != 1:
        die(f"MILP: {len(interrupted)} interrupted hard runs; the text says one")
    # The same paragraph counts the solved instances with \VqSepInstances and
    # \VqSepHard (the energy check), so both must cover the instances solved here.
    sep = {(r["instance"], r["tier"]) for r in read_csv(VELOXQ / "analysis" / "energy_separation.csv")}
    if +collections.Counter(tier for _, tier in sep) != +done:
        die("MILP: the energy check and the MILP deposit cover different instances")
    return {
        "MilpThreads": threads,
        "MilpGurobi": gurobi,
        "MilpNotRunHard": str(MANIFEST["hard"] - done["hard"] - len(interrupted)),
        "MilpNotRunExtreme": str(MANIFEST["extreme"] - done["extreme"]),
        "MilpFirstMaxSec": f"{math.ceil(10 * max(first)) / 10:.1f}",   # "at most": round up
        "MilpProofMaxHours": fmt(longest / 3600, 1),
    }


def prod_presolve_numbers() -> dict:
    """Sizes of the 3_studies encodings by presolve level (checks/room_presolve_sizes.py).
    Its counts level must be the matrix of the S3 runs on 3_studies."""
    levels = ("none", "exact", "implied", "counts")
    table = {}
    for line in PRESOLVE_LOG_3STUDIES.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 5 and all(p.replace(",", "").isdigit() for p in parts[-4:]):
            table[" ".join(parts[:-4])] = dict(zip(levels, (int(p.replace(",", "")) for p in parts[-4:])))
    need = ("variables", "x", "y", "z", "MC slack", "room count slack", "room capacity slack",
            "idle markers", "matrix entries", "rows", "count_cannot_bind", "capacity_cannot_bind",
            "capacity_implied", "capacity_left_to_rooms")
    if any(k not in table for k in need):
        die(f"presolve sizes: {PRESOLVE_LOG_3STUDIES.name} lacks {[k for k in need if k not in table]}")
    md = _cache_metadata(ART / UPLOADED_3STUDIES / "caches" / "3_studies_instance.qubo_cache.h5")
    if (table["variables"]["counts"], table["matrix entries"]["counts"], table["x"]["counts"]) != \
            (md["n_vars"], md["n_q_entries"], md["n_x_index"]):
        die("presolve sizes: the counts level is not the matrix of the S3 runs on 3_studies")
    none = {k: v["none"] for k, v in table.items()}
    aux = none["variables"] - none["x"]
    if aux != sum(none[k] for k in ("y", "z", "MC slack", "room count slack", "room capacity slack",
                                    "idle markers")):
        die("presolve sizes: the auxiliary bits do not add up")
    n = none["variables"]
    pairs = n * (n - 1) / 2
    lo = fmt(100 * (none["matrix entries"] - n) / pairs, 2)   # every diagonal entry stored
    hi = fmt(100 * none["matrix entries"] / pairs, 2)         # no diagonal entry stored
    if lo != hi:
        die("presolve sizes: the configured density depends on the diagonal; quote it otherwise")
    share = lambda k: fmt(100 * none[k] / aux, 1)
    return {
        "ProdNoneVars": fmt(table["variables"]["none"]),
        "ProdExactVars": fmt(table["variables"]["exact"]),
        "ProdImpliedVars": fmt(table["variables"]["implied"]),
        "ProdImpliedDropPct": fmt(100 * (1 - table["variables"]["implied"] / table["variables"]["none"])),
        "ProdAux": fmt(aux),
        "ProdCapSlack": fmt(none["room capacity slack"]), "ProdCapSlackPct": share("room capacity slack"),
        "ProdGroupSlot": fmt(none["y"]), "ProdGroupSlotPct": share("y"),
        "ProdCountSlack": fmt(none["room count slack"]), "ProdCountSlackPct": share("room count slack"),
        "ProdIdleMarkers": fmt(none["idle markers"]), "ProdIdlePct": share("idle markers"),
        "ProdGroupDay": fmt(none["z"]),
        "ProdMCSlack": fmt(none["MC slack"]),
        "ProdNoneEntriesM": fmt(none["matrix entries"] / 1e6, 1),
        "ProdRows": fmt(table["rows"]["none"]),
        "ProdCountCannotBind": fmt(table["count_cannot_bind"]["counts"]),
        "ProdCapCannotBind": fmt(table["capacity_cannot_bind"]["counts"]),
        "ProdCapImplied": fmt(table["capacity_implied"]["counts"]),
        "ProdSeatRows": fmt(table["capacity_left_to_rooms"]["counts"]),
        "DensProdNone": lo,
    }


def prod_pr5_numbers() -> dict:
    """PR5 pairs of 3_studies (checks/pr5_fast_copy_and_pair_count.py --json), on the
    instance and candidates of the S3 runs."""
    rec = json.loads(PR5_PAIRS_3STUDIES.read_text(encoding="utf-8"))
    md = _cache_metadata(ART / UPLOADED_3STUDIES / "caches" / "3_studies_instance.qubo_cache.h5")
    if rec["instance_sha256"] != md["extra"]["source_sha256"] or rec["candidates"] != md["n_x_index"]:
        die("PR5 pairs: counted on another instance or candidate set than the S3 runs")
    if not rec["fast_copy_identical_on_subsamples"]:
        die("PR5 pairs: the fast builder differs from the compiler's")
    return {"ProdPRFivePairs": fmt(rec["pairs"])}


def _ising_precision(path: Path, level: float = 0.01) -> tuple:
    """Dynamic range of the Ising coefficients of a matrix, and the share of them
    below ``level`` once scaled into h in [-4, 4], J in [-1, 1]
    (as repository_ready/dwave_capacity/code/dwave_capacity_precision.py does)."""
    import h5py
    with h5py.File(path, "r") as h:
        n = int(h["qubo"].attrs["n_vars"])
        i, j = np.asarray(h["qubo"]["Q_i"]), np.asarray(h["qubo"]["Q_j"])
        v = np.asarray(h["qubo"]["Q_v"], dtype=float)
    d, o = i == j, i != j
    field = (np.bincount(i[d], weights=v[d] / 2.0, minlength=n)
             + np.bincount(i[o], weights=v[o] / 4.0, minlength=n)
             + np.bincount(j[o], weights=v[o] / 4.0, minlength=n))
    coupling = np.abs(v[o] / 4.0)
    field = np.abs(field[field != 0])
    coupling = coupling[coupling != 0]
    both = np.concatenate([field, coupling])
    scale = max(field.max(initial=0.0) / 4.0, coupling.max(initial=0.0) / 1.0)
    return float(both.max() / both.min()), float(np.mean(both / scale < level))


def qpu_numbers() -> dict:
    """Appendix C: coefficient precision after QPU scaling and the clique embeddings on
    Advantage_system4. The precision is computed on the matrices the VeloxQ runs
    submitted where they exist, and must agree with the deposit's rows for them."""
    import math
    _, s0 = _ising_precision(S0_CACHES / "easy_000_seed_1000.qubo_cache.h5")
    _, s3 = _ising_precision(S3_CACHES / "easy_000_seed_1000.qubo_cache.h5")
    prod_range, prod_s3 = _ising_precision(ART / UPLOADED_3STUDIES / "caches" / "3_studies_instance.qubo_cache.h5")
    rows = {name: {r["encoding"]: r for r in read_csv(DWAVE_RESULTS / f"{name}.csv")}
            for name in ("precision_easy000", "precision_easy000_sufficient_penalties", "precision_3studies")}
    share = lambda name, enc: float(rows[name][enc]["share_below_error_level"])
    if abs(share("precision_easy000", "default") - s0) > 1e-9 or \
            abs(share("precision_easy000_sufficient_penalties", "presolved") - s3) > 1e-9:
        die("QPU precision: the deposit's rows differ from the S0 and S3 matrices of the runs")
    ranges = [(float(r["ising_dynamic_range"]), name, enc) for name, rs in rows.items() for enc, r in rs.items()]
    ranges.append((prod_range, "precision_3studies", "S3"))
    lo, hi = min(ranges), max(ranges)
    if lo[1:] != ("precision_easy000_sufficient_penalties", "feasibility") or hi[1] != "precision_3studies":
        die(f"QPU precision: the text names the extremes of the dynamic range, found {lo[1:]} and {hi[1:]}")
    prod_min = min([share("precision_3studies", enc) for enc in rows["precision_3studies"]] + [prod_s3])

    def one_digit(x):
        e = int(math.floor(math.log10(x)))
        m = round(x / 10 ** e)
        if m == 10:
            m, e = 1, e + 1
        return rf"{m}\times10^{{{e}}}"

    lines = (DWAVE_RESULTS / "facts.txt").read_text(encoding="utf-8").splitlines()
    k = next(i for i, line in enumerate(lines) if line.split()[:1] == ["Advantage_system4"])
    import re
    m = re.search(r"on 2 thinned stand-ins: K_(\d+) \(chains <= (\d+)\), K_(\d+) \(chains <= (\d+)\)", lines[k + 1])
    if m is None:
        die("QPU: facts.txt has no stand-in embeddings for Advantage_system4")
    return {
        "QpuPrecSZero": fmt(100 * s0),
        "QpuPrecSThree": fmt(100 * s3),
        "QpuPrecFeas": fmt(100 * share("precision_easy000_sufficient_penalties", "feasibility")),
        "QpuPrecProdMin": f"{math.floor(1000 * prod_min) / 10:.1f}",   # "at least": round down
        "QpuRangeLo": one_digit(lo[0]),
        "QpuRangeHi": one_digit(hi[0]),
        "QpuStandInClique": str(min(int(m.group(1)), int(m.group(3)))),
        "QpuStandInChain": str(max(int(m.group(2)), int(m.group(4)))),
    }


def margin_numbers() -> dict:
    """How far the configured penalties exceed their requirements (tier medians of
    Table 2's ratios), for the failure modes of Table 8."""
    ratios, _ = sufficiency_ratios()
    med = {key: [stats.median(r[3] for r in ratios if r[0] == t and r[2] == key) for t in TIERS]
           for key in ("Lambda_room_count", "Lambda_nonoverlap", "Lambda_PR1")}
    return {
        "MarginRoomLo": fmt(min(med["Lambda_room_count"]), 3),
        "MarginRoomHi": fmt(max(med["Lambda_room_count"]), 3),
        "MarginClashLo": fmt(min(med["Lambda_nonoverlap"])),
        "MarginClashHi": fmt(max(med["Lambda_nonoverlap"])),
        "MarginHoursLo": fmt(min(med["Lambda_PR1"])),
        "MarginHoursHi": fmt(max(med["Lambda_PR1"])),
    }


# ===================================================================== 5c
# VeloxQ campaign of 13-15.10.2026: seven presolve and penalty settings on the
# 64 certified synthetic instances, three calls each. Read from the deposit's
# analysis tables (scripts/analyze_veloxq_campaign.py), so the paper cites what
# repository_ready/veloxq_synthetic holds. Writes tab_veloxq_settings.tex,
# tab_veloxq_breakdown.tex and generated_numbers_veloxq.tex.

VELOXQ = ROOT / "repository_ready" / "veloxq_synthetic"
VELOXQ_SETTINGS = [  # setting, presolve level, penalties
    ("S0", "none", "configured"),
    ("S1", "implied", r"configured, room count $100$"),
    ("S2", "counts", r"$\max$(configured, $1.5\times$ requirement)"),
    ("S3", "counts", r"$1.5\times$ requirement"),
    ("S4", "none", r"$1.5\times$ requirement, seats configured"),
    ("S5", "counts", "configured"),
    ("S6", "counts", r"$5\times$ requirement"),
]
VELOXQ_MACRO = {"S0": "SZero", "S1": "SOne", "S2": "STwo", "S3": "SThree",
                "S4": "SFour", "S5": "SFive", "S6": "SSix"}


def _sci(x: float) -> str:
    e = int(np.floor(np.log10(x)))
    m = x / 10 ** e
    if round(m, 1) >= 10:
        m, e = m / 10, e + 1
    return rf"${m:.1f}\times10^{{{e}}}$"


def _mean_cell(x: float) -> str:
    if x == 0:
        return "$0$"
    return "$<0.1$" if x < 0.05 else f"${fmt(x, 1)}$"


def _range_cell(lo: float, hi: float) -> str:
    return _sci(lo) if _sci(lo) == _sci(hi) else f"{_sci(lo)}--{_sci(hi)}"


def tab_veloxq_settings():
    ana = VELOXQ / "analysis"
    need = ("calls.csv", "topk.csv", "breakdown_tiers.csv", "tier_view.csv")
    if not all((ana / n).exists() for n in need):
        print("[make_figures] VeloxQ campaign analysis missing; skipping tab_veloxq_settings")
        return
    calls = read_csv(ana / "calls.csv")
    topk = read_csv(ana / "topk.csv")
    brk = [r for r in read_csv(ana / "breakdown_tiers.csv") if r["sample"] == "lowest energy"]
    view = {(r["setting"], r["tier"]): r for r in read_csv(ana / "tier_view.csv")}
    settings = [s for s, _, _ in VELOXQ_SETTINGS]
    n_calls = collections.Counter(r["setting"] for r in calls)
    reps = max(int(r["rep"]) for r in calls)
    if set(n_calls) != set(settings) or any(n != sum(MANIFEST.values()) * reps for n in n_calls.values()):
        die(f"VeloxQ calls per setting {dict(n_calls)}, expected {sum(MANIFEST.values()) * reps} for each of {settings}")
    for (s, t), r in view.items():
        if int(r["instances"]) != MANIFEST[t]:
            die(f"tier_view: {s} {t} has {r['instances']} instances, the manifest {MANIFEST[t]}")
    job = json.loads((VELOXQ / "S0" / "jobs.jsonl").read_text(encoding="utf-8").splitlines()[0])

    def count(s, col, tiers=TIERS):
        return sum(int(float(view[(s, t)][col])) for t in tiers)

    returned = "instances_all_checks_lowest_energy"
    deleted = "instances_all_checks_lowest_energy_after_deletion"
    best = "instances_all_checks_fewest_violations_after_deletion"
    # Sections 7.5 and 7.6 say that no setting gives a valid timetable on the extreme tier.
    if any(count(s, returned, ("extreme",)) for s in settings):
        die("a setting yields a valid timetable on the extreme tier: the prose says none does")

    def cell(s, tiers):
        a, b = count(s, returned, tiers), count(s, deleted, tiers)
        return f"${a}$" if a == b else f"${a}$ (${b}$)"

    L = [r"\setlength{\tabcolsep}{3.5pt}\small",
         r"\begin{tabular}{@{}lllcrrrrrr@{}}", r"\toprule",
         r" & & & & \multicolumn{5}{c}{instances with a valid timetable} & \\",
         r"\cmidrule(lr){5-9}",
         r"setting & presolve & penalties & largest coefficient & easy & medium & hard & extreme & all & best of $16$ \\",
         r"\midrule"]
    for s, level, penalties in VELOXQ_SETTINGS:
        coef = [float(r["max_abs_coefficient"]) for r in calls if r["setting"] == s]
        L.append(f"{s} & \\texttt{{{level}}} & {penalties} & {_range_cell(min(coef), max(coef))} & "
                 + " & ".join(cell(s, (t,)) for t in TIERS) + f" & {cell(s, TIERS)} & ${count(s, best)}$ \\\\")
    L += [r"\bottomrule", r"\end{tabular}"]
    (HERE / "tab_veloxq_settings.tex").write_text("\n".join(L) + "\n")

    fam = {(r["setting"], r["tier"]): r for r in brk}
    # The caption says every course short of its minutes has no lesson at all.
    for (s, t), r in fam.items():
        if r["mean_PR1_courses_under"] != r["mean_PR1_courses_absent"]:
            die(f"VeloxQ breakdown {s} {t}: a course short of its minutes still has a lesson; fix the caption")
    shown = ("medium", "hard", "extreme")
    L = [r"\setlength{\tabcolsep}{3pt}\small",
         r"\begin{tabular}{@{}l" + "rrrr" * len(shown) + "@{}}", r"\toprule",
         " & " + " & ".join(rf"\multicolumn{{4}}{{c}}{{{t}}}" for t in shown) + r" \\",
         "".join(rf"\cmidrule(lr){{{2 + 4 * k}-{5 + 4 * k}}}" for k in range(len(shown))),
         "setting & " + " & ".join(["clashes & room rows & surplus & missing"] * len(shown)) + r" \\",
         r"\midrule"]
    for s, _, _ in VELOXQ_SETTINGS:
        cells = []
        for t in shown:
            r = fam[(s, t)]
            cells += [_mean_cell(float(r["mean_PR3_PR4_lecturer_overlap"]) + float(r["mean_PR3_PR4_group_overlap"])),
                      _mean_cell(float(r["mean_CONJ_PHASE3_room_count"]) + float(r["mean_CONJ_PHASE3_room_capacity"])),
                      _mean_cell(float(r["mean_PR1_courses_over"])), _mean_cell(float(r["mean_PR1_courses_under"]))]
        L.append(f"{s} & " + " & ".join(cells) + r" \\")
    L += [r"\bottomrule", r"\end{tabular}"]
    (HERE / "tab_veloxq_breakdown.tex").write_text("\n".join(L) + "\n")

    # Paired weighted objective where both settings have a valid lowest-energy sample.
    best_obj = collections.defaultdict(dict)
    for r in calls:
        if r["full"] == "True" and r["soft_objective"] not in ("", "None"):
            prev = best_obj[r["setting"]].get(r["instance"])
            v = float(r["soft_objective"])
            best_obj[r["setting"]][r["instance"]] = v if prev is None else min(prev, v)

    def paired(a, b):
        both = set(best_obj[a]) & set(best_obj[b])
        return len(both), sum(1 for i in both if best_obj[a][i] < best_obj[b][i])

    better = sum(1 for r in topk if float(r["lowest_V_in_k"]) < float(r["V_lowest_energy"])) / len(topk)
    rhos = [float(r["rank_correlation_energy_V"]) for r in topk if r["rank_correlation_energy_V"] not in ("", "None")]
    M = [r"%% Auto-generated by paper/figures/make_figures.py -- do not edit.",
         rf"\newcommand{{\VqCalls}}{{{reps}}}",
         rf"\newcommand{{\VqTotalCalls}}{{{fmt(len(calls))}}}",
         rf"\newcommand{{\VqSteps}}{{{fmt(job['num_steps'])}}}",
         rf"\newcommand{{\VqReplicas}}{{{fmt(job['num_rep'])}}}",
         rf"\newcommand{{\VqHardMax}}{{{max(count(s, returned, ('hard',)) for s in settings)}}}",
         rf"\newcommand{{\VqTopKBetter}}{{{fmt(100 * better)}}}",
         rf"\newcommand{{\VqTopKRho}}{{{fmt(stats.median(rhos), 2)}}}"]
    for s in settings:
        n = VELOXQ_MACRO[s]
        M += [rf"\newcommand{{\VqValid{n}}}{{{count(s, returned)}}}",
              rf"\newcommand{{\VqValidDel{n}}}{{{count(s, deleted)}}}",
              rf"\newcommand{{\VqValidBest{n}}}{{{count(s, best)}}}",
              rf"\newcommand{{\VqHard{n}}}{{{count(s, returned, ('hard',))}}}",
              rf"\newcommand{{\VqHardDel{n}}}{{{count(s, deleted, ('hard',))}}}"]
    s3_hard, s3_ext, s0_ext = fam[("S3", "hard")], fam[("S3", "extreme")], fam[("S0", "extreme")]
    n03, w03 = paired("S3", "S0")
    n63, w63 = paired("S3", "S6")
    M += [rf"\newcommand{{\VqSurplusHardSThree}}{{{fmt(float(s3_hard['mean_PR1_courses_over']), 1)}}}",
          rf"\newcommand{{\VqMissingExtremeSThree}}{{{fmt(float(s3_ext['mean_PR1_courses_under']), 0)}}}",
          rf"\newcommand{{\VqClashExtremeSZero}}{{{fmt(float(s0_ext['mean_PR3_PR4_lecturer_overlap']) + float(s0_ext['mean_PR3_PR4_group_overlap']), 0)}}}",
          rf"\newcommand{{\VqMedianVHardSThree}}{{{fmt(float(s3_hard['median_V']), 0)}}}",
          rf"\newcommand{{\VqMedianVHardSZero}}{{{fmt(float(fam[('S0', 'hard')]['median_V']), 1)}}}",
          rf"\newcommand{{\VqPairN}}{{{n03}}}", rf"\newcommand{{\VqPairSThreeBetter}}{{{w03}}}",
          rf"\newcommand{{\VqPairSixN}}{{{n63}}}", rf"\newcommand{{\VqPairSThreeBetterSSix}}{{{w63}}}"]
    # Limitations, Statistics: instances whose answer is valid in some but not all
    # of their calls under S0.
    valid_calls = collections.Counter(r["instance"] for r in calls
                                      if r["setting"] == "S0" and r["full"] == "True")
    s0_instances = {r["instance"] for r in calls if r["setting"] == "S0"}
    M.append(rf"\newcommand{{\VqSZeroPartlyValid}}{{"
             rf"{sum(1 for i in s0_instances if 0 < valid_calls[i] < reps)}}}")
    M += _veloxq_s2_kept_nonoverlap()
    M += _veloxq_separation_macros(calls)
    M += _veloxq_repair()
    (HERE / "generated_numbers_veloxq.tex").write_text("\n".join(M) + "\n")
    print("[make_figures] wrote tab_veloxq_settings.tex, tab_veloxq_breakdown.tex, tab_veloxq_repair.tex, "
          "generated_numbers_veloxq.tex")


def _veloxq_s2_kept_nonoverlap() -> list:
    """Section 7.6: the instances on which S2 keeps the configured non-overlap
    penalty (it raises a penalty only where 1.5 times its requirement is larger),
    read from the matrices as submitted."""
    import h5py

    def config_of(path):
        with h5py.File(path, "r") as h:
            md = json.loads(h.attrs.get("metadata", "{}"))
        return md.get("config", md.get("qubo_config", {}))

    s0 = {f.name: config_of(f) for f in sorted((VELOXQ / "S0" / "caches").glob("*.qubo_cache.h5"))}
    s2 = {f.name: config_of(f) for f in sorted((VELOXQ / "S2" / "caches").glob("*.qubo_cache.h5"))}
    if sorted(s0) != sorted(s2) or len(s2) != sum(MANIFEST.values()):
        die("S2 / S0 caches: the two settings do not cover the same 64 instances")
    # The text: S2 keeps the course-hour, block-limit and linking penalties as
    # configured on every instance.
    for key in ("Lambda_PR1", "Lambda_MC", "Lambda_y", "Lambda_z"):
        if any(float(s2[n][key]) != float(s0[n][key]) for n in s2):
            die(f"S2: {key} differs from the configured value; the text says S2 keeps it")
    kept = sum(1 for n in s2 if float(s2[n]["Lambda_nonoverlap"]) == float(s0[n]["Lambda_nonoverlap"]))
    return [rf"\newcommand{{\VqSTwoNonoverlapKept}}{{{kept}}}"]


def _words(x: float) -> str:
    """A large energy in words for the prose: 2.4~million, 17{,}000."""
    if x >= 1e6:
        return f"{x / 1e6:.1f}~million"
    return fmt(round(x, -3) if x >= 1e4 else x, 0)


def _veloxq_separation_macros(calls) -> list:
    """In-text numbers of the energy check (scripts/check_energy_separation.py): where the samples
    lie relative to the best legal timetable, and what oversized penalties do to the search. Every
    sentence the macros feed is guarded: the script aborts if the data stop supporting it."""
    ana = VELOXQ / "analysis"
    sep, nb = ana / "energy_separation.csv", ana / "optimum_neighbours.csv"
    if not (sep.exists() and nb.exists()):
        die("energy_separation.csv / optimum_neighbours.csv missing: run scripts/check_energy_separation.py")
    sep, nb = read_csv(sep), read_csv(nb)
    if any(int(r["samples_below_opt"]) for r in sep):
        die("a sample lies below the best legal timetable: the prose says none does")
    if any(float(r["best_completed_above_opt"]) < -1e-6 for r in sep):
        die("an answer with its auxiliaries at their best lies below the optimum: the prose says none does")
    if any(int(r["illegal_below_opt"]) for r in nb):
        die("a neighbour of the optimum is illegal and below it: the prose says none is")
    if any(int(r["illegal_below_worst_legal"]) for r in nb if r["setting"] in ("S2", "S3", "S4", "S6")):
        die("with a sufficient room-count penalty an illegal neighbour lies below a legal one: the prose says none does")
    if not all(any(int(r["illegal_below_worst_legal"]) for r in nb if r["setting"] == s) for s in ("S0", "S1", "S5")):
        die("with a room-count penalty of 10 or 100 no illegal neighbour lies below a legal one: the prose says some do")
    valid = collections.defaultdict(set)
    n_valid = collections.Counter()
    for r in calls:
        if r["full"] == "True":
            valid[r["setting"]].add(r["instance"])
            n_valid[r["setting"]] += 1

    def aux(s, tier):
        return stats.median(float(r["energy_in_auxiliaries"]) for r in sep if r["setting"] == s and r["tier"] == tier)

    def steps(s):
        v = [float(r["reported_energy_step"]) for r in sep if r["setting"] == s]
        return min(v), max(v)

    surplus = [r for r in sep if r["setting"] == "S3" and r["tier"] == "hard" and int(r["surplus_lessons"]) > 0]
    if not surplus or any(float(r["deletion_change_bits_only"]) <= 0 or float(r["deletion_change_completed"]) >= 0
                          for r in surplus):
        die("S3 hard: deleting surplus lessons is not uphill bit by bit and downhill with the auxiliaries reset")
    ex = "medium_005_seed_1050"
    add_ex = next(float(r["cheapest_addition_above_opt"]) for r in nb if r["setting"] == "S3" and r["instance"] == ex)
    legal_ex = max(float(r["best_completed_above_opt"]) for r in sep if r["instance"] == ex and r["best_all_checks"] == "True")
    if not legal_ex > add_ex:
        die(f"{ex}: no returned legal timetable lies above S3's cheapest addition; change the example")
    thin_row = next(r for r in nb if r["setting"] == "S0" and r["instance"] == "hard_009_seed_1090")
    if thin_row["cheapest_illegal_move"] != "move" or "CONJ_PHASE3_room_count" not in thin_row["cheapest_illegal_breaks"]:
        die("S0 hard_009: the cheapest illegal neighbour is not a lesson moved into a room-count row; fix the prose")
    thin = float(thin_row["cheapest_illegal_above_opt"])
    lo2, hi2 = steps("S2")
    lo3, hi3 = steps("S3")
    M = [rf"\newcommand{{\VqSepInstances}}{{{len({r['instance'] for r in sep})}}}",
         rf"\newcommand{{\VqSepHard}}{{{len({r['instance'] for r in sep if r['tier'] == 'hard'})}}}",
         rf"\newcommand{{\VqSepSamples}}{{{fmt(sum(int(r['samples']) for r in sep) / 1e6, 1)}~million}}",
         rf"\newcommand{{\VqNbInstances}}{{{len({r['instance'] for r in nb})}}}",
         rf"\newcommand{{\VqSThreeOnly}}{{{len(valid['S3'] - valid['S2'])}}}",
         rf"\newcommand{{\VqSTwoOnly}}{{{len(valid['S2'] - valid['S3'])}}}",
         rf"\newcommand{{\VqStepSTwo}}{{${fmt(lo2)}$ to ${fmt(hi2)}$}}",
         rf"\newcommand{{\VqStepSThree}}{{${lo3:g}$ to ${fmt(hi3)}$}}",
         rf"\newcommand{{\VqSurplusCalls}}{{{len(surplus)}}}",
         rf"\newcommand{{\VqAddExample}}{{{fmt(add_ex)}}}",
         rf"\newcommand{{\VqLegalExample}}{{{fmt(legal_ex)}}}",
         rf"\newcommand{{\VqThinMargin}}{{{fmt(thin)}}}"]
    for s in ("S0", "S2", "S3", "S6"):
        n = VELOXQ_MACRO[s]
        M.append(rf"\newcommand{{\VqCallsValid{n}}}{{{n_valid[s]}}}")
        for tier in ("easy", "medium", "hard"):
            M.append(rf"\newcommand{{\VqAux{n}{tier.capitalize()}}}{{{_words(aux(s, tier))}}}")
    return M


# The calls the repair leaves invalid, as the prose names them: instance -> number of calls.
REPAIR_STUCK_INSTANCES = {"extreme_014_seed_1140": 2, "extreme_014_seed_1142": 1, "extreme_014_seed_1143": 1}


def _veloxq_repair() -> list:
    """The repair (H1 + H2, k = 1, 2, the MILP's room rows in the first key) on every S3 call:
    tab_veloxq_repair.tex and the in-text numbers, from the deposit's repair_*.csv
    (scripts/analyze_veloxq_repair.py). Objective numbers cover valid timetables only. Every
    sentence the numbers feed is guarded: the script aborts if the data stop supporting it."""
    ana = VELOXQ / "analysis"
    calls = read_csv(ana / "repair_calls.csv")
    tiers = {r["tier"]: r for r in read_csv(ana / "repair_tiers.csv")}
    stuck = read_csv(ana / "repair_stuck.csv")
    if {r["setting"] for r in calls} != {"S3"} or len(calls) != 3 * sum(MANIFEST.values()):
        die(f"repair_calls.csv: {len(calls)} calls of {sorted({r['setting'] for r in calls})}, expected the 192 S3 calls")
    for t in TIERS:
        if int(tiers[t]["instances"]) != MANIFEST[t] or int(tiers[t]["calls"]) != 3 * MANIFEST[t]:
            die(f"repair_tiers.csv: tier {t} does not match the manifest")
    if any(r["converged"] != "True" for r in calls):
        die("a repair call stopped before converging: the prose says every call ran until a pass changed nothing")
    if any(r["violations_after"] == "0" and r["full"] != "True" for r in calls):
        die("a call at zero in the repair's cost fails a check: the prose says the room rows close that gap")
    if any(r["gap_percent"] and float(r["gap_percent"]) < -1e-6 for r in calls):
        die("a valid repaired timetable lies below the MILP optimum")
    invalid = [r for r in calls if r["full"] != "True"]
    by_call = {(r["instance"], r["rep"]): r for r in stuck}
    if {(r["instance"], r["rep"]) for r in invalid} != set(by_call):
        die("repair_stuck.csv does not list exactly the invalid calls")
    if dict(collections.Counter(r["instance"] for r in invalid)) != REPAIR_STUCK_INSTANCES:
        die(f"the invalid calls are {sorted((r['instance'], r['rep']) for r in invalid)}; "
            "fix the prose and REPAIR_STUCK_INSTANCES")
    for r in invalid:
        s = by_call[(r["instance"], r["rep"])]
        if r["left"] != "PR1_course_minutes=1" or s["lessons_now"] != "0" or s["missing_minutes"] != "45":
            die(f"{r['instance']} call {r['rep']}: not one course with no lesson and one 45-minute lesson missing")
        if s["valid_1_moves"] != "0" or s["valid_2_moves"] != "0":
            die(f"{r['instance']} call {r['rep']}: a move of at most two lessons gives a valid timetable")
        if int(s["other_calls_valid"]) < 1:
            die(f"{r['instance']} call {r['rep']}: no other call of the instance is valid")
        if min(int(p.split(":")[0]) for p in s["places_by_clashing_lessons"].split()) < 1:
            die(f"{r['instance']} call {r['rep']}: a place of the missing lesson is free")
    clash_max = max(int(p.split(":")[0]) for s in stuck for p in s["places_by_clashing_lessons"].split())
    if min(int(s["lessons_freeing_a_place"]) for s in stuck) < 1:
        die("a stuck call has no lesson whose removal frees a place: the prose says each has some")
    freed = sum(1 for s in stuck if s["continued_full"] == "True")
    if any(s["continued_full"] != "True" and s["continued_violations_after"] != "1" for s in stuck):
        die("a continued call ends worse than one lesson short")

    def pct(x: str) -> str:
        return rf"${fmt(float(x), 1)}\,\%$"

    def secs(x: str) -> str:
        v = float(x)
        return f"${fmt(v, 1) if v < 10 else fmt(v, 0)}$"

    def row(t: str, r: dict, one_call: bool) -> str:
        known = int(r["valid_calls_with_optimum"])
        if known:
            obj = [f"${r['calls_at_optimum']}/{known}$", f"{pct(r['gap_median'])} ({pct(r['gap_max'])})",
                   "--" if one_call else f"{pct(r['best_gap_median'])} ({pct(r['best_gap_max'])})"]
        else:
            obj = ["--", "--", "--"]
        return (f"{t} & ${r['calls_valid']}/{r['calls']}$ & ${r['instances_valid']}/{r['instances']}$ & "
                + " & ".join(obj) + f" & {secs(r['repair_seconds_median'])} ({secs(r['repair_seconds_max'])}) \\\\")

    empty_tiers, empty_macros = _veloxq_empty_start(calls)
    L = [r"\setlength{\tabcolsep}{4pt}\small",
         r"\begin{tabular}{@{}lrrrrrr@{}}", r"\toprule",
         r" & \multicolumn{2}{c}{valid} & \multicolumn{3}{c}{weighted objective of the valid timetables}"
         r" & search \\",
         r"\cmidrule(lr){2-3}\cmidrule(lr){4-6}",
         r"tier & calls & instances & at the optimum & above it & best call per instance & (s) \\",
         r"\midrule", r"\multicolumn{7}{@{}l}{\emph{from the solver's answers, three calls per instance}} \\"]
    L += [row(t, tiers[t], False) for t in TIERS]
    L += [r"\midrule", r"\multicolumn{7}{@{}l}{\emph{from an empty timetable, once per instance}} \\"]
    L += [row(t, empty_tiers[t], True) for t in TIERS]
    L += [r"\bottomrule", r"\end{tabular}"]
    (HERE / "tab_veloxq_repair.tex").write_text("\n".join(L) + "\n")

    def num(key: str, col: str, nd: int = 0) -> str:
        return fmt(float(tiers[key][col]), nd)

    rng = lambda col: (min(int(s[col]) for s in stuck), max(int(s[col]) for s in stuck))  # noqa: E731
    words = ("none", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")

    def word(n: int) -> str:
        return words[n] if n < len(words) else str(n)

    return [rf"\newcommand{{\VqRepairStuckWord}}{{{word(len(invalid))}}}",
            rf"\newcommand{{\VqRepairContinuedValidWord}}{{{word(freed)}}}",
            rf"\newcommand{{\VqRepairCalls}}{{{len(calls)}}}",
            rf"\newcommand{{\VqRepairValid}}{{{len(calls) - len(invalid)}}}",
            rf"\newcommand{{\VqRepairInstancesValid}}{{{sum(int(tiers[t]['instances_valid']) for t in TIERS)}}}",
            rf"\newcommand{{\VqRepairEasyAtOpt}}{{{tiers['easy']['calls_at_optimum']}}}",
            rf"\newcommand{{\VqRepairEasyKnown}}{{{tiers['easy']['valid_calls_with_optimum']}}}",
            rf"\newcommand{{\VqRepairMediumGap}}{{{num('medium', 'gap_median', 1)}}}",
            rf"\newcommand{{\VqRepairHardGap}}{{{num('hard', 'gap_median', 1)}}}",
            rf"\newcommand{{\VqRepairHardOptInstances}}{{{tiers['hard']['instances_with_optimum']}}}",
            rf"\newcommand{{\VqRepairStuck}}{{{len(invalid)}}}",
            rf"\newcommand{{\VqRepairStuckGroupsMin}}{{{rng('groups')[0]}}}",
            rf"\newcommand{{\VqRepairStuckGroupsMax}}{{{rng('groups')[1]}}}",
            rf"\newcommand{{\VqRepairStuckStudentsMin}}{{{rng('students')[0]}}}",
            rf"\newcommand{{\VqRepairStuckStudentsMax}}{{{rng('students')[1]}}}",
            rf"\newcommand{{\VqRepairStuckPlacesMin}}{{{rng('places')[0]}}}",
            rf"\newcommand{{\VqRepairStuckPlacesMax}}{{{rng('places')[1]}}}",
            rf"\newcommand{{\VqRepairStuckClashMax}}{{{clash_max}}}",
            rf"\newcommand{{\VqRepairStuckFreeMin}}{{{rng('lessons_freeing_a_place')[0]}}}",
            rf"\newcommand{{\VqRepairStuckFreeMax}}{{{rng('lessons_freeing_a_place')[1]}}}",
            rf"\newcommand{{\VqRepairContinuedValid}}{{{freed}}}"] + empty_macros


def _veloxq_empty_start(answers: list) -> tuple:
    """The same repair from an empty timetable, once per instance (the null-seed control of
    21.10.2026), and its k = 3 continuation of the instance it leaves invalid: the per-tier rows
    of the lower part of tab_veloxq_repair.tex, computed from the deposited run records with
    scripts/analyze_veloxq_repair.py as for the answers (``answers``: repair_calls.csv), and the
    in-text numbers. Every sentence they feed is guarded."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import analyze_veloxq_repair as ar
    rdir = VELOXQ / "repair"
    run, cont = rdir / "S3_room_set_rows_empty_start", rdir / "S3_room_set_rows_empty_start_k3_targeted"
    opts = json.loads((run / "settings.json").read_text(encoding="utf-8"))
    base = json.loads((rdir / "S3_room_set_rows" / "settings.json").read_text(encoding="utf-8"))
    keys = ("setting", "ks", "candidate_shortlist_k", "max_outer_passes", "max_wall_seconds_per_pass", "extra")
    if not opts.get("empty_start") or any(opts[k] != base[k] for k in keys):
        die("empty start: not the repair of Table tab:repair from an empty timetable")
    cont_opts = json.loads((cont / "settings.json").read_text(encoding="utf-8"))
    cont_base = json.loads((rdir / "S3_room_set_rows_k3_targeted" / "settings.json").read_text(encoding="utf-8"))
    if cont_opts.get("input_run") != run.name or any(cont_opts[k] != cont_base[k] for k in keys):
        die("empty start: its continuation is not the k = 3 continuation of the answers")
    optima = {}
    for r in read_csv(VELOXQ / "analysis" / "energy_separation.csv"):
        optima.setdefault(r["instance"], float(r["E_opt"]))
    calls = ar.calls_of(run, optima)
    if sorted(c["instance"] for c in calls) != sorted({r["instance"] for r in answers}) \
            or any(c["rep"] for c in calls):
        die("empty start: not one call (call 0) per instance of the answers")
    if not all(c["converged"] for c in calls):
        die("empty start: a call stopped before converging")
    tiers = {r["tier"]: r for r in ar.tiers_of(calls)}

    def greedy_zero(stats_file: Path) -> bool:
        first = json.loads(stats_file.read_text(encoding="utf-8"))["cycles"][0]
        if first["name"] != "H1_greedy_repair":
            die(f"{stats_file.name}: the repair does not start with H1")
        return first["violations_out"] == 0

    empty_h1 = {c["instance"]: greedy_zero(run / "rep_0" / f"{c['instance']}_stats.json") for c in calls}
    answer_h1 = collections.Counter(
        r["instance"].split("_")[0] for r in answers
        if greedy_zero(rdir / "S3_room_set_rows" / f"rep_{r['rep']}" / f"{r['instance']}_stats.json"))
    # The prose: every easy, medium and hard empty start is valid, and H1 alone leaves it no violation;
    # from the answers H1 alone never does so on the extreme tier.
    for c in calls:
        if c["tier"] != "extreme" and not (c["full"] and empty_h1[c["instance"]]):
            die(f"empty start: {c['instance']} is not valid with no violation after H1 alone")
    if answer_h1["extreme"]:
        die("from an answer, H1 alone leaves an extreme call no violation: the prose says none")

    # The weighted objective, empty start against each valid repaired answer of the instance
    # (both valid), and against the best of them.
    objective = collections.defaultdict(list)
    for r in answers:
        if r["full"] == "True":
            objective[r["instance"]].append(float(r["objective"]))
    pairs = {t: [0, 0, 0] for t in TIERS}    # empty start lower, higher, comparisons
    best = {t: [0, 0, 0] for t in TIERS}     # best repaired answer lower, higher, instances
    for c in calls:
        if not (c["full"] and objective[c["instance"]]):
            continue
        e, b = c["objective"], min(objective[c["instance"]])
        for a in objective[c["instance"]]:
            pairs[c["tier"]][0] += e < a - 1e-6
            pairs[c["tier"]][1] += e > a + 1e-6
            pairs[c["tier"]][2] += 1
        best[c["tier"]][0] += b < e - 1e-6
        best[c["tier"]][1] += b > e + 1e-6
        best[c["tier"]][2] += 1
    if any(min(pairs[t][:2]) == 0 for t in ("medium", "hard", "extreme")):
        die("empty start: one start is lower in every comparison of a tier; the prose says neither")
    if any(best[t][0] <= best[t][1] for t in ("hard", "extreme")):
        die("empty start: the best repaired answer is not lower more often on the hard and extreme tiers")

    # The instance it leaves invalid: one course without its lesson, as two repaired answers of the
    # same instance; the continuation at k = 3 does not free it.
    invalid = [c for c in calls if not c["full"]]
    continued = ar.calls_of(cont, optima)
    if [c["instance"] for c in invalid] != ["extreme_014_seed_1140"] \
            or [c["instance"] for c in continued] != ["extreme_014_seed_1140"] or continued[0]["full"]:
        die("empty start: the prose names extreme_014 seed 1140 as the one invalid instance, not freed at k = 3")
    stem = invalid[0]["instance"]
    lessons = {int(r["lessons"]) for r in answers if r["instance"] == stem and r["full"] == "True"}
    if invalid[0]["left"] != "PR1_course_minutes=1" or lessons != {invalid[0]["lessons"] + 1} \
            or REPAIR_STUCK_INSTANCES.get(stem) != 2:
        die("empty start: the invalid instance does not fail as two of its repaired answers do")

    macros = [rf"\newcommand{{\VqEmptyValid}}{{{sum(c['full'] for c in calls)}}}",
              rf"\newcommand{{\VqEmptyExtremeValid}}{{{tiers['extreme']['instances_valid']}}}",
              rf"\newcommand{{\VqEmptyGreedyExtreme}}{{{sum(empty_h1[c['instance']] for c in calls if c['tier'] == 'extreme')}}}",
              rf"\newcommand{{\VqAnswerGreedyHard}}{{{answer_h1['hard']}}}",
              rf"\newcommand{{\VqRepairHardCalls}}{{{3 * MANIFEST['hard']}}}",
              rf"\newcommand{{\VqRepairExtremeCalls}}{{{3 * MANIFEST['extreme']}}}"]
    for t, name in (("medium", "Medium"), ("hard", "Hard"), ("extreme", "Extreme")):
        macros += [rf"\newcommand{{\VqEmptyLower{name}}}{{{pairs[t][0]}}}",
                   rf"\newcommand{{\VqEmptyHigher{name}}}{{{pairs[t][1]}}}",
                   rf"\newcommand{{\VqEmptyPairs{name}}}{{{pairs[t][2]}}}"]
    for t, name in (("hard", "Hard"), ("extreme", "Extreme")):
        macros += [rf"\newcommand{{\VqBestLower{name}}}{{{best[t][0]}}}",
                   rf"\newcommand{{\VqBestPairs{name}}}{{{best[t][2]}}}"]
    return tiers, macros


# ===================================================================== 4
# Structure figures: sparsity pattern and per-family non-zero census.
# These replace two earlier PNGs whose axis labels and 20-entry
# "combination" legend were illegible at print size.

FAMILY_LABEL = {
    "PR1": ("PR1 course-hours", "A"),
    "MAX_CHUNKS": ("MC chunk budget", "C"),
    "PR4_lecturers": ("PR4 non-overlap (lect.)", "B"),
    "PR4_students": ("PR4 non-overlap (group)", "B"),
    "mixed_modality": ("PR5 mixed modality", "B"),
    "CONJ_PHASE3": ("ST count / capacity", "C"),
    "y_linking": (r"$y$-linking", "A"),
    "z_linking": (r"$z$-linking", "B"),
    "satisfaction": ("RU2 satisfaction", "--"),
    "time_of_day": ("RU8 time of day", "--"),
    "min_days": ("RU10 active days", "D"),
    "gap": ("RU9 idle-time markers", "B"),
    "lecture_before": ("RU6 lecture-before", "B"),
}
PATTERN_COLOUR = {"A": OKABE["red"], "B": OKABE["blue"],
                  "C": OKABE["orange"], "D": OKABE["grey"], "--": OKABE["grey"]}


def fig_family_census(rows):
    """Horizontal bars: new non-zeros each penalty family introduces."""
    ref = "extreme_011_seed_1110"
    sub = [r for r in rows if r["instance"] == ref]
    if not sub:
        die(f"family census: {ref} missing")
    sub = [r for r in sub if int(r["delta_nnz"]) > 0]
    sub.sort(key=lambda r: int(r["delta_nnz"]))
    total = sum(int(r["delta_nnz"]) for r in sub)

    labels = [FAMILY_LABEL.get(r["family"], (r["family"], "--"))[0] for r in sub]
    pats = [FAMILY_LABEL.get(r["family"], (r["family"], "--"))[1] for r in sub]
    vals = [int(r["delta_nnz"]) for r in sub]

    fig, ax = plt.subplots(figsize=(TEXTWIDTH_IN, 2.65))
    ys = np.arange(len(sub))
    ax.barh(ys, vals, height=0.68,
            color=[PATTERN_COLOUR[p] for p in pats], edgecolor="none")
    for y, v in zip(ys, vals):
        ax.text(v * 1.06, y, f"{v:,}".replace(",", " ") +
                f"  ({100*v/total:.0f}\\%)".replace("\\%", "%"),
                va="center", fontsize=7.2)
    ax.set_yticks(ys)
    ax.set_yticklabels(labels, fontsize=7.6)
    ax.set_xscale("log")
    ax.set_xlim(1, total * 30)
    ax.set_xlabel(r"new $Q$ entries contributed, diagonal included (log)")
    ax.grid(axis="y", visible=False)
    handles = [plt.Rectangle((0, 0), 1, 1, color=PATTERN_COLOUR[p])
               for p in ("A", "C", "B", "D")]
    ax.legend(handles,
              ["(A) squared deviation", "(C) slack inequality",
               "(B) quadratic products", "diagonal terms"],
              frameon=False, fontsize=7, loc="upper center",
              bbox_to_anchor=(0.5, -0.30), ncol=4, columnspacing=1.1,
              handlelength=1.0, handletextpad=0.4, borderpad=0.0)
    ax.set_xlim(1, total * 8)
    fig.tight_layout(pad=0.3)
    fig.savefig(HERE / "fig_family_census.pdf")
    plt.close(fig)
    print("[make_figures] wrote fig_family_census.pdf")


def fig_sparsity():
    """Clean spy plot of two compiled matrices, with the block split marked: the
    S0 matrices of the VeloxQ runs, as deposited."""
    import h5py
    cache = S0_CACHES
    panels = [("medium_004_seed_1040", "medium tier"),
              ("extreme_011_seed_1110", "extreme tier")]
    fig, axes = plt.subplots(1, 2, figsize=(TEXTWIDTH_IN, 2.65))
    for ax, (stem, title) in zip(axes, panels):
        f = cache / f"{stem}.qubo_cache.h5"
        if not f.exists():
            die(f"fig_sparsity: {f} missing")
        with h5py.File(f, "r") as h:
            g = h["qubo"]
            n = int(g.attrs["n_vars"])
            rowi = np.asarray(g["Q_i"])
            colj = np.asarray(g["Q_j"])
            n_dec = int(np.asarray(h["x_index"]["idx"]).max()) + 1
        off = rowi != colj
        msize = 0.9 if n < 3000 else 0.45
        ax.scatter(colj[off], rowi[off], s=msize, marker="s",
                   color="#12355B", alpha=0.85, linewidths=0, rasterized=True)
        ax.scatter(rowi[off], colj[off], s=msize, marker="s",
                   color="#12355B", alpha=0.85, linewidths=0, rasterized=True)
        if n_dec:
            for pos in (n_dec,):
                ax.axhline(pos, color=OKABE["red"], lw=0.7, ls="--")
                ax.axvline(pos, color=OKABE["red"], lw=0.7, ls="--")
            ax.annotate(r"$x\times x$", xy=(n_dec * 0.5, n_dec * 0.5),
                        fontsize=7, ha="center", va="center",
                        bbox=dict(boxstyle="round,pad=0.16", fc="white",
                                  ec=OKABE["grey"], lw=0.4, alpha=0.92))
            ax.annotate("slack / linking", xy=((n + n_dec) * 0.5, (n + n_dec) * 0.5),
                        fontsize=7, ha="center", va="center",
                        bbox=dict(boxstyle="round,pad=0.16", fc="white",
                                  ec=OKABE["grey"], lw=0.4, alpha=0.92))
        dens = 100.0 * off.sum() / (n * (n - 1) / 2)
        ax.set_xlim(0, n); ax.set_ylim(n, 0)
        ax.set_aspect("equal")
        nstr = f"{n:,}".replace(",", "\u2009")
        ax.set_title(f"{title}  ($n={nstr}$, {dens:.2f}% dense)",
                     loc="left", fontsize=7.8, pad=4)
        ax.set_xlabel("column $j$")
        ax.locator_params(nbins=4)
        ax.grid(False)
    axes[0].set_ylabel("row $i$")
    fig.tight_layout(pad=0.3, w_pad=1.6)
    fig.savefig(HERE / "fig_sparsity.pdf", dpi=700)
    plt.close(fig)
    print("[make_figures] wrote fig_sparsity.pdf")


# ===================================================================== 5
# Penalty table generated from the metadata stored INSIDE each compiled
# matrix, so the paper cannot quote a coefficient the solved QUBO did not use.

LAMBDA_ROWS = [
    # (symbol, family, pattern, config key)
    (r"$\Lambda_1$", "PR1 course-hours equality", "A", "Lambda_PR1"),
    (r"$\Lambda_2$", "MC chunk budget", "C", "Lambda_MC"),
    (r"$\Lambda_3$", "PR3/PR4 non-overlap", "B", "Lambda_nonoverlap"),
    (r"$\Lambda_4$", "PR5 mixed modality", "B", "Lambda_mix"),
    (r"$\Lambda_5$", "ST room count and capacity", "C", "Lambda_room"),
    (r"$\Lambda_y$", r"$y$-linking", "A", "Lambda_y"),
    (r"$\Lambda_z$", r"$z$-linking", "B", "Lambda_z"),
    (r"$\Lambda_{\mathrm{idle}}$", "RU9 idle-time markers", "B", "Lambda_idle_marker"),
    (r"$\alpha$", "RU6 lecture-before", "B", "alpha_lecture_before"),
    (r"$\gamma$", "RU9 idle time, per minute", "--", "gamma_gap_per_minute"),
    (r"$\delta$", "RU10 active days, per group and day", "--", "delta_days_per_group"),
]
# Keys of terms added after some matrices were compiled (exact idle time,
# 08.10.2026): a row is left out when no cache has its key -- those matrices
# do not contain the term -- and an error when only some have it.
LAMBDA_LATER = {"Lambda_idle_marker"}
# Family switches read from the same metadata, so "off" labels cannot drift
# from what the solved matrices actually contain.
LAMBDA_ENABLE = {"Lambda_mix": "enable_mixed_modality",
                 "alpha_lecture_before": "enable_lecture_before"}
# The two matrices of the table: the configured encoding of the synthetic suite
# (any S0 matrix: the configuration does not depend on the instance) and the
# 3_studies matrix of the S3 runs, the one the solver received.
LAMBDA_COLUMNS = [
    (r"synthetic (S0)", ROOT / "repository_ready" / "veloxq_synthetic" / "S0" / "caches"
     / "easy_000_seed_1000.qubo_cache.h5"),
    (r"\texttt{3\_studies} (S3)", ART / UPLOADED_3STUDIES / "caches" / "3_studies_instance.qubo_cache.h5"),
]


def _room_coefficient(c):
    """Lambda_5 of a matrix: the own coefficients of the room-count and the
    room-capacity rows, each falling back to Lambda_room (as the compiler does)."""
    count = c.get("Lambda_room_count")
    cap = c.get("Lambda_room_capacity")
    return (c["Lambda_room"] if count is None else count,
            c["Lambda_room"] if cap is None else cap)


def tab_lambdas():
    try:
        import h5py
        import hashlib
        import json as _json
    except ImportError:
        print("[make_figures] h5py missing; skipping tab_lambdas")
        return

    def config_of(path):
        with h5py.File(path, "r") as h:
            md = _json.loads(h.attrs.get("metadata", "{}"))
        return md.get("config", md.get("qubo_config", {}))

    cols, cfgs = [], []
    for name, f in LAMBDA_COLUMNS:
        if not f.exists():
            print(f"[make_figures] {f.relative_to(ROOT)} missing; skipping tab_lambdas")
            return
        cols.append(name)
        cfgs.append(config_of(f))
    # The synthetic column stands for every S0 matrix.
    keys = [k for *_, k in LAMBDA_ROWS] + ["satisfaction_weights", "tod_weights"]
    for f in sorted(LAMBDA_COLUMNS[0][1].parent.glob("*.qubo_cache.h5")):
        c = config_of(f)
        if any(c.get(k) != cfgs[0].get(k) for k in keys) or _room_coefficient(c) != _room_coefficient(cfgs[0]):
            die(f"tab_lambdas: {f.name} has other coefficients than the synthetic column")
    check_uploaded(hashlib.sha256(LAMBDA_COLUMNS[1][1].read_bytes()).hexdigest(),
                   "tab_lambdas, 3_studies column")

    def num(v):
        v = float(v)
        if abs(v - round(v)) < 1e-9:
            return fmt(v, 0)
        return fmt(v, 1) if abs(v) >= 100 else f"{v:.3g}"

    L = [r"\setlength{\tabcolsep}{4pt}\small",
         r"\begin{tabular}{@{}llcrr@{}}", r"\toprule",
         r"symbol & family & pattern & " + " & ".join(cols) + r" \\",
         r"\midrule"]
    for sym, fam, pat, key in LAMBDA_ROWS:
        if key in LAMBDA_LATER and not any(c.get(key) is not None for c in cfgs):
            continue
        vals = []
        for c in cfgs:
            if key not in c:
                die(f"tab_lambdas: {key} absent from cache metadata")
            if key == "Lambda_room":
                # The caption: Lambda_5 is the coefficient of both room rows.
                count, cap = _room_coefficient(c)
                if count != cap:
                    die(f"tab_lambdas: room-count {count} and room-capacity {cap} coefficients differ")
                vals.append(f"${num(count)}$")
            else:
                vals.append(f"${num(c[key])}$")
        ek = LAMBDA_ENABLE.get(key)
        if ek is not None:
            flags = [bool(c.get(ek, True)) for c in cfgs]
            if not any(flags):
                fam = fam + " (off in runs)"
            elif not all(flags):
                fam = fam + " (on only in " + ", ".join(
                    cname for cname, f in zip(cols, flags) if f) + ")"
        L.append(f"{sym} & {fam} & {pat} & " + " & ".join(vals) + r" \\")
    sat = [c.get("satisfaction_weights", {}) for c in cfgs]
    tod = [c.get("tod_weights", {}) for c in cfgs]
    L.append(r"\midrule")
    L.append(r"$a_{p,t}$ & RU2 desiderata reward (pref./undes./other) & -- & " +
             " & ".join(f"${int(x.get('preferred',0))}/{int(x.get('undesired',0))}/{int(x.get('neutral',0))}$"
                        for x in sat) + r" \\")
    L.append(r"$w_t$ & RU8 time of day (morn./aft./eve.) & -- & " +
             " & ".join(f"${x.get('morning',0):g}/{x.get('afternoon',0):g}/{x.get('evening',0):+g}$"
                        for x in tod) + r" \\")
    L += [r"\bottomrule", r"\end{tabular}"]
    (HERE / "tab_lambdas.tex").write_text("\n".join(L) + "\n")
    print("[make_figures] wrote tab_lambdas.tex")


# ===================================================================== 5b
# Setting S3 on 3_studies (19.10.2026): the VeloxQ answers (artifacts/campaign/
# veloxq_3studies), their repair and the same repair from an empty timetable
# (artifacts/campaign/veloxq_3studies_ls), all kept in this private repository.
REPAIR_3STUDIES = "campaign/veloxq_3studies_ls"      # under artifacts/
NUMBER_WORDS = {0: "no", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
LEFT_WORDS = {"PR1_course_minutes": "hours", "MC_max_chunks": "blocks",
              "PR3_PR4_lecturer_overlap": "clashes", "PR3_PR4_group_overlap": "clashes",
              "RU2_lecturer_availability": "availability", "PR2_lecturer_assigned": "admissibility",
              "CONJ_PHASE3_room_count": "room screen", "CONJ_PHASE3_room_capacity": "room screen",
              "BREAK_lecturer": "breaks", "BREAK_group": "breaks", "PR5_mixed_modality": "PR5",
              "room_set_count": "room rows", "room_set_capacity": "room rows"}


def _same_file(path, sha256):
    """The file's bytes hash to ``sha256``, allowing for the line endings git
    may have changed on checkout."""
    import hashlib
    raw = path.read_bytes()
    lf = raw.replace(b"\r\n", b"\n")
    return sha256 in {hashlib.sha256(b).hexdigest() for b in (raw, lf, lf.replace(b"\n", b"\r\n"))}


def tab_veloxq_3studies():
    """tab_veloxq_3studies.tex and the in-text numbers of the S3 runs on
    3_studies; {} (and no table) without their outputs."""
    import hashlib
    import yaml
    run_dir, ls_dir = ART / UPLOADED_3STUDIES, ART / REPAIR_3STUDIES
    answers = sorted(run_dir.glob("rep_*/3_studies_instance_velox_solution.yaml"))
    if not answers or not ls_dir.exists():
        print("[make_figures] 3_studies S3 outputs missing; skipping tab_veloxq_3studies")
        return {}
    check_uploaded(hashlib.sha256((run_dir / "caches" / "3_studies_instance.qubo_cache.h5")
                                  .read_bytes()).hexdigest(), "3_studies S3 runs")
    calls = {}
    for path in answers:
        with open(path, encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
        md = doc["metadata"]
        ver = md["verifier"]
        calls[int(path.parent.name.split("_")[1])] = {
            "path": path, "lessons": len(doc["lessons"]), "verifier": ver,
            "solver_s": float(md["phase2"]["veloxq_solver_time_seconds"]),
            "steps": int(md["veloxq"]["num_steps"]), "reps": int(md["veloxq"]["num_rep"])}
    if len({(c["steps"], c["reps"]) for c in calls.values()}) != 1:
        die("3_studies S3: the calls ran with different budgets")

    def repair(run, empty_start):
        """The repair run's settings checked against the prose, then its rows."""
        settings = json.loads((ls_dir / run / "settings.json").read_text(encoding="utf-8"))
        same = (settings["setting"] == "S3" and settings["ks"] == [1, 2]
                and settings["candidate_shortlist_k"] == 10 and settings["extra"] == ["--room-set-rows"]
                and settings["max_outer_passes"] == "none" and settings["max_wall_seconds_per_pass"] == "none"
                and bool(settings.get("empty_start")) == empty_start)
        if not same:
            die(f"3_studies S3: {run} did not run with the settings of Table tab:repair")
        out = {}
        for r in read_csv(ls_dir / run / "summary.csv"):
            rep = int(r["rep"])
            d = ls_dir / run / f"rep_{rep}"
            verdict = json.loads((d / "3_studies_instance_postLS_verdict.json").read_text(encoding="utf-8"))
            with open(d / "3_studies_instance_postLS.yaml", encoding="utf-8") as fh:
                meta = (yaml.safe_load(fh) or {})["metadata"]
            stats = json.loads((d / "3_studies_instance_stats.json").read_text(encoding="utf-8"))
            full = verdict["statuses"]["full"] is True
            if full != (r["full"] == "True"):
                die(f"3_studies S3: {run} rep {rep}: the summary and the verdict disagree")
            if not empty_start and not _same_file(calls[rep]["path"], meta["source_solution_file"]["sha256"]):
                die(f"3_studies S3: the repair of call {rep} did not start from its answer file")
            left = collections.Counter()
            for counts in (verdict["violations_by_constraint"], verdict["extra_violations_by_rule"],
                           meta["final"]["room_set_rows_exceeded"]):
                for k, n in counts.items():
                    left[LEFT_WORDS[k]] += int(n)
            if not verdict["statuses"]["rooms"]:
                left["rooms"] += 1
            out[rep] = {"before": int(r["violations_before"]), "after": int(r["violations_after"]),
                        "lessons": int(verdict["lessons"]), "full": full,
                        "left": ", ".join(f"{w} {n}" for w, n in left.items() if n),
                        "objective": float(meta["final"]["soft_objective"]) if full else None,
                        "terms": meta["final"]["soft_objective_terms"] if full else None,
                        "minutes": float(r["ls_wall_s"]) / 60,
                        "to_valid": float(r["ls_time_to_zero_s"]) / 60 if r["ls_time_to_zero_s"] else None,
                        "cycles": stats["cycles"]}
        return out

    fixed = repair("S3_room_set_rows", False)
    empty = repair("S3_room_set_rows_empty_start", True)
    if sorted(fixed) != sorted(calls) or sorted(empty) != [0]:
        die("3_studies S3: the repair runs do not cover the five calls and one empty start")
    e = empty[0]

    # The prose: no answer is valid; exactly one repaired answer is; the empty start
    # is valid, better and with fewer idle minutes and less satisfaction; every run
    # ends with a second pass that changes nothing; single-lesson moves take seconds.
    if any(c["verifier"]["statuses"]["full"] for c in calls.values()):
        die("3_studies S3: a VeloxQ answer is valid; the prose says none is")
    valid = [rep for rep, x in fixed.items() if x["full"]]
    if len(valid) != 1 or not e["full"]:
        die(f"3_studies S3: valid repairs {valid}, empty start {e['full']}; the prose says one and yes")
    best = fixed[valid[0]]
    idle = lambda x: x["terms"]["min_gaps_students"]
    sat = lambda x: -x["terms"]["lecturers_satisfaction"]
    if not (e["objective"] < best["objective"] and idle(e) < idle(best) and sat(e) < sat(best)):
        die("3_studies S3: the comparison of the two valid timetables is not the one the prose states")
    for x in list(fixed.values()) + [e]:
        if any(c["improvement_violations"] or c["improvement_second_key"] for c in x["cycles"]
               if c["outer_pass"] == 2) or x["cycles"][-1]["outer_pass"] != 2:
            die("3_studies S3: a run did not end with a second pass that changes nothing")
    single = [c for x in fixed.values() for c in x["cycles"] if c["name"] == "H2_k=1" and c["outer_pass"] == 1]
    h1 = e["cycles"][0]
    if h1["name"] != "H1_greedy_repair" or h1["placements_out"] != 130 or h1["violations_out"] != 1:
        die("3_studies S3: from the empty timetable H1 does not place 130 lessons and leave one violation")

    stuck = [x for x in fixed.values() if not x["full"]]
    clash = [c["verifier"]["violations_by_constraint"]["PR3_PR4_lecturer_overlap"]
             + c["verifier"]["violations_by_constraint"]["PR3_PR4_group_overlap"] for c in calls.values()]
    rule = lambda k: [c["verifier"]["violations_by_constraint"][k] for c in calls.values()]
    deleted = [calls[rep]["lessons"] - x["lessons"] for rep, x in fixed.items()]
    # Lessons the greedy fill (H1) adds to each answer before the k-OPT moves.
    if any(x["cycles"][0]["name"] != "H1_greedy_repair" for x in fixed.values()):
        die("3_studies S3: a repair of an answer does not start with H1")
    greedy = [x["cycles"][0]["placements_out"] - x["cycles"][0]["placements_in"] for x in fixed.values()]
    # How many of the solver's lessons (same course, lecturer, day and time) the
    # repaired timetables keep: scripts/analyze_answer_overlap.py.
    overlap = {int(r["rep"]): r for r in read_csv(ART / "answer_overlap_S3.csv")
               if r["tier"] == "3_studies"}
    if sorted(overlap) != sorted(fixed) or any(
            int(overlap[rep]["answer_lessons"]) != calls[rep]["lessons"]
            or int(overlap[rep]["final_lessons"]) != fixed[rep]["lessons"] for rep in fixed):
        die("3_studies S3: answer_overlap_S3.csv does not match the answers and their repairs")
    kept = [int(overlap[rep]["kept_exact"]) for rep in fixed]

    L = [r"\setlength{\tabcolsep}{4pt}\small",
         r"\begin{tabular}{@{}lrrrrlcrr@{}}", r"\toprule",
         r" & \multicolumn{2}{c}{start} & \multicolumn{6}{c}{after the repair} \\",
         r"\cmidrule(lr){2-3}\cmidrule(lr){4-9}",
         r"start & lessons & violations & violations & lessons & left & valid & objective & time (min) \\",
         r"\midrule"]

    def line(label, lessons0, x):
        obj = f"${fmt(x['objective'])}$" if x["full"] else "--"
        L.append(f"{label} & ${lessons0}$ & ${x['before']}$ & ${x['after']}$ & ${x['lessons']}$ & "
                 f"{x['left'] or '--'} & {'yes' if x['full'] else 'no'} & {obj} & "
                 f"${fmt(x['minutes'])}$ \\\\")

    for rep in sorted(fixed):
        line(f"call {rep}", calls[rep]["lessons"], fixed[rep])
    L.append(r"\midrule")
    line("empty timetable", 0, e)
    L += [r"\bottomrule", r"\end{tabular}"]
    (HERE / "tab_veloxq_3studies.tex").write_text("\n".join(L) + "\n")
    print("[make_figures] wrote tab_veloxq_3studies.tex")

    c0 = next(iter(calls.values()))
    return {
        "ProdSThreeCalls": str(len(calls)),
        "ProdSThreeSteps": fmt(c0["steps"]),
        "ProdSThreeReps": fmt(c0["reps"]),
        "ProdSThreeSolverMin": fmt(stats.mean(c["solver_s"] for c in calls.values()) / 60),
        "ProdSThreeLessonsLo": str(min(c["lessons"] for c in calls.values())),
        "ProdSThreeLessonsHi": str(max(c["lessons"] for c in calls.values())),
        "ProdSThreeHoursLo": str(min(rule("PR1_course_minutes"))),
        "ProdSThreeHoursHi": str(max(rule("PR1_course_minutes"))),
        "ProdSThreeBlocksLo": str(min(rule("MC_max_chunks"))),
        "ProdSThreeBlocksHi": str(max(rule("MC_max_chunks"))),
        "ProdSThreeClashLo": str(min(clash)),
        "ProdSThreeClashHi": str(max(clash)),
        "ProdSThreeRoomsWord": NUMBER_WORDS[sum(bool(c["verifier"]["statuses"]["rooms"])
                                                for c in calls.values())],
        "ProdSThreeSingleSecMax": fmt(max(c["wall_seconds"] for c in single)),
        "ProdSThreeAfterSingleLo": str(min(c["violations_out"] for c in single)),
        "ProdSThreeAfterSingleHi": str(max(c["violations_out"] for c in single)),
        "ProdSThreeDeletedLo": str(min(deleted)),
        "ProdSThreeDeletedHi": str(max(deleted)),
        "ProdSThreeGreedyLo": str(min(greedy)),
        "ProdSThreeGreedyHi": str(max(greedy)),
        "ProdSThreeKeptLo": str(min(kept)),
        "ProdSThreeKeptHi": str(max(kept)),
        "ProdSThreeRepairMinLo": fmt(min(x["minutes"] for x in fixed.values())),
        "ProdSThreeRepairMinHi": fmt(max(x["minutes"] for x in fixed.values())),
        "ProdSThreeValidCall": str(valid[0]),
        "ProdSThreeStuckWord": NUMBER_WORDS[len(stuck)],
        "ProdSThreeStuckLo": str(min(x["after"] for x in stuck)),
        "ProdSThreeStuckHi": str(max(x["after"] for x in stuck)),
        "ProdSThreeAnswerObjective": fmt(best["objective"]),
        "ProdSThreeAnswerToValidMin": fmt(best["to_valid"]),
        "ProdSThreeEmptyObjective": fmt(e["objective"]),
        "ProdSThreeEmptyMin": fmt(e["minutes"]),
        "ProdSThreeEmptyToValidMin": fmt(e["to_valid"]),
        "ProdSThreeIdleAnswer": fmt(idle(best)),
        "ProdSThreeIdleEmpty": fmt(idle(e)),
        "ProdSThreeSatAnswer": fmt(sat(best)),
        "ProdSThreeSatEmpty": fmt(sat(e)),
    }


# ===================================================================== 6
# Re-drawn inherited figures (vector, house style). Each reads its numbers
# from the single place they already live, never from a new transcription.

def fig_synth_feasibility():
    """Pre/post-LS feasibility and violations of the MAIN benchmark run,
    read per instance from the repair stage's own summary."""
    rows = read_csv(ART / "local_search_results" / "synthetic_demo" / "sweep_summary.csv")
    T = by_tier(rows, key="instance_stem")
    for t in TIERS:
        if len(T[t]) != MANIFEST[t]:
            die(f"synth feasibility: tier {t} has {len(T[t])} rows, manifest {MANIFEST[t]}")
    n = {t: len(T[t]) for t in TIERS}
    pre_f = {t: sum(int(r["pre_violations"]) == 0 for r in T[t]) for t in TIERS}
    post_f = {t: sum(int(r["post_violations"]) == 0 for r in T[t]) for t in TIERS}
    pre_v = {t: sum(int(r["pre_violations"]) for r in T[t]) for t in TIERS}
    post_v = {t: sum(int(r["post_violations"]) for r in T[t]) for t in TIERS}
    fig, axes = plt.subplots(1, 2, figsize=(TEXTWIDTH_IN, 2.2))
    xs = np.arange(len(TIERS)); w = 0.36
    c_pre, c_post = OKABE["grey"], OKABE["blue"]

    ax = axes[0]
    for off, d, c, lab, hatch in [(-w/2, pre_f, c_pre, "solver only", "//"),
                                  (w/2, post_f, c_post, "after repair", None)]:
        vals = [100.0 * d[t] / n[t] for t in TIERS]
        ax.bar(xs + off, vals, w, color=c, edgecolor="white", linewidth=0.5,
               hatch=hatch, label=lab)
        for x, t, v in zip(xs + off, TIERS, vals):
            ax.text(x, v + 2, f"{d[t]}", ha="center", va="bottom", fontsize=6.8)
    ax.set_xticks(xs); ax.set_xticklabels(TIERS)
    ax.set_ylim(0, 115); ax.set_ylabel("instances feasible [%]")
    ax.set_title("(a) feasibility", loc="left")


    ax = axes[1]
    for off, d, c, hatch in [(-w/2, pre_v, c_pre, "//"), (w/2, post_v, c_post, None)]:
        vals = [d[t] for t in TIERS]
        ax.bar(xs + off, vals, w, color=c, edgecolor="white", linewidth=0.5, hatch=hatch)
        for x, v in zip(xs + off, vals):
            ax.text(x, max(v, 0.0) * 1.15 + (0.06 if v == 0 else 0), f"{v}",
                    ha="center", va="bottom", fontsize=6.8)
    ax.set_yscale("symlog", linthresh=1)
    ax.set_ylim(0, 900)
    ax.set_xticks(xs); ax.set_xticklabels(TIERS)
    ax.set_ylabel(r"$\Sigma V$ (hard violations)")
    ax.set_title("(b) residual violations", loc="left")
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, frameon=False, fontsize=7, ncol=2, loc="upper center",
               bbox_to_anchor=(0.5, 1.04))
    fig.tight_layout(pad=0.3, w_pad=1.5, rect=(0, 0, 1, 0.93))
    fig.savefig(HERE / "fig2_synth_feasibility.pdf")
    plt.close(fig)
    print("[make_figures] wrote fig2_synth_feasibility.pdf")
    return n, pre_f, post_f


def _lato_rows():
    """LATO head-to-head data, imported from the authors' own plot script."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "plot_vqls_vs_milp", ROOT / "scripts" / "plot_vqls_vs_milp.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.ROWS, getattr(mod, "MILP_OBJ_SCALE", 1.0)


def fig_vqls_vs_milp():
    rows, scale = _lato_rows()
    qubo = [r for r in rows if not r["label"].startswith("MILP")]
    milp = sorted([r for r in rows if r["label"].startswith("MILP")],
                  key=lambda r: r["runtime_s"])
    snap = [r["label"].split("—")[-1].strip() for r in milp]
    panels = [("gap_min", "student gap minutes", 1.0),
              ("days_grp", "days per group", 1.0),
              ("qubo_E", r"QUBO energy $[10^{7}]$", 1e-7),
              ("milp_obj", "MILP weighted objective", scale)]
    fig, axes = plt.subplots(2, 2, figsize=(TEXTWIDTH_IN, 3.6), sharex=True)
    for ax, (key, lab, k), tag in zip(axes.flat, panels, "abcd"):
        xm = [r["runtime_s"] for r in milp]; ym = [r[key] * k for r in milp]
        ax.plot(xm, ym, "-", color=OKABE["orange"], lw=1.1, zorder=2)
        ax.scatter(xm, ym, s=22, color=OKABE["orange"], edgecolor="white",
                   linewidth=0.6, zorder=3, label="MILP snapshots")
        if tag == "a":
            for i, (x, y, t) in enumerate(zip(xm, ym, snap)):
                ax.annotate(t, (x, y), textcoords="offset points",
                            xytext=(6, 4) if i else (6, -2), ha="left",
                            fontsize=6.2, color=OKABE["grey"])
        for r in qubo:
            ax.scatter(r["runtime_s"], r[key] * k, s=34, marker="s",
                       color=OKABE["blue"], edgecolor="white", linewidth=0.6,
                       zorder=4, label="QUBO+LS")
        ax.set_xscale("log")
        ax.set_title(f"({tag}) {lab}", loc="left", fontsize=8)
        ax.margins(y=0.22)
    for ax in axes[1]:
        ax.set_xlabel("wall time [s] (log)")
    h, l = axes[0, 0].get_legend_handles_labels()
    fig.legend(h[:2], l[:2], frameon=False, fontsize=7, loc="upper center",
               ncol=2, bbox_to_anchor=(0.5, 1.03))
    fig.tight_layout(pad=0.3, h_pad=0.8, w_pad=1.2, rect=(0, 0, 1, 0.95))
    fig.savefig(HERE / "fig_vqls_vs_milp.pdf")
    plt.close(fig)
    print("[make_figures] wrote fig_vqls_vs_milp.pdf  (lower is better in every panel)")


def fig_lato_time_of_day():
    """Morning/afternoon/evening shares of placed lessons on LATO, computed
    from the decoded schedules with the authors' own bucketing
    (scripts/plot_lato_time_of_day.py: morning = start before 12:00)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "plot_lato_time_of_day", ROOT / "scripts" / "plot_lato_time_of_day.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if abs(mod.MORNING_END - 12.0) > 1e-9:
        die("LATO time-of-day: expected a noon morning threshold")
    routes = []
    for r in mod.ROUTES:
        c = mod._shares(r["stem"])["counts"]
        routes.append((r["label"].replace("—", "–"), c["morning"], c["afternoon"], c["evening"]))
    fig, ax = plt.subplots(figsize=(TEXTWIDTH_IN, 1.9))
    cols = [OKABE["sky"], OKABE["blue"], OKABE["orange"]]
    labs = ["before 12:00", "12:00–16:00", "from 16:00"]
    ys = np.arange(len(routes))[::-1]
    for y, (name, m_, a_, e_) in zip(ys, routes):
        tot = m_ + a_ + e_; left = 0.0
        for v, c, lab in zip((m_, a_, e_), cols, labs):
            share = 100.0 * v / tot
            ax.barh(y, share, left=left, color=c, edgecolor="white", linewidth=0.6,
                    label=lab if y == ys[0] else None)
            if share >= 6:
                ax.text(left + share / 2, y, f"{share:.0f}%", ha="center", va="center",
                        fontsize=6.8, color="white" if c != OKABE["sky"] else "black")
            left += share
    ax.set_yticks(ys); ax.set_yticklabels([r[0] for r in routes], fontsize=7.4)
    ax.set_xlim(0, 100); ax.set_xlabel("share of placed lessons [%]")
    ax.grid(axis="y", visible=False)
    ax.legend(frameon=False, fontsize=7, ncol=3, loc="upper center",
              bbox_to_anchor=(0.45, 1.22))
    fig.tight_layout(pad=0.3)
    fig.savefig(HERE / "fig_lato_time_of_day.pdf")
    plt.close(fig)
    print("[make_figures] wrote fig_lato_time_of_day.pdf")


if __name__ == "__main__":
    if sys.argv[1:] == ["--only", "veloxq-settings"]:   # the VeloxQ campaign's floats alone
        tab_veloxq_settings()
        raise SystemExit(0)
    raise SystemExit(main())
