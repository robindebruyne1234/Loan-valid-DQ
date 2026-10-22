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
