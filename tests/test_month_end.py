"""Month-end closing balance: the rule of D028, tested on purpose-built data.

The production SQL block of ``core.fact_account_month_end_balance`` (between
the ``@@month_end_balance`` markers in ``sql/30_core.sql``) is run verbatim
against a throw-away schema of synthetic postings, inside a transaction that is
rolled back. Each synthetic account exercises one case the rule must get
right. The real table is then checked against an independent derivation that
reads the chain from the other end.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

import pytest

from src import config, db

SCHEMA = "meb_test"

# (account, trans_id, date, signed_amount, balance_after)
POSTINGS = [
    # 1: same-day chain where the HIGHEST id is not the closing posting.
    #    Interest +5 (id 900) runs 100 -> 105, then a fee -2 (id 50) 105 -> 103.
    (1, 10, "2001-01-01", 100, 100),
    (1, 900, "2001-01-31", 5, 105),
    (1, 50, "2001-01-31", -2, 103),
    #    ... then nothing until April: February and March are carried forward.
    (1, 60, "2001-04-30", 7, 110),          # a posting on the last day of the book
    # 2: first posting in March: no row, and no balance, before March.
    (2, 70, "2001-03-15", 40, 40),
    # 3: two postings whose balances do not chain: ambiguous.
    (3, 80, "2001-02-10", 10, 60),          # starts at 50
    (3, 81, "2001-02-10", -5, 65),          # starts at 70
    # 4: a cycle (+10 then -10): no chain end at all: ambiguous.
    (4, 90, "2001-02-20", 10, 210),
    (4, 91, "2001-02-20", -10, 200),
    # 5: a zero-amount posting after a credit: one chain end, unambiguous.
    (5, 95, "2001-03-31", 10, 310),
    (5, 96, "2001-03-31", 0, 310),
    # 6: a single posting on the first day of the book.
    (6, 99, "2001-01-01", 25, 25),
]
MONTH_ENDS = ["2001-01-31", "2001-02-28", "2001-03-31", "2001-04-30"]


def _production_block() -> str:
    """Return the month-end SQL exactly as the build runs it."""
    text = (config.SQL_DIR / "30_core.sql").read_text(encoding="utf-8")
    block = re.search(r"-- @@month_end_balance:begin\n(.*?)-- @@month_end_balance:end",
                      text, flags=re.S)
    assert block, "the @@month_end_balance markers are missing from sql/30_core.sql"
    sql = block.group(1)
    assert "core.fact_transaction" in sql and "core.dim_date" in sql
    return sql.replace("core.", f"{SCHEMA}.")


@pytest.fixture(scope="module")
def synthetic() -> dict[tuple[int, date], dict]:
    """Build the fact from the synthetic postings and return it keyed by (account, month end)."""
    with db.connect() as conn:
        try:
            conn.execute(f"CREATE SCHEMA {SCHEMA}")
            conn.execute(f"""CREATE TABLE {SCHEMA}.fact_transaction (
                trans_id bigint, account_id bigint, trans_date date,
                signed_amount numeric, balance_after numeric)""")
            conn.execute(f"CREATE TABLE {SCHEMA}.dim_date (month_end date)")
            for account, trans_id, day, amount, balance in POSTINGS:
                conn.execute(
                    f"INSERT INTO {SCHEMA}.fact_transaction VALUES (%s, %s, %s, %s, %s)",
                    (trans_id, account, day, amount, balance))
            for month_end in MONTH_ENDS:
                conn.execute(f"INSERT INTO {SCHEMA}.dim_date VALUES (%s)", (month_end,))
            conn.execute(_production_block())
            rows = db.fetch_all(conn, f"SELECT * FROM {SCHEMA}.fact_account_month_end_balance")
        finally:
            conn.rollback()  # nothing of the synthetic schema survives the test
    return {(r["account_id"], r["month_end_date"]): r for r in rows}


def _row(table: dict, account: int, month_end: str) -> dict:
    return table[(account, date.fromisoformat(month_end))]


def test_same_day_postings_close_on_the_end_of_the_balance_chain(synthetic) -> None:
    row = _row(synthetic, 1, "2001-01-31")
    assert row["closing_balance"] == Decimal("103")      # after the fee, not 105
    assert row["last_trans_id"] == 50                     # the LOWER id closed the day
    assert row["closing_basis"] == "balance chain"
    assert row["is_carried_forward"] is False


def test_a_month_without_postings_carries_the_last_balance_forward(synthetic) -> None:
    for month_end in ("2001-02-28", "2001-03-31"):
        row = _row(synthetic, 1, month_end)
        assert row["is_carried_forward"] is True
        assert row["closing_balance"] == Decimal("103")
        assert row["balance_as_of_month_end"] == date(2001, 1, 31)
        assert row["closing_basis"] == "balance chain"     # inherited from January


def test_no_row_exists_before_the_first_posting(synthetic) -> None:
    months = sorted(m for (a, m) in synthetic if a == 2)
    assert months == [date(2001, 3, 31), date(2001, 4, 30)]
    assert _row(synthetic, 2, "2001-04-30")["is_carried_forward"] is True


def test_first_and_last_dates_of_the_book_are_included(synthetic) -> None:
    assert _row(synthetic, 6, "2001-01-31")["closing_balance"] == Decimal("25")
    assert _row(synthetic, 6, "2001-01-31")["closing_basis"] == "single posting"
    last = _row(synthetic, 1, "2001-04-30")
    assert (last["closing_balance"], last["is_carried_forward"]) == (Decimal("110"), False)
    assert max(m for (_, m) in synthetic) == date(2001, 4, 30)   # no month past the book


def test_unchainable_postings_are_marked_ambiguous_not_guessed_silently(synthetic) -> None:
    broken = _row(synthetic, 3, "2001-02-28")
    assert broken["closing_basis"] == "ambiguous"
    assert broken["last_trans_id"] == 80                  # the documented fallback
    cycle = _row(synthetic, 4, "2001-02-28")
    assert cycle["closing_basis"] == "ambiguous"
    assert cycle["closing_balance"] in (Decimal("200"), Decimal("210"))


def test_a_zero_amount_posting_does_not_create_ambiguity(synthetic) -> None:
    row = _row(synthetic, 5, "2001-03-31")
    assert (row["closing_balance"], row["closing_basis"]) == (Decimal("310"), "balance chain")


def test_every_observed_balance_is_a_balance_the_source_reported(synthetic) -> None:
    reported = {(a, date.fromisoformat(d), Decimal(b)) for a, _, d, _, b in POSTINGS}
    for (account, month_end), row in synthetic.items():
        if row["is_carried_forward"]:
            continue
        assert any(a == account and d.replace(day=1) == month_end.replace(day=1)
                   and b == row["closing_balance"] for a, d, b in reported), row


# ---------------------------------------------------------------------------
# The real table
# ---------------------------------------------------------------------------


def test_real_closing_balances_agree_with_an_independent_derivation() -> None:
    """Re-derive every resolved closing balance from the head of the chain.

    The fact table finds the chain's END. This finds its HEAD (the posting no
    other same-day posting ends at) and adds the day's net flow, which needs
    no order at all. Where the head is unique, both must agree to the cent.
    """
    with db.connect() as conn:
        result = db.fetch_all(conn, """
            WITH day AS (
                SELECT account_id, date_trunc('month', trans_date)::date AS m, max(trans_date) AS d
                FROM core.fact_transaction GROUP BY 1, 2),
            p AS (
                SELECT t.account_id, day.m, t.trans_id, t.signed_amount, t.balance_after,
                       t.balance_after - t.signed_amount AS before
                FROM core.fact_transaction t JOIN day ON day.account_id = t.account_id AND day.d = t.trans_date),
            head AS (
                SELECT p.* FROM p WHERE NOT EXISTS (
                    SELECT 1 FROM p q WHERE q.account_id = p.account_id AND q.m = p.m
                      AND q.trans_id <> p.trans_id AND q.balance_after = p.before)),
            net AS (SELECT account_id, m, sum(signed_amount) AS flow FROM p GROUP BY 1, 2),
            one_head AS (SELECT account_id, m, min(before) AS opening
                         FROM head GROUP BY 1, 2 HAVING count(*) = 1),
            derived AS (
                SELECT h.account_id, h.m, h.opening + n.flow AS closing
                FROM one_head h JOIN net n USING (account_id, m))
            SELECT count(*) AS compared,
                   count(*) FILTER (WHERE abs(d.closing - b.closing_balance) > 0.005) AS disagree
            FROM derived d
            JOIN core.fact_account_month_end_balance b
              ON b.account_id = d.account_id
             AND b.month_end_date = (d.m + INTERVAL '1 month - 1 day')::date
            WHERE NOT b.is_carried_forward AND b.closing_basis <> 'ambiguous'
        """)[0]
    assert result["compared"] > 180_000, result
    assert result["disagree"] == 0, result


def test_real_table_coverage_and_ambiguity_are_as_documented() -> None:
    with db.connect() as conn:
        stats = db.fetch_all(conn, """
            SELECT
              count(*) FILTER (WHERE NOT is_carried_forward) AS observed,
              count(*) FILTER (WHERE NOT is_carried_forward AND closing_basis = 'ambiguous') AS ambiguous,
              count(*) FILTER (WHERE month_end_date = DATE '1998-12-31') AS accounts_at_book_end,
              count(*) FILTER (WHERE month_end_date = DATE '1998-12-31' AND closing_basis = 'ambiguous') AS ambiguous_at_book_end
            FROM core.fact_account_month_end_balance""")[0]
        early = db.fetch_value(conn, """
            SELECT count(*) FROM (
                SELECT b.account_id FROM core.fact_account_month_end_balance b
                JOIN core.fact_transaction t USING (account_id)
                GROUP BY b.account_id
                HAVING min(b.month_end_date)
                       <> (date_trunc('month', min(t.trans_date)) + INTERVAL '1 month - 1 day')::date) z""")
    assert stats["accounts_at_book_end"] == 4500
    assert stats["ambiguous"] / stats["observed"] < 0.02, stats       # 2,303 of 185,057
    assert stats["ambiguous_at_book_end"] == 42, stats
    assert early == 0, "a balance row exists before the account's first posting month"


def test_the_reconciliation_rules_read_the_same_closing_balance_as_the_fact() -> None:
    """The DQ rules and the fact must agree on what 'last reported balance' means."""
    with db.connect() as conn:
        mismatches = db.fetch_value(conn, """
            WITH last_day AS (SELECT account_id, max(trans_date) d FROM core.fact_transaction GROUP BY 1),
            p AS (SELECT t.account_id, t.trans_id, t.balance_after, t.balance_after - t.signed_amount AS before
                  FROM core.fact_transaction t JOIN last_day l ON l.account_id = t.account_id AND l.d = t.trans_date),
            final AS (SELECT DISTINCT ON (p.account_id) p.account_id, p.balance_after FROM p
                      ORDER BY p.account_id, NOT EXISTS (SELECT 1 FROM p q WHERE q.account_id = p.account_id
                               AND q.trans_id <> p.trans_id AND q.before = p.balance_after) DESC, p.trans_id)
            SELECT count(*) FROM final f
            JOIN core.fact_account_month_end_balance b
              ON b.account_id = f.account_id AND b.month_end_date = DATE '1998-12-31'
            WHERE b.closing_balance <> f.balance_after""")
    assert mismatches == 0
