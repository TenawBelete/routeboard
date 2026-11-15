import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import Hub, PATHS_PER_FLUSH, RECENT_PER_COUNTRY, SAMPLES_PER_SECOND, flatten_path, matches, sse, to_events  # noqa: E402

NAMES = {15169: ("Google", "US"), 1299: ("Arelion", "SE"), 30987: ("EriTel", "ER"), 3333: ("RIPE NCC", "NL")}


def msg(**data):
    return json.dumps({"type": "ris_message", "data": {"peer_asn": "3333", **data}})


def test_flatten_path_handles_sets_and_repeats():
    assert flatten_path([3333, 1299, 1299, [64512, 64513], 15169]) == [3333, 1299, 64512, 64513, 15169]
    assert flatten_path(None) == [] and flatten_path(["x", 5]) == [5]


def test_announcement_becomes_an_open_event_with_names_and_countries():
    (e,) = to_events(msg(path=[3333, 1299, 15169], announcements=[{"next_hop": "x", "prefixes": ["8.8.8.0/24", "8.8.4.0/24"]}]), NAMES)
    assert e == {"k": "open", "n": 2, "p": "8.8.8.0/24", "o": 15169, "on": "Google", "oc": "US",
                 "path": [3333, 1299, 15169], "pc": ["NL", "SE", "US"], "peer": 3333}


def test_withdrawal_becomes_a_close_event_and_both_can_come_from_one_message():
    events = to_events(msg(path=[3333, 30987], announcements=[{"prefixes": ["196.200.96.0/20"]}], withdrawals=["10.0.0.0/8", "10.1.0.0/16"]), NAMES)
    assert [e["k"] for e in events] == ["open", "close"]
    assert events[1]["n"] == 2 and events[1]["pn"] == "RIPE NCC" and events[1]["o"] is None


def test_garbage_never_raises():
    for bad in [b"", b"not json", b"[]", b'{"data": 5}', b'{"data": {"peer_asn": "abc"}}', msg(path=[1, 2])]:
        assert to_events(bad, NAMES) == []
    assert to_events(msg(announcements=[{"prefixes": ["1.1.1.0/24"]}]), NAMES) == []      # no path -> not shown


def test_country_filter_looks_along_the_whole_path():
    (e,) = to_events(msg(path=[3333, 1299, 30987], announcements=[{"prefixes": ["196.200.96.0/20"]}]), NAMES)
    assert matches(e, "ER") and matches(e, "SE") and matches(e, None) and not matches(e, "US")


def test_hub_counts_per_second_and_limits_samples():
    async def run():
        hub = Hub(clock=lambda: 1000)
        world, eritrea = hub.connect(None), hub.connect("ER")
        for i in range(40):
            hub.add(to_events(msg(path=[3333, 1299, 15169], announcements=[{"prefixes": ["8.8.8.0/24"]}], withdrawals=["10.0.0.0/8"]), NAMES))
        hub.add(to_events(msg(path=[3333, 30987], announcements=[{"prefixes": ["196.200.96.0/20"]}]), NAMES))
        t = hub.tick()
        assert t == {"t": 1000, "opened": 41, "closed": 40, "messages": 41, "up": False}
        got = [world.get_nowait() for _ in range(world.qsize())]
        assert got[0] == ("tick", t) and len(got) == 1 + SAMPLES_PER_SECOND
        er = [eritrea.get_nowait() for _ in range(eritrea.qsize())]
        assert [k for k, _ in er] == ["tick", "msg"] and er[1][1]["oc"] == "ER"
        assert hub.tick()["opened"] == 0 and list(hub.history)[0] == t          # counters reset, history kept
        hub.disconnect(world); hub.disconnect(eritrea)
        assert hub.clients == {}
    asyncio.run(run())


def test_slow_browser_drops_instead_of_blocking_and_client_cap_holds():
    async def run():
        hub = Hub(max_clients=1)
        q = hub.connect(None)
        assert hub.connect(None) is None
        for _ in range(500):
            hub.tick()                      # nobody reads the queue
        assert q.qsize() == q.maxsize       # full, and tick() never blocked or raised
    asyncio.run(run())


def test_sse_frame_format():
    assert sse("tick", {"t": 1}) == b'event: tick\ndata: {"t":1}\n\n'


def test_lz4_compressed_batches_can_be_read():
    """The producer compresses with lz4. Without the lz4 package the consumer fails on every batch."""
    from aiokafka.codec import has_lz4
    from aiokafka.record.default_records import DefaultRecordBatch, DefaultRecordBatchBuilder
    assert has_lz4(), "install aiokafka[lz4]"
    b = DefaultRecordBatchBuilder(magic=2, compression_type=3, is_transactional=0, producer_id=-1,
                                  producer_epoch=-1, base_sequence=-1, batch_size=1 << 20)
    b.append(0, timestamp=1, key=b"3333", value=msg(path=[3333, 15169], announcements=[{"prefixes": ["8.8.8.0/24"]}]).encode(), headers=[])
    (record,) = list(DefaultRecordBatch(bytes(b.build())))
    assert to_events(record.value, NAMES)[0]["on"] == "Google"


def test_tick_says_whether_the_feed_is_up():
    hub = Hub(clock=lambda: 5)
    assert hub.tick()["up"] is False            # nothing has ever arrived
    hub.feed_up = True
    assert hub.tick()["up"] is True


def test_flush_sends_many_paths_for_the_maps_and_respects_country():
    async def run():
        hub = Hub(clock=lambda: 77)
        world, eritrea = hub.connect(None), hub.connect("ER")
        for _ in range(100):
            hub.add(to_events(msg(path=[3333, 1299, 15169], announcements=[{"prefixes": ["8.8.8.0/24"]}]), NAMES))
        hub.add(to_events(msg(path=[3333, 1299, 30987], announcements=[{"prefixes": ["196.200.96.0/20"]}]), NAMES))
        hub.add(to_events(msg(withdrawals=["10.0.0.0/8"]), NAMES))                 # closures have no path to draw
        assert hub.flush() == 101
        kind, paths = world.get_nowait()
        assert kind == "paths" and 20 <= len(paths) <= PATHS_PER_FLUSH and paths[0] == [[3333, 1299, 15169], ["NL", "SE", "US"]]
        kind, paths = eritrea.get_nowait()
        assert paths == [[[3333, 1299, 30987], ["NL", "SE", "ER"]]]
        assert hub.flush() == 0 and world.empty()                                   # nothing new -> nothing sent
    asyncio.run(run())


def test_recent_changes_are_kept_per_country_for_replay():
    hub = Hub(clock=lambda: 500)
    for _ in range(RECENT_PER_COUNTRY + 25):
        hub.add(to_events(msg(path=[3333, 1299, 30987], announcements=[{"prefixes": ["196.200.96.0/20"]}]), NAMES))
    assert len(hub.recent["ER"]) == RECENT_PER_COUNTRY and len(hub.recent["SE"]) == RECENT_PER_COUNTRY
    assert hub.recent["ER"][-1] == {"t": 500, "path": [3333, 1299, 30987], "pc": ["NL", "SE", "ER"]}
    assert "US" not in hub.recent
