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

Runs INSIDE the streaming job's JVM (see stream_job.start_maintenance_thread).
Delta on S3 is only safe with a single writer process per table, so a second
Spark application must never write to these tables.
"""

import logging
import os
from datetime import date, datetime, timedelta, timezone

from delta.tables import DeltaTable
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

import transforms as T

LAKE = os.environ.get("LAKE_PATH", "/data/lake")
BRONZE = f"{LAKE}/bronze/ris_raw"
SILVER = f"{LAKE}/silver/prefix_events"
EDGES_DAILY = f"{LAKE}/gold/as_edges_daily"
MAINTENANCE_HOUR_UTC = int(os.environ.get("MAINTENANCE_HOUR_UTC", "3"))
MAINTENANCE_MINUTE_UTC = int(os.environ.get("MAINTENANCE_MINUTE_UTC", "15"))

RETENTION_BRONZE_DAYS = int(os.environ.get("RETENTION_BRONZE_DAYS", "3"))
RETENTION_SILVER_DAYS = int(os.environ.get("RETENTION_SILVER_DAYS", "14"))
# Delta keeps deleted files this long so that running queries can still read
# them. 1 hour is plenty here: the only reader is our own streaming job.
VACUUM_RETAIN_HOURS = int(os.environ.get("VACUUM_RETAIN_HOURS", "1"))

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


def next_run_after(now: datetime, hour: int, minute: int) -> datetime:
    """The next daily run time strictly after `now` (UTC)."""
    t = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return t if t > now else t + timedelta(days=1)


def run(spark: SparkSession, today: date | None = None) -> None:
    today = today or datetime.now(timezone.utc).date()
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
