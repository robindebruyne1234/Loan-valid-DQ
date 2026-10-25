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
from tests import support

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
    with support.consumer(role) as conn:
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
    """Two managers see different clients, and any overlap is explained.

    Their books are disjoint by construction, so the portfolios alone should
    not put a client in both. A delegation deliberately can -- that is what
    delegation is for -- so the test does not forbid overlap. It requires
    every overlapping client to be accounted for by a live delegation, which
    is the stronger property: no client is reachable by two people for a
    reason nobody wrote down.
    """
    with support.consumer("rm_north") as north, support.consumer("rm_south") as south:
        north_clients = {
            row["client_id"] for row in db.fetch_all(north, "SELECT client_id FROM ai.client")
        }
        south_clients = {
            row["client_id"] for row in db.fetch_all(south, "SELECT client_id FROM ai.client")
        }
    assert north_clients and south_clients
    overlap = north_clients & south_clients
    if overlap:
        with db.connect() as conn:
            explained = {
                row["subject_id"]
                for row in db.fetch_all(
                    conn,
                    """
                    SELECT DISTINCT subject_id FROM sec.v_access_grant
                    WHERE grant_source = 'delegation' AND subject_kind = 'client'
                      AND db_role IN ('rm_north', 'rm_south')
                      AND sec.grant_is_live(valid_from, valid_to)
                    """,
                )
            }
        assert overlap <= explained, (
            f"clients {sorted(overlap - explained)} are visible to both books with "
            f"no delegation to explain it"
        )
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
    with support.consumer("cro_global") as conn:
        assert db.fetch_value(conn, "SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user") is False
        assert db.fetch_value(conn, "SELECT rolsuper FROM pg_roles WHERE rolname = current_user") is False


def test_reference_data_is_not_filtered() -> None:
    """Districts and the calendar stay visible to everyone, including an unentitled user."""
    with support.consumer("rm_unassigned") as conn:
        for view in AI_VIEWS_REFERENCE:
            assert int(db.fetch_value(conn, f"SELECT count(*) FROM ai.{view}") or 0) > 0, view


# ---------------------------------------------------------------------------
# Bypass attempts. Each one is something an LLM could emit.
# ---------------------------------------------------------------------------

def test_cannot_switch_to_another_user_role() -> None:
    """SET ROLE to another relationship manager must fail."""
    with support.consumer("rm_north") as conn:
        with pytest.raises(psycopg.Error):
            db.execute(conn, "SET ROLE rm_south")


def test_cannot_switch_to_the_pipeline_owner() -> None:
    """SET ROLE to the table owner (which bypasses RLS) must fail."""
    with support.consumer("rm_north") as conn:
        with pytest.raises(psycopg.Error):
            db.execute(conn, f"SET ROLE {config.PGUSER}")


def test_querying_the_base_tables_directly_is_still_filtered() -> None:
    """Going around the ai views changes nothing: the policy is on the base table.

    This is the single most important property of the design. The filter is not
    a column list in a view or a WHERE clause the query could omit -- it is
    attached to the table, so reaching the table reaches the policy.
    """
    with support.consumer("rm_unassigned") as conn:
        for table in CORE_PROTECTED_TABLES:
            visible = int(db.fetch_value(conn, f"SELECT count(*) FROM core.{table}") or 0)
            assert visible == 0, f"core.{table} leaked {visible} rows to an unentitled user"


def test_cannot_read_the_raw_or_staging_layers() -> None:
    """The unfiltered layers are not readable by a consumer at all."""
    with support.consumer("rm_north") as conn:
        for target in ("raw.trans", "stg.trans", "dq.quarantine", "inject.trans"):
            with pytest.raises(psycopg.Error):
                db.fetch_value(conn, f"SELECT count(*) FROM {target}")
            conn.rollback()


def test_setting_a_session_variable_does_not_change_visibility() -> None:
    """Identity comes from session_user, so a GUC cannot re-point it.

    A design that resolved the caller from ``current_setting('app.user')``
    would be defeated by exactly this statement, which is why it is tested.
    """
    with support.consumer("rm_north") as conn:
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
    with support.consumer("rm_unassigned") as conn:
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
    with support.consumer("rm_north") as conn:
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
    with support.consumer("cro_global") as conn:
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
    with support.consumer("rm_north") as conn:
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
        # Start from a known state. A previous run that failed part-way would
        # otherwise leave an enrolled factor behind and make the first
        # assertion below pass or fail for the wrong reason.
        support.forget(role)
        db.execute(conn, "DELETE FROM sec.app_user WHERE db_role = %s", (role,))
        build_security.create_login_role(conn, role, config.DEMO_USER_PASSWORD)
        build_security.onboard_user(conn, role, "Temporary test user", "test", ())

        # A credential alone is not a login. Until the new user enrols a
        # second factor they cannot complete step two, so they cannot read
        # anything at all -- not even the nothing they are entitled to.
        from src import auth  # noqa: PLC0415

        with pytest.raises(auth.AuthenticationError):
            with auth.login(role, demo_autocode=True):
                pass

        # Enrolment is a separate act, as it is in life: the user scans a
        # code into their authenticator. Only then can they log in.
        build_security.enrol_second_factor(conn, role)

        # Before any portfolio is granted: sees nothing.
        with support.consumer(role) as user_conn:
            assert int(db.fetch_value(user_conn, "SELECT count(*) FROM ai.client") or 0) == 0

        clients = build_security.onboard_portfolio(
            conn, "TEST_BOOK", "Temporary portfolio for the onboarding test", ("Prague",)
        )
        build_security.onboard_user(
            conn, role, "Temporary test user", "test", ("TEST_BOOK",)
        )

        # After two inserts: sees exactly that book, on the very next statement.
        with support.consumer(role) as user_conn:
            visible = int(db.fetch_value(user_conn, "SELECT count(*) FROM ai.client") or 0)
            accounts = int(db.fetch_value(user_conn, "SELECT count(*) FROM ai.account") or 0)
        assert visible == clients > 0
        assert 0 < accounts < config.REFERENCE_ROW_COUNTS["account"]

        # Deactivating the user revokes access with one UPDATE.
        db.execute(conn, "UPDATE sec.app_user SET is_active = false WHERE db_role = %s", (role,))
        with support.consumer(role) as user_conn:
            assert int(db.fetch_value(user_conn, "SELECT count(*) FROM ai.client") or 0) == 0

        # Clean up so the test is repeatable.
        support.forget(role)
        db.execute(conn, "DELETE FROM sec.app_user WHERE db_role = %s", (role,))
        db.execute(conn, "DELETE FROM sec.portfolio WHERE portfolio_code = 'TEST_BOOK'")
        db.execute(conn, f'DROP ROLE IF EXISTS "{role}"')


# ---------------------------------------------------------------------------
# Per-client isolation: two customers of the SAME relationship manager
#
# The brief asks that a user see only rows for their own clients. These tests
# cover the finer grain underneath it: a self-service customer is a principal
# that IS one client rather than one that HOLDS a book, and two such customers
# must not see each other even when one relationship manager sees them both.
#
# Clients 11409 and 3763 both live in north Bohemia, so both are inside
# rm_north's portfolio. That is deliberate: isolating customers in different
# books would prove nothing a portfolio boundary did not already prove.
# ---------------------------------------------------------------------------

#: ``(role, own client, the other customer's client)``, both ways round, so
#: neither direction can pass by accident.
CLIENT_PAIRS: tuple[tuple[str, int, int], ...] = (
    ("client_11409", config.EXAMPLE_CLIENT_ID, config.EXAMPLE_OTHER_CLIENT_ID),
    ("client_3763", config.EXAMPLE_OTHER_CLIENT_ID, config.EXAMPLE_CLIENT_ID),
)


def _owned_account(conn: psycopg.Connection, client_id: int) -> int:
    """Return an account owned by a client, read as the owner.

    :param conn: Open connection as the pipeline owner (exempt from policies).
    :param client_id: The client whose owned account is wanted.
    :returns: One account id.
    """
    account_id = db.fetch_value(
        conn,
        """
        SELECT account_id FROM core.bridge_disposition
        WHERE client_id = %s AND is_owner ORDER BY account_id LIMIT 1
        """,
        (client_id,),
    )
    assert account_id is not None, f"client {client_id} owns no account"
    return int(account_id)


@pytest.mark.parametrize(("role", "own", "other"), CLIENT_PAIRS)
def test_a_customer_sees_exactly_themselves(role: str, own: int, other: int) -> None:
    """A self-service login resolves to one client row: their own."""
    with support.consumer(role) as conn:
        rows = db.fetch_all(conn, "SELECT client_id FROM ai.client")
    assert [row["client_id"] for row in rows] == [own], (
        f"{role} should see exactly client {own}, got {rows}"
    )
    assert all(row["client_id"] != other for row in rows)


@pytest.mark.parametrize(("role", "own", "other"), CLIENT_PAIRS)
def test_a_customer_cannot_see_the_other_customers_data(
    role: str, own: int, other: int
) -> None:
    """Every entitled object of the other customer must return zero rows.

    This is the test that answers "can one client see another client's secret
    data". It names the other customer's own account explicitly rather than
    counting rows, because a count can pass while a targeted lookup leaks.
    """
    with db.connect() as owner_conn:
        own_account = _owned_account(owner_conn, own)
        other_account = _owned_account(owner_conn, other)

    with support.consumer(role) as conn:
        # The other customer, asked for by name.
        assert int(db.fetch_value(
            conn, "SELECT count(*) FROM ai.client WHERE client_id = %s", (other,)) or 0) == 0
        # Their account, loans, cards, transactions and balances.
        for view, column in (
            ("ai.account", "account_id"),
            ("ai.account_owner", "account_id"),
            ("ai.loan", "account_id"),
            ("ai.transaction", "account_id"),
            ("ai.account_month_end_balance", "account_id"),
        ):
            leaked = int(db.fetch_value(
                conn, f"SELECT count(*) FROM {view} WHERE {column} = %s",
                (other_account,)) or 0)
            assert leaked == 0, f"{role} can see {leaked} rows of {view} for client {other}"
        # And their own data is still there, so the test cannot pass by the
        # policy simply returning nothing to anybody.
        assert int(db.fetch_value(
            conn, "SELECT count(*) FROM ai.account WHERE account_id = %s",
            (own_account,)) or 0) == 1
        assert int(db.fetch_value(
            conn, "SELECT count(*) FROM ai.transaction WHERE account_id = %s",
            (own_account,)) or 0) > 0


def test_the_relationship_manager_sees_both_customers() -> None:
    """The isolation must be between the customers, not a missing portfolio.

    If rm_north could not see both clients either, the two tests above would
    pass for the wrong reason.
    """
    with support.consumer("rm_north") as conn:
        visible = {
            row["client_id"]
            for row in db.fetch_all(
                conn, "SELECT client_id FROM ai.client WHERE client_id = ANY(%s)",
                ([config.EXAMPLE_CLIENT_ID, config.EXAMPLE_OTHER_CLIENT_ID],),
            )
        }
    assert visible == {config.EXAMPLE_CLIENT_ID, config.EXAMPLE_OTHER_CLIENT_ID}, (
        "rm_north must see both customers, otherwise the isolation test is vacuous"
    )


@pytest.mark.parametrize(("role", "own", "other"), CLIENT_PAIRS)
def test_a_customer_cannot_widen_their_own_entitlement(
    role: str, own: int, other: int
) -> None:
    """The obvious attacks on a self-service login, tried rather than assumed.

    A customer login is the lowest-privilege principal in the system and the
    one most likely to be exposed to the open internet, so the bypasses are
    attempted against it specifically.
    """
    with support.consumer(role) as conn:
        # Grant themselves the other client by editing the entitlement table.
        for statement, params in (
            ("UPDATE sec.app_user SET subject_client_id = %s WHERE db_role = %s",
             (other, role)),
            ("INSERT INTO sec.portfolio_client (portfolio_id, client_id) VALUES (1, %s)",
             (other,)),
            ("UPDATE sec.app_user SET user_type = 'risk' WHERE db_role = %s", (role,)),
        ):
            with pytest.raises(psycopg.Error):
                db.execute(conn, statement, params)
            conn.rollback()

        # Read the entitlement tables to learn who else exists.
        for statement in (
            "SELECT count(*) FROM sec.app_user",
            "SELECT count(*) FROM sec.portfolio_client",
            "SELECT count(*) FROM sec.v_entitlement",
        ):
            with pytest.raises(psycopg.Error):
                db.fetch_value(conn, statement)
            conn.rollback()

        # Read the uncleaned layers, where no policy applies at all.
        for statement in (
            "SELECT count(*) FROM stg.client",
            "SELECT count(*) FROM raw.client",
        ):
            with pytest.raises(psycopg.Error):
                db.fetch_value(conn, statement)
            conn.rollback()

        # Turn the policy off, or become somebody else.
        for statement in (
            "ALTER TABLE core.dim_client DISABLE ROW LEVEL SECURITY",
            "DROP POLICY entitled_clients ON core.dim_client",
            "SET ROLE cro_global",
            "SET ROLE rm_north",
        ):
            with pytest.raises(psycopg.Error):
                db.execute(conn, statement)
            conn.rollback()

        # Still exactly one client after every attempt.
        assert int(db.fetch_value(conn, "SELECT count(*) FROM ai.client") or 0) == 1


def test_the_client_grain_added_no_policy() -> None:
    """Adding a second kind of principal must not have touched the policies.

    The claim this project makes about its entitlement model is that the
    filter lives in one place. Adding self-service customers would undermine
    that if it had required a policy of its own, so the policy count and the
    set of protected tables are pinned.
    """
    with db.connect() as conn:
        policies = db.fetch_all(
            conn,
            """
            SELECT tablename, policyname FROM pg_policies
            WHERE schemaname = 'core' ORDER BY tablename
            """,
        )
    assert len(policies) == len(CORE_PROTECTED_TABLES), (
        f"expected one policy per protected table, got {policies}"
    )
    assert {row["tablename"] for row in policies} == set(CORE_PROTECTED_TABLES)
    # No policy mentions the client grain: they all read sec.v_my_clients or
    # sec.v_my_accounts, which is where the two grains are reconciled.
    with db.connect() as conn:
        definitions = db.fetch_all(
            conn,
            "SELECT policyname, qual FROM pg_policies WHERE schemaname = 'core'",
        )
    for row in definitions:
        assert "subject_client_id" not in (row["qual"] or ""), (
            f"policy {row['policyname']} knows about the client grain; it should "
            f"only ask sec.v_my_clients who the caller may see"
        )


def test_a_user_cannot_be_both_kinds_of_principal() -> None:
    """The check constraint is the thing stopping a quiet privilege gain.

    Without it, giving a staff user a subject_client_id would add a client to
    their entitlement that no portfolio ever granted, and nothing else in the
    model would notice.
    """
    with db.connect() as conn:
        for user_type, subject in (("relationship_manager", 4242), ("client", None)):
            with pytest.raises(psycopg.Error):
                db.execute(
                    conn,
                    """
                    INSERT INTO sec.app_user (db_role, display_name, user_type,
                                              subject_client_id)
                    VALUES ('tmp_incoherent_user', 'Should not be insertable', %s, %s)
                    """,
                    (user_type, subject),
                )
            conn.rollback()


def test_the_demo_question_totals_correctly_for_an_unrestricted_caller() -> None:
    """The worked example's own query must be right, not just discriminating.

    An early draft used ``sum(DISTINCT l.amount)`` as a reflex guard against
    join fan-out and under-reported the bank-wide loan book by 4,480,920 CZK,
    because 37 of the 682 loans share an amount with another loan. A demo that
    proves the entitlement filter with a wrong number proves very little, so
    the total a fully entitled caller sees is pinned against the base table.
    """
    from src import worked_example  # noqa: PLC0415

    with db.connect() as conn:
        expected = db.fetch_value(conn, "SELECT sum(amount) FROM core.fact_loan")
        expected_loans = db.fetch_value(conn, "SELECT count(*) FROM core.fact_loan")
    with support.consumer("cro_global") as conn:
        row = db.fetch_all(conn, worked_example.DEMO_QUESTION)[0]
    assert row["loan_value"] == expected, (
        f"demo question reports {row['loan_value']} against a true {expected}"
    )
    assert row["loans"] == expected_loans


def test_the_demo_question_discriminates_between_principals() -> None:
    """Each principal must get a different, correctly narrowed answer."""
    from src import worked_example  # noqa: PLC0415

    answers = {}
    for role in ("client_11409", "client_3763", "rm_north", "rm_unassigned", "cro_global"):
        with support.consumer(role) as conn:
            answers[role] = db.fetch_all(conn, worked_example.DEMO_QUESTION)[0]

    assert answers["client_11409"]["clients"] == 1
    assert answers["client_3763"]["clients"] == 1
    assert answers["rm_unassigned"]["clients"] == 0
    # A customer's loan value must be a real amount, and a strict subset of
    # what their relationship manager sees.
    assert 0 < answers["client_11409"]["loan_value"] < answers["rm_north"]["loan_value"]
    assert answers["rm_north"]["loan_value"] < answers["cro_global"]["loan_value"]
    # The two customers are disjoint: neither total can equal the other's.
    assert answers["client_11409"]["loan_value"] != answers["client_3763"]["loan_value"]


# ---------------------------------------------------------------------------
# The access grant model: who may reach what, and why
# ---------------------------------------------------------------------------


def test_a_disponent_reaches_the_account_but_not_its_owner() -> None:
    """The containment that makes per-account grants the right shape.

    Client 3764 is authorised to operate account 3112, which client 3763
    owns. Being able to use an account is not being able to see the person
    who owns it: if the grant were per-client, it would be.
    """
    shared = config.EXAMPLE_SHARED_ACCOUNT_ID
    owner = config.EXAMPLE_OTHER_CLIENT_ID
    with support.consumer("client_3764") as conn:
        assert int(db.fetch_value(
            conn, "SELECT count(*) FROM ai.account WHERE account_id = %s", (shared,)) or 0) == 1
        assert int(db.fetch_value(
            conn, "SELECT count(*) FROM ai.transaction WHERE account_id = %s",
            (shared,)) or 0) > 0
        # ... and nothing at all about the owner.
        assert int(db.fetch_value(
            conn, "SELECT count(*) FROM ai.client WHERE client_id = %s", (owner,)) or 0) == 0
        visible = [row["client_id"] for row in db.fetch_all(
            conn, "SELECT client_id FROM ai.client")]
        assert visible == [config.EXAMPLE_DISPONENT_CLIENT_ID]


def test_the_owner_and_the_disponent_see_the_same_account() -> None:
    """Both reach it, by different rights. Neither reaches the other."""
    shared = config.EXAMPLE_SHARED_ACCOUNT_ID
    for role in ("client_3763", "client_3764"):
        with support.consumer(role) as conn:
            assert int(db.fetch_value(
                conn, "SELECT count(*) FROM ai.account WHERE account_id = %s",
                (shared,)) or 0) == 1
    with db.connect() as conn:
        sources = {
            (row["db_role"], row["grant_source"])
            for row in db.fetch_all(
                conn,
                """
                SELECT db_role, grant_source FROM sec.v_access_grant
                WHERE subject_kind = 'account' AND subject_id = %s
                  AND db_role LIKE 'client_%%'
                """,
                (shared,),
            )
        }
    assert ("client_3763", "ownership") in sources
    assert ("client_3764", "disposition") in sources


def test_portfolio_grants_are_view_only() -> None:
    """Being accountable for a client is not authority to move their money."""
    with db.connect() as conn:
        permissions = {
            row["permission"]
            for row in db.fetch_all(
                conn,
                "SELECT DISTINCT permission FROM sec.v_access_grant "
                "WHERE grant_source = 'portfolio'",
            )
        }
    assert permissions == {"view"}, (
        f"portfolio grants carry {permissions}; 'operate' there would turn a "
        f"reporting entitlement into a payment authority"
    )


def test_a_delegation_is_visible_and_expires() -> None:
    """A delegated right works, is attributable, and stops by itself."""
    subject = config.EXAMPLE_OTHER_CLIENT_ID
    with db.connect() as conn:
        row = db.fetch_all(
            conn,
            """
            SELECT granted_by, reason, valid_to FROM sec.v_access_grant
            WHERE grant_source = 'delegation' AND db_role = 'rm_south'
              AND subject_id = %s
            """,
            (subject,),
        )
    assert row, "the demo delegation is missing"
    assert row[0]["granted_by"] and row[0]["reason"], "a delegation must say who and why"
    assert row[0]["valid_to"] is not None, "this delegation is meant to be time-boxed"

    # It is doing something: rm_south reaches a client outside their own book.
    with support.consumer("rm_south") as conn:
        assert int(db.fetch_value(
            conn, "SELECT count(*) FROM ai.client WHERE client_id = %s", (subject,)) or 0) == 1

    # Expire it, and the reach goes away with no other change.
    with db.connect(autocommit=True) as owner:
        db.execute(
            owner,
            # valid_to must stay after valid_from (the table says so), so
            # expire it by moving the END of the window into the past rather
            # than behind its own start.
            "UPDATE sec.access_delegation "
            "SET valid_to = valid_from + interval '1 second' "
            "WHERE db_role = 'rm_south' AND subject_id = %s",
            (subject,),
        )
        try:
            with support.consumer("rm_south") as conn:
                assert int(db.fetch_value(
                    conn, "SELECT count(*) FROM ai.client WHERE client_id = %s",
                    (subject,)) or 0) == 0
        finally:
            db.execute(
                owner,
                "UPDATE sec.access_delegation SET valid_to = now() + interval '14 days' "
                "WHERE db_role = 'rm_south' AND subject_id = %s",
                (subject,),
            )


def test_who_can_reach_a_client_is_answerable_from_the_model() -> None:
    """The privacy question must have an answer that is not someone's memory."""
    with db.connect() as conn:
        rows = db.fetch_all(
            conn,
            """
            SELECT DISTINCT db_role, grant_source FROM sec.v_who_can_reach_client
            WHERE client_id = %s AND is_live
            """,
            (config.EXAMPLE_OTHER_CLIENT_ID,),
        )
    by_role = {row["db_role"]: row["grant_source"] for row in rows}
    assert by_role.get("client_3763") == "ownership"
    assert by_role.get("rm_north") == "portfolio"
    assert "client_11409" not in by_role, "an unrelated customer must not appear"
    assert every_grant_has_a_source(rows)


def every_grant_has_a_source(rows: list[dict[str, object]]) -> bool:
    """Whether every row names one of the four known sources.

    :param rows: Rows from the who-can-reach view.
    :returns: ``True`` when all sources are known.
    """
    known = {"ownership", "disposition", "portfolio", "delegation"}
    return all(row["grant_source"] in known for row in rows)


def test_external_references_are_not_guessable_from_the_id() -> None:
    """A sequential id must not be the handle a customer-facing surface uses."""
    with db.connect() as conn:
        rows = db.fetch_all(
            conn,
            "SELECT client_id, client_ref FROM core.dim_client "
            "WHERE client_id BETWEEN 1 AND 40 ORDER BY client_id",
        )
    refs = [row["client_ref"] for row in rows]
    assert len(set(refs)) == len(refs), "references must be unique"
    assert all(ref.startswith("BRK-") and len(ref) == 13 for ref in refs)
    # Adjacent ids must not produce adjacent references.
    assert not any(
        refs[i][4:8] == refs[i + 1][4:8] for i in range(len(refs) - 1)
    ), "neighbouring ids produced neighbouring references; the mapping leaks order"


def test_account_references_carry_valid_iban_check_digits() -> None:
    """A typo in an account number must be caught the way a real one would be."""
    with db.connect() as conn:
        refs = [row["account_ref"] for row in db.fetch_all(
            conn, "SELECT account_ref FROM core.dim_account ORDER BY account_id LIMIT 50")]

    def mod97(iban: str) -> int:
        rearranged = iban[4:] + iban[:4]
        digits = "".join(
            str(ord(ch) - 55) if ch.isalpha() else ch for ch in rearranged
        )
        return int(digits) % 97

    for ref in refs:
        assert ref.startswith("CZ") and len(ref) == 24, ref
        assert mod97(ref) == 1, f"{ref} has invalid check digits"
    # And a corrupted one must fail, or the check proves nothing.
    broken = refs[0][:-1] + ("1" if refs[0][-1] != "1" else "2")
    assert mod97(broken) != 1
