"""Pure graph computations on a pandas edge list (src, dst, weight)."""

import networkx as nx
import pandas as pd


def build_graph(edges: pd.DataFrame) -> nx.DiGraph:
    g = nx.DiGraph()
    g.add_weighted_edges_from(edges[["src", "dst", "weight"]].itertuples(index=False, name=None))
    return g


def node_metrics(g: nx.DiGraph, alpha: float = 0.85) -> pd.DataFrame:
    """PageRank (weighted, same alpha=0.85 as the course notebook) + degrees + hub score."""
    pr = nx.pagerank(g, alpha=alpha, weight="weight")
    df = pd.DataFrame({
        "asn": list(g.nodes),
        "pagerank": [pr[n] for n in g.nodes],
        "in_degree": [g.in_degree(n) for n in g.nodes],
        "out_degree": [g.out_degree(n) for n in g.nodes],
    })
    df["hub_score"] = df["in_degree"] + df["out_degree"]
    df["pagerank_rank"] = df["pagerank"].rank(ascending=False, method="first").astype(int)
    df["hub_rank"] = df["hub_score"].rank(ascending=False, method="first").astype(int)
    return df.sort_values("pagerank_rank").reset_index(drop=True)


def component_summary(g: nx.DiGraph) -> tuple[int, float]:
    comps = list(nx.weakly_connected_components(g))
    if not comps:
        return 0, 0.0
    largest = max(len(c) for c in comps)
    return len(comps), largest / g.number_of_nodes()
