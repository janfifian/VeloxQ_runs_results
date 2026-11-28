#!/usr/bin/env python
"""How large a timetabling instance fits on a D-Wave quantum processor (QPU)?

Topology only: can the time-allocation QUBO that our compiler builds for an
instance be minor-embedded in the qubit graph of a current D-Wave QPU, as it
must be to run on the QPU directly (not through a hybrid solver)? Whether the
QPU then solves it well is a separate question (coefficient precision, chain
strength; see "Precision" below).

Instances
---------
Either existing instance files (``--instance``), or synthetic ones made by the
project's generator from explicit parameters: days of the week, the slot grid
of a day (first start, last end, slot length, break between slots), student
groups, lecturers, rooms, courses, lecturer availability; every other
generator knob comes from a base preset (``--base-preset``, default the easy
tier). In the generator every course is one weekly lesson that fills one
slot, taught by one lecturer to one or more student groups, so a course has
one candidate placement per slot of the week in which its lecturer is
available. ``--scan`` varies one parameter over a range.

Logical graph
-------------
The instance is compiled by ``TimeAllocationQUBO`` under one of three encodings:

* ``default``: ``cfg/qubo_cfg.yaml`` as is -- the encoding of our experiments
  (course-hours and block-limit rows, non-overlap, PR5, room rows per 15-minute
  cell with their slack bits, group activity indicators, exact idle time);
* ``presolved``: the same with ``room_presolve: counts`` (review R1);
* ``feasibility``: presolved, without soft terms: no lecturer preference, time
  of day, active days, idle time, lecture-before, and no activity indicators.

``--qubo-config KEY=VALUE`` overrides a compiler setting in every encoding
(e.g. ``penalty_profile=sufficient``).

The logical graph has a node per variable that has at least one coupling and
an edge per nonzero coupling. A variable without couplings needs no qubit
connections (its best value follows from its sign) and is left out. The
report counts the coupled variables per family of the compiler's variable
names: ``x`` placements, ``y``/``z`` group activity per slot/day,
``idle_s``/``idle_e`` idle-time markers, ``mc_ladder``, and slack bits of the
course-hours rows (``slack_MC``), room-count rows (``slack_RC``,
``slack_RC_clean``) and room-capacity rows (``slack_CAP``, ``slack_CAP_clean``).

Verdicts per QPU
----------------
* ``proved: does not fit`` -- a necessary condition for a minor embedding fails.
  Each lower bound below holds for every embedding:
  - variables with couplings > working qubits;
  - qubits: a chain of L qubits in a graph of degree Delta has at most
    L(Delta-2)+2 couplers leaving it, so a logical variable with d couplings
    needs a chain of at least max(1, ceil((d-2)/(Delta-2))) qubits; the sum
    over the variables must not exceed the working qubits;
  - couplers: every coupling needs its own physical coupler between two chains
    and a chain of L qubits needs L-1 couplers inside it; the sum must not exceed
    the working couplers;
  - treewidth: a minor never has a larger treewidth than its host. The host's
    treewidth is bounded above by the width of an elimination order computed
    here on the full (ideal) graph -- which bounds every working graph, a
    subgraph -- and the logical graph's treewidth is bounded below by its
    degeneracy, by the contraction-degeneracy bound MMD+ (min-d), and by the
    placement grid: the placements of a course are coupled pairwise (its
    course-hours row), and so are the placements starting in the same slot
    when a room row covers them all; such placements form the line graph of
    the bipartite graph between courses and slots, whose balanced separators
    are large (see ``grid_separator_bound``). A clique of k logical variables
    has treewidth k-1, so the course-hours clique of a course with more
    candidate placements than the bound cannot be embedded.
* ``embedded`` -- an embedding was found and checked here independently
  (chains disjoint and connected, every coupling realised), either
  - by a clique embedding: every graph on n vertices is a subgraph of the
    complete graph K_n, so a clique embedding of K_n embeds every QUBO with n
    coupled variables; busclique (minorminer) builds clique embeddings of
    Pegasus and Zephyr graphs, also with qubits and couplers missing; or
  - by minorminer's heuristic search (``--embed-timeout`` seconds per graph).
  On the ideal graph it is an optimistic answer; on graphs thinned at random to
  the published numbers of working qubits and couplers (as D-Wave's own guide
  simulates yield) a realistic one; on a QPU's exact working graph
  (``--working-graph``, exported with a Leap account) the definitive one for
  that calibration.
* ``undecided`` -- no bound excludes it and no embedding was found within the
  time given. minorminer is a heuristic: failing to find an embedding is not a
  proof that none exists.

Hardware (read on 2026-10-10)
-----------------------------
Per-QPU solver properties, docs.dwavequantum.com/en/latest/quantum_research/
solver_properties_specific.html: Advantage2_system1 Zephyr Z12, 4,575 qubits,
41,474 couplers; Advantage2_system2 Z12, 4,506 / 40,302; Advantage2_system4 Z6,
1,202 / 10,537; Advantage_system4 Pegasus P16, 5,627 / 40,279;
Advantage_system6 P16, 5,612 / 40,088. Working graphs change with calibrations
and are given only to Leap users; the ideal graphs are built with
dwave-networkx (P16 fabric: 5,640 qubits, 40,484 couplers, degree 15; Z12:
4,800 / 45,864, degree 20; Z6: 1,248 / 11,400). D-Wave's papers bound the
treewidth by 12M-4 (Pegasus P_M; Boothby et al., arXiv:2003.00133) and 16m+8
(Zephyr Z_m; D-Wave technical report 14-1056A-A); the bounds verified here
are slightly weaker (P16: 202, Z12: 202, Z6: 106) and are the ones used.
Clique embeddings built by busclique: K_184 on the ideal Z12, K_180 on the
ideal P16, K_88 on the ideal Z6; on thinned stand-ins about K_107-111
(Advantage2_system1), K_173-176 (Advantage_system4), K_70-75
(Advantage2_system4). ``--facts`` recomputes all of these. On the real
Advantage_system4 working graph (unchanged since its release with these counts)
D-Wave's release notes of 2021-10-05 report an embedded K_177 with chains of 17.

Precision (not part of the verdict)
-----------------------------------
A QPU takes h in a bounded range ([-4, 4] on Advantage) and J in [-1, 1]
(extended [-2, 1]) and scales the problem into them; integrated control errors
blur small coefficients. The report gives the Ising dynamic range of each QUBO
(largest over smallest nonzero |coefficient|); how much of it a given QPU
resolves is not published for Advantage2 in a form we could rely on.

Run (needs minorminer and dwave-networkx):
  python scripts/dwave_capacity.py --instance artifacts/generated_instances/easy_000_seed_1000.yaml --embed-timeout 60
  python scripts/dwave_capacity.py --days 1 --groups 2 --teachers 2 --rooms 2 --courses 3 \\
      --day-start 8:00 --day-end 20:00 --slot-minutes 90 --break-minutes 15 --seeds 1 2 --embed-timeout 60
  python scripts/dwave_capacity.py --days 5 --groups 3 --teachers 3 --rooms 3 --courses 3 \\
      --scan courses=3:12:1 --seeds 1 2 --embed-timeout 120 --jobs 8 --csv capacity.csv
  python scripts/dwave_capacity.py --facts        (hardware table, treewidth bounds, clique embeddings)
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import contextlib
import copy
import csv
import heapq
import io
import json
import math
import random
import sys
import tempfile
import time
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
from _pipeline_helpers import setup_environment  # noqa: E402

setup_environment(REPO)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass
warnings.filterwarnings("ignore", message="dwave-networkx is deprecated")

import networkx as nx  # noqa: E402
import yaml  # noqa: E402
import dwave_networkx as dnx  # noqa: E402
import minorminer  # noqa: E402
from minorminer import busclique  # noqa: E402

from etpmachine.ETPMachine_ProblemInstance import ProblemInstance  # noqa: E402
from etpmachine.ETPMachine_QUBO import TimeAllocationQUBO  # noqa: E402
from etpmachine.utils import run_record  # noqa: E402

FACTS_READ_ON = "2026-10-10"
FACTS_SOURCE = "https://docs.dwavequantum.com/en/latest/quantum_research/solver_properties_specific.html"

# Published working graphs (per-QPU solver properties page, read on FACTS_READ_ON).
HARDWARE: Dict[str, Dict[str, Any]] = {
    "Advantage2_system1": {"topology": "zephyr", "m": 12, "t": 4, "qubits": 4575, "couplers": 41474},
    "Advantage2_system2": {"topology": "zephyr", "m": 12, "t": 4, "qubits": 4506, "couplers": 40302},
    "Advantage2_system4": {"topology": "zephyr", "m": 6, "t": 4, "qubits": 1202, "couplers": 10537},
    "Advantage_system4": {"topology": "pegasus", "m": 16, "qubits": 5627, "couplers": 40279},
    "Advantage_system6": {"topology": "pegasus", "m": 16, "qubits": 5612, "couplers": 40088},
}
# minorminer is tried on one QPU of each design; Advantage2_system2 and
# Advantage_system6 (the same designs as Advantage2_system1 and
# Advantage_system4 with a few working qubits fewer) get the bounds and the
# clique embeddings unless named with --embed-on.
DEFAULT_EMBED_TARGETS = ("Advantage2_system1", "Advantage2_system4", "Advantage_system4")

SOFT_OFF = {k: False for k in ("enable_satisfaction", "enable_time_of_day", "enable_min_days",
                               "enable_gap", "enable_lecture_before", "enable_y_linking",
                               "enable_z_linking")}
ENCODINGS: Dict[str, Dict[str, Any]] = {
    "default": {},
    "presolved": {"room_presolve": "counts"},
    "feasibility": {"room_presolve": "counts", **SOFT_OFF},
}

SCAN_DIMENSIONS = ("days", "groups", "teachers", "rooms", "courses", "slot_minutes")
CLIQUE_SEEDS = (0, 1, 2)

CSV_FIELDS = [
    "instance", "encoding", "days", "slots_per_day", "slot_minutes", "break_minutes", "groups",
    "lecturers", "rooms", "courses_requested", "availability", "seed",
    "courses", "candidate_placements", "largest_course_candidates", "qubo_variables",
    "coupled_variables", "couplings", "max_degree", "mean_degree", "degeneracy",
    "treewidth_grid_bound", "treewidth_at_least", "ising_dynamic_range", "coupled_by_family",
    "qpu", "qpu_qubits", "qpu_couplers", "host_treewidth_at_most", "largest_clique_on_ideal_graph",
    "qubits_needed_at_least", "couplers_needed_at_least", "verdict", "reason",
    "ideal_graph", "thinned_graphs", "exact_working_graph", "embed_timeout", "tools",
]


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


def tools_used() -> str:
    return f"minorminer {minorminer.__version__}, dwave-networkx {dnx.__version__}, networkx {nx.__version__}"


# ==============================================================================
# Hardware graphs
# ==============================================================================

def ideal_graph(spec: Dict[str, Any], coordinates: bool = False) -> nx.Graph:
    """The full (100 % yield) graph of the QPU's design: Pegasus P_M fabric or
    Zephyr Z_{m,t}."""
    if spec["topology"] == "pegasus":
        return dnx.pegasus_graph(spec["m"], fabric_only=True, coordinates=coordinates)
    return dnx.zephyr_graph(spec["m"], spec["t"], coordinates=coordinates)


def elimination_order_width(G: nx.Graph, order: List[Any]) -> int:
    """Width of an elimination order: eliminating a vertex joins all its
    remaining neighbours to each other; the width is the largest number of
    remaining neighbours any vertex has when it is eliminated. Every
    elimination order's width is an upper bound on the treewidth."""
    if len(order) != G.number_of_nodes() or set(order) != set(G.nodes):
        raise ValueError("the order must list every vertex once")
    adj = {v: set(G[v]) for v in G}
    width = 0
    for v in order:
        nbrs = adj.pop(v)
        width = max(width, len(nbrs))
        for a in nbrs:
            s = adj[a]
            s.discard(v)
            s.update(nbrs)
            s.discard(a)
    return width


def column_elimination_order(G: nx.Graph, order_key, is_vertical) -> List[Any]:
    """The order D-Wave's papers describe: vertical qubits one parallel column
    at a time, a horizontal qubit as soon as all its vertical neighbours are
    eliminated."""
    vertical = sorted((v for v in G if is_vertical(v)), key=order_key)
    left = {v: sum(1 for x in G[v] if is_vertical(x)) for v in G if not is_vertical(v)}
    order = [h for h, n in left.items() if n == 0]
    placed = set(order)
    for v in vertical:
        order.append(v)
        for h in G[v]:
            if h in left and h not in placed:
                left[h] -= 1
                if left[h] == 0:
                    order.append(h)
                    placed.add(h)
    order.extend(h for h in left if h not in placed)
    return order


def _elimination_width(G: nx.Graph, order_key, is_vertical) -> int:
    return elimination_order_width(G, column_elimination_order(G, order_key, is_vertical))


_TW_CACHE: Dict[Tuple, int] = {}


def host_treewidth_upper_bound(spec: Dict[str, Any]) -> int:
    """Certified upper bound on the treewidth of the QPU design's full graph
    (hence of every working graph, a subgraph of it)."""
    key = (spec["topology"], spec["m"], spec.get("t"))
    if key not in _TW_CACHE:
        G = ideal_graph(spec, coordinates=True)
        vertical = lambda c: c[0] == 0  # noqa: E731
        if spec["topology"] == "pegasus":
            # coordinates (u, w, k, z): columns by w, then k, then z
            orders = [lambda c: (12 * c[1] + c[2], c[3])]
        else:
            # coordinates (u, w, k, j, z): columns by w; (w, k, z, j) is the best of the
            # orders tried (Z12: 202, against 212 for (w, k, j, z))
            orders = [lambda c: (c[1], c[2], c[4], c[3]), lambda c: (c[1], c[2], c[3], c[4])]
        _TW_CACHE[key] = min(_elimination_width(G, order, vertical) for order in orders)
    return _TW_CACHE[key]


def paper_treewidth_bound(spec: Dict[str, Any]) -> Optional[int]:
    """D-Wave's published upper bound (not used for verdicts)."""
    if spec["topology"] == "pegasus":
        return 12 * spec["m"] - 4
    return 16 * spec["m"] + 8 if spec.get("t") == 4 else None


def thinned_graph(spec: Dict[str, Any], seed: int) -> nx.Graph:
    """The ideal graph with random qubits, then random couplers, removed until
    the published numbers of working qubits and couplers are left -- D-Wave's
    own way of simulating yield in its embedding guide. A stand-in for the
    real working graph, whose missing qubits are not random. Keeps the
    dwave-networkx graph attributes, which busclique needs."""
    rng = random.Random(seed)
    G = ideal_graph(spec).copy()
    drop = rng.sample(sorted(G.nodes), G.number_of_nodes() - spec["qubits"])
    G.remove_nodes_from(drop)
    extra = G.number_of_edges() - spec["couplers"]
    if extra > 0:
        G.remove_edges_from(rng.sample(sorted(G.edges), extra))
    return G


def working_graph_from_file(path: Path, spec: Dict[str, Any]) -> nx.Graph:
    """A QPU's exact working graph exported with a Leap account, as JSON with
    the solver properties' ``qubits`` and ``couplers`` lists (linear labels),
    e.g. from ``DWaveSampler(solver=NAME).properties``."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    nodes = [int(q) for q in data["qubits"]]
    edges = [(int(a), int(b)) for a, b in data["couplers"]]
    # The checks raise ValueError for a qubit or coupler outside the design graph.
    if spec["topology"] == "pegasus":
        return dnx.pegasus_graph(spec["m"], fabric_only=True, node_list=nodes, edge_list=edges,
                                 check_node_list=True, check_edge_list=True)
    return dnx.zephyr_graph(spec["m"], spec["t"], node_list=nodes, edge_list=edges,
                            check_node_list=True, check_edge_list=True)


# ==============================================================================
# Logical graph and its lower bounds
# ==============================================================================

def logical_graph(model: TimeAllocationQUBO) -> nx.Graph:
    G = nx.Graph()
    G.add_edges_from((i, j) for (i, j), v in model.qubo.Q.items() if i != j and v != 0.0)
    return G


def variable_families(model: TimeAllocationQUBO, variables) -> Dict[str, int]:
    """How many of ``variables`` belong to each family of the compiler's
    variable names (the first element of the name; slack bits by their row)."""
    counts: Dict[str, int] = {}
    for i in variables:
        name = model.vars.name(i)
        family = name[0]
        if family == "sigma":
            family = f"slack_{name[1][0]}"
        counts[family] = counts.get(family, 0) + 1
    return dict(sorted(counts.items()))


def coupling_degrees(model: TimeAllocationQUBO) -> Tuple[Dict[int, int], int]:
    """Number of couplings of every coupled variable, and the number of
    couplings -- without building the graph (for QUBOs far too large for it)."""
    degrees: Dict[int, int] = {}
    couplings = 0
    for (i, j), v in model.qubo.Q.items():
        if i != j and v != 0.0:
            degrees[i] = degrees.get(i, 0) + 1
            degrees[j] = degrees.get(j, 0) + 1
            couplings += 1
    return degrees, couplings


def contraction_degeneracy_lower_bound(G: nx.Graph) -> int:
    """MMD+ (min-d) lower bound on treewidth: repeatedly take a vertex of
    minimum degree, record its degree, contract it into its neighbour of
    minimum degree. Every graph reached is a minor of G and the treewidth of a
    graph is at least its minimum degree, so the largest recorded degree is a
    lower bound on tw(G) (Bodlaender, Koster, Wolle)."""
    adj = {v: set(G[v]) for v in G}
    heap = [(len(s), v) for v, s in adj.items()]
    heapq.heapify(heap)
    best = 0
    while len(adj) > 1:
        d, v = heapq.heappop(heap)
        if v not in adj or d != len(adj[v]):
            continue
        best = max(best, d)
        if d == 0:
            del adj[v]
            continue
        u = min(adj[v], key=lambda x: len(adj[x]))
        for w in adj[v]:
            if w == u:
                continue
            adj[w].discard(v)
            adj[w].add(u)
            adj[u].add(w)
            heapq.heappush(heap, (len(adj[w]), w))
        adj[u].discard(v)
        del adj[v]
        heapq.heappush(heap, (len(adj[u]), u))
    return best


def logical_bounds(H: nx.Graph, degree: int) -> Dict[str, int]:
    """Lower bounds on any embedding of H into a graph of maximum degree ``degree``."""
    return bounds_from_degrees([d for _, d in H.degree()], H.number_of_edges(), degree)


def bounds_from_degrees(degrees: List[int], couplings: int, degree: int) -> Dict[str, int]:
    chains = [max(1, math.ceil((d - 2) / (degree - 2))) for d in degrees]
    return {
        "variables": len(degrees),
        "couplings": couplings,
        "qubits_needed_at_least": sum(chains),
        "couplers_needed_at_least": couplings + sum(L - 1 for L in chains),
    }


def grid_separator_bound(cells) -> int:
    """Lower bound on the treewidth of the line graph L(B) of a bipartite graph
    B given by its edges ``cells`` = (row, column) pairs (rows: courses,
    columns: slots); two cells are adjacent when they share a row or a column.

    A graph of treewidth k has a set X of at most k+1 vertices such that no
    component of the graph minus X has more than half of the vertices
    (balanced separators; Cygan et al., Parameterized Algorithms, Lemma 7.19).
    The components of L(B) minus X are the edge sets of the components of B
    minus X; a component using r rows and c columns has at most r*c edges, and
    different components use disjoint rows and columns. So |X| is at least
    |E(B)| minus the largest sum of min(r_k * c_k, |E(B)|/2) over families of
    disjoint (r_k rows, c_k columns) blocks -- computed by a dynamic programme
    over the numbers of rows and columns used -- and the treewidth is at least
    |X| - 1."""
    cells = set(cells)
    edges = len(cells)
    if edges < 2:
        return 0
    m = len({r for r, _ in cells})
    n = len({c for _, c in cells})
    cap = edges // 2
    best = [[0] * (n + 1) for _ in range(m + 1)]
    for a in range(1, m + 1):
        for b in range(1, n + 1):
            value = max(best[a - 1][b], best[a][b - 1])
            for r in range(1, a + 1):
                row = best[a - r]
                for c in range(1, b + 1):
                    v = min(r * c, cap) + row[b - c]
                    if v > value:
                        value = v
            best[a][b] = value
    return max(0, edges - best[m][n] - 1)


def placement_grid(model: TimeAllocationQUBO, H: nx.Graph) -> List[Tuple[int, int]]:
    """The (course, slot) cells whose placements form a line graph of courses
    and slots inside the logical graph: one coupled placement per cell, kept
    only for courses whose placements are coupled pairwise and for slots
    whose placements are coupled pairwise (checked on H)."""
    from itertools import combinations
    cell: Dict[Tuple[int, int], int] = {}
    for (c, _p, t), i in sorted(model.x_index.items()):
        if i in H and (c, t) not in cell:
            cell[(c, t)] = i
    by_course: Dict[int, List[int]] = {}
    by_slot: Dict[int, List[int]] = {}
    for (c, t), i in cell.items():
        by_course.setdefault(c, []).append(i)
        by_slot.setdefault(t, []).append(i)

    def clique(nodes: List[int]) -> bool:
        return all(H.has_edge(a, b) for a, b in combinations(nodes, 2))

    courses = {c for c, nodes in by_course.items() if clique(nodes)}
    slots = {t for t, nodes in by_slot.items() if clique(nodes)}
    return [(c, t) for (c, t) in cell if c in courses and t in slots]


def graph_profile(H: nx.Graph) -> Dict[str, Any]:
    degrees = [d for _, d in H.degree()]
    core = max(nx.core_number(H).values()) if H.number_of_edges() else 0
    return {
        "max_degree": max(degrees) if degrees else 0,
        "mean_degree": round(sum(degrees) / len(degrees), 2) if degrees else 0.0,
        "degeneracy": core,
        "treewidth_at_least": max(core, contraction_degeneracy_lower_bound(H)),
    }


# ==============================================================================
# Embedding
# ==============================================================================

def verify_embedding(emb: Dict[Any, List[Any]], H: nx.Graph, T: nx.Graph) -> Optional[str]:
    """None when ``emb`` is a valid minor embedding of H in T, else the reason."""
    used = set()
    for v in H.nodes:
        chain = emb.get(v)
        if not chain:
            return f"no chain for {v}"
        chain = set(chain)
        if not chain <= set(T.nodes):
            return f"chain of {v} uses a qubit outside the graph"
        if used & chain:
            return f"chain of {v} overlaps another chain"
        used |= chain
        if not nx.is_connected(T.subgraph(chain)):
            return f"chain of {v} is not connected"
    for u, v in H.edges:
        if not any(T.has_edge(a, b) for a in emb[u] for b in emb[v]):
            return f"coupling {u}-{v} has no coupler between the chains"
    return None


def _embedding_summary(emb: Dict[Any, List[Any]], method: str, t0: float) -> Dict[str, Any]:
    lengths = [len(c) for c in emb.values()]
    return {"found": True, "method": method, "seconds": round(time.time() - t0, 1),
            "qubits_used": sum(lengths), "max_chain": max(lengths, default=0),
            "mean_chain": round(sum(lengths) / len(lengths), 2) if lengths else 0.0}


def try_embedding(H: nx.Graph, T: nx.Graph, timeout: float, tries: int, seed: int) -> Dict[str, Any]:
    """minorminer's heuristic search, its result checked."""
    t0 = time.time()
    emb = minorminer.find_embedding(list(H.edges), list(T.edges), timeout=timeout,
                                    tries=tries, random_seed=seed)
    if not emb or len(emb) < H.number_of_nodes():
        return {"found": False, "method": "minorminer", "seconds": round(time.time() - t0, 1)}
    problem = verify_embedding(emb, H, T)
    if problem:
        return {"found": False, "method": "minorminer", "seconds": round(time.time() - t0, 1),
                "invalid": problem}
    return _embedding_summary(emb, "minorminer", t0)


def clique_embedding(H: nx.Graph, T: nx.Graph, seeds=CLIQUE_SEEDS) -> Optional[Dict[str, Any]]:
    """Embed H through a clique embedding of K_n (n = vertices of H) built by
    busclique, checked; None when busclique finds no K_n with any seed."""
    t0 = time.time()
    nodes = sorted(H.nodes)
    if not nodes:
        return {"found": True, "method": "nothing to embed", "seconds": 0.0, "qubits_used": 0,
                "max_chain": 0, "mean_chain": 0.0}
    for seed in seeds:
        clique = busclique.find_clique_embedding(len(nodes), T, use_cache=False, seed=seed)
        if not clique:
            continue
        emb = {v: list(clique[i]) for i, v in enumerate(nodes)}
        if verify_embedding(emb, H, T) is None:
            return _embedding_summary(emb, "clique", t0)
    return None


def largest_clique_embedding(T: nx.Graph, top: int, seed: int = 0) -> Tuple[int, int]:
    """(k, longest chain) for the largest k <= top for which busclique, with
    this seed, built a clique embedding of K_k in T (checked): a bisection,
    then a downward check. busclique's search is randomised and need not be
    monotone in k, so k is a constructive lower bound on the largest clique
    minor, not necessarily the maximum."""
    def found(k: int) -> bool:
        return bool(busclique.find_clique_embedding(k, T, use_cache=False, seed=seed))
    lo, hi = 0, top
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if found(mid):
            lo = mid
        else:
            hi = mid - 1
    for k in range(min(top, lo + 3), 0, -1):
        emb = busclique.find_clique_embedding(k, T, use_cache=False, seed=seed)
        if emb and verify_embedding(emb, nx.complete_graph(k), T) is None:
            return k, max(len(c) for c in emb.values())
    return 0, 0


_CLIQUE_CACHE: Dict[Tuple, int] = {}


def ideal_clique_size(spec: Dict[str, Any]) -> int:
    """Largest clique busclique embeds in the ideal graph; the treewidth bound
    plus one caps the search (K_k needs treewidth k-1)."""
    key = (spec["topology"], spec["m"], spec.get("t"))
    if key not in _CLIQUE_CACHE:
        _CLIQUE_CACHE[key] = largest_clique_embedding(ideal_graph(spec), host_treewidth_upper_bound(spec) + 1)[0]
    return _CLIQUE_CACHE[key]


# ==============================================================================
# Instances
# ==============================================================================

def _clock(text: str) -> int:
    h, m = text.split(":")
    return int(h) * 60 + int(m)


def periods_per_day(day_start: str, day_end: str, slot_minutes: int, break_minutes: int) -> List[str]:
    """The slot grid of one day: slots of ``slot_minutes`` from ``day_start``,
    ``break_minutes`` apart, as long as a slot ends by ``day_end``. Slot
    boundaries must lie on the 15-minute grid the room rows use."""
    start, end = _clock(day_start), _clock(day_end)
    if start % 15 or slot_minutes % 15 or break_minutes % 15:
        raise ValueError("day start, slot length and break must be multiples of 15 minutes "
                         "(the room rows are written on a 15-minute grid)")
    out = []
    t = start
    while t + slot_minutes <= end:
        out.append(f"{t // 60}:{t % 60:02d}-{(t + slot_minutes) // 60}:{(t + slot_minutes) % 60:02d}")
        t += slot_minutes + break_minutes
    if not out:
        raise ValueError("no slot fits into the day")
    return out


def generator_config(base: Dict[str, Any], p: Dict[str, Any], seed: int) -> Dict[str, Any]:
    cfg = copy.deepcopy(base)
    cfg["seed"] = int(seed)
    cfg["benchmark_suite_size"] = 1
    cfg["skip_seed_offsets"] = []
    cfg["metadata"]["name"] = "dwave-capacity"
    dims = cfg["dimensions"]
    dims.update({
        "days": p["days"],
        "periods_per_day": periods_per_day(p["day_start"], p["day_end"], p["slot_minutes"], p["break_minutes"]),
        "student_groups": p["groups"], "teachers": p["teachers"], "rooms": p["rooms"],
        "courses": p["courses"], "courses_from_utilization": False,
    })
    if p.get("availability") is not None:
        cfg["resources"]["teacher_availability"]["availability_ratio"] = p["availability"]
    if p.get("max_courses_per_teacher") is not None:
        cfg["topology"]["teacher_assignment"]["max_courses_per_teacher"] = p["max_courses_per_teacher"]
    return cfg


def generate_instance(cfg: Dict[str, Any], path: Path) -> Path:
    from etpmachine.generators.artificial_entity_generator import InstanceGenerator
    from etpmachine.generators.generator_config_operator import BenchmarkConfig
    pi = quiet(lambda: InstanceGenerator(BenchmarkConfig.from_dict(cfg)).generate())
    quiet(pi.to_yaml, str(path))
    return path


def compile_qubo(path: Path, encoding: str, overrides: Optional[Dict[str, Any]] = None) -> TimeAllocationQUBO:
    def build():
        pi = ProblemInstance.from_yaml(str(path))
        pi.rebuild_derived()
        model = TimeAllocationQUBO(pi, config={**ENCODINGS[encoding], **(overrides or {})})
        model.build(verbose=False)
        return model
    return quiet(build)


# ==============================================================================
# One instance against every QPU
# ==============================================================================

def analyse(path: Path, label: str, encoding: str, args, targets: List[str],
            host_tw: Dict[str, int], clique_limit: Dict[str, int]) -> List[Dict[str, Any]]:
    model = compile_qubo(path, encoding, args.qubo_config)
    degrees, couplings = coupling_degrees(model)
    if len(degrees) > max(HARDWARE[name]["qubits"] for name in targets):
        # More coupled variables than any QPU has qubits: proved without the graph.
        H = None
        values = list(degrees.values())
        profile = {"max_degree": max(values), "mean_degree": round(sum(values) / len(values), 2),
                   "degeneracy": "", "treewidth_at_least": ""}
    else:
        H = logical_graph(model)
        profile = graph_profile(H)
        grid = grid_separator_bound(placement_grid(model, H))
        profile["treewidth_grid_bound"] = grid
        profile["treewidth_at_least"] = max(profile["treewidth_at_least"], grid)
    stats = run_record.qubo_matrix_stats_from_qubo(model.qubo)
    largest_course = max((len(v) for v in model.data.PT_c.values()), default=0)
    common = {
        "instance": label, "encoding": encoding,
        "courses": len(model.data.PT_c), "candidate_placements": len(model.x_index),
        "largest_course_candidates": largest_course,
        "qubo_variables": model.qubo.n_vars, "coupled_variables": len(degrees),
        "couplings": couplings, **profile,
        "ising_dynamic_range": stats.get("dynamic_range"),
        "coupled_by_family": json.dumps(variable_families(model, degrees)),
        "embed_timeout": args.embed_timeout, "tools": tools_used(),
    }
    rows = []
    ideal_results: Dict[Tuple, Dict[str, Any]] = {}     # QPUs of one design share the ideal graph
    for name in targets:
        spec = HARDWARE[name]
        degree = 15 if spec["topology"] == "pegasus" else 4 * spec["t"] + 4
        bounds = bounds_from_degrees(list(degrees.values()), couplings, degree)
        reasons = []
        if bounds["variables"] > spec["qubits"]:
            reasons.append(f"variables {bounds['variables']} > qubits {spec['qubits']}")
        if bounds["qubits_needed_at_least"] > spec["qubits"]:
            reasons.append(f"chains need >= {bounds['qubits_needed_at_least']} qubits > {spec['qubits']}")
        if bounds["couplers_needed_at_least"] > spec["couplers"]:
            reasons.append(f"needs >= {bounds['couplers_needed_at_least']} couplers > {spec['couplers']}")
        if profile["treewidth_at_least"] != "" and profile["treewidth_at_least"] > host_tw[name]:
            reasons.append(f"treewidth >= {profile['treewidth_at_least']} > {host_tw[name]} (host bound)")
        row = {**common, "qpu": name, "qpu_qubits": spec["qubits"], "qpu_couplers": spec["couplers"],
               "host_treewidth_at_most": host_tw[name], "largest_clique_on_ideal_graph": clique_limit[name],
               "qubits_needed_at_least": bounds["qubits_needed_at_least"],
               "couplers_needed_at_least": bounds["couplers_needed_at_least"]}
        if reasons:
            row.update({"verdict": "proved: does not fit", "reason": "; ".join(reasons)})
        else:
            row.update(_embed_everywhere(H, spec, name, args, clique_limit[name], ideal_results))
        rows.append(row)
    return rows


def _embed_on(H: nx.Graph, T: nx.Graph, clique_ok: bool, minorminer_ok: bool, args) -> Dict[str, Any]:
    """The clique embedding first (quick, any graph structure), then minorminer."""
    if clique_ok:
        found = clique_embedding(H, T)
        if found:
            return found
    if minorminer_ok:
        return try_embedding(H, T, args.embed_timeout, args.embed_tries, args.embed_seed)
    return {"found": False, "method": "clique" if clique_ok else "none"}


def _embed_everywhere(H: nx.Graph, spec: Dict[str, Any], name: str, args, clique_limit: int,
                      ideal_results: Dict[Tuple, Dict[str, Any]]) -> Dict[str, Any]:
    clique_ok = H.number_of_nodes() <= clique_limit
    minorminer_ok = args.embed_timeout is not None and name in args.embed_on
    not_found = ("no embedding found" + (f" (minorminer {args.embed_timeout:g} s)" if minorminer_ok
                                         else " (minorminer not tried)"))
    out: Dict[str, Any] = {}
    if args.working_graph and name in args.working_graph:
        exact = _embed_on(H, working_graph_from_file(args.working_graph[name], spec), clique_ok, minorminer_ok, args)
        out["exact_working_graph"] = json.dumps(exact)
        out["verdict"] = "embedded on the exact working graph" if exact["found"] else "undecided"
        out["reason"] = exact["method"] if exact["found"] else not_found + " on the exact working graph"
        return out
    design = (spec["topology"], spec["m"], spec.get("t"), minorminer_ok)
    if design not in ideal_results:
        ideal_results[design] = _embed_on(H, ideal_graph(spec), clique_ok, minorminer_ok, args)
    ideal = ideal_results[design]
    out["ideal_graph"] = json.dumps(ideal)
    if not ideal["found"]:
        out.update({"verdict": "undecided", "reason": not_found + " on the ideal graph"})
        return out
    trials = [_embed_on(H, thinned_graph(spec, seed=k), clique_ok, minorminer_ok, args)
              for k in range(args.thinned)]
    found = sum(t["found"] for t in trials)
    out["thinned_graphs"] = json.dumps(trials)
    methods = sorted({ideal["method"]} | {t["method"] for t in trials if t["found"]})
    if args.thinned == 0:
        out.update({"verdict": "embedded on the ideal graph",
                    "reason": f"{'/'.join(methods)}; thinned graphs not tried"})
    elif found == args.thinned:
        out.update({"verdict": "embedded (ideal and all thinned graphs)",
                    "reason": f"{'/'.join(methods)}; {found}/{args.thinned} thinned graphs"})
    else:
        out.update({"verdict": "embedded on the ideal graph only",
                    "reason": f"{'/'.join(methods)}; {found}/{args.thinned} thinned graphs"})
    return out


def _job(job: Tuple) -> List[Dict[str, Any]]:
    """One instance under one encoding against every QPU (runs in a worker)."""
    path, label, encoding, params, args, targets, host_tw, clique_limit = job
    try:
        rows = analyse(Path(path), label, encoding, args, targets, host_tw, clique_limit)
    except Exception as exc:
        rows = [{"instance": label, "encoding": encoding, "verdict": "compile failed",
                 "reason": repr(exc)[:300]}]
    for r in rows:
        r.update(params or {})
    return rows


# ==============================================================================
# Command line
# ==============================================================================

def _parse_scan(text: str) -> Tuple[str, List[int]]:
    dim, rng = text.split("=")
    dim = dim.replace("-", "_")
    if dim not in SCAN_DIMENSIONS:
        raise argparse.ArgumentTypeError(f"--scan dimension must be one of {SCAN_DIMENSIONS}")
    a, b, s = (int(x) for x in rng.split(":"))
    return dim, list(range(a, b + 1, s))


def _parse_settings(items: List[str]) -> Dict[str, Any]:
    out = {}
    for item in items or []:
        key, value = item.split("=", 1)
        out[key.strip()] = yaml.safe_load(value)
    return out


def _parse_working(items: List[str]) -> Dict[str, Path]:
    out = {}
    for item in items or []:
        name, path = item.split("=", 1)
        if name not in HARDWARE:
            raise SystemExit(f"--working-graph: unknown QPU {name!r}")
        out[name] = Path(path)
    return out


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_argument_group("instances")
    src.add_argument("--instance", type=Path, action="append", default=[],
                     help="an existing instance YAML (repeatable)")
    src.add_argument("--base-preset", type=Path, default=REPO / "generated_presets" / "easy_000.yaml",
                     help="generator preset for every knob not given below")
    src.add_argument("--days", type=int, help="days of the week (1-7)")
    src.add_argument("--day-start", default="8:00", help="start of the first slot (default 8:00)")
    src.add_argument("--day-end", default="20:00", help="latest end of a slot (default 20:00)")
    src.add_argument("--slot-minutes", type=int, default=90, help="slot length (default 90)")
    src.add_argument("--break-minutes", type=int, default=15, help="break between slots (default 15)")
    src.add_argument("--groups", type=int, help="student groups")
    src.add_argument("--teachers", type=int, help="lecturers")
    src.add_argument("--rooms", type=int, help="rooms")
    src.add_argument("--courses", type=int, help="courses (one weekly lesson each; at least --groups)")
    src.add_argument("--availability", type=float, default=None,
                     help="share of a day's slots a lecturer is available (default: the preset's)")
    src.add_argument("--max-courses-per-teacher", type=int, default=None)
    src.add_argument("--seeds", type=int, nargs="+", default=[1])
    src.add_argument("--scan", type=_parse_scan, default=None,
                     help="vary one parameter: DIM=START:STOP:STEP, DIM in " + ", ".join(SCAN_DIMENSIONS))
    enc = p.add_argument_group("encoding and QPUs")
    enc.add_argument("--encoding", choices=sorted(ENCODINGS), action="append", default=None,
                     help="repeatable; default: all three")
    enc.add_argument("--qubo-config", action="append", default=[], metavar="KEY=VALUE",
                     help="override a compiler setting in every encoding (repeatable)")
    enc.add_argument("--qpu", choices=sorted(HARDWARE), action="append", default=None,
                     help="QPUs to check (repeatable; default: all)")
    enc.add_argument("--embed-on", choices=sorted(HARDWARE), action="append", default=None,
                     help="QPUs to run minorminer on (default: " + ", ".join(DEFAULT_EMBED_TARGETS) + ")")
    enc.add_argument("--embed-timeout", type=float, default=None,
                     help="seconds per minorminer attempt; without it only the bounds and the clique "
                          "embeddings are used")
    enc.add_argument("--embed-tries", type=int, default=10)
    enc.add_argument("--embed-seed", type=int, default=1)
    enc.add_argument("--thinned", type=int, default=3,
                     help="randomly thinned working-graph stand-ins tried after an ideal-graph success")
    enc.add_argument("--working-graph", action="append", default=[], metavar="QPU=PATH",
                     help="exact working graph of a QPU as JSON (qubits, couplers), from a Leap account")
    out = p.add_argument_group("output")
    out.add_argument("--jobs", type=int, default=1, help="instances analysed in parallel (processes)")
    out.add_argument("--csv", type=Path, default=None, help="one row per instance, encoding and QPU, "
                                                             "written as the results come in")
    out.add_argument("--facts", action="store_true",
                     help="print the hardware table, the treewidth bounds and the clique embeddings")
    return p


def print_facts(thinned: int) -> None:
    print(f"QPUs (working graphs as published on {FACTS_READ_ON}, {FACTS_SOURCE}); {tools_used()}:")
    for name, spec in HARDWARE.items():
        G = ideal_graph(spec)
        shape = f"P{spec['m']}" if spec["topology"] == "pegasus" else f"Z{spec['m']}"
        k, chain = largest_clique_embedding(G, host_treewidth_upper_bound(spec) + 1)
        cliques = [largest_clique_embedding(thinned_graph(spec, s), k) for s in range(thinned)]
        print(f"  {name:20s} {spec['topology']:8s} {shape:4s} working {spec['qubits']:5d} qubits "
              f"{spec['couplers']:6d} couplers | ideal {G.number_of_nodes():5d} / {G.number_of_edges():6d}, "
              f"degree {max(d for _, d in G.degree())} | treewidth <= {host_treewidth_upper_bound(spec)} "
              f"(verified here; D-Wave's papers: <= {paper_treewidth_bound(spec)})", flush=True)
        print(f"  {'':20s} clique embedding K_{k} on the ideal graph (chains <= {chain}); on {thinned} thinned "
              f"stand-ins: " + ", ".join(f"K_{c} (chains <= {L})" for c, L in cliques), flush=True)


SHORT = {"proved: does not fit": "NO (proved)", "embedded (ideal and all thinned graphs)": "YES",
         "embedded on the exact working graph": "YES (exact)", "embedded on the ideal graph": "ideal only",
         "embedded on the ideal graph only": "ideal only", "undecided": "?"}


def print_summary(rows: List[Dict[str, Any]]) -> None:
    """One line per instance and encoding, one column per QPU: YES = embedded
    on the ideal graph and on every thinned stand-in; ideal only; ? = not
    decided; NO (proved) = a necessary condition fails."""
    qpus = []
    for r in rows:
        if r.get("qpu") and r["qpu"] not in qpus:
            qpus.append(r["qpu"])
    if not qpus:
        return
    table: Dict[Tuple[str, str], Dict[str, str]] = {}
    sizes: Dict[Tuple[str, str], str] = {}
    for r in rows:
        if not r.get("qpu"):
            continue
        key = (r["instance"], r["encoding"])
        table.setdefault(key, {})[r["qpu"]] = SHORT.get(r["verdict"], r["verdict"])
        sizes[key] = f"{r['candidate_placements']}/{r['coupled_variables']}/{r['couplings']}"
    print("\nSummary (placements / coupled variables / couplings):")
    width = max(len(f"{i} [{e}]") for i, e in table) + 2
    print(" " * width + "".join(f"{q:>20s}" for q in qpus))
    for (inst, enc), verdicts in table.items():
        print(f"{inst} [{enc}]".ljust(width) + "".join(f"{verdicts.get(q, ''):>20s}" for q in qpus)
              + f"   {sizes[(inst, enc)]}")


def _print_job(rows: List[Dict[str, Any]]) -> None:
    first = rows[0]
    if not first.get("qpu"):
        print(f"{first['instance']} [{first.get('encoding', '')}]: {first['verdict']}: {first['reason']}", flush=True)
        return
    print(f"{first['instance']} [{first['encoding']}]: {first['candidate_placements']} placements, "
          f"{first['coupled_variables']} coupled variables, {first['couplings']} couplings, "
          f"largest course {first['largest_course_candidates']} candidates, "
          f"treewidth >= {first['treewidth_at_least']}", flush=True)
    for r in rows:
        print(f"    {r['qpu']:20s} {r['verdict']}" + (f" -- {r['reason']}" if r.get("reason") else ""), flush=True)


def main() -> int:
    args = make_parser().parse_args()
    if args.facts:
        print_facts(args.thinned)
        return 0
    args.working_graph = _parse_working(args.working_graph)
    args.qubo_config = _parse_settings(args.qubo_config)
    encodings = args.encoding or ["default", "presolved", "feasibility"]
    targets = args.qpu or list(HARDWARE)
    args.embed_on = args.embed_on or [t for t in DEFAULT_EMBED_TARGETS if t in targets]

    host_tw = {name: host_treewidth_upper_bound(HARDWARE[name]) for name in targets}
    clique_limit = {name: ideal_clique_size(HARDWARE[name]) for name in targets}

    generated = all(getattr(args, k) is not None for k in ("days", "groups", "teachers", "rooms", "courses"))
    if not generated and any(getattr(args, k) is not None for k in ("days", "groups", "teachers", "rooms", "courses")):
        raise SystemExit("a generated instance needs --days, --groups, --teachers, --rooms and --courses")
    if not args.instance and not generated:
        raise SystemExit("nothing to do: give --instance or the generator parameters (or --facts)")

    rows: List[Dict[str, Any]] = []
    writer = None
    fh = None
    if args.csv:
        fh = open(args.csv, "w", newline="", encoding="utf-8")
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore", restval="")
        writer.writeheader()
        fh.flush()

    def record(job_rows: List[Dict[str, Any]]) -> None:
        _print_job(job_rows)
        rows.extend(job_rows)
        if writer:
            writer.writerows(job_rows)
            fh.flush()

    with tempfile.TemporaryDirectory(prefix="dwave_capacity_") as tmp:
        jobs: List[Tuple] = []
        for path in args.instance:
            for encoding in encodings:
                jobs.append((str(path), path.stem, encoding, None, args, targets, host_tw, clique_limit))
        if generated:
            base = yaml.safe_load(args.base_preset.read_text(encoding="utf-8"))
            params = {k: getattr(args, k) for k in ("days", "day_start", "day_end", "slot_minutes", "break_minutes",
                                                    "groups", "teachers", "rooms", "courses",
                                                    "availability", "max_courses_per_teacher")}
            dim, values = args.scan if args.scan else (None, [None])
            for index, value in enumerate(values):
                p = dict(params)
                if dim:
                    p[dim] = value
                for seed in args.seeds:
                    slots = len(periods_per_day(p["day_start"], p["day_end"], p["slot_minutes"], p["break_minutes"]))
                    label = (f"days={p['days']} slots/day={slots} ({p['slot_minutes']} min) groups={p['groups']} "
                             f"lecturers={p['teachers']} rooms={p['rooms']} courses={p['courses']} seed={seed}")
                    columns = {"days": p["days"], "slots_per_day": slots, "slot_minutes": p["slot_minutes"],
                               "break_minutes": p["break_minutes"], "groups": p["groups"],
                               "lecturers": p["teachers"], "rooms": p["rooms"], "courses_requested": p["courses"],
                               "availability": p["availability"], "seed": seed}
                    path = Path(tmp) / f"instance_{index:03d}_seed_{seed}.yaml"
                    try:
                        generate_instance(generator_config(base, p, seed), path)
                    except Exception as exc:
                        record([{"instance": label, "verdict": "generator refused", "reason": repr(exc)[:300],
                                 **columns}])
                        continue
                    for encoding in encodings:
                        jobs.append((str(path), label, encoding, columns, args, targets, host_tw, clique_limit))

        if args.jobs <= 1:
            for job in jobs:
                record(_job(job))
        else:
            with cf.ProcessPoolExecutor(max_workers=args.jobs) as pool:
                for future in cf.as_completed([pool.submit(_job, job) for job in jobs]):
                    record(future.result())
    if fh:
        fh.close()
    order = {(j[1], j[2]): i for i, j in enumerate(jobs)} if jobs else {}
    rows.sort(key=lambda r: order.get((r.get("instance"), r.get("encoding")), -1))
    print_summary(rows)
    if args.csv:
        print(f"written {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
