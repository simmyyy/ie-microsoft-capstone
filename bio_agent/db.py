"""
PostgreSQL connection for biodiversity agent tools.
Supports env vars (PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD) or Secrets Manager (SECRET_ARN).
"""
from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from typing import Any, Generator

logger = logging.getLogger(__name__)

_SCHEMA = os.environ.get("PG_SCHEMA", "serving")


def _get_credentials() -> dict[str, Any]:
    """Resolve DB credentials from env or Secrets Manager."""
    secret_arn = os.environ.get("SECRET_ARN")
    if secret_arn:
        try:
            import boto3
            client = boto3.client("secretsmanager")
            resp = client.get_secret_value(SecretId=secret_arn)
            secret = json.loads(resp.get("SecretString", "{}"))
            return {
                "host": secret.get("host"),
                "port": int(secret.get("port", 5432)),
                "dbname": secret.get("dbname"),
                "user": secret.get("username") or secret.get("user"),
                "password": secret.get("password"),
            }
        except Exception as e:
            logger.exception("Failed to fetch secret: %s", e)
            raise

    return {
        "host": os.environ.get("PGHOST"),
        "port": int(os.environ.get("PGPORT", "5432")),
        "dbname": os.environ.get("PGDATABASE"),
        "user": os.environ.get("PGUSER"),
        "password": os.environ.get("PGPASSWORD"),
    }


@contextmanager
def get_connection() -> Generator[Any, None, None]:
    """Yield a psycopg2 connection. Closes on exit."""
    import psycopg2
    creds = _get_credentials()
    if not all([creds.get("host"), creds.get("dbname"), creds.get("user"), creds.get("password")]):
        raise ValueError("Missing DB credentials. Set PGHOST, PGDATABASE, PGUSER, PGPASSWORD or SECRET_ARN")
    conn = psycopg2.connect(
        host=creds["host"],
        port=creds["port"],
        dbname=creds["dbname"],
        user=creds["user"],
        password=creds["password"],
        connect_timeout=10,
    )
    conn.autocommit = False
    try:
        yield conn
    finally:
        conn.close()


def schema() -> str:
    return _SCHEMA


def _row_to_dict(cursor, row: tuple) -> dict:
    """Convert row to dict using cursor column names."""
    if row is None:
        return {}
    return dict(zip([d[0] for d in cursor.description], row))
