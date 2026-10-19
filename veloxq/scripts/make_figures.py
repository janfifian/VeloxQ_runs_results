#!/usr/bin/env python3
"""
Single source of truth for the paper's generated figures and tables.

Every number that appears in a generated float comes from a CSV under
``artifacts/``; nothing is transcribed by hand. Run from the repo root::

    python3 paper/figures/make_figures.py

Outputs (all written next to this file):

  fig_effort_sweep.pdf        VeloxQ-only feasibility vs solver effort
  fig_frustration.pdf         corrected balance / cycle-frustration profile
  fig_pareto.pdf              MILP vs QUBO+LS across every objective lens
  tab_frustration.tex         corrected structural profile (per-tier medians)
  tab_pareto.tex              Pareto comparison with IQR + paired statistics
  generated_numbers.tex       \\newcommand macros for in-text numbers
  tab_veloxq_settings.tex     VeloxQ campaign: valid timetables per penalty setting
  tab_veloxq_breakdown.tex    VeloxQ campaign: how the solver's answers break
  tab_veloxq_repair.tex       VeloxQ campaign: the repair of the S3 answers
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
def fig_and_tab_frustration(rows):
    T = by_tier(rows)
    for t in TIERS:
        if len(T[t]) != MANIFEST[t]:
            die(f"frustration: tier {t} has {len(T[t])} rows, manifest says "
                f"{MANIFEST[t]}")

    # Guard: the old bug was a column silently equal to another one.
    for r in rows:
        if abs(float(r["minority_sign_frac"]) - float(r["F_UB_ratio"])) < 1e-12:
            die("minority_sign_frac is identical to F_UB_ratio -- "
                "two different metrics must not coincide")

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

    # ---- table
    L = [r"\begin{tabular}{lrrrrrr}", r"\toprule",
         r"tier & $n$ & $|x|$ & $|Q|_{\mathrm{off}}$ & minority-sign "
         r"& $R_F^C$ (BFS) & balanced \\",
         r"\midrule"]
    for t in TIERS:
        r = T[t]
        nb = sum(1 for x in r if x["is_balanced"] == "True")
        L.append(
            f"{t} & ${len(r)}$ & ${fmt(med(r,'n_vars'))}$ & "
            f"${fmt(med(r,'n_quadratic'))}$ & ${med(r,'minority_sign_frac'):.3f}$ & "
            f"${med(r,'RF_C'):.3f}$ & "
            f"${nb}/{len(r)}$ \\\\")
    prod_path = ART / "qubo_frustration_paper_3studies.csv"
    prod = None
    if prod_path.exists():
        prod = read_csv(prod_path)[0]
        L.append(r"\midrule")
        L.append(
            f"\\texttt{{3\\_studies}} & $1$ & ${fmt(float(prod['n_vars']))}$ & "
            f"${fmt(float(prod['n_quadratic']))}$ & "
            f"${float(prod['minority_sign_frac']):.3f}$ & "
            f"${float(prod['RF_C']):.3f}^{{\\dagger}}$ & "
            f"${0 if prod['is_balanced']=='False' else 1}/1$ \\\\")
    L += [r"\bottomrule", r"\end{tabular}"]
    (HERE / "tab_frustration.tex").write_text("\n".join(L) + "\n")
    print("[make_figures] wrote tab_frustration.tex")

    out_extra = {}
    if prod is not None:
        out_extra = {
            "prod_afm": float(prod["frac_afm"]),
            "prod_fm": float(prod["frac_fm"]),
            "prod_rfc": float(prod["RF_C"]),
            "prod_fub": float(prod["F_UB_ratio"]),
            "prod_nvars": int(float(prod["n_vars"])),
            "prod_cycles": int(float(prod["n_cycles_sampled"])),
        }
    return {
        **out_extra,
        "n_balanced": n_bal,
        "n_total": len(rows),
        "rfc_lo": min(float(r["RF_C"]) for r in rows),
        "rfc_hi": max(float(r["RF_C"]) for r in rows),
        "fub_lo": min(float(r["F_UB_ratio"]) for r in rows),
        "fub_hi": max(float(r["F_UB_ratio"]) for r in rows),
        "per_tier": {t: (med(T[t], "RF_C"), med(T[t], "F_UB_ratio"))
                     for t in TIERS},
    }


# ===================================================================== 3
METRICS = [
    # label, milp col, ls col, direction ("min"/"max"), decimals
    (r"$P_4$ satisfaction $\uparrow$", "milp_p6_sat", "ls_p6_sat", "max", 0),
    (r"$P_3$ gap minutes $\downarrow$", "milp_p5_gap", "ls_p5_gap", "min", 0),
    (r"$P_2$ time of day $\downarrow$", "milp_p4_tod", "ls_p4_tod", "min", 0),
    (r"$P_1$ active days $\downarrow$",  "milp_p3_days", "ls_p3_days", "min", 0),
    (r"unified cost $\downarrow$",      "milp_unified", "ls_unified", "min", 0),
]


def paired_stats(rows, mc, lc, direction):
    """Descriptive paired summary of one metric over the instances.

    Returns (rbc_signed, milp_better, ties, ls_better). r_rb is the signed
    matched-pairs rank-biserial correlation, oriented so that POSITIVE means
    QUBO+LS is better on this metric and NEGATIVE means the MILP is:
    r_rb = (W+ - W-) / (W+ + W-) over the ranks of the non-zero paired
    differences, sign-flipped for minimised metrics. Ties (zero differences)
    do not enter r_rb, so r_rb = -1 does not mean the MILP wins every pair;
    the win/tie/loss counts say how often it does. No p-value is reported:
    the instances are nested in generator levels and are not a sample from a
    stated population, so a test would have no defined inferential model.
    """
    from scipy.stats import rankdata
    d = np.array([float(r[lc]) - float(r[mc]) for r in rows])  # LS - MILP
    ls_better_mask = d > 0 if direction == "max" else d < 0
    ties = int(np.sum(d == 0))
    ls_better = int(np.sum(ls_better_mask & (d != 0)))
    milp_better = int(d.size - ties - ls_better)
    nz = d[d != 0]
    if nz.size == 0:
        return 0.0, milp_better, ties, ls_better
    ranks = rankdata(np.abs(nz))
    w_plus, w_minus = float(ranks[nz > 0].sum()), float(ranks[nz < 0].sum())
    rbc = (w_plus - w_minus) / (w_plus + w_minus)
    if direction == "min":              # lower is better: LS better when d < 0
        rbc = -rbc
    return rbc, milp_better, ties, ls_better


def fig_and_tab_pareto(rows):
    T = by_tier(rows, key="instance")
    for t in TIERS:
        if len(T[t]) != MANIFEST[t]:
            die(f"pareto: tier {t} has {len(T[t])} rows, manifest {MANIFEST[t]}")

    # ---- table with IQR and paired statistics over all 64 instances
    L = [r"\setlength{\tabcolsep}{3pt}\small",
         r"\begin{tabular}{@{}l r@{\;}r r@{\;}r r@{\;}r r@{\;}r cc@{}}", r"\toprule",
         r"\multirow{2}{*}{metric}"
         r" & \multicolumn{2}{c}{easy} & \multicolumn{2}{c}{medium}"
         r" & \multicolumn{2}{c}{hard} & \multicolumn{2}{c}{extreme}"
         r" & \multirow{2}{*}{$r_{\mathrm{rb}}$} & pairs won \\",
         r"\cmidrule(lr){2-3}\cmidrule(lr){4-5}\cmidrule(lr){6-7}\cmidrule(lr){8-9}",
         r" & MILP & QUBO$+$LS & MILP & QUBO$+$LS & MILP & QUBO$+$LS"
         r" & MILP & QUBO$+$LS & & M/tie/Q \\",
         r"\midrule"]
    pareto_summary = {}
    raw = {m[1]: paired_stats(rows, m[1], m[2], m[3]) for m in METRICS}
    for label, mc, lc, direction, nd in METRICS:
        cells = []
        vals = []
        for t in TIERS:
            vals += [med(T[t], mc), med(T[t], lc)]
        nd = row_decimals(vals)
        for t in TIERS:
            r = T[t]
            m, l = med(r, mc), med(r, lc)
            better_ls = (l > m) if direction == "max" else (l < m)
            ms, ls_ = fmt(m, nd), fmt(l, nd)
            if abs(m - l) < 1e-9:
                cells += [f"${ms}$", f"${ls_}$"]
            elif better_ls:
                cells += [f"${ms}$", rf"$\mathbf{{{ls_}}}$"]
            else:
                cells += [rf"$\mathbf{{{ms}}}$", f"${ls_}$"]
        rbc, mw, ti, lw = raw[mc]
        pareto_summary[mc] = (rbc, mw, ti, lw)
        L.append(" & ".join([label] + cells + [f"${rbc:+.2f}$", f"${mw}/{ti}/{lw}$"]) + r" \\")
    L += [r"\bottomrule", r"\end{tabular}"]
    (HERE / "tab_pareto.tex").write_text("\n".join(L) + "\n")
    print("[make_figures] wrote tab_pareto.tex")

    # ---- figure, two panels:
    #   (a) ratio, only for metrics that are strictly positive on both routes
    #   (b) paired difference, for the SIGNED metrics where a ratio is
    #       meaningless (time-of-day and the unified cost both cross zero)
    RATIO = [m for m in METRICS if m[1] in
             ("milp_p6_sat", "milp_p5_gap", "milp_p3_days")]
    DIFF = [m for m in METRICS if m[1] in ("milp_p4_tod", "milp_unified")]

    fig, axes = plt.subplots(
        1, 2, figsize=(TEXTWIDTH_IN, 2.3),
        gridspec_kw={"width_ratios": [1.5, 1]})
    rng = np.random.default_rng(0)

    # -- (a) ratios
    ax = axes[0]
    colours = [OKABE["orange"], OKABE["blue"], OKABE["green"]]
    excluded = []
    for i, (label, mc, lc, direction, _) in enumerate(RATIO):
        good, bad = [], 0
        for r in rows:
            m, l = float(r[mc]), float(r[lc])
            if m <= 0 or l < 0:
                bad += 1
                continue
            good.append(l / m)
        if bad:
            excluded.append(f"{label.split()[1]}: {bad}")
        v = np.array(good)
        jitter = (rng.random(v.size) - 0.5) * 0.24
        ax.scatter(np.full(v.size, i) + jitter, v, s=9, color=colours[i],
                   alpha=0.5, edgecolors="none", zorder=3)
        m_ = float(np.median(v))
        ax.plot([i - 0.32, i + 0.32], [m_] * 2, color="black", lw=1.7, zorder=5)
        ax.annotate(f"{m_:.2f}", xy=(i + 0.34, m_), fontsize=7.4, va="center",
                    ha="left", zorder=6,
                    bbox=dict(boxstyle="round,pad=0.12", fc="white",
                              ec="none", alpha=0.85))
    if excluded:
        print(f"[make_figures] pareto ratio panel excluded (non-positive "
              f"denominator or value): {', '.join(excluded)}")
    ax.axhline(1.0, color=OKABE["grey"], lw=0.9, ls="--", zorder=2)
    ax.set_xticks(np.arange(len(RATIO)))
    ax.set_xticklabels([r"lecturer" "\n" r"satisfaction $\uparrow$",
                        r"student gap" "\n" r"minutes $\downarrow$",
                        r"active" "\n" r"days $\downarrow$"], fontsize=7.4)
    ax.set_yscale("log")
    ax.set_ylim(0.13, 7)
    ax.set_yticks([0.25, 0.5, 1, 2, 4])
    ax.set_yticklabels(["0.25", "0.5", "1", "2", "4"])
    ax.set_xlim(-0.55, len(RATIO) - 0.2)
    ax.set_ylabel("QUBO$+$LS $/$ MILP")
    ax.set_title("(a) ratio, strictly positive metrics", loc="left")

    # -- (b) signed metrics: paired difference
    ax = axes[1]
    dcolours = [OKABE["purple"], OKABE["red"]]
    for i, (label, mc, lc, direction, _) in enumerate(DIFF):
        d = np.array([float(r[lc]) - float(r[mc]) for r in rows])
        jitter = (rng.random(d.size) - 0.5) * 0.24
        ax.scatter(np.full(d.size, i) + jitter, d, s=9, color=dcolours[i],
                   alpha=0.5, edgecolors="none", zorder=3)
        m_ = float(np.median(d))
        ax.plot([i - 0.32, i + 0.32], [m_] * 2, color="black", lw=1.7, zorder=5)
        ax.annotate(f"{m_:+,.0f}".replace(",", " "), xy=(i + 0.34, m_),
                    fontsize=7.4, va="center", ha="left", zorder=6,
                    bbox=dict(boxstyle="round,pad=0.12", fc="white",
                              ec="none", alpha=0.85))
    ax.axhline(0.0, color=OKABE["grey"], lw=0.9, ls="--", zorder=2)
    ax.set_yscale("symlog", linthresh=10)
    ax.set_xticks(np.arange(len(DIFF)))
    ax.set_xticklabels([r"time of" "\n" r"day $\downarrow$",
                        r"unified" "\n" r"cost $\downarrow$"], fontsize=7.4)
    ax.set_xlim(-0.6, len(DIFF) + 0.15)
    ax.set_ylabel("QUBO$+$LS $-$ MILP")
    ax.set_title("(b) difference, signed metrics", loc="left")

    fig.tight_layout(pad=0.3, w_pad=1.5)
    fig.savefig(HERE / "fig_pareto.pdf")
    plt.close(fig)
    print("[make_figures] wrote fig_pareto.pdf")
    return pareto_summary


# ===================================================================== main
def main() -> int:
    grid, names = load_sweep()
    tier_feas, steps_vals, reps_vals = fig_effort_sweep(grid, names)

    frows = read_csv(ART / "qubo_frustration_paper_synth.csv")
    fr = fig_and_tab_frustration(frows)

    prows = read_csv(ART / "milp_vs_qubo_soft_cost.csv")
    ps = fig_and_tab_pareto(prows)

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
    if "prod_rfc" in fr:
        M += [
            rf"\newcommand{{\ProdAFM}}{{{fr['prod_afm']:.3f}}}",
            rf"\newcommand{{\ProdFM}}{{{fr['prod_fm']:.3f}}}",
            rf"\newcommand{{\ProdRFC}}{{{fr['prod_rfc']:.2f}}}",
            rf"\newcommand{{\ProdFUB}}{{{fr['prod_fub']:.2f}}}",
            rf"\newcommand{{\ProdCycles}}{{{fr['prod_cycles']:,}}}".replace(",", "{,}"),
        ]
    # LaTeX control sequences may not contain digits.
    RBC_NAME = {
        "milp_p6_sat": "RbcSat",
        "milp_p5_gap": "RbcGap",
        "milp_p4_tod": "RbcTod",
        "milp_p3_days": "RbcDays",
        "milp_unified": "RbcUnified",
    }
    for mc, (rbc, mw, ti, lw) in ps.items():
        base = RBC_NAME[mc][3:]
        M.append(rf"\newcommand{{\{RBC_NAME[mc]}}}{{{rbc:+.2f}}}")
        M.append(rf"\newcommand{{\WinMilp{base}}}{{{mw}}}")
        M.append(rf"\newcommand{{\Tie{base}}}{{{ti}}}")
        M.append(rf"\newcommand{{\WinLs{base}}}{{{lw}}}")
    # Main benchmark run (seeds handed to the repair stage), kept apart from the
    # effort-sweep numbers above.
    n_main, pre_main, post_main = fig_synth_feasibility()
    M.append(rf"\newcommand{{\MainFeasPre}}{{{sum(pre_main.values())}}}")
    M.append(rf"\newcommand{{\MainFeasPost}}{{{sum(post_main.values())}}}")
    for t in TIERS:
        M.append(rf"\newcommand{{\MainFeas{t.capitalize()}}}{{{pre_main[t]}/{n_main[t]}}}")
    (HERE / "generated_numbers.tex").write_text("\n".join(M) + "\n")
    fig_family_census(read_csv(ART / "qubo_family_census.csv"))
    fig_sparsity()
    tab_lambdas()
    tab_penalty_sufficiency()
    tab_veloxq_settings()
    fig_vqls_vs_milp()
    fig_lato_time_of_day()
    print("[make_figures] wrote generated_numbers.tex")
    print("[make_figures] done.")
    return 0




# ===================================================================== 5b
# Penalty sufficiency (penalty re-check, 08.10.2026): the configured penalty
# over the value it must exceed, smallest over each tier's instances, read from
# checks/penalty_sufficiency.py's CSV.

SUFFICIENCY_ROWS = [
    (r"$\Lambda_1$", "PR1 course hours", "Lambda_PR1"),
    (r"$\Lambda_2$", "MC chunk limit", "Lambda_MC"),
    (r"$\Lambda_3$", "PR3/PR4 non-overlap", "Lambda_nonoverlap"),
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


def tab_penalty_sufficiency():
    path = ART / "penalty_recheck" / "penalty_sufficiency.csv"
    if not path.exists():
        print("[make_figures] penalty_sufficiency.csv missing; skipping tab_penalty_sufficiency")
        return
    rows = read_csv(path)
    cols = [t for t in (*TIERS, "3_studies") if any(r["tier"] == t for r in rows)]
    worst = {}
    for r in rows:
        if r["ratio"] in ("", "None"):
            continue
        k = (r["key"], r["tier"])
        worst[k] = min(worst.get(k, float("inf")), float(r["ratio"]))
    L = [r"\setlength{\tabcolsep}{4pt}\small",
         r"\begin{tabular}{@{}ll" + "r" * len(cols) + "@{}}", r"\toprule",
         r"symbol & rule & " + " & ".join(c.replace("_", r"\_") for c in cols) + r" \\",
         r"\midrule"]
    for sym, rule, key in SUFFICIENCY_ROWS:
        L.append(f"{sym} & {rule} & " + " & ".join(_ratio_cell(worst.get((key, c))) for c in cols) + r" \\")
    L += [r"\bottomrule", r"\end{tabular}"]
    (HERE / "tab_penalty_sufficiency.tex").write_text("\n".join(L) + "\n")
    print("[make_figures] wrote tab_penalty_sufficiency.tex")


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
    ("S2", "counts", r"weak ones raised to $1.5\times$"),
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
    M += _veloxq_separation_macros(calls)
    M += _veloxq_repair()
    (HERE / "generated_numbers_veloxq.tex").write_text("\n".join(M) + "\n")
    print("[make_figures] wrote tab_veloxq_settings.tex, tab_veloxq_breakdown.tex, tab_veloxq_repair.tex, "
          "generated_numbers_veloxq.tex")


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

    L = [r"\setlength{\tabcolsep}{4pt}\small",
         r"\begin{tabular}{@{}lrrrrrr@{}}", r"\toprule",
         r" & \multicolumn{2}{c}{valid} & \multicolumn{3}{c}{weighted objective of the valid timetables}"
         r" & search \\",
         r"\cmidrule(lr){2-3}\cmidrule(lr){4-6}",
         r"tier & calls & instances & at the optimum & above it & best call per instance & (s) \\",
         r"\midrule"]
    for t in TIERS:
        r = tiers[t]
        known = int(r["valid_calls_with_optimum"])
        if known:
            obj = [f"${r['calls_at_optimum']}/{known}$", f"{pct(r['gap_median'])} ({pct(r['gap_max'])})",
                   f"{pct(r['best_gap_median'])} ({pct(r['best_gap_max'])})"]
        else:
            obj = ["--", "--", "--"]
        L.append(f"{t} & ${r['calls_valid']}/{r['calls']}$ & ${r['instances_valid']}/{r['instances']}$ & "
                 + " & ".join(obj) + f" & {secs(r['repair_seconds_median'])} ({secs(r['repair_seconds_max'])}) \\\\")
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
            rf"\newcommand{{\VqRepairContinuedValid}}{{{freed}}}"]


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
    "gap": ("RU9 gap minutes", "B"),
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
               "(B) pairwise exclusion", "diagonal terms"],
              frameon=False, fontsize=7, loc="upper center",
              bbox_to_anchor=(0.5, -0.30), ncol=4, columnspacing=1.1,
              handlelength=1.0, handletextpad=0.4, borderpad=0.0)
    ax.set_xlim(1, total * 8)
    fig.tight_layout(pad=0.3)
    fig.savefig(HERE / "fig_family_census.pdf")
    plt.close(fig)
    print("[make_figures] wrote fig_family_census.pdf")


def fig_sparsity():
    """Clean spy plot of two compiled matrices, with the block split marked."""
    try:
        import h5py
    except ImportError:
        print("[make_figures] h5py missing; skipping fig_sparsity")
        return
    cache = ART / "qubo_caches_recalibrated"
    panels = [("medium_004_seed_1040", "medium tier"),
              ("extreme_011_seed_1110", "extreme tier")]
    fig, axes = plt.subplots(1, 2, figsize=(TEXTWIDTH_IN, 2.65))
    for ax, (stem, title) in zip(axes, panels):
        f = cache / f"{stem}.qubo_cache.h5"
        if not f.exists():
            print(f"[make_figures] {f.name} missing; skipping fig_sparsity")
            plt.close(fig)
            return
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
    (r"$\Lambda_5^{\mathrm{cnt}}$", "ST room count (own coefficient)", "C", "Lambda_room_count"),
    (r"$\Lambda_5^{\mathrm{cap}}$", "ST room capacity (own coefficient)", "C", "Lambda_room_capacity"),
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
LAMBDA_LATER = {"Lambda_idle_marker", "Lambda_room_count", "Lambda_room_capacity"}
# Family switches read from the same metadata, so "off" labels cannot drift
# from what the solved matrices actually contain.
LAMBDA_ENABLE = {"Lambda_mix": "enable_mixed_modality",
                 "alpha_lecture_before": "enable_lecture_before"}


def tab_lambdas():
    try:
        import h5py
        import json as _json
    except ImportError:
        print("[make_figures] h5py missing; skipping tab_lambdas")
        return
    cache = ART / "qubo_caches_recalibrated"
    cols = [("synthetic", "easy_000_seed_1000"), ("3\\_studies", "3_studies_instance")]
    cfgs = []
    for _, stem in cols:
        f = cache / f"{stem}.qubo_cache.h5"
        if not f.exists():
            print(f"[make_figures] {f.name} missing; skipping tab_lambdas")
            return
        with h5py.File(f, "r") as h:
            md = _json.loads(h.attrs.get("metadata", "{}"))
        cfgs.append(md.get("config", md.get("qubo_config", {})))

    def num(v):
        v = float(v)
        return fmt(v, 0) if abs(v - round(v)) < 1e-9 else f"{v:g}"

    L = [r"\setlength{\tabcolsep}{4pt}\small",
         r"\begin{tabular}{@{}llcrr@{}}", r"\toprule",
         r"symbol & family & pattern & " + " & ".join(c for c, _ in cols) + r" \\",
         r"\midrule"]
    for sym, fam, pat, key in LAMBDA_ROWS:
        if key in LAMBDA_LATER and not any(c.get(key) is not None for c in cfgs):
            continue
        vals = []
        for c in cfgs:
            if key not in c:
                die(f"tab_lambdas: {key} absent from cache metadata")
            vals.append(f"${num(c[key])}$")
        ek = LAMBDA_ENABLE.get(key)
        if ek is not None:
            flags = [bool(c.get(ek, True)) for c in cfgs]
            if not any(flags):
                fam = fam + " (off in runs)"
            elif not all(flags):
                fam = fam + " (on only in " + ", ".join(
                    cname for (cname, _), f in zip(cols, flags) if f) + ")"
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
