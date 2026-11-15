"""Every 5 minutes: find notable events in the KPI tables and record them.

Two kinds, both judged against the network's or the stream's own recent normal:

  burst  - a minute (or run of minutes) in which far more routes were closed
           than usual. Threshold: robust z-score on the last 24 h
           (median + 8 x MAD) and at least 4 x the median.
  surge  - one network whose routes changed at least 8 x more in the last hour
           than in its typical hour.

Events are upserted by (kind, start, network), so re-running is harmless.
"""

import json
import logging
from datetime import timedelta

from common import connect

log = logging.getLogger("events_job")
MIN_HISTORY_MINUTES = 120        # do not judge "unusual" on less history than this
BURST_FLOOR = 50                 # ignore tiny absolute numbers
SURGE_FLOOR, SURGE_TIMES = 1000, 8.0   # tuned on real traffic: 500 / 5x flagged half a dozen networks every hour


def group_minutes(rows, gap_minutes=2):
    """[(minute, value)] sorted by time -> [(start, end, peak)] joining minutes <= gap apart."""
    groups = []
    for t, v in rows:
        if groups and t - groups[-1][1] <= timedelta(minutes=gap_minutes):
            groups[-1][1] = t
            groups[-1][2] = max(groups[-1][2], v)
        else:
            groups.append([t, t, v])
    return [(a, b + timedelta(minutes=1), p) for a, b, p in groups]


def detect_bursts(conn) -> int:
    st = conn.execute("""
        with d as (select withdrawals as w from kpi_events_1m
                   where window_start >= now() - interval '24 hours' and window_start <= now() - interval '180 seconds'),
             m as (select percentile_cont(0.5) within group (order by w) as med, count(*) as n from d)
        select m.med, m.n, (select percentile_cont(0.5) within group (order by abs(w - m.med)) from d) as mad from m""").fetchone()
    med, n, mad = float(st[0] or 0), st[1], float(st[2] or 0)
    if n < MIN_HISTORY_MINUTES or med <= 0:
        return 0
    threshold = max(4 * med, med + 8 * 1.4826 * mad, BURST_FLOOR)
    rows = conn.execute("""select window_start, withdrawals from kpi_events_1m
                           where window_start >= now() - interval '180 minutes' and window_start <= now() - interval '180 seconds'
                             and withdrawals >= %s order by window_start""", (threshold,)).fetchall()
    found = 0
    edge = conn.execute("select now() - interval '120 minutes'").fetchone()[0]
    for start, end, peak in group_minutes(rows):
        if start < edge:
            continue                                 # too close to the look-back edge: its true start may be cut off
        times = peak / med
        reporters = conn.execute("""
            select peer_asn, sum(withdrawals) as w from kpi_peers_5m
            where window_start >= %s - interval '5 minutes' and window_start < %s
            group by peer_asn having sum(withdrawals) > 0 order by w desc limit 5""", (start, end)).fetchall()
        data = {"reporters": [{"asn": a, "withdrawals": int(w)} for a, w in reporters], "usual_per_minute": round(med)}
        conn.execute("""
            insert into events (kind, started_at, ended_at, severity, value, magnitude, data)
            values ('burst', %s, %s, %s, %s, %s, %s)
            on conflict (kind, started_at, (coalesce(asn, 0))) do update
              set ended_at = excluded.ended_at, severity = excluded.severity, value = excluded.value,
                  magnitude = excluded.magnitude, data = excluded.data""",
            (start, end, "alert" if times >= 8 else "watch", int(peak), times, json.dumps(data)))
        found += 1
    return found


def detect_surges(conn) -> int:
    rows = conn.execute("""
        with span as (select extract(epoch from (now() - interval '1 hour' - min(window_start))) / 3600.0 as h
                      from kpi_origins_5m where window_start >= now() - interval '24 hours'),
        h as (select origin_asn,
                     coalesce(sum(announcements) filter (where window_start >= now() - interval '1 hour'), 0) as last_h,
                     coalesce(sum(announcements) filter (where window_start <  now() - interval '1 hour'), 0) as before
              from kpi_origins_5m where window_start >= now() - interval '24 hours' group by 1)
        select h.origin_asn, h.last_h, h.before / span.h as usual
        from h cross join span
        where span.h >= 3 and h.last_h >= %s and h.last_h >= %s * greatest(h.before / span.h, 1)
          and not exists (select 1 from events e where e.kind = 'surge' and e.asn = h.origin_asn
                          and e.started_at >= now() - interval '6 hours')
        order by h.last_h desc limit 10""", (SURGE_FLOOR, SURGE_TIMES)).fetchall()
    for asn, last_h, usual in rows:
        times = float(last_h) / max(float(usual), 1.0)
        conn.execute("""
            insert into events (kind, started_at, ended_at, severity, value, magnitude, asn, data)
            values ('surge', date_trunc('minute', now()) - interval '1 hour', date_trunc('minute', now()), %s, %s, %s, %s, %s)
            on conflict do nothing""",
            ("alert" if times >= 20 else "watch", int(last_h), times, asn, json.dumps({"usual_per_hour": round(float(usual), 1)})))
    return len(rows)


def main() -> int:
    with connect() as conn:
        b, s = detect_bursts(conn), detect_surges(conn)
        conn.execute("""insert into job_runs (job, last_ok_at, last_run_at, detail) values ('events', now(), now(), %s)
                        on conflict (job) do update set last_ok_at = now(), last_run_at = now(), detail = excluded.detail""",
                     (f"{b} bursts in view, {s} new surges",))
        conn.commit()
    log.info("events: %d bursts in view, %d new surges", b, s)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        log.exception("events job failed")
        raise SystemExit(1)
