"""Read-only Postgres access through one connection pool.

Every query is a plain SQL string with bound parameters. The session is forced
read-only (see Settings.dsn), so even a bug in a handler cannot modify data.
"""

from contextlib import contextmanager
from typing import Any, Iterator

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .settings import settings

pool = ConnectionPool(
    conninfo=settings.dsn,
    min_size=settings.pool_min,
    max_size=settings.pool_max,
    kwargs={"row_factory": dict_row},
    open=False,
)


@contextmanager
def cursor() -> Iterator[Any]:
    with pool.connection() as conn:
        with conn.cursor() as cur:
            yield cur


def rows(sql: str, params: tuple = ()) -> list[dict]:
    with cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def one(sql: str, params: tuple = ()) -> dict | None:
    with cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()
