# Direct execution on D-Wave quantum processors: capacity analysis

This folder accompanies the paper *Would bigger quantum annealers help? An
emulator-based test of QUBO against MILP on university timetabling*, appendix
"On the current applicability to physical devices". It asks which timetabling
instances could run directly on a current D-Wave quantum processing unit (QPU),
without a hybrid solver, in the QUBO that the authors' compiler builds. It
holds the scripts, their unit tests, every result file behind the numbers in
the paper, and the source of every hardware figure.

## Contents

<!-- CONTENTS:BEGIN -->
| path | content |
|---|---|
| `code/dwave_capacity.py` | the analysis script: copy of `scripts/dwave_capacity.py`, commit `8e35775` of the authors' code repository |
| `code/dwave_capacity_precision.py` | coefficient precision after the QPU's scaling: copy of `scripts/dwave_capacity_precision.py`, commit `9508038` of the authors' code repository |
| `code/pr5_milp_rows.py` | counts the candidate placements of an instance (used for LATO): copy of `checks/pr5_milp_rows.py`, commit `27d1186` of the authors' code repository |
| `code/_common.py` | helper imported by pr5_milp_rows.py: copy of `checks/_common.py`, commit `ec79458` of the authors' code repository |
| `code/assemble_dwave_capacity_deposit.py` | builds this folder: copies the scripts, fills the tables of this README from results/, writes SHA256SUMS: copy of `scripts/assemble_dwave_capacity_deposit.py`, commit `ad75b0f` of the authors' code repository |
| `code/test_dwave_capacity.py` | unit tests of the proof machinery: copy of `tests/unit/test_dwave_capacity.py`, commit `8e35775` of the authors' code repository |
| `results/` | every output: one CSV row per instance, encoding and QPU (columns below); `facts.txt`, the hardware table; `lato_placements.txt`, the placement count of LATO |
| `SHA256SUMS` | checksums of every file in this folder (`sha256sum -c SHA256SUMS`) |

The scripts import the authors' MILP-to-QUBO compiler and instance generator, and the helper `scripts/_pipeline_helpers.py`, which are not public (see the paper's data availability statement); the results are therefore deposited in full. The hardware-side computations (treewidth bounds, clique embeddings, thinned stand-ins) use only the public libraries `dwave-networkx` and `minorminer`.

The compiler, its configuration, the generator presets and the checks used here are those of the tag `frozen` (`89c641f`), the code state of the paper's runs: `src/`, `cfg/`, `generated_presets/` and `checks/` are unchanged between that tag and the commits above.
<!-- CONTENTS:END -->

## The question and the three verdicts

To run on a QPU, a QUBO must be minor-embedded in the QPU's working graph:
every variable becomes a connected chain of qubits, the chains are disjoint,
and every nonzero coupling of two variables has a physical coupler between
their chains. A variable without couplings needs no qubit (its best value
follows from its sign) and is left out. For each instance, encoding and QPU the
script gives one verdict:

| verdict | meaning | how sure |
|---|---|---|
| `proved: does not fit` | a necessary condition for every embedding fails | a proof; it holds for every working graph of the design |
| `embedded (ideal and all thinned graphs)` | an embedding was found on the ideal graph and on every thinned stand-in, and checked by the script (chains disjoint and connected, every coupling realised) | certain for those graphs; evidence, not proof, for the exact working graph of a given calibration, which D-Wave does not publish |
| `embedded on the ideal graph only` | found on the ideal graph, not on every stand-in | as above, weaker |
| `undecided` | no bound excludes it, no embedding was found in the time given | minorminer is a heuristic; failing to find an embedding proves nothing |

### Necessary conditions (each holds for every embedding)

1. Coupled variables ≤ working qubits.
2. Chain lengths. A connected chain of L qubits in a graph of maximum degree Δ
   has at most L(Δ−2)+2 couplers leaving it (it has at least L−1 couplers
   inside, each using two of the at most LΔ coupler ends). A variable with d
   couplings needs couplers to d disjoint chains, so its chain has at least
   max(1, ⌈(d−2)/(Δ−2)⌉) qubits; the sum over all variables must not exceed
   the working qubits. Δ is 15 on Pegasus and 20 on Zephyr [2, 3].
3. Couplers. Every coupling needs its own coupler between two chains and a
   chain of L qubits needs L−1 couplers inside; the sum must not exceed the
   working couplers.
4. Treewidth. A minor never has a larger treewidth than its host, and a
   working graph is a subgraph of the design's full ("ideal") graph. For the
   host, the script computes the width of an elimination order on the ideal
   graph — vertical qubits one column at a time, a horizontal qubit once all
   its vertical neighbours are gone, the order of [2, §5] and [3, §5] — and
   obtains 202 for Pegasus P16, 202 for Zephyr Z12 and 106 for Zephyr Z6
   (`results/facts.txt`). These are slightly weaker than the published bounds
   (12M−4 = 188 for P16 [2, §5]; 16m+8 = 200 for Z12 and 104 for Z6 [3, §5])
   and are used because the script checks them itself. For the QUBO, three
   lower bounds on the treewidth:
   - the degeneracy;
   - the contraction-degeneracy bound MMD+ (min-d) [6];
   - the placement grid. The placements of a course are coupled pairwise by
     its course-hours row (a sum of nonnegative terms, so no such coupling
     cancels), and the placements starting in the same slot are coupled
     pairwise when a room row covers them all; the script checks both on the
     QUBO and keeps the courses and slots where they hold. Such placements
     form the line graph of the bipartite graph between courses and slots. A
     graph of treewidth k has a set of at most k+1 vertices whose removal
     leaves no component with more than half of the vertices [7, Lemma 7.19];
     in this line graph the components left are the edge sets of components
     of the bipartite graph, and a component using r courses and c slots has
     at most r·c placements. A dynamic programme over the numbers of courses
     and slots used gives the smallest such set, hence a lower bound on the
     treewidth; for C courses and S slots it is about (√2−1)·C·S ≈ 0.41·C·S.

A course whose candidate placements exceed the host bound plus one is
excluded by its course-hours row alone (a clique of k variables has treewidth
k−1).

### Embeddings

- Clique embedding: every graph on n vertices is a subgraph of the complete
  graph K_n, so a clique embedding of K_n embeds every QUBO with n coupled
  variables. The script asks minorminer's `busclique` [8, 9] for K_n, with
  three seeds, on each graph.
- minorminer's `find_embedding`, an implementation of the heuristic of [10],
  with the time limit given per graph (`embed_timeout` column), 10 tries and
  random seed 1.
- Each embedding found is checked by the script itself (`verify_embedding`):
  every chain non-empty, inside the graph, disjoint from the others and
  connected; every coupling realised by a coupler between the two chains.
- Graphs: the ideal graph of the design (dwave-networkx: `pegasus_graph(16,
  fabric_only=True)`, `zephyr_graph(12, 4)`, `zephyr_graph(6, 4)`); and, after
  a success there, stand-ins thinned at random to the published numbers of
  working qubits and couplers (seeds 0, 1, …): random qubits are removed
  first, then random couplers. D-Wave's embedding guide simulates yield in the
  same way, by random removal of nodes and edges [5]. minorminer runs on
  Advantage2_system1, Advantage2_system4 and Advantage_system4 unless the
  command says otherwise; Advantage2_system2 and Advantage_system6 (the same
  designs with fewer working qubits) get the bounds and the clique
  embeddings.

### Encodings

The instance is compiled by the authors' `TimeAllocationQUBO` under one of
three encodings (`encoding` column):

- `default`: the encoding of the paper's experiments (course-hours and
  block-limit rows, non-overlap, PR5, room rows per 15-minute cell with their
  slack bits, group activity indicators, exact idle time);
- `presolved`: the same with `room_presolve: counts`;
- `feasibility`: presolved, without soft terms (no lecturer preference, time
  of day, active days, idle time, lecture-before) and without activity
  indicators.

### Synthetic instances of the scans

Made by the authors' generator from the preset `easy_000` with the parameters
in the row (`days`, `slots_per_day`, `slot_minutes`, `break_minutes`,
`groups`, `lecturers`, `rooms`, `courses_requested`, `seed`): days
08:00–20:00, slots of `slot_minutes` with `break_minutes` between them. In
this generator every course is one weekly lesson that fills one slot, taught
by one lecturer to one or more student groups, so a course has one candidate
placement per slot of the week in which its lecturer is available. The
generated instances are not stored; the generator reproduces them from the
parameters and the seed.

## Hardware facts and their sources

All D-Wave documentation pages were read on 10 October 2026 and re-checked on
11 October 2026; section and table names are those of that day. Numbers,
ranges, property names and the titles of pages, sections and tables are given
exactly as published. The statements are paraphrases, not quotations (the one
quoted phrase is marked by quotation marks); each names the page and the
section or table it comes from, so that the wording can be checked there.

### The QPUs

From D-Wave's *Per-QPU Solver Properties and Schedules* [1], tables "QPU
Physical Properties" (Table 25: Advantage2_system4; 26: Advantage2_system2;
27: Advantage2_system1; 28: Advantage_system6; 29: Advantage_system4), rows
"Graph size", "Number of qubits" and "Number of couplers":

| QPU | topology | graph size | number of qubits | number of couplers |
|---|---|---|---|---|
| Advantage2_system1 | Zephyr | Z12 | 4575 | 41474 |
| Advantage2_system2 | Zephyr | Z12 | 4506 | 40302 |
| Advantage2_system4 | Zephyr | Z6 | 1202 | 10537 |
| Advantage_system4 | Pegasus | P16 | 5627 | 40279 |
| Advantage_system6 | Pegasus | P16 | 5612 | 40088 |

The same page gives the physical properties, the anneal schedule and (as of
its first release, 2026-06-24) the working-graph changes of Advantage2_research2
as identical to those of Advantage2_system4, and says that these values are
physical properties of a calibrated QPU, "not QPU specifications". Its Table 30, "Working-Graph
Changes", lists per release the qubits removed from the working graph since
the previous release: for Advantage_system4 only the first release
(Advantage_system4.1, 2021-10-05) and a name change (2026-05-26); for
Advantage2_system1 the first release (Advantage2_system1.1, 2025-05-20) and
16 later rows, 25 qubits in all. The qubits missing at a first release are not
listed, so the exact working graphs cannot be rebuilt from the page. They are
the solver properties `qubits` and `couplers`, defined as the indices of the
qubits and of the couplers in the working graph (*General QPU Solver
Properties* [4], sections qubits and couplers; the page's examples read them
as `sampler.properties["qubits"]` of a `DWaveSampler`).

### The topologies

- Pegasus [2]: a P_M graph has 24M(M−1) qubits and maximum degree 15; a P16
  has 5760 qubits in total and 5640 in the main fabric (§2.1). Clique
  embeddings: up to 12(M−1) variables with chains of length M and M+1, up to
  12M−10 with longer chains (§3.1). Treewidth between 12M−11 and 12M−4, with
  the elimination order above (§5).
- Zephyr [3]: a Z_{m,t} graph (Z_m when t = 4) has 8tm²+4tm qubits and
  maximum degree 4t+4, i.e. 20 (§2.1). On full-yield graphs, clique
  embeddings with chains of length m of size 2(2m−1)t, i.e. 16m−8 for t = 4
  (§2.2); cliques of size 16m+1 with chains of mostly 2m qubits (§5.1). Treewidth between 16m and 16m+8, with the same kind of
  elimination order (§5).
- The ideal graphs built by dwave-networkx 0.8.19 have 5640 qubits and 40484
  couplers (P16 fabric), 4800 and 45864 (Z12), 1248 and 11400 (Z6)
  (`results/facts.txt`).

### Cliques on real working graphs

D-Wave's *Release Notes* [11], entry "2021-10-05 Release: Hybrid CQM Solver
and Advantage System Performance Update", subsection "Higher Yield", report
that on Advantage_system4.1 (yield 99.7 %, 5,627 qubits; 99.4 % of couplers,
40,279, available for use) the largest clique successfully embedded grew from
119 to 177 nodes, with chains of 17 qubits; earlier Advantage QPUs had 5,436
to 5,567 available qubits (working-graph yields of 96 % to 98.7 %). Since Table 30 lists no
qubit removal for Advantage_system4 after that release and its counts are
unchanged, every QUBO with at most 177 coupled variables fits that QPU. No
such figure exists for the Advantage2 QPUs. D-Wave's embedding guide [5],
section "Embedding Complete Graphs", gives K_150 as the largest clique
embeddable in a full-yield Pegasus graph with chain length 14, and, in its
Table 56 ("Complete Embeddings Versus Chain Length for 95% Yields", working
graphs simulated by random removal of 5 % of nodes and 0.5 % of edges), for
Pegasus K_4, K_10, K_30 and K_71 at chain lengths 1, 2, 4 and 10.

### Precision

- *General QPU Solver Properties* [4] gives, as examples, `h_range` [-4.0,
  4.0], `j_range` [-1.0, 1.0] and `extended_j_range` [-2.0, 1.0]; the ranges
  are properties of each solver.
- *Errors and Error Correction* [12], section ICE ("Sources of ICE" and
  "Characterizing the Effect of Flux Noise"): the Gaussian contribution of
  flux noise to δh is approximately 0.009 early in the anneal and less later
  in the anneal; the relative
  error in h is about 0.01; with DAC quantization, h = 0 may be realised up to
  ±0.008 away; the h scale varies across qubits with a standard deviation of
  about 1 %. The figures are marked as representative of D-Wave 2X systems,
  and the chapter as representative of D-Wave systems; the page gives no
  separate magnitudes for Advantage or Advantage2 (it states that one noise
  source, spin-bath polarization, is much reduced on Advantage2).
- The same page, section "Virtual Graphs", expects embedded problems to work
  well up to a maximum chain length of 5 to 7 qubits.

## Results

<!-- RESULTS:BEGIN -->
### What fits whatever the QUBO's structure

Clique embeddings built by busclique and checked by the script (`results/facts.txt`). Every QUBO with at most that many coupled variables fits the graph.

| QPU | treewidth at most (verified) | clique on the ideal graph | cliques on the two stand-ins |
|---|---|---|---|
| Advantage2_system1 | 202 | K_184 (chains ≤ 13) | K_108 (chains ≤ 14), K_109 (chains ≤ 13) |
| Advantage2_system2 | 202 | K_184 (chains ≤ 13) | K_102 (chains ≤ 14), K_111 (chains ≤ 14) |
| Advantage2_system4 | 106 | K_88 (chains ≤ 7) | K_73 (chains ≤ 8), K_70 (chains ≤ 8) |
| Advantage_system4 | 202 | K_180 (chains ≤ 17) | K_173 (chains ≤ 17), K_173 (chains ≤ 17) |
| Advantage_system6 | 202 | K_180 (chains ≤ 17) | K_172 (chains ≤ 17), K_172 (chains ≤ 17) |

### The instances of the paper

**3_studies** (`results/paper_3studies.csv`; the instance itself is in the authors' code repository and is not deposited here):

| encoding | placements | coupled variables | couplings | qubits needed at least (Zephyr / Pegasus) | couplers needed at least (Zephyr / Pegasus) | verdict on the five QPUs |
|---|---|---|---|---|---|---|
| default | 31,151 | 119,876 | 30,057,866 | 3,382,508 / 4,671,575 | 33,320,498 / 34,609,565 | proved: does not fit |
| presolved | 31,151 | 65,102 | 26,504,092 | 2,976,913 / 4,105,201 | 29,415,903 / 30,544,191 | proved: does not fit |
| feasibility | 31,151 | 43,046 | 26,355,835 | 2,944,969 / 4,068,065 | 29,257,758 / 30,380,854 | proved: does not fit |

**LATO** (`artifacts/Corrected_lato_3fix.yaml`, 697 courses; 504,309 candidate placements, `results/lato_placements.txt`; not compiled here). Two placements of the same course are coupled by its course-hours row, and every other term the compiler writes on such a pair is nonnegative (block-limit rows, non-overlap, room rows, PR5; the lecture-before term joins different courses), so no such coupling cancels. Only a course with a single candidate placement can leave a placement uncoupled; with 697 courses more than 500,000 coupled variables remain against at most 5,627 qubits: it does not fit any of the QPUs.

**The 64 synthetic instances** of `instances/synthetic` (`results/paper_synthetic_bounds.csv`: bounds and clique embeddings on all five QPUs; `results/paper_synthetic_embeddings.csv`: minorminer with 300 s per graph and two stand-ins on Advantage2_system1 and Advantage_system4 for every instance not proved there). Counts per verdict: Y embedded on the ideal graph and on both stand-ins, i on the ideal graph only, ? undecided, N proved not to fit:

| tier | instances | courses | placements | encoding | coupled variables | Advantage2_system1 | Advantage_system4 | Advantage2_system4 |
|---|---|---|---|---|---|---|---|---|
| easy | 20 | 5–14 | 154–420 | default | 1,175–2,430 | ? 20 | ? 20 | N 20 |
| easy | 20 | 5–14 | 154–420 | presolved | 587–1,494 | Y 1 i 1 ? 18 | Y 1 ? 19 | ? 5 N 15 |
| easy | 20 | 5–14 | 154–420 | feasibility | 271–638 | Y 5 ? 15 | Y 5 ? 15 | ? 6 N 14 |
| medium | 15 | 22–32 | 612–930 | default | 2,780–3,832 | N 15 | N 15 | N 15 |
| medium | 15 | 22–32 | 612–930 | presolved | 1,902–2,586 | ? 1 N 14 | ? 1 N 14 | N 15 |
| medium | 15 | 22–32 | 612–930 | feasibility | 926–1,286 | ? 1 N 14 | ? 1 N 14 | N 15 |
| hard | 20 | 38–55 | 1,056–1,554 | default | 4,240–5,465 | N 20 | N 20 | N 20 |
| hard | 20 | 38–55 | 1,056–1,554 | presolved | 2,957–4,084 | N 20 | N 20 | N 20 |
| hard | 20 | 38–55 | 1,056–1,554 | feasibility | 1,425–1,996 | N 20 | N 20 | N 20 |
| extreme | 9 | 75–100 | 1,986–2,355 | default | 5,976–7,180 | N 9 | N 9 | N 9 |
| extreme | 9 | 75–100 | 1,986–2,355 | presolved | 4,696–5,598 | N 9 | N 9 | N 9 |
| extreme | 9 | 75–100 | 1,986–2,355 | feasibility | 2,496–2,848 | N 9 | N 9 | N 9 |

Embedded on the ideal graph and both stand-ins:

| instance | encoding | coupled variables | QPU | qubits used (ideal; stand-ins) | longest chain (ideal; stand-ins) |
|---|---|---|---|---|---|
| easy_000_seed_1001 | feasibility | 320 | Advantage2_system1 | 2,507; 2,687, 2,786 | 23; 26, 25 |
| easy_000_seed_1001 | feasibility | 320 | Advantage_system4 | 3,271; 3,119, 3,181 | 30; 29, 28 |
| easy_000_seed_1000 | feasibility | 320 | Advantage2_system1 | 2,975; 2,815, 2,880 | 28; 24, 26 |
| easy_000_seed_1000 | feasibility | 320 | Advantage_system4 | 3,448; 3,513, 3,245 | 33; 32, 31 |
| easy_000_seed_1002 | feasibility | 320 | Advantage2_system1 | 2,417; 2,597, 2,857 | 21; 22, 26 |
| easy_000_seed_1002 | feasibility | 320 | Advantage_system4 | 3,106; 3,356, 3,501 | 27; 33, 33 |
| easy_000_seed_1003 | feasibility | 320 | Advantage2_system1 | 2,661; 2,922, 2,799 | 23; 28, 26 |
| easy_000_seed_1003 | feasibility | 320 | Advantage_system4 | 3,265; 3,250, 3,156 | 32; 28, 28 |
| easy_000_seed_1004 | presolved | 587 | Advantage2_system1 | 3,466; 3,240, 3,165 | 29; 29, 29 |
| easy_000_seed_1004 | presolved | 587 | Advantage_system4 | 3,849; 4,076, 3,935 | 38; 36, 37 |
| easy_000_seed_1004 | feasibility | 271 | Advantage2_system1 | 1,986; 2,227, 1,790 | 20; 24, 18 |
| easy_000_seed_1004 | feasibility | 271 | Advantage_system4 | 2,405; 2,444, 2,519 | 27; 27, 27 |

### Scans over the instance parameters

Synthetic instances as described above, 3 student groups, 3 lecturers and 3 rooms unless the table says otherwise. A cell gives the coupled variables and then, per seed, the verdict on Advantage2_system1 (Zephyr Z12) / Advantage_system4 (Pegasus P16) / Advantage2_system4 (Zephyr Z6): Y embedded on the ideal graph and on both stand-ins, i on the ideal graph only, ? undecided, N proved not to fit. minorminer had 120 s per graph; 11 to 16 courses a week ran with the bounds and clique embeddings only.

**One week (5 days, 7 slots of 90 minutes a day)** (`scan_week.csv`, `scan_week_bounds.csv`):

| courses | placements | default | presolved | feasibility |
|---|---|---|---|---|
| 3 | 105 | 1,138: ??? / ??? / NNN | 438: YYY / YYY / ??? | 108: YYY / YYY / YYY |
| 4 | 140 | 1,174: ??? / ??? / NNN | 614: iii / ??? / ??? | 284: YYY / YYY / ??? |
| 5 | 175 | 1,210: ??? / ??? / NNN | 650: ??? / ??? / ??? | 320: YYY / YYY / ??? |
| 6 | 210 | 1,246–1,526: ??? / ??? / NNN | 686: ??? / ??? / ??? | 356: ii? / ??? / ??? |
| 7 | 245 | 1,282: ??? / ??? / NNN | 722: ??? / ??? / NNN | 392: ??? / ??? / ??? |
| 8 | 280 | 1,318–1,598: ??? / ??? / NNN | 758: ??? / ??? / NNN | 428: ??? / ??? / NNN |
| 9 | 315 | 1,354–1,634: ??? / ??? / NNN | 794: ??? / ??? / NNN | 464: ??? / ??? / NNN |
| 10 | 350 | 1,390–1,670: ??? / ??? / NNN | 830: ??? / ??? / NNN | 500: ??? / ??? / NNN |
| 11 | 385 | 1,426–1,706: ??? / ??? / NNN | 866–901: ??? / ??? / NNN | 536–571: ??? / ??? / NNN |
| 12 | 420 | 1,462–1,742: ??? / ??? / NNN | 902: ??? / ??? / NNN | 572: ??? / ??? / NNN |
| 13 | 455 | 1,498–1,778: ??? / ??? / NNN | 938: ??? / ??? / NNN | 608: ??? / ??? / NNN |
| 14 | 490 | 1,534–1,779: NNN / NNN / NNN | 974: NNN / NNN / NNN | 644: NNN / NNN / NNN |
| 15 | 525 | 1,570–1,850: NNN / NNN / NNN | 1,010–1,045: NNN / NNN / NNN | 680–715: NNN / NNN / NNN |
| 16 | 560 | 1,606–1,886: NNN / NNN / NNN | 1,046–1,081: NNN / NNN / NNN | 716–751: NNN / NNN / NNN |

**One day (7 slots)** (`scan_day.csv`; with 3 groups the generator allows at most 21 courses):

| courses | placements | default | presolved | feasibility |
|---|---|---|---|---|
| 3 | 21 | 230: YYY / YYY / YYY | 90: YYY / YYY / YYY | 24: YYY / YYY / YYY |
| 4 | 28 | 238: YYY / YYY / YYY | 126: YYY / YYY / YYY | 60: YYY / YYY / YYY |
| 5 | 35 | 246: YYY / YYY / YYY | 134: YYY / YYY / YYY | 68: YYY / YYY / YYY |
| 6 | 42 | 254–310: YYY / YYY / YYY | 142: YYY / YYY / YYY | 76: YYY / YYY / YYY |
| 7 | 49 | 262: YYY / YYY / YYY | 150: YYY / YYY / YYY | 84: YYY / YYY / YYY |
| 8 | 56 | 270–326: YYY / YYY / i?? | 158: YYY / YYY / YYY | 92: YYY / YYY / YYY |
| 9 | 63 | 278–334: YYY / YYY / ??? | 166: YYY / YYY / YYY | 100: YYY / YYY / YYY |
| 10 | 70 | 286–342: YYY / YYY / ??? | 174: YYY / YYY / YYY | 108: YYY / YYY / YYY |
| 11 | 77 | 294–350: YYY / YYY / ??? | 182–189: YYY / YYY / YYY | 116–123: YYY / YYY / YYY |
| 12 | 84 | 302–358: YYY / YYY / ??? | 190: YYY / YYY / YYY | 124: YYY / YYY / YYY |
| 13 | 91 | 310–366: YYY / YYY / ??? | 198: YYY / YYY / i?? | 132: YYY / YYY / YYY |
| 14 | 98 | 318–374: YYY / YYY / ??? | 206: YYY / YYY / ??? | 140: YYY / YYY / YYY |
| 15 | 105 | 326–382: YYY / YYY / ??? | 214: YYY / YYY / ??? | 148: YYY / YYY / YYY |
| 16 | 112 | 334: YYY / YYY / ??? | 222: YYY / YYY / ??? | 156: YYY / YYY / iii |
| 17 | 119 | 342–398: YYY / YYY / ??? | 230–237: YYY / YYY / ??? | 164–171: YYY / YYY / ??? |
| 18 | 126 | 350–406: YYY / YYY / ??? | 238: YYY / YYY / ??? | 172: YYY / YYY / ??? |
| 19 | 133 | 358: YYi / YYY / ??? | 246: YYY / YYY / ??? | 180: YYY / YYY / ??? |
| 20 | 140 | 366: iii / iii / ??? | 254: YYY / YYY / ??? | 188: YYY / YYY / ??? |
| 21 | 147 | 374: ii? / i?? / ??? | 262: YYY / YYY / ??? | 196: YYY / YYY / ??? |

**One day, 6 groups, 6 lecturers, 6 rooms** (`scan_day_6groups.csv`):

| courses | placements | default | presolved | feasibility |
|---|---|---|---|---|
| 6 | 42 | 348: YY / YY / ii | 180: YY / YY / YY | 48: YY / YY / YY |
| 9 | 63 | 372–421: YY / YY / ?? | 246: YY / YY / YY | 114: YY / YY / YY |
| 12 | 84 | 396: YY / YY / ?? | 270: YY / YY / i? | 138: YY / YY / YY |
| 15 | 105 | 420: YY / YY / ?? | 294: YY / YY / ?? | 162: YY / YY / ii |
| 18 | 126 | 444–493: i? / ?? / ?? | 318: YY / YY / ?? | 186: YY / YY / ?? |
| 21 | 147 | 468–517: ?? / ?? / ?? | 342: YY / YY / ?? | 210: YY / YY / ?? |
| 24 | 168 | 492–548: ?? / ?? / ?N | 366: ii / ?? / ?? | 234: YY / YY / ?? |
| 27 | 189 | 516–565: ?? / ?? / NN | 390: ?? / ?? / ?? | 258: YY / YY / ?? |
| 30 | 210 | 589–596: ?? / ?? / NN | 414: ?? / ?? / ?? | 282: ii / ?? / ?? |
| 33 | 231 | 613–620: ?? / ?? / NN | 438–445: ?? / ?? / ?? | 306–313: ?? / ?? / ?? |
| 36 | 252 | 588–644: ?? / ?? / NN | 462: ?? / ?? / ?? | 330: ?? / ?? / ?? |
| 39 | 273 | 612–668: ?? / ?? / NN | 486: ?? / ?? / NN | 354: ?? / ?? / NN |
| 42 | 294 | 636: ?? / ?? / NN | 510: ?? / ?? / NN | 378: ?? / ?? / NN |

**Slot length, one week, 3 courses** (`scan_slot_length.csv`):

| slot minutes | placements | default | presolved | feasibility |
|---|---|---|---|---|
| 45 (12 slots a day) | 165 | 1,853–1,873: ?? / ?? / NN | 693: ii / ?? / ?? | 168: YY / YY / ?? |
| 60 (9 slots a day) | 135 | 1,458: ?? / ?? / NN | 558: YY / YY / ?? | 138: YY / YY / i? |
| 75 (8 slots a day) | 120 | 1,298: ?? / ?? / NN | 498: YY / YY / ?? | 123: YY / YY / YY |
| 90 (7 slots a day) | 105 | 1,138: ?? / ?? / NN | 438: YY / YY / ?? | 108: YY / YY / YY |
| 105 (6 slots a day) | 90 | 978: ?? / ?? / ?? | 378: YY / YY / ii | 93: YY / YY / YY |
| 120 (5 slots a day) | 75 | 818: Yi / ?? / ?? | 318: YY / YY / YY | 78: YY / YY / YY |
| 135 (4 slots a day) | 60 | 658: YY / ii / ?? | 258: YY / YY / YY | 63: YY / YY / YY |
| 150 (4 slots a day) | 60 | 658: YY / ii / ?? | 258: YY / YY / YY | 63: YY / YY / YY |
| 165 (4 slots a day) | 60 | 658: YY / Yi / ?? | 258: YY / YY / YY | 63: YY / YY / YY |
| 180 (3 slots a day) | 45 | 498: YY / YY / ?? | 198: YY / YY / YY | 48: YY / YY / YY |

**Days of the week, 3 courses** (`scan_days.csv`):

| days | placements | default | presolved | feasibility |
|---|---|---|---|---|
| 1 | 21 | 230: YY / YY / YY | 90: YY / YY / YY | 24: YY / YY / YY |
| 2 | 42 | 457: YY / YY / ?? | 177: YY / YY / YY | 45: YY / YY / YY |
| 3 | 63 | 684: YY / YY / ?? | 264: YY / YY / YY | 66: YY / YY / YY |
| 4 | 84 | 911: ?? / ?? / ?? | 351: YY / YY / YY | 87: YY / YY / YY |
| 5 | 105 | 1,138: ?? / ?? / NN | 438: YY / YY / ?? | 108: YY / YY / YY |
| 6 | 126 | 1,365: ?? / ?? / NN | 525: YY / YY / ?? | 129: YY / YY / Yi |
| 7 | 147 | 1,592: ?? / ?? / NN | 612: YY / YY / ?? | 150: YY / YY / ?? |

**Rooms, one week, 6 courses** (`scan_rooms_week.csv`):

| rooms | placements | default | presolved | feasibility |
|---|---|---|---|---|
| 1 | 210 | 1,036–1,106: ?? / ?? / NN | 616: ?? / ?? / ?? | 286: ii / ii / ?? |
| 2 | 210 | 1,176–1,246: ?? / ?? / NN | 686: ?? / ?? / ?? | 356: ?? / ?? / ?? |
| 3 | 210 | 1,246: ?? / ?? / NN | 686: ?? / ?? / ?? | 356: i? / ?? / ?? |
| 4 | 210 | 1,316: ?? / ?? / NN | 756: ?? / ?? / ?? | 426: ?? / ?? / ?? |
| 5 | 210 | 1,316–1,386: ?? / ?? / NN | 756: ?? / ?? / ?? | 426: ?? / ?? / ?? |
| 6 | 210 | 1,386: ?? / ?? / NN | 546: i? / i? / ?? | 216: YY / YY / ?? |

**Rooms, one day, 15 courses** (`scan_rooms_day.csv`):

| rooms | placements | default | presolved | feasibility |
|---|---|---|---|---|
| 3 | 105 | 326: YY / YY / ?? | 214: YY / YY / ?? | 148: YY / YY / YY |
| 4 | 105 | 340: YY / YY / ?? | 228: YY / YY / ?? | 162: YY / YY / ii |
| 5 | 105 | 340–354: YY / YY / ?? | 228: YY / YY / ?? | 162: YY / YY / ii |
| 6 | 105 | 354: YY / YY / ?? | 228: YY / YY / ?? | 162: YY / YY / ii |

The generator refused: rooms = 1 (2 seeds), rooms = 2 (2 seeds).

**Lecturers, one day, 15 courses** (`scan_lecturers_day.csv`):

| lecturers | placements | default | presolved | feasibility |
|---|---|---|---|---|
| 1 | 105 | 326: YY / YY / ?? | 214: YY / YY / ?? | 148: YY / YY / YY |
| 2 | 105 | 326: YY / YY / ?? | 214: YY / YY / ?? | 148: YY / YY / YY |
| 3 | 105 | 326: YY / YY / ?? | 214: YY / YY / ?? | 148: YY / YY / YY |
| 4 | 105 | 326: YY / YY / ?? | 214: YY / YY / ?? | 148: YY / YY / YY |
| 5 | 105 | 326: YY / YY / ?? | 214: YY / YY / ?? | 148: YY / YY / YY |
| 6 | 105 | 326: YY / YY / ?? | 214: YY / YY / ?? | 148: YY / YY / YY |

**Student groups, one day, 15 courses** (`scan_groups_day.csv`):

| groups | placements | default | presolved | feasibility |
|---|---|---|---|---|
| 3 | 105 | 326: YY / YY / ?? | 214: YY / YY / ?? | 148: YY / YY / YY |
| 4 | 105 | 348–397: YY / YY / ?? | 236: YY / YY / ?? | 148: YY / YY / YY |
| 5 | 105 | 370: YY / YY / ?? | 258: YY / YY / ?? | 148: YY / YY / YY |
| 6 | 105 | 392–448: YY / YY / ?? | 280: YY / YY / ?? | 148: YY / YY / YY |
| 7 | 105 | 414: YY / YY / ?? | 302: YY / YY / ?? | 148: YY / YY / YY |
| 8 | 105 | 436: YY / YY / ?? | 324: YY / YY / ?? | 148: YY / YY / YY |

### Longer searches

minorminer with 30 minutes per graph and one stand-in, seed 1 (`long_*.csv`). The qubits and the longest chain are those of the embedding on the stand-in, or on the ideal graph when only that one was found.

| instance | encoding | coupled variables | Advantage2_system1 | Advantage_system4 |
|---|---|---|---|---|
| 5 days × 7 slots, 3 courses | default | 1,138 | ideal graph only (3,909 qubits, chains ≤ 33, 1777 s) | embedded (ideal graph and the stand-in) (4,794 qubits, chains ≤ 56, 1113 s) |
| 5 days × 7 slots, 4 courses | default | 1,174 | undecided | undecided |
| 5 days × 7 slots, 4 courses | presolved | 614 | embedded (ideal graph and the stand-in) (3,397 qubits, chains ≤ 30, 252 s) | embedded (ideal graph and the stand-in) (4,391 qubits, chains ≤ 42, 271 s) |
| 5 days × 7 slots, 5 courses | presolved | 650 | ideal graph only (3,944 qubits, chains ≤ 40, 609 s) | embedded (ideal graph and the stand-in) (4,599 qubits, chains ≤ 37, 842 s) |
| 5 days × 7 slots, 6 courses | feasibility | 356 | embedded (ideal graph and the stand-in) (3,435 qubits, chains ≤ 28, 702 s) | embedded (ideal graph and the stand-in) (4,191 qubits, chains ≤ 35, 340 s) |
| 5 days × 7 slots, 6 courses | presolved | 686 | undecided | undecided |
| 5 days × 7 slots, 7 courses | feasibility | 392 | ideal graph only (4,082 qubits, chains ≤ 32, 1589 s) | undecided |
| 5 days × 7 slots, 8 courses | feasibility | 428 | undecided | undecided |
| easy_000_seed_1000 | default | 1,210 | undecided | undecided |
| easy_000_seed_1000 | presolved | 650 | ideal graph only (3,938 qubits, chains ≤ 31, 344 s) | embedded (ideal graph and the stand-in) (4,606 qubits, chains ≤ 41, 602 s) |
| easy_001_seed_1010 | feasibility | 534 | undecided | undecided |
| easy_001_seed_1010 | presolved | 1,084 | undecided | undecided |
| medium_004_seed_1044 | feasibility | 940 | undecided | undecided |

### Where the variables come from

Coupled variables per family of the compiler's variable names, `easy_000_seed_1000` (5 courses, one week of 35 slots, 3 rooms; `easy000_encodings.csv`):

| family | default | presolved | feasibility |
|---|---|---|---|
| `x` | 175 | 175 | 175 |
| `idle_e` | 105 | 105 | – |
| `idle_s` | 105 | 105 | – |
| `slack_CAP` | 280 | – | – |
| `slack_CAP_clean` | 280 | – | – |
| `slack_MC` | 5 | 5 | 5 |
| `slack_RC` | 70 | 70 | 70 |
| `slack_RC_clean` | 70 | 70 | 70 |
| `y` | 105 | 105 | – |
| `z` | 15 | 15 | – |
| coupled variables | 1,210 | 650 | 320 |
| couplings | 10,035 | 5,275 | 4,270 |

### Precision

Ising coefficients after the scaling a QPU applies with the example ranges h in [-4, 4] and J in [-1, 1] (`precision_*.csv`, from `dwave_capacity_precision.py`); 0.01 is the size of the integrated control errors in D-Wave's documentation [12]:

| instance | penalties | encoding | Ising dynamic range | smallest coefficient after scaling | share of nonzero coefficients below 0.01 |
|---|---|---|---|---|---|
| easy_000_seed_1000 | as in cfg/qubo_cfg.yaml | default | 1.8e+07 | 2.2e-07 | 72.0% |
| easy_000_seed_1000 | as in cfg/qubo_cfg.yaml | presolved | 1.8e+07 | 2.2e-07 | 46.8% |
| easy_000_seed_1000 | as in cfg/qubo_cfg.yaml | feasibility | 1.3e+07 | 3.0e-07 | 31.4% |
| easy_000_seed_1000 | smallest sufficient | default | 1.5e+07 | 7.5e-08 | 65.5% |
| easy_000_seed_1000 | smallest sufficient | presolved | 8.5e+04 | 3.8e-05 | 13.2% |
| easy_000_seed_1000 | smallest sufficient | feasibility | 4.2e+04 | 7.7e-05 | 3.9% |
| 3_studies_instance | as in cfg/qubo_cfg.yaml | default | 3.9e+09 | 1.0e-09 | 99.8% |
| 3_studies_instance | as in cfg/qubo_cfg.yaml | presolved | 3.9e+09 | 1.0e-09 | 99.8% |
| 3_studies_instance | as in cfg/qubo_cfg.yaml | feasibility | 2.9e+09 | 1.4e-09 | 99.8% |
<!-- RESULTS:END -->

## What is not known

- **The exact working graphs** (see above). "Embedded" verdicts on the
  stand-ins are evidence for the real QPUs, not proof; on Advantage_system4
  the vendor's real-chip clique (177) and our stand-ins (173) agree closely.
  A user of D-Wave's cloud service can save a solver's `qubits` and
  `couplers` as JSON and pass `--working-graph QPU=FILE` to get definitive
  answers for that calibration.
- **How precise Advantage2 is.** D-Wave's error documentation gives
  magnitudes for earlier systems only.
- **The undecided cases.** minorminer is a heuristic: a longer search may move
  a case from undecided to embedded, never to proved. Outcomes near the time
  limit also depend on the machine and its load; the time limits and seeds are
  recorded in every row.
- **Other formulations.** The verdicts concern the authors' QUBO. A
  formulation with fewer auxiliary variables could fit larger instances; the
  clique sizes, and the statements that hold for every QUBO with at most a
  given number of coupled variables, do not depend on the formulation.
- **Quality.** Fitting says nothing about the answers a QPU would return.

## Result files

Every row: `instance`, `encoding`, the scan parameters (for generated
instances), `courses`, `candidate_placements`, `largest_course_candidates`,
`qubo_variables`, `coupled_variables`, `couplings`, `max_degree`,
`mean_degree`, `degeneracy`, `treewidth_grid_bound`, `treewidth_at_least`,
`ising_dynamic_range`, `coupled_by_family` (JSON: coupled variables per family
of the compiler's variable names: `x` placements, `y`/`z` group activity per
slot/day, `idle_s`/`idle_e` idle-time markers, `slack_MC` course-hours slack,
`slack_RC`/`slack_RC_clean` room-count slack, `slack_CAP`/`slack_CAP_clean`
seat-capacity slack), then per QPU `qpu`, `qpu_qubits`, `qpu_couplers`,
`host_treewidth_at_most`, `largest_clique_on_ideal_graph`,
`qubits_needed_at_least`, `couplers_needed_at_least`, `verdict`, `reason`,
`ideal_graph` and `thinned_graphs` (JSON: found, method, seconds, qubits used,
longest and mean chain), `embed_timeout`, `tools` (library versions).
Columns that do not apply are empty; for QUBOs with more coupled variables than
any QPU has qubits the treewidth bounds are not computed.

<!-- COMMANDS:BEGIN -->
## How each result file was made

From the root of the authors' code repository, with `scripts/dwave_capacity.py` as of commit `8e35775`, `scripts/dwave_capacity_precision.py` as of commit `9508038` and `checks/pr5_milp_rows.py` as of commit `27d1186`; each command with `--csv results/<file>` (the `.txt` files: standard output):

| file | run on | command |
|---|---|---|
| `facts.txt` | 2026-10-11 | `python scripts/dwave_capacity.py --facts --thinned 2 > results/facts.txt` |
| `paper_3studies.csv` | 2026-10-11 | `python scripts/dwave_capacity.py --instance artifacts/3studies/3_studies_instance.yaml --jobs 1` |
| `paper_synthetic_bounds.csv` | 2026-10-10 | `python scripts/dwave_capacity.py --instance repository_ready/instances/synthetic/<each of the 64 files>.yaml --jobs 3` |
| `paper_synthetic_embeddings.csv` | 2026-10-11 | `python scripts/dwave_capacity.py --instance <the instances not proved in paper_synthetic_bounds.csv on Advantage2_system1 or Advantage_system4 (each passed as --instance)> --qpu Advantage2_system1 --qpu Advantage_system4 --embed-timeout 300 --thinned 2 --jobs 8` |
| `scan_week.csv` | 2026-10-11 | `python scripts/dwave_capacity.py --days 5 --groups 3 --teachers 3 --rooms 3 --courses 3 --scan courses=3:10:1 --seeds 1 2 3 --embed-timeout 120 --thinned 2 --jobs 5` |
| `scan_week_bounds.csv` | 2026-10-10 | `python scripts/dwave_capacity.py --days 5 --groups 3 --teachers 3 --rooms 3 --courses 11 --scan courses=11:16:1 --seeds 1 2 3 --qpu Advantage2_system1 --qpu Advantage2_system4 --qpu Advantage_system4 --jobs 9` |
| `scan_day.csv` | 2026-10-11 | `python scripts/dwave_capacity.py --days 1 --groups 3 --teachers 3 --rooms 3 --courses 3 --scan courses=3:21:1 --seeds 1 2 3 --embed-timeout 120 --thinned 2 --jobs 5` |
| `scan_day_6groups.csv` | 2026-10-10 | `python scripts/dwave_capacity.py --seeds 1 2 --qpu Advantage2_system1 --qpu Advantage2_system4 --qpu Advantage_system4 --embed-timeout 120 --thinned 2 --jobs 9 --days 1 --groups 6 --teachers 6 --rooms 6 --courses 6 --scan courses=6:42:3` |
| `scan_slot_length.csv` | 2026-10-10 | `python scripts/dwave_capacity.py --seeds 1 2 --qpu Advantage2_system1 --qpu Advantage2_system4 --qpu Advantage_system4 --embed-timeout 120 --thinned 2 --jobs 9 --days 5 --groups 3 --teachers 3 --rooms 3 --courses 3 --scan slot_minutes=45:180:15` |
| `scan_days.csv` | 2026-10-10 | `python scripts/dwave_capacity.py --seeds 1 2 --qpu Advantage2_system1 --qpu Advantage2_system4 --qpu Advantage_system4 --embed-timeout 120 --thinned 2 --jobs 9 --days 1 --groups 3 --teachers 3 --rooms 3 --courses 3 --scan days=1:7:1` |
| `scan_rooms_week.csv` | 2026-10-10 | `python scripts/dwave_capacity.py --days 5 --courses 6 --seeds 1 2 --qpu Advantage2_system1 --qpu Advantage2_system4 --qpu Advantage_system4 --embed-timeout 120 --thinned 2 --jobs 9 --groups 3 --teachers 3 --rooms 3 --scan rooms=1:6:1` |
| `scan_rooms_day.csv` | 2026-10-10 | `python scripts/dwave_capacity.py --days 1 --courses 15 --seeds 1 2 --qpu Advantage2_system1 --qpu Advantage2_system4 --qpu Advantage_system4 --embed-timeout 120 --thinned 2 --jobs 9 --groups 3 --teachers 3 --rooms 3 --scan rooms=1:6:1` |
| `scan_lecturers_day.csv` | 2026-10-10 | `python scripts/dwave_capacity.py --days 1 --courses 15 --seeds 1 2 --qpu Advantage2_system1 --qpu Advantage2_system4 --qpu Advantage_system4 --embed-timeout 120 --thinned 2 --jobs 9 --groups 3 --teachers 3 --rooms 3 --scan teachers=1:6:1` |
| `scan_groups_day.csv` | 2026-10-10 | `python scripts/dwave_capacity.py --days 1 --courses 15 --seeds 1 2 --qpu Advantage2_system1 --qpu Advantage2_system4 --qpu Advantage_system4 --embed-timeout 120 --thinned 2 --jobs 9 --groups 3 --teachers 3 --rooms 3 --scan groups=3:8:1` |
| `long_week3_default_Advantage2_system1.csv` | 2026-10-10 | `python scripts/dwave_capacity.py --days 5 --groups 3 --teachers 3 --rooms 3 --courses 3 --seeds 1 --encoding default --qpu Advantage2_system1 --embed-timeout 1800 --thinned 1` |
| `long_week4_default_Advantage2_system1.csv` | 2026-10-10 | `python scripts/dwave_capacity.py --days 5 --groups 3 --teachers 3 --rooms 3 --seeds 1 --courses 4 --encoding default --qpu Advantage2_system1 --embed-timeout 1800 --thinned 1` |
| `long_week_presolved_Advantage2_system1.csv` | 2026-10-10 | `python scripts/dwave_capacity.py --days 5 --groups 3 --teachers 3 --rooms 3 --seeds 1 --courses 4 --scan courses=4:6:1 --encoding presolved --qpu Advantage2_system1 --embed-timeout 1800 --thinned 1 --jobs 3` |
| `long_week_feasibility_Advantage2_system1.csv` | 2026-10-10 | `python scripts/dwave_capacity.py --days 5 --groups 3 --teachers 3 --rooms 3 --seeds 1 --courses 6 --scan courses=6:8:1 --encoding feasibility --qpu Advantage2_system1 --embed-timeout 1800 --thinned 1 --jobs 3` |
| `long_easy000_default_Advantage2_system1.csv` | 2026-10-10 | `python scripts/dwave_capacity.py --instance repository_ready/instances/synthetic/easy_000_seed_1000.yaml --encoding default --qpu Advantage2_system1 --embed-timeout 1800 --thinned 1` |
| `long_easy000_presolved_Advantage2_system1.csv` | 2026-10-10 | `python scripts/dwave_capacity.py --instance repository_ready/instances/synthetic/easy_000_seed_1000.yaml --encoding presolved --qpu Advantage2_system1 --embed-timeout 1800 --thinned 1` |
| `long_easy001_Advantage2_system1.csv` | 2026-10-10 | `python scripts/dwave_capacity.py --instance repository_ready/instances/synthetic/easy_001_seed_1010.yaml --encoding feasibility --encoding presolved --qpu Advantage2_system1 --embed-timeout 1800 --thinned 1 --jobs 2` |
| `long_medium1044_Advantage2_system1.csv` | 2026-10-10 | `python scripts/dwave_capacity.py --instance repository_ready/instances/synthetic/medium_004_seed_1044.yaml --encoding feasibility --qpu Advantage2_system1 --embed-timeout 1800 --thinned 1` |
| `long_week3_default_Advantage_system4.csv` | 2026-10-10 | `python scripts/dwave_capacity.py --days 5 --groups 3 --teachers 3 --rooms 3 --courses 3 --seeds 1 --encoding default --qpu Advantage_system4 --embed-timeout 1800 --thinned 1` |
| `long_week4_default_Advantage_system4.csv` | 2026-10-10 | `python scripts/dwave_capacity.py --days 5 --groups 3 --teachers 3 --rooms 3 --seeds 1 --courses 4 --encoding default --qpu Advantage_system4 --embed-timeout 1800 --thinned 1` |
| `long_week_presolved_Advantage_system4.csv` | 2026-10-10 | `python scripts/dwave_capacity.py --days 5 --groups 3 --teachers 3 --rooms 3 --seeds 1 --courses 4 --scan courses=4:6:1 --encoding presolved --qpu Advantage_system4 --embed-timeout 1800 --thinned 1 --jobs 3` |
| `long_week_feasibility_Advantage_system4.csv` | 2026-10-10 | `python scripts/dwave_capacity.py --days 5 --groups 3 --teachers 3 --rooms 3 --seeds 1 --courses 6 --scan courses=6:8:1 --encoding feasibility --qpu Advantage_system4 --embed-timeout 1800 --thinned 1 --jobs 3` |
| `long_easy000_default_Advantage_system4.csv` | 2026-10-10 | `python scripts/dwave_capacity.py --instance repository_ready/instances/synthetic/easy_000_seed_1000.yaml --encoding default --qpu Advantage_system4 --embed-timeout 1800 --thinned 1` |
| `long_easy000_presolved_Advantage_system4.csv` | 2026-10-10 | `python scripts/dwave_capacity.py --instance repository_ready/instances/synthetic/easy_000_seed_1000.yaml --encoding presolved --qpu Advantage_system4 --embed-timeout 1800 --thinned 1` |
| `long_easy001_Advantage_system4.csv` | 2026-10-10 | `python scripts/dwave_capacity.py --instance repository_ready/instances/synthetic/easy_001_seed_1010.yaml --encoding feasibility --encoding presolved --qpu Advantage_system4 --embed-timeout 1800 --thinned 1 --jobs 2` |
| `long_medium1044_Advantage_system4.csv` | 2026-10-10 | `python scripts/dwave_capacity.py --instance repository_ready/instances/synthetic/medium_004_seed_1044.yaml --encoding feasibility --qpu Advantage_system4 --embed-timeout 1800 --thinned 1` |
| `lato_placements.txt` | 2026-10-11 | `python checks/pr5_milp_rows.py artifacts/Corrected_lato_3fix.yaml > results/lato_placements.txt` |
| `easy000_encodings.csv` | 2026-10-11 | `python scripts/dwave_capacity.py --instance repository_ready/instances/synthetic/easy_000_seed_1000.yaml --qpu Advantage2_system1` |
| `easy000_encodings_sufficient_penalties.csv` | 2026-10-11 | `python scripts/dwave_capacity.py --instance repository_ready/instances/synthetic/easy_000_seed_1000.yaml --qpu Advantage2_system1 --qubo-config penalty_profile=sufficient` |
| `precision_easy000.csv` | 2026-10-11 | `python scripts/dwave_capacity_precision.py --instance repository_ready/instances/synthetic/easy_000_seed_1000.yaml` |
| `precision_easy000_sufficient_penalties.csv` | 2026-10-11 | `python scripts/dwave_capacity_precision.py --instance repository_ready/instances/synthetic/easy_000_seed_1000.yaml --qubo-config penalty_profile=sufficient` |
| `precision_3studies.csv` | 2026-10-11 | `python scripts/dwave_capacity_precision.py --instance artifacts/3studies/3_studies_instance.yaml` |
<!-- COMMANDS:END -->

## References

1. D-Wave. *Per-QPU Solver Properties and Schedules*. Online documentation,
   https://docs.dwavequantum.com/en/latest/quantum_research/solver_properties_specific.html
   (Tables 25–30; accessed 11 October 2026).
2. K. Boothby, P. Bunyk, J. Raymond, A. Roy. *Next-Generation Topology of
   D-Wave Quantum Processors*. arXiv:2003.00133, 2020.
   https://arxiv.org/abs/2003.00133
3. K. Boothby, A. D. King, J. Raymond. *Zephyr Topology of D-Wave Quantum
   Processors*. D-Wave Technical Report 14-1056A-A, 2021-09-22.
   https://dwavequantum.com/media/2uznec4s/14-1056a-a_zephyr_topology_of_d-wave_quantum_processors.pdf
4. D-Wave. *General QPU Solver Properties*. Online documentation,
   https://docs.dwavequantum.com/en/latest/quantum_research/solver_properties_all.html
   (accessed 11 October 2026).
5. D-Wave. *Minor-Embedding: Best Practices*. Online documentation,
   https://docs.dwavequantum.com/en/latest/quantum_research/embedding_guidance.html
   (section Embedding Complete Graphs, Table 56; accessed 11 October 2026).
6. H. L. Bodlaender, T. Wolle, A. M. C. A. Koster. *Contraction and Treewidth
   Lower Bounds*. Journal of Graph Algorithms and Applications 10(1):5–49,
   2006 (contraction degeneracy, §1; the MMD+(min-d) heuristic, §1 and later
   sections).
   https://doi.org/10.7155/jgaa.00117
7. M. Cygan, F. V. Fomin, Ł. Kowalik, D. Lokshtanov, D. Marx, M. Pilipczuk,
   M. Pilipczuk, S. Saurabh. *Parameterized Algorithms*. Springer, Cham, 2015,
   Lemma 7.19. https://doi.org/10.1007/978-3-319-21275-3
8. D-Wave. *minorminer* (version 0.2.21). https://github.com/dwavesystems/minorminer
   (README; accessed 11 October 2026).
9. K. Boothby, A. D. King, A. Roy. *Fast clique minor generation in Chimera
   qubit connectivity graphs*. arXiv:1507.04774, 2015.
   https://arxiv.org/abs/1507.04774
10. J. Cai, W. G. Macready, A. Roy. *A practical heuristic for finding graph
    minors*. arXiv:1406.2741, 2014. https://arxiv.org/abs/1406.2741
11. D-Wave. *Release Notes*. Online documentation,
    https://docs.dwavequantum.com/projects/leap_sapi/en/latest/release_notes.html
    (entry "2021-10-05 Release: Hybrid CQM Solver and Advantage System
    Performance Update", subsection Higher Yield; accessed 11 October 2026).
12. D-Wave. *Errors and Error Correction*. Online documentation,
    https://docs.dwavequantum.com/en/latest/quantum_research/errors.html
    (sections ICE and Virtual Graphs; accessed 11 October 2026).
