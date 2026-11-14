"""RIS Live -> Kafka producer.

Connects to the RIPE RIS Live WebSocket, subscribes to BGP UPDATE messages,
keeps one message in every SAMPLE_EVERY, and publishes the raw JSON to Kafka
keyed by peer ASN. Reconnects with exponential backoff and shuts down cleanly
on SIGTERM so `docker compose down` loses nothing.

The payload is published unchanged: {"type": "ris_message", "data": {...}}.
"""

import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from urllib.parse import quote

from confluent_kafka import Producer
from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "localhost:19092")
KAFKA_TOPIC = os.environ.get("KAFKA_TOPIC", "ris.updates.raw")
RIS_CLIENT = os.environ.get("RIS_CLIENT", "bgp-pipeline")
RIS_HOSTS = [h.strip() for h in os.environ.get("RIS_HOSTS", "").split(",") if h.strip()]
SAMPLE_EVERY = max(1, int(os.environ.get("SAMPLE_EVERY", "50")))

RIS_URL = f"wss://ris-live.ripe.net/v1/ws/?client={quote(RIS_CLIENT)}"
RECV_TIMEOUT_S = 60       # no message for this long -> treat the link as dead
STATS_EVERY_S = 30
BACKOFF_START_S = 2.0
BACKOFF_MAX_S = 60.0
HEARTBEAT = Path("/tmp/heartbeat")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("producer")


class Stats:
    def __init__(self):
        self.received = 0
        self.produced = 0
        self.delivered = 0
        self.failed = 0
        self.skipped = 0
        self.last_report = time.monotonic()

    def maybe_report(self):
        now = time.monotonic()
        if now - self.last_report < STATS_EVERY_S:
            return
        log.info(
            "received=%d produced=%d delivered=%d failed=%d skipped=%d",
            self.received, self.produced, self.delivered, self.failed, self.skipped,
        )
        self.last_report = now
        try:
            HEARTBEAT.touch()
        except OSError:
            pass


stats = Stats()
stopping = False


def handle_stop(signum, _frame):
    global stopping
    log.info("signal %s received, stopping", signum)
    stopping = True


def on_delivery(err, _msg):
    if err is not None:
        stats.failed += 1
    else:
        stats.delivered += 1


def make_producer() -> Producer:
    return Producer({
        "bootstrap.servers": KAFKA_BOOTSTRAP,
        "client.id": "ris-producer",
        "enable.idempotence": True,   # no duplicates on retry
        "acks": "all",
        "compression.type": "lz4",
        "linger.ms": 200,             # batch for throughput
    })


def publish(producer: Producer, raw: str) -> None:
    """Validate one RIS message and send it to Kafka."""
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        stats.skipped += 1
        return

    if msg.get("type") != "ris_message":
        # ris_error, pong, etc.
        if msg.get("type") == "ris_error":
            log.warning("ris_error: %s", msg.get("data"))
        stats.skipped += 1
        return

    data = msg.get("data") or {}
    key = str(data.get("peer_asn") or "")

    while True:
        try:
            producer.produce(KAFKA_TOPIC, key=key, value=raw, on_delivery=on_delivery)
            stats.produced += 1
            return
        except BufferError:
            # Local queue is full: let the client drain, then retry.
            producer.poll(1.0)


def subscribe(ws) -> None:
    """Ask RIS Live for UPDATE messages, optionally limited to some collectors."""
    if RIS_HOSTS:
        for host in RIS_HOSTS:
            ws.send(json.dumps({"type": "ris_subscribe",
                                "data": {"type": "UPDATE", "host": host}}))
    else:
        ws.send(json.dumps({"type": "ris_subscribe", "data": {"type": "UPDATE"}}))


def stream_once(producer: Producer) -> None:
    """One WebSocket session. Returns or raises when the connection ends."""
    with connect(RIS_URL, open_timeout=15, max_size=4 * 1024 * 1024) as ws:
        subscribe(ws)
        log.info("subscribed (hosts=%s, sample_every=%d)",
                 ",".join(RIS_HOSTS) or "all", SAMPLE_EVERY)
        while not stopping:
            raw = ws.recv(timeout=RECV_TIMEOUT_S)
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")

            stats.received += 1
            if stats.received % SAMPLE_EVERY == 0:
                publish(producer, raw)

            producer.poll(0)          # serve delivery callbacks
            stats.maybe_report()


def main() -> int:
    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    log.info("kafka=%s topic=%s", KAFKA_BOOTSTRAP, KAFKA_TOPIC)
    producer = make_producer()
    HEARTBEAT.touch()

    backoff = BACKOFF_START_S
    while not stopping:
        started = time.monotonic()
        try:
            stream_once(producer)
        except (WebSocketException, OSError, TimeoutError) as exc:
            log.warning("stream error: %s: %s", type(exc).__name__, exc)

        if stopping:
            break

        # A session that lasted a while was healthy, so start the backoff over.
        if time.monotonic() - started > 60:
            backoff = BACKOFF_START_S
        log.info("reconnecting in %.0fs", backoff)
        deadline = time.monotonic() + backoff
        while not stopping and time.monotonic() < deadline:
            producer.poll(0.5)
        backoff = min(BACKOFF_MAX_S, backoff * 2)

    remaining = producer.flush(15)
    log.info("stopped; produced=%d delivered=%d failed=%d unflushed=%d",
             stats.produced, stats.delivered, stats.failed, remaining)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
