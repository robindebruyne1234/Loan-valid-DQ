"""Database access helpers and project-wide logging setup.

Thin wrappers around :mod:`psycopg` so that every pipeline step connects,
logs and reports the same way. All connection defaults come from
:mod:`src.config`; nothing here hard-codes a host, a role or a schema.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import sys
import time
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql as pgsql
from psycopg.rows import dict_row

from src import config

_LOGGING_READY = False


def setup_logging(name: str, level: int = logging.INFO) -> logging.Logger:
    """Configure root logging once and return a named logger.

    Log messages are plain ASCII by project convention: no emoji, no Unicode
    icons, so the output stays readable in any terminal or CI log.

    :param name: Logger name, usually the pipeline step (``ingest``, ``dq``).
    :param level: Logging level for the returned logger.
    :returns: A configured :class:`logging.Logger`.
    """
    global _LOGGING_READY
    if not _LOGGING_READY:
        logging.basicConfig(
            level=level,
            format=config.LOG_FORMAT,
            datefmt=config.LOG_DATE_FORMAT,
            stream=sys.stdout,
        )
        _LOGGING_READY = True
    logger = logging.getLogger(name)
    logger.setLevel(level)
    return logger


def connect(
    user: str | None = None,
    password: str | None = None,
    autocommit: bool = False,
    role: str | None = None,
) -> psycopg.Connection:
    """Open a connection to the project database.

    :param user: Login role. Defaults to the owner role from the config.
    :param password: Password for ``user``. Defaults are resolved by
        :func:`src.config.dsn`.
    :param autocommit: When ``True`` every statement commits immediately,
        which DDL batches and ``VACUUM`` need.
    :param role: Optional role to ``SET ROLE`` to right after connecting,
        used by the entitlement tests.
    :returns: An open connection whose cursors return dictionaries.
    """
    conn = psycopg.connect(config.dsn(user, password), row_factory=dict_row)
    conn.autocommit = autocommit
    if role:
        with conn.cursor() as cur:
            cur.execute(pgsql.SQL("SET ROLE {}").format(pgsql.Identifier(role)))
    return conn


def execute(conn: psycopg.Connection, sql: str, params: Sequence[Any] | None = None) -> None:
    """Execute one statement that returns no rows.

    :param conn: Open connection.
    :param sql: Statement to run.
    :param params: Optional positional parameters.
    :returns: ``None``.
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)


def fetch_all(
    conn: psycopg.Connection, sql: str, params: Sequence[Any] | None = None
) -> list[dict[str, Any]]:
    """Run a query and return every row as a dictionary.

    :param conn: Open connection.
    :param sql: Query to run.
    :param params: Optional positional parameters.
    :returns: List of row dictionaries, empty when the query returns nothing.
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def fetch_value(
    conn: psycopg.Connection, sql: str, params: Sequence[Any] | None = None
) -> Any:
    """Run a query and return the first column of the first row.

    :param conn: Open connection.
    :param sql: Query to run; should return exactly one row and column.
    :param params: Optional positional parameters.
    :returns: The scalar value, or ``None`` when the query returns no row.
    """
    rows = fetch_all(conn, sql, params)
    if not rows:
        return None
    return next(iter(rows[0].values()))


def run_sql_file(conn: psycopg.Connection, path: Path, logger: logging.Logger | None = None) -> float:
    """Execute a whole ``.sql`` file as one batch.

    The file is sent to the server unmodified, so ``psql``-style dollar quoted
    function bodies and multi-statement batches work as written.

    :param path: Path of the SQL file to execute.
    :param conn: Open connection; the caller controls the transaction.
    :param logger: Optional logger that receives a start and finish line.
    :returns: Wall clock duration of the batch, in seconds.
    """
    sql_text = path.read_text(encoding="utf-8")
    started = time.perf_counter()
    if logger:
        logger.info("running SQL file -> %s", path.name)
    with conn.cursor() as cur:
        cur.execute(sql_text)
    elapsed = time.perf_counter() - started
    if logger:
        logger.info("done %s in %.2fs", path.name, elapsed)
    return elapsed


def table_count(conn: psycopg.Connection, schema: str, table: str) -> int:
    """Count the rows of one table.

    :param conn: Open connection.
    :param schema: Schema name.
    :param table: Table name.
    :returns: Row count.
    """
    return int(fetch_value(conn, f'SELECT count(*) FROM {schema}."{table}"') or 0)


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """Hash a file with SHA-256, streaming it in chunks.

    Gzipped sources are hashed on their decompressed byte stream, so the hash
    identifies the data and not the compression settings.

    :param path: File to hash.
    :param chunk_size: Read buffer size in bytes.
    :returns: Lowercase hexadecimal digest.
    """
    digest = hashlib.sha256()
    opener: Any
    if path.suffix == ".gz":
        import gzip

        opener = gzip.open
    else:
        opener = open
    with opener(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def utc_now_iso() -> str:
    """Return the current UTC timestamp as an ISO-8601 string.

    :returns: Timestamp such as ``2026-10-22T09:30:00+00:00``.
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_run(step: str, command: str, detail: dict[str, Any] | None = None) -> None:
    """Append one provenance entry to the run log.

    Every number that reaches a deliverable is produced by a logged step, so
    the walkthrough can point at the command and timestamp behind it.

    :param step: Pipeline step name, for example ``ingest`` or ``dq``.
    :param command: The command a reader can re-run to reproduce the step.
    :param detail: Optional JSON-serialisable detail such as row counts.
    :returns: ``None``.
    """
    config.DQ_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "step": step,
        "command": command,
        "executed_at_utc": utc_now_iso(),
        "detail": detail or {},
    }
    with config.RUN_LOG_JSONL.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, default=str) + "\n")


def git_commit() -> str:
    """Return the current git commit hash, or ``unknown`` outside a repo.

    :returns: Short commit hash of ``HEAD``.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(config.PROJECT_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return out.stdout.strip() or "unknown"
    except Exception:  # pragma: no cover - provenance is best effort
        return "unknown"


def qualified(schema: str, table: str) -> str:
    """Return a quoted, schema-qualified table name.

    :param schema: Schema name.
    :param table: Table name, quoted because ``order`` is a reserved word.
    :returns: Identifier such as ``stg."order"``.
    """
    return f'{schema}."{table}"'


def iter_sql_statements(sql_text: str) -> Iterable[str]:
    """Split a SQL script into statements on semicolons outside quotes.

    Only used where statements must run one by one, for example when each
    statement needs its own error handling. Dollar quoted blocks are kept
    whole.

    :param sql_text: Full script text.
    :returns: Iterator over non-empty statements, without trailing semicolons.
    """
    statement: list[str] = []
    in_single = False
    in_double = False
    in_dollar: str | None = None
    index = 0
    while index < len(sql_text):
        char = sql_text[index]
        if in_dollar:
            if sql_text.startswith(in_dollar, index):
                statement.append(in_dollar)
                index += len(in_dollar)
                in_dollar = None
                continue
        elif char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "$" and not in_single and not in_double:
            end = sql_text.find("$", index + 1)
            if end != -1 and sql_text[index + 1 : end].replace("_", "").isalnum() or (
                end == index + 1
            ):
                in_dollar = sql_text[index : end + 1]
                statement.append(in_dollar)
                index = end + 1
                continue
        elif char == ";" and not in_single and not in_double:
            candidate = "".join(statement).strip()
            if candidate:
                yield candidate
            statement = []
            index += 1
            continue
        statement.append(char)
        index += 1
    tail = "".join(statement).strip()
    if tail:
        yield tail
