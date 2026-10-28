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
from tests import support

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
    # A CTE name stands in only for an UNqualified reference. These three once
    # passed: the name matched a CTE, so the schema was never looked at.
    ("CTE named like a core table", "WITH dim_client AS (SELECT 1) SELECT * FROM core.dim_client"),
    ("CTE named like a raw table", "WITH client AS (SELECT 1) SELECT * FROM raw.client"),
    ("CTE named like a sec table", "WITH app_user AS (SELECT 1) SELECT * FROM sec.app_user"),
    # Functions reached through a schema. These once passed too: a qualified
    # call is not a table, so the table check never saw it.
    ("internal function", "SELECT sec.end_session()"),
    ("second factor function", "SELECT sec.verify_second_factor('000000')"),
    ("internal function in FROM", "SELECT * FROM sec.verify_second_factor('000000')"),
    ("function in core", "SELECT core.ref_token(1) FROM ai.client"),
    ("three-part function name", "SELECT berka.sec.end_session()"),
    ("reading configuration", "SELECT current_setting('berka.ref_salt', true)"),
    ("join into raw", "SELECT * FROM ai.client c JOIN raw.client r ON r.client_id = c.client_id::text"),
    ("union into stg", "SELECT client_id FROM ai.client UNION SELECT client_id FROM stg.client"),
    ("CTE body into core", "WITH x AS (SELECT * FROM core.dim_client) SELECT * FROM x"),
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

    fetch = sql_guard.guard("SELECT * FROM ai.client FETCH FIRST 5 ROWS ONLY")
    assert fetch.allowed and "FETCH FIRST 5" in fetch.rewritten_sql.upper()
    assert not fetch.notes


@pytest.mark.parametrize("sql", [
    "SELECT * FROM ai.transaction LIMIT 100000000",
    "SELECT * FROM ai.transaction LIMIT ALL",
    "SELECT * FROM ai.transaction LIMIT (SELECT 100000000)",
    "SELECT * FROM ai.transaction FETCH FIRST 100000000 ROWS ONLY",
    "SELECT * FROM ai.transaction FETCH FIRST 10 PERCENT ROWS ONLY",
    "SELECT * FROM ai.transaction ORDER BY amount FETCH FIRST 5 ROWS WITH TIES",
    "SELECT trans_id FROM ai.transaction UNION ALL SELECT trans_id FROM ai.transaction LIMIT 20000",
])
def test_a_model_cannot_raise_the_row_cap(sql: str) -> None:
    """A limit the model wrote is kept only if it is a number within the cap.

    The cap used to be added only when no limit was present, so a model that
    wrote ``LIMIT 100000000`` -- or ``LIMIT ALL`` -- got the whole table.
    """
    verdict = sql_guard.guard(sql)
    assert verdict.allowed, verdict.reason
    assert f"LIMIT {config.GUARD_MAX_ROWS}" in verdict.rewritten_sql.upper()
    assert "FETCH" not in verdict.rewritten_sql.upper()
    assert any("replaced" in note for note in verdict.notes)


def test_guarded_execution_never_returns_more_than_the_cap() -> None:
    """Measured on real rows, not on the rewritten text.

    A customer's transactions crossed with the calendar is far more than the
    cap, and the model asked for 50,000 of them. Before the fix, it got them.
    """
    sql = ("SELECT t.trans_id, c.date_key FROM ai.transaction t "
           "CROSS JOIN ai.calendar c LIMIT 50000")
    with support.consumer("client_3763") as conn:
        verdict, rows, error = sql_guard.execute_guarded(conn, sql)
    assert verdict.allowed and error is None, error
    assert len(rows) == config.GUARD_MAX_ROWS


def test_a_long_query_is_stopped_by_the_statement_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A query that passes the guard still cannot run for longer than allowed."""
    monkeypatch.setattr(config, "GUARD_STATEMENT_TIMEOUT_MS", 300)
    with support.consumer("client_3763") as conn:
        verdict, rows, error = sql_guard.execute_guarded(
            conn, "SELECT count(*) FROM generate_series(1, 5000000000) AS g")
    assert verdict.allowed, verdict.reason
    assert rows is None
    assert "statement timeout" in error


def test_the_guarded_transaction_is_read_only() -> None:
    """The layer under the guard: even a statement the guard were talked into
    allowing cannot write, because the transaction itself is read only.

    The guard is widened here on purpose, to reach a function that writes.
    """
    with support.consumer("client_3763") as conn:
        verdict, rows, error = sql_guard.execute_guarded(
            conn, "SELECT sec.end_session()", allowed_schemas=("ai", "sec"))
    assert verdict.allowed
    assert rows is None
    assert "read-only transaction" in error


def test_generated_sql_runs_as_the_authenticated_persona() -> None:
    """The identity is the login's. The statement cannot name another one."""
    with support.consumer("client_3763") as conn:
        _, rows, error = sql_guard.execute_guarded(
            conn, "SELECT current_user AS acting, session_user AS logged_in "
                  "FROM ai.calendar LIMIT 1")
    assert error is None, error
    assert rows == [{"acting": "client_3763", "logged_in": "client_3763"}]
    for attempt in ("SET ROLE cro_global",
                    "SELECT set_config('role', 'cro_global', false)",
                    "SELECT pg_catalog.set_config('role', 'cro_global', false)",
                    "RESET ROLE"):
        assert not sql_guard.guard(attempt).allowed, attempt


def test_guarded_execution_is_read_only_and_entitlement_filtered() -> None:
    """A guarded query runs as the consumer, and still only sees their rows."""
    with support.consumer("rm_north") as conn:
        verdict, rows, error = sql_guard.execute_guarded(
            conn, "SELECT count(*) AS clients FROM ai.client"
        )
        assert verdict.allowed, verdict.reason
        assert error is None
        north = rows[0]["clients"]

    with support.consumer("rm_unassigned") as conn:
        _, rows, error = sql_guard.execute_guarded(
            conn, "SELECT count(*) AS clients FROM ai.client"
        )
        assert error is None
        assert rows[0]["clients"] == 0

    assert 0 < north < config.REFERENCE_ROW_COUNTS["client"]


def test_guarded_execution_refuses_to_run_a_rejected_statement() -> None:
    """A rejected statement is never sent to the database."""
    with support.consumer("rm_north") as conn:
        verdict, rows, error = sql_guard.execute_guarded(
            conn, "UPDATE ai.client SET gender = 'male'"
        )
    assert not verdict.allowed
    assert rows is None and error is None
