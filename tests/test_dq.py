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
