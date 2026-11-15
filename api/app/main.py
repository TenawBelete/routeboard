"""BGP Pipeline API: read-only JSON over the gold tables in Postgres.

Routes are grouped by page of the dashboard. Everything is cached for a few
seconds at the HTTP layer (Cache-Control) because the data changes once a
minute at most.
"""

import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
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
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.middleware("http")
async def cache_headers(request: Request, call_next):
    response: Response = await call_next(request)
    if request.method == "GET" and response.status_code == 200 and request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "public, max-age=5")
    return response


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
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "localhost")
    base = f"{request.headers.get('x-forwarded-proto', request.url.scheme)}://{host}"
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
