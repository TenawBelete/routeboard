import json
import sys
from pathlib import Path

import pytest
from pyspark.sql import SparkSession

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import transforms as T  # noqa: E402


@pytest.fixture(scope="module")
def spark():
    s = (SparkSession.builder.master("local[1]")
         .config("spark.sql.session.timeZone", "UTC")
         .config("spark.ui.enabled", "false")
         .config("spark.sql.shuffle.partitions", "2")
         .getOrCreate())
    yield s
    s.stop()


def msg(ts, peer_asn, path=None, ann=None, wd=None, mtype="ris_message"):
    data = {"timestamp": ts, "peer": "1.2.3.4", "peer_asn": str(peer_asn),
            "host": "rrc00.ripe.net", "type": "UPDATE"}
    if path is not None:
        data["path"] = path
    if ann is not None:
        data["announcements"] = ann
    if wd is not None:
        data["withdrawals"] = wd
    return json.dumps({"type": mtype, "data": data})


# 2026-11-14 08:22:10 UTC and 08:22:50 UTC (same minute), 08:23:05 UTC (next minute)
T0 = 1794126130.5
ROWS = [
    # announce two prefixes, normal path
    msg(T0, 3333, [3333, 1103, 12859],
        ann=[{"next_hop": "1.1.1.1", "prefixes": ["10.0.0.0/24", "10.0.1.0/24"]}]),
    # path ending in an AS_SET, plus a withdrawal in the same message
    msg(T0 + 40, 174, [174, 3356, [64500, 64501]],
        ann=[{"next_hop": "2.2.2.2", "prefixes": ["192.0.2.0/24"]}],
        wd=["198.51.100.0/24"]),
    # pure withdrawal, no path
    msg(T0 + 55, 3333, wd=["203.0.113.0/24", "203.0.113.128/25"]),
    # not an update: must be dropped
    msg(T0, 3333, mtype="ris_error"),
    # garbage: must be dropped, not crash
    "this is not json",
]


def silver(spark):
    raw = spark.createDataFrame([(r,) for r in ROWS], ["raw_json"])
    return T.explode_events(T.parse_messages(raw))


def test_parse_drops_non_messages(spark):
    raw = spark.createDataFrame([(r,) for r in ROWS], ["raw_json"])
    assert T.parse_messages(raw).count() == 3


def test_explode_counts_and_types(spark):
    rows = silver(spark).collect()
    assert len(rows) == 6                      # 3 announcements + 3 withdrawals
    by_type = {t: sum(1 for r in rows if r.event_type == t) for t in "AW"}
    assert by_type == {"A": 3, "W": 3}


def test_origin_and_path_length(spark):
    rows = {r.prefix: r for r in silver(spark).collect()}
    normal = rows["10.0.0.0/24"]
    assert normal.origin_asn == 12859 and normal.path_length == 3
    as_set = rows["192.0.2.0/24"]
    assert as_set.origin_asn == 64501          # last number, even inside an AS_SET
    wd = rows["203.0.113.0/24"]
    assert wd.origin_asn is None and wd.path_length is None


def test_peer_asn_is_numeric(spark):
    assert {r.peer_asn for r in silver(spark).collect()} == {3333, 174}


def test_kpi_events_per_minute(spark):
    out = {str(r.window_start): r for r in T.kpi_events_1m(silver(spark)).collect()}
    # Every row must land in exactly one minute and the totals must add up.
    assert sum(r.total_updates for r in out.values()) == 6
    assert sum(r.announcements for r in out.values()) == 3
    assert sum(r.withdrawals for r in out.values()) == 3
    assert all(r.total_updates == r.announcements + r.withdrawals for r in out.values())


def test_kpi_peers_and_origins(spark):
    s = silver(spark)
    peers = {(str(r.window_start), r.peer_asn): r for r in T.kpi_peers_5m(s).collect()}
    assert sum(r.updates for r in peers.values()) == 6
    p3333 = [r for (w, a), r in peers.items() if a == 3333]
    assert sum(r.updates for r in p3333) == 4 and sum(r.withdrawals for r in p3333) == 2
    origins = {r.origin_asn: r.announcements for r in T.kpi_origins_5m(s).collect()}
    assert origins == {12859: 2, 64501: 1}


def test_five_minute_windows_align(spark):
    for r in T.kpi_peers_5m(silver(spark)).collect():
        assert r.window_start.minute % 5 == 0 and r.window_start.second == 0
