"""Test that the semantic layer tells the truth about the database.

A semantic layer that has drifted from the schema is worse than no semantic
layer: it gives the model confident, wrong information, and the model has no
way to check it. So the layer is validated against ``information_schema`` on
every run, and these tests additionally assert the properties that make it
useful rather than merely accurate.
"""

from __future__ import annotations

from src import config, db, semantic_context


def test_semantic_layer_agrees_with_the_database() -> None:
    """Every described entity and column exists, and nothing exists undescribed."""
    layer = semantic_context.load_semantic_layer()
    with db.connect() as conn:
        problems = semantic_context.validate(layer, conn)
    assert not problems, "\n".join(problems)


def test_every_question_is_claimed_by_an_entity() -> None:
    """Each of the 10 questions has at least one entity that answers it."""
    layer = semantic_context.load_semantic_layer()
    claimed = {q for entity in layer["entities"] for q in (entity.get("answers") or [])}
    assert set(config.QUESTION_IDS) <= claimed


def test_declared_grains_hold_in_the_database() -> None:
    """A declared grain is a promise to the model, so it is verified.

    This is the property an AI assistant silently depends on: if
    ``ai.account_owner`` were not one row per account, a correct-looking query
    would double count.
    """
    layer = semantic_context.load_semantic_layer()
    with db.connect() as conn:
        for entity in layer["entities"]:
            key = entity.get("primary_key") or []
            if not key:
                continue
            key_list = ", ".join(f'"{part}"' for part in key)
            duplicates = db.fetch_value(
                conn,
                f"SELECT count(*) FROM (SELECT {key_list} FROM {entity['name']} "
                f"GROUP BY {key_list} HAVING count(*) > 1) d",
            )
            assert duplicates == 0, f"{entity['name']} violates its declared grain"


def test_context_pack_contains_the_definitions_the_questions_need() -> None:
    """The rendered pack must carry the traps, not just the column names.

    Each of these strings is a place where a plausible query gives a wrong
    answer. If one disappears from the pack, a question starts failing and the
    cause would be hard to find, so their presence is pinned here.
    """
    layer = semantic_context.load_semantic_layer()
    pack = semantic_context.render_context_pack(layer)
    for needle in (
        "is_problematic",          # Q3, Q10: the certified definition
        "no card",                 # Q4: the explicit category
        "direction",               # Q5: what "incoming" means
        "ai.calendar",             # Q6: zero-filling periods
        "owner_age_at_loan_start", # Q7: pre-computed exact age
        "disponent",               # Q4, Q8: the owner/disponent distinction
        "account_month_end_balance",  # Q9: the right entity
        "is_carried_forward",      # Q9: the caveat
        "within-group rate",       # Q10: the share definition
        "client's own region",     # Q1 vs Q5: whose district
    ):
        assert needle in pack, f"the context pack no longer explains '{needle}'"


def test_context_pack_contains_no_answers() -> None:
    """The pack must not leak a reference answer, or the evaluation means nothing."""
    layer = semantic_context.load_semantic_layer()
    pack = semantic_context.render_context_pack(layer)
    for forbidden in ("11.14", "43808", "South Moravia: 937", "76 of 682"):
        assert forbidden not in pack, f"the context pack leaks an answer: {forbidden}"


def test_every_caveat_names_a_real_rule() -> None:
    """Each caveat points at a rule id that exists in the rule file."""
    import yaml

    layer = semantic_context.load_semantic_layer()
    rules = yaml.safe_load(config.DQ_RULES_YAML.read_text(encoding="utf-8"))["rules"]
    rule_ids = {rule["rule_id"] for rule in rules}
    for caveat in layer["caveats"]:
        assert caveat["rule_id"] in rule_ids, caveat["id"]
        assert caveat["severity"] in config.VALID_SEVERITIES
        assert caveat["rows"] > 0


def test_prompt_template_has_the_required_placeholders() -> None:
    """The template must take the context pack and the question, and ask for JSON."""
    template = config.PROMPT_TEMPLATE_MD.read_text(encoding="utf-8")
    for placeholder in ("{context_pack}", "{question}", "{question_id}"):
        assert placeholder in template, placeholder
    assert '"sql"' in template and '"caveats"' in template


# ---------------------------------------------------------------------------
# Regressions from the semantic-model audit (docs/SEMANTIC_MODEL_AUDIT.md)
# ---------------------------------------------------------------------------


def test_validator_catches_join_grain_and_metadata_drift() -> None:
    """The defect classes the audit found must fail validation, not pass it.

    Before the audit the validator compared column-name sets only, so a
    duplicated column, a stale row count and an undeclared fan-out all passed.
    """
    import copy

    layer = copy.deepcopy(semantic_context.load_semantic_layer())
    entities = {entity["name"]: entity for entity in layer["entities"]}
    account, client = entities["ai.account"], entities["ai.client"]
    # A fan-out join declared as one-to-one.
    next(j for j in account["joins"] if j["to"] == "ai.transaction")["cardinality"] = "one-to-one"
    # A join that loses rows, declared as if it did not.
    next(j for j in client["joins"] if j["to"] == "ai.account_owner").pop("optional")
    client["columns"].append(dict(client["columns"][0]))
    entities["ai.code_reference"]["row_count_unfiltered"] = 1
    next(m for m in layer["metrics"] if m["name"] == "loan_count")["time_column"] = "open_date"

    with db.connect() as conn:
        problems = "\n".join(semantic_context.validate(layer, conn))
    for expected in (
        "ai.account -> ai.transaction: declared one-to-one",
        "ai.client -> ai.account_owner: 869 rows of ai.client have no match",
        "described more than once",
        "ai.code_reference: row_count_unfiltered says 1",
        "metric loan_count: time_column open_date",
    ):
        assert expected in problems, f"validator missed: {expected}\n{problems}"


def test_context_pack_defines_quarters_and_time_anchors() -> None:
    """'Q1-Q3 of 1995 and 1998' must be answerable from the pack alone.

    The pack labels the reference questions Q1-Q10, so a user's 'Q1' (a
    quarter) has to be disambiguated explicitly, and each metric must say
    which date its periods are filtered on.
    """
    pack = semantic_context.render_context_pack(semantic_context.load_semantic_layer())
    for needle in (
        "Q1 = January-March",
        "Q3 = July-September",
        "they never mean quarters",
        "every named year must appear in the filter",
        "time_column: `loan_date`",
        "loan_date = date_key",
        "one-to-many",
    ):
        assert needle in pack, f"the context pack no longer explains '{needle}'"


def test_calendar_quarters_agree_with_date_ranges() -> None:
    """The two ways to express 'Q1-Q3 of 1995 and 1998' must give one answer.

    Guards ai.calendar (quarter derived from month) and the example in the
    design record: a calendar join on year/quarter and half-open date ranges
    on loan_date have to agree to the row.
    """
    with db.connect() as conn:
        assert db.fetch_value(
            conn, "SELECT count(*) FROM ai.calendar WHERE quarter <> (month - 1) / 3 + 1") == 0
        via_calendar = db.fetch_all(conn, """
            SELECT c.year, count(*) AS loans, sum(l.amount) AS total
            FROM ai.loan l JOIN ai.calendar c ON c.date_key = l.loan_date
            WHERE c.year IN (1995, 1998) AND c.quarter BETWEEN 1 AND 3
            GROUP BY c.year ORDER BY c.year""")
        via_ranges = db.fetch_all(conn, """
            SELECT extract(year FROM l.loan_date)::int AS year, count(*) AS loans, sum(l.amount) AS total
            FROM ai.loan l
            WHERE (l.loan_date >= DATE '1995-01-01' AND l.loan_date < DATE '1995-10-01')
               OR (l.loan_date >= DATE '1998-01-01' AND l.loan_date < DATE '1998-10-01')
            GROUP BY 1 ORDER BY 1""")
    assert [r["year"] for r in via_calendar] == [1995, 1998]
    assert via_calendar == via_ranges


def test_the_traps_the_pack_warns_about_are_real() -> None:
    """Each warning in the pack is a claim about the data, so it is measured.

    The audit found one warning pointing the wrong way (the age bias); these
    pin the direction and size of the ones the model is told to avoid.
    """
    with db.connect() as conn:
        exact, truncated = db.fetch_all(conn, """
            SELECT avg(owner_age_at_loan_start) AS exact,
                   avg(date_part('year', age(loan_date, owner_birth_date))) AS truncated
            FROM ai.loan""")[0].values()
        assert float(exact) - float(truncated) > 0.3, "truncating ages no longer reads low"

        fan_out = db.fetch_value(conn, """
            SELECT (SELECT sum(l.amount) FROM ai.loan l JOIN ai.transaction t USING (account_id))
                 / (SELECT sum(amount) FROM ai.loan)""")
        assert float(fan_out) > 100, "the loan-to-transaction fan-out warning is overstated"

        dropped = db.fetch_value(conn, """
            SELECT count(*) FROM ai.client c
            WHERE NOT EXISTS (SELECT 1 FROM ai.account_owner o WHERE o.owner_client_id = c.client_id)""")
        assert dropped == 869
