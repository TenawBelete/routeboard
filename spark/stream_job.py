"""Kafka -> Delta (bronze, silver) -> Postgres (gold KPIs).

One streaming query reads the Kafka topic. For every micro-batch it:

  1. appends the raw messages to the BRONZE Delta table (replayable raw copy)
  2. appends one row per announced/withdrawn prefix to the SILVER Delta table
  3. recomputes the KPI windows that this batch touched, from SILVER, and
     upserts them into Postgres (GOLD)

Replay safety: Spark may re-run a micro-batch after a crash. Steps 1 and 2 use
Delta's idempotent-write options (txnAppId + txnVersion = batch id), so a re-run
batch is skipped instead of appended twice. Step 3 recomputes instead of
adding, so it is safe to repeat and late messages simply correct their window.
Note: txnVersion is the Spark batch id, which restarts at 0 if the checkpoint is
deleted - so the checkpoint and the lake must always be deleted together
(`make clean` does this).
"""

import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

import transforms as T

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "redpanda:9092")
KAFKA_TOPIC = os.environ.get("KAFKA_TOPIC", "ris.updates.raw")
LAKE = os.environ.get("LAKE_PATH", "/data/lake")
CHECKPOINT = os.environ.get("CHECKPOINT_PATH", "/data/checkpoints/ingest")   # local FS, see README
TRIGGER_SECONDS = int(os.environ.get("TRIGGER_SECONDS", "30"))
MAX_OFFSETS = int(os.environ.get("MAX_OFFSETS_PER_TRIGGER", "200000"))
LAKE_FORMAT = os.environ.get("LAKE_FORMAT", "delta")   # tests use "parquet"

PG_HOST = os.environ.get("POSTGRES_HOST", "postgres")
PG_DB = os.environ["POSTGRES_DB"]
PG_USER = os.environ["POSTGRES_USER"]
PG_PASSWORD = os.environ["POSTGRES_PASSWORD"]
PG_URL = f"jdbc:postgresql://{PG_HOST}:5432/{PG_DB}"

BRONZE = f"{LAKE}/bronze/ris_raw"
SILVER = f"{LAKE}/silver/prefix_events"
EDGES_DAILY = f"{LAKE}/gold/as_edges_daily"      # built by maintenance.py
TRIGGER_FILE = Path(os.environ.get("MAINTENANCE_TRIGGER", "/data/checkpoints/run-maintenance"))

logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("stream_job")
logging.getLogger("py4j").setLevel(logging.WARNING)   # hide Spark-internal chatter


def build_spark(app_name: str = "bgp-stream") -> SparkSession:
    """SparkSession with Delta enabled and S3A pointed at our object store.

    S3_* variables are optional: when LAKE_PATH is a plain directory (tests,
    or a Docker-volume fallback) they are simply not used.
    """
    b = (
        SparkSession.builder.appName(app_name)
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog",
                "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "4")   # default 200 is far too many for one machine
        .config("spark.ui.showConsoleProgress", "false")
        # Keep Delta's own retention logic honest: we never want to vacuum below 7 days
        # by accident, so maintenance.py sets the check explicitly when it does.
    )
    endpoint = os.environ.get("S3_ENDPOINT")
    if endpoint:
        b = (b.config("spark.hadoop.fs.s3a.endpoint", endpoint)
              .config("spark.hadoop.fs.s3a.access.key", os.environ["S3_ACCESS_KEY"])
              .config("spark.hadoop.fs.s3a.secret.key", os.environ["S3_SECRET_KEY"])
              .config("spark.hadoop.fs.s3a.path.style.access", "true")
              .config("spark.hadoop.fs.s3a.connection.ssl.enabled",
                      str(endpoint.startswith("https")).lower())
              .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem")
              .config("spark.hadoop.fs.s3a.aws.credentials.provider",
                      "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider")
              # Delta on S3 needs a log store that gives atomic "put if absent";
              # with a single writer per table the S3A store is safe.
              .config("spark.delta.logStore.s3a.impl", "io.delta.storage.S3SingleDriverLogStore")
              .config("spark.hadoop.fs.s3a.committer.name", "directory")
              .config("spark.hadoop.fs.s3a.fast.upload", "true"))
    return b.getOrCreate()


# --- Postgres helpers --------------------------------------------------------

def run_sql(spark: SparkSession, sql: str) -> None:
    """Run one SQL statement on Postgres through the JVM JDBC driver."""
    jvm = spark._sc._gateway.jvm
    props = jvm.java.util.Properties()
    props.setProperty("user", PG_USER)
    props.setProperty("password", PG_PASSWORD)
    conn = jvm.org.postgresql.Driver().connect(PG_URL, props)
    try:
        stmt = conn.createStatement()
        stmt.execute(sql)
        stmt.close()
    finally:
        conn.close()


def upsert(spark: SparkSession, df: DataFrame, table: str, keys: list, values: list) -> None:
    """Write df to a staging table, then INSERT .. ON CONFLICT DO UPDATE into `table`."""
    stage = f"stg_{table}"
    (df.write.format("jdbc")
       .option("url", PG_URL).option("dbtable", stage)
       .option("user", PG_USER).option("password", PG_PASSWORD)
       .option("driver", "org.postgresql.Driver")
       .option("truncate", "true")
       .mode("overwrite").save())

    cols = keys + values
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in values)
    run_sql(spark, f"""
        INSERT INTO {table} ({", ".join(cols)}, updated_at)
        SELECT {", ".join(cols)}, now() FROM {stage}
        ON CONFLICT ({", ".join(keys)}) DO UPDATE SET {sets}, updated_at = now()
    """)


def touched(silver: DataFrame, events: DataFrame, window_fn) -> DataFrame:
    """Rows of `silver` that fall in any window that `events` (this batch) touches."""
    days = [r.dt for r in events.select("dt").distinct().collect()]
    windows = events.select(window_fn("event_time").alias("_w")).distinct()
    return (silver.where(F.col("dt").isin(days))          # prune to the days involved
                  .withColumn("_sw", window_fn("event_time"))
                  .join(F.broadcast(windows), F.col("_sw") == F.col("_w"), "inner")
                  .drop("_sw", "_w"))


def refresh_gold(spark: SparkSession, events: DataFrame) -> None:
    silver = spark.read.format(LAKE_FORMAT).load(SILVER)

    upsert(spark, T.kpi_events_1m(touched(silver, events, T.minute_of)),
           "kpi_events_1m", ["window_start"],
           ["announcements", "withdrawals", "total_updates"])

    s5 = touched(silver, events, T.five_minute_of).cache()
    upsert(spark, T.kpi_peers_5m(s5), "kpi_peers_5m",
           ["window_start", "peer_asn"], ["updates", "withdrawals"])
    upsert(spark, T.kpi_origins_5m(s5), "kpi_origins_5m",
           ["window_start", "origin_asn"], ["announcements"])
    s5.unpersist()


# --- the micro-batch ---------------------------------------------------------

def process_batch(batch: DataFrame, batch_id: int) -> None:
    spark = batch.sparkSession
    raw = batch.select(
        F.col("value").cast("string").alias("raw_json"),
        F.col("topic"), F.col("partition"), F.col("offset"),
        F.col("timestamp").alias("kafka_time"),
    ).cache()

    n_raw = raw.count()
    if n_raw == 0:
        raw.unpersist()
        return

    # 1) bronze: raw copy
    (raw.withColumn("dt", F.to_date("kafka_time")).write
        .format(LAKE_FORMAT).mode("append").partitionBy("dt")
        .option("txnAppId", "bgp-bronze").option("txnVersion", batch_id)   # idempotent on replay
        .save(BRONZE))

    # 2) silver: one row per prefix event
    events = T.explode_events(T.parse_messages(raw)).cache()
    n_events = events.count()
    (events.write.format(LAKE_FORMAT).mode("append").partitionBy("dt")
        .option("txnAppId", "bgp-silver").option("txnVersion", batch_id)   # idempotent on replay
        .option("mergeSchema", "true")   # lets us add columns (e.g. as_path) without a rebuild
        .save(SILVER))

    # 3) gold: recompute the windows this batch touched, from the full silver table
    if n_events > 0:
        refresh_gold(spark, events)

    log.info("batch %d: raw=%d prefix_events=%d", batch_id, n_raw, n_events)
    events.unpersist()
    raw.unpersist()


def maintenance_loop(spark: SparkSession) -> None:
    """Daily maintenance, plus on demand when TRIGGER_FILE appears (make maintenance).

    Runs in a thread of THIS process: Delta on S3 allows one writer process per
    table, and the streaming query is that writer.
    """
    import maintenance as M   # imported here: needs the delta package, not needed in unit tests
    nxt = M.next_run_after(datetime.now(timezone.utc),
                           M.MAINTENANCE_HOUR_UTC, M.MAINTENANCE_MINUTE_UTC)
    log.info("maintenance scheduled for %s UTC daily; next %s", 
             f"{M.MAINTENANCE_HOUR_UTC:02d}:{M.MAINTENANCE_MINUTE_UTC:02d}", nxt.isoformat())
    while True:
        time.sleep(5)
        now = datetime.now(timezone.utc)
        manual = TRIGGER_FILE.exists()
        if manual or now >= nxt:
            if manual:
                TRIGGER_FILE.unlink(missing_ok=True)
            try:
                M.run(spark)
            except Exception:   # never kill the stream because maintenance failed
                log.exception("maintenance failed; will retry at the next scheduled time")
            if now >= nxt:
                nxt = M.next_run_after(datetime.now(timezone.utc),
                                       M.MAINTENANCE_HOUR_UTC, M.MAINTENANCE_MINUTE_UTC)


def main() -> None:
    spark = build_spark()
    spark.sparkContext.setLogLevel("WARN")
    log.info("reading %s from %s, trigger=%ss", KAFKA_TOPIC, KAFKA_BOOTSTRAP, TRIGGER_SECONDS)

    stream = (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", KAFKA_BOOTSTRAP)
        .option("subscribe", KAFKA_TOPIC)
        .option("startingOffsets", "earliest")      # only used on the very first run
        .option("maxOffsetsPerTrigger", MAX_OFFSETS)
        .option("failOnDataLoss", "false")          # old data may expire by retention
        .load()
    )

    query = (
        stream.writeStream
        .foreachBatch(process_batch)
        .option("checkpointLocation", CHECKPOINT)
        .trigger(processingTime=f"{TRIGGER_SECONDS} seconds")
        .start()
    )
    threading.Thread(target=maintenance_loop, args=(spark,), daemon=True,
                     name="maintenance").start()
    query.awaitTermination()


if __name__ == "__main__":
    main()
