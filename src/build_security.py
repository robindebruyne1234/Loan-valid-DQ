"""Apply the entitlement model, the row level security policies and the demo users.

Task 3 asks three things, and this module is where each is made concrete
rather than described:

* **Where the filter sits.** On the core tables, as row level security
  policies, applied by the database engine inside every plan. The ai views are
  ``security_invoker``, so they evaluate those policies as the calling user.
* **Why an LLM-generated query cannot bypass it.** The LLM never holds a
  connection. It emits text; the guard parses it; the statement runs on a
  session authenticated as a policy-bound role. The predicate is not in the
  query, so rewriting the query cannot remove it. ``tests/test_rls.py`` tries
  nine bypasses and all nine fail.
* **How a new user or portfolio is onboarded without code changes.** By
  inserting rows. :func:`onboard_user` and :func:`onboard_portfolio` are
  nothing but inserts, and they are what the demo seeding uses -- so the
  onboarding path is the one that is exercised, not a separate story.

Run with ``make entitlements``.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg import sql as pgsql

from src import config, db

LOGGER = db.setup_logging("security")

#: Demo portfolios: code, description, and the regions whose clients belong to
#: it. ``None`` means "every client", which is how an unrestricted consumer is
#: modelled -- through data, not through privilege.
DEMO_PORTFOLIOS: tuple[tuple[str, str, tuple[str, ...] | None], ...] = (
    (
        "NORTH_BOOK",
        "Clients living in the northern regions (north Bohemia, north Moravia)",
        ("north Bohemia", "north Moravia"),
    ),
    (
        "SOUTH_BOOK",
        "Clients living in the southern regions (south Bohemia, south Moravia)",
        ("south Bohemia", "south Moravia"),
    ),
    (
        "PRAGUE_BOOK",
        "Clients living in Prague",
        ("Prague",),
    ),
    (
        "ALL_CLIENTS",
        "Every client in the bank; held by group risk, for bank-wide reporting",
        None,
    ),
)

#: Demo users: login role, display name, type, and the portfolios they hold.
#: ``rm_unassigned`` holds none on purpose: it is the proof that the default is
#: "see nothing" rather than "see everything".
DEMO_USERS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("rm_north", "Relationship manager, northern book", "relationship_manager",
     ("NORTH_BOOK",)),
    ("rm_south", "Relationship manager, southern book", "relationship_manager",
     ("SOUTH_BOOK",)),
    ("cro_global", "Group risk, bank-wide reporting", "risk",
     ("ALL_CLIENTS",)),
    ("rm_unassigned", "Newly created user with no portfolio yet", "relationship_manager",
     ()),
)


def create_login_role(conn: psycopg.Connection, role: str, password: str) -> None:
    """Create a login role that inherits the ``ai_consumer`` privileges.

    This is the only DDL in the onboarding path, and it is a *credential*
    rather than business logic: the role carries no permissions of its own, it
    inherits them from ``ai_consumer``, and what it may see is decided entirely
    by the rows in ``sec``.

    :param conn: Open connection as a role that may create roles.
    :param role: Login role name.
    :param password: Password for the role.
    :returns: ``None``.
    """
    exists = db.fetch_value(conn, "SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
    # CREATE ROLE and ALTER ROLE are utility statements and take no bind
    # parameters, so the identifier and the password are composed with
    # psycopg's quoting rather than interpolated by hand.
    statement = pgsql.SQL(
        "ALTER ROLE {role} LOGIN PASSWORD {password}"
        if exists
        else "CREATE ROLE {role} LOGIN PASSWORD {password} IN ROLE ai_consumer"
    ).format(role=pgsql.Identifier(role), password=pgsql.Literal(password))
    with conn.cursor() as cur:
        cur.execute(statement)
        cur.execute(pgsql.SQL("GRANT ai_consumer TO {}").format(pgsql.Identifier(role)))


def onboard_portfolio(
    conn: psycopg.Connection, code: str, description: str, regions: tuple[str, ...] | None
) -> int:
    """Create a portfolio and fill it with clients. Pure inserts.

    :param conn: Open connection.
    :param code: Portfolio code, unique.
    :param description: What the portfolio is, in business words.
    :param regions: Regions whose resident clients join the portfolio, or
        ``None`` for every client in the bank.
    :returns: Number of clients placed in the portfolio.
    """
    portfolio_id = db.fetch_value(
        conn,
        """
        INSERT INTO sec.portfolio (portfolio_code, description)
        VALUES (%s, %s)
        ON CONFLICT (portfolio_code) DO UPDATE SET description = excluded.description
        RETURNING portfolio_id
        """,
        (code, description),
    )
    if regions is None:
        db.execute(
            conn,
            """
            INSERT INTO sec.portfolio_client (portfolio_id, client_id)
            SELECT %s, client_id FROM core.dim_client
            ON CONFLICT DO NOTHING
            """,
            (portfolio_id,),
        )
    else:
        db.execute(
            conn,
            """
            INSERT INTO sec.portfolio_client (portfolio_id, client_id)
            SELECT %s, c.client_id
            FROM core.dim_client c
            JOIN core.dim_district d ON d.district_id = c.district_id
            WHERE d.region = ANY (%s)
            ON CONFLICT DO NOTHING
            """,
            (portfolio_id, list(regions)),
        )
    clients = db.fetch_value(
        conn,
        "SELECT count(*) FROM sec.portfolio_client WHERE portfolio_id = %s",
        (portfolio_id,),
    )
    LOGGER.info("portfolio %-12s -> %5d clients", code, clients)
    return int(clients or 0)


def onboard_user(
    conn: psycopg.Connection,
    db_role: str,
    display_name: str,
    user_type: str,
    portfolios: tuple[str, ...],
) -> None:
    """Register a user and grant them portfolios. Pure inserts.

    :param conn: Open connection.
    :param db_role: The PostgreSQL login role the person authenticates as.
    :param display_name: Human-readable name for administration.
    :param user_type: Free-form classification, for reporting.
    :param portfolios: Portfolio codes to grant.
    :returns: ``None``.
    """
    app_user_id = db.fetch_value(
        conn,
        """
        INSERT INTO sec.app_user (db_role, display_name, user_type)
        VALUES (%s, %s, %s)
        ON CONFLICT (db_role) DO UPDATE
            SET display_name = excluded.display_name,
                user_type    = excluded.user_type,
                is_active    = true
        RETURNING app_user_id
        """,
        (db_role, display_name, user_type),
    )
    for code in portfolios:
        db.execute(
            conn,
            """
            INSERT INTO sec.user_portfolio (app_user_id, portfolio_id)
            SELECT %s, portfolio_id FROM sec.portfolio WHERE portfolio_code = %s
            ON CONFLICT DO NOTHING
            """,
            (app_user_id, code),
        )
    LOGGER.info(
        "user      %-12s -> portfolios: %s",
        db_role,
        ", ".join(portfolios) if portfolios else "(none yet)",
    )


def summarise_entitlements(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Report, per demo user, how many clients and accounts they can see.

    The counts are produced by connecting **as each user** and querying the ai
    views, so they are what the policies actually return rather than what the
    entitlement tables intend.

    :param conn: Open connection as the owner (used only for the user list).
    :returns: One dictionary per user with the visible row counts.
    """
    users = db.fetch_all(
        conn, "SELECT db_role, display_name FROM sec.app_user ORDER BY db_role"
    )
    summary: list[dict[str, Any]] = []
    for user in users:
        role = user["db_role"]
        with db.connect(user=role) as user_conn:
            row = db.fetch_all(
                user_conn,
                """
                SELECT (SELECT count(*) FROM ai.client)                  AS clients,
                       (SELECT count(*) FROM ai.account)                 AS accounts,
                       (SELECT count(*) FROM ai.loan)                    AS loans,
                       (SELECT count(*) FROM ai.transaction)             AS transactions,
                       (SELECT count(*) FROM ai.district)                AS districts,
                       (SELECT portfolios FROM ai.my_entitlement)        AS portfolios
                """,
            )[0]
        entry = {"db_role": role, "display_name": user["display_name"], **row}
        summary.append(entry)
        LOGGER.info(
            "visible to %-14s clients=%-6s accounts=%-6s loans=%-5s transactions=%-8s "
            "districts=%-3s portfolios=%s",
            role,
            row["clients"],
            row["accounts"],
            row["loans"],
            row["transactions"],
            row["districts"],
            row["portfolios"] or "(none)",
        )
    return summary


def main() -> int:
    """Build the ai views, apply the security model and seed the demo users.

    :returns: Process exit code, ``0`` on success.
    """
    with db.connect(autocommit=True) as conn:
        # Order matters: the entitlement views live in sec and ai.my_entitlement
        # reads them, so sec is built first.
        LOGGER.info("--- applying the entitlement model and row level security ---")
        db.run_sql_file(conn, config.SQL_DIR / "50_sec_rls.sql", LOGGER)

        LOGGER.info("--- building the ai consumer views ---")
        db.run_sql_file(conn, config.SQL_DIR / "40_ai_views.sql", LOGGER)

        LOGGER.info("--- onboarding the demo portfolios and users (inserts only) ---")
        for code, description, regions in DEMO_PORTFOLIOS:
            onboard_portfolio(conn, code, description, regions)
        for role, display_name, user_type, portfolios in DEMO_USERS:
            create_login_role(conn, role, config.DEMO_USER_PASSWORD)
            onboard_user(conn, role, display_name, user_type, portfolios)

        # Re-grant on the ai views, which were dropped and recreated above.
        db.execute(conn, "GRANT SELECT ON ALL TABLES IN SCHEMA ai TO ai_consumer")

        policies = db.fetch_all(
            conn,
            """
            SELECT schemaname, tablename, policyname, roles::text AS roles
            FROM pg_policies WHERE schemaname = 'core' ORDER BY tablename
            """,
        )
        LOGGER.info("--- %d row level security policies active ---", len(policies))
        for policy in policies:
            LOGGER.info("  %-34s %-22s %s",
                        f"core.{policy['tablename']}", policy["policyname"], policy["roles"])

        LOGGER.info("--- what each user can actually see ---")
        summary = summarise_entitlements(conn)

    db.record_run(
        "entitlements",
        "make entitlements",
        {"policies": len(policies), "visible_rows": summary},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
