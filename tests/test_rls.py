"""Prove the entitlement filter cannot be bypassed.

Task 3 asks *why* an LLM-generated query cannot get around the filter. The
honest way to answer that is to try, so this module connects as real,
low-privilege users and attempts the bypasses an adversarial query author
would reach for: switching role, reading the base tables directly, reading the
raw layer, setting a session variable, editing the entitlement tables,
disabling the policy, and dropping it.

It also pins the two settings whose absence silently removes the filter:
``security_invoker`` on every view between the consumer and the policy, and a
policy on every core table that carries client data. Both have already been
wrong once in this project (see DECISIONS.md D009), which is why they are
tested rather than reviewed.
"""

from __future__ import annotations

import psycopg
import pytest

from src import build_security, config, db

#: Every ai view a consumer may query, with whether it must be filtered.
#: Reference data is not filtered by design (assumption A22).
AI_VIEWS_FILTERED: tuple[str, ...] = (
    "client",
    "account",
    "account_owner",
    "card",
    "loan",
    "transaction",
    "account_month_end_balance",
)
AI_VIEWS_REFERENCE: tuple[str, ...] = ("district", "calendar", "code_reference")

#: Core tables that carry client data and must therefore have a policy.
CORE_PROTECTED_TABLES: tuple[str, ...] = (
    "dim_client",
    "dim_account",
    "bridge_disposition",
    "dim_card",
    "fact_loan",
    "fact_transaction",
    "fact_account_month_end_balance",
)


def counts_for(role: str) -> dict[str, int]:
    """Count the rows each filtered ai view returns for one user.

    :param role: Login role to connect as.
    :returns: Mapping of view name to visible row count.
    """
    with db.connect(user=role) as conn:
        return {
            view: int(db.fetch_value(conn, f"SELECT count(*) FROM ai.{view}") or 0)
            for view in AI_VIEWS_FILTERED
        }


# ---------------------------------------------------------------------------
# The filter works at all
# ---------------------------------------------------------------------------

def test_unentitled_user_sees_nothing() -> None:
    """A user with no portfolio sees zero rows, not everything.

    The default has to be "see nothing": a newly created user who has not been
    granted a book yet is the most likely identity to exist in a real bank at
    any moment.
    """
    counts = counts_for("rm_unassigned")
    assert counts == dict.fromkeys(AI_VIEWS_FILTERED, 0), counts


def test_entitled_users_see_their_own_slice_only() -> None:
    """Two relationship managers see disjoint client sets, both smaller than the whole."""
    with db.connect(user="rm_north") as north, db.connect(user="rm_south") as south:
        north_clients = {
            row["client_id"] for row in db.fetch_all(north, "SELECT client_id FROM ai.client")
        }
        south_clients = {
            row["client_id"] for row in db.fetch_all(south, "SELECT client_id FROM ai.client")
        }
    assert north_clients and south_clients
    assert not (north_clients & south_clients), "two books share clients"
    total = config.REFERENCE_ROW_COUNTS["client"]
    assert len(north_clients) < total and len(south_clients) < total


def test_unrestricted_access_is_granted_through_data_not_privilege() -> None:
    """The bank-wide user sees everything, and is an ordinary policy-bound role.

    This is the distinction that matters for governance: "sees everything" is a
    portfolio containing every client, not an exemption from the policy.
    """
    counts = counts_for("cro_global")
    assert counts["client"] == config.REFERENCE_ROW_COUNTS["client"]
    assert counts["account"] == config.REFERENCE_ROW_COUNTS["account"]
    assert counts["loan"] == config.REFERENCE_ROW_COUNTS["loan"]
    with db.connect(user="cro_global") as conn:
        assert db.fetch_value(conn, "SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user") is False
        assert db.fetch_value(conn, "SELECT rolsuper FROM pg_roles WHERE rolname = current_user") is False


def test_reference_data_is_not_filtered() -> None:
    """Districts and the calendar stay visible to everyone, including an unentitled user."""
    with db.connect(user="rm_unassigned") as conn:
        for view in AI_VIEWS_REFERENCE:
            assert int(db.fetch_value(conn, f"SELECT count(*) FROM ai.{view}") or 0) > 0, view


# ---------------------------------------------------------------------------
# Bypass attempts. Each one is something an LLM could emit.
# ---------------------------------------------------------------------------

def test_cannot_switch_to_another_user_role() -> None:
    """SET ROLE to another relationship manager must fail."""
    with db.connect(user="rm_north") as conn:
        with pytest.raises(psycopg.Error):
            db.execute(conn, "SET ROLE rm_south")


def test_cannot_switch_to_the_pipeline_owner() -> None:
    """SET ROLE to the table owner (which bypasses RLS) must fail."""
    with db.connect(user="rm_north") as conn:
        with pytest.raises(psycopg.Error):
            db.execute(conn, f"SET ROLE {config.PGUSER}")


def test_querying_the_base_tables_directly_is_still_filtered() -> None:
    """Going around the ai views changes nothing: the policy is on the base table.

    This is the single most important property of the design. The filter is not
    a column list in a view or a WHERE clause the query could omit -- it is
    attached to the table, so reaching the table reaches the policy.
    """
    with db.connect(user="rm_unassigned") as conn:
        for table in CORE_PROTECTED_TABLES:
            visible = int(db.fetch_value(conn, f"SELECT count(*) FROM core.{table}") or 0)
            assert visible == 0, f"core.{table} leaked {visible} rows to an unentitled user"


def test_cannot_read_the_raw_or_staging_layers() -> None:
    """The unfiltered layers are not readable by a consumer at all."""
    with db.connect(user="rm_north") as conn:
        for target in ("raw.trans", "stg.trans", "dq.quarantine", "inject.trans"):
            with pytest.raises(psycopg.Error):
                db.fetch_value(conn, f"SELECT count(*) FROM {target}")
            conn.rollback()


def test_setting_a_session_variable_does_not_change_visibility() -> None:
    """Identity comes from session_user, so a GUC cannot re-point it.

    A design that resolved the caller from ``current_setting('app.user')``
    would be defeated by exactly this statement, which is why it is tested.
    """
    with db.connect(user="rm_north") as conn:
        before = int(db.fetch_value(conn, "SELECT count(*) FROM ai.client") or 0)
        # set_config is the form a pooling gateway would use, and the form an
        # LLM would emit; "SET app.user" is a syntax error because user is
        # reserved, so the realistic spelling is tested.
        db.fetch_value(conn, "SELECT set_config('app.end_user', 'cro_global', false)")
        db.fetch_value(conn, "SELECT set_config('app.current_user_id', '1', false)")
        db.execute(conn, "SET ROLE NONE")
        after = int(db.fetch_value(conn, "SELECT count(*) FROM ai.client") or 0)
    assert before == after > 0


def test_cannot_grant_itself_a_portfolio() -> None:
    """A consumer cannot write to the entitlement tables, or even read them."""
    with db.connect(user="rm_unassigned") as conn:
        for statement in (
            "INSERT INTO sec.portfolio_client (portfolio_id, client_id) VALUES (1, 1)",
            "INSERT INTO sec.user_portfolio (app_user_id, portfolio_id) VALUES (1, 1)",
            "UPDATE sec.app_user SET is_active = true",
            "SELECT count(*) FROM sec.portfolio_client",
        ):
            with pytest.raises(psycopg.Error):
                db.execute(conn, statement)
            conn.rollback()


def test_cannot_disable_or_drop_the_policy() -> None:
    """A consumer cannot turn row level security off or remove a policy."""
    with db.connect(user="rm_north") as conn:
        for statement in (
            "ALTER TABLE core.dim_client DISABLE ROW LEVEL SECURITY",
            "DROP POLICY entitled_clients ON core.dim_client",
            "ALTER TABLE core.dim_client NO FORCE ROW LEVEL SECURITY",
        ):
            with pytest.raises(psycopg.Error):
                db.execute(conn, statement)
            conn.rollback()


def test_consumer_cannot_write_anywhere_in_the_product() -> None:
    """Every write into core or ai is refused for a consumer."""
    with db.connect(user="cro_global") as conn:
        for statement in (
            "UPDATE core.fact_loan SET amount = 0",
            "DELETE FROM core.dim_client",
            "INSERT INTO core.dim_district (district_id, district_name) VALUES (999, 'x')",
            "TRUNCATE core.fact_transaction",
        ):
            with pytest.raises(psycopg.Error):
                db.execute(conn, statement)
            conn.rollback()


def test_a_join_cannot_widen_the_result() -> None:
    """Joining an entitled row to an unentitled one yields nothing, not a leak.

    An LLM asked for "all clients" might join its way outwards. Each table in
    the join carries its own policy, so the result is the intersection of what
    the user may see -- never the union.
    """
    with db.connect(user="rm_north") as conn:
        leaked = db.fetch_value(
            conn,
            """
            SELECT count(*)
            FROM core.dim_client c
            FULL OUTER JOIN core.fact_loan l ON TRUE
            WHERE c.client_id IS NULL OR l.loan_id IS NULL
            """,
        )
        entitled_clients = int(db.fetch_value(conn, "SELECT count(*) FROM ai.client") or 0)
        entitled_loans = int(db.fetch_value(conn, "SELECT count(*) FROM ai.loan") or 0)
    assert entitled_clients > 0 and entitled_loans > 0
    # Every row either side of the outer join is itself entitled, so no row can
    # appear that belongs to another portfolio.
    assert leaked == 0


# ---------------------------------------------------------------------------
# The settings whose absence silently removes the filter
# ---------------------------------------------------------------------------

def test_every_protected_core_table_has_row_level_security_and_a_policy() -> None:
    """A core table carrying client data without a policy is a leak waiting to happen."""
    with db.connect() as conn:
        for table in CORE_PROTECTED_TABLES:
            enabled = db.fetch_value(
                conn,
                "SELECT relrowsecurity FROM pg_class WHERE oid = %s::regclass",
                (f"core.{table}",),
            )
            policies = db.fetch_value(
                conn,
                "SELECT count(*) FROM pg_policies WHERE schemaname = 'core' AND tablename = %s",
                (table,),
            )
            assert enabled is True, f"core.{table} has row level security disabled"
            assert policies and policies > 0, f"core.{table} has no policy"


def test_every_view_between_the_consumer_and_the_policy_is_security_invoker() -> None:
    """Each ai view, and each core view it reads, must be security_invoker.

    Without the setting a view reads its base tables with the view owner's
    rights, and the owner is exempt from its own policies -- so one
    non-invoker view anywhere in the chain returns everything. That is not
    hypothetical: it happened here, and ai.loan served all 682 loans to a user
    entitled to none while the base table correctly served zero.
    """
    with db.connect() as conn:
        views = db.fetch_all(
            conn,
            """
            SELECT n.nspname AS schema, c.relname AS view_name,
                   coalesce((
                       SELECT option_value::boolean
                       FROM pg_options_to_table(c.reloptions)
                       WHERE option_name = 'security_invoker'
                   ), false) AS security_invoker
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind = 'v'
              AND (n.nspname = 'ai' OR (n.nspname = 'core' AND c.relname LIKE 'v_%'))
            ORDER BY n.nspname, c.relname
            """,
        )
    # ai.my_entitlement is intentionally not security_invoker: it reports the
    # caller's own entitlement through self-filtering sec views and must be
    # able to read them.
    offenders = [
        f"{row['schema']}.{row['view_name']}"
        for row in views
        if not row["security_invoker"] and row["view_name"] != "my_entitlement"
    ]
    assert not offenders, f"views that would bypass row level security: {offenders}"
    assert len(views) >= 13, f"expected the full view surface, found {len(views)}"


# ---------------------------------------------------------------------------
# Onboarding without code changes
# ---------------------------------------------------------------------------

def test_onboarding_a_user_and_a_portfolio_is_pure_insert() -> None:
    """A new user and a new portfolio change visibility with no code or DDL change.

    The only DDL is CREATE ROLE, which is a credential rather than business
    logic. No policy, view or query is touched, and the next statement the new
    user runs already sees the new entitlement.
    """
    role = "rm_test_onboarding"
    with db.connect(autocommit=True) as conn:
        build_security.create_login_role(conn, role, config.DEMO_USER_PASSWORD)
        build_security.onboard_user(conn, role, "Temporary test user", "test", ())

        # Before any portfolio is granted: sees nothing.
        with db.connect(user=role) as user_conn:
            assert int(db.fetch_value(user_conn, "SELECT count(*) FROM ai.client") or 0) == 0

        clients = build_security.onboard_portfolio(
            conn, "TEST_BOOK", "Temporary portfolio for the onboarding test", ("Prague",)
        )
        build_security.onboard_user(
            conn, role, "Temporary test user", "test", ("TEST_BOOK",)
        )

        # After two inserts: sees exactly that book, on the very next statement.
        with db.connect(user=role) as user_conn:
            visible = int(db.fetch_value(user_conn, "SELECT count(*) FROM ai.client") or 0)
            accounts = int(db.fetch_value(user_conn, "SELECT count(*) FROM ai.account") or 0)
        assert visible == clients > 0
        assert 0 < accounts < config.REFERENCE_ROW_COUNTS["account"]

        # Deactivating the user revokes access with one UPDATE.
        db.execute(conn, "UPDATE sec.app_user SET is_active = false WHERE db_role = %s", (role,))
        with db.connect(user=role) as user_conn:
            assert int(db.fetch_value(user_conn, "SELECT count(*) FROM ai.client") or 0) == 0

        # Clean up so the test is repeatable.
        db.execute(conn, "DELETE FROM sec.app_user WHERE db_role = %s", (role,))
        db.execute(conn, "DELETE FROM sec.portfolio WHERE portfolio_code = 'TEST_BOOK'")
        db.execute(conn, f'DROP ROLE IF EXISTS "{role}"')
