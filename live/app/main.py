"""Live service: pushes route changes to browsers as they happen.

It is a second, independent reader of the same Kafka topic the Spark job uses
(no consumer group, always from the newest message), so it adds no load to the
main pipeline and holds no state: restart it at any time.

  GET /live/stream            Server-Sent Events: `tick` every second, `msg` for a few route changes in
                              words, `paths` four times a second for the map animations
  GET /live/stream?country=ER only route changes whose path touches that country (ticks stay global)
  GET /live/health
"""

import asyncio
import logging
import os
import time
import re
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from .core import FLUSHES_PER_SECOND, Hub, sse, to_events

logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("live")

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "redpanda:9092")
KAFKA_TOPIC = os.environ.get("KAFKA_TOPIC", "ris.updates.raw")
NAMES_REFRESH_SECONDS = 3600

hub = Hub(max_clients=int(os.environ.get("LIVE_MAX_CLIENTS", "300")))
names: dict[int, tuple[str | None, str | None]] = {}
state = {"kafka": "starting", "names": 0, "last_error": None, "bad_messages": 0}


def _load_names() -> dict:
    import psycopg
    user, pw = (os.environ.get("API_DB_USER", "bgp_api"), os.environ["API_DB_PASSWORD"]) if os.environ.get("API_DB_PASSWORD") \
        else (os.environ["POSTGRES_USER"], os.environ["POSTGRES_PASSWORD"])
    with psycopg.connect(host=os.environ.get("POSTGRES_HOST", "postgres"), port=os.environ.get("POSTGRES_PORT", "5432"),
                         dbname=os.environ["POSTGRES_DB"], user=user, password=pw, connect_timeout=10,
                         options="-c default_transaction_read_only=on") as conn:
        return {a: (n, c) for a, n, c in conn.execute("select asn, name, country from asn_names")}


async def names_loop() -> None:
    while True:
        try:
            fresh = await asyncio.to_thread(_load_names)
            names.clear(); names.update(fresh); state["names"] = len(names)
            log.info("loaded %d network names", len(names))
            await asyncio.sleep(NAMES_REFRESH_SECONDS)
        except Exception as exc:                       # database not ready yet: names are optional, retry soon
            log.warning("could not load names (%s); retrying in 60s", type(exc).__name__)
            await asyncio.sleep(60)


async def kafka_loop() -> None:
    from aiokafka import AIOKafkaConsumer
    while True:
        consumer = AIOKafkaConsumer(KAFKA_TOPIC, bootstrap_servers=KAFKA_BOOTSTRAP, group_id=None,
                                    auto_offset_reset="latest", enable_auto_commit=False)
        try:
            await consumer.start()
            state["kafka"] = "connected"; hub.feed_up = True
            log.info("reading %s from %s (newest messages only)", KAFKA_TOPIC, KAFKA_BOOTSTRAP)
            async for m in consumer:
                try:
                    hub.add(to_events(m.value, names))
                except Exception as exc:               # one odd message must never stop the stream
                    state["bad_messages"] += 1
                    if state["bad_messages"] <= 5:
                        log.warning("skipped a message (%s: %s)", type(exc).__name__, exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            state["kafka"] = "reconnecting"; hub.feed_up = False
            state["last_error"] = f"{type(exc).__name__}: {exc}"[:300]      # shown by /live/health so the cause is visible without the logs
            log.warning("kafka error (%s: %s); reconnecting in 5s", type(exc).__name__, exc)
            await asyncio.sleep(5)
        finally:
            try:
                await consumer.stop()
            except Exception:
                pass


BACKFILL_MAX_SECONDS = int(os.environ.get("LIVE_BACKFILL_MAX_SECONDS", "600"))


async def backfill_loop() -> None:
    """Once, at start-up: read what Kafka still holds (up to the topic's retention, 6 h by default)
    and remember the last real route changes per country. Counters are not touched, so the
    live numbers stay about now; only the per-country replay memory gets a past."""
    from aiokafka import AIOKafkaConsumer, TopicPartition
    for _ in range(60):                                   # names give paths their countries; wait for them briefly
        if state["names"]:
            break
        await asyncio.sleep(1)
    state["backfill"] = {"status": "running"}
    consumer = AIOKafkaConsumer(bootstrap_servers=KAFKA_BOOTSTRAP, group_id=None,
                                auto_offset_reset="earliest", enable_auto_commit=False, max_poll_records=2000)
    started = time.time(); n = 0
    try:
        await consumer.start()
        parts = [TopicPartition(KAFKA_TOPIC, p) for p in sorted(consumer.partitions_for_topic(KAFKA_TOPIC) or [])]
        if not parts:
            raise RuntimeError("topic has no partitions yet")
        consumer.assign(parts)
        end = await consumer.end_offsets(parts)
        await consumer.seek_to_beginning(*parts)
        done = {tp: (await consumer.position(tp)) >= end[tp] for tp in parts}
        while not all(done.values()) and time.time() - started < BACKFILL_MAX_SECONDS:
            batch = await consumer.getmany(timeout_ms=2000, max_records=2000)
            if not batch:
                continue
            for tp, msgs in batch.items():
                for m in msgs:
                    try:
                        hub.remember(to_events(m.value, names), m.timestamp // 1000)
                    except Exception:
                        pass
                n += len(msgs)
                if msgs and msgs[-1].offset + 1 >= end[tp]:
                    done[tp] = True
            await asyncio.sleep(0)                        # let ticks and browsers run between batches
        hub.sort_recent()
        state["backfill"] = {"status": "done", "messages": n, "seconds": round(time.time() - started),
                             "countries": len(hub.recent)}
        log.info("backfill: %d messages in %ds, memory for %d countries", n, time.time() - started, len(hub.recent))
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        state["backfill"] = {"status": "skipped", "error": f"{type(exc).__name__}: {exc}"[:200]}
        log.warning("backfill skipped (%s: %s); the memory fills from live messages instead", type(exc).__name__, exc)
    finally:
        try:
            await consumer.stop()
        except Exception:
            pass


async def tick_loop() -> None:
    n = 0
    while True:
        await asyncio.sleep(1 / FLUSHES_PER_SECOND)
        hub.flush()
        n += 1
        if n % FLUSHES_PER_SECOND == 0:
            hub.tick()


@asynccontextmanager
async def lifespan(_: FastAPI):
    tasks = [asyncio.create_task(c()) for c in (names_loop, kafka_loop, tick_loop, backfill_loop)]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Routeboard live stream", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/live/health")
def health():
    from aiokafka.codec import has_lz4
    return {"status": "ok" if state["kafka"] == "connected" else "degraded", "kafka": state["kafka"],
            "clients": len(hub.clients), "names": state["names"], "messages": hub.total_messages,
            "bad_messages": state["bad_messages"], "last_error": state["last_error"], "lz4": has_lz4(),
            "backfill": state.get("backfill")}


async def stream(request: Request, country: str | None):
    q = hub.connect(country)
    if q is None:
        raise HTTPException(503, "too many viewers right now; try again shortly")

    async def body():
        try:
            yield b"retry: 3000\n\n"
            yield sse("hello", {"history": list(hub.history), "country": country, "up": hub.feed_up,
                              "recent": list(hub.recent[country]) if country else []})
            while True:
                try:
                    kind, payload = await asyncio.wait_for(q.get(), timeout=15)
                    yield sse(kind, payload)
                except asyncio.TimeoutError:
                    yield b": keep-alive\n\n"
                if await request.is_disconnected():
                    break
        finally:
            hub.disconnect(q)

    return StreamingResponse(body(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


@app.get("/live/stream")
async def live_stream(request: Request, country: str | None = Query(None, min_length=2, max_length=2)):
    if country is not None:
        country = country.upper()
        if not re.fullmatch(r"[A-Z]{2}", country):
            raise HTTPException(422, "country must be a two-letter code")
    return await stream(request, country)
