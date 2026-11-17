"""BGP Pipeline API: read-only JSON over the gold tables in Postgres.

Routes are grouped by page of the dashboard. Everything is cached for a few
seconds at the HTTP layer (Cache-Control) because the data changes once a
minute at most.
"""

import hmac
import json
import logging
import time
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from xml.sax.saxutils import escape

from . import db, queries
from .settings import settings

log = logging.getLogger("api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.pool.open(wait=True, timeout=30)
    log.info("db pool open")
    yield
    db.pool.close()


app = FastAPI(
    title="BGP Pipeline API",
    version="1.0.0",
    description="Live BGP routing KPIs, AS-graph metrics and withdrawal-risk model output.",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.api_docs else None,
    openapi_url="/api/openapi.json" if settings.api_docs else None,
    redoc_url=None,
)

# --- response cache -------------------------------------------------------------
# The data changes at most once a minute, so identical requests within CACHE_FRESH seconds get the same
# answer without touching the database. This is what stops a burst of visitors (or a bot) from turning
# into a burst of expensive queries. Answers are kept longer (CACHE_KEEP) only to fill the offline bundle.
CACHE_FRESH = 15
CACHE_KEEP = 900
CACHE_MAX = 1000
_cache: dict[str, tuple[float, bytes, str]] = {}
_UNCACHED = {"/api/offline-bundle"}


def _evict(now: float) -> None:
    if len(_cache) <= CACHE_MAX:
        return
    for k in [k for k, (t, _, _) in _cache.items() if now - t > CACHE_KEEP]:
        _cache.pop(k, None)
    if len(_cache) > CACHE_MAX:                      # still full: drop the oldest half
        for k, _ in sorted(_cache.items(), key=lambda kv: kv[1][0])[: len(_cache) // 2]:
            _cache.pop(k, None)


@app.middleware("http")
async def cache_and_headers(request: Request, call_next):
    path = request.url.path
    if request.method != "GET" or not path.startswith("/api/") or path in _UNCACHED:
        return await call_next(request)
    key = path + (f"?{request.url.query}" if request.url.query else "")
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < CACHE_FRESH:
        return Response(hit[1], media_type=hit[2], headers={"Cache-Control": "public, max-age=5"})
    response = await call_next(request)
    if response.status_code != 200:
        return response
    body = b"".join([chunk async for chunk in response.body_iterator])
    media = response.headers.get("content-type", "application/json")
    _cache[key] = (now, body, media)
    _evict(now)
    headers = {k: v for k, v in response.headers.items() if k.lower() not in ("content-length", "content-type")}
    headers.setdefault("cache-control", "public, max-age=5")
    return Response(body, status_code=200, media_type=media, headers=headers)


# Added after the cache so it wraps it: cached answers get CORS headers too.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse({"detail": "internal error"}, status_code=500)


# --- health -------------------------------------------------------------------

@app.get("/health", tags=["ops"])
def health():
    try:
        f = queries.freshness()
    except Exception as exc:  # database down
        return JSONResponse({"status": "down", "error": type(exc).__name__}, status_code=503)
    age = f.get("kpi_updated_age_seconds")
    status = "ok" if age is not None and age <= settings.freshness_warn_seconds else "degraded"
    return {"status": status, "freshness": f}


# --- live analytics ---------------------------------------------------------------

@app.get("/api/kpi/latest", tags=["live"])
def kpi_latest():
    row = queries.latest_kpi()
    if row is None:
        raise HTTPException(404, "no data yet")
    return row


@app.get("/api/kpi/timeline", tags=["live"])
def kpi_timeline(minutes: int = Query(120, ge=5, le=queries.MAX_TIMELINE_MINUTES)):
    return {"minutes": minutes, "points": queries.timeline(minutes)}


@app.get("/api/peers/top", tags=["live"])
def peers_top(limit: int = Query(10, ge=1, le=100), window_minutes: int = Query(60, ge=5, le=1440)):
    return {"window_minutes": window_minutes, "items": queries.top_peers(limit, window_minutes)}


@app.get("/api/origins/top", tags=["live"])
def origins_top(limit: int = Query(10, ge=1, le=100), window_minutes: int = Query(60, ge=5, le=1440)):
    return {"window_minutes": window_minutes, "items": queries.top_origins(limit, window_minutes)}


# --- lookup and briefing ------------------------------------------------------------

@app.get("/api/search", tags=["lookup"])
def search(q: str = Query(..., min_length=2, max_length=60), limit: int = Query(8, ge=1, le=20)):
    return {"items": queries.search(q, limit)}


@app.get("/api/network/{asn}", tags=["lookup"])
def network(asn: int):
    if not 0 < asn < 4294967296:
        raise HTTPException(422, "not a valid network number")
    return queries.network(asn)


@app.get("/api/briefing", tags=["lookup"])
def briefing():
    return queries.briefing()


@app.get("/api/countries", tags=["countries"])
def countries():
    return {"items": queries.countries()}


@app.get("/api/country/{cc}", tags=["countries"])
def country(cc: str):
    cc = cc.upper()
    if len(cc) != 2 or not cc.isalpha() or not cc.isascii():
        raise HTTPException(422, "country must be a two-letter code such as ER")
    return queries.country(cc)


@app.get("/api/events", tags=["events"])
def events(days: int = Query(7, ge=1, le=90), limit: int = Query(100, ge=1, le=500),
           kind: str | None = Query(None, pattern="^(burst|surge)$")):
    return {"days": days, "items": queries.events(days * 24, limit, kind)}


@app.get("/api/events.atom", tags=["events"])
def events_feed(request: Request):
    """Atom feed of recorded events, for feed readers and automations."""
    if settings.site_url:
        base = settings.site_url.rstrip("/")
    else:  # local development only; production sets SITE_URL so links never come from request headers
        base = f"{request.url.scheme}://{request.headers.get('host', 'localhost')}"
    base = escape(base, {'"': "&quot;"})
    items = queries.events(24 * 14, 40)
    updated = (items[0]["started_at"] if items else datetime.now(timezone.utc)).isoformat()
    entries = "".join(
        f"<entry><id>{base}/event/{e['id']}</id><title>{escape(e['title'])}</title>"
        f"<link href=\"{base}/event/{e['id']}\"/><updated>{e['started_at'].isoformat()}</updated>"
        f"<summary>{escape(e['detail'])}</summary></entry>" for e in items)
    # The stylesheet makes the feed readable when a person opens it in a browser; feed readers ignore it.
    xml = (f'<?xml version="1.0" encoding="utf-8"?><?xml-stylesheet type="text/xsl" href="/feed.xsl"?>'
           f'<feed xmlns="http://www.w3.org/2005/Atom">'
           f"<title>Routeboard: internet routing events</title><id>{base}/</id><link href=\"{base}/\"/>"
           f"<updated>{updated}</updated>{entries}</feed>")
    # application/xml (not atom+xml) so browsers apply the stylesheet instead of showing the source.
    return Response(xml, media_type="application/xml")


@app.get("/api/events/{event_id}", tags=["events"])
def event(event_id: int):
    e = queries.event(event_id)
    if e is None:
        raise HTTPException(404, "no such event")
    return e


@app.get("/api/status", tags=["ops"])
def status():
    stages = queries.status()
    worst = "stalled" if any(s["state"] == "stalled" for s in stages) else \
            "late" if any(s["state"] == "late" for s in stages) else "ok"
    return {"overall": worst, "stages": stages}


# --- graph ---------------------------------------------------------------------

@app.get("/api/graph/summary", tags=["graph"])
def graph_summary():
    run = queries.latest_graph_run()
    if run is None:
        raise HTTPException(404, "graph job has not run yet")
    return run


@app.get("/api/graph/nodes", tags=["graph"])
def graph_nodes(order_by: str = Query("pagerank", pattern="^(pagerank|hub)$"),
                limit: int = Query(20, ge=1, le=200)):
    run = queries.latest_graph_run()
    if run is None:
        raise HTTPException(404, "graph job has not run yet")
    return {"run": run, "items": queries.graph_nodes(run["run_id"], order_by, limit)}


@app.get("/api/graph/edges", tags=["graph"])
def graph_edges(limit: int = Query(50, ge=1, le=500), core: int = Query(0, ge=0, le=400)):
    """`core=N` returns links among the N most influential networks instead of the heaviest links overall."""
    run = queries.latest_graph_run()
    if run is None:
        raise HTTPException(404, "graph job has not run yet")
    items = queries.graph_core_edges(run["run_id"], core, limit) if core else queries.graph_edges(run["run_id"], limit)
    return {"run": run, "items": items}


# --- model ---------------------------------------------------------------------

@app.get("/api/model/summary", tags=["model"])
def model_summary():
    run = queries.latest_model_run()
    if run is None:
        raise HTTPException(404, "model job has not run yet")
    return run


@app.get("/api/model/history", tags=["model"])
def model_history(limit: int = Query(30, ge=1, le=200)):
    return {"items": queries.model_history(limit)}


@app.get("/api/model/predictions", tags=["model"])
def model_predictions(limit: int = Query(20, ge=1, le=200)):
    run = queries.latest_model_run()
    if run is None:
        raise HTTPException(404, "model job has not run yet")
    return {"run_id": run["run_id"], "trained_at": run["trained_at"],
            "items": queries.model_predictions(run["run_id"], limit)}


# --- offline bundle ------------------------------------------------------------------
# A Cloudflare Worker calls this every two minutes and keeps the answer. If this server stops, the
# website (hosted by Cloudflare) shows that saved data, clearly marked with the time it was saved,
# instead of an error page. The paths are exactly the ones the pages request, so the browser finds them.
OFFLINE_PATHS = [
    "/api/briefing", "/api/kpi/latest", "/api/kpi/timeline?minutes=60",
    "/api/peers/top?limit=10&window_minutes=60", "/api/origins/top?limit=10&window_minutes=60",
    "/api/graph/summary", "/api/graph/edges?core=70&limit=180", "/api/graph/edges?core=120&limit=320",
    "/api/graph/edges?limit=10", "/api/graph/nodes?order_by=pagerank&limit=15",
    "/api/events?days=7&limit=300", "/api/countries", "/api/country/US",
    "/api/model/summary", "/api/model/predictions?limit=12", "/api/network/15169",
]
OFFLINE_EXTRA_MAX = 250   # plus whatever visitors opened in the last 15 minutes (countries, networks, events)


@app.get("/api/offline-bundle", include_in_schema=False)
async def offline_bundle(x_offline_key: str = Header("")):
    if not settings.offline_key or not hmac.compare_digest(x_offline_key, settings.offline_key):
        raise HTTPException(404, "not found")
    import httpx
    out: dict[str, object] = {}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bundle") as client:
        for path in OFFLINE_PATHS:
            try:
                r = await client.get(path)
                if r.status_code == 200:
                    out[path] = r.json()
            except Exception as exc:
                log.warning("offline bundle: %s failed (%s)", path, type(exc).__name__)
    now = time.time()
    extra = 0
    for key, (t, body, media) in sorted(_cache.items(), key=lambda kv: -kv[1][0]):
        if extra >= OFFLINE_EXTRA_MAX:
            break
        # Never the status: a saved "everything works" must not be shown while the server is down.
        if key in out or key.startswith(("/api/search", "/api/status")) or now - t > CACHE_KEEP or not media.startswith("application/json"):
            continue
        out[key] = json.loads(body)
        extra += 1
    # Never stored by Cloudflare or anything else: it is only for the key holder, and must be fresh.
    return JSONResponse({"saved_at": int(now), "api": jsonable_encoder(out)}, headers={"Cache-Control": "no-store"})
