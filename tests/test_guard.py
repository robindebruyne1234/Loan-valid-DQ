"""Test the SQL guard against the statements an LLM might actually emit.

The guard is the second line of defence -- the entitlement filter is a database
policy and holds regardless -- but it is the line that decides whether a
generated statement is allowed to touch the database at all, so it is tested
adversarially: comment-hidden batches, writes buried in CTEs, casing tricks,
internal schemas, and environment-reading functions.
"""

from __future__ import annotations

import pytest

from src import config, db, sql_guard

LEGITIMATE = [
    "SELECT region, count(*) AS clients FROM ai.client GROUP BY region",
    "SELECT loan_year, sum(amount) FROM ai.loan GROUP BY loan_year ORDER BY loan_year",
    """
    WITH monthly AS (
        SELECT c.year_month, count(a.account_id) AS opened
        FROM ai.calendar c
        LEFT JOIN ai.account a ON date_trunc('month', a.open_date) = c.month_start
        WHERE c.year = 1996 AND c.is_month_end
        GROUP BY c.year_month
    )
    SELECT * FROM monthly ORDER BY year_month
    """,
    "SELECT count(*) FROM ai.transaction WHERE direction = 'credit' LIMIT 5",
    "SELECT owner_gender, count(*) FROM ai.account_owner WHERE owner_card_type = 'gold' GROUP BY owner_gender",
]

REJECTED = [
    ("empty", ""),
    ("batch", "SELECT 1 FROM ai.client; DROP TABLE core.dim_client"),
    ("comment-hidden batch", "SELECT 1 FROM ai.client/**/;/**/DELETE FROM core.fact_loan"),
    ("update", "UPDATE ai.client SET gender = 'male'"),
    ("delete", "DELETE FROM ai.loan"),
    ("insert", "INSERT INTO ai.client (client_id) VALUES (1)"),
    ("create", "CREATE TABLE ai.evil AS SELECT * FROM ai.client"),
    ("drop", "DROP VIEW ai.client"),
    ("alter", "ALTER TABLE core.dim_client DISABLE ROW LEVEL SECURITY"),
    ("grant", "GRANT SELECT ON core.dim_client TO PUBLIC"),
    ("truncate", "TRUNCATE ai.client"),
    ("staging schema", "SELECT count(*) FROM stg.trans"),
    ("raw schema", "SELECT count(*) FROM raw.trans"),
    ("entitlement tables", "SELECT * FROM sec.portfolio_client"),
    ("core schema", "SELECT count(*) FROM core.fact_loan"),
    ("inject schema", "SELECT count(*) FROM inject.loan"),
    ("unqualified table", "SELECT count(*) FROM client"),
    ("catalog probing", "SELECT * FROM pg_catalog.pg_roles"),
    ("file read", "SELECT pg_read_file('/etc/passwd')"),
    ("sleep", "SELECT pg_sleep(60)"),
    ("set_config", "SELECT set_config('app.end_user', 'cro_global', false)"),
    ("write in a CTE", "WITH x AS (DELETE FROM core.fact_loan RETURNING 1) SELECT * FROM x"),
    ("insert in a CTE", "WITH x AS (INSERT INTO ai.client (client_id) VALUES (1) RETURNING 1) SELECT * FROM x"),
    ("select into", "SELECT * INTO ai.copy FROM ai.client"),
    ("row locking", "SELECT * FROM ai.client FOR UPDATE"),
    ("set statement", "SET ROLE cro_global"),
    ("not sql", "I am afraid I cannot answer that question."),
    ("subquery into a forbidden schema", "SELECT (SELECT count(*) FROM stg.loan) FROM ai.client"),
]


@pytest.mark.parametrize("sql", LEGITIMATE)
def test_legitimate_queries_pass(sql: str) -> None:
    """A correct query against the ai schema is allowed and comes back bounded."""
    verdict = sql_guard.guard(sql)
    assert verdict.allowed, verdict.reason
    assert verdict.rewritten_sql
    assert "limit" in verdict.rewritten_sql.lower()


@pytest.mark.parametrize("label,sql", REJECTED)
def test_hostile_or_wrong_queries_are_rejected(label: str, sql: str) -> None:
    """Each statement an LLM should never execute is rejected with a reason.

    :param label: What the statement is attempting.
    :param sql: The statement.
    """
    verdict = sql_guard.guard(sql)
    assert not verdict.allowed, f"{label} was allowed: {sql}"
    assert verdict.violations, label
    assert verdict.rewritten_sql is None, label


def test_case_and_whitespace_do_not_defeat_the_guard() -> None:
    """Casing and formatting tricks do not change the verdict.

    A regular-expression guard is defeated by exactly these; an abstract syntax
    tree is not, which is the reason sqlglot is a dependency.
    """
    for sql in (
        "uPdAtE ai.client SeT gender = 'male'",
        "sElEcT   count(*)\n\nFROM\n\tStG.TrAnS",
        "/* comment */ SELECT 1 FROM ai.client /* another */ ; SELECT 2",
    ):
        assert not sql_guard.guard(sql).allowed, sql


def test_row_limit_is_applied_only_when_missing() -> None:
    """The guard adds a row cap, and leaves a stricter one alone."""
    added = sql_guard.guard("SELECT * FROM ai.client")
    assert added.allowed
    assert str(config.GUARD_MAX_ROWS) in added.rewritten_sql
    assert any("row limit" in note for note in added.notes)

    kept = sql_guard.guard("SELECT * FROM ai.client LIMIT 5")
    assert kept.allowed
    assert "LIMIT 5" in kept.rewritten_sql.upper()
    assert not kept.notes


def test_guarded_execution_is_read_only_and_entitlement_filtered() -> None:
    """A guarded query runs as the consumer, and still only sees their rows."""
    with db.connect(user="rm_north") as conn:
        verdict, rows, error = sql_guard.execute_guarded(
            conn, "SELECT count(*) AS clients FROM ai.client"
        )
        assert verdict.allowed, verdict.reason
        assert error is None
        north = rows[0]["clients"]

    with db.connect(user="rm_unassigned") as conn:
        _, rows, error = sql_guard.execute_guarded(
            conn, "SELECT count(*) AS clients FROM ai.client"
        )
        assert error is None
        assert rows[0]["clients"] == 0

    assert 0 < north < config.REFERENCE_ROW_COUNTS["client"]


def test_guarded_execution_refuses_to_run_a_rejected_statement() -> None:
    """A rejected statement is never sent to the database."""
    with db.connect(user="rm_north") as conn:
        verdict, rows, error = sql_guard.execute_guarded(
            conn, "UPDATE ai.client SET gender = 'male'"
        )
    assert not verdict.allowed
    assert rows is None and error is None
