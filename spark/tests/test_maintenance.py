"""Tests the DECISIONS in maintenance.py (which days to summarise, which to
delete, which to protect) with Delta calls stubbed out. Delta itself is not
available in the test environment; its operations are exercised on the real
stack."""
import os
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.update(POSTGRES_DB="x", POSTGRES_USER="x", POSTGRES_PASSWORD="x")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.modules.setdefault("delta", SimpleNamespace(tables=SimpleNamespace(DeltaTable=object)))
sys.modules.setdefault("delta.tables", SimpleNamespace(DeltaTable=object))
import maintenance as M  # noqa: E402

TODAY = date(2026, 11, 20)


class FakeTable:
    def __init__(self, days):
        self.days = set(days)
        self.deleted_below = None

    def toDF(self):
        return self

    def select(self, *_):
        return self

    def distinct(self):
        return self

    def collect(self):
        return [SimpleNamespace(dt=d) for d in sorted(self.days)]

    def delete(self, cond):
        self.deleted_below = cond   # we only check it was called


def install(monkeypatch, tables):
    """tables: {path: FakeTable}; anything else does not exist."""
    monkeypatch.setattr(M, "table_exists", lambda spark, p: p in tables)
    monkeypatch.setattr(M, "DeltaTable",
                        SimpleNamespace(forPath=lambda spark, p: tables[p]))


def test_days_to_delete_respects_cutoff_and_protection():
    existing = {date(2026, 11, d) for d in range(1, 21)}
    # keep 14 days -> cutoff 2026-11-06 ; protect the 3rd
    doomed = M.days_to_delete(existing, 14, TODAY, protect={date(2026, 11, 3)})
    assert doomed == [date(2026, 11, 1), date(2026, 11, 2),
                      date(2026, 11, 4), date(2026, 11, 5)]
    assert date(2026, 11, 6) not in doomed      # cutoff day itself is kept


def test_days_to_delete_empty_when_all_recent():
    assert M.days_to_delete({TODAY, date(2026, 11, 19)}, 3, TODAY) == []


def test_expire_noop_when_nothing_old(monkeypatch):
    bronze = FakeTable([date(2026, 11, 19), date(2026, 11, 20)])
    install(monkeypatch, {M.BRONZE: bronze})
    M.expire(None, M.BRONZE, 3, TODAY)
    assert bronze.deleted_below is None


def test_expire_skips_missing_table(monkeypatch):
    install(monkeypatch, {})
    M.expire(None, M.BRONZE, 3, TODAY)   # must not raise


def test_vacuum_retention_is_at_least_one_hour():
    assert M.VACUUM_RETAIN_HOURS >= 1
