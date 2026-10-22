"""Load the raw PKDD'99 source files into schema ``raw``.

The landing zone is deliberately dumb: every column is ``text``, nothing is
cast, nothing is cleaned and nothing is rejected. That keeps the question
"did the loader change this value?" answerable, which is the whole point of
having a raw layer in a data quality exercise.

Two details matter for later phases:

* The ``.asc`` files distinguish a *quoted* empty field (``""``) from an
  *unquoted* empty field. PostgreSQL's CSV reader maps the first to an empty
  string and the second to ``NULL``, so that distinction survives into ``raw``
  and the completeness rules can report on it (``trans.k_symbol`` is quoted
  empty, ``trans.bank`` and ``trans.account`` are unquoted empty).
* ``_source_row`` is an identity column filled in COPY insertion order, which
  is file order, so every staged row can be traced back to a line number.

Run with ``make ingest``.
"""

from __future__ import annotations

import argparse
import gzip
import io
import time
import uuid
from pathlib import Path
from typing import IO

import psycopg

from src import config, db

LOGGER = db.setup_logging("ingest")

#: COPY options used for every source file, recorded in ``raw.load_audit``.
COPY_OPTIONS = "FORMAT csv, DELIMITER ';', HEADER true, QUOTE '\"', NULL ''"


def resolve_source(name: str) -> Path:
    """Find the file for one source table, preferring the bank-supplied copy.

    Lookup order per table: ``data/raw/provided/<file>`` (the bank's copy, when
    one has been placed there), then ``data/raw/<file>``, then the gzipped
    variant of either. The first hit wins and the chosen path is logged, so a
    run can never silently mix the two copies.

    :param name: Source table name, a key of :data:`src.config.RAW_TABLES`.
    :returns: Path of the file to load.
    :raises FileNotFoundError: When no candidate path exists.
    """
    file_name, _ = config.RAW_TABLES[name]
    candidates = [
        config.PROVIDED_DIR / file_name,
        config.PROVIDED_DIR / f"{file_name}.gz",
        config.RAW_DIR / file_name,
        config.RAW_DIR / f"{file_name}.gz",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"no source file for '{name}'; looked for: "
        + ", ".join(str(c) for c in candidates)
    )


def open_text_stream(path: Path) -> IO[bytes]:
    """Open a source file as a byte stream, transparently decompressing ``.gz``.

    :param path: Path of the source file.
    :returns: Readable binary stream positioned at the start of the file.
    """
    if path.suffix == ".gz":
        return gzip.open(path, "rb")
    return path.open("rb")


def raw_table_ddl(name: str) -> str:
    """Build the ``CREATE TABLE`` statement for one raw landing table.

    The shape is a mechanical projection of the file layout held in
    :data:`src.config.RAW_TABLES`, which is why it is generated rather than
    hand-written: the file layout is the single source of truth and a drifting
    copy of it in SQL would be a defect waiting to happen.

    :param name: Source table name.
    :returns: A ``CREATE TABLE`` statement with every data column typed ``text``.
    """
    file_name, columns = config.RAW_TABLES[name]
    column_sql = ",\n    ".join(f'"{column}" text' for column in columns)
    return (
        f'CREATE TABLE {config.SCHEMA_RAW}."{name}" (\n'
        "    _source_row bigint GENERATED ALWAYS AS IDENTITY,\n"
        f"    _source_file text NOT NULL DEFAULT '{file_name}',\n"
        f"    {column_sql}\n"
        ");"
    )


def load_table(conn: psycopg.Connection, name: str, path: Path, run_id: uuid.UUID) -> int:
    """Load one raw file into the ``raw`` schema and audit the load.

    :param conn: Open connection; the caller owns the transaction.
    :param name: Target table name in the ``raw`` schema.
    :param path: Path of the source file.
    :param run_id: Identifier of the ingest run, written to ``raw.load_audit``.
    :returns: Number of rows loaded.
    """
    _, columns = config.RAW_TABLES[name]
    column_list = ", ".join(f'"{column}"' for column in columns)
    started = time.perf_counter()

    with conn.cursor() as cur:
        cur.execute(f'DROP TABLE IF EXISTS {config.SCHEMA_RAW}."{name}" CASCADE')
        cur.execute(raw_table_ddl(name))
        copy_sql = (
            f'COPY {config.SCHEMA_RAW}."{name}" ({column_list}) '
            f"FROM STDIN WITH ({COPY_OPTIONS})"
        )
        with open_text_stream(path) as source, cur.copy(copy_sql) as copy:
            while True:
                chunk = source.read(1 << 20)
                if not chunk:
                    break
                copy.write(chunk)

    rows = db.table_count(conn, config.SCHEMA_RAW, name)
    duration = time.perf_counter() - started
    expected = config.REFERENCE_ROW_COUNTS.get(name)
    digest = db.sha256_file(path)
    raw_bytes = path.stat().st_size

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO raw.load_audit (
                run_id, source_name, source_file, file_bytes, file_sha256,
                rows_loaded, rows_expected, counts_match, copy_options, duration_sec
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                str(run_id),
                name,
                str(path.relative_to(config.PROJECT_ROOT)),
                raw_bytes,
                digest,
                rows,
                expected,
                None if expected is None else rows == expected,
                COPY_OPTIONS,
                round(duration, 3),
            ),
        )

    verdict = "ok" if expected is None or rows == expected else "MISMATCH"
    LOGGER.info(
        "loaded %-9s rows=%-8d expected=%-8s %s | %.2fs | sha256=%s",
        name,
        rows,
        expected if expected is not None else "n/a",
        verdict,
        duration,
        digest[:16],
    )
    return rows


def drop_all(conn: psycopg.Connection) -> None:
    """Drop every project schema, so a rebuild starts from nothing.

    The raw files on disk are untouched, so ``make all`` restores everything.

    :param conn: Open connection.
    :returns: ``None``.
    """
    for schema in (*config.ALL_SCHEMAS, config.SCHEMA_INJECT):
        LOGGER.info("dropping schema -> %s", schema)
        db.execute(conn, f"DROP SCHEMA IF EXISTS {schema} CASCADE")


def main() -> int:
    """Create the schemas and load every source file into ``raw``.

    :returns: Process exit code: ``0`` on success, ``1`` when a loaded row
        count disagrees with the published reference count.
    """
    parser = argparse.ArgumentParser(description="Load raw Berka files into PostgreSQL.")
    parser.add_argument(
        "--drop-all",
        action="store_true",
        help="drop every project schema and exit",
    )
    args = parser.parse_args()

    run_id = uuid.uuid4()
    with db.connect(autocommit=True) as conn:
        if args.drop_all:
            drop_all(conn)
            LOGGER.info("all project schemas dropped")
            return 0

        LOGGER.info("ingest run_id=%s", run_id)
        db.run_sql_file(conn, config.SQL_DIR / "00_schemas.sql", LOGGER)

        provided = sorted(p.name for p in config.PROVIDED_DIR.glob("*") if p.is_file())
        if provided:
            LOGGER.info("bank-supplied copy present in data/raw/provided -> %s", provided)
        else:
            LOGGER.info("data/raw/provided is empty -> using the public copy (see DECISIONS D004)")

        totals: dict[str, int] = {}
        mismatches: list[str] = []
        for name in config.RAW_TABLES:
            path = resolve_source(name)
            totals[name] = load_table(conn, name, path, run_id)
            expected = config.REFERENCE_ROW_COUNTS.get(name)
            if expected is not None and totals[name] != expected:
                mismatches.append(f"{name}: loaded {totals[name]}, expected {expected}")

        LOGGER.info("___ ingest summary ___")
        for name, rows in totals.items():
            LOGGER.info("  %-9s %8d rows", name, rows)
        LOGGER.info("  total     %8d rows", sum(totals.values()))

        db.record_run(
            "ingest",
            "make ingest",
            {"run_id": str(run_id), "row_counts": totals, "mismatches": mismatches},
        )

        if mismatches:
            LOGGER.error("row count mismatches against the public reference:")
            for line in mismatches:
                LOGGER.error("  ! %s", line)
            LOGGER.error(
                "a mismatch is not automatically a failure: it is the expected "
                "signal when the bank's own copy is loaded. Review the diff report."
            )
            return 1

        LOGGER.info("all row counts match the published reference counts")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
