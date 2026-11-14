"""Nightly maintenance for the lake. Safe to run more than once a day.

  1. Daily AS-link summary  (gold/as_edges_daily): for every day that is
     complete and not summarised yet, aggregate silver into per-day
     (src, dst, weight) rows. Kept forever; this is what the graph stage reads
     after the detailed rows expire.
  2. Retention: delete bronze partitions older than RETENTION_BRONZE_DAYS and
     silver partitions older than RETENTION_SILVER_DAYS. A silver day is only
     deleted after step 1 has summarised it, so nothing is lost silently.
  3. Compaction: OPTIMIZE the tables (many small streaming files -> few large
     ones), then VACUUM to free the disk space of deleted files.

Exit code is non-zero on any failure so the scheduler log shows it.
"""

import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone

from delta.tables import DeltaTable
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

import transforms as T
from stream_job import BRONZE, EDGES_DAILY, SILVER, build_spark

RETENTION_BRONZE_DAYS = int(os.environ.get("RETENTION_BRONZE_DAYS", "3"))
RETENTION_SILVER_DAYS = int(os.environ.get("RETENTION_SILVER_DAYS", "14"))
# Delta keeps deleted files this long so that running queries can still read
# them. 1 hour is plenty here: the only reader is our own streaming job.
VACUUM_RETAIN_HOURS = int(os.environ.get("VACUUM_RETAIN_HOURS", "1"))

logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("maintenance")


def table_exists(spark: SparkSession, path: str) -> bool:
    return DeltaTable.isDeltaTable(spark, path)


def summarise_completed_days(spark: SparkSession, today: date) -> int:
    """Build as_edges_daily for every past day in silver that is missing from it."""
    if not table_exists(spark, SILVER):
        log.info("silver does not exist yet; nothing to summarise")
        return 0

    silver = spark.read.format("delta").load(SILVER)
    silver_days = {r.dt for r in silver.select("dt").distinct().collect()}
    done = set()
    if table_exists(spark, EDGES_DAILY):
        done = {r.dt for r in spark.read.format("delta").load(EDGES_DAILY)
                .select("dt").distinct().collect()}

    # Only days strictly before today: today's data is still arriving.
    todo = sorted(d for d in silver_days if d < today and d not in done)
    for d in todo:
        edges = T.as_edges_daily(silver.where(F.col("dt") == F.lit(d)))
        # replaceWhere makes a re-run for the same day idempotent.
        (edges.write.format("delta").mode("overwrite").partitionBy("dt")
              .option("replaceWhere", f"dt = '{d.isoformat()}'")
              .save(EDGES_DAILY))
        log.info("summarised %s: %d AS links", d, edges.count())
    return len(todo)


def days_to_delete(existing: set, keep_days: int, today: date,
                   protect: set | None = None) -> list:
    """Pure decision: which day partitions are past retention and not protected."""
    cutoff = today - timedelta(days=keep_days)
    protect = protect or set()
    return sorted(d for d in existing if d < cutoff and d not in protect)


def expire(spark: SparkSession, path: str, keep_days: int, today: date,
           protect: set | None = None) -> None:
    if not table_exists(spark, path):
        return
    t = DeltaTable.forPath(spark, path)
    existing = {r.dt for r in t.toDF().select("dt").distinct().collect()}
    doomed = days_to_delete(existing, keep_days, today, protect)
    if not doomed:
        log.info("%s: nothing to expire (keep %d days)", path, keep_days)
        return
    # Delete exactly the listed days, so protected days are never touched.
    t.delete(F.col("dt").isin([F.lit(d) for d in doomed]))
    log.info("%s: deleted %d day partitions: %s", path, len(doomed),
             ", ".join(d.isoformat() for d in doomed))


def compact(spark: SparkSession, path: str) -> None:
    if not table_exists(spark, path):
        return
    t = DeltaTable.forPath(spark, path)
    t.optimize().executeCompaction()
    # Delta refuses short retention unless told we know what we are doing.
    spark.conf.set("spark.databricks.delta.retentionDurationCheck.enabled", "false")
    t.vacuum(VACUUM_RETAIN_HOURS)
    log.info("%s: optimized and vacuumed (retain %dh)", path, VACUUM_RETAIN_HOURS)


def main() -> int:
    spark = build_spark("bgp-maintenance")
    spark.sparkContext.setLogLevel("WARN")
    today = datetime.now(timezone.utc).date()
    log.info("maintenance start (today=%s, bronze keep=%dd, silver keep=%dd)",
             today, RETENTION_BRONZE_DAYS, RETENTION_SILVER_DAYS)

    summarise_completed_days(spark, today)

    # Silver days that are not summarised yet must survive, whatever their age.
    summarised = set()
    if table_exists(spark, EDGES_DAILY):
        summarised = {r.dt for r in spark.read.format("delta").load(EDGES_DAILY)
                      .select("dt").distinct().collect()}
    unsummarised = set()
    if table_exists(spark, SILVER):
        unsummarised = {r.dt for r in spark.read.format("delta").load(SILVER)
                        .select("dt").distinct().collect()} - summarised - {today}
    if unsummarised:
        log.warning("silver days kept because not summarised: %s", sorted(unsummarised))

    expire(spark, BRONZE, RETENTION_BRONZE_DAYS, today)
    expire(spark, SILVER, RETENTION_SILVER_DAYS, today, protect=unsummarised)

    for path in (BRONZE, SILVER, EDGES_DAILY):
        compact(spark, path)

    log.info("maintenance done")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        log.exception("maintenance failed")
        raise SystemExit(1)
