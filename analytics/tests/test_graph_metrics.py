import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from graph_metrics import build_graph, component_summary, node_metrics  # noqa: E402


def test_pagerank_and_degrees():
    # 174 -> 3356 (heavy), 1299 -> 3356, 3356 -> 15169 ; 64500 <-> 64501 isolated pair
    edges = pd.DataFrame([(174, 3356, 100), (1299, 3356, 50), (3356, 15169, 120),
                          (64500, 64501, 1), (64501, 64500, 1)], columns=["src", "dst", "weight"])
    g = build_graph(edges)
    nodes = node_metrics(g).set_index("asn")
    assert nodes.loc[3356, "in_degree"] == 2 and nodes.loc[3356, "out_degree"] == 1
    assert nodes.loc[3356, "hub_score"] == 3 and nodes.loc[3356, "hub_rank"] == 1
    assert nodes.loc[15169, "pagerank"] > nodes.loc[174, "pagerank"]   # sink of the heavy chain
    assert abs(nodes["pagerank"].sum() - 1.0) < 1e-9
    assert sorted(nodes["pagerank_rank"]) == list(range(1, 7))
    n_comp, share = component_summary(g)
    assert n_comp == 2 and share == 4 / 6
