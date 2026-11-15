"""Spins up a throwaway PostgreSQL 16 (binaries must be on the machine), applies
the real schema files, seeds a little data and yields a FastAPI TestClient."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PGBIN = next((Path(p) for p in ["/usr/lib/postgresql/16/bin", "/usr/lib/postgresql/17/bin",
                                "/opt/homebrew/opt/postgresql@16/bin"] if Path(p).exists()), None)
PORT = "5599"


def _run(cmd, **kw):
    return subprocess.run(cmd, check=True, text=True, capture_output=True, **kw)


@pytest.fixture(scope="session")
def pg():
    if PGBIN is None:
        pytest.skip("no PostgreSQL binaries found")
    d = Path(tempfile.mkdtemp(prefix="pgapi-"))
    sock = d / "sock"; sock.mkdir()
    as_user = []
    if os.geteuid() == 0:                       # initdb refuses to run as root
        shutil.chown(d, "postgres"); shutil.chown(sock, "postgres")
        as_user = ["runuser", "-u", "postgres", "--"]
    _run(as_user + [str(PGBIN / "initdb"), "-D", str(d / "data"), "-U", "postgres", "-A", "trust", "-E", "UTF8", "--locale=C"])
    _run(as_user + [str(PGBIN / "pg_ctl"), "-D", str(d / "data"), "-o", f"-p {PORT} -k {sock}",
                    "-l", str(d / "log"), "start", "-w"])
    psql = as_user + [str(PGBIN / "psql"), "-h", str(sock), "-p", PORT, "-U", "postgres", "-v", "ON_ERROR_STOP=1", "-q"]
    _run(psql + ["-d", "postgres", "-c", "create database bgp"])
    for f in sorted((ROOT / "postgres" / "init").glob("*.sql")):
        _run(psql + ["-d", "bgp", "-f", str(f)])
    _run(psql + ["-d", "bgp", "-f", str(Path(__file__).with_name("seed.sql"))])
    yield {"host": str(sock), "port": PORT}
    subprocess.run(as_user + [str(PGBIN / "pg_ctl"), "-D", str(d / "data"), "stop", "-m", "immediate"],
                   capture_output=True)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(scope="session")
def client(pg):
    os.environ.update(POSTGRES_HOST=pg["host"], POSTGRES_PORT=pg["port"], POSTGRES_DB="bgp",
                      POSTGRES_USER="postgres", POSTGRES_PASSWORD="x")
    sys.path.insert(0, str(ROOT / "api"))
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c
