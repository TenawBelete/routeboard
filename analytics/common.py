"""Shared helpers for the analytics jobs."""

import logging
import os
import sys

import psycopg

logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                    format="%(asctime)s %(levelname)s %(message)s")


def pg_conninfo() -> str:
    return (f"host={os.environ.get('POSTGRES_HOST', 'postgres')} "
            f"port={os.environ.get('POSTGRES_PORT', '5432')} "
            f"dbname={os.environ['POSTGRES_DB']} user={os.environ['POSTGRES_USER']} "
            f"password={os.environ['POSTGRES_PASSWORD']} application_name=bgp-analytics")


def connect() -> psycopg.Connection:
    return psycopg.connect(pg_conninfo())
