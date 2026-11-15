"""Daily: refresh network names and countries from the public RIPE NCC list.

If the download fails the existing names stay as they are; the job exits
non-zero so the runner logs it and tries again at the next slot.
"""

import logging
import os
import urllib.request

from common import connect
from names import parse_line

URL = os.environ.get("ASN_NAMES_URL", "https://ftp.ripe.net/ripe/asnames/asn.txt")
MIN_ROWS = int(os.environ.get("ASN_NAMES_MIN_ROWS", "50000"))   # refuse a truncated file
log = logging.getLogger("names_job")


def fetch(url: str = URL) -> list[tuple]:
    req = urllib.request.Request(url, headers={"User-Agent": "bgp-pipeline (portfolio project)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        text = r.read().decode("utf-8", errors="replace")
    rows = {}
    for line in text.splitlines():
        p = parse_line(line)
        if p:
            rows[p[0]] = p
    return list(rows.values())


def store(conn, rows: list[tuple]) -> None:
    with conn.cursor() as cur:
        cur.execute("create temp table _names (asn bigint, handle text, name text, country text) on commit drop")
        with cur.copy("copy _names (asn, handle, name, country) from stdin") as cp:
            for r in rows:
                cp.write_row(r)
        cur.execute("""insert into asn_names (asn, handle, name, country, updated_at)
                       select asn, handle, name, country, now() from _names
                       on conflict (asn) do update set handle = excluded.handle, name = excluded.name,
                                                       country = excluded.country, updated_at = now()""")
    conn.commit()


def main() -> int:
    rows = fetch()
    if len(rows) < MIN_ROWS:
        log.error("only %d names parsed (expected >= %d); keeping the existing table", len(rows), MIN_ROWS)
        return 1
    with connect() as conn:
        store(conn, rows)
        conn.execute("""insert into job_runs (job, last_ok_at, last_run_at, detail) values ('names', now(), now(), %s)
                        on conflict (job) do update set last_ok_at = now(), last_run_at = now(), detail = excluded.detail""",
                     (f"{len(rows)} names",))
        conn.commit()
    log.info("stored %d network names", len(rows))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        log.exception("names job failed")
        raise SystemExit(1)
