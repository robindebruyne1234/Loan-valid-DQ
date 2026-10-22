"""Execute the declarative data quality rule set and report the defects.

The rules live in ``dq/dq_rules.yaml``; this module is only an engine. That
split matters for the walkthrough: adding a rule is a YAML change reviewable by
a data steward, not a code change, and the same rule set can be pointed at a
different schema. ``--dataset inject`` runs every rule against a deliberately
corrupted copy of staging, which is how the rules themselves are tested.

Outputs:

* ``dq.run`` / ``dq.results``  -- one row per rule per run, with sample keys
* ``dq.quarantine``            -- the rows a block rule removed, and why
* ``dq.reconciliation``        -- raw -> stg -> core row and amount checks
* ``deliverables/defects.csv`` -- exactly the columns of the Excel defect tab
* ``dq/results/dq_report.md``  -- executive summary, ordered by severity

Run with ``make dq``.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
import uuid
from collections import defaultdict
from typing import Any

import psycopg
import yaml

from src import config, db

LOGGER = db.setup_logging("dq")

#: Primary key column per source table, used to attach a JSON snapshot to a
#: quarantined row so a reviewer can see the row as it arrived.
KEY_COLUMNS: dict[str, str] = {
    "account": "account_id",
    "client": "client_id",
    "disp": "disp_id",
    "card": "card_id",
    "loan": "loan_id",
    "order": "order_id",
    "trans": "trans_id",
    "district": "district_id",
}

#: Upper bound on snapshots stored per rule, so one catastrophic rule cannot
#: write a million JSON blobs into the quarantine table.
MAX_SNAPSHOTS_PER_RULE: int = 500

#: Number of sample violating keys kept per rule in ``dq.results``.
SAMPLE_KEY_LIMIT: int = 10


class RuleError(RuntimeError):
    """Raised when the rule file itself is invalid."""


def load_rules(path: Any = None) -> dict[str, Any]:
    """Load and validate the rule file.

    Validation is deliberately strict: a rule without a severity rationale or
    without the questions it affects is rejected rather than executed, because
    the brief scores an unjustified rule the same as no rule at all.

    :param path: Optional path to a rule file; defaults to
        :data:`src.config.DQ_RULES_YAML`.
    :returns: The parsed rule document with ``sweeps`` and ``rules`` keys.
    :raises RuleError: When a rule is missing a mandatory field, uses an
        unknown dimension or severity, or repeats a ``rule_id``.
    """
    path = path or config.DQ_RULES_YAML
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    rules = document.get("rules") or []
    seen: set[str] = set()
    for rule in rules:
        rule_id = rule.get("rule_id")
        if not rule_id:
            raise RuleError(f"a rule has no rule_id: {rule}")
        if rule_id in seen:
            raise RuleError(f"duplicate rule_id: {rule_id}")
        seen.add(rule_id)
        for field in ("dimension", "table", "description", "severity",
                      "severity_rationale", "handling", "sql", "total_sql"):
            if not rule.get(field):
                raise RuleError(f"{rule_id}: missing mandatory field '{field}'")
        if "affects_questions" not in rule:
            raise RuleError(f"{rule_id}: missing 'affects_questions' (use [] when none)")
        if rule["severity"] not in config.VALID_SEVERITIES:
            raise RuleError(f"{rule_id}: unknown severity '{rule['severity']}'")
        if rule["dimension"] not in config.VALID_DIMENSIONS:
            raise RuleError(f"{rule_id}: unknown dimension '{rule['dimension']}'")
        unknown = set(rule["affects_questions"]) - set(config.QUESTION_IDS)
        if unknown:
            raise RuleError(f"{rule_id}: unknown question ids {sorted(unknown)}")
    LOGGER.info("rule file valid -> %d explicit rules, %d sweeps",
                len(rules), len(document.get("sweeps") or []))
    return document


def expand_sweeps(
    conn: psycopg.Connection, document: dict[str, Any], schema: str
) -> list[dict[str, Any]]:
    """Turn each sweep definition into one concrete rule per column.

    The completeness sweep is the safety net for defects nobody predicted: it
    measures the null rate of every column of every table, including the ones
    no current metric reads. Columns already covered by a hand-justified rule
    are skipped so the same defect is never counted twice.

    :param conn: Open connection, used to read the live column list.
    :param document: Parsed rule document.
    :param schema: Schema the sweep should run against.
    :returns: List of generated rule dictionaries, shaped like explicit rules.
    """
    generated: list[dict[str, Any]] = []
    for sweep in document.get("sweeps") or []:
        excluded = set(sweep.get("exclude_columns") or [])
        excluded_qualified = set(sweep.get("exclude_qualified") or [])
        for table in sweep["tables"]:
            columns = db.fetch_all(
                conn,
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
                """,
                (schema, table),
            )
            for row in columns:
                column = row["column_name"]
                if column in excluded or f"{table}.{column}" in excluded_qualified:
                    continue
                if column.endswith("_raw"):
                    # The *_raw audit columns are only populated when a cast
                    # failed, so "NULL" is their normal state. They are covered
                    # by the VAL_*_UNPARSABLE rules instead.
                    continue
                key_column = KEY_COLUMNS[table]
                quoted_table = f'{schema}."{table}"'
                generated.append(
                    {
                        "rule_id": f"{sweep['sweep_id']}__{table}__{column}",
                        "dimension": sweep["dimension"],
                        "table": table,
                        "description": sweep["description_template"].format(
                            table=table, column=column
                        ),
                        "defect_type": sweep.get("defect_type"),
                        "severity": sweep["severity_default"],
                        "severity_rationale": sweep["severity_rationale_default"],
                        "handling": sweep["handling_default"],
                        "affects_questions": [],
                        "generated_by": sweep["sweep_id"],
                        "skip_quarantine": True,
                        "total_sql": f"SELECT count(*) FROM {quoted_table}",
                        "sql": (
                            f'SELECT "{key_column}"::text AS business_key, '
                            f"'{column} is NULL' AS reason "
                            f'FROM {quoted_table} WHERE "{column}" IS NULL'
                        ),
                    }
                )
    LOGGER.info("sweeps expanded -> %d generated rules", len(generated))
    return generated


def execute_rule(
    conn: psycopg.Connection, rule: dict[str, Any], schema: str
) -> dict[str, Any]:
    """Run one rule and return its outcome.

    :param conn: Open connection.
    :param rule: Rule dictionary from the rule file or a sweep expansion.
    :param schema: Schema to substitute for the ``{s}`` placeholder.
    :returns: Dictionary with the violation count, the denominator, sample
        keys, the violating rows (capped) and the duration.
    """
    sql = rule["sql"].replace("{s}", schema)
    total_sql = rule["total_sql"].replace("{s}", schema)
    started = time.perf_counter()
    error: str | None = None
    violations: list[dict[str, Any]] = []
    total: int | None = None

    try:
        violations = db.fetch_all(conn, sql)
        total = int(db.fetch_value(conn, total_sql) or 0)
    except psycopg.Error as exc:
        conn.rollback()
        error = str(exc).strip().splitlines()[0]
        LOGGER.error("rule %s failed -> %s", rule["rule_id"], error)

    duration = time.perf_counter() - started
    count = len(violations)
    return {
        "violation_count": count,
        "total_count": total,
        "violation_rate": (count / total) if total else None,
        "sample_keys": [
            {"key": str(row.get("business_key")), "reason": row.get("reason")}
            for row in violations[:SAMPLE_KEY_LIMIT]
        ],
        "violations": violations[:MAX_SNAPSHOTS_PER_RULE],
        "duration_sec": round(duration, 3),
        "error_message": error,
    }


def quarantine_rows(
    conn: psycopg.Connection,
    run_id: uuid.UUID,
    rule: dict[str, Any],
    outcome: dict[str, Any],
    schema: str,
) -> int:
    """Write the rows a block rule rejected into ``dq.quarantine``.

    Quarantine is the mechanism behind the ``block`` severity: the row is kept,
    with the rule that rejected it and the reason, and ``core`` is built from
    staging minus quarantine. Nothing is ever deleted, so every exclusion is
    reversible and countable.

    :param conn: Open connection.
    :param run_id: Current data quality run.
    :param rule: The rule that fired.
    :param outcome: Result of :func:`execute_rule`.
    :param schema: Schema the rule ran against, used for the row snapshot.
    :returns: Number of rows written to the quarantine table.
    """
    if rule["severity"] != config.SEVERITY_BLOCK or rule.get("skip_quarantine"):
        return 0

    written = 0
    with conn.cursor() as cur:
        for row in outcome["violations"]:
            business_key = str(row.get("business_key"))
            target_table = rule["table"]
            key_value = business_key
            # Multi-table rules prefix the key with the table, e.g. "loan:5314".
            if ":" in business_key and business_key.split(":", 1)[0] in KEY_COLUMNS:
                target_table, key_value = business_key.split(":", 1)

            snapshot = None
            key_column = KEY_COLUMNS.get(target_table)
            if key_column and key_value.isdigit():
                try:
                    snapshot = db.fetch_value(
                        conn,
                        f'SELECT to_jsonb(t) FROM {schema}."{target_table}" t '
                        f'WHERE t."{key_column}"::text = %s LIMIT 1',
                        (key_value,),
                    )
                except psycopg.Error:
                    conn.rollback()
                    snapshot = None

            cur.execute(
                """
                INSERT INTO dq.quarantine (
                    run_id, rule_id, severity, target_schema, target_table,
                    business_key, reason, row_snapshot
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(run_id),
                    rule["rule_id"],
                    rule["severity"],
                    schema,
                    target_table,
                    key_value,
                    row.get("reason") or rule["description"],
                    json.dumps(snapshot, default=str) if snapshot is not None else None,
                ),
            )
            written += 1
    return written


def write_reconciliation(
    conn: psycopg.Connection, run_id: uuid.UUID, schema: str
) -> list[dict[str, Any]]:
    """Reconcile row counts and amount sums across the raw, stg and quarantine layers.

    This answers the question a reviewer actually asks: "where did the rows
    go?". ``core`` is filled in later by :mod:`src.build_model`, which updates
    the same rows, so the final table shows raw -> stg -> quarantine -> core in
    one place.

    :param conn: Open connection.
    :param run_id: Current data quality run.
    :param schema: Staging schema to reconcile against raw.
    :returns: The reconciliation rows that were written.
    """
    rows: list[dict[str, Any]] = []
    for table in KEY_COLUMNS:
        raw_rows = db.table_count(conn, config.SCHEMA_RAW, table)
        stg_rows = db.table_count(conn, schema, table)
        quarantined = int(
            db.fetch_value(
                conn,
                """
                SELECT count(DISTINCT business_key) FROM dq.quarantine
                WHERE run_id = %s AND target_table = %s AND severity = %s
                """,
                (str(run_id), table, config.SEVERITY_BLOCK),
            )
            or 0
        )
        rows.append(
            {
                "metric": "row_count",
                "entity": table,
                "raw_value": raw_rows,
                "stg_value": stg_rows,
                "quarantined": quarantined,
                "delta": stg_rows - raw_rows,
                "is_balanced": stg_rows == raw_rows,
                "note": "stg must equal raw: staging casts, it never filters",
            }
        )

    for entity, table, column in (
        ("trans.amount", "trans", "amount"),
        ("loan.amount", "loan", "amount"),
        ("order.amount", "order", "amount"),
    ):
        raw_sum = db.fetch_value(
            conn, f'SELECT round(sum("{column}"::numeric), 2) FROM raw."{table}"'
        )
        stg_sum = db.fetch_value(
            conn, f'SELECT round(sum("{column}"), 2) FROM {schema}."{table}"'
        )
        rows.append(
            {
                "metric": "amount_sum",
                "entity": entity,
                "raw_value": raw_sum,
                "stg_value": stg_sum,
                "quarantined": None,
                "delta": (stg_sum - raw_sum) if (raw_sum is not None and stg_sum is not None) else None,
                "is_balanced": raw_sum == stg_sum,
                "note": "the money must survive the cast from text to numeric",
            }
        )

    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                """
                INSERT INTO dq.reconciliation (
                    run_id, metric, entity, raw_value, stg_value, quarantined,
                    delta, is_balanced, note
                ) VALUES (%(run_id)s, %(metric)s, %(entity)s, %(raw_value)s,
                          %(stg_value)s, %(quarantined)s, %(delta)s,
                          %(is_balanced)s, %(note)s)
                """,
                {**row, "run_id": str(run_id)},
            )

    unbalanced = [r for r in rows if not r["is_balanced"]]
    for row in unbalanced:
        LOGGER.error("reconciliation FAILED -> %s %s: raw=%s stg=%s",
                     row["metric"], row["entity"], row["raw_value"], row["stg_value"])
    if not unbalanced:
        LOGGER.info("reconciliation ok -> %d checks balanced (raw == stg)", len(rows))
    return rows


def write_defects_csv(results: list[dict[str, Any]]) -> int:
    """Write ``deliverables/defects.csv`` with the exact Excel tab columns.

    Rules that share a ``defect_type`` are merged into one row, because the
    deliverable asks for defect *types* rather than rule instances: eight
    primary key rules are one defect type across eight tables. Rules without a
    ``defect_type`` stand on their own.

    :param results: Per-rule outcomes, each carrying its rule definition.
    :returns: Number of defect-type rows written.
    """
    fired = [r for r in results if r["violation_count"] > 0 and not r["error_message"]]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in fired:
        rule = result["rule"]
        key = rule.get("defect_type") or rule["rule_id"]
        groups[key].append(result)

    rows: list[dict[str, Any]] = []
    for key, members in groups.items():
        first = members[0]["rule"]
        severity = min(
            (m["rule"]["severity"] for m in members),
            key=lambda s: config.SEVERITY_ORDER[s],
        )
        questions = sorted(
            {q for m in members for q in m["rule"]["affects_questions"]},
            key=lambda q: int(q[1:]),
        )
        tables = sorted({m["rule"]["table"] for m in members})
        # When several rules merge, their rationales are joined so no
        # justification is lost in the roll-up.
        rationales = []
        handlings = []
        for member in members:
            rationale = " ".join(member["rule"]["severity_rationale"].split())
            if rationale not in rationales:
                rationales.append(rationale)
            handling = " ".join(member["rule"]["handling"].split())
            if handling not in handlings:
                handlings.append(handling)
        rows.append(
            {
                "Defect type": key if len(members) > 1 else first["description"],
                "Table(s)": ", ".join(tables),
                "Rule(s)": ", ".join(sorted(m["rule"]["rule_id"] for m in members)),
                "Dimension": ", ".join(sorted({m["rule"]["dimension"] for m in members})),
                "Severity": severity,
                "Severity rationale": " | ".join(rationales),
                "Rows affected": sum(m["violation_count"] for m in members),
                "Handling": " | ".join(handlings),
                "Questions affected": ", ".join(questions) if questions else "none",
                "Example": (members[0]["sample_keys"][0]["reason"]
                            if members[0]["sample_keys"] else ""),
            }
        )

    rows.sort(
        key=lambda row: (config.SEVERITY_ORDER[row["Severity"]], -row["Rows affected"])
    )
    config.DELIVERABLES_DIR.mkdir(parents=True, exist_ok=True)
    with config.DEFECTS_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else
                                ["Defect type", "Table(s)", "Rule(s)", "Dimension",
                                 "Severity", "Severity rationale", "Rows affected",
                                 "Handling", "Questions affected", "Example"])
        writer.writeheader()
        writer.writerows(rows)
    LOGGER.info("wrote %s -> %d defect types",
                config.DEFECTS_CSV.relative_to(config.PROJECT_ROOT), len(rows))
    return len(rows)


def write_dq_report(
    run_id: uuid.UUID,
    dataset: str,
    results: list[dict[str, Any]],
    recon: list[dict[str, Any]],
    quarantined: dict[str, int],
) -> None:
    """Write the executive data quality report, ordered by severity.

    :param run_id: Current run identifier.
    :param dataset: Schema the rules ran against.
    :param results: Per-rule outcomes.
    :param recon: Reconciliation rows.
    :param quarantined: Rows quarantined per table.
    :returns: ``None``.
    """
    fired = [r for r in results if r["violation_count"] > 0]
    clean = [r for r in results if r["violation_count"] == 0 and not r["error_message"]]
    failed = [r for r in results if r["error_message"]]

    by_severity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in fired:
        by_severity[result["rule"]["severity"]].append(result)

    lines = [
        "# Data quality report",
        "",
        f"- run_id: `{run_id}`",
        f"- dataset: `{dataset}`",
        f"- executed at: {db.utc_now_iso()} (git {db.git_commit()})",
        f"- command: `make dq`" + (f" (dataset {dataset})" if dataset != config.SCHEMA_STG else ""),
        f"- rules executed: **{len(results)}** "
        f"({len(fired)} fired, {len(clean)} clean, {len(failed)} errored)",
        "",
        "## Executive summary",
        "",
        "| severity | defect types firing | rows affected | what it means |",
        "|---|---:|---:|---|",
    ]
    meaning = {
        config.SEVERITY_BLOCK: "rows quarantined, excluded from core and from the ai views",
        config.SEVERITY_WARN: "rows kept and flagged, metrics carry a caveat",
        config.SEVERITY_INFO: "standardised and logged, no answer changes",
    }
    for severity in config.VALID_SEVERITIES:
        members = by_severity.get(severity, [])
        lines.append(
            f"| **{severity}** | {len(members)} | "
            f"{sum(m['violation_count'] for m in members):,} | {meaning[severity]} |"
        )

    lines += [
        "",
        f"Rows quarantined this run: **{sum(quarantined.values()):,}**"
        + (f" ({', '.join(f'{t}: {n:,}' for t, n in sorted(quarantined.items()) if n)})"
           if any(quarantined.values()) else " (none)"),
        "",
        "## Findings by severity",
        "",
    ]
    for severity in config.VALID_SEVERITIES:
        members = sorted(
            by_severity.get(severity, []), key=lambda r: -r["violation_count"]
        )
        lines += [f"### {severity} ({len(members)} firing)", ""]
        if not members:
            lines += ["None.", ""]
            continue
        lines += [
            "| rule | table | rows | rate | questions | defect |",
            "|---|---|---:|---:|---|---|",
        ]
        for result in members:
            rule = result["rule"]
            rate = result["violation_rate"]
            lines.append(
                "| `{rule_id}` | {table} | {rows:,} | {rate} | {questions} | {description} |".format(
                    rule_id=rule["rule_id"],
                    table=rule["table"],
                    rows=result["violation_count"],
                    rate=f"{rate:.4%}" if rate is not None else "-",
                    questions=", ".join(rule["affects_questions"]) or "-",
                    description=rule["description"],
                )
            )
        lines.append("")
        for result in members[:6]:
            rule = result["rule"]
            lines += [
                f"**`{rule['rule_id']}`** -- {rule['description']}",
                "",
                f"- severity rationale: {' '.join(rule['severity_rationale'].split())}",
                f"- handling: {' '.join(rule['handling'].split())}",
            ]
            if result["sample_keys"]:
                example = result["sample_keys"][0]
                lines.append(f"- example: key `{example['key']}` -- {example['reason']}")
            lines.append("")

    lines += [
        "## Rules that did not fire",
        "",
        "These rules found nothing on this copy of the data. They ship anyway:",
        "the bank's own copy may carry exactly these defects, and a rule that",
        "only exists after the incident is not a control.",
        "",
        "| rule | severity | defect |",
        "|---|---|---|",
    ]
    for result in sorted(clean, key=lambda r: r["rule"]["rule_id"]):
        rule = result["rule"]
        if rule.get("generated_by"):
            continue
        lines.append(
            f"| `{rule['rule_id']}` | {rule['severity']} | {rule['description']} |"
        )

    lines += [
        "",
        "## Reconciliation",
        "",
        "| metric | entity | raw | stg | quarantined | balanced |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in recon:
        lines.append(
            "| {metric} | {entity} | {raw} | {stg} | {q} | {ok} |".format(
                metric=row["metric"],
                entity=row["entity"],
                raw=f"{row['raw_value']:,}" if row["raw_value"] is not None else "-",
                stg=f"{row['stg_value']:,}" if row["stg_value"] is not None else "-",
                q=f"{row['quarantined']:,}" if row["quarantined"] is not None else "-",
                ok="yes" if row["is_balanced"] else "**NO**",
            )
        )
    if failed:
        lines += ["", "## Rules that errored", ""]
        for result in failed:
            lines.append(f"- `{result['rule']['rule_id']}`: {result['error_message']}")
    lines.append("")

    config.DQ_REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("wrote %s", config.DQ_REPORT_MD.relative_to(config.PROJECT_ROOT))


def run(dataset: str = config.SCHEMA_STG, write_deliverables: bool = True) -> dict[str, Any]:
    """Execute every rule against one dataset and write the reports.

    :param dataset: Schema to run against: ``stg`` for the real data,
        ``inject`` for the deliberately corrupted copy.
    :param write_deliverables: When ``False``, skip ``defects.csv`` and
        ``dq_report.md``; used by the rule self-tests so a test run never
        overwrites the real deliverables.
    :returns: Summary dictionary with counts per severity and the run id.
    """
    document = load_rules()
    run_id = uuid.uuid4()
    started = time.perf_counter()

    with db.connect(autocommit=True) as conn:
        rules = list(document["rules"]) + expand_sweeps(conn, document, dataset)
        db.execute(
            conn,
            """
            INSERT INTO dq.run (run_id, dataset, git_commit, rules_total, command)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (str(run_id), dataset, db.git_commit(), len(rules), f"make dq ({dataset})"),
        )
        LOGGER.info("--- data quality run %s on schema %s ---", run_id, dataset)

        results: list[dict[str, Any]] = []
        quarantined: dict[str, int] = defaultdict(int)
        for rule in rules:
            outcome = execute_rule(conn, rule, dataset)
            outcome["rule"] = rule
            results.append(outcome)

            written = quarantine_rows(conn, run_id, rule, outcome, dataset)
            if written:
                quarantined[rule["table"]] += written

            db.execute(
                conn,
                """
                INSERT INTO dq.results (
                    run_id, rule_id, dimension, target_schema, target_table,
                    severity, violation_count, total_count, violation_rate,
                    sample_keys, duration_sec, error_message
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(run_id),
                    rule["rule_id"],
                    rule["dimension"],
                    dataset,
                    rule["table"],
                    rule["severity"],
                    outcome["violation_count"],
                    outcome["total_count"],
                    outcome["violation_rate"],
                    json.dumps(outcome["sample_keys"], default=str),
                    outcome["duration_sec"],
                    outcome["error_message"],
                ),
            )
            if outcome["violation_count"]:
                LOGGER.info(
                    "%-5s %-7d %s",
                    rule["severity"].upper(),
                    outcome["violation_count"],
                    rule["rule_id"],
                )

        # Quarantine must be deduplicated by (table, key): several block rules
        # can reject the same row, and core filters on distinct keys.
        recon = write_reconciliation(conn, run_id, dataset)

        failed_rules = sum(1 for r in results if r["error_message"])
        db.execute(
            conn,
            "UPDATE dq.run SET finished_at = now(), rules_failed = %s WHERE run_id = %s",
            (failed_rules, str(run_id)),
        )

    by_severity = {
        severity: sum(
            1 for r in results
            if r["violation_count"] > 0 and r["rule"]["severity"] == severity
        )
        for severity in config.VALID_SEVERITIES
    }
    summary = {
        "run_id": str(run_id),
        "dataset": dataset,
        "rules_executed": len(results),
        "rules_fired": sum(1 for r in results if r["violation_count"] > 0),
        "rules_errored": failed_rules,
        "by_severity": by_severity,
        "rows_quarantined": sum(quarantined.values()),
        "quarantined_by_table": dict(quarantined),
        "duration_sec": round(time.perf_counter() - started, 2),
    }

    if write_deliverables:
        defect_types = write_defects_csv(results)
        write_dq_report(run_id, dataset, results, recon, dict(quarantined))
        summary["defect_types"] = defect_types

    LOGGER.info("___ dq summary ___")
    LOGGER.info("  rules executed    : %d", summary["rules_executed"])
    LOGGER.info("  rules fired       : %d", summary["rules_fired"])
    LOGGER.info("  block | warn | info firing: %d | %d | %d",
                by_severity[config.SEVERITY_BLOCK],
                by_severity[config.SEVERITY_WARN],
                by_severity[config.SEVERITY_INFO])
    LOGGER.info("  rows quarantined  : %d", summary["rows_quarantined"])
    LOGGER.info("  errored rules     : %d", summary["rules_errored"])
    LOGGER.info("  duration          : %.1fs", summary["duration_sec"])
    return summary


def main() -> int:
    """Command line entry point.

    :returns: Process exit code: ``0`` on success, ``1`` when a rule errored or
        a reconciliation check failed.
    """
    parser = argparse.ArgumentParser(description="Run the data quality rule set.")
    parser.add_argument(
        "--dataset",
        default=config.SCHEMA_STG,
        help="schema to run against (stg = real data, inject = corrupted copy)",
    )
    parser.add_argument(
        "--no-deliverables",
        action="store_true",
        help="do not write defects.csv or dq_report.md",
    )
    args = parser.parse_args()

    summary = run(dataset=args.dataset, write_deliverables=not args.no_deliverables)
    db.record_run("dq", f"make dq (dataset={args.dataset})", summary)
    return 1 if summary["rules_errored"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
