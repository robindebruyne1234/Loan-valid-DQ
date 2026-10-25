"""Build the ``core`` star schema and verify it.

Three jobs, in order:

1. Publish ``core.ref_codes`` from the decode maps in :mod:`src.config`, so
   that the code-to-business-label mapping has exactly one source. The SQL in
   ``30_core.sql`` joins this table for every label, and the semantic layer
   renders its allowed-value lists from the same place, so SQL and the LLM
   context cannot drift apart.
2. Run ``sql/30_core.sql``.
3. Verify the result: primary keys unique, foreign keys resolvable, declared
   grains actually one-row-per-key, and ``core = stg - quarantine`` on both row
   counts and amount sums. A failure here stops the pipeline, because every
   number in the deliverables is built on this layer.

Run with ``make model``.
"""

from __future__ import annotations

import uuid
from typing import Any

import psycopg

from src import config, db

LOGGER = db.setup_logging("model")

#: Code sets published to ``core.ref_codes``. The name is what the semantic
#: layer and the SQL both refer to; the mapping comes from :mod:`src.config`.
CODE_SETS: dict[str, tuple[dict[str, str], str]] = {
    "statement_frequency": (
        config.FREQUENCY_CODES,
        "How often the bank issues an account statement.",
    ),
    "loan_status": (
        config.LOAN_STATUS_CODES,
        "Loan repayment status. B and D together are the certified definition "
        "of a problematic loan.",
    ),
    "card_type": (
        config.CARD_TYPE_CODES,
        "Payment card product tier.",
    ),
    "disposition_type": (
        config.DISP_TYPE_CODES,
        "Capacity in which a client may operate an account. OWNER is the legal "
        "account holder; DISPONENT may transact but does not own the account.",
    ),
    "transaction_type": (
        config.TRANS_TYPE_CODES,
        "Direction of a posting. PRIJEM increases the balance; VYDAJ and VYBER "
        "decrease it.",
    ),
    "transaction_operation": (
        config.TRANS_OPERATION_CODES,
        "Mode of the posting. NULL for bank-generated interest postings, by "
        "design, and not a missing value.",
    ),
    "transaction_category": (
        config.K_SYMBOL_CODES,
        "What the posting or standing order was for (the source k_symbol "
        "column, which both tables carry). LEASING occurs only on standing "
        "orders; what each published entity can actually contain is narrower "
        "and is stated per entity in the semantic layer.",
    ),
}

#: Foreign keys verified after the build: (child table, column, parent table,
#: parent column). Declared here rather than as database constraints because
#: core is rebuilt by CREATE TABLE AS on every run; the check is the same.
FOREIGN_KEYS: tuple[tuple[str, str, str, str], ...] = (
    ("dim_client", "district_id", "dim_district", "district_id"),
    ("dim_account", "district_id", "dim_district", "district_id"),
    ("bridge_disposition", "client_id", "dim_client", "client_id"),
    ("bridge_disposition", "account_id", "dim_account", "account_id"),
    ("dim_card", "disp_id", "bridge_disposition", "disp_id"),
    ("fact_loan", "account_id", "dim_account", "account_id"),
    ("fact_transaction", "account_id", "dim_account", "account_id"),
    ("fact_account_month_end_balance", "account_id", "dim_account", "account_id"),
)

#: Primary keys verified after the build.
PRIMARY_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("dim_date", ("date_key",)),
    ("dim_district", ("district_id",)),
    ("dim_client", ("client_id",)),
    ("dim_account", ("account_id",)),
    ("bridge_disposition", ("disp_id",)),
    ("dim_card", ("card_id",)),
    ("fact_loan", ("loan_id",)),
    ("fact_transaction", ("trans_id",)),
    ("fact_account_month_end_balance", ("account_id", "month_end_date")),
)

#: Row-count reconciliation: core table -> staging table it is built from.
CORE_TO_STG: dict[str, str] = {
    "dim_district": "district",
    "dim_client": "client",
    "dim_account": "account",
    "bridge_disposition": "disp",
    "dim_card": "card",
    "fact_loan": "loan",
    "fact_transaction": "trans",
}


def build_ref_codes(conn: psycopg.Connection) -> int:
    """Create and populate ``core.ref_codes`` from the config decode maps.

    :param conn: Open connection.
    :returns: Number of code rows published.
    """
    db.execute(conn, "DROP TABLE IF EXISTS core.ref_codes CASCADE")
    db.execute(
        conn,
        """
        CREATE TABLE core.ref_codes (
            code_set      text NOT NULL,
            code          text NOT NULL,
            label         text NOT NULL,
            code_set_note text NOT NULL,
            PRIMARY KEY (code_set, code)
        )
        """,
    )
    db.execute(
        conn,
        """
        COMMENT ON TABLE core.ref_codes IS
            'The one published mapping from source codes to business labels. '
            'Generated from src/config.py by src/build_model.py; joined by '
            '30_core.sql and rendered into semantic/semantic_layer.yaml, so '
            'the SQL and the LLM context can never disagree.'
        """,
    )
    rows = [
        (code_set, code, label, note)
        for code_set, (mapping, note) in CODE_SETS.items()
        for code, label in mapping.items()
    ]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO core.ref_codes (code_set, code, label, code_set_note) "
            "VALUES (%s, %s, %s, %s)",
            rows,
        )
    LOGGER.info("published core.ref_codes -> %d codes in %d code sets",
                len(rows), len(CODE_SETS))
    return len(rows)


def check_codes_against_staging(conn: psycopg.Connection) -> list[str]:
    """Check that every code present in staging is published in ``ref_codes``.

    The staging layer also carries human-readable labels, produced inline while
    casting. That is deliberate redundancy, so it is verified rather than
    trusted: if a label in staging disagrees with ``core.ref_codes``, or a code
    appears in the data that the catalogue does not know, the build fails here
    instead of shipping two different answers to the same question.

    :param conn: Open connection.
    :returns: List of human-readable problems; empty when everything agrees.
    """
    checks: tuple[tuple[str, str, str, str | None], ...] = (
        ("statement_frequency", "stg.account", "frequency_code", "frequency_label"),
        ("loan_status", "stg.loan", "status_code", "status_label"),
        ("card_type", "stg.card", "card_type", None),
        ("disposition_type", "stg.disp", "disp_type_code", "disp_type_label"),
        ("transaction_type", "stg.trans", "trans_type_code", "trans_type_label"),
        ("transaction_operation", "stg.trans", "operation_code", "operation_label"),
        ("transaction_category", "stg.trans", "k_symbol_code", "k_symbol_label"),
        # The k_symbol column appears on standing orders too. Leaving this
        # table out is how LEASING reached the product undecoded on 341 rows:
        # the profiler reported the code, but nothing checked it against the
        # catalogue, so no build ever failed. See DECISIONS.md D017.
        ("transaction_category", 'stg."order"', "k_symbol_code", "k_symbol_label"),
    )
    problems: list[str] = []
    for code_set, table, code_column, label_column in checks:
        unknown = db.fetch_all(
            conn,
            f"""
            SELECT DISTINCT s."{code_column}" AS code
            FROM {table} s
            WHERE s."{code_column}" IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM core.ref_codes r
                  WHERE r.code_set = %s AND r.code = s."{code_column}"
              )
            """,
            (code_set,),
        )
        for row in unknown:
            problems.append(
                f"{table}.{code_column} contains '{row['code']}' "
                f"which is not published in ref_codes code_set '{code_set}'"
            )
        if label_column:
            mismatched = db.fetch_all(
                conn,
                f"""
                SELECT DISTINCT s."{code_column}" AS code,
                       s."{label_column}" AS stg_label, r.label AS ref_label
                FROM {table} s
                JOIN core.ref_codes r
                  ON r.code_set = %s AND r.code = s."{code_column}"
                WHERE s."{label_column}" IS DISTINCT FROM r.label
                """,
                (code_set,),
            )
            for row in mismatched:
                problems.append(
                    f"{table}: code '{row['code']}' is labelled "
                    f"'{row['stg_label']}' in staging but '{row['ref_label']}' "
                    f"in ref_codes"
                )
    if problems:
        for problem in problems:
            LOGGER.error("code catalogue mismatch -> %s", problem)
    else:
        LOGGER.info("code catalogue agrees with staging on all %d code sets", len(checks))
    return problems


def check_primary_keys(conn: psycopg.Connection) -> list[str]:
    """Verify that every declared primary key is unique and complete.

    :param conn: Open connection.
    :returns: List of problems; empty when all keys hold.
    """
    problems: list[str] = []
    for table, columns in PRIMARY_KEYS:
        column_list = ", ".join(f'"{c}"' for c in columns)
        duplicates = db.fetch_value(
            conn,
            f"""
            SELECT count(*) FROM (
                SELECT {column_list} FROM core."{table}"
                GROUP BY {column_list} HAVING count(*) > 1
            ) d
            """,
        )
        nulls = db.fetch_value(
            conn,
            f'SELECT count(*) FROM core."{table}" WHERE '
            + " OR ".join(f'"{c}" IS NULL' for c in columns),
        )
        if duplicates:
            problems.append(f"core.{table}: {duplicates} duplicate key values")
        if nulls:
            problems.append(f"core.{table}: {nulls} rows with a NULL key column")
    if not problems:
        LOGGER.info("primary keys ok -> %d tables, unique and non-null", len(PRIMARY_KEYS))
    return problems


def check_foreign_keys(conn: psycopg.Connection) -> list[str]:
    """Verify that every declared foreign key resolves.

    :param conn: Open connection.
    :returns: List of problems; empty when all keys resolve.
    """
    problems: list[str] = []
    for child, column, parent, parent_column in FOREIGN_KEYS:
        orphans = db.fetch_value(
            conn,
            f"""
            SELECT count(*) FROM core."{child}" c
            LEFT JOIN core."{parent}" p ON p."{parent_column}" = c."{column}"
            WHERE c."{column}" IS NOT NULL AND p."{parent_column}" IS NULL
            """,
        )
        if orphans:
            problems.append(
                f"core.{child}.{column} -> core.{parent}: {orphans} orphan rows"
            )
    if not problems:
        LOGGER.info("foreign keys ok -> %d relationships, no orphans", len(FOREIGN_KEYS))
    return problems


def check_grains(conn: psycopg.Connection) -> list[str]:
    """Verify the grains the semantic layer promises the LLM.

    The most important one is ``v_account_owner``: the semantic layer tells the
    model it is one row per account, and a question like Q9 is only correct if
    that is true. An unchecked promise in a semantic layer is how an AI
    assistant ends up double counting.

    :param conn: Open connection.
    :returns: List of problems; empty when every grain holds.
    """
    problems: list[str] = []
    accounts = db.table_count(conn, config.SCHEMA_CORE, "dim_account")
    owner_rows = int(db.fetch_value(conn, "SELECT count(*) FROM core.v_account_owner") or 0)
    distinct_owner_accounts = int(
        db.fetch_value(conn, "SELECT count(DISTINCT account_id) FROM core.v_account_owner") or 0
    )
    if owner_rows != distinct_owner_accounts:
        problems.append(
            f"core.v_account_owner is not one row per account: "
            f"{owner_rows} rows for {distinct_owner_accounts} accounts"
        )
    if distinct_owner_accounts != accounts:
        problems.append(
            f"core.v_account_owner covers {distinct_owner_accounts} of "
            f"{accounts} accounts"
        )

    loans = db.table_count(conn, config.SCHEMA_CORE, "fact_loan")
    enriched = int(db.fetch_value(conn, "SELECT count(*) FROM core.v_loan_enriched") or 0)
    if loans != enriched:
        problems.append(
            f"core.v_loan_enriched is not one row per loan: {enriched} rows "
            f"for {loans} loans (a fan-out in the owner or card join)"
        )

    clients = db.table_count(conn, config.SCHEMA_CORE, "dim_client")
    regions = int(db.fetch_value(conn, "SELECT count(*) FROM core.v_client_region") or 0)
    if clients != regions:
        problems.append(
            f"core.v_client_region is not one row per client: {regions} rows "
            f"for {clients} clients"
        )
    if not problems:
        LOGGER.info("grains ok -> v_account_owner, v_loan_enriched, v_client_region "
                    "are one row per account / loan / client")
    return problems


def reconcile_core(conn: psycopg.Connection) -> tuple[list[dict[str, Any]], list[str]]:
    """Reconcile core against staging minus quarantine, on rows and on money.

    :param conn: Open connection.
    :returns: Tuple of (reconciliation rows, list of problems).
    """
    rows: list[dict[str, Any]] = []
    problems: list[str] = []

    for core_table, stg_table in CORE_TO_STG.items():
        stg_rows = db.table_count(conn, config.SCHEMA_STG, stg_table)
        core_rows = db.table_count(conn, config.SCHEMA_CORE, core_table)
        blocked = int(
            db.fetch_value(
                conn,
                "SELECT count(*) FROM dq.v_blocked WHERE target_table = %s",
                (stg_table,),
            )
            or 0
        )
        expected = stg_rows - blocked
        balanced = core_rows == expected
        rows.append(
            {
                "metric": "row_count",
                "entity": f"core.{core_table}",
                "stg_value": stg_rows,
                "quarantined": blocked,
                "core_value": core_rows,
                "delta": core_rows - expected,
                "is_balanced": balanced,
                "note": "core must equal stg minus quarantined rows",
            }
        )
        if not balanced:
            problems.append(
                f"core.{core_table}: {core_rows} rows, expected "
                f"{expected} = {stg_rows} staged - {blocked} quarantined"
            )

    for entity, core_table, stg_table, column in (
        ("trans.amount", "fact_transaction", "trans", "amount"),
        ("loan.amount", "fact_loan", "loan", "amount"),
    ):
        stg_sum = db.fetch_value(
            conn,
            f"""
            SELECT round(coalesce(sum(s."{column}"), 0), 2) FROM stg."{stg_table}" s
            WHERE NOT EXISTS (
                SELECT 1 FROM dq.v_blocked b
                WHERE b.target_table = %s AND b.business_key = s.{db.KEY_COLUMN_BY_TABLE[stg_table]}::text
            )
            """,
            (stg_table,),
        )
        core_sum = db.fetch_value(
            conn, f'SELECT round(coalesce(sum("{column}"), 0), 2) FROM core."{core_table}"'
        )
        balanced = stg_sum == core_sum
        rows.append(
            {
                "metric": "amount_sum",
                "entity": f"core.{core_table}.{column}",
                "stg_value": stg_sum,
                "quarantined": None,
                "core_value": core_sum,
                "delta": (core_sum - stg_sum) if None not in (core_sum, stg_sum) else None,
                "is_balanced": balanced,
                "note": "the money must survive the move from staging into core",
            }
        )
        if not balanced:
            problems.append(
                f"core.{core_table}.{column}: core sum {core_sum} != "
                f"staged-minus-quarantined sum {stg_sum}"
            )

    run_id = uuid.uuid4()
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                """
                INSERT INTO dq.reconciliation (
                    run_id, metric, entity, stg_value, quarantined, core_value,
                    delta, is_balanced, note
                ) VALUES (%(run_id)s, %(metric)s, %(entity)s, %(stg_value)s,
                          %(quarantined)s, %(core_value)s, %(delta)s,
                          %(is_balanced)s, %(note)s)
                """,
                {**row, "run_id": str(run_id)},
            )
    if not problems:
        LOGGER.info("core reconciliation ok -> %d checks balanced "
                    "(core == stg - quarantine, on rows and on money)", len(rows))
    return rows, problems



#: One row per published core object for the model explanation deliverable:
#: (object, kind, grain, key, why it exists in this shape).
MODEL_OBJECTS: tuple[tuple[str, str, str, str, str], ...] = (
    ("dim_date", "dimension", "one calendar day", "date_key",
     "Lets 'per month in 1996' (Q6) report all twelve months, including any "
     "month with no activity, instead of the query having to invent the gaps."),
    ("dim_district", "dimension", "one administrative district", "district_id",
     "Reference data shared by clients and accounts. Holds the region that Q1 "
     "groups by, so the region has exactly one definition."),
    ("dim_client", "dimension", "one client", "client_id",
     "The entitlement key: access is granted per client, so the client has to "
     "be a first-class object rather than an attribute of an account."),
    ("dim_account", "dimension", "one account", "account_id",
     "Carries the statement frequency (Q10) and the account's own district "
     "(Q5), which is not always the owner's district."),
    ("bridge_disposition", "bridge", "one client-account-capacity triple", "disp_id",
     "The client-to-account relationship is many-to-many, and the capacity "
     "(OWNER or DISPONENT) is the whole point: collapsing it into either side "
     "is what makes 'the account owner' ambiguous. Cards also hang off it."),
    ("dim_card", "dimension", "one issued card", "card_id",
     "A card belongs to a disposition, not to a client, so it reaches a person "
     "only through the bridge. Q4 and Q8 depend on that path being explicit."),
    ("fact_loan", "fact", "one loan", "loan_id",
     "Grain is the loan, not the account, so a second loan on one account is "
     "representable even though this dataset has none. is_problematic is the "
     "certified B-or-D definition used by Q3 and Q10."),
    ("fact_transaction", "fact", "one posting", "trans_id",
     "signed_amount is pre-computed (credits positive, debits negative) so no "
     "consumer re-derives the sign from a Czech type code - the single most "
     "likely place for generated SQL to go wrong."),
    ("fact_account_month_end_balance", "fact (derived)",
     "one account per month end", "account_id + month_end_date",
     "'The balance at the end of December 1998' (Q9) is a modelling decision, "
     "not a column: it needs a tie-break for intra-day order and a "
     "carry-forward for months with no posting. Both are decided here, once, "
     "and marked with is_carried_forward."),
    ("v_account_owner", "curated view", "one account", "account_id",
     "The only place that decides what 'the account owner' means. Four "
     "questions say the phrase; without this view each generated query would "
     "re-invent the join and some would pick a disponent."),
    ("v_loan_enriched", "curated view", "one loan", "loan_id",
     "Answers Q2, Q3, Q4, Q7 and Q10 with no further joins, including the "
     "owner's exact age at loan start."),
    ("v_client_region", "curated view", "one client", "client_id",
     "Answers Q1 from the client's OWN district, with the choice stated in the "
     "view comment rather than left to the query."),
)


def write_model_explanation(conn: psycopg.Connection) -> None:
    """Write ``deliverables/model_explanation.md`` with live row counts.

    The document feeds the "Model explanation" tab of the Excel deliverable. It
    is generated rather than hand-written so that the row counts and the grain
    statements in it are the ones the database actually has.

    :param conn: Open connection.
    :returns: ``None``.
    """
    counts: dict[str, int] = {}
    for name, kind, _, _, _ in MODEL_OBJECTS:
        if kind.startswith("curated"):
            counts[name] = int(db.fetch_value(conn, f"SELECT count(*) FROM core.{name}") or 0)
        else:
            counts[name] = db.table_count(conn, config.SCHEMA_CORE, name)

    lines = [
        "# Data model explanation",
        "",
        f"Generated by `make model` at {db.utc_now_iso()} (git {db.git_commit()}).",
        "Row counts below are read from the built database, not transcribed.",
        "",
        "## Shape: star schema with a bridge, plus curated views",
        "",
        "Seven source tables become four dimensions, one bridge, two base facts",
        "and one derived fact, with three curated views on top. The views are",
        "the surface the `ai` schema publishes, so an AI consumer never has to",
        "rediscover a join path that the business already has one answer for.",
        "",
        "```mermaid",
        "erDiagram",
        "    dim_district ||--o{ dim_client : \"lives in\"",
        "    dim_district ||--o{ dim_account : \"registered in\"",
        "    dim_client ||--o{ bridge_disposition : \"may operate\"",
        "    dim_account ||--o{ bridge_disposition : \"is operated via\"",
        "    bridge_disposition ||--o| dim_card : \"holds\"",
        "    dim_account ||--o{ fact_loan : \"carries\"",
        "    dim_account ||--o{ fact_transaction : \"is posted to\"",
        "    dim_account ||--o{ fact_account_month_end_balance : \"snapshot of\"",
        "    dim_date ||--o{ fact_transaction : \"posted on\"",
        "    dim_date ||--o{ fact_loan : \"granted on\"",
        "",
        "    dim_district {",
        "        int district_id PK",
        "        text district_name",
        "        text region",
        "        int inhabitants",
        "        numeric average_salary",
        "    }",
        "    dim_client {",
        "        int client_id PK",
        "        date birth_date",
        "        text gender",
        "        int district_id FK",
        "        bool birth_number_valid",
        "    }",
        "    dim_account {",
        "        int account_id PK",
        "        date open_date",
        "        text statement_frequency",
        "        int district_id FK",
        "    }",
        "    bridge_disposition {",
        "        int disp_id PK",
        "        int client_id FK",
        "        int account_id FK",
        "        bool is_owner",
        "    }",
        "    dim_card {",
        "        int card_id PK",
        "        int disp_id FK",
        "        text card_type",
        "        date issued_date",
        "    }",
        "    fact_loan {",
        "        int loan_id PK",
        "        int account_id FK",
        "        date loan_date",
        "        numeric amount",
        "        text loan_status",
        "        bool is_problematic",
        "    }",
        "    fact_transaction {",
        "        int trans_id PK",
        "        int account_id FK",
        "        date trans_date",
        "        numeric signed_amount",
        "        numeric balance_after",
        "        text direction",
        "    }",
        "    fact_account_month_end_balance {",
        "        int account_id FK",
        "        date month_end_date",
        "        numeric closing_balance",
        "        bool is_carried_forward",
        "    }",
        "    dim_date {",
        "        date date_key PK",
        "        int year",
        "        int month",
        "        bool is_month_end",
        "    }",
        "```",
        "",
        "## Grain, keys and why each object exists",
        "",
        "| object | kind | grain (one row per) | key | rows | why this shape |",
        "|---|---|---|---|---:|---|",
    ]
    for name, kind, grain, key, why in MODEL_OBJECTS:
        lines.append(
            f"| `core.{name}` | {kind} | {grain} | {key} | {counts[name]:,} | {why} |"
        )

    lines += [
        "",
        "## Join paths",
        "",
        "| from | to | path | note |",
        "|---|---|---|---|",
        "| account | its owner | `dim_account -> bridge_disposition (is_owner) -> dim_client` | "
        "Exactly one owner per account, enforced by block rule `UNQ_ACCOUNT_SINGLE_OWNER`. |",
        "| account | the owner's card | `... -> bridge_disposition (is_owner) -> dim_card` | "
        "A disponent's card must not be attributed to the owner; the join goes through the owner's disposition only. |",
        "| client | region | `dim_client -> dim_district.region` | "
        "The client's OWN district. Q1 uses this. |",
        "| account | region | `dim_account -> dim_district.region` | "
        "The district the account is registered in. Q5 uses this. The two differ for 9.1 percent of owners. |",
        "| loan | owner, card, frequency | `core.v_loan_enriched` | One row per loan, no fan-out. |",
        "| account | month-end balance | `core.fact_account_month_end_balance` | "
        "Pre-computed; carrying forward and tie-breaks are already decided. |",
        "",
        "## Which object answers which question",
        "",
        "| question | object | why |",
        "|---|---|---|",
        "| Q1 clients per region | `v_client_region` | Region of the client's own district. |",
        "| Q2 loan amount per year | `fact_loan` | `loan_year` is materialised, so no date function in the grouping. |",
        "| Q3 share of problematic loans | `fact_loan.is_problematic` | One certified definition (status B or D). |",
        "| Q4 average loan amount per owner's card type | `v_loan_enriched.owner_card_type` | "
        "Owner-only card join; loans whose owner holds no card fall in `no card`. |",
        "| Q5 top districts by incoming amount 1997 | `fact_transaction` + `dim_account` + `dim_district` | "
        "`direction = 'credit'` is the certified meaning of incoming. |",
        "| Q6 accounts opened per month 1996 | `dim_account` + `dim_date` | "
        "The date dimension supplies the empty months. |",
        "| Q7 average owner age at loan start per status | `v_loan_enriched.owner_age_at_loan_start` | "
        "Exact age from date of birth, computed once in the view. |",
        "| Q8 gender split of gold card owners | `v_account_owner` | "
        "Owner's own card only, so a disponent's gold card cannot leak in. |",
        "| Q9 average balance at end of December 1998 | `fact_account_month_end_balance` | "
        "Month-end grain with carry-forward already applied. |",
        "| Q10 problematic share per statement frequency | `v_loan_enriched.statement_frequency` | "
        "Frequency travels with the loan, so no extra join. |",
        "",
        "## Alternatives considered",
        "",
        "**One big table.** Flatten everything onto the transaction, which is",
        "the shape many text-to-SQL tools prefer because it removes joins. It",
        "was rejected for two reasons. First, the questions have four different",
        "grains (client, account, loan, posting), and a single table at posting",
        "grain makes every count of clients, accounts and loans a",
        "`count(distinct ...)` - which is exactly the construct an LLM gets",
        "wrong quietly. Second, entitlements: the filter belongs on the client,",
        "and in a flattened table the client column repeats 1.06 m times, so a",
        "row level security predicate has to be evaluated per posting instead",
        "of per client. The curated views give the same join-free experience to",
        "the model while keeping the grains honest.",
        "",
        "**Data Vault.** Hubs, links and satellites would model the",
        "client-account relationship and its history properly, and it is the",
        "right answer for a bank integrating many source systems. It was",
        "rejected here: there is one source, no history to track (the dataset",
        "is a single 1999 extract), and it would roughly triple the object",
        "count and add a presentation layer on top before a single question",
        "could be answered - the infrastructure-over-substance trap the brief",
        "warns about.",
        "",
        "**Keep the source model.** Query `stg` directly and skip `core`.",
        "Rejected because the source model encodes its business meaning in",
        "Czech codes and in a disposition table whose `type` column decides who",
        "the owner is. Every one of the 10 questions would then start by",
        "re-deriving that meaning, and each generated query would be free to",
        "re-derive it differently. The modelling work here is precisely the",
        "work of deciding those things once.",
        "",
        "**Surrogate keys.** Not used: the source keys are stable integers, and",
        "at this volume a surrogate layer would add a join per dimension",
        "without adding conformance. What changes at 100,000x is in the Design",
        "Decision Record.",
        "",
    ]
    config.MODEL_EXPLANATION_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("wrote %s", config.MODEL_EXPLANATION_MD.relative_to(config.PROJECT_ROOT))


def main() -> int:
    """Build and verify the core layer.

    :returns: Process exit code: ``0`` when every check passes, ``1`` otherwise.
    """
    with db.connect(autocommit=True) as conn:
        LOGGER.info("--- publishing the code catalogue ---")
        codes = build_ref_codes(conn)

        LOGGER.info("--- building the core star schema ---")
        duration = db.run_sql_file(conn, config.SQL_DIR / "30_core.sql", LOGGER)

        LOGGER.info("--- verifying the core layer ---")
        problems: list[str] = []
        problems += check_codes_against_staging(conn)
        problems += check_primary_keys(conn)
        problems += check_foreign_keys(conn)
        problems += check_grains(conn)
        recon, recon_problems = reconcile_core(conn)
        problems += recon_problems

        write_model_explanation(conn)

        counts = {
            table: db.table_count(conn, config.SCHEMA_CORE, table)
            for table, _ in PRIMARY_KEYS
        }

    LOGGER.info("___ core summary ___")
    for table, rows in counts.items():
        LOGGER.info("  core.%-32s %9d rows", table, rows)
    LOGGER.info("  ref_codes published: %d", codes)
    LOGGER.info("  build time: %.1fs", duration)

    if problems:
        LOGGER.error("core verification FAILED -> %d problems", len(problems))
        for problem in problems:
            LOGGER.error("  ! %s", problem)
    else:
        LOGGER.info("core verification passed -> keys, grains and reconciliation all hold")

    db.record_run(
        "model",
        "make model",
        {"row_counts": counts, "ref_codes": codes, "problems": problems,
         "reconciliation_checks": len(recon)},
    )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
