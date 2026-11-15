"""All SQL in one place. Each function returns plain dicts/lists ready for JSON."""

from datetime import datetime, timedelta, timezone

from . import db

MAX_TIMELINE_MINUTES = 7 * 24 * 60


def latest_kpi() -> dict | None:
    # The newest minute is still filling up, so "latest" is the newest minute
    # that is at least 3 minutes old (late messages keep arriving for a while). That makes the headline numbers stable.
    return db.one("""
        select window_start, announcements, withdrawals, total_updates,
               case when total_updates > 0
                    then round(withdrawals::numeric / total_updates, 4) else 0 end as withdraw_rate,
               updated_at
        from kpi_events_1m
        where window_start <= now() - interval '180 seconds'
        order by window_start desc limit 1""")


def timeline(minutes: int) -> list[dict]:
    minutes = max(5, min(minutes, MAX_TIMELINE_MINUTES))
    if minutes > 1440:      # days: hourly averages per minute, so the scale matches the short views
        return db.rows("""
            select date_trunc('hour', window_start) as window_start,
                   round(avg(announcements))::bigint as announcements, round(avg(withdrawals))::bigint as withdrawals,
                   round(avg(total_updates))::bigint as total_updates, max(withdrawals) as peak_withdrawals
            from kpi_events_1m
            where window_start >= now() - make_interval(mins => %s) and window_start <= now() - interval '180 seconds'
            group by 1 order by 1""", (minutes,))
    return db.rows("""
        select window_start, announcements, withdrawals, total_updates
        from kpi_events_1m
        where window_start >= now() - make_interval(mins => %s)
        order by window_start""", (minutes,))


def top_peers(limit: int, window_minutes: int) -> list[dict]:
    return db.rows("""
        select t.*, n.name, n.country from (
          select peer_asn, sum(updates) as updates, sum(withdrawals) as withdrawals,
                 case when sum(updates) > 0
                      then round(sum(withdrawals)::numeric / sum(updates), 4) else 0 end as withdraw_rate
          from kpi_peers_5m
          where window_start >= now() - make_interval(mins => %s)
          group by peer_asn order by updates desc limit %s) t
        left join asn_names n on n.asn = t.peer_asn order by t.updates desc""", (window_minutes, limit))


def top_origins(limit: int, window_minutes: int) -> list[dict]:
    return db.rows("""
        select t.*, n.name, n.country from (
          select origin_asn, sum(announcements) as announcements
          from kpi_origins_5m
          where window_start >= now() - make_interval(mins => %s)
          group by origin_asn order by announcements desc limit %s) t
        left join asn_names n on n.asn = t.origin_asn order by t.announcements desc""", (window_minutes, limit))


def latest_graph_run() -> dict | None:
    return db.one("select * from graph_runs order by computed_at desc limit 1")


def graph_nodes(run_id: int, order_by: str, limit: int) -> list[dict]:
    col = {"pagerank": "pagerank_rank", "hub": "hub_rank"}[order_by]   # whitelist
    return db.rows(f"""
        select g.asn, g.pagerank, g.in_degree, g.out_degree, g.hub_score, g.pagerank_rank, g.hub_rank,
               n.name, n.country
        from graph_nodes g left join asn_names n on n.asn = g.asn
        where g.run_id = %s order by g.{col} limit %s""", (run_id, limit))


def graph_core_edges(run_id: int, nodes: int, limit: int) -> list[dict]:
    """Links among the most influential networks: a connected picture of the core."""
    return db.rows("""
        with top as (select asn from graph_nodes where run_id = %s order by pagerank_rank limit %s)
        select e.src, e.dst, e.weight, a.name as src_name, b.name as dst_name
        from (select src, dst, weight from graph_edges_top
              where run_id = %s and src in (select asn from top) and dst in (select asn from top)
              order by weight desc limit %s) e
        left join asn_names a on a.asn = e.src left join asn_names b on b.asn = e.dst
        order by e.weight desc""", (run_id, nodes, run_id, limit))


def graph_edges(run_id: int, limit: int) -> list[dict]:
    return db.rows("""
        select e.src, e.dst, e.weight, a.name as src_name, b.name as dst_name
        from (select src, dst, weight from graph_edges_top
              where run_id = %s order by weight desc limit %s) e
        left join asn_names a on a.asn = e.src left join asn_names b on b.asn = e.dst
        order by e.weight desc""", (run_id, limit))


def latest_model_run() -> dict | None:
    return db.one("select * from model_runs order by trained_at desc limit 1")


def model_history(limit: int) -> list[dict]:
    return db.rows("""
        select run_id, trained_at, n_train, n_test, positive_rate, auc, precision_, recall, f1, baseline_auc
        from model_runs order by trained_at desc limit %s""", (limit,))


def model_predictions(run_id: int, limit: int) -> list[dict]:
    return db.rows("""
        select p.window_start, p.peer_asn, p.probability, p.predicted, p.actual, n.name, n.country
        from model_predictions p left join asn_names n on n.asn = p.peer_asn
        where p.run_id = %s order by p.probability desc limit %s""", (run_id, limit))


# --- lookup ---------------------------------------------------------------------

def _like(q: str) -> str:
    return q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search(q: str, limit: int) -> list[dict]:
    q = q.strip()
    digits = q.upper().removeprefix("AS").strip()
    asn = int(digits) if digits.isdigit() and len(digits) <= 10 else -1
    like = _like(q)
    found = db.rows("""
        select n.asn, n.name, n.country, g.pagerank_rank
        from asn_names n
        left join graph_nodes g on g.asn = n.asn and g.run_id = (select max(run_id) from graph_runs)
        where n.asn = %s or lower(n.name) like %s or lower(n.handle) like %s
        order by (n.asn = %s) desc, (lower(n.name) like %s) desc, g.pagerank_rank nulls last, n.asn
        limit %s""", (asn, f"%{like}%", f"{like}%", asn, f"{like}%", limit))
    if asn > 0 and not any(r["asn"] == asn for r in found):
        found.insert(0, {"asn": asn, "name": None, "country": None, "pagerank_rank": None})
    return found[:limit]


def network(asn: int) -> dict:
    ident = db.one("select asn, handle, name, country from asn_names where asn = %s", (asn,)) or \
        {"asn": asn, "handle": None, "name": None, "country": None}
    run = latest_graph_run()
    graph, upstream, downstream = None, [], []
    if run:
        graph = db.one("""select pagerank, pagerank_rank, hub_rank, in_degree, out_degree, hub_score
                          from graph_nodes where run_id = %s and asn = %s""", (run["run_id"], asn))
        # A link src -> dst means: routes that belong behind dst were passed on by src.
        upstream = db.rows("""select e.src as asn, e.weight, n.name, n.country from graph_edges_top e
                              left join asn_names n on n.asn = e.src
                              where e.run_id = %s and e.dst = %s order by e.weight desc limit 8""", (run["run_id"], asn))
        downstream = db.rows("""select e.dst as asn, e.weight, n.name, n.country from graph_edges_top e
                                left join asn_names n on n.asn = e.dst
                                where e.run_id = %s and e.src = %s order by e.weight desc limit 8""", (run["run_id"], asn))
    activity = db.rows("""select window_start, announcements from kpi_origins_5m
                          where origin_asn = %s and window_start >= now() - interval '24 hours'
                          order by window_start""", (asn,))
    peer = db.one("""select sum(updates) as updates, sum(withdrawals) as withdrawals from kpi_peers_5m
                     where peer_asn = %s and window_start >= now() - interval '24 hours'""", (asn,))
    usual = db.one("""
        select coalesce(sum(announcements) filter (where window_start >= now() - interval '1 hour'), 0) as last_hour,
               coalesce(sum(announcements) filter (where window_start < now() - interval '1 hour'), 0) as before,
               greatest(extract(epoch from (now() - interval '1 hour' - min(window_start))) / 3600.0, 1) as hours_before
        from kpi_origins_5m where origin_asn = %s and window_start >= now() - interval '24 hours'""", (asn,))
    risk = db.one("""select p.probability, p.window_start, p.actual from model_predictions p
                     where p.peer_asn = %s and p.run_id = (select max(run_id) from model_runs)
                     order by p.window_start desc limit 1""", (asn,))
    last_hour = int(usual["last_hour"] or 0)
    per_hour = float(usual["before"] or 0) / float(usual["hours_before"] or 1)
    ratio = (last_hour / per_hour) if per_hour >= 1 else None
    return {
        "asn": asn, "name": ident["name"], "handle": ident["handle"], "country": ident["country"],
        "seen": bool(graph or activity or (peer and peer["updates"])),
        "graph": dict(graph, n_nodes=run["n_nodes"], computed_at=run["computed_at"], window_hours=run["window_hours"]) if graph else None,
        "upstream": upstream, "downstream": downstream,
        "activity": activity,
        "announcements_last_hour": last_hour, "announcements_usual_per_hour": round(per_hour, 1), "activity_ratio": ratio,
        "peer": {"updates": int(peer["updates"]), "withdrawals": int(peer["withdrawals"] or 0)} if peer and peer["updates"] else None,
        "risk": risk,
    }


COUNTRY_WINDOW_DAYS = 7
MIN_ROUTES_FOR_SHARES = 30     # below this many observed routes, percentages would be noise


# --- countries -----------------------------------------------------------------

def countries() -> list[dict]:
    """Every country with at least one network on today's map, with its share of recent activity."""
    run = latest_graph_run()
    return db.rows("""
        with seen as (select n.country, count(*) as networks from graph_nodes g join asn_names n on n.asn = g.asn
                      where g.run_id = %s and n.country is not null group by 1),
             act as (select n.country, sum(k.announcements) as changes from kpi_origins_5m k join asn_names n on n.asn = k.origin_asn
                     where k.window_start >= now() - interval '1 hour' and n.country is not null group by 1)
        select coalesce(seen.country, act.country) as country, coalesce(seen.networks, 0) as networks,
               coalesce(act.changes, 0) as changes_last_hour
        from seen full join act on act.country = seen.country
        order by networks desc, changes_last_hour desc""", (run["run_id"] if run else -1,))


def country(cc: str) -> dict:
    """How one country's networks connect to the rest of the world, from the latest map."""
    run = latest_graph_run()
    rid = run["run_id"] if run else -1
    # A link src -> dst means src passed on routes that belong behind dst. So for links that
    # END in the country, the foreign src is a network the country reaches the world through.
    links = db.rows("""
        select e.src, e.dst, e.weight, a.country as sc, b.country as dc, a.name as sn, b.name as dn
        from graph_edges_seen e join asn_names a on a.asn = e.src join asn_names b on b.asn = e.dst
        where e.last_seen >= now() - make_interval(days => %s) and (a.country = %s or b.country = %s)""",
                    (COUNTRY_WINDOW_DAYS, cc, cc))
    inbound = [l for l in links if l["dc"] == cc and l["sc"] != cc and l["sc"]]
    outbound = [l for l in links if l["sc"] == cc and l["dc"] != cc and l["dc"]]

    def by_country(rows, key):
        agg: dict[str, dict] = {}
        for l in rows:
            a = agg.setdefault(l[key], {"country": l[key], "weight": 0, "networks": set()})
            a["weight"] += int(l["weight"]); a["networks"].add(l["src"] if key == "sc" else l["dst"])
        total = sum(a["weight"] for a in agg.values()) or 1
        return sorted(({"country": a["country"], "weight": a["weight"], "share": a["weight"] / total,
                        "networks": len(a["networks"])} for a in agg.values()), key=lambda x: -x["weight"])

    def by_network(rows, asn_key, name_key, cc_key):
        agg: dict[int, dict] = {}
        for l in rows:
            a = agg.setdefault(l[asn_key], {"asn": l[asn_key], "name": l[name_key], "country": l[cc_key], "weight": 0})
            a["weight"] += int(l["weight"])
        total = sum(a["weight"] for a in agg.values()) or 1
        out = sorted(agg.values(), key=lambda x: -x["weight"])
        for a in out:
            a["share"] = a["weight"] / total
        return out

    up_networks = by_network(inbound, "src", "sn", "sc")
    nets = db.rows("""select g.asn, n.name, g.pagerank_rank, g.hub_score from graph_nodes g join asn_names n on n.asn = g.asn
                      where g.run_id = %s and n.country = %s order by g.pagerank_rank limit 12""", (rid, cc))
    total = db.one("""select count(*) as n from graph_nodes g join asn_names n on n.asn = g.asn
                      where g.run_id = %s and n.country = %s""", (rid, cc))["n"]
    activity = db.rows("""select k.window_start, sum(k.announcements) as announcements
                          from kpi_origins_5m k join asn_names n on n.asn = k.origin_asn
                          where n.country = %s and k.window_start >= now() - interval '24 hours'
                          group by 1 order by 1""", (cc,))
    usual = db.one("""
        select coalesce(sum(k.announcements) filter (where k.window_start >= now() - interval '1 hour'), 0) as last_hour,
               coalesce(sum(k.announcements) filter (where k.window_start < now() - interval '1 hour'), 0) as before,
               greatest(extract(epoch from (now() - interval '1 hour' - min(k.window_start))) / 3600.0, 1) as hours_before
        from kpi_origins_5m k join asn_names n on n.asn = k.origin_asn
        where n.country = %s and k.window_start >= now() - interval '24 hours'""", (cc,))
    last_hour = int(usual["last_hour"] or 0)
    per_hour = float(usual["before"] or 0) / float(usual["hours_before"] or 1)
    evs = db.rows(f"""select {_EVENT_COLS} from events e join asn_names n on n.asn = e.asn
                      where n.country = %s and e.started_at >= now() - interval '7 days'
                      order by e.started_at desc limit 20""", (cc,))
    return {
        "country": cc, "seen": bool(total or activity),
        "networks_total": total, "networks": nets,
        "upstream_countries": by_country(inbound, "sc")[:12], "upstream_networks": up_networks[:10],
        "downstream_countries": by_country(outbound, "dc")[:12],
        "domestic_links": sum(1 for l in links if l["sc"] == cc and l["dc"] == cc),
        "routes_observed": sum(int(l["weight"]) for l in inbound), "window_days": COUNTRY_WINDOW_DAYS,
        "enough_data": sum(int(l["weight"]) for l in inbound) >= MIN_ROUTES_FOR_SHARES,
        "dependence": {"upstream_networks": len(up_networks), "upstream_countries": len({l["sc"] for l in inbound}),
                       "top_share": up_networks[0]["share"] if up_networks else None,
                       "top_name": (up_networks[0]["name"] or f"AS{up_networks[0]['asn']}") if up_networks else None,
                       "top_asn": up_networks[0]["asn"] if up_networks else None},
        "activity": activity, "changes_last_hour": last_hour, "changes_usual_per_hour": round(per_hour, 1),
        "activity_ratio": (last_hour / per_hour) if per_hour >= 1 else None,
        "events": [_describe(e) for e in evs],
        "computed_at": run["computed_at"] if run else None, "window_hours": run["window_hours"] if run else None,
    }


# --- events -------------------------------------------------------------------

def _describe(e: dict) -> dict:
    """Facts -> the sentence shown on the site."""
    who = e.get("name") or (f"An unnamed network (AS{e['asn']})" if e.get("asn") else None)
    mins = max(1, round((e["ended_at"] - e["started_at"]).total_seconds() / 60))
    if e["kind"] == "burst":
        e["title"] = "A burst of routes closed at once"
        e["detail"] = (f"{e['value']:,} routes closed in a single minute, {e['magnitude']:.1f} times the usual."
                       + (f" The burst lasted about {mins} minutes." if mins > 1 else ""))
    else:
        e["title"] = f"{who} was far busier than usual"
        e["detail"] = f"{e['value']:,} route changes in one hour, {e['magnitude']:.0f} times its usual."
    return e


_EVENT_COLS = """e.id, e.kind, e.started_at, e.ended_at, e.severity, e.value, e.magnitude, e.asn, e.data,
                 n.name, n.country"""


def events(hours: int, limit: int, kind: str | None = None) -> list[dict]:
    rows = db.rows(f"""
        select {_EVENT_COLS} from events e left join asn_names n on n.asn = e.asn
        where e.started_at >= now() - make_interval(hours => %s) and (%s::text is null or e.kind = %s)
        order by e.started_at desc limit %s""", (hours, kind, kind, limit))
    return [_describe(r) for r in rows]


def event(event_id: int) -> dict | None:
    e = db.one(f"select {_EVENT_COLS} from events e left join asn_names n on n.asn = e.asn where e.id = %s", (event_id,))
    if e is None:
        return None
    _describe(e)
    if e["kind"] == "burst":
        e["series"] = db.rows("""select window_start, withdrawals as value from kpi_events_1m
                                 where window_start between %s - interval '45 minutes' and %s + interval '45 minutes'
                                 order by window_start""", (e["started_at"], e["ended_at"]))
        ids = [r["asn"] for r in e["data"].get("reporters", [])]
        names = {r["asn"]: r for r in db.rows("select asn, name, country from asn_names where asn = any(%s)", (ids,))} if ids else {}
        e["reporters"] = [dict(r, name=names.get(r["asn"], {}).get("name"), country=names.get(r["asn"], {}).get("country"))
                          for r in e["data"].get("reporters", [])]
    else:
        e["series"] = db.rows("""select window_start, announcements as value from kpi_origins_5m
                                 where origin_asn = %s and window_start between %s - interval '6 hours' and %s + interval '2 hours'
                                 order by window_start""", (e["asn"], e["started_at"], e["ended_at"]))
        e["reporters"] = []
    return e


def status() -> list[dict]:
    """One row per stage of the pipeline: when it last produced something."""
    r = db.one("""
        select (select max(window_start) from kpi_events_1m)                 as newest_minute,
               (select max(updated_at) from kpi_events_1m)                   as stream_write,
               (select max(computed_at) from graph_runs)                     as graph,
               (select max(trained_at) from model_runs)                      as model,
               (select last_ok_at from job_runs where job = 'events')        as events,
               (select last_ok_at from job_runs where job = 'names')         as names,
               (select count(*) from asn_names)                              as n_names,
               (select count(*) from events where started_at >= now() - interval '7 days') as n_events""")
    now = datetime.now(timezone.utc)
    age = lambda t: (now - t).total_seconds() if t else None
    def row(key, label, what, t, ok_s, warn_s, extra=None):
        a = age(t)
        state = "waiting" if a is None else "ok" if a <= ok_s else "late" if a <= warn_s else "stalled"
        return {"key": key, "label": label, "what": what, "last": t, "age_seconds": a, "state": state, "extra": extra}
    return [
        row("feed", "Live feed", "Newest minute of routing messages received", r["newest_minute"], 240, 900),
        row("stream", "Stream processing", "Last batch written by the stream processor", r["stream_write"], 180, 900),
        row("events", "Event detection", "Looks for bursts and surges every 5 minutes", r["events"], 600, 1800, f"{r['n_events']} events in the last 7 days"),
        row("graph", "Network map", "Recalculated every hour", r["graph"], 2 * 3600, 6 * 3600),
        row("model", "Forecast model", "Retrained every 6 hours", r["model"], 8 * 3600, 24 * 3600),
        row("names", "Network names", "Refreshed daily from the public registry", r["names"], 30 * 3600, 72 * 3600, f"{r['n_names']:,} names"),
    ]


# --- briefing -------------------------------------------------------------------

def briefing() -> dict:
    """Plain-language summary of what the routing system is doing right now."""
    base = db.one("""
        with d as (select * from kpi_events_1m where window_start >= now() - interval '24 hours'
                   and window_start <= now() - interval '180 seconds')
        select (select percentile_cont(0.5) within group (order by total_updates) from d) as usual_total,
               (select percentile_cont(0.5) within group (order by withdrawals) from d)   as usual_withdrawn,
               (select avg(total_updates) from (select total_updates from d order by window_start desc limit 10) x) as recent_total,
               (select count(*) from d) as minutes""")
    if not base or not base["minutes"]:
        return {"state": None, "items": [], "countries": []}
    usual, recent = float(base["usual_total"] or 0), float(base["recent_total"] or 0)
    ratio = recent / usual if usual > 0 else 1.0
    recent_w = db.one("""select avg(withdrawals) as w from (select withdrawals from kpi_events_1m
                         where window_start <= now() - interval '180 seconds' order by window_start desc limit 10) x""")["w"]
    w_ratio = float(recent_w or 0) / float(base["usual_withdrawn"]) if base["usual_withdrawn"] else 1.0
    # "Turbulent" is reserved for routes disappearing; a lot of routes opening is only busy.
    level, label = ("turbulent", "Unusually turbulent") if w_ratio >= 3 and ratio >= 1.5 else \
                   ("calm", "Quieter than usual") if ratio < 0.7 else ("normal", "A normal day so far") if ratio <= 1.5 else \
                   ("busy", "Busier than usual") if ratio <= 3 else ("busy", "Much busier than usual")
    items: list[dict] = []

    recent_events = events(hours=6, limit=60)
    bursts = [e for e in recent_events if e["kind"] == "burst"][:3]
    surges = sorted((e for e in recent_events if e["kind"] == "surge"), key=lambda e: -e["magnitude"])[:3]   # the three most extreme, not all
    for e in sorted(bursts + surges, key=lambda e: e["started_at"] if e["kind"] == "burst" else e["ended_at"], reverse=True):
        items.append({"kind": e["kind"], "tone": e["severity"], "at": e["started_at"] if e["kind"] == "burst" else e["ended_at"],
                      "asn": e["asn"], "event_id": e["id"], "title": e["title"], "detail": e["detail"]})
    total_hour = db.one("select coalesce(sum(announcements), 0) as n from kpi_origins_5m where window_start >= now() - interval '1 hour'")["n"]
    top = db.one("""select t.asn, t.n, n.name from (select origin_asn as asn, sum(announcements) as n from kpi_origins_5m
                    where window_start >= now() - interval '1 hour' group by 1 order by 2 desc limit 1) t
                    left join asn_names n on n.asn = t.asn""")
    if top and total_hour and not any(i["asn"] == top["asn"] for i in items):
        share = float(top["n"]) / float(total_hour)
        if share >= 0.05:
            items.append({"kind": "share", "tone": "info", "at": None, "asn": top["asn"], "event_id": None,
                          "title": f"{top['name'] or 'AS' + str(top['asn'])} is changing routes the most",
                          "detail": f"It accounts for {share:.0%} of all route changes in the last hour."})
    risk = db.one("""select p.peer_asn as asn, p.probability, n.name from model_predictions p
                     left join asn_names n on n.asn = p.peer_asn
                     where p.run_id = (select max(run_id) from model_runs) order by p.probability desc limit 1""")
    if risk:
        items.append({"kind": "forecast", "tone": "info", "at": None, "asn": risk["asn"], "event_id": None,
                      "title": f"Forecast to watch: {risk['name'] or 'AS' + str(risk['asn'])}",
                      "detail": f"Highest risk score in the latest forecast, {round(risk['probability'] * 100)} out of 100."})

    countries = db.rows("""
        select n.country, sum(k.announcements) as announcements, count(distinct k.origin_asn) as networks
        from kpi_origins_5m k join asn_names n on n.asn = k.origin_asn
        where k.window_start >= now() - interval '1 hour' and n.country is not null
        group by n.country order by 2 desc limit 8""")
    for c in countries:
        c["share"] = float(c["announcements"]) / float(total_hour) if total_hour else 0.0
    return {"state": {"level": level, "label": label, "ratio": round(ratio, 2),
                      "recent_per_minute": round(recent), "usual_per_minute": round(usual)},
            "items": items, "countries": countries}


def freshness() -> dict:
    """How old the newest data is, per table. Drives /health."""
    r = db.one("""
        select
          (select max(updated_at) from kpi_events_1m)  as kpi_updated_at,
          (select max(computed_at) from graph_runs)    as graph_computed_at,
          (select max(trained_at) from model_runs)     as model_trained_at""")
    now = datetime.now(timezone.utc)
    out = {}
    for k, v in (r or {}).items():
        out[k] = v
        out[k.rsplit("_", 1)[0] + "_age_seconds"] = (now - v).total_seconds() if v else None
    return out
