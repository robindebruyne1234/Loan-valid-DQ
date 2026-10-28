"""Compare the LLM's answers with the hand-written reference answers.

The comparison is deliberately value-based rather than text-based. Two correct
queries will name their columns differently (``clients`` versus
``client_count``) and may return extra supporting columns, so comparing SQL or
column names would measure style. What matters is whether the numbers the
business user sees are the right ones.

For each question an expectation is extracted from the reference result as a
set of (dimension value -> measure value) pairs, or as a set of scalar values
where the answer has no dimension. The LLM's result is then searched for each
expected pair: a dimension cell that matches and, on the same row, a numeric
cell equal to the expected measure within tolerance. Order is checked
separately where the question asks for a ranking.

Verdicts:

``match``
    every expected value found, and the ordering holds where it matters.
``partial``
    some expected values found. The detail names exactly which are missing.
``mismatch``
    none found, or the query returned nothing.
``not_executed``
    no LLM answer exists for the question.

Only a question the runner recorded as ``answered`` -- every check of
:mod:`src.sql_ir` passed -- is compared; a refused answer is ``not_executed``
with the refusal as its note.

Run with ``make evaluate``; ``--suite extra`` evaluates the additional
questions, and ``--llm``/``--out`` evaluate another provider's results file
into its own evaluation file.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from src import config, db

LOGGER = db.setup_logging("evaluate")

#: Tolerance when comparing two numbers. It exists for exactly one reason: the
#: reference answers round to two decimals and a model's answer may not, so
#: 43808.9388 must match 43808.94. An ABSOLUTE half-cent absorbs that.
#:
#: A relative tolerance must not be used for this. At 1e-4 -- which this
#: evaluator originally carried -- the Q5 top district of 115,130,200.10 CZK
#: would accept an answer wrong by 11,513 CZK and report it as a match. The
#: relative term is therefore kept only to absorb floating point
#: representation error, which is what 1e-9 is for.
ABSOLUTE_TOLERANCE = 0.011
RELATIVE_TOLERANCE = 1e-9

#: Per question: which reference columns may carry the dimension, which carry
#: the measures, and whether the order of rows is part of the answer.
#: ``dimensions = []`` means the answer is a single scalar row.
#:
#: Several dimension columns are listed per question on purpose. A dimension
#: usually has more than one correct published representation -- a month is
#: `1996-01`, `1` or `January`, a district is a name or an id -- and a correct
#: answer may use any of them. An answer is credited when ANY representation
#: of the expected key appears on a row that also carries the expected measure,
#: which keeps the comparison about the numbers rather than about labelling
#: taste. (This cost Q6 a false mismatch on the first run: the model returned
#: `1996-01` with exactly the reference counts while the evaluator was looking
#: for the integer 1.)
EXPECTATIONS: dict[str, dict[str, Any]] = {
    "Q1":  {"dimensions": ["region"],                         "measures": ["clients"],                   "ordered": False},
    "Q2":  {"dimensions": ["year"],                           "measures": ["total_amount"],              "ordered": False},
    "Q3":  {"dimensions": [],                                 "measures": ["problematic_pct", "problematic_loans", "total_loans"], "ordered": False},
    "Q4":  {"dimensions": ["owner_card_type"],                "measures": ["average_loan_amount"],       "ordered": False},
    "Q5":  {"dimensions": ["district_name", "district_id"],   "measures": ["total_incoming_amount"],     "ordered": True},
    "Q6":  {"dimensions": ["year_month", "month_number", "month_name"], "measures": ["accounts_opened"], "ordered": True},
    "Q7":  {"dimensions": ["loan_status", "status_code"],     "measures": ["average_age_at_loan_start"], "ordered": False},
    "Q8":  {"dimensions": ["gender"],                         "measures": ["gold_card_owners"],          "ordered": False},
    "Q9":  {"dimensions": [],                                 "measures": ["average_balance"],           "ordered": False},
    "Q10": {"dimensions": ["statement_frequency"],            "measures": ["problematic_pct"],           "ordered": True},
}

#: The additional suite (sql/61_reference_extra.sql), same structure.
EXTRA_EXPECTATIONS: dict[str, dict[str, Any]] = {
    "E1": {"dimensions": ["gender"],   "measures": ["loans"],        "ordered": False},
    "E2": {"dimensions": ["year"],     "measures": ["total_amount"], "ordered": False},
    "E3": {"dimensions": [],           "measures": ["new_accounts"], "ordered": False},
    "E4": {"dimensions": ["quarter"],  "measures": ["loans"],        "ordered": False},
}

EXPECTATIONS_BY_SUITE: dict[str, dict[str, dict[str, Any]]] = {
    "core": EXPECTATIONS,
    "extra": EXTRA_EXPECTATIONS,
}


def numeric(value: Any) -> float | None:
    """Coerce a value to a float when it is numeric.

    :param value: Value from a result row.
    :returns: The float, or ``None`` when the value is not numeric. Booleans
        are not treated as numbers, because ``True == 1`` would create false
        matches against a count of one.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().replace(",", ""))
        except ValueError:
            return None
    return None


def close(left: float, right: float) -> bool:
    """Compare two numbers with a relative tolerance.

    :param left: First value.
    :param right: Second value.
    :returns: ``True`` when the two are equal within the tolerance.
    """
    return math.isclose(left, right, rel_tol=RELATIVE_TOLERANCE, abs_tol=ABSOLUTE_TOLERANCE)


def cell_is_key(value: Any, keys: tuple[Any, ...]) -> bool:
    """Check whether one cell holds any accepted representation of a key.

    :param value: A cell from the LLM's result row.
    :param keys: Accepted representations of the expected dimension value.
    :returns: ``True`` when the cell equals one of them, as text or as a number.
    """
    text = str(value).strip().lower()
    cell_number = numeric(value)
    for key in keys:
        if key is None:
            continue
        if text == str(key).strip().lower():
            return True
        key_number = numeric(key)
        if cell_number is not None and key_number is not None and close(cell_number, key_number):
            return True
    return False


def row_matches(row: dict[str, Any], keys: tuple[Any, ...], measure: float) -> bool:
    """Check whether one result row carries the expected dimension and measure.

    :param row: A row from the LLM's result.
    :param keys: Accepted representations of the expected dimension value;
        empty for a scalar answer.
    :param measure: Expected measure value.
    :returns: ``True`` when the row contains both.
    """
    if keys and not any(cell_is_key(value, keys) for value in row.values()):
        return False
    return any(
        (candidate := numeric(value)) is not None and close(candidate, measure)
        for value in row.values()
    )


def evaluate_question(
    question_id: str, reference: dict[str, Any], llm: dict[str, Any] | None,
    expectations: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate one question's LLM answer against the reference answer.

    :param question_id: Question identifier.
    :param reference: The reference result entry.
    :param llm: The LLM result entry, or ``None`` when absent.
    :param expectations: The suite's expectations (default: the brief's ten).
    :returns: A verdict dictionary with the matched and missing values.
    """
    spec = (expectations or EXPECTATIONS)[question_id]
    reference_rows = reference["rows"]

    expected: list[tuple[tuple[Any, ...], str, float]] = []
    for row in reference_rows:
        keys = tuple(
            row[column] for column in spec["dimensions"]
            if column in row and row[column] is not None
        )
        for measure_column in spec["measures"]:
            value = numeric(row.get(measure_column))
            if value is not None:
                expected.append((keys, measure_column, value))

    if llm is None or llm.get("status") != "answered":
        return {
            "question_id": question_id,
            "verdict": "not_executed",
            "expected_values": len(expected),
            "matched_values": 0,
            "missing": [
                {"key": keys[0] if keys else None, "measure": column, "value": value}
                for keys, column, value in expected
            ],
            "note": (llm or {}).get("error") or config.NOT_EXECUTED,
            "llm_status": (llm or {}).get("status", config.NOT_EXECUTED),
        }

    llm_rows = llm["rows"]
    matched: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for keys, column, value in expected:
        label = keys[0] if keys else None
        if any(row_matches(row, keys, value) for row in llm_rows):
            matched.append({"key": label, "measure": column, "value": value})
        else:
            missing.append({"key": label, "measure": column, "value": value})

    order_ok = True
    order_note = ""
    if spec["ordered"] and spec["dimensions"]:
        # The expected sequence of keys, each as its set of accepted
        # representations, so a ranking in any labelling can be compared.
        reference_order = [
            tuple(
                row[column] for column in spec["dimensions"]
                if column in row and row[column] is not None
            )
            for row in reference_rows
        ]
        seen: list[int] = []
        for row in llm_rows:
            for index, keys in enumerate(reference_order):
                if index in seen:
                    continue
                if any(cell_is_key(value, keys) for value in row.values()):
                    seen.append(index)
                    break
        order_ok = seen == list(range(len(reference_order)))
        if not order_ok:
            order_note = (
                f"row order differs: the reference ranks "
                f"{[str(k[0]) for k in reference_order[:4]]}..., the answer "
                f"produced positions {seen[:6]}..."
            )

    if not missing and order_ok:
        verdict = "match"
    elif matched:
        verdict = "partial"
    else:
        verdict = "mismatch"

    return {
        "question_id": question_id,
        "verdict": verdict,
        "expected_values": len(expected),
        "matched_values": len(matched),
        "missing": missing,
        "order_checked": bool(spec["ordered"]),
        "order_ok": order_ok,
        "note": order_note,
        "llm_status": llm["status"],
        "llm_row_count": llm.get("row_count"),
        "reference_row_count": reference["row_count"],
        "attempts_used": llm.get("attempts_used"),
    }


def main() -> int:
    """Evaluate every question of a suite and write its evaluation file.

    :returns: Process exit code: ``0`` when every question matches, ``1``
        otherwise. A non-zero exit is information, not a build failure: the
        point of the evaluation is to report honestly on the model.
    """
    parser = argparse.ArgumentParser(description="Evaluate LLM answers against the reference.")
    parser.add_argument("--suite", choices=sorted(config.SUITES), default="core")
    parser.add_argument("--llm", type=Path, help="LLM results file (default: the suite's own)")
    parser.add_argument("--out", type=Path, help="evaluation file (default: the suite's own)")
    args = parser.parse_args()
    suite = config.SUITES[args.suite]
    expectations = EXPECTATIONS_BY_SUITE[args.suite]
    llm_path: Path = args.llm or suite["llm_json"]
    out_path: Path = args.out or suite["evaluation_json"]
    if args.llm and not args.out and llm_path.resolve() != suite["llm_json"].resolve():
        LOGGER.error("--llm names another results file: give --out too, so the "
                     "official evaluation is not overwritten")
        return 1

    if not suite["reference_json"].exists():
        LOGGER.error("no reference results; run 'make reference' (--suite %s) first", args.suite)
        return 1
    reference = json.loads(suite["reference_json"].read_text(encoding="utf-8"))["results"]
    llm_payload = (
        json.loads(llm_path.read_text(encoding="utf-8"))
        if llm_path.exists()
        else {"results": {}}
    )
    llm_results = llm_payload.get("results", {})

    verdicts = [
        evaluate_question(question_id, reference[question_id], llm_results.get(question_id),
                          expectations)
        for question_id in expectations
    ]

    tally: dict[str, int] = {}
    for verdict in verdicts:
        tally[verdict["verdict"]] = tally.get(verdict["verdict"], 0) + 1

    payload = {
        "generated_at_utc": db.utc_now_iso(),
        "git_commit": db.git_commit(),
        "command": f"make evaluate (suite={args.suite})",
        "suite": args.suite,
        "reference_source": f"{suite['reference_sql'].relative_to(config.PROJECT_ROOT)} (hand written)",
        "llm_results_file": str(llm_path),
        "llm_provider": llm_payload.get("provider"),
        "llm_model": llm_payload.get("model"),
        "llm_run_as_role": llm_payload.get("run_as_role"),
        "comparison_method": (
            "value based: every (dimension, measure) pair in the reference answer "
            "must appear on some row of the LLM answer, within an absolute "
            f"tolerance of {ABSOLUTE_TOLERANCE} (enough to absorb two-decimal "
            "rounding, not enough to absorb a wrong number); row order is "
            "additionally checked for the questions that ask for a ranking"
        ),
        "tally": tally,
        "verdicts": verdicts,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    LOGGER.info("___ evaluation ___")
    for verdict in verdicts:
        LOGGER.info(
            "  %-4s %-12s %2d/%-2d values%s%s",
            verdict["question_id"],
            verdict["verdict"],
            verdict["matched_values"],
            verdict["expected_values"],
            "  order ok" if verdict.get("order_checked") and verdict.get("order_ok") else "",
            f"  ! {verdict['note']}" if verdict.get("note") else "",
        )
        for item in verdict["missing"][:3]:
            LOGGER.warning(
                "       missing: %s %s = %s", item["key"], item["measure"], item["value"]
            )
    LOGGER.info("  tally: %s", ", ".join(f"{k}={v}" for k, v in sorted(tally.items())))
    LOGGER.info("wrote %s", out_path)

    db.record_run("evaluate", f"make evaluate (suite={args.suite})",
                  {"suite": args.suite, "llm_results_file": str(llm_path), "tally": tally})
    return 0 if tally.get("match", 0) == len(expectations) else 1


if __name__ == "__main__":
    raise SystemExit(main())
