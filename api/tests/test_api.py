def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"                       # kpi updated seconds ago
    assert body["freshness"]["kpi_updated_age_seconds"] < 60


def test_kpi_latest_skips_current_minute(client):
    r = client.get("/api/kpi/latest")
    assert r.status_code == 200
    row = r.json()
    assert row["total_updates"] == 1056                          # g=3 row: newest minute that is 3+ minutes old
    assert row["withdraw_rate"] == round(row["withdrawals"] / row["total_updates"], 4)
    assert r.headers["cache-control"] == "public, max-age=5"


def test_timeline_bounds(client):
    assert client.get("/api/kpi/timeline?minutes=1").status_code == 422
    r = client.get("/api/kpi/timeline?minutes=20")
    pts = r.json()["points"]
    assert 15 <= len(pts) <= 20
    assert pts == sorted(pts, key=lambda p: p["window_start"])


def test_top_peers_aggregates_windows(client):
    items = client.get("/api/peers/top?limit=2&window_minutes=60").json()["items"]
    assert [i["peer_asn"] for i in items] == [3356, 3333]
    assert items[0]["updates"] == 6 * 335                # 6 windows summed


def test_top_origins(client):
    items = client.get("/api/origins/top?limit=3").json()["items"]
    assert len(items) == 3 and items[0]["announcements"] >= items[-1]["announcements"]


def test_graph_endpoints(client):
    assert client.get("/api/graph/summary").json()["n_nodes"] == 3
    pr = client.get("/api/graph/nodes?order_by=pagerank&limit=2").json()["items"]
    assert [n["asn"] for n in pr] == [3356, 174]
    assert client.get("/api/graph/nodes?order_by=evil").status_code == 422
    edges = client.get("/api/graph/edges").json()["items"]
    assert edges[0]["weight"] == 500


def test_model_endpoints(client):
    s = client.get("/api/model/summary").json()
    assert s["auc"] == 0.81 and "rate_t0" in s["features"]
    preds = client.get("/api/model/predictions").json()["items"]
    assert preds[0]["peer_asn"] == 3333 and preds[0]["predicted"] is True
    assert len(client.get("/api/model/history").json()["items"]) == 1


def test_read_only_session(client):
    """A bug in a handler must never be able to write. The DSN forces read-only."""
    from app import db
    import psycopg
    try:
        db.rows("insert into graph_runs (window_hours,n_nodes,n_edges,n_components,largest_component_share) values (1,1,1,1,1)")
        assert False, "write succeeded on a read-only session"
    except psycopg.errors.ReadOnlySqlTransaction:
        pass


def test_docs_served(client):
    assert client.get("/api/openapi.json").status_code == 200


def test_names_are_joined(client):
    items = client.get("/api/peers/top?limit=4").json()["items"]
    by = {i["peer_asn"]: i for i in items}
    assert by[3356]["name"] == "Lumen" and by[3356]["country"] == "US"
    edges = client.get("/api/graph/edges").json()["items"]
    assert edges[0]["src_name"] == "Cogent" and edges[0]["dst_name"] == "Lumen"


def test_search_by_name_number_and_garbage(client):
    assert client.get("/api/search?q=goog").json()["items"][0]["asn"] == 15169
    assert client.get("/api/search?q=AS3356").json()["items"][0]["name"] == "Lumen"
    assert client.get("/api/search?q=999999").json()["items"][0] == {"asn": 999999, "name": None, "country": None, "pagerank_rank": None}
    assert client.get("/api/search?q=%25%25").json()["items"] == []        # wildcards are escaped
    assert client.get("/api/search?q=x").status_code == 422


def test_network_profile(client):
    n = client.get("/api/network/3356").json()
    assert n["name"] == "Lumen" and n["seen"] is True
    assert n["graph"]["pagerank_rank"] == 1 and n["graph"]["n_nodes"] == 3
    assert [u["asn"] for u in n["upstream"]] == [174] and [d["asn"] for d in n["downstream"]] == [15169]
    assert n["peer"]["updates"] == 6 * 335
    unknown = client.get("/api/network/64999").json()
    assert unknown["seen"] is False and unknown["name"] is None
    assert client.get("/api/network/0").status_code == 422


def test_briefing_reads_like_sentences(client):
    b = client.get("/api/briefing").json()
    assert b["state"]["level"] in {"calm", "normal", "busy", "turbulent"}
    kinds = [i["kind"] for i in b["items"]]
    assert kinds[:2] == ["burst", "surge"] and "forecast" in kinds      # recorded events first, newest first
    assert all(i["at"] for i in b["items"][:2])                         # every event row carries its time
    assert b["items"][0]["event_id"] and b["items"][1]["title"] == "Google was far busier than usual"
    assert all(i["title"] and i["detail"] for i in b["items"])
    assert b["countries"][0]["country"] == "US" and 0 < b["countries"][0]["share"] <= 1


def test_core_edges_stay_inside_the_top_networks(client):
    core = client.get("/api/graph/edges?core=2&limit=50").json()["items"]
    assert [(e["src"], e["dst"]) for e in core] == [(174, 3356)]       # 15169 is rank 3, so its link is left out


def test_events_list_detail_and_feed(client):
    week = client.get("/api/events").json()["items"]
    assert [e["kind"] for e in week] == ["burst", "surge", "surge"]     # the 9-day-old one is outside 7 days
    assert len(client.get("/api/events?days=30").json()["items"]) == 4
    assert [e["kind"] for e in client.get("/api/events?kind=surge").json()["items"]] == ["surge", "surge"]
    assert client.get("/api/events?kind=drop%20table").status_code == 422
    b = client.get(f"/api/events/{week[0]['id']}").json()
    assert "lasted about 3 minutes" in b["detail"] and len(b["series"]) > 10
    assert b["reporters"][0]["name"] == "Arelion" and b["reporters"][1]["name"] is None
    assert client.get("/api/events/999999").status_code == 404
    feed = client.get("/api/events.atom", headers={"host": "bgp.example.com", "x-forwarded-proto": "https"})
    assert feed.headers["content-type"].startswith("application/xml") and "/feed.xsl" in feed.text
    assert f"https://bgp.example.com/event/{week[0]['id']}" in feed.text and "<feed" in feed.text
    import xml.etree.ElementTree as ET
    ET.fromstring(feed.text)                                            # well-formed XML


def test_status_reports_every_stage(client):
    s = client.get("/api/status").json()
    by = {x["key"]: x for x in s["stages"]}
    assert set(by) == {"feed", "stream", "events", "graph", "model", "names"}
    assert by["events"]["state"] == "ok" and by["names"]["state"] == "ok"
    assert s["overall"] in {"ok", "late", "stalled"}


def test_week_timeline_is_hourly(client):
    pts = client.get("/api/kpi/timeline?minutes=10080").json()["points"]
    assert 1 <= len(pts) <= 2 and "peak_withdrawals" in pts[0]         # 30 minutes of seed data -> 1-2 hourly buckets


def test_country_shows_who_it_depends_on(client):
    c = client.get("/api/country/er").json()                               # lower case is accepted
    assert c["country"] == "ER" and c["seen"] and c["networks_total"] == 2
    assert [(u["country"], round(u["share"], 2)) for u in c["upstream_countries"]] == [("SE", 0.9), ("US", 0.1)]
    assert c["upstream_networks"][0]["name"] == "Arelion"
    d = c["dependence"]
    assert d["upstream_networks"] == 2 and d["upstream_countries"] == 2 and round(d["top_share"], 2) == 0.9 and d["top_name"] == "Arelion"
    assert c["domestic_links"] == 1 and c["downstream_countries"] == []
    assert c["routes_observed"] == 100 and c["enough_data"] is True and c["window_days"] == 7     # the 10-day-old link is ignored
    tiny = client.get("/api/country/TV").json()
    assert tiny["routes_observed"] == 2 and tiny["enough_data"] is False                          # too little to quote percentages
    assert c["changes_last_hour"] == 6 and len(c["activity"]) == 6
    assert c["events"][0]["title"] == "EriTel was far busier than usual"
    empty = client.get("/api/country/ZZ").json()
    assert empty["seen"] is False and empty["upstream_countries"] == [] and empty["dependence"]["top_share"] is None
    for bad in ["ERI", "E", "1x", "%C3%A9r"]:
        assert client.get(f"/api/country/{bad}").status_code == 422


def test_countries_list(client):
    items = client.get("/api/countries").json()["items"]
    by = {i["country"]: i for i in items}
    assert by["ER"]["networks"] == 2 and by["ER"]["changes_last_hour"] == 6 and by["US"]["networks"] == 3
