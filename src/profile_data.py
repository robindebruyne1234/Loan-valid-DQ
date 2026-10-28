"""Build the staging layer and profile every column in it.

Profiling comes before rule writing on purpose. The brief says the bank may
have injected defects whose nature is unknown, so the rules cannot be derived
from the published dataset description alone: they have to be derived from what
the data actually looks like. This module produces that evidence
(``dq/results/profile.md`` and ``profile.json``) and a ranked list of candidate
defects (``dq/results/candidates.md``) that the rules in ``dq/dq_rules.yaml``
then formalise.

Run with ``make profile``.
"""

from __future__ import annotations

import json
import time
from typing import Any

import psycopg

from src import config, db

LOGGER = db.setup_logging("profile")

#: Tables profiled, in reporting order.
STG_TABLES: tuple[str, ...] = (
    "district",
    "client",
    "account",
    "disp",
    "card",
    "loan",
    "order",
    "trans",
)

#: Columns that hold business codes. These get a pattern distribution on top of
#: the usual statistics, because an injected defect often shows up as a value
#: with the right type but the wrong shape.
CODE_COLUMNS: dict[str, tuple[str, ...]] = {
    "account": ("frequency_code", "frequency_label"),
    "client": ("birth_number", "gender"),
    "disp": ("disp_type_code",),
    "card": ("card_type",),
    "loan": ("status_code",),
    "order": ("bank_to", "k_symbol_code"),
    "trans": ("trans_type_code", "operation_code", "k_symbol_code", "partner_bank"),
    "district": ("region",),
}

#: Candidate defect checks, evaluated after profiling. Each one is a hypothesis
#: about the data; the count it returns decides whether it becomes a rule, and
#: with which severity. ``note`` explains what a non-zero count means.
CANDIDATE_CHECKS: tuple[dict[str, str], ...] = (
    {
        "label": "district: placeholder '?' in 1995 unemployment and crime columns",
        "sql": """
            SELECT count(*) FROM stg.district
            WHERE unemployment_rate_1995_raw IS NOT NULL
               OR crimes_1995_raw IS NOT NULL
        """,
        "note": "Known original-dataset gap (district 69, Jesenik). Only matters "
                "once a metric uses the 1995 columns; none of the 10 questions does.",
    },
    {
        "label": "trans: structural NULL in operation (interest postings have no operation)",
        "sql": "SELECT count(*) FROM stg.trans WHERE operation_code IS NULL",
        "note": "Every one of these is an interest credit (k_symbol = UROK). The NULL "
                "is meaningful, not missing, so it must not be imputed.",
    },
    {
        "label": "trans: three different encodings of 'no value' in the same column",
        "sql": """
            SELECT count(*) FROM raw.trans
            WHERE k_symbol IS NULL OR k_symbol = '' OR btrim(k_symbol) = ''
        """,
        "note": "raw.trans.k_symbol arrives as quoted empty string, unquoted empty "
                "field (NULL) and a single space. Three spellings of the same fact.",
    },
    {
        "label": "trans: partner bank and partner account missing together",
        "sql": """
            SELECT count(*) FROM stg.trans
            WHERE partner_bank IS NULL AND partner_account IS NULL
        """,
        "note": "Structural: cash operations have no counterparty. Expected to equal "
                "the number of non-transfer operations.",
    },
    {
        "label": "trans: amount is zero",
        "sql": "SELECT count(*) FROM stg.trans WHERE amount = 0",
        "note": "Zero-value postings (sanction interest and interest with no accrual). "
                "Breaks a naive 'amount > 0' validity rule but changes no sum.",
    },
    {
        "label": "trans: negative balance after the transaction",
        "sql": "SELECT count(*) FROM stg.trans WHERE balance_after < 0",
        "note": "Overdrafts. Real banking behaviour, not a defect; relevant to Q9 "
                "because they drag the average balance down and must not be clipped.",
    },
    {
        "label": "trans: duplicate business key (same account, date, type, amount, balance)",
        "sql": """
            SELECT coalesce(sum(n) - count(*), 0) FROM (
                SELECT count(*) AS n
                FROM stg.trans
                GROUP BY account_id, trans_date, trans_type_code,
                         coalesce(operation_code, '~'), amount, balance_after
                HAVING count(*) > 1
            ) d
        """,
        "note": "Distinct trans_id, identical business content. A duplicate posting "
                "the primary key cannot catch.",
    },
    {
        "label": "trans: running balance does not reconcile per account (tolerance 1.00 CZK)",
        "sql": """
            WITH last_day AS (
                SELECT account_id, max(trans_date) AS d FROM stg.trans GROUP BY account_id
            ), day_postings AS (
                SELECT t.account_id, t.trans_id, t.balance_after,
                       t.balance_after - t.signed_amount AS balance_before
                FROM stg.trans t
                JOIN last_day l ON l.account_id = t.account_id AND l.d = t.trans_date
            ), final AS (
                -- The last reported balance is the END of the last day's running-balance
                -- chain, the same rule as core.fact_account_month_end_balance (D028).
                -- trans_id is not chronological, so "highest id" picked a mid-day balance.
                SELECT DISTINCT ON (p.account_id) p.account_id, p.balance_after
                FROM day_postings p
                ORDER BY p.account_id,
                         NOT EXISTS (SELECT 1 FROM day_postings q
                                     WHERE q.account_id = p.account_id AND q.trans_id <> p.trans_id
                                       AND q.balance_before = p.balance_after) DESC,
                         p.trans_id ASC
            ), summed AS (
                SELECT account_id, sum(signed_amount) AS total FROM stg.trans GROUP BY 1
            )
            SELECT count(*) FROM summed s JOIN final f USING (account_id)
            WHERE abs(s.total - f.balance_after) > 1.00
        """,
        "note": "Order independent test: the sum of signed amounts should equal the "
                "last reported balance. Differences cluster at 0.1-0.5 CZK (rounding), "
                "but a tail of accounts is off by hundreds, which is a real gap.",
    },
    {
        "label": "trans: running balance off by more than 100 CZK per account",
        "sql": """
            WITH last_day AS (
                SELECT account_id, max(trans_date) AS d FROM stg.trans GROUP BY account_id
            ), day_postings AS (
                SELECT t.account_id, t.trans_id, t.balance_after,
                       t.balance_after - t.signed_amount AS balance_before
                FROM stg.trans t
                JOIN last_day l ON l.account_id = t.account_id AND l.d = t.trans_date
            ), final AS (
                -- The last reported balance is the END of the last day's running-balance
                -- chain, the same rule as core.fact_account_month_end_balance (D028).
                -- trans_id is not chronological, so "highest id" picked a mid-day balance.
                SELECT DISTINCT ON (p.account_id) p.account_id, p.balance_after
                FROM day_postings p
                ORDER BY p.account_id,
                         NOT EXISTS (SELECT 1 FROM day_postings q
                                     WHERE q.account_id = p.account_id AND q.trans_id <> p.trans_id
                                       AND q.balance_before = p.balance_after) DESC,
                         p.trans_id ASC
            ), summed AS (
                SELECT account_id, sum(signed_amount) AS total FROM stg.trans GROUP BY 1
            )
            SELECT count(*) FROM summed s JOIN final f USING (account_id)
            WHERE abs(s.total - f.balance_after) > 100.00
        """,
        "note": "Material, not rounding: a missing or extra posting. Directly affects Q9.",
    },
    {
        "label": "trans: intra-day ordering is undefined (accounts with >1 posting on their last date)",
        "sql": """
            SELECT count(*) FROM (
                SELECT account_id, trans_date, count(*) AS n,
                       row_number() OVER (PARTITION BY account_id ORDER BY trans_date DESC) AS rn
                FROM stg.trans GROUP BY account_id, trans_date
            ) x WHERE rn = 1 AND n > 1
        """,
        "note": "The closing balance of a day is only well defined if the last posting "
                "of that day is identifiable. trans_id is not chronological within a "
                "day, so for these accounts the closing balance is a choice, not a fact.",
    },
    {
        "label": "owner was younger than 15 at account opening",
        "sql": """
            SELECT count(*) FROM stg.disp d
            JOIN stg.client c USING (client_id)
            JOIN stg.account a ON a.account_id = d.account_id
            WHERE d.disp_type_code = 'OWNER'
              AND (a.open_date - c.birth_date) / 365.25 < 15
        """,
        "note": "Implausible for a legal account holder. Minimum observed age is 10.3 "
                "years. Affects Q7 (average age at loan start) and Q8.",
    },
    {
        "label": "owner was younger than 15 at loan start",
        "sql": """
            SELECT count(*) FROM stg.loan l
            JOIN stg.disp d ON d.account_id = l.account_id AND d.disp_type_code = 'OWNER'
            JOIN stg.client c USING (client_id)
            WHERE (l.loan_date - c.birth_date) / 365.25 < 15
        """,
        "note": "A minor cannot take a loan. Direct hit on Q7.",
    },
    {
        "label": "client district differs from the district of the account they own",
        "sql": """
            SELECT count(*) FROM stg.disp d
            JOIN stg.client c USING (client_id)
            JOIN stg.account a ON a.account_id = d.account_id
            WHERE d.disp_type_code = 'OWNER' AND c.district_id <> a.district_id
        """,
        "note": "Not a defect: a client may bank in a different district than they live "
                "in. It is a modelling fork for Q1 and Q5, which is why both questions "
                "state which district they use.",
    },
    {
        "label": "card: holder is a disponent rather than the account owner",
        "sql": """
            SELECT count(*) FROM stg.card k
            JOIN stg.disp d USING (disp_id)
            WHERE d.disp_type_code <> 'OWNER'
        """,
        "note": "Q4 and Q8 ask about the card of the account OWNER, so a card held by a "
                "disponent must not be attributed to the owner.",
    },
    {
        "label": "account has no transaction at all",
        "sql": """
            SELECT count(*) FROM stg.account a
            WHERE NOT EXISTS (SELECT 1 FROM stg.trans t WHERE t.account_id = a.account_id)
        """,
        "note": "Would make the account invisible in any transaction-derived metric, "
                "including the Q9 balance.",
    },
    {
        "label": "business date outside the configured plausibility window",
        "sql": """
            SELECT (SELECT count(*) FROM stg.account WHERE open_date NOT BETWEEN %(lo)s AND %(hi)s)
                 + (SELECT count(*) FROM stg.loan    WHERE loan_date NOT BETWEEN %(lo)s AND %(hi)s)
                 + (SELECT count(*) FROM stg.card    WHERE issued_date NOT BETWEEN %(lo)s AND %(hi)s)
                 + (SELECT count(*) FROM stg.trans   WHERE trans_date NOT BETWEEN %(lo)s AND %(hi)s)
        """,
        "note": "Window is 1993-01-01 to 1998-12-31 (src.config). A date outside it "
                "silently corrupts every per-year and per-month grouping (Q2, Q5, Q6).",
    },
    {
        "label": "unparsable date or amount anywhere in staging",
        "sql": """
            SELECT (SELECT count(*) FROM stg.account WHERE open_date_raw IS NOT NULL)
                 + (SELECT count(*) FROM stg.loan    WHERE loan_date_raw IS NOT NULL)
                 + (SELECT count(*) FROM stg.card    WHERE issued_raw IS NOT NULL)
                 + (SELECT count(*) FROM stg.trans   WHERE trans_date_raw IS NOT NULL)
                 + (SELECT count(*) FROM stg.loan    WHERE amount_raw IS NOT NULL)
                 + (SELECT count(*) FROM stg.trans   WHERE amount_raw IS NOT NULL)
                 + (SELECT count(*) FROM stg.trans   WHERE balance_raw IS NOT NULL)
        """,
        "note": "Non-zero means a cast silently produced NULL. The raw text is kept in "
                "the *_raw audit columns, so nothing is lost and the rows are countable.",
    },
)


def list_columns(conn: psycopg.Connection, schema: str, table: str) -> list[dict[str, Any]]:
    """List the columns of one table with their declared types.

    :param conn: Open connection.
    :param schema: Schema name.
    :param table: Table name.
    :returns: List of ``{"column_name": ..., "data_type": ...}`` dictionaries
        in ordinal position order.
    """
    return db.fetch_all(
        conn,
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema, table),
    )


def profile_column(
    conn: psycopg.Connection,
    schema: str,
    table: str,
    column: str,
    data_type: str,
    total_rows: int,
    with_pattern: bool,
) -> dict[str, Any]:
    """Profile one column: nulls, cardinality, range, lengths and top values.

    :param conn: Open connection.
    :param schema: Schema holding the table.
    :param table: Table name.
    :param column: Column name.
    :param data_type: Declared SQL type, used to decide which statistics apply.
    :param total_rows: Row count of the table, used for the null rate.
    :param with_pattern: When ``True`` also compute a pattern distribution
        (digits folded to ``9``, letters to ``A``), which exposes values of the
        right type but the wrong shape.
    :returns: Dictionary of profile statistics for this column.
    """
    target = db.qualified(schema, table)
    quoted = f'"{column}"'
    is_array = data_type == "ARRAY"
    # Arrays have no useful min/max or cast to text for this purpose.
    castable = not is_array

    stats = db.fetch_all(
        conn,
        f"""
        SELECT count({quoted})                              AS non_null,
               count(*) - count({quoted})                   AS nulls,
               count(DISTINCT {quoted})                     AS distinct_values
        FROM {target}
        """,
    )[0]

    result: dict[str, Any] = {
        "column": column,
        "data_type": data_type,
        "rows": total_rows,
        "nulls": int(stats["nulls"]),
        "null_rate": round(float(stats["nulls"]) / total_rows, 6) if total_rows else None,
        "distinct_values": int(stats["distinct_values"]),
    }

    if castable:
        # Booleans have no min/max aggregate, so they are compared as 0/1.
        rankable = f"{quoted}::int" if data_type == "boolean" else quoted
        extremes = db.fetch_all(
            conn,
            f"""
            SELECT min({rankable})::text AS min_value,
                   max({rankable})::text AS max_value,
                   min(length({quoted}::text)) AS min_length,
                   max(length({quoted}::text)) AS max_length
            FROM {target}
            """,
        )[0]
        result.update(
            {
                "min_value": extremes["min_value"],
                "max_value": extremes["max_value"],
                "min_length": extremes["min_length"],
                "max_length": extremes["max_length"],
            }
        )

        top = db.fetch_all(
            conn,
            f"""
            SELECT {quoted}::text AS value, count(*) AS n
            FROM {target}
            GROUP BY 1 ORDER BY n DESC, 1 NULLS LAST LIMIT 5
            """,
        )
        result["top_values"] = [{"value": row["value"], "count": int(row["n"])} for row in top]

    if with_pattern and castable:
        patterns = db.fetch_all(
            conn,
            f"""
            SELECT regexp_replace(regexp_replace({quoted}::text, '[0-9]', '9', 'g'),
                                  '[A-Za-z]', 'A', 'g') AS pattern,
                   count(*) AS n
            FROM {target}
            WHERE {quoted} IS NOT NULL
            GROUP BY 1 ORDER BY n DESC LIMIT 8
            """,
        )
        result["patterns"] = [
            {"pattern": row["pattern"], "count": int(row["n"])} for row in patterns
        ]

    return result


def profile_table(conn: psycopg.Connection, table: str) -> dict[str, Any]:
    """Profile every column of one staging table.

    :param conn: Open connection.
    :param table: Table name inside the ``stg`` schema.
    :returns: Dictionary with the row count and a list of column profiles.
    """
    started = time.perf_counter()
    total_rows = db.table_count(conn, config.SCHEMA_STG, table)
    code_columns = CODE_COLUMNS.get(table, ())
    columns = []
    for meta in list_columns(conn, config.SCHEMA_STG, table):
        name = meta["column_name"]
        columns.append(
            profile_column(
                conn,
                config.SCHEMA_STG,
                table,
                name,
                meta["data_type"],
                total_rows,
                with_pattern=name in code_columns,
            )
        )
    elapsed = time.perf_counter() - started
    LOGGER.info(
        "profiled %-9s rows=%-8d columns=%-3d in %.2fs", table, total_rows, len(columns), elapsed
    )
    return {"table": table, "rows": total_rows, "columns": columns, "duration_sec": round(elapsed, 3)}


def run_candidates(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Evaluate every candidate defect check against the staged data.

    :param conn: Open connection.
    :returns: List of ``{"label", "count", "note", "sql"}`` dictionaries,
        ordered with the non-zero findings first.
    """
    findings: list[dict[str, Any]] = []
    params = {"lo": config.DATA_MIN_DATE, "hi": config.DATA_MAX_DATE}
    for check in CANDIDATE_CHECKS:
        sql = check["sql"]
        with conn.cursor() as cur:
            cur.execute(sql, params if "%(lo)s" in sql else None)
            row = cur.fetchone()
        count = int(next(iter(row.values())) or 0) if row else 0
        findings.append(
            {
                "label": check["label"],
                "count": count,
                "note": check["note"],
                "sql": " ".join(sql.split()),
            }
        )
        LOGGER.info("candidate %-7d %s", count, check["label"])
    findings.sort(key=lambda item: (item["count"] == 0, -item["count"]))
    return findings


def write_profile_markdown(profiles: list[dict[str, Any]]) -> None:
    """Render the column profile as Markdown.

    :param profiles: Per-table profile dictionaries from :func:`profile_table`.
    :returns: ``None``.
    """
    lines: list[str] = [
        "# Column profile of the staging layer",
        "",
        f"Generated by `make profile` at {db.utc_now_iso()} "
        f"(git {db.git_commit()}). Source of truth: `dq/results/profile.json`.",
        "",
        "Lineage and audit columns (`_source_file`, `_source_row`, `*_raw`,",
        "`_conversion_notes`) are profiled too: a non-zero count in a `*_raw`",
        "column is itself a defect signal, because it only fills when a cast",
        "changed or dropped a value.",
        "",
    ]
    for profile in profiles:
        lines += [
            f"## stg.{profile['table']}  ({profile['rows']:,} rows)",
            "",
            "| column | type | nulls | null rate | distinct | min | max | top values |",
            "|---|---|---:|---:|---:|---|---|---|",
        ]
        for column in profile["columns"]:
            top = ", ".join(
                f"{(item['value'] if item['value'] is not None else 'NULL')}"
                f" ({item['count']:,})"
                for item in column.get("top_values", [])[:3]
            )
            lines.append(
                "| `{column}` | {data_type} | {nulls:,} | {rate} | {distinct:,} | {lo} | {hi} | {top} |".format(
                    column=column["column"],
                    data_type=column["data_type"],
                    nulls=column["nulls"],
                    rate=f"{column['null_rate']:.4%}" if column["null_rate"] is not None else "-",
                    distinct=column["distinct_values"],
                    lo=_truncate(column.get("min_value")),
                    hi=_truncate(column.get("max_value")),
                    top=top or "-",
                )
            )
        patterned = [c for c in profile["columns"] if c.get("patterns")]
        if patterned:
            lines += ["", "Pattern distribution of the code columns:", ""]
            for column in patterned:
                shapes = ", ".join(
                    f"`{item['pattern']}` ({item['count']:,})" for item in column["patterns"]
                )
                lines.append(f"- `{column['column']}`: {shapes}")
        lines.append("")
    config.PROFILE_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("wrote %s", config.PROFILE_MD.relative_to(config.PROJECT_ROOT))


def _truncate(value: Any, width: int = 24) -> str:
    """Shorten a value for display in a Markdown table cell.

    :param value: Value to render.
    :param width: Maximum number of characters to keep.
    :returns: A single-line string, truncated with an ellipsis marker.
    """
    if value is None:
        return "-"
    text = str(value).replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= width else text[: width - 3] + "..."


def write_candidates_markdown(findings: list[dict[str, Any]]) -> None:
    """Render the candidate defect list as Markdown.

    :param findings: Candidate findings from :func:`run_candidates`.
    :returns: ``None``.
    """
    present = [f for f in findings if f["count"] > 0]
    absent = [f for f in findings if f["count"] == 0]
    lines = [
        "# Candidate defects found by profiling",
        "",
        f"Generated by `make profile` at {db.utc_now_iso()} (git {db.git_commit()}).",
        "",
        "This list is written **before** the rules in `dq/dq_rules.yaml`, and it is",
        "what the rules were derived from. Each candidate is a hypothesis with a",
        "count attached; the count and the note together decide the severity.",
        "",
        "A candidate that returns zero is kept in the list on purpose: on this",
        "public copy of the dataset it does not fire, but the rule still ships,",
        "because the bank's own copy may carry exactly that defect.",
        "",
        f"## Present in this copy ({len(present)})",
        "",
        "| rows | candidate | what a non-zero count means |",
        "|---:|---|---|",
    ]
    for finding in present:
        lines.append(f"| {finding['count']:,} | {finding['label']} | {finding['note']} |")
    lines += [
        "",
        f"## Not present in this copy ({len(absent)})",
        "",
        "| candidate | why the rule ships anyway |",
        "|---|---|",
    ]
    for finding in absent:
        lines.append(f"| {finding['label']} | {finding['note']} |")
    lines += [
        "",
        "## How this feeds the rules",
        "",
        "Every candidate above maps to one or more `rule_id` values in",
        "`dq/dq_rules.yaml`, and every rule there carries a severity plus the",
        "reason for that severity in terms of the 10 questions. The mapping is",
        "visible in the `affects_questions` field of each rule and in the",
        "`Questions affected` column of `deliverables/defects.csv`.",
        "",
    ]
    config.CANDIDATES_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("wrote %s", config.CANDIDATES_MD.relative_to(config.PROJECT_ROOT))


def main() -> int:
    """Build the staging layer, profile it and write the candidate defect list.

    :returns: Process exit code, ``0`` on success.
    """
    config.DQ_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with db.connect(autocommit=True) as conn:
        LOGGER.info("--- building the staging layer ---")
        duration = db.run_sql_file(conn, config.SQL_DIR / "10_stg.sql", LOGGER)

        LOGGER.info("--- profiling every column ---")
        profiles = [profile_table(conn, table) for table in STG_TABLES]

        LOGGER.info("--- evaluating candidate defects ---")
        findings = run_candidates(conn)

    payload = {
        "generated_at_utc": db.utc_now_iso(),
        "git_commit": db.git_commit(),
        "stg_build_seconds": round(duration, 3),
        "tables": profiles,
        "candidates": findings,
    }
    config.PROFILE_JSON.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    LOGGER.info("wrote %s", config.PROFILE_JSON.relative_to(config.PROJECT_ROOT))
    write_profile_markdown(profiles)
    write_candidates_markdown(findings)

    present = sum(1 for f in findings if f["count"] > 0)
    LOGGER.info(
        "___ profile summary ___ tables=%d candidates=%d present=%d",
        len(profiles),
        len(findings),
        present,
    )
    db.record_run(
        "profile",
        "make profile",
        {
            "tables": {p["table"]: p["rows"] for p in profiles},
            "candidates_present": present,
            "candidates_total": len(findings),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
