"""
The proof machinery of scripts/dwave_capacity.py: what a "proved: does not fit"
verdict rests on, checked on graphs whose answers are known.

* elimination_order_width (upper bound on treewidth) gives the known width on
  cliques, paths, cycles and grids;
* the contraction-degeneracy lower bound never exceeds a known treewidth and
  reaches it on cliques, trees and cycles;
* the placement-grid bound never exceeds the exact treewidth (computed by the
  subset recurrence) of small line graphs of bipartite graphs, nor an upper
  bound on larger ones;
* the chain lemma behind the qubit and coupler bounds: a connected set of L
  qubits in a graph of maximum degree D has at most L(D-2)+2 couplers leaving
  it -- checked on random connected sets of Pegasus and Zephyr graphs;
* the per-variable chain bound and the coupler bound on a star;
* the embedding check rejects overlapping and disconnected chains and missing
  couplings, and accepts a real minorminer embedding;
* a clique embedding of K_n embeds any graph on n vertices; busclique's
  largest clique on the ideal Zephyr Z2 is at least D-Wave's K_{16m-8};
* a thinned stand-in graph has exactly the published numbers of working
  qubits and couplers and keeps the attributes busclique needs;
* an exported working graph is read back exactly, and a coupler outside the
  design graph is refused;
* the slot grid of a day.

Needs minorminer and dwave-networkx (skipped without them).

Run:  python -m pytest tests/unit/test_dwave_capacity.py -q
"""
from __future__ import annotations

import itertools
import random
import sys
from pathlib import Path

import networkx as nx
import pytest

pytest.importorskip("minorminer")
pytest.importorskip("dwave_networkx")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import dwave_capacity as cap  # noqa: E402
import dwave_networkx as dnx  # noqa: E402


def test_elimination_width_on_known_graphs():
    K = nx.complete_graph(7)
    assert cap.elimination_order_width(K, list(K)) == 6
    P = nx.path_graph(12)
    assert cap.elimination_order_width(P, list(range(12))) == 1
    C = nx.cycle_graph(9)
    assert cap.elimination_order_width(C, list(range(9))) == 2
    for k in (3, 4, 6):
        G = nx.grid_2d_graph(k, k)
        order = sorted(G)                       # row by row
        assert cap.elimination_order_width(G, order) == k


def test_contraction_degeneracy_is_a_lower_bound():
    assert cap.contraction_degeneracy_lower_bound(nx.complete_graph(9)) == 8
    assert cap.contraction_degeneracy_lower_bound(nx.balanced_tree(2, 4)) == 1
    assert cap.contraction_degeneracy_lower_bound(nx.cycle_graph(10)) == 2
    for k in (4, 6, 8):                         # treewidth of the k x k grid is k
        lb = cap.contraction_degeneracy_lower_bound(nx.grid_2d_graph(k, k))
        assert 2 <= lb <= k
    rng = random.Random(3)
    for _ in range(20):
        G = nx.gnp_random_graph(40, rng.uniform(0.05, 0.4), seed=rng.randrange(10**6))
        upper, _ = nx.algorithms.approximation.treewidth_min_degree(G)
        assert cap.contraction_degeneracy_lower_bound(G) <= upper


def _exact_treewidth(G):
    """Exact treewidth by the subset recurrence TW(S) = min over v in S of
    max(TW(S - v), |Q(S - v, v)|), Q(S, v) = vertices outside S + v reachable
    from v through S (Bodlaender, Fomin, Koster, Kratsch, Thilikos). Small graphs only."""
    nodes = list(G)
    n = len(nodes)
    pos = {v: i for i, v in enumerate(nodes)}
    adj = [0] * n
    for u, v in G.edges:
        adj[pos[u]] |= 1 << pos[v]
        adj[pos[v]] |= 1 << pos[u]

    def neighbours(mask):
        out = 0
        while mask:
            low = mask & -mask
            out |= adj[low.bit_length() - 1]
            mask ^= low
        return out

    def q(S, v):
        inside = S | (1 << v)
        seen = frontier = 1 << v
        while frontier:
            frontier = neighbours(frontier) & inside & ~seen
            seen |= frontier
        return bin(neighbours(seen) & ~inside).count("1")

    tw = {0: -1}
    for size in range(1, n + 1):
        for combo in itertools.combinations(range(n), size):
            S = sum(1 << i for i in combo)
            tw[S] = min(max(tw[S & ~(1 << v)], q(S & ~(1 << v), v)) for v in combo)
    return tw[(1 << n) - 1]


def _line_graph(cells):
    B = nx.Graph()
    B.add_edges_from((("course", r), ("slot", c)) for r, c in cells)
    return nx.line_graph(B)


def test_the_placement_grid_bound_is_a_lower_bound():
    assert _exact_treewidth(nx.complete_graph(6)) == 5
    assert _exact_treewidth(nx.cycle_graph(8)) == 2
    for m, n in ((3, 3), (3, 4), (2, 5), (2, 6), (4, 3)):
        cells = [(r, c) for r in range(m) for c in range(n)]
        assert cap.grid_separator_bound(cells) <= _exact_treewidth(_line_graph(cells))
    assert _exact_treewidth(_line_graph([(r, c) for r in range(3) for c in range(3)])) == 5
    rng = random.Random(11)
    for _ in range(25):
        all_cells = [(r, c) for r in range(4) for c in range(5)]
        cells = rng.sample(all_cells, rng.randint(3, 12))
        assert cap.grid_separator_bound(cells) <= _exact_treewidth(_line_graph(cells))
    for m, n in ((5, 12), (8, 10), (6, 20)):
        cells = [(r, c) for r in range(m) for c in range(n)]
        upper, _ = nx.algorithms.approximation.treewidth_min_fill_in(_line_graph(cells))
        bound = cap.grid_separator_bound(cells)
        assert bound <= upper
        assert bound >= 0.4 * m * n - 1                  # the bound is about (sqrt 2 - 1) m n
    # a week of 35 slots: from 15 courses on, above every QPU's treewidth bound
    assert cap.grid_separator_bound([(r, c) for r in range(15) for c in range(35)]) > 212


def _random_connected_set(G, size, rng):
    start = rng.choice(list(G))
    chosen = {start}
    frontier = set(G[start])
    while len(chosen) < size and frontier:
        v = rng.choice(sorted(frontier))
        chosen.add(v)
        frontier |= set(G[v])
        frontier -= chosen
    return chosen


@pytest.mark.parametrize("graph, degree", [
    (dnx.pegasus_graph(6, fabric_only=True), 15),
    (dnx.zephyr_graph(4, 4), 20),
])
def test_a_chain_has_at_most_L_times_degree_minus_2_plus_2_couplers_leaving_it(graph, degree):
    assert max(d for _, d in graph.degree()) == degree
    rng = random.Random(7)
    for _ in range(300):
        L = rng.randint(1, 30)
        chain = _random_connected_set(graph, L, rng)
        leaving = sum(1 for v in chain for w in graph[v] if w not in chain)
        assert leaving <= len(chain) * (degree - 2) + 2


def test_bounds_on_a_star():
    star = nx.star_graph(30)                    # centre 0 with 30 leaves
    b = cap.logical_bounds(star, degree=15)
    assert b["qubits_needed_at_least"] == 3 + 30       # ceil((30 - 2) / 13) = 3 for the centre
    assert b["couplers_needed_at_least"] == 30 + 2


def test_the_embedding_check():
    H = nx.complete_graph(3)
    T = nx.cycle_graph(4)                       # 0-1-2-3-0
    good = {0: [0], 1: [1], 2: [2, 3]}
    assert cap.verify_embedding(good, H, T) is None
    assert "overlaps" in cap.verify_embedding({0: [0], 1: [0], 2: [2, 3]}, H, T)
    assert "not connected" in cap.verify_embedding({0: [0, 2], 1: [1], 2: [3]}, H, T)
    assert "no coupler" in cap.verify_embedding({0: [0], 1: [1], 2: [2]}, H, T)
    K = nx.complete_graph(10)
    result = cap.try_embedding(K, dnx.zephyr_graph(2, 4), timeout=30, tries=5, seed=1)
    assert result["found"] and result["max_chain"] >= 1


def test_a_clique_embedding_embeds_any_graph_on_as_many_vertices():
    T = dnx.zephyr_graph(2, 4)
    rng = random.Random(5)
    for _ in range(5):
        H = nx.gnp_random_graph(20, rng.uniform(0.1, 0.9), seed=rng.randrange(10**6))
        H.remove_nodes_from([v for v in list(H) if H.degree(v) == 0])
        result = cap.clique_embedding(H, T)
        assert result and result["found"] and result["method"] == "clique"
    k, chain = cap.largest_clique_embedding(T, top=60)
    assert k >= 16 * 2 - 8 and chain >= 1                # D-Wave's native clique K_{16m-8}


def test_a_thinned_graph_has_the_published_counts():
    spec = cap.HARDWARE["Advantage2_system4"]
    G = cap.thinned_graph(spec, seed=0)
    assert G.number_of_nodes() == spec["qubits"] and G.number_of_edges() == spec["couplers"]
    assert set(G.nodes) <= set(cap.ideal_graph(spec).nodes)
    assert G.graph["family"] == "zephyr"                 # busclique reads the topology from here


def test_a_working_graph_file_is_read_back_exactly(tmp_path):
    import json
    spec = {"topology": "zephyr", "m": 2, "t": 4}
    full = dnx.zephyr_graph(2, 4)
    qubits = sorted(full)[7:]
    couplers = [list(e) for e in full.edges if e[0] in qubits and e[1] in qubits][5:]
    path = tmp_path / "working.json"
    path.write_text(json.dumps({"qubits": qubits, "couplers": couplers}), encoding="utf-8")
    G = cap.working_graph_from_file(path, spec)
    assert set(G.nodes) == set(qubits)
    assert {frozenset(e) for e in G.edges} == {frozenset(e) for e in couplers}
    stranger = next([a, b] for a in qubits for b in qubits if a < b and not full.has_edge(a, b))
    path.write_text(json.dumps({"qubits": qubits, "couplers": couplers + [stranger]}), encoding="utf-8")
    with pytest.raises(ValueError):
        cap.working_graph_from_file(path, spec)


def test_the_slot_grid_of_a_day():
    slots = cap.periods_per_day("8:00", "20:00", 90, 15)
    assert slots[0] == "8:00-9:30" and slots[-1] == "18:30-20:00" and len(slots) == 7
    assert len(cap.periods_per_day("8:00", "20:00", 45, 0)) == 16
    with pytest.raises(ValueError):
        cap.periods_per_day("8:10", "20:00", 90, 15)


def test_the_host_bound_lies_between_the_known_clique_and_the_computed_width():
    spec = {"topology": "zephyr", "m": 2, "t": 4}
    bound = cap.host_treewidth_upper_bound(spec)
    # Z_2 contains K_{16m-8} = K_24 (D-Wave's construction), so its treewidth is at least 23.
    emb = cap.try_embedding(nx.complete_graph(24), dnx.zephyr_graph(2, 4), timeout=60, tries=10, seed=1)
    if emb["found"]:
        assert bound >= 23
    assert bound >= 16 * 2                        # D-Wave's lower bound 16m
