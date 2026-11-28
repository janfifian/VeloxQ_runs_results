#!/usr/bin/env python
"""Assemble repository_ready/dwave_capacity: copy the scripts and the unit
tests, fill the result tables of README.md from the files in results/ (so the
note cannot drift from the data), list the command behind every result file,
and write SHA256SUMS. Every file is written with LF line endings; the folder's
.gitattributes keeps them byte-exact in git.

The result files are put into results/ beforehand, under the names of
COMMANDS below. Run from the repository root:
  python scripts/assemble_dwave_capacity_deposit.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "repository_ready" / "dwave_capacity"
RESULTS = OUT / "results"
CODE = OUT / "code"
# deposited name -> (path in the code repository, what it is)
CODE_FILES = {
    "dwave_capacity.py": ("scripts/dwave_capacity.py", "the analysis script"),
    "dwave_capacity_precision.py": ("scripts/dwave_capacity_precision.py",
                                    "coefficient precision after the QPU's scaling"),
    "pr5_milp_rows.py": ("checks/pr5_milp_rows.py",
                         "counts the candidate placements of an instance (used for LATO)"),
    "_common.py": ("checks/_common.py", "helper imported by pr5_milp_rows.py"),
    "assemble_dwave_capacity_deposit.py": ("scripts/assemble_dwave_capacity_deposit.py",
                                           "builds this folder: copies the scripts, fills the tables of this README "
                                           "from results/, writes SHA256SUMS"),
    "test_dwave_capacity.py": ("tests/unit/test_dwave_capacity.py", "unit tests of the proof machinery"),
}


def last_commit(path: str) -> str:
    """The last commit that changed ``path`` (the deposited copy is that version)."""
    out = subprocess.run(["git", "log", "-1", "--format=%h", "--", path], cwd=REPO,
                         capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", path], cwd=REPO).returncode != 0
    return (out or "uncommitted") + (" + uncommitted changes" if dirty else "")

SYN = "repository_ready/instances/synthetic"
WEEK = "--days 5 --groups 3 --teachers 3 --rooms 3"
THREE = "--qpu Advantage2_system1 --qpu Advantage2_system4 --qpu Advantage_system4"
LONG = "--embed-timeout 1800 --thinned 1"
PAPER_OPEN = "the instances not proved in paper_synthetic_bounds.csv on Advantage2_system1 or Advantage_system4 (each passed as --instance)"

# (results file, date run, command); every command runs from the repository root at commit 8e35775
# (dwave_capacity_precision.py: the commit named in the README), with --csv results/<file>.
COMMANDS = [
    ("facts.txt", "2026-10-11", "python scripts/dwave_capacity.py --facts --thinned 2 > results/facts.txt"),
    ("paper_3studies.csv", "2026-10-11", "python scripts/dwave_capacity.py --instance artifacts/3studies/3_studies_instance.yaml --jobs 1"),
    ("paper_synthetic_bounds.csv", "2026-10-10", f"python scripts/dwave_capacity.py --instance {SYN}/<each of the 64 files>.yaml --jobs 3"),
    ("paper_synthetic_embeddings.csv", "2026-10-11", f"python scripts/dwave_capacity.py --instance <{PAPER_OPEN}> --qpu Advantage2_system1 --qpu Advantage_system4 --embed-timeout 300 --thinned 2 --jobs 8"),
    ("scan_week.csv", "2026-10-11", f"python scripts/dwave_capacity.py {WEEK} --courses 3 --scan courses=3:10:1 --seeds 1 2 3 --embed-timeout 120 --thinned 2 --jobs 5"),
    ("scan_week_bounds.csv", "2026-10-10", f"python scripts/dwave_capacity.py {WEEK} --courses 11 --scan courses=11:16:1 --seeds 1 2 3 {THREE} --jobs 9"),
    ("scan_day.csv", "2026-10-11", "python scripts/dwave_capacity.py --days 1 --groups 3 --teachers 3 --rooms 3 --courses 3 --scan courses=3:21:1 --seeds 1 2 3 --embed-timeout 120 --thinned 2 --jobs 5"),
    ("scan_day_6groups.csv", "2026-10-10", f"python scripts/dwave_capacity.py --seeds 1 2 {THREE} --embed-timeout 120 --thinned 2 --jobs 9 --days 1 --groups 6 --teachers 6 --rooms 6 --courses 6 --scan courses=6:42:3"),
    ("scan_slot_length.csv", "2026-10-10", f"python scripts/dwave_capacity.py --seeds 1 2 {THREE} --embed-timeout 120 --thinned 2 --jobs 9 {WEEK} --courses 3 --scan slot_minutes=45:180:15"),
    ("scan_days.csv", "2026-10-10", f"python scripts/dwave_capacity.py --seeds 1 2 {THREE} --embed-timeout 120 --thinned 2 --jobs 9 --days 1 --groups 3 --teachers 3 --rooms 3 --courses 3 --scan days=1:7:1"),
    ("scan_rooms_week.csv", "2026-10-10", f"python scripts/dwave_capacity.py --days 5 --courses 6 --seeds 1 2 {THREE} --embed-timeout 120 --thinned 2 --jobs 9 --groups 3 --teachers 3 --rooms 3 --scan rooms=1:6:1"),
    ("scan_rooms_day.csv", "2026-10-10", f"python scripts/dwave_capacity.py --days 1 --courses 15 --seeds 1 2 {THREE} --embed-timeout 120 --thinned 2 --jobs 9 --groups 3 --teachers 3 --rooms 3 --scan rooms=1:6:1"),
    ("scan_lecturers_day.csv", "2026-10-10", f"python scripts/dwave_capacity.py --days 1 --courses 15 --seeds 1 2 {THREE} --embed-timeout 120 --thinned 2 --jobs 9 --groups 3 --teachers 3 --rooms 3 --scan teachers=1:6:1"),
    ("scan_groups_day.csv", "2026-10-10", f"python scripts/dwave_capacity.py --days 1 --courses 15 --seeds 1 2 {THREE} --embed-timeout 120 --thinned 2 --jobs 9 --groups 3 --teachers 3 --rooms 3 --scan groups=3:8:1"),
]
for qpu in ("Advantage2_system1", "Advantage_system4"):
    q = f"--qpu {qpu} {LONG}"
    COMMANDS += [
        (f"long_week3_default_{qpu}.csv", "2026-10-10", f"python scripts/dwave_capacity.py {WEEK} --courses 3 --seeds 1 --encoding default {q}"),
        (f"long_week4_default_{qpu}.csv", "2026-10-10", f"python scripts/dwave_capacity.py {WEEK} --seeds 1 --courses 4 --encoding default {q}"),
        (f"long_week_presolved_{qpu}.csv", "2026-10-10", f"python scripts/dwave_capacity.py {WEEK} --seeds 1 --courses 4 --scan courses=4:6:1 --encoding presolved {q} --jobs 3"),
        (f"long_week_feasibility_{qpu}.csv", "2026-10-10", f"python scripts/dwave_capacity.py {WEEK} --seeds 1 --courses 6 --scan courses=6:8:1 --encoding feasibility {q} --jobs 3"),
        (f"long_easy000_default_{qpu}.csv", "2026-10-10", f"python scripts/dwave_capacity.py --instance {SYN}/easy_000_seed_1000.yaml --encoding default {q}"),
        (f"long_easy000_presolved_{qpu}.csv", "2026-10-10", f"python scripts/dwave_capacity.py --instance {SYN}/easy_000_seed_1000.yaml --encoding presolved {q}"),
        (f"long_easy001_{qpu}.csv", "2026-10-10", f"python scripts/dwave_capacity.py --instance {SYN}/easy_001_seed_1010.yaml --encoding feasibility --encoding presolved {q} --jobs 2"),
        (f"long_medium1044_{qpu}.csv", "2026-10-10", f"python scripts/dwave_capacity.py --instance {SYN}/medium_004_seed_1044.yaml --encoding feasibility {q}"),
    ]
COMMANDS += [
    ("lato_placements.txt", "2026-10-11", "python checks/pr5_milp_rows.py artifacts/Corrected_lato_3fix.yaml > results/lato_placements.txt"),
    ("easy000_encodings.csv", "2026-10-11", f"python scripts/dwave_capacity.py --instance {SYN}/easy_000_seed_1000.yaml --qpu Advantage2_system1"),
    ("easy000_encodings_sufficient_penalties.csv", "2026-10-11", f"python scripts/dwave_capacity.py --instance {SYN}/easy_000_seed_1000.yaml --qpu Advantage2_system1 --qubo-config penalty_profile=sufficient"),
    ("precision_easy000.csv", "2026-10-11", f"python scripts/dwave_capacity_precision.py --instance {SYN}/easy_000_seed_1000.yaml"),
    ("precision_easy000_sufficient_penalties.csv", "2026-10-11", f"python scripts/dwave_capacity_precision.py --instance {SYN}/easy_000_seed_1000.yaml --qubo-config penalty_profile=sufficient"),
    ("precision_3studies.csv", "2026-10-11", "python scripts/dwave_capacity_precision.py --instance artifacts/3studies/3_studies_instance.yaml"),
]

SHORT = {"proved: does not fit": "N", "embedded (ideal and all thinned graphs)": "Y",
         "embedded on the ideal graph only": "i", "embedded on the ideal graph": "i",
         "undecided": "?", "embedded on the exact working graph": "Y"}
ORDER = "Yi?N"
LARGE = ("Advantage2_system1", "Advantage_system4")


def rows(name):
    path = RESULTS / name
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def num(v):
    return f"{int(v):,}"


def rng(values):
    lo, hi = min(values), max(values)
    return f"{lo:,}" if lo == hi else f"{lo:,}–{hi:,}"


def letters(v):
    return "".join(sorted(v, key=ORDER.index)) if v else "–"


# ------------------------------------------------------------------ tables
def table_cliques():
    lines = ["| QPU | treewidth at most (verified) | clique on the ideal graph | cliques on the two stand-ins |",
             "|---|---|---|---|"]
    text = (RESULTS / "facts.txt").read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(text):
        m = re.match(r"\s+(Advantage\S+)\s.*treewidth <= (\d+)", line)
        if m:
            nxt = text[i + 1]
            c = re.search(r"clique embedding K_(\d+) on the ideal graph \(chains <= (\d+)\); on 2 thinned stand-ins: (.*)", nxt)
            thin = re.findall(r"K_(\d+) \(chains <= (\d+)\)", c.group(3))
            lines.append(f"| {m.group(1)} | {m.group(2)} | K_{c.group(1)} (chains ≤ {c.group(2)}) | "
                         + ", ".join(f"K_{k} (chains ≤ {L})" for k, L in thin) + " |")
    return "\n".join(lines)


def table_3studies():
    data = rows("paper_3studies.csv")
    by = defaultdict(dict)
    for r in data:
        by[r["encoding"]][r["qpu"]] = r
    lines = ["| encoding | placements | coupled variables | couplings | qubits needed at least (Zephyr / Pegasus) | couplers needed at least (Zephyr / Pegasus) | verdict on the five QPUs |",
             "|---|---|---|---|---|---|---|"]
    for enc in ("default", "presolved", "feasibility"):
        if not {"Advantage2_system1", "Advantage_system4"} <= set(by[enc]):
            continue
        z, p = by[enc]["Advantage2_system1"], by[enc]["Advantage_system4"]
        verdicts = {r["verdict"] for r in by[enc].values()}
        lines.append(f"| {enc} | {num(z['candidate_placements'])} | {num(z['coupled_variables'])} | {num(z['couplings'])} | "
                     f"{num(z['qubits_needed_at_least'])} / {num(p['qubits_needed_at_least'])} | "
                     f"{num(z['couplers_needed_at_least'])} / {num(p['couplers_needed_at_least'])} | {', '.join(sorted(verdicts))} |")
    return "\n".join(lines)


def synthetic_final():
    bounds = rows("paper_synthetic_bounds.csv")
    embed = {(r["instance"], r["encoding"], r["qpu"]): r for r in rows("paper_synthetic_embeddings.csv")}
    final = []
    for r in bounds:
        key = (r["instance"], r["encoding"], r["qpu"])
        e = embed.get(key)
        if r["verdict"] != "proved: does not fit" and e is not None:
            r = {**r, "verdict": e["verdict"], "reason": e["reason"], "ideal_graph": e["ideal_graph"],
                 "thinned_graphs": e["thinned_graphs"], "embed_timeout": e["embed_timeout"]}
        final.append(r)
    return final


def table_synthetic(final):
    tiers = ("easy", "medium", "hard", "extreme")
    lines = ["| tier | instances | courses | placements | encoding | coupled variables | Advantage2_system1 | Advantage_system4 | Advantage2_system4 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for tier in tiers:
        tr = [r for r in final if r["instance"].startswith(tier)]
        insts = sorted({r["instance"] for r in tr})
        for enc in ("default", "presolved", "feasibility"):
            er = [r for r in tr if r["encoding"] == enc]
            ref = [r for r in er if r["qpu"] == "Advantage2_system1"]

            def count(qpu):
                c = defaultdict(int)
                for r in er:
                    if r["qpu"] == qpu:
                        c[SHORT.get(r["verdict"], r["verdict"])] += 1
                return " ".join(f"{k} {c[k]}" for k in ORDER if c[k])
            lines.append(f"| {tier} | {len(insts)} | {rng([int(r['courses']) for r in ref])} | "
                         f"{rng([int(r['candidate_placements']) for r in ref])} | {enc} | "
                         f"{rng([int(r['coupled_variables']) for r in ref])} | {count('Advantage2_system1')} | "
                         f"{count('Advantage_system4')} | {count('Advantage2_system4')} |")
    return "\n".join(lines)


def table_synthetic_fits(final):
    lines = ["| instance | encoding | coupled variables | QPU | qubits used (ideal; stand-ins) | longest chain (ideal; stand-ins) |",
             "|---|---|---|---|---|---|"]
    for r in final:
        if r["verdict"] == "embedded (ideal and all thinned graphs)":
            ideal = json.loads(r["ideal_graph"])
            thin = json.loads(r["thinned_graphs"]) if r["thinned_graphs"] else []
            used = "; ".join([f"{ideal['qubits_used']:,}", ", ".join(f"{t['qubits_used']:,}" for t in thin)])
            chains = "; ".join([str(ideal["max_chain"]), ", ".join(str(t["max_chain"]) for t in thin)])
            lines.append(f"| {r['instance']} | {r['encoding']} | {num(r['coupled_variables'])} | {r['qpu']} | "
                         f"{used} | {chains} |")
    return "\n".join(lines) if len(lines) > 2 else "(none)"


def table_scan(files, dim, label, slots=False):
    cells = defaultdict(lambda: defaultdict(list))
    sizes = defaultdict(list)
    placements = defaultdict(list)
    spd = {}
    refused = defaultdict(int)
    for name in files:
        for r in rows(name):
            if r["verdict"] == "generator refused":
                refused[int(r[dim])] += 1
                continue
            if not r.get("qpu"):
                continue
            v = int(r[dim])
            cells[(v, r["encoding"])][r["qpu"]].append(SHORT.get(r["verdict"], r["verdict"]))
            if r["qpu"] == "Advantage2_system1":
                sizes[(v, r["encoding"])].append(int(r["coupled_variables"]))
                placements[v].append(int(r["candidate_placements"]))
                spd[v] = r.get("slots_per_day", "")
    lines = [f"| {label} | placements | default | presolved | feasibility |", "|---|---|---|---|---|"]
    for v in sorted({k[0] for k in cells}):
        row = [f"{v} ({spd[v]} slots a day)" if slots else str(v), rng(placements[v])]
        for e in ("default", "presolved", "feasibility"):
            c = cells[(v, e)]
            row.append(f"{rng(sizes[(v, e)])}: {letters(c.get('Advantage2_system1'))} / "
                       f"{letters(c.get('Advantage_system4'))} / {letters(c.get('Advantage2_system4'))}" if c else "")
        lines.append("| " + " | ".join(row) + " |")
    if refused:
        lines += ["", "The generator refused: " + ", ".join(f"{label} = {k} ({n} seeds)" for k, n in sorted(refused.items())) + "."]
    return "\n".join(lines)


def table_long():
    found = {}
    for name, _, _ in COMMANDS:
        if not name.startswith("long_"):
            continue
        for r in rows(name):
            if not r.get("qpu"):
                continue
            setting = (f"{r['days']} days × {r['slots_per_day']} slots, {r['courses_requested']} courses"
                       if r.get("days") else r["instance"])
            text = {"Y": "embedded (ideal graph and the stand-in)", "i": "ideal graph only", "?": "undecided",
                    "N": "proved not to fit"}[SHORT[r["verdict"]]]
            detail = ""
            for field in ("thinned_graphs", "ideal_graph"):
                if r.get(field):
                    data = json.loads(r[field])
                    hits = [d for d in (data if isinstance(data, list) else [data]) if d.get("found")]
                    if hits:
                        d = hits[0]
                        detail = f" ({d['qubits_used']:,} qubits, chains ≤ {d['max_chain']}, {d['seconds']:.0f} s)"
                        break
            found.setdefault((setting, r["encoding"]), {"coupled": r["coupled_variables"]})[r["qpu"]] = text + detail
    lines = ["| instance | encoding | coupled variables | Advantage2_system1 | Advantage_system4 |", "|---|---|---|---|---|"]
    for (setting, enc), d in sorted(found.items()):
        lines.append(f"| {setting} | {enc} | {num(d['coupled'])} | {d.get('Advantage2_system1', '')} | {d.get('Advantage_system4', '')} |")
    return "\n".join(lines)


def table_families():
    lines = ["| family | default | presolved | feasibility |", "|---|---|---|---|"]
    data = {r["encoding"]: r for r in rows("easy000_encodings.csv")}
    fam = {e: json.loads(data[e]["coupled_by_family"]) for e in ("default", "presolved", "feasibility")}
    names = sorted(set().union(*fam.values()), key=lambda k: (k != "x", k))
    for k in names:
        lines.append(f"| `{k}` | " + " | ".join(str(fam[e].get(k, "–")) for e in ("default", "presolved", "feasibility")) + " |")
    lines.append("| coupled variables | " + " | ".join(num(data[e]["coupled_variables"]) for e in ("default", "presolved", "feasibility")) + " |")
    lines.append("| couplings | " + " | ".join(num(data[e]["couplings"]) for e in ("default", "presolved", "feasibility")) + " |")
    return "\n".join(lines)


def table_precision():
    lines = ["| instance | penalties | encoding | Ising dynamic range | smallest coefficient after scaling | share of nonzero coefficients below 0.01 |",
             "|---|---|---|---|---|---|"]
    for name, label in (("precision_easy000.csv", "as in cfg/qubo_cfg.yaml"),
                        ("precision_easy000_sufficient_penalties.csv", "smallest sufficient"),
                        ("precision_3studies.csv", "as in cfg/qubo_cfg.yaml")):
        if not (RESULTS / name).exists():
            continue
        for r in rows(name):
            lines.append(f"| {r['instance']} | {label} | {r['encoding']} | {float(r['ising_dynamic_range']):.2g} | "
                         f"{float(r['smallest_scaled_coefficient']):.1e} | {float(r['share_below_error_level']):.1%} |")
    return "\n".join(lines)


def results_section():
    final = synthetic_final()
    parts = [
        "### What fits whatever the QUBO's structure",
        "Clique embeddings built by busclique and checked by the script (`results/facts.txt`). Every QUBO with at most "
        "that many coupled variables fits the graph.",
        table_cliques(),
        "### The instances of the paper",
        "**3_studies** (`results/paper_3studies.csv`; the instance itself is in the authors' code repository and is "
        "not deposited here):",
        table_3studies(),
        "**LATO** (`artifacts/Corrected_lato_3fix.yaml`, 697 courses; 504,309 candidate placements, "
        "`results/lato_placements.txt`; not compiled here). Two placements of the same course are coupled by "
        "its course-hours row, and every other term the compiler writes on such a pair is nonnegative (block-limit "
        "rows, non-overlap, room rows, PR5; the lecture-before term joins different courses), so no such coupling "
        "cancels. Only a course with a single candidate placement can leave a placement uncoupled; with 697 courses "
        "more than 500,000 coupled variables remain against at most 5,627 qubits: it does not fit any of the QPUs.",
        "**The 64 synthetic instances** of `instances/synthetic` (`results/paper_synthetic_bounds.csv`: bounds and "
        "clique embeddings on all five QPUs; `results/paper_synthetic_embeddings.csv`: minorminer with 300 s per graph "
        "and two stand-ins on Advantage2_system1 and Advantage_system4 for every instance not proved there). Counts "
        "per verdict: Y embedded on the ideal graph and on both stand-ins, i on the ideal graph only, ? undecided, "
        "N proved not to fit:",
        table_synthetic(final),
        "Embedded on the ideal graph and both stand-ins:",
        table_synthetic_fits(final),
        "### Scans over the instance parameters",
        "Synthetic instances as described above, 3 student groups, 3 lecturers and 3 rooms unless the table says "
        "otherwise. A cell gives the coupled variables and then, per seed, the verdict on Advantage2_system1 (Zephyr "
        "Z12) / Advantage_system4 (Pegasus P16) / Advantage2_system4 (Zephyr Z6): Y embedded on the ideal graph and on "
        "both stand-ins, i on the ideal graph only, ? undecided, N proved not to fit. minorminer had 120 s per graph; "
        "11 to 16 courses a week ran with the bounds and clique embeddings only.",
        "**One week (5 days, 7 slots of 90 minutes a day)** (`scan_week.csv`, `scan_week_bounds.csv`):",
        table_scan(["scan_week.csv", "scan_week_bounds.csv"], "courses_requested", "courses"),
        "**One day (7 slots)** (`scan_day.csv`; with 3 groups the generator allows at most 21 courses):",
        table_scan(["scan_day.csv"], "courses_requested", "courses"),
        "**One day, 6 groups, 6 lecturers, 6 rooms** (`scan_day_6groups.csv`):",
        table_scan(["scan_day_6groups.csv"], "courses_requested", "courses"),
        "**Slot length, one week, 3 courses** (`scan_slot_length.csv`):",
        table_scan(["scan_slot_length.csv"], "slot_minutes", "slot minutes", slots=True),
        "**Days of the week, 3 courses** (`scan_days.csv`):",
        table_scan(["scan_days.csv"], "days", "days"),
        "**Rooms, one week, 6 courses** (`scan_rooms_week.csv`):",
        table_scan(["scan_rooms_week.csv"], "rooms", "rooms"),
        "**Rooms, one day, 15 courses** (`scan_rooms_day.csv`):",
        table_scan(["scan_rooms_day.csv"], "rooms", "rooms"),
        "**Lecturers, one day, 15 courses** (`scan_lecturers_day.csv`):",
        table_scan(["scan_lecturers_day.csv"], "lecturers", "lecturers"),
        "**Student groups, one day, 15 courses** (`scan_groups_day.csv`):",
        table_scan(["scan_groups_day.csv"], "groups", "groups"),
        "### Longer searches",
        "minorminer with 30 minutes per graph and one stand-in, seed 1 (`long_*.csv`). The qubits and the longest "
        "chain are those of the embedding on the stand-in, or on the ideal graph when only that one was found.",
        table_long(),
        "### Where the variables come from",
        "Coupled variables per family of the compiler's variable names, `easy_000_seed_1000` (5 courses, one week of "
        "35 slots, 3 rooms; `easy000_encodings.csv`):",
        table_families(),
        "### Precision",
        "Ising coefficients after the scaling a QPU applies with the example ranges h in [-4, 4] and J in [-1, 1] "
        "(`precision_*.csv`, from `dwave_capacity_precision.py`); 0.01 is the size of the integrated control errors "
        "in D-Wave's documentation [12]:",
        table_precision(),
    ]
    return "\n\n".join(parts)


def frozen_statement() -> str:
    """Whether the compiler, its configuration, the generator presets and the
    checks are those of the tag ``frozen`` (the code state of the paper's runs)."""
    tag = subprocess.run(["git", "rev-list", "-n", "1", "frozen"], cwd=REPO,
                         capture_output=True, text=True).stdout.strip()[:7]
    if not tag:
        return "The tag `frozen` does not exist in this checkout."
    same = subprocess.run(["git", "diff", "--quiet", "frozen", "HEAD", "--", "src", "cfg", "generated_presets",
                           "checks"], cwd=REPO).returncode == 0
    if same:
        return (f"The compiler, its configuration, the generator presets and the checks used here are those of the "
                f"tag `frozen` (`{tag}`), the code state of the paper's runs: `src/`, `cfg/`, `generated_presets/` "
                "and `checks/` are unchanged between that tag and the commits above.")
    return (f"`src/`, `cfg/`, `generated_presets/` or `checks/` differ between the tag `frozen` (`{tag}`) and the "
            "commits above.")


def contents_section():
    lines = ["| path | content |", "|---|---|"]
    for name, (path, what) in CODE_FILES.items():
        lines.append(f"| `code/{name}` | {what}: copy of `{path}`, commit `{last_commit(path)}` of the authors' "
                     "code repository |")
    lines += ["| `results/` | every output: one CSV row per instance, encoding and QPU (columns below); "
              "`facts.txt`, the hardware table; `lato_placements.txt`, the placement count of LATO |",
              "| `SHA256SUMS` | checksums of every file in this folder (`sha256sum -c SHA256SUMS`) |", "",
              "The scripts import the authors' MILP-to-QUBO compiler and instance generator, and the helper "
              "`scripts/_pipeline_helpers.py`, which are not public (see the paper's data availability "
              "statement); the results are therefore deposited in full. The hardware-side computations "
              "(treewidth bounds, clique embeddings, thinned stand-ins) use only the public libraries "
              "`dwave-networkx` and `minorminer`.", "", frozen_statement()]
    return "\n".join(lines)


def commands_section():
    lines = ["## How each result file was made", "",
             "From the root of the authors' code repository, with `scripts/dwave_capacity.py` as of commit "
             f"`{last_commit('scripts/dwave_capacity.py')}`, `scripts/dwave_capacity_precision.py` as of commit "
             f"`{last_commit('scripts/dwave_capacity_precision.py')}` and `checks/pr5_milp_rows.py` as of commit "
             f"`{last_commit('checks/pr5_milp_rows.py')}`; each command with `--csv results/<file>` "
             "(the `.txt` files: standard output):", "",
             "| file | run on | command |", "|---|---|---|"]
    for name, date, cmd in COMMANDS:
        if (RESULTS / name).exists():
            lines.append(f"| `{name}` | {date} | `{cmd}` |")
    return "\n".join(lines)


def replace_between(text, tag, body):
    begin, end = f"<!-- {tag}:BEGIN -->", f"<!-- {tag}:END -->"
    a, b = text.index(begin), text.index(end)
    return text[:a] + begin + "\n" + body + "\n" + text[b:]


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    missing = [n for n, _, _ in COMMANDS if not (RESULTS / n).exists()]
    if missing:
        print("missing result files:", ", ".join(missing))
    CODE.mkdir(parents=True, exist_ok=True)
    for name, (path, _) in CODE_FILES.items():
        (CODE / name).write_bytes((REPO / path).read_bytes().replace(b"\r\n", b"\n"))
    readme = (OUT / "README.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    readme = replace_between(readme, "CONTENTS", contents_section())
    readme = replace_between(readme, "RESULTS", results_section())
    readme = replace_between(readme, "COMMANDS", commands_section())
    (OUT / "README.md").write_bytes(readme.encode("utf-8"))
    for path in RESULTS.iterdir():
        if path.is_file():
            path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
    (OUT / ".gitattributes").write_bytes(b"* -text\n")
    sums = []
    for path in sorted(p for p in OUT.rglob("*") if p.is_file() and p.name != "SHA256SUMS"):
        rel = path.relative_to(OUT).as_posix()
        sums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {rel}\n")
    (OUT / "SHA256SUMS").write_bytes("".join(sums).encode("utf-8"))
    print(f"assembled {OUT} ({len(sums)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
