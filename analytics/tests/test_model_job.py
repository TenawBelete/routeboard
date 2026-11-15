"""End-to-end: synthetic peers in a real PostgreSQL -> model_job.main() -> rows."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
def _find_pgbin():
    """Newest PostgreSQL on this machine: Linux packages, Homebrew, or PATH."""
    import glob
    import shutil as _sh

    def ver(p):
        v = p.split("/")[4]
        return int(v) if v.isdigit() else 0
    cands = sorted(glob.glob("/usr/lib/postgresql/*/bin"), key=ver)
    cands += sorted(glob.glob("/opt/homebrew/opt/postgresql@*/bin"))
    cands += glob.glob("/opt/homebrew/opt/postgresql/bin")
    for p in reversed(cands):
        if Path(p, "initdb").exists():
            return Path(p)
    found = _sh.which("initdb")
    return Path(found).parent if found else None


def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return str(s.getsockname()[1])


PGBIN = _find_pgbin()
PORT = _free_port()


@pytest.fixture(scope="module")
def pg():
    if PGBIN is None:
        pytest.fail("PostgreSQL (initdb) not found; install postgresql to run these tests")
    d = Path(tempfile.mkdtemp(prefix="pgml-")); sock = d / "sock"; sock.mkdir()
    su = []
    if os.geteuid() == 0:
        shutil.chown(d, "postgres"); shutil.chown(sock, "postgres"); su = ["runuser", "-u", "postgres", "--"]
    run = lambda c: subprocess.run(c, check=True, capture_output=True, text=True)
    run(su + [str(PGBIN / "initdb"), "-D", str(d / "data"), "-U", "postgres", "-A", "trust", "-E", "UTF8", "--locale=C"])
    run(su + [str(PGBIN / "pg_ctl"), "-D", str(d / "data"), "-o", f"-p {PORT} -k {sock}", "-l", str(d / "log"), "start", "-w"])
    psql = su + [str(PGBIN / "psql"), "-h", str(sock), "-p", PORT, "-U", "postgres", "-v", "ON_ERROR_STOP=1", "-q"]
    run(psql + ["-d", "postgres", "-c", "create database bgp"])
    for f in sorted((ROOT / "postgres/init").glob("*.sql")):
        run(psql + ["-d", "bgp", "-f", str(f)])
    os.environ.update(POSTGRES_HOST=str(sock), POSTGRES_PORT=PORT, POSTGRES_DB="bgp",
                      POSTGRES_USER="postgres", POSTGRES_PASSWORD="x", MODEL_MIN_ROWS="200")
    yield
    subprocess.run(su + [str(PGBIN / "pg_ctl"), "-D", str(d / "data"), "stop", "-m", "immediate"], capture_output=True)
    shutil.rmtree(d, ignore_errors=True)


def seed(conn, n_peers=20, n_windows=600, seed=7):
    """Peers whose withdrawal rate is autocorrelated, so there IS a learnable signal."""
    rng = np.random.default_rng(seed)
    rows = []
    for p in range(n_peers):
        rate = 0.05
        for w in range(n_windows):
            rate = float(np.clip(0.7 * rate + 0.3 * rng.beta(1, 8) + (0.4 if rng.random() < 0.03 else 0), 0, 1))
            upd = int(rng.integers(20, 200))
            rows.append((w, 1000 + p, upd, int(round(rate * upd))))
    with conn.cursor() as cur:
        cur.executemany("""insert into kpi_peers_5m (window_start, peer_asn, updates, withdrawals)
                           values (now() - interval '2 days' + %s * interval '5 minutes', %s, %s, %s)""", rows)
    conn.commit()


def test_model_job_end_to_end(pg):
    sys.path.insert(0, str(ROOT / "analytics"))
    import model_job
    from common import connect
    with connect() as conn:
        seed(conn)
    assert model_job.main() == 0
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select n_train, n_test, auc, positive_rate, test_from > train_to from model_runs")
        n_train, n_test, auc, pos, chronological = cur.fetchone()
        assert n_train > n_test > 0 and chronological
        assert 0 < pos < 1
        assert auc is not None and auc > 0.6          # autocorrelated signal must be learnable
        cur.execute("select count(*), max(probability) from model_predictions")
        n_pred, pmax = cur.fetchone()
        assert n_pred == 20 and 0 <= pmax <= 1       # one prediction per peer, newest window

    # Second run: must fill `actual` for predictions whose next window now exists... it does not yet
    # (the newest window has no successor), so actual stays null; then add a window and re-run.
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""insert into kpi_peers_5m (window_start, peer_asn, updates, withdrawals)
                       select max(window_start) + interval '5 minutes', peer_asn, 100, 50
                       from kpi_peers_5m group by peer_asn""")
        conn.commit()
    assert model_job.main() == 0
    with connect() as conn, conn.cursor() as cur:
        cur.execute("select count(*) filter (where actual is not null), count(*) filter (where actual) from model_predictions")
        filled, positives = cur.fetchone()
        assert filled == 20 and positives == 20      # 50/100 = 0.5 >= 0.25
        cur.execute("select count(*) from model_runs")
        assert cur.fetchone()[0] == 2


def test_names_store_upserts(pg):
    sys.path.insert(0, str(ROOT / "analytics"))
    import names_job
    from common import connect
    with connect() as conn:
        names_job.store(conn, [(15169, "GOOGLE", "Google", "US"), (64500, "NEW-NET", "New Net", None)])
        names_job.store(conn, [(64500, "NEW-NET", "Renamed Net", "ES")])        # second run updates in place
        rows = dict(conn.execute("select asn, name from asn_names where asn in (15169, 64500)").fetchall())
    assert rows == {15169: "Google", 64500: "Renamed Net"}


def test_events_job_finds_a_burst_and_a_surge_once(pg):
    sys.path.insert(0, str(ROOT / "analytics"))
    import events_job
    from common import connect
    with connect() as conn:
        conn.execute("truncate kpi_events_1m, kpi_origins_5m, kpi_peers_5m, events")
        conn.execute("""insert into kpi_events_1m (window_start, announcements, withdrawals, total_updates)
                        select date_trunc('minute', now()) - g * interval '1 minute', 5000, 100 + (g % 7), 5100
                        from generate_series(4, 600) g""")
        # a 3-minute burst 20-22 minutes ago, peaking at 2,500 (25x the usual ~103)
        conn.execute("""update kpi_events_1m set withdrawals = case when window_start = date_trunc('minute', now()) - interval '21 minutes'
                        then 2500 else 900 end
                        where window_start between date_trunc('minute', now()) - interval '22 minutes'
                                               and date_trunc('minute', now()) - interval '20 minutes'""")
        conn.execute("""insert into kpi_peers_5m (window_start, peer_asn, updates, withdrawals)
                        select to_timestamp(floor(extract(epoch from now()) / 300) * 300) - g * interval '5 minutes', 1299, 3000, 800
                        from generate_series(3, 5) g""")
        # network 64500: quiet for 10 hours (10/5min = 120/h), then 300/5min in the last hour (3,600/h = 30x)
        conn.execute("""insert into kpi_origins_5m (window_start, origin_asn, announcements)
                        select to_timestamp(floor(extract(epoch from now()) / 300) * 300) - g * interval '5 minutes', 64500,
                               case when g <= 11 then 300 else 10 end from generate_series(1, 120) g""")
        conn.commit()
        events_job.main(); events_job.main()            # twice: must not duplicate
        rows = conn.execute("select kind, severity, value, round(magnitude), asn, data from events order by kind").fetchall()
    assert len(rows) == 2
    burst, surge = rows
    assert burst[:3] == ("burst", "alert", 2500) and 20 <= burst[3] <= 26
    assert burst[5]["reporters"][0]["asn"] == 1299
    assert surge[0] == "surge" and surge[4] == 64500 and surge[1] == "alert" and surge[2] >= 3000


def test_group_minutes_joins_neighbours():
    sys.path.insert(0, str(ROOT / "analytics"))
    from datetime import datetime, timedelta, timezone
    import events_job
    t = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
    m = lambda k: t + timedelta(minutes=k)
    out = events_job.group_minutes([(m(0), 5), (m(1), 9), (m(3), 4), (m(10), 7)])
    assert out == [(m(0), m(4), 9), (m(10), m(11), 7)]
