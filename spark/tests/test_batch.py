"""Runs process_batch() on fake Kafka rows with Parquet standing in for Delta
and a stub for the Postgres upsert. Checks the gold tables are RECOMPUTED, so a
second batch that touches the same minute corrects it instead of double counting."""
import json
import os
import sys
from pathlib import Path

import pytest
from pyspark.sql import SparkSession

os.environ.update(POSTGRES_DB="x", POSTGRES_USER="x", POSTGRES_PASSWORD="x", LAKE_FORMAT="parquet")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stream_job as J  # noqa: E402

T0 = 1794126130.5   # 2026-11-14 08:22:10 UTC


def kafka_row(i, ts, asn, ann=(), wd=()):
    data = {"timestamp": ts, "peer_asn": str(asn), "host": "rrc00", "type": "UPDATE"}
    if ann:
        data["path"] = [asn, 3356, 15169]
        data["announcements"] = [{"next_hop": "1.1.1.1", "prefixes": list(ann)}]
    if wd:
        data["withdrawals"] = list(wd)
    val = json.dumps({"type": "ris_message", "data": data}).encode()
    return (val, "ris.updates.raw", 0, i, __import__("datetime").datetime.utcfromtimestamp(ts))


@pytest.fixture()
def spark(tmp_path):
    J.BRONZE = str(tmp_path / "bronze")
    J.SILVER = str(tmp_path / "silver")
    s = (SparkSession.builder.master("local[1]")
         .config("spark.sql.session.timeZone", "UTC").config("spark.ui.enabled", "false")
         .config("spark.sql.shuffle.partitions", "2").getOrCreate())
    yield s
    s.stop()


def batch(spark, rows):
    return spark.createDataFrame(rows, "value binary, topic string, partition int, offset long, timestamp timestamp")


def test_gold_is_recomputed_not_added(spark, monkeypatch):
    captured = {}
    monkeypatch.setattr(J, "upsert", lambda sp, df, table, keys, vals:
                        captured.__setitem__(table, {tuple(r[k] for k in keys): r.asDict() for r in df.collect()}))

    # batch 1: two events in minute 08:22
    J.process_batch(batch(spark, [
        kafka_row(0, T0, 3333, ann=["10.0.0.0/24", "10.0.1.0/24"]),
    ]), 0)
    first = list(captured["kpi_events_1m"].values())
    assert len(first) == 1 and first[0]["total_updates"] == 2

    # batch 2: one more announcement + one withdrawal in the SAME minute
    J.process_batch(batch(spark, [
        kafka_row(1, T0 + 20, 174, ann=["192.0.2.0/24"], wd=["198.51.100.0/24"]),
    ]), 1)
    second = list(captured["kpi_events_1m"].values())
    assert len(second) == 1                     # still one row for that minute
    assert second[0]["announcements"] == 3 and second[0]["withdrawals"] == 1
    assert second[0]["total_updates"] == 4      # 2 + 2, not just the last batch

    peers = {k[1]: v for k, v in captured["kpi_peers_5m"].items()}
    assert peers[3333]["updates"] == 2 and peers[174]["updates"] == 2   # recomputed over both batches
    origins = {k[1]: v["announcements"] for k, v in captured["kpi_origins_5m"].items()}
    assert origins == {15169: 3}


def test_empty_batch_is_a_noop(spark, monkeypatch):
    calls = []
    monkeypatch.setattr(J, "upsert", lambda *a, **k: calls.append(1))
    J.process_batch(batch(spark, []), 0)
    assert calls == []
