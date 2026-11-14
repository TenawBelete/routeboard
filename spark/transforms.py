"""Pure DataFrame transforms for the BGP pipeline.

Nothing here touches Kafka, Delta or Postgres, so the same functions run in
the streaming job and in unit tests.
"""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    ArrayType, DoubleType, StringType, StructField, StructType,
)

# The parts of a RIS Live message we need. "path" is parsed separately because
# it mixes numbers and nested lists (AS_SETs), which a fixed schema cannot hold.
MESSAGE_SCHEMA = StructType([
    StructField("type", StringType()),
    StructField("data", StructType([
        StructField("timestamp", DoubleType()),
        StructField("peer_asn", StringType()),
        StructField("host", StringType()),
        StructField("type", StringType()),
        StructField("announcements", ArrayType(StructType([
            StructField("next_hop", StringType()),
            StructField("prefixes", ArrayType(StringType())),
        ]))),
        StructField("withdrawals", ArrayType(StringType())),
    ])),
])

SILVER_COLUMNS = [
    "event_time", "dt", "host", "peer_asn", "event_type",
    "prefix", "origin_asn", "path_length",
]


def parse_messages(raw: DataFrame) -> DataFrame:
    """Kafka rows (with a string column `raw_json`) -> one row per RIS message."""
    parsed = raw.withColumn("msg", F.from_json("raw_json", MESSAGE_SCHEMA))
    path_json = F.get_json_object("raw_json", "$.data.path")
    return (
        parsed
        .where(F.col("msg.type") == "ris_message")
        .select(
            F.timestamp_seconds(F.col("msg.data.timestamp")).alias("event_time"),
            F.col("msg.data.host").alias("host"),
            F.col("msg.data.peer_asn").cast("long").alias("peer_asn"),
            # Last number in the path = origin AS (works when it ends in an AS_SET too).
            F.regexp_extract(path_json, r"(\d+)\D*$", 1).alias("_origin"),
            # Count of numbers in the path; a rough path length.
            F.size(F.split(F.regexp_replace(path_json, r"[^\d,\[]", ""), ",")).alias("_plen"),
            path_json.isNotNull().alias("_has_path"),
            F.col("msg.data.announcements").alias("announcements"),
            F.col("msg.data.withdrawals").alias("withdrawals"),
        )
        .where(F.col("event_time").isNotNull() & F.col("peer_asn").isNotNull())
    )


def explode_events(messages: DataFrame) -> DataFrame:
    """One row per (message, prefix), labelled announce 'A' or withdraw 'W'."""
    base = ["event_time", "host", "peer_asn", "_origin", "_plen", "_has_path"]

    announced = (
        messages
        .select(*base, F.explode_outer("announcements").alias("a"))
        .select(*base, F.explode_outer("a.prefixes").alias("prefix"))
        .where(F.col("prefix").isNotNull())
        .withColumn("event_type", F.lit("A"))
    )
    withdrawn = (
        messages
        .select(*base, F.explode_outer("withdrawals").alias("prefix"))
        .where(F.col("prefix").isNotNull())
        .withColumn("event_type", F.lit("W"))
    )

    events = announced.unionByName(withdrawn)
    return events.select(
        "event_time",
        F.to_date("event_time").alias("dt"),
        "host",
        "peer_asn",
        "event_type",
        "prefix",
        # Withdrawals carry no path, so origin and length stay null for them.
        F.when((F.col("event_type") == "A") & F.col("_has_path") & (F.col("_origin") != ""),
               F.col("_origin").cast("long")).alias("origin_asn"),
        F.when((F.col("event_type") == "A") & F.col("_has_path"),
               F.col("_plen")).alias("path_length"),
    )


def minute_of(col):
    return F.date_trunc("minute", col)


def five_minute_of(col):
    return F.timestamp_seconds(F.floor(F.unix_timestamp(col) / 300) * 300)


def kpi_events_1m(silver: DataFrame) -> DataFrame:
    return (
        silver
        .groupBy(minute_of("event_time").alias("window_start"))
        .agg(
            F.sum((F.col("event_type") == "A").cast("long")).alias("announcements"),
            F.sum((F.col("event_type") == "W").cast("long")).alias("withdrawals"),
            F.count("*").alias("total_updates"),
        )
    )


def kpi_peers_5m(silver: DataFrame) -> DataFrame:
    return (
        silver
        .groupBy(five_minute_of("event_time").alias("window_start"), "peer_asn")
        .agg(
            F.count("*").alias("updates"),
            F.sum((F.col("event_type") == "W").cast("long")).alias("withdrawals"),
        )
    )


def kpi_origins_5m(silver: DataFrame) -> DataFrame:
    return (
        silver
        .where((F.col("event_type") == "A") & F.col("origin_asn").isNotNull())
        .groupBy(five_minute_of("event_time").alias("window_start"), "origin_asn")
        .agg(F.count("*").alias("announcements"))
    )
