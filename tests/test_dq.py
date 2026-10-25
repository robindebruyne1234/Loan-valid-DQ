"""Prove that the data quality rules actually catch defects.

A rule set that has never fired is not a control. The public copy of the Berka
data is clean, so these tests build a deliberately corrupted copy of staging
(``sql/70_inject_defects.sql``, one seeded defect per rule family), run the
*identical* rule set against it, and assert that each seeded defect is caught
by the rule that is supposed to catch it.

The tests also assert the properties the rule file itself must have: a severity
and a justification on every rule, only known dimensions and severities, and no
rule that quarantines rows without declaring a handling.
"""

from __future__ import annotations

import pytest

from src import config, db, dq_runner, inject_defects


@pytest.fixture(scope="module")
def rule_document() -> dict:
    """Load the rule file once for the whole module.

    :returns: The parsed and validated rule document.
    """
    return dq_runner.load_rules()


@pytest.fixture(scope="module")
def injected_run() -> dict:
    """Build the corrupted copy and run every rule against it.

    :returns: Dictionary with the injected defect register and the per-rule
        violation counts from the run against schema ``inject``.
    """
    register = inject_defects.build()
    summary = dq_runner.run(dataset=config.SCHEMA_INJECT, write_deliverables=False)
    with db.connect() as conn:
        counts = {
            row["rule_id"]: row["violation_count"]
            for row in db.fetch_all(
                conn,
                "SELECT rule_id, violation_count FROM dq.results WHERE run_id = %s",
                (summary["run_id"],),
            )
        }
    return {"register": register, "counts": counts, "summary": summary}


# ---------------------------------------------------------------------------
# The rule file is itself a deliverable, so its shape is tested
# ---------------------------------------------------------------------------

def test_every_rule_declares_a_justified_severity(rule_document: dict) -> None:
    """Every rule must carry a severity and a non-trivial justification.

    The brief scores a rule without reasoning the same as no rule, so a thin
    rationale is treated as a test failure rather than a style issue.
    """
    for rule in rule_document["rules"]:
        assert rule["severity"] in config.VALID_SEVERITIES, rule["rule_id"]
        rationale = " ".join(rule["severity_rationale"].split())
        assert len(rationale) > 80, f"{rule['rule_id']}: rationale too thin"
        assert rule["handling"], rule["rule_id"]


def test_every_dimension_is_covered(rule_document: dict) -> None:
    """All six data quality dimensions must have at least one rule."""
    covered = {rule["dimension"] for rule in rule_document["rules"]}
    missing = set(config.VALID_DIMENSIONS) - covered
    assert not missing, f"dimensions with no rule: {sorted(missing)}"


def test_every_table_has_a_primary_key_rule(rule_document: dict) -> None:
    """Each of the eight source tables must have a uniqueness rule on its key."""
    uniqueness_tables = {
        rule["table"]
        for rule in rule_document["rules"]
        if rule["dimension"] == "uniqueness"
    }
    for table in dq_runner.KEY_COLUMNS:
        assert table in uniqueness_tables, f"no uniqueness rule for {table}"


def test_block_rules_affect_a_question_or_say_why_not(rule_document: dict) -> None:
    """A block rule with no affected question must justify blocking anyway.

    Blocking removes data, so the rule has to be able to defend itself even
    when no current metric depends on the column.
    """
    for rule in rule_document["rules"]:
        if rule["severity"] != config.SEVERITY_BLOCK or rule["affects_questions"]:
            continue
        rationale = rule["severity_rationale"].lower()
        assert any(
            phrase in rationale
            for phrase in ("no current", "no certified", "uniformly", "product")
        ), f"{rule['rule_id']}: blocks rows but neither affects a question nor explains why"


# ---------------------------------------------------------------------------
# Seeded defect detection, one assertion per rule family
# ---------------------------------------------------------------------------

def test_injection_register_covers_every_dimension(injected_run: dict) -> None:
    """The seeded defects must span all six dimensions."""
    covered = {row["dimension"] for row in injected_run["register"]}
    missing = set(config.VALID_DIMENSIONS) - covered
    assert not missing, f"no seeded defect for dimensions: {sorted(missing)}"


@pytest.mark.parametrize("defect_no", range(1, 21))
def test_seeded_defect_is_detected(injected_run: dict, defect_no: int) -> None:
    """Each seeded defect is caught by the rule that is supposed to catch it.

    :param injected_run: The corrupted-copy run fixture.
    :param defect_no: Number of the seeded defect in
        ``inject.injected_defect``.
    """
    register = {row["defect_no"]: row for row in injected_run["register"]}
    defect = register[defect_no]
    rule_id = defect["expected_rule_id"]
    counts = injected_run["counts"]

    assert rule_id in counts, f"rule {rule_id} did not execute"
    assert counts[rule_id] > 0, (
        f"defect {defect_no} ({defect['description']}) was injected into "
        f"{defect['target_table']} but rule {rule_id} reported no violation"
    )


def test_clean_copy_has_no_block_violations_beyond_the_known_duplicate() -> None:
    """On the real data, exactly one block rule fires, and it is the known one.

    This pins the baseline: if a future change makes a block rule fire on the
    untouched public copy, the test fails and the change has to be explained.
    """
    summary = dq_runner.run(dataset=config.SCHEMA_STG, write_deliverables=False)
    with db.connect() as conn:
        firing = db.fetch_all(
            conn,
            """
            SELECT rule_id, violation_count FROM dq.results
            WHERE run_id = %s AND severity = %s AND violation_count > 0
            ORDER BY rule_id
            """,
            (summary["run_id"], config.SEVERITY_BLOCK),
        )
    assert [row["rule_id"] for row in firing] == ["UNQ_TRANS_BUSINESS_KEY"], firing
    assert firing[0]["violation_count"] == 1


def test_quarantine_is_populated_and_traceable() -> None:
    """Every quarantined row names the rule and the reason that rejected it."""
    with db.connect() as conn:
        rows = db.fetch_all(
            conn,
            """
            SELECT rule_id, severity, target_table, business_key, reason, row_snapshot
            FROM dq.quarantine
            WHERE target_schema = %s
            ORDER BY quarantine_id DESC LIMIT 20
            """,
            (config.SCHEMA_STG,),
        )
    assert rows, "nothing in quarantine: the block path has never been exercised"
    for row in rows:
        assert row["severity"] == config.SEVERITY_BLOCK
        assert row["rule_id"] and row["reason"] and row["business_key"]
        assert row["row_snapshot"] is not None, (
            f"{row['rule_id']} quarantined {row['business_key']} without a snapshot"
        )


def test_every_warn_flag_lands_on_a_real_row() -> None:
    """A warn flag whose key does not resolve is a flag that reaches nobody.

    This is the structural version of a bug this project actually shipped: the
    balance reconciliation rules report a defect in the transaction data but
    identify it by ``account_id``, and were recorded against the ``trans``
    table. ``core.fact_transaction`` joins flags on ``trans_id``, so all 319
    account-level flags silently landed nowhere -- Q9 reported zero
    unreconciled accounts while 55 existed. The fix is the rules'
    ``flag_target_table``; this test is what stops it coming back.
    """
    with db.connect() as conn:
        unresolved = db.fetch_all(
            conn,
            """
            SELECT f.target_table, f.rule_id, count(*) AS flags
            FROM dq.flags f
            WHERE f.target_schema = 'stg'
              AND NOT EXISTS (
                  SELECT 1 FROM stg.account   a WHERE f.target_table = 'account'  AND a.account_id::text  = f.business_key
                  UNION ALL
                  SELECT 1 FROM stg.client    c WHERE f.target_table = 'client'   AND c.client_id::text   = f.business_key
                  UNION ALL
                  SELECT 1 FROM stg.disp      d WHERE f.target_table = 'disp'     AND d.disp_id::text     = f.business_key
                  UNION ALL
                  SELECT 1 FROM stg.card      k WHERE f.target_table = 'card'     AND k.card_id::text     = f.business_key
                  UNION ALL
                  SELECT 1 FROM stg.loan      l WHERE f.target_table = 'loan'     AND l.loan_id::text     = f.business_key
                  UNION ALL
                  SELECT 1 FROM stg.trans     t WHERE f.target_table = 'trans'    AND t.trans_id::text    = f.business_key
                  UNION ALL
                  SELECT 1 FROM stg.district  s WHERE f.target_table = 'district' AND s.district_id::text = f.business_key
                  UNION ALL
                  SELECT 1 FROM stg."order"   o WHERE f.target_table = 'order'    AND o.order_id::text    = f.business_key
              )
            GROUP BY f.target_table, f.rule_id
            """,
        )
    assert not unresolved, f"flags that reach no row: {unresolved}"


def test_warn_flags_are_visible_on_the_core_rows() -> None:
    """The flags must actually appear in core._dq_flags, where a consumer sees them."""
    with db.connect() as conn:
        counts = {
            row["flag"]: row["rows"]
            for row in db.fetch_all(
                conn,
                """
                SELECT flag, count(*) AS rows FROM (
                    SELECT unnest(_dq_flags) AS flag FROM core.dim_account
                    UNION ALL SELECT unnest(_dq_flags) FROM core.dim_client
                    UNION ALL SELECT unnest(_dq_flags) FROM core.fact_loan
                    UNION ALL SELECT unnest(_dq_flags) FROM core.fact_transaction
                ) f GROUP BY flag
                """,
            )
        }
    assert counts.get("con_balance_reconciliation_material") == 55, counts
    assert counts.get("con_intraday_order_ambiguous") == 183, counts
    assert counts.get("val_owner_age_at_loan_start") == 6, counts
    assert counts.get("val_owner_age_at_account_open") == 114, counts


# ---------------------------------------------------------------------------
# Cleaning: every decodable code in staging actually got decoded
#
# The first build shipped 341 standing orders carrying k_symbol = LEASING with
# no English label, because the code catalogue check covered stg.trans and not
# stg."order". Nothing failed: the profiler reported the code, and the only
# rule that noticed was the null-label completeness sweep, which reads as
# "this column is often empty" rather than "a code was not decoded".
#
# These tests make the silence impossible. The first asserts the outcome a
# consumer cares about -- a code with no label is a cleaning step that did not
# happen -- and the second pins the catalogue to every column that carries a
# coded value, so a new coded column cannot be added without being checked.
# ---------------------------------------------------------------------------

#: (table, code column, label column) for every coded column in staging.
CODED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("stg.account", "frequency_code", "frequency_label"),
    ("stg.disp", "disp_type_code", "disp_type_label"),
    ("stg.loan", "status_code", "status_label"),
    ("stg.trans", "trans_type_code", "trans_type_label"),
    ("stg.trans", "operation_code", "operation_label"),
    ("stg.trans", "k_symbol_code", "k_symbol_label"),
    ('stg."order"', "k_symbol_code", "k_symbol_label"),
)


@pytest.mark.parametrize(("table", "code", "label"), CODED_COLUMNS)
def test_every_present_code_resolves_to_a_label(table: str, code: str, label: str) -> None:
    """No row may carry a code the cleaning step failed to decode."""
    with db.connect() as conn:
        undecoded = db.fetch_all(
            conn,
            f"""
            SELECT "{code}" AS code, count(*) AS rows
            FROM {table}
            WHERE "{code}" IS NOT NULL AND "{label}" IS NULL
            GROUP BY 1 ORDER BY 2 DESC
            """,
        )
    assert not undecoded, (
        f"{table}.{code} holds codes with no label: {undecoded}. "
        f"Add them to the decode map in src/config.py and to the CASE in sql/10_stg.sql."
    )


def test_the_code_catalogue_covers_every_coded_column() -> None:
    """build_model must check each coded column, not only the ones on trans."""
    from src.build_model import check_codes_against_staging  # noqa: PLC0415

    import inspect  # noqa: PLC0415

    source = inspect.getsource(check_codes_against_staging)
    for table, code, _label in CODED_COLUMNS:
        bare = table.replace('"', "")
        assert (table in source or bare in source) and code in source, (
            f"{table}.{code} is cleaned but is not in the code catalogue check, "
            f"so an unknown code there would never fail a build"
        )


# ---------------------------------------------------------------------------
# The cleaning ledger must describe THIS build, not every build
#
# raw.load_audit keeps one row per file per ingest run. The first version of
# the ledger summed the whole table, so after three `make build` runs against
# the same database it reported 3,239,040 rows landed from 24 files instead of
# 1,079,680 from 8. Those two numbers are rendered into
# docs/CLEANING_LEDGER.md and into the workbook's Cleaning tab, so the defect
# put a wrong figure in a deliverable -- and only on a re-run, which is
# exactly the case a single clean-build test would never reach.
# ---------------------------------------------------------------------------


def test_the_ledger_counts_one_ingest_not_all_of_them() -> None:
    """C01 and C02 must report the latest load, whatever the history holds."""
    from src import cleaning_ledger  # noqa: PLC0415

    steps = {step.step: step for step in cleaning_ledger.STEPS}
    with db.connect() as conn:
        runs = int(db.fetch_value(
            conn, "SELECT count(DISTINCT run_id) FROM raw.load_audit") or 0)
        landed = cleaning_ledger.measure(conn, steps["C01"])
        files = cleaning_ledger.measure(conn, steps["C02"])
        actual = int(db.fetch_value(
            conn,
            """
            SELECT sum(n) FROM (
                SELECT count(*) AS n FROM raw.account UNION ALL
                SELECT count(*) FROM raw.client       UNION ALL
                SELECT count(*) FROM raw.disp         UNION ALL
                SELECT count(*) FROM raw.card         UNION ALL
                SELECT count(*) FROM raw.loan         UNION ALL
                SELECT count(*) FROM raw."order"      UNION ALL
                SELECT count(*) FROM raw.trans        UNION ALL
                SELECT count(*) FROM raw.district
            ) t
            """,
        ) or 0)

    assert landed == actual, (
        f"ledger C01 reports {landed:,} rows landed but raw holds {actual:,}; "
        f"there are {runs} ingest runs in load_audit, so the probe is almost "
        f"certainly summing all of them"
    )
    assert files == len(config.RAW_TABLES), (
        f"ledger C02 reports {files} files; there are "
        f"{len(config.RAW_TABLES)} source tables"
    )
