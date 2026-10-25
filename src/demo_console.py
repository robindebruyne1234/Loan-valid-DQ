"""A switchable login console, for demonstrating privacy to an audience.

Run it with ``make demo-login``. It shows one thing, repeatedly and from
different angles: **the data a person can reach is decided by who they proved
themselves to be, and by nothing else.**

Each round is a real two-step login against the real database. Nothing is
simulated except the authenticator app: the console prints the one-time code
that a customer's phone would show, because a stakeholder demo cannot hand
six phones around. Everything else -- the password check, the code
verification, the session, the row filtering -- is the production path.

Modes:

``--script``
    Run the scripted stakeholder walkthrough end to end, unattended. This is
    what ``make demo-login`` runs and what docs/DEMO_SCRIPT.md narrates.
``--interactive``
    Pick a persona, type the code yourself, run queries, switch. For when an
    audience wants to drive.
``--as ROLE``
    Log in as one principal and print what they can reach.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

import psycopg

from src import auth, config, db

LOGGER = db.setup_logging("console")

WIDTH = 78

#: The personas, in the order the stakeholder script introduces them. The
#: narrative order matters: a customer first, so "this is what a person sees"
#: is established before anything is compared to it.
PERSONAS: tuple[tuple[str, str], ...] = (
    ("client_3763", "Customer. Owns one account."),
    ("client_3764", "Customer. Owns nothing, but may OPERATE 3763's account."),
    ("client_11409", "Customer. Unrelated to the other two."),
    ("rm_north", "Relationship manager. Holds the northern book."),
    ("rm_south", "Relationship manager. Holds the southern book."),
    ("rm_unassigned", "New employee. Granted nothing yet."),
    ("admin_demo", "Administrator. Holds a book containing every client."),
    ("cro_global", "Group risk. Bank-wide reporting."),
)


def rule(title: str = "", char: str = "-") -> None:
    """Print a labelled horizontal rule.

    :param title: Optional label.
    :param char: Rule character.
    :returns: ``None``.
    """
    if not title:
        print(char * WIDTH)
    else:
        print(f"{char * 3} {title} " + char * max(0, WIDTH - len(title) - 5))


def describe(conn: psycopg.Connection) -> dict[str, Any]:
    """Read what the authenticated principal can reach.

    :param conn: An authenticated connection.
    :returns: Counts and identifiers, as that principal sees them.
    """
    entitlement = db.fetch_all(conn, "SELECT * FROM ai.my_entitlement")[0]
    clients = db.fetch_all(
        conn, "SELECT client_id, client_ref FROM ai.client ORDER BY client_id LIMIT 6")
    accounts = db.fetch_all(
        conn, "SELECT account_id, account_ref FROM ai.account ORDER BY account_id LIMIT 6")
    totals = db.fetch_all(
        conn,
        """
        SELECT (SELECT count(*) FROM ai.client)      AS clients,
               (SELECT count(*) FROM ai.account)     AS accounts,
               (SELECT count(*) FROM ai.loan)        AS loans,
               (SELECT count(*) FROM ai.transaction) AS transactions
        """,
    )[0]
    return {"entitlement": entitlement, "clients": clients,
            "accounts": accounts, "totals": totals}


def show(role: str, label: str, view: dict[str, Any]) -> None:
    """Print one principal's reach.

    :param role: The login.
    :param label: What this persona is, in business words.
    :param view: The result of :func:`describe`.
    :returns: ``None``.
    """
    totals, ent = view["totals"], view["entitlement"]
    print(f"  logged in as : {role}   ({label})")
    # A principal granted nothing has NULL here. "None" is Python leaking into
    # a stakeholder demo; "(nothing yet)" is the point being made.
    entitled = ent["portfolios"] or "(nothing yet)"
    print(f"  principal    : {ent['principal_type']}, entitled to {entitled}")
    print(f"  can reach    : {totals['clients']:,} clients | "
          f"{totals['accounts']:,} accounts | {totals['loans']:,} loans | "
          f"{totals['transactions']:,} transactions")
    if view["clients"]:
        shown = ", ".join(f"{c['client_id']} ({c['client_ref']})" for c in view["clients"])
        more = "" if totals["clients"] <= 6 else f", ... and {totals['clients'] - 6:,} more"
        print(f"  clients      : {shown}{more}")
    if view["accounts"]:
        shown = ", ".join(f"{a['account_ref']}" for a in view["accounts"])
        more = "" if totals["accounts"] <= 6 else f", ... and {totals['accounts'] - 6:,} more"
        print(f"  accounts     : {shown}{more}")


def login_round(role: str, label: str, *, type_code: str | None = None,
                show_steps: bool = True) -> dict[str, Any] | None:
    """Perform one full two-step login and print what it unlocks.

    :param role: The principal.
    :param label: Business description of the persona.
    :param type_code: A code to present instead of the generated one, for
        showing what a wrong code does.
    :param show_steps: Print the intermediate state between the two factors.
    :returns: The principal's view, or ``None`` when the login failed.
    """
    print()
    rule(f"LOGIN: {role}")
    code = type_code if type_code is not None else auth.demo_fresh_code(role)

    print("  step 1 of 2  : password ... accepted")
    conn = db.connect(user=role, password=config.DEMO_USER_PASSWORD)
    try:
        if show_steps:
            # The moment worth pausing on in front of an audience.
            before = int(db.fetch_value(conn, "SELECT count(*) FROM ai.client") or 0)
            print(f"  BETWEEN STEPS: authenticated, but can reach {before} clients. "
                  f"The password alone is worth nothing.")
        source = "(a wrong code)" if type_code is not None else "(from the authenticator app)"
        print(f"  step 2 of 2  : one-time code {code} {source}")
        try:
            auth.verify_second_factor(conn, code)
        except auth.AuthenticationError as exc:
            print(f"  REFUSED      : {exc}")
            print(f"  can reach    : "
                  f"{db.fetch_value(conn, 'SELECT count(*) FROM ai.client')} clients")
            return None
        print("  step 2 of 2  : accepted")
        view = describe(conn)
        print()
        show(role, label, view)
        return view
    finally:
        try:
            db.fetch_value(conn, "SELECT sec.end_session()")
            conn.commit()
        except psycopg.Error:
            pass
        conn.close()


def cross_check(viewer: str, target_client: int, target_account: int) -> None:
    """Log in as one person and try to read another's data by name.

    :param viewer: The principal doing the looking.
    :param target_client: The client id they must not see.
    :param target_account: The account id they must not see.
    :returns: ``None``.
    """
    print()
    rule(f"{viewer} ASKS FOR CLIENT {target_client} BY NAME")
    with auth.login(viewer, demo_autocode=True) as conn:
        probes = (
            (f"their client record (id {target_client})",
             "SELECT count(*) FROM ai.client WHERE client_id = %s", (target_client,)),
            (f"their account (id {target_account})",
             "SELECT count(*) FROM ai.account WHERE account_id = %s", (target_account,)),
            ("their transactions",
             "SELECT count(*) FROM ai.transaction WHERE account_id = %s", (target_account,)),
            ("the base table, going around the views",
             "SELECT count(*) FROM core.fact_transaction WHERE account_id = %s",
             (target_account,)),
            ("the uncleaned staging copy",
             "SELECT count(*) FROM stg.trans WHERE account_id = %s", (target_account,)),
            ("who else uses the system",
             "SELECT count(*) FROM sec.app_user", ()),
            ("granting themselves that client",
             "UPDATE sec.app_user SET subject_client_id = %s WHERE db_role = session_user",
             (target_client,)),
        )
        for description, sql, params in probes:
            try:
                value = db.fetch_value(conn, sql, params or None)
                verdict = "LEAK" if (value or 0) else "0 rows  (policy)"
            except psycopg.Error as exc:
                conn.rollback()
                verdict = f"refused (privilege): {str(exc).strip().splitlines()[0][:38]}"
            print(f"  {description:<46} {verdict}")


def who_can_reach(client_id: int) -> None:
    """Print every principal who can reach a client, and why.

    :param client_id: The client to report on.
    :returns: ``None``.
    """
    print()
    rule(f"WHO CAN REACH CLIENT {client_id}, AND WHY")
    with db.connect() as conn:
        rows = db.fetch_all(
            conn,
            """
            SELECT DISTINCT db_role, user_type, permission, grant_source, reason
            FROM sec.v_who_can_reach_client
            WHERE client_id = %s AND is_live
            ORDER BY grant_source, db_role, permission
            """,
            (client_id,),
        )
    print(f"  {'principal':<14}{'kind':<21}{'may':<8}{'because':<12}reason")
    for row in rows:
        reason = row["reason"] or ""
        # The reason is the column that earns this view its place, so it gets
        # the space left over rather than the first truncation.
        if len(reason) > 55:
            reason = reason[:54].rstrip() + "\u2026"
        print(f"  {row['db_role']:<14}{row['user_type']:<21}{row['permission']:<8}"
              f"{row['grant_source']:<12}{reason}")
    print(f"  -- {len(rows)} live grants. This is the answer to a privacy question,")
    print("     and it comes from the model rather than from someone's memory.")


def scripted() -> int:
    """Run the stakeholder walkthrough end to end, unattended.

    Seven acts, each proving one thing. The order is the argument: establish
    what a customer sees, show a second customer is invisible to the first,
    show the manager who sees both, show that the password alone is worthless,
    and only then explain the machinery.

    :returns: Process exit code; non-zero if anything leaked.
    """
    rule("THE GOVERNED DATA PRODUCT -- PRIVACY WALKTHROUGH", "=")
    print("Every login below is real. The only thing simulated is the")
    print("authenticator app: the console prints the code a customer's phone")
    print("would show, because an audience cannot share six phones.")

    print()
    rule("ACT 1 -- A CUSTOMER LOGS IN", "=")
    print("Klara owns one account. This is her whole view of the bank.")
    login_round("client_3763", "Customer, owns account 3112")

    print()
    rule("ACT 2 -- A SECOND CUSTOMER, IN THE SAME MANAGER'S BOOK", "=")
    print("Petr may OPERATE Klara's account -- the bank authorised him -- but")
    print("he does not own it, and he is not her.")
    login_round("client_3764", "Customer, disponent on account 3112")
    print()
    print("  NOTE: he reaches the same ACCOUNT, and not her CLIENT record.")
    print("        Being able to use an account is not being able to see its")
    print("        owner. That containment is a design choice, and it is the")
    print("        reason the right is granted per account, not per person.")

    print()
    rule("ACT 3 -- CAN ONE CUSTOMER READ ANOTHER?", "=")
    cross_check("client_11409", config.EXAMPLE_OTHER_CLIENT_ID,
                config.EXAMPLE_SHARED_ACCOUNT_ID)
    print()
    print("  Two different kinds of refusal, and the second is the stronger:")
    print("  'refused' means the statement was blocked. '0 rows' means the")
    print("  statement RAN and the engine had already narrowed the answer.")

    print()
    rule("ACT 4 -- THE PEOPLE WHO LOOK AFTER THEM", "=")
    for role, label in (("rm_north", "Relationship manager, northern book"),
                        ("rm_unassigned", "New employee, granted nothing yet")):
        login_round(role, label, show_steps=False)
    print()
    print("  The manager sees both customers from Acts 1 and 2, because both")
    print("  are in her book. Neither customer can see the other. And a new")
    print("  employee starts at zero: the default is see nothing.")

    print()
    rule("ACT 5 -- THE PASSWORD ON ITS OWN IS WORTH NOTHING", "=")
    print("The administrator can see every client in the bank. Watch what")
    print("happens when they have the password but not the second factor.")
    login_round("admin_demo", "Administrator", type_code="000000")
    print()
    print("  A stolen password is not a breach here. It is a login that")
    print("  returns an empty database.")
    login_round("admin_demo", "Administrator")

    print()
    rule("ACT 6 -- WHY EACH PERSON CAN REACH WHAT THEY REACH", "=")
    who_can_reach(config.EXAMPLE_OTHER_CLIENT_ID)

    print()
    rule("ACT 7 -- WHAT THE MODEL IS", "=")
    with db.connect() as conn:
        for row in db.fetch_all(
            conn,
            """
            SELECT grant_source, permission, count(*) AS n
            FROM sec.v_access_grant
            WHERE sec.grant_is_live(valid_from, valid_to)
            GROUP BY 1, 2 ORDER BY 1, 2
            """,
        ):
            print(f"  {row['grant_source']:<14}{row['permission']:<10}{row['n']:>8,} live grants")
    print()
    print("  Four sources of access, one shape. Three are derived from the")
    print("  bank's own records, so they cannot drift; only delegation is a")
    print("  human decision, and every one of those carries a reason.")
    print()
    rule("END", "=")
    return 0


def interactive() -> int:
    """Let the audience drive: choose a persona, type the code, switch.

    :returns: Process exit code.
    """
    while True:
        print()
        rule("CHOOSE A PERSONA", "=")
        for index, (role, label) in enumerate(PERSONAS, 1):
            print(f"  {index}. {role:<15} {label}")
        print("  q. quit")
        choice = input("\n  persona> ").strip().lower()
        if choice in ("q", "quit", "exit", ""):
            return 0
        if not choice.isdigit() or not 1 <= int(choice) <= len(PERSONAS):
            print("  -- not one of the options")
            continue
        role, label = PERSONAS[int(choice) - 1]

        code = auth.demo_fresh_code(role)
        print()
        print(f"  Step 1: connecting as {role} with their password ...")
        conn = db.connect(user=role, password=config.DEMO_USER_PASSWORD)
        try:
            seen = db.fetch_value(conn, "SELECT count(*) FROM ai.client")
            print(f"          connected, and can reach {seen} clients.")
            print()
            print(f"  Step 2: their authenticator app is showing  {code}")
            print(f"          (valid for another {auth.seconds_remaining()}s)")
            typed = input("          enter the code> ").strip()
            try:
                auth.verify_second_factor(conn, typed)
            except auth.AuthenticationError as exc:
                print(f"\n  REFUSED: {exc}")
                print(f"  Still reaching {db.fetch_value(conn, 'SELECT count(*) FROM ai.client')} clients.")
                continue
            print("          accepted.\n")
            show(role, label, describe(conn))
            while True:
                query = input("\n  SQL (or 'back')> ").strip()
                if query.lower() in ("back", "b", ""):
                    break
                try:
                    rows = db.fetch_all(conn, query)
                    print(f"  -> {len(rows)} row(s)")
                    for row in rows[:10]:
                        print(f"     {row}")
                except psycopg.Error as exc:
                    conn.rollback()
                    print(f"  -> refused: {str(exc).strip().splitlines()[0]}")
        finally:
            try:
                db.fetch_value(conn, "SELECT sec.end_session()")
                conn.commit()
            except psycopg.Error:
                pass
            conn.close()


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    :param argv: Command-line arguments.
    :returns: Process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--script", action="store_true",
                       help="run the scripted stakeholder walkthrough (default)")
    group.add_argument("--interactive", action="store_true",
                       help="choose personas and type codes by hand")
    group.add_argument("--as", dest="role", help="log in as one principal and stop")
    args = parser.parse_args(argv)

    if args.interactive:
        return interactive()
    if args.role:
        labels = dict(PERSONAS)
        return 0 if login_round(args.role, labels.get(args.role, "")) else 1
    return scripted()


if __name__ == "__main__":
    sys.exit(main())
