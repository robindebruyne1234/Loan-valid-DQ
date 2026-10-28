"""Execute the hand-written reference queries and store the ground truth.

The reference answers are the yardstick the LLM is measured against, so three
properties matter more than anything else here:

* they are hand written (``sql/60_reference_queries.sql``, and
  ``sql/61_reference_extra.sql`` for the additional suite), by a person, from
  the question text -- not generated and not derived from the model's output;
* they are executed, with the command and timestamp recorded, so every number
  in the deliverables has a provenance entry in ``dq/results/run_log.jsonl``;
* they never reach the LLM. The context pack rendered by
  :mod:`src.semantic_context` contains the model's structure and business
  meaning, and no answers.

Run with ``make reference``; ``--suite extra`` runs the additional questions
into their own results file.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from decimal import Decimal
from typing import Any

from src import config, db

LOGGER = db.setup_logging("reference")

#: Marker that starts a labelled query block in the reference SQL file.
QUERY_MARKER = re.compile(r"^--\s*@@([A-Z]+\d+)\s*$", re.MULTILINE)


def parse_reference_sql(sql_text: str) -> dict[str, dict[str, str]]:
    """Split the reference SQL file into one labelled query per question.

    :param sql_text: Contents of ``sql/60_reference_queries.sql``.
    :returns: Mapping of question id to ``{"sql": ..., "interpretation": ...}``,
        where the interpretation is the comment block above the statement.
    """
    queries: dict[str, dict[str, str]] = {}
    matches = list(QUERY_MARKER.finditer(sql_text))
    for index, match in enumerate(matches):
        question_id = match.group(1)
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(sql_text)
        block = sql_text[start:end].strip()

        comment_lines: list[str] = []
        sql_lines: list[str] = []
        for line in block.splitlines():
            if line.lstrip().startswith("--") and not sql_lines:
                comment_lines.append(line.lstrip().lstrip("-").strip())
            else:
                sql_lines.append(line)
        statement = "\n".join(sql_lines).strip().rstrip(";")
        queries[question_id] = {
            "sql": statement,
            "interpretation": "\n".join(line for line in comment_lines if line),
        }
    return queries


def jsonable(value: Any) -> Any:
    """Convert a database value into something ``json.dumps`` accepts.

    :param value: Value from a query result.
    :returns: A JSON-serialisable equivalent; ``Decimal`` becomes ``float``,
        dates become ISO strings.
    """
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def load_questions(suite: str = "core") -> dict[str, str]:
    """Read a suite's questions, in file order.

    :param suite: A key of :data:`config.SUITES`.
    :returns: Mapping of question id to question text.
    """
    with config.SUITES[suite]["questions"].open(encoding="utf-8") as handle:
        return {row["id"]: row["question"] for row in csv.DictReader(handle)}


def main() -> int:
    """Run every reference query of a suite and write its results file.

    :returns: Process exit code: ``0`` on success, ``1`` when a question has no
        reference query or a query fails.
    """
    parser = argparse.ArgumentParser(description="Run the hand-written reference queries.")
    parser.add_argument("--suite", choices=sorted(config.SUITES), default="core")
    args = parser.parse_args()
    suite = config.SUITES[args.suite]
    questions = load_questions(args.suite)
    question_ids = config.QUESTION_IDS if args.suite == "core" else tuple(questions)
    queries = parse_reference_sql(suite["reference_sql"].read_text(encoding="utf-8"))

    missing = [q for q in question_ids if q not in queries]
    if missing:
        LOGGER.error("no reference query for: %s", ", ".join(missing))
        return 1

    results: dict[str, Any] = {}
    failures: list[str] = []
    with db.connect() as conn:
        for question_id in question_ids:
            entry = queries[question_id]
            try:
                rows = db.fetch_all(conn, entry["sql"])
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                conn.rollback()
                LOGGER.error("%s FAILED -> %s", question_id, str(exc).splitlines()[0])
                failures.append(question_id)
                continue
            clean_rows = [
                {key: jsonable(value) for key, value in row.items()} for row in rows
            ]
            results[question_id] = {
                "question": questions[question_id],
                "label": "REFERENCE (hand-written)",
                "sql": entry["sql"],
                "interpretation": entry["interpretation"],
                "columns": list(rows[0].keys()) if rows else [],
                "row_count": len(clean_rows),
                "rows": clean_rows,
                "executed_at_utc": db.utc_now_iso(),
            }
            headline = clean_rows[0] if clean_rows else {}
            LOGGER.info(
                "%-4s %2d rows | %s",
                question_id,
                len(clean_rows),
                ", ".join(f"{k}={v}" for k, v in list(headline.items())[:4]),
            )

    payload = {
        "generated_at_utc": db.utc_now_iso(),
        "git_commit": db.git_commit(),
        "source": str(suite["reference_sql"].relative_to(config.PROJECT_ROOT)),
        "suite": args.suite,
        "label": "REFERENCE (hand-written, never shown to the LLM)",
        "command": f"make reference (suite={args.suite})",
        "results": results,
    }
    suite["reference_json"].write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    LOGGER.info("wrote %s", suite["reference_json"].relative_to(config.PROJECT_ROOT))

    db.record_run(
        "reference",
        f"make reference (suite={args.suite})",
        {"suite": args.suite, "questions": len(results), "failures": failures},
    )
    if failures:
        return 1
    LOGGER.info("___ all %d reference answers computed ___", len(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
