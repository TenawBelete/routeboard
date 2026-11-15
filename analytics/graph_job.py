"""Hourly AS-graph job.

Reads the last GRAPH_WINDOW_HOURS of announcements from the silver Delta table
(via Spark, because it lives on S3), aggregates consecutive AS-path pairs into
weighted directed edges, then computes PageRank, degrees and hub score with
NetworkX on the driver (the AS graph is ~30k nodes, which fits easily), and
stores the top nodes and edges in Postgres for the API.

Why NetworkX and not GraphFrames: same PageRank, no extra JVM package to resolve
at start-up, and the whole graph fits in memory. The trade-off is documented in
the README; swapping in GraphFrames would only change this file.
"""

import logging
import os
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
from pyspark.sql import functions as F

sys.path.insert(0, "/app/spark")       # transforms.py / stream_job.py live there
import transforms as T                 # noqa: E402
from stream_job import SILVER, build_spark   # noqa: E402

from common import connect             # noqa: E402
from graph_metrics import build_graph, component_summary, node_metrics  # noqa: E402

WINDOW_HOURS = int(os.environ.get("GRAPH_WINDOW_HOURS", "24"))
KEEP_RUNS_DAYS = int(os.environ.get("GRAPH_KEEP_RUNS_DAYS", "7"))
KEEP_DETAIL_RUNS = int(os.environ.get("GRAPH_KEEP_DETAIL_RUNS", "2"))
log = logging.getLogger("graph_job")


def load_edges(spark, since: datetime) -> pd.DataFrame:
    silver = (spark.read.format("delta").load(SILVER)
              .where(F.col("dt") >= F.lit(since.date()))
              .where(F.col("event_time") >= F.lit(since)))
    edges = (T.as_edges_daily(silver)
             .groupBy("src", "dst").agg(F.sum("weight").alias("weight")))
    return edges.toPandas()


def store(edges: pd.DataFrame, nodes: pd.DataFrame, n_components: int, share: float) -> int:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""insert into graph_runs (window_hours, n_nodes, n_edges, n_components, largest_component_share)
                       values (%s, %s, %s, %s, %s) returning run_id""",
                    (WINDOW_HOURS, len(nodes), len(edges), n_components, share))
        run_id = cur.fetchone()[0]
        # Every node and link is stored so any network can be looked up, not just the top ones.
        with cur.copy("copy graph_nodes from stdin") as cp:
            for r in nodes.itertuples(index=False):
                cp.write_row((run_id, int(r.asn), float(r.pagerank), int(r.in_degree), int(r.out_degree),
                              int(r.hub_score), int(r.pagerank_rank), int(r.hub_rank)))
        with cur.copy("copy graph_edges_top from stdin") as cp:
            for r in edges.itertuples(index=False):
                cp.write_row((run_id, int(r.src), int(r.dst), int(r.weight)))
        # Week-long memory for the country pages: keep each link's largest 24 h count and when it was last seen.
        cur.execute("""insert into graph_edges_seen (src, dst, weight, last_seen)
                       select src, dst, weight, now() from graph_edges_top where run_id = %s
                       on conflict (src, dst) do update
                         set weight = greatest(graph_edges_seen.weight, excluded.weight), last_seen = now()""", (run_id,))
        cur.execute("delete from graph_edges_seen where last_seen < now() - interval '30 days'")
        # Full detail only for the newest runs; older runs keep their one-line summary.
        cur.execute("delete from graph_nodes where run_id < %s", (run_id - KEEP_DETAIL_RUNS + 1,))
        cur.execute("delete from graph_edges_top where run_id < %s", (run_id - KEEP_DETAIL_RUNS + 1,))
        cur.execute("delete from graph_runs where computed_at < now() - make_interval(days => %s)",
                    (KEEP_RUNS_DAYS,))
        conn.commit()
    return run_id


def main() -> int:
    spark = build_spark("bgp-graph")
    spark.sparkContext.setLogLevel("WARN")
    since = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)
    edges = load_edges(spark, since)
    if edges.empty:
        log.warning("no announcements in the last %dh; nothing to compute", WINDOW_HOURS)
        return 0
    g = build_graph(edges)
    nodes = node_metrics(g)
    n_comp, share = component_summary(g)
    run_id = store(edges, nodes, n_comp, share)
    log.info("run %d: %d nodes, %d edges, %d components (largest %.1f%%); top PageRank: %s",
             run_id, len(nodes), len(edges), n_comp, 100 * share,
             nodes.head(5)[["asn", "pagerank"]].values.tolist())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        log.exception("graph job failed")
        raise SystemExit(1)
