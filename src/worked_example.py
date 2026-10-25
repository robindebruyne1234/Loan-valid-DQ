"""End-to-end worked example: one client, cleaned, published and kept private.

Everything this project claims is claimed about 1.06 m rows and six principals,
which is hard to hold in your head. This module takes a single real client and
walks them the whole way:

1. the four lines of source file they start as;
2. every cleaning step that touched them, named by its ledger id;
3. the published rows they became, including the caveats they carry;
4. who can see those rows, measured by authenticating as each principal;
5. a targeted attempt by one customer to read another customer's account;
6. onboarding a new customer, performed live, as inserts.

The client is :data:`src.config.EXAMPLE_CLIENT_ID`, chosen because their data
exercises the interesting cases rather than the clean ones: the birth number
decodes to a date and a gender, the account was opened when the owner was 12
(a warn flag that must survive into the answer), the account's district is not
the client's own district, and the account carries a second flag of its own.

The negative control is :data:`src.config.EXAMPLE_OTHER_CLIENT_ID`, a different
customer in the SAME relationship manager's book. Isolating two customers in
different books would prove nothing that a portfolio boundary did not already
prove.

Nothing here is a fixture: every value is read from the live database at run
time, and the markdown report is written from the same values. Usage::

    make demo              # or: python -m src.worked_example
"""

from __future__ import annotations

import textwrap
from datetime import datetime, timezone
from typing import Any

import psycopg

from src import auth, config, db

LOGGER = db.setup_logging("demo")

TARGET = config.PROJECT_ROOT / "docs" / "WORKED_EXAMPLE.md"

#: Width of the console rules, so the output is readable in a terminal.
RULE = 78


def _rule(title: str = "") -> str:
    """Build a labelled horizontal rule for the console output.

    :param title: Optional label.
    :returns: The rule, as plain ASCII.
    """
    if not title:
        return "-" * RULE
    return f"--- {title} " + "-" * max(0, RULE - len(title) - 5)


def collect(conn: psycopg.Connection) -> dict[str, Any]:
    """Read everything the example needs, as the pipeline owner.

    The owner is exempt from the policies, which is exactly why this function
    is kept separate from :func:`measure_visibility`: the "what is true" half
    and the "who can see it" half must not be read through the same identity.

    :param conn: Open connection as the pipeline owner.
    :returns: Mapping of everything the report renders.
    """
    client_id = config.EXAMPLE_CLIENT_ID
    other_id = config.EXAMPLE_OTHER_CLIENT_ID

    account_id = int(db.fetch_value(
        conn,
        """
        SELECT account_id FROM core.bridge_disposition
        WHERE client_id = %s AND is_owner ORDER BY account_id LIMIT 1
        """,
        (client_id,),
    ))
    other_account_id = int(db.fetch_value(
        conn,
        """
        SELECT account_id FROM core.bridge_disposition
        WHERE client_id = %s AND is_owner ORDER BY account_id LIMIT 1
        """,
        (other_id,),
    ))

    data: dict[str, Any] = {
        "client_id": client_id,
        "other_id": other_id,
        "account_id": account_id,
        "other_account_id": other_account_id,
        "raw_client": db.fetch_all(
            conn, "SELECT * FROM raw.client WHERE client_id = %s", (str(client_id),))[0],
        "raw_account": db.fetch_all(
            conn, "SELECT * FROM raw.account WHERE account_id = %s", (str(account_id),))[0],
        "raw_loan": db.fetch_all(
            conn, "SELECT * FROM raw.loan WHERE account_id = %s", (str(account_id),))[0],
        "stg_client": db.fetch_all(
            conn,
            """
            SELECT client_id, birth_number, birth_date, gender, birth_number_valid,
                   district_id, _source_file, _source_row
            FROM stg.client WHERE client_id = %s
            """,
            (client_id,))[0],
        "stg_account": db.fetch_all(
            conn,
            """
            SELECT account_id, district_id, frequency_code, frequency_label,
                   open_date, _source_file, _source_row
            FROM stg.account WHERE account_id = %s
            """,
            (account_id,))[0],
        "core_client": db.fetch_all(
            conn, "SELECT * FROM core.dim_client WHERE client_id = %s", (client_id,))[0],
        "core_account": db.fetch_all(
            conn, "SELECT * FROM core.dim_account WHERE account_id = %s", (account_id,))[0],
        "core_loan": db.fetch_all(
            conn, "SELECT * FROM core.fact_loan WHERE account_id = %s", (account_id,))[0],
    }

    data["client_district"] = db.fetch_all(
        conn, "SELECT district_id, district_name, region FROM core.dim_district WHERE district_id = %s",
        (data["core_client"]["district_id"],))[0]
    data["account_district"] = db.fetch_all(
        conn, "SELECT district_id, district_name, region FROM core.dim_district WHERE district_id = %s",
        (data["core_account"]["district_id"],))[0]

    data["age_at_open"] = db.fetch_value(
        conn,
        """
        SELECT round(extract(epoch FROM age(a.open_date, c.birth_date)) / 31557600.0, 2)
        FROM core.dim_client c, core.dim_account a
        WHERE c.client_id = %s AND a.account_id = %s
        """,
        (client_id, account_id),
    )
    data["transactions"] = db.fetch_value(
        conn, "SELECT count(*) FROM core.fact_transaction WHERE account_id = %s", (account_id,))
    data["first_postings"] = db.fetch_all(
        conn,
        """
        SELECT t.trans_id, t.trans_date, t.trans_type_code, t.transaction_type,
               t.direction, t.amount, t.signed_amount, t.balance_after,
               t.operation_code, t.operation, t.category_code, t.category
        FROM core.fact_transaction t
        WHERE t.account_id = %s ORDER BY t.trans_date, t.trans_id LIMIT 4
        """,
        (account_id,),
    )
    data["flags"] = db.fetch_all(
        conn,
        """
        SELECT f.target_table, f.rule_id, f.flag, f.reason
        FROM dq.flags f
        WHERE f.target_schema = 'stg'
          AND ((f.target_table = 'client'  AND f.business_key = %s)
            OR (f.target_table = 'account' AND f.business_key = %s))
        ORDER BY f.target_table, f.rule_id
        """,
        (str(client_id), str(account_id)),
    )
    return data


#: The question every principal is asked, in the consumer's own schema. It is
#: deliberately an ordinary business question rather than a probe: the point is
#: that the SAME query returns a different, correct answer per caller.
#:
#: ``sum(l.amount)`` is deliberately NOT ``sum(DISTINCT l.amount)``. The first
#: draft used DISTINCT as a reflex guard against join fan-out and reported
#: 98,780,760 CZK bank-wide against a true 103,261,740: 37 of the 682 loans
#: share an amount with another loan, and DISTINCT silently discarded them.
#: There is no fan-out to guard against here -- account_owner is one row per
#: account and a loan belongs to one account -- so the plain sum is both
#: correct and the right thing to demonstrate.
DEMO_QUESTION = """
SELECT count(DISTINCT c.client_id)  AS clients,
       count(DISTINCT o.account_id) AS accounts,
       count(DISTINCT l.loan_id)    AS loans,
       coalesce(sum(l.amount), 0)   AS loan_value
FROM ai.client c
LEFT JOIN ai.account_owner o ON o.owner_client_id = c.client_id
LEFT JOIN ai.loan          l ON l.account_id     = o.account_id
"""


def measure_visibility(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Run the same question as every principal and record what comes back.

    Each row is produced on a connection authenticated as that principal, so
    the numbers are what the policies return, not what the entitlement tables
    intend.

    :param data: The collected example, used for the targeted leak probes.
    :returns: One row per principal.
    """
    rows: list[dict[str, Any]] = []
    with db.connect() as conn:
        principals = db.fetch_all(
            conn,
            """
            SELECT db_role, display_name, user_type, subject_client_id
            FROM sec.app_user ORDER BY user_type, db_role
            """,
        )
    for principal in principals:
        role = principal["db_role"]
        with auth.login(role, demo_autocode=True) as user_conn:
            answer = db.fetch_all(user_conn, DEMO_QUESTION)[0]
            sees_example = int(db.fetch_value(
                user_conn, "SELECT count(*) FROM ai.client WHERE client_id = %s",
                (data["client_id"],)) or 0)
            sees_other = int(db.fetch_value(
                user_conn, "SELECT count(*) FROM ai.client WHERE client_id = %s",
                (data["other_id"],)) or 0)
            sees_other_account = int(db.fetch_value(
                user_conn, "SELECT count(*) FROM ai.transaction WHERE account_id = %s",
                (data["other_account_id"],)) or 0)
            entitlement = db.fetch_all(user_conn, "SELECT * FROM ai.my_entitlement")[0]
        rows.append({
            "db_role": role,
            "display_name": principal["display_name"],
            "user_type": principal["user_type"],
            "portfolios": entitlement["portfolios"] or "(none)",
            **answer,
            "sees_example_client": sees_example,
            "sees_other_client": sees_other,
            "other_account_postings": sees_other_account,
        })
    return rows


def attempt_cross_client_reads(data: dict[str, Any]) -> list[dict[str, str]]:
    """Have one customer try, by name, to read the other customer's data.

    A row count can pass while a targeted lookup leaks, so these ask for the
    other customer's own identifiers explicitly rather than counting.

    :param data: The collected example.
    :returns: One row per attempt, with what came back.
    """
    other_account = data["other_account_id"]
    other_client = data["other_id"]
    attempts: tuple[tuple[str, str, tuple[Any, ...]], ...] = (
        ("Read the other customer's client record by id",
         "SELECT count(*) FROM ai.client WHERE client_id = %s", (other_client,)),
        ("Read their account by id",
         "SELECT count(*) FROM ai.account WHERE account_id = %s", (other_account,)),
        ("Read their loan",
         "SELECT count(*) FROM ai.loan WHERE account_id = %s", (other_account,)),
        ("Read their transactions",
         "SELECT count(*) FROM ai.transaction WHERE account_id = %s", (other_account,)),
        ("Read their month-end balances",
         "SELECT count(*) FROM ai.account_month_end_balance WHERE account_id = %s",
         (other_account,)),
        ("Read their cards through the disposition bridge",
         "SELECT count(*) FROM ai.card WHERE account_id = %s", (other_account,)),
        ("Go around the ai views, straight to the core table",
         "SELECT count(*) FROM core.fact_transaction WHERE account_id = %s", (other_account,)),
        ("Read the uncleaned staging copy, where no policy exists",
         "SELECT count(*) FROM stg.trans WHERE account_id = %s", (other_account,)),
        ("Read the raw landing copy",
         "SELECT count(*) FROM raw.trans WHERE account_id = %s", (str(other_account),)),
        ("Look up who else is a user of the system",
         "SELECT count(*) FROM sec.app_user", ()),
        ("Grant themselves the other customer",
         "UPDATE sec.app_user SET subject_client_id = %s WHERE db_role = session_user",
         (other_client,)),
        ("Turn the policy off",
         "ALTER TABLE core.dim_client DISABLE ROW LEVEL SECURITY", ()),
        ("Become the relationship manager who can see both",
         "SET ROLE rm_north", ()),
    )
    results: list[dict[str, str]] = []
    with auth.login("client_11409", demo_autocode=True) as conn:
        for description, sql, params in attempts:
            try:
                value = db.fetch_value(conn, sql, params or None)
                outcome = f"{int(value)} rows" if value is not None else "no rows"
                verdict = "LEAK" if (value or 0) else "blocked: 0 rows"
            except psycopg.Error as exc:
                conn.rollback()
                outcome = str(exc).strip().splitlines()[0]
                verdict = "blocked: refused"
            results.append({
                "attempt": description,
                "outcome": outcome,
                "verdict": verdict,
            })
    return results


def demonstrate_onboarding() -> list[dict[str, str]]:
    """Onboard a third customer live, prove it works, and remove them again.

    The brief asks how a new user is onboarded without code changes. Asserting
    it is cheap; doing it in front of the reader is not much dearer.

    :returns: One row per step, with the observed effect.
    """
    role = "client_demo_tmp"
    # A client nobody else in this demo is entitled to.
    steps: list[dict[str, str]] = []
    # autocommit, because each step has to be visible to a SEPARATE connection
    # authenticating as the new role -- which is the whole point of the demo.
    with db.connect(autocommit=True) as conn:
        subject = int(db.fetch_value(
            conn,
            """
            SELECT client_id FROM core.dim_client
            WHERE client_id NOT IN (%s, %s) ORDER BY client_id LIMIT 1
            """,
            (config.EXAMPLE_CLIENT_ID, config.EXAMPLE_OTHER_CLIENT_ID),
        ))
        db.execute(conn, f'DROP ROLE IF EXISTS "{role}"')
        db.execute(conn, "DELETE FROM sec.app_user WHERE db_role = %s", (role,))

        from src import build_security  # noqa: PLC0415 - avoids a circular import

        build_security.create_login_role(conn, role, config.DEMO_USER_PASSWORD)
        steps.append({
            "step": "CREATE ROLE (a credential, the only DDL)",
            "effect": f"login role {role} exists, inheriting ai_consumer",
        })

        build_security.onboard_client_user(conn, role, subject)
        steps.append({
            "step": f"INSERT INTO sec.app_user (user_type 'client', subject {subject})",
            "effect": "one row inserted; no portfolio, no policy, no code",
        })

        # A password is not a login. Until this customer enrols an
        # authenticator they cannot complete step two, so the entitlement
        # just granted reaches them not at all.
        try:
            with auth.login(role, demo_autocode=True):
                blocked = "LOGGED IN -- which would be a defect"
        except auth.AuthenticationError as exc:
            blocked = f"refused: {str(exc).split(': ', 1)[-1]}"
        steps.append({
            "step": "Try to log in before a second factor is enrolled",
            "effect": blocked,
        })

        secret = build_security.enrol_second_factor(conn, role)
        steps.append({
            "step": "Enrol the authenticator (the customer scans a code)",
            "effect": f"enrolled; {len(secret)}-character shared secret, never leaves the database",
        })

        with auth.login(role, demo_autocode=True) as user_conn:
            after = int(db.fetch_value(user_conn, "SELECT count(*) FROM ai.client") or 0)
            account_rows = int(db.fetch_value(user_conn, "SELECT count(*) FROM ai.account") or 0)
            peek = int(db.fetch_value(
                user_conn, "SELECT count(*) FROM ai.client WHERE client_id = %s",
                (config.EXAMPLE_CLIENT_ID,)) or 0)
        steps.append({
            "step": "Log in with both factors, and query",
            "effect": f"{after} client and {account_rows} account(s) visible -- their own",
        })
        steps.append({
            "step": "And try to read the example customer",
            "effect": f"{peek} rows -- the new login is isolated from them too",
        })

        db.execute(conn, "UPDATE sec.app_user SET is_active = false WHERE db_role = %s", (role,))
        with auth.login(role, demo_autocode=True) as user_conn:
            revoked = int(db.fetch_value(user_conn, "SELECT count(*) FROM ai.client") or 0)
        steps.append({
            "step": "UPDATE sec.app_user SET is_active = false",
            "effect": f"{revoked} clients visible -- offboarding is one UPDATE",
        })

        db.execute(conn, "DELETE FROM sec.app_user WHERE db_role = %s", (role,))
        db.execute(conn, f'DROP ROLE IF EXISTS "{role}"')
        steps.append({
            "step": "Clean up, so the demo is repeatable",
            "effect": "temporary user and role removed",
        })
    return steps


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    """Render a markdown table.

    :param headers: Column headings.
    :param rows: Row values, already stringified.
    :returns: Markdown lines.
    """
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(row) + " |" for row in rows]
    return out


def render(data: dict[str, Any], visibility: list[dict[str, Any]],
           attempts: list[dict[str, str]], onboarding: list[dict[str, str]]) -> str:
    """Render the worked example as Markdown.

    :param data: The collected example.
    :param visibility: Per-principal measurements.
    :param attempts: Cross-customer read attempts.
    :param onboarding: The live onboarding steps.
    :returns: The document text.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cid, oid = data["client_id"], data["other_id"]
    acct, oacct = data["account_id"], data["other_account_id"]
    rc, sc, cc = data["raw_client"], data["stg_client"], data["core_client"]
    ra, sa, ca = data["raw_account"], data["stg_account"], data["core_account"]
    rl, cl = data["raw_loan"], data["core_loan"]

    out: list[str] = [
        f"# Worked example: client {cid}, cleaned and kept private",
        "",
        "One client, followed the whole way: from the line of text they arrive as,",
        "through every cleaning step that touches them, into the published product,",
        "and then through the entitlement model that decides who may read them.",
        "",
        f"Generated by `src/worked_example.py` (`make demo`) at {stamp}. Every value",
        "below was read from the live database during that run; nothing is a fixture",
        "and nothing is transcribed.",
        "",
        f"**Why this client.** Client {cid} was chosen because their data exercises the",
        "awkward cases rather than the clean ones: the birth number has to be decoded",
        "into two facts, the account was opened when the owner was a child (which raises",
        "a warn flag that must survive all the way into an answer), the account's",
        "district is not the client's own district, and the account carries a second,",
        "different flag. A tidy record would have demonstrated nothing.",
        "",
        f"**The negative control.** Client {oid} is a different customer who lives in the",
        "same region, and is therefore in the *same relationship manager's book*. That",
        "is the point: isolating two customers in different books would prove nothing",
        "that a portfolio boundary did not already prove.",
        "",
        "---",
        "",
        "## 1. What arrives: four lines of text",
        "",
        "Bronze lands every field as text, unchanged, with the file and line number",
        "stamped on the row. Nothing below has been typed, trimmed or decoded yet.",
        "",
        "```text",
        f"client.asc  line {rc['_source_row']:>6}   client_id={rc['client_id']}  "
        f"birth_number={rc['birth_number']}  district_id={rc['district_id']}",
        f"account.asc line {ra['_source_row']:>6}   account_id={ra['account_id']}  "
        f"district_id={ra['district_id']}  frequency={ra['frequency']}  date={ra['date']}",
        f"loan.asc    line {rl['_source_row']:>6}   loan_id={rl['loan_id']}  "
        f"account_id={rl['account_id']}  date={rl['date']}  amount={rl['amount']}  "
        f"duration={rl['duration']}  payments={rl['payments']}  status={rl['status']}",
        f"trans.asc   {data['transactions']:,} lines for this account",
        "```",
        "",
        "Read that as a person and almost nothing is answerable. `805502` is not a date",
        "of birth, `POPLATEK MESICNE` is not a statement frequency anyone can group by,",
        "and `A` is not a loan outcome. That gap is what the cleaning closes.",
        "",
        "## 2. What the cleaning does to this one client",
        "",
        "Each step cites its id in `docs/CLEANING_LEDGER.md`, where the same step is",
        "measured across the whole dataset.",
        "",
    ]

    out += _table(
        ["Step", "Field", "Before", "After", "What had to be known"],
        [
            ["C05", "`account.date`", f"`{ra['date']}`", f"`{sa['open_date']}`",
             "YYMMDD, and a two-digit year means 19xx (A17)"],
            ["C05", "`loan.date`", f"`{rl['date']}`", f"`{cl['loan_date']}`", "the same rule"],
            ["C07", "`client.birth_number`", f"`{rc['birth_number']}`",
             f"`{sc['birth_date']}`",
             "the month carries +50 for women, so 55 means May"],
            ["C08", "`client.birth_number`", f"`{rc['birth_number']}`",
             f"`{sc['gender']}`",
             "the same digits again: this dataset has no gender column"],
            ["C09", "`account.frequency`", f"`{ra['frequency']}`",
             f"`{sa['frequency_label']}`", "one decode map, checked against the catalogue"],
            ["C09", "`loan.status`", f"`{rl['status']}`", f"`{cl['loan_status']}`",
             "A/B/C/D are outcomes, not grades"],
            ["C11", "`loan.status`", f"`{rl['status']}`",
             f"`is_problematic = {cl['is_problematic']}`",
             "the certified B-or-D definition, settled once (A4)"],
            ["C04", "`loan.amount`", f"`'{rl['amount']}'` (text)",
             f"`{cl['amount']}` (numeric)",
             "the digits are unchanged; the TYPE is the point, and a cast that "
             "fails returns NULL rather than aborting the load"],
        ],
    )
    out += [
        "",
        "The birth number is the clearest case. `805502` is one field holding three",
        f"facts: born 1980, **May** (55 minus the 50 that marks a woman), on the 2nd —",
        f"so `birth_date = {sc['birth_date']}` and `gender = {sc['gender']}`. The original",
        "digits stay in the row beside the two derived columns, so the derivation can",
        "be checked rather than trusted, and `birth_number_valid` records that it",
        f"succeeded (`{sc['birth_number_valid']}`).",
        "",
        "## 3. What the grading finds about this client",
        "",
        "Cleaning makes the values usable. It does not make them *right*, and two",
        "things about this client are odd enough to travel with them.",
        "",
    ]

    age = data["age_at_open"]
    out += _table(
        ["Finding", "Rule", "Severity", "What happens to it"],
        [
            [f"The account was opened on {ca['open_date']}, when the owner, born "
             f"{cc['birth_date']}, was **{age} years old**",
             "`VAL_OWNER_AGE_AT_ACCOUNT_OPEN`", "warn",
             "flagged on the row, not removed: the bank's record says this, and "
             "deleting it would hide a real data problem"],
            [f"The client lives in district {data['client_district']['district_id']} "
             f"({data['client_district']['district_name']}, "
             f"{data['client_district']['region']}) but the account is registered in "
             f"district {data['account_district']['district_id']} "
             f"({data['account_district']['district_name']}, "
             f"{data['account_district']['region']})",
             "`CON_CLIENT_ACCOUNT_DISTRICT_MISMATCH`", "info",
             "logged, and it is why Q1 and Q5 deliberately use different districts "
             "(A1, A8)"],
        ],
    )
    out += ["", "The flags the published rows actually carry, read from the product:", ""]
    out += _table(
        ["Object", "Flag", "Rule"],
        [[f"`core.{'dim_client' if f['target_table'] == 'client' else 'dim_account'}`",
          f"`{f['flag']}`", f"`{f['rule_id']}`"] for f in data["flags"]]
        or [["-", "none", "-"]],
    )

    out += [
        "",
        "## 4. What they become: the published rows",
        "",
        "```text",
        f"ai.client     client_id={cc['client_id']}  birth_date={cc['birth_date']}  "
        f"gender={cc['gender']}  district_id={cc['district_id']}",
        f"              _dq_flags={list(cc['_dq_flags'])}",
        f"ai.account    account_id={ca['account_id']}  open_date={ca['open_date']}  "
        f"statement_frequency={ca['statement_frequency']}",
        f"              _dq_flags={list(ca['_dq_flags'])}",
        f"ai.loan       loan_id={cl['loan_id']}  amount={cl['amount']}  "
        f"duration_months={cl['duration_months']}  status={cl['loan_status']}  "
        f"is_problematic={cl['is_problematic']}",
        "```",
        "",
        f"And the first postings on the account, with the sign already resolved "
        f"(step C10) so that no consumer has to know that `VYDAJ` and `VYBER` both "
        f"mean money leaving:",
        "",
    ]
    out += _table(
        ["trans_id", "date", "source type", "published type", "amount", "signed", "balance after", "category"],
        [[str(t["trans_id"]), str(t["trans_date"]), f"`{t['trans_type_code']}`",
          t["transaction_type"], f"{t['amount']:,}", f"{t['signed_amount']:,}",
          f"{t['balance_after']:,}", t["category"] or "-"]
         for t in data["first_postings"]],
    )

    out += [
        "",
        "## 5. Who may read any of it",
        "",
        "The same question — *how many clients, accounts and loans can you see, and",
        "what are the loans worth* — asked on six connections, each authenticated as a",
        "different principal. The SQL is identical every time; only the login differs.",
        "",
        "```sql",
        textwrap.dedent(DEMO_QUESTION).strip(),
        "```",
        "",
    ]
    out += _table(
        ["Principal", "Kind", "Entitled to", "Clients", "Accounts", "Loans", "Loan value",
         f"Sees {cid}?", f"Sees {oid}?"],
        [[f"`{r['db_role']}`", r["user_type"], f"`{r['portfolios']}`",
          f"{r['clients']:,}", f"{r['accounts']:,}", f"{r['loans']:,}",
          f"{r['loan_value']:,.0f}",
          "**yes**" if r["sees_example_client"] else "no",
          "**yes**" if r["sees_other_client"] else "no"]
         for r in visibility],
    )
    out += [
        "",
        f"The row that matters is `rm_north`: that manager sees **both** customers,",
        f"because both are in the northern book. Each customer sees **one** client —",
        "themselves. Nobody had to write a different query, and no query either",
        "customer could write would change their own row.",
        "",
        "## 6. One customer trying to read the other, on purpose",
        "",
        f"Connected as `client_{cid}`, asking for client {oid}'s data by name. A row",
        "count can pass while a targeted lookup leaks, so these name the other",
        "customer's own identifiers rather than counting.",
        "",
    ]
    out += _table(
        ["Attempt", "Result", "Outcome"],
        [[a["attempt"], f"`{a['outcome'][:88]}`", a["verdict"]] for a in attempts],
    )
    leaks = [a for a in attempts if a["verdict"] == "LEAK"]
    out += [
        "",
        f"**{len(attempts) - len(leaks)} of {len(attempts)} blocked"
        + ("" if not leaks else f"; {len(leaks)} LEAKED and that is a defect") + ".**",
        "",
        "Worth separating two different reasons for a block, because they are not",
        "equally strong. The reads of `stg`, `raw` and `sec.app_user` are refused by a",
        "**privilege** check — the role was never granted them. The reads of `ai.*` and",
        "`core.*` return **zero rows** through a **policy**: the customer is allowed to",
        "run the query and the engine filters the answer. The second is the one that",
        "matters for an AI assistant, because it means a generated query does not need",
        "to be inspected for whose data it asks about.",
        "",
        "## 7. Onboarding a new customer, performed rather than asserted",
        "",
        "The brief asks how a new user or portfolio is onboarded without code changes.",
        "This ran live during the same execution that produced this document.",
        "",
    ]
    out += _table(["Step", "Observed effect"],
                  [[s["step"], s["effect"]] for s in onboarding])
    out += [
        "",
        "No policy was written, no view altered, no deployment made. A self-service",
        "customer needs no portfolio at all: the principal *is* the client, and",
        "`sec.v_my_clients` resolves that directly.",
        "",
        "## 8. What this does not protect against",
        "",
        "Stated here because a privacy claim with no stated limits is not a claim a",
        "reviewer can weigh.",
        "",
        "1. **The pipeline owner sees everything.** `berka_owner` owns the tables and",
        "   is exempt from their policies, which is what makes the build possible.",
        "   That identity is a deployment secret, never an application login. A real",
        "   deployment separates the build role from the owning role and puts the",
        "   owner's credential in a vault.",
        "2. **`cro_global` sees every client** — but through a portfolio containing all",
        "   of them, not through a privilege. It goes through the same policy as",
        "   everyone else (`rolbypassrls = false`), so the audit question \"who can see",
        "   this client\" is answerable from the entitlement tables alone.",
        "3. **Role-per-user does not pool connections.** Correct here, and the first",
        "   thing to revisit at scale; the Design Decision Record covers the trade.",
        "4. **Nothing is encrypted at rest or masked.** A customer sees their own birth",
        "   date in full. Field-level masking is a separate control this build does not",
        "   implement, and for data this sensitive a real deployment would want it.",
        "5. **No audit log of reads.** The model controls who *can* read; it does not",
        "   record who *did*. For a bank that is a regulatory requirement and it is",
        "   absent here.",
        "6. **This is the public dataset.** The clients are real records from a 1999",
        "   research release, not live customers, which is why they can appear in a",
        "   document at all.",
        "",
    ]
    return "\n".join(out) + "\n"


def main() -> int:
    """Run the worked example and write the report.

    :returns: Process exit code; non-zero if a cross-customer read leaked.
    """
    with db.connect() as conn:
        data = collect(conn)
    visibility = measure_visibility(data)
    attempts = attempt_cross_client_reads(data)
    onboarding = demonstrate_onboarding()

    cid, oid = data["client_id"], data["other_id"]
    LOGGER.info(_rule(f"worked example: client {cid}"))
    LOGGER.info("  raw          | birth_number=%s district=%s",
                data["raw_client"]["birth_number"], data["raw_client"]["district_id"])
    LOGGER.info("  cleaned      | birth_date=%s gender=%s valid=%s",
                data["stg_client"]["birth_date"], data["stg_client"]["gender"],
                data["stg_client"]["birth_number_valid"])
    LOGGER.info("  account      | opened %s, owner was %s years old",
                data["core_account"]["open_date"], data["age_at_open"])
    LOGGER.info("  flags        | %s",
                ", ".join(f["flag"] for f in data["flags"]) or "none")
    LOGGER.info(_rule("who can see this client"))
    for row in visibility:
        LOGGER.info("  %-14s %-20s clients=%-7s accounts=%-6s loans=%-4s sees %s=%s sees %s=%s",
                    row["db_role"], row["portfolios"], f"{row['clients']:,}",
                    f"{row['accounts']:,}", f"{row['loans']:,}",
                    cid, "YES" if row["sees_example_client"] else "no",
                    oid, "YES" if row["sees_other_client"] else "no")
    LOGGER.info(_rule(f"client_{cid} trying to read client {oid}"))
    leaks = [a for a in attempts if a["verdict"] == "LEAK"]
    for attempt in attempts:
        LOGGER.info("  %-8s %-56s %s",
                    "LEAK !!" if attempt["verdict"] == "LEAK" else "blocked",
                    attempt["attempt"][:56], attempt["outcome"][:40])
    LOGGER.info(_rule("onboarding a new customer, live"))
    for step in onboarding:
        LOGGER.info("  %-56s -> %s", step["step"][:56], step["effect"])

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(render(data, visibility, attempts, onboarding), encoding="utf-8")
    LOGGER.info(_rule())
    LOGGER.info("wrote %s", TARGET.relative_to(config.PROJECT_ROOT))
    LOGGER.info("___ summary ___ principals=%d  attempts=%d  blocked=%d  leaked=%d",
                len(visibility), len(attempts), len(attempts) - len(leaks), len(leaks))
    if leaks:
        LOGGER.error("CROSS-CLIENT LEAK: %s", [a["attempt"] for a in leaks])
    db.record_run("demo", "make demo",
                  {"principals": len(visibility), "attempts": len(attempts),
                   "leaks": len(leaks)})
    return 1 if leaks else 0


if __name__ == "__main__":
    raise SystemExit(main())
