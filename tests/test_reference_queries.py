"""Sanity-check the hand-written reference answers.

These tests do not re-implement the queries -- that would only test the test.
They assert the invariants a wrong answer would break: published cross-checks,
completeness of groupings, percentages that sum to 100, and agreement between
answers that share a population (Q2, Q3, Q4 and Q10 all count the same 682
loans).
"""

from __future__ import annotations

import json

import pytest

from src import config, db, run_reference


@pytest.fixture(scope="module")
def reference() -> dict:
    """Load the stored reference results, computing them if absent.

    :returns: The ``results`` mapping from ``reference_results.json``.
    """
    if not config.REFERENCE_RESULTS_JSON.exists():
        assert run_reference.main() == 0
    payload = json.loads(config.REFERENCE_RESULTS_JSON.read_text(encoding="utf-8"))
    return payload["results"]


def test_every_question_has_an_answer(reference: dict) -> None:
    """All ten questions must have a reference answer with at least one row."""
    for question_id in config.QUESTION_IDS:
        assert question_id in reference, f"{question_id} has no reference answer"
        assert reference[question_id]["row_count"] > 0, question_id


def test_every_reference_query_documents_its_interpretation(reference: dict) -> None:
    """Each reference query must carry the reading it implements.

    Ambiguity is the main source of disagreement with a reference value, so an
    undocumented interpretation is treated as a defect.
    """
    for question_id in config.QUESTION_IDS:
        interpretation = reference[question_id]["interpretation"]
        assert "Interpretation" in interpretation, (
            f"{question_id}: no documented interpretation"
        )
        assert len(interpretation) > 120, f"{question_id}: interpretation too thin"


def test_q1_clients_per_region_sums_to_the_client_count(reference: dict) -> None:
    """Q1's regional counts must add up to the total number of clients."""
    rows = reference["Q1"]["rows"]
    total = sum(row["clients"] for row in rows)
    assert total == config.REFERENCE_ROW_COUNTS["client"], (
        f"regions sum to {total}, expected {config.REFERENCE_ROW_COUNTS['client']}"
    )
    assert abs(sum(row["pct_of_clients"] for row in rows) - 100.0) < 0.05


def test_q2_loan_years_are_inside_the_dataset_window(reference: dict) -> None:
    """Q2 must only report years the dataset covers, and all 682 loans."""
    rows = reference["Q2"]["rows"]
    years = [row["year"] for row in rows]
    assert min(years) >= config.DATA_MIN_DATE.year
    assert max(years) <= config.DATA_MAX_DATE.year
    assert sum(row["loans"] for row in rows) == config.REFERENCE_ROW_COUNTS["loan"]


def test_q3_matches_the_published_cross_check(reference: dict) -> None:
    """Q3 must reproduce the documented 76 of 682 (about 11.14 percent).

    This is the one answer the brief itself suggests cross-checking, so it is
    pinned exactly rather than approximately.
    """
    row = reference["Q3"]["rows"][0]
    assert row["total_loans"] == config.REFERENCE_ROW_COUNTS["loan"]
    assert row["problematic_loans"] == config.REFERENCE_PROBLEMATIC_LOANS
    assert row["problematic_loans"] == row["status_b_finished_unpaid"] + row["status_d_running_in_debt"]
    assert abs(row["problematic_pct"] - config.REFERENCE_PROBLEMATIC_LOAN_PCT) < 0.01


def test_q4_card_types_cover_every_loan(reference: dict) -> None:
    """Q4's card-type groups must account for all 682 loans, 'no card' included."""
    rows = reference["Q4"]["rows"]
    assert sum(row["loans"] for row in rows) == config.REFERENCE_ROW_COUNTS["loan"]
    labels = {row["owner_card_type"] for row in rows}
    assert config.NO_CARD_LABEL in labels, (
        "loans whose owner holds no card must be an explicit category, not dropped"
    )
    assert labels - set(config.CARD_TYPE_CODES) - {config.NO_CARD_LABEL} == set()


def test_q5_returns_ten_ranked_districts(reference: dict) -> None:
    """Q5 must return exactly 10 districts, ranked and strictly decreasing."""
    rows = reference["Q5"]["rows"]
    assert len(rows) == 10
    totals = [row["total_incoming_amount"] for row in rows]
    assert totals == sorted(totals, reverse=True)
    assert rows[0]["rank"] == 1


def test_q6_reports_all_twelve_months(reference: dict) -> None:
    """Q6 must report all 12 months of 1996, even one with no new accounts."""
    rows = reference["Q6"]["rows"]
    assert len(rows) == 12, "an omitted month reads as 'no data', not 'no accounts'"
    assert [row["month_number"] for row in rows] == list(range(1, 13))
    assert all(row["year_month"].startswith("1996-") for row in rows)


def test_q7_ages_are_plausible_and_cover_every_status(reference: dict) -> None:
    """Q7 must report one row per loan status with a plausible average age."""
    rows = reference["Q7"]["rows"]
    assert {row["status_code"] for row in rows} == set(config.LOAN_STATUS_CODES)
    assert sum(row["loans"] for row in rows) == config.REFERENCE_ROW_COUNTS["loan"]
    for row in rows:
        assert 18 <= row["average_age_at_loan_start"] <= 80, row


def test_q8_gender_split_sums_to_100(reference: dict) -> None:
    """Q8's percentages must sum to 100 over the allowed gender values."""
    rows = reference["Q8"]["rows"]
    assert {row["gender"] for row in rows} <= {config.GENDER_MALE, config.GENDER_FEMALE}
    assert abs(sum(row["pct_of_gold_card_owners"] for row in rows) - 100.0) < 0.05
    assert sum(row["gold_card_owners"] for row in rows) > 0


def test_q9_population_and_caveats_are_reported(reference: dict) -> None:
    """Q9 must state its population and carry its data quality caveats."""
    row = reference["Q9"]["rows"][0]
    assert row["accounts_with_known_balance"] > 0
    assert row["accounts_with_known_balance"] <= config.REFERENCE_ROW_COUNTS["account"]
    assert row["min_balance"] <= row["average_balance"] <= row["max_balance"]
    for caveat in ("accounts_carried_forward", "accounts_balance_unreconciled"):
        assert caveat in row, f"Q9 must report {caveat} next to the average"


def test_q10_ranking_is_complete_and_consistent_with_q3(reference: dict) -> None:
    """Q10 must rank every statement frequency and agree with Q3 in total."""
    rows = reference["Q10"]["rows"]
    assert len(rows) == len(config.FREQUENCY_CODES)
    assert sum(row["loans"] for row in rows) == config.REFERENCE_ROW_COUNTS["loan"]
    assert sum(row["problematic_loans"] for row in rows) == config.REFERENCE_PROBLEMATIC_LOANS
    assert rows[0]["rank_by_problematic_share"] == 1
    shares = [row["problematic_pct"] for row in rows]
    assert shares == sorted(shares, reverse=True)


def test_reference_sql_never_reads_the_inject_schema() -> None:
    """The reference answers must come from the real data, never the test copy."""
    sql_text = (config.SQL_DIR / "60_reference_queries.sql").read_text(encoding="utf-8")
    assert config.SCHEMA_INJECT not in sql_text.replace("-- ", "")


def test_month_end_balance_fact_is_internally_consistent() -> None:
    """A carried-forward month-end balance must equal the last real one.

    Q9 rests on this fact table, so the carry-forward logic is tested directly
    rather than only through the answer.
    """
    with db.connect() as conn:
        mismatches = db.fetch_value(
            conn,
            """
            WITH carried AS (
                SELECT account_id, month_end_date, closing_balance,
                       balance_as_of_month_end
                FROM core.fact_account_month_end_balance
                WHERE is_carried_forward
            )
            SELECT count(*)
            FROM carried c
            JOIN core.fact_account_month_end_balance src
              ON src.account_id = c.account_id
             AND src.month_end_date = c.balance_as_of_month_end
            WHERE src.closing_balance IS DISTINCT FROM c.closing_balance
            """,
        )
    assert mismatches == 0, f"{mismatches} carried-forward balances do not match their source"
