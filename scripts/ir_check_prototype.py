"""PROTOTYPE for docs/SEMANTIC_MODEL_AUDIT.md -- not used by the pipeline or the web app.

SUPERSEDED by src/sql_ir.py (DECISIONS.md D029), which the question runner and
the web app now call on every answer. Kept unchanged as the evidence behind
§2.5 of the audit; do not extend it.

Shows that a small intermediate representation (IR) of a question lets the
application check generated SQL *before* trusting it, in two layers:

1. Static checks with sqlglot against the semantic layer: the metric is
   certified, its entity is queried, every join is a declared path and none
   fans out the counted entity, the period filter is on the metric's
   time_column, and every requested year and quarter bound appears.
2. Differential execution: the IR compiles deterministically to canonical SQL
   for a certified metric; the generated SQL's result must contain the same
   (period, value) pairs, compared with src.evaluate's tolerance.

Read-only. Usage: python scripts/ir_check_prototype.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import sqlglot
from sqlglot import exp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db, evaluate, semantic_context, sql_guard  # noqa: E402
from src.run_questions import jsonable  # noqa: E402

QUARTER_END_MONTH = {1: 4, 2: 7, 3: 10, 4: 1}


def periods(years: list[int], quarters: list[int]) -> list[dict[str, Any]]:
    """Expand years x a contiguous quarter range into half-open date ranges."""
    first, last = min(quarters), max(quarters)
    out = []
    for year in years:
        start = f"{year}-{3 * (first - 1) + 1:02d}-01"
        end_year = year + 1 if last == 4 else year
        end = f"{end_year}-{QUARTER_END_MONTH[last]:02d}-01"
        out.append({"label": year, "from": start, "to": end})
    return out


def compile_ir(ir: dict[str, Any], layer: dict[str, Any]) -> str:
    """Deterministic SQL for a certified metric, one row per period."""
    metric = next(m for m in layer["metrics"] if m["name"] == ir["metric"])
    col = ir["time"]["column"]
    cases = " ".join(
        f"WHEN {col} >= DATE '{p['from']}' AND {col} < DATE '{p['to']}' THEN {p['label']}"
        for p in ir["time"]["periods"])
    where = " OR ".join(
        f"({col} >= DATE '{p['from']}' AND {col} < DATE '{p['to']}')" for p in ir["time"]["periods"])
    if metric.get("filter"):
        where = f"({where}) AND {metric['filter']}"
    return (f"SELECT CASE {cases} END AS period, {metric['expression']} AS value "
            f"FROM {metric['entity']} WHERE {where} GROUP BY 1 ORDER BY 1")


def static_check(sql: str, ir: dict[str, Any], layer: dict[str, Any]) -> list[str]:
    """Findings that need no execution. Empty list = consistent with the IR."""
    findings: list[str] = []
    metrics = {m["name"]: m for m in layer["metrics"]}
    if ir["metric"] not in metrics:
        return [f"unsupported metric '{ir['metric']}': route to review, do not answer"]
    metric = metrics[ir["metric"]]
    tree = sqlglot.parse_one(sql, read="postgres")

    tables = {f"{t.db}.{t.name}" for t in tree.find_all(exp.Table) if t.db}
    if metric["entity"] not in tables:
        findings.append(f"metric entity {metric['entity']} is not queried (found {sorted(tables)})")

    declared = {}
    for entity in layer["entities"]:
        for join in entity.get("joins") or []:
            declared[(entity["name"], join["to"])] = join["cardinality"]
    for other in sorted(tables - {metric["entity"]}):
        card = declared.get((metric["entity"], other))
        if card is None:
            findings.append(f"join {metric['entity']} -> {other} is not a declared path")
        elif card.endswith("to-many") and "DISTINCT" not in sql.upper():
            findings.append(f"join {metric['entity']} -> {other} is {card}: the measure fans out")

    where_sql = " ".join(w.sql() for w in tree.find_all(exp.Where)) + " " + " ".join(
        j.sql() for j in tree.find_all(exp.Join))
    time_col = ir["time"]["column"]
    if time_col not in where_sql:
        findings.append(f"no filter or join on the metric's time_column {time_col}")
    for p in ir["time"]["periods"]:
        if str(p["label"]) not in sql:
            findings.append(f"requested year {p['label']} does not appear in the SQL")
    quarters = ir["time"].get("quarters")
    if quarters and quarters != [1, 2, 3, 4]:
        month_bound = f"-{QUARTER_END_MONTH[max(quarters)]:02d}-01" in sql or f", {QUARTER_END_MONTH[max(quarters)]}, 1)" in sql
        quarter_bound = "QUARTER" in sql.upper()
        if not (month_bound or quarter_bound):
            findings.append(f"no quarter or month bound for Q{min(quarters)}-Q{max(quarters)}")
    return findings


def differential_check(sql: str, ir: dict[str, Any], layer: dict[str, Any], conn: Any) -> list[str]:
    """Run canonical and generated SQL; every canonical (period, value) must appear."""
    canonical = db.fetch_all(conn, compile_ir(ir, layer))
    verdict = sql_guard.guard(sql)
    if not verdict.allowed:
        return [f"guard rejected: {verdict.violations}"]
    # Same conversion the question runner applies before scoring: the
    # evaluator's numeric() does not read Decimal.
    generated = [{k: jsonable(v) for k, v in row.items()}
                 for row in db.fetch_all(conn, verdict.rewritten_sql)]
    missing = [f"{row['period']}={row['value']}" for row in canonical
               if not any(evaluate.row_matches(g, (row["period"],), float(row["value"])) for g in generated)]
    return [f"result lacks canonical values {missing}"] if missing else []


IR_Q1_Q3 = {
    "question": "Compare the total amount of loans granted in Q1-Q3 of 1995 with Q1-Q3 of 1998.",
    "metric": "total_loan_amount", "entity": "ai.loan", "counting_grain": "loan_id",
    "aggregation": "sum(amount)",
    "time": {"column": "loan_date", "calendar_grain": "quarter", "quarters": [1, 2, 3],
             "periods": periods([1995, 1998], [1, 2, 3])},
    "group_by": ["period"], "filters": [],
    "comparison": {"type": "period_vs_period", "periods": [1995, 1998]},
}
IR_Q1_ONLY = dict(IR_Q1_Q3, question="... Q1 only of 1995 and 1998",
                  time={"column": "loan_date", "calendar_grain": "quarter", "quarters": [1],
                        "periods": periods([1995, 1998], [1])})

CASES = [
    ("A  correct, half-open ranges", IR_Q1_Q3, """SELECT loan_year, sum(amount) AS total FROM ai.loan
        WHERE (loan_date >= DATE '1995-01-01' AND loan_date < DATE '1995-10-01')
           OR (loan_date >= DATE '1998-01-01' AND loan_date < DATE '1998-10-01') GROUP BY loan_year"""),
    ("A' correct, calendar quarters", IR_Q1_Q3, """SELECT c.year, sum(l.amount) AS total FROM ai.loan l
        JOIN ai.calendar c ON c.date_key = l.loan_date
        WHERE c.year IN (1995, 1998) AND c.quarter BETWEEN 1 AND 3 GROUP BY c.year"""),
    ("B  quarter bound dropped", IR_Q1_Q3,
     "SELECT loan_year, sum(amount) AS total FROM ai.loan WHERE loan_year IN (1995, 1998) GROUP BY loan_year"),
    ("C  1995 dropped", IR_Q1_Q3, """SELECT loan_year, sum(amount) AS total FROM ai.loan
        WHERE loan_year = 1998 AND extract(quarter FROM loan_date) <= 3 GROUP BY loan_year"""),
    ("D  years dropped", IR_Q1_Q3, """SELECT loan_year, sum(amount) AS total FROM ai.loan
        WHERE extract(quarter FROM loan_date) <= 3 GROUP BY loan_year"""),
    ("E  fan-out via transactions", IR_Q1_Q3, """SELECT l.loan_year, sum(l.amount) AS total FROM ai.loan l
        JOIN ai.transaction t ON t.account_id = l.account_id
        WHERE l.loan_year IN (1995, 1998) AND extract(quarter FROM l.loan_date) <= 3 GROUP BY l.loan_year"""),
    ("F  wrong date (account open_date)", IR_Q1_Q3, """SELECT extract(year FROM a.open_date) AS yr, sum(l.amount) AS total
        FROM ai.loan l JOIN ai.account a ON a.account_id = l.account_id
        WHERE extract(year FROM a.open_date) IN (1995, 1998) AND extract(quarter FROM a.open_date) <= 3 GROUP BY 1"""),
    ("G  'Q1' read as question 1", IR_Q1_Q3, "SELECT region, count(*) AS clients FROM ai.client GROUP BY region"),
    ("H  Q1 only, correct", IR_Q1_ONLY, """SELECT loan_year, sum(amount) AS total FROM ai.loan
        WHERE loan_year IN (1995, 1998) AND extract(quarter FROM loan_date) = 1 GROUP BY loan_year"""),
    ("I  model output, old pack", IR_Q1_Q3, """WITH periods AS (SELECT 1995 AS yr UNION ALL SELECT 1998), agg AS
        (SELECT l.loan_year AS yr, count(*) AS loan_count, sum(l.amount) AS total_loan_amount FROM ai.loan AS l
        WHERE l.loan_year IN (1995, 1998) AND l.loan_date >= make_date(l.loan_year, 1, 1)
        AND l.loan_date < make_date(l.loan_year, 10, 1) GROUP BY l.loan_year)
        SELECT p.yr AS loan_year, COALESCE(a.loan_count, 0) AS loan_count,
        COALESCE(a.total_loan_amount, 0) AS total_loan_amount FROM periods AS p LEFT JOIN agg AS a ON a.yr = p.yr"""),
]


def main() -> int:
    """Run every case through both checks and print a table."""
    layer = semantic_context.load_semantic_layer()
    print("canonical SQL for the example IR:\n  " + compile_ir(IR_Q1_Q3, layer) + "\n")
    with db.connect() as conn:
        conn.rollback()
        conn.read_only = True
        for label, ir, sql in CASES:
            static = static_check(sql, ir, layer)
            diff = differential_check(sql, ir, layer, conn)
            status = "PASS" if not static and not diff else "FLAG"
            print(f"{label:36s} {status}  static={static or '-'}  differential={diff or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
