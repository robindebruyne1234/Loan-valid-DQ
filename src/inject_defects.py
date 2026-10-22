"""Build the deliberately corrupted copy of staging used to test the rules.

See the header of ``sql/70_inject_defects.sql`` for why this exists. The short
version: the public copy of the dataset is clean, so without a corrupted copy
most rules would report zero and nobody could tell a working rule from a
broken one.

Run with ``python -m src.inject_defects`` (``make test`` does it automatically).
"""

from __future__ import annotations

from typing import Any

from src import config, db

LOGGER = db.setup_logging("inject")


def build() -> list[dict[str, Any]]:
    """Create schema ``inject`` and seed one defect per rule family.

    :returns: The register of injected defects, one dictionary per defect, each
        naming the ``rule_id`` that is expected to catch it.
    """
    with db.connect(autocommit=True) as conn:
        db.run_sql_file(conn, config.SQL_DIR / "70_inject_defects.sql", LOGGER)
        register = db.fetch_all(
            conn,
            """
            SELECT defect_no, expected_rule_id, dimension, target_table,
                   business_key, description
            FROM inject.injected_defect ORDER BY defect_no
            """,
        )
    LOGGER.info("injected %d defects into schema %s", len(register), config.SCHEMA_INJECT)
    for row in register:
        LOGGER.info(
            "  %2d %-36s %-22s key=%s",
            row["defect_no"],
            row["expected_rule_id"],
            row["dimension"],
            row["business_key"],
        )
    return register


def main() -> int:
    """Entry point.

    :returns: Process exit code, ``0`` on success.
    """
    register = build()
    db.record_run(
        "inject",
        "python -m src.inject_defects",
        {"defects": len(register),
         "rules_targeted": sorted({r["expected_rule_id"] for r in register})},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
