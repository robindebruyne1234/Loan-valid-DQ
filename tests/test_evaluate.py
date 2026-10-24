"""Test the evaluator itself, including that it rejects wrong answers.

An evaluator that reports "match" for everything proves nothing, and the one
in this project was loosened once already (to accept `1996-01` as well as the
integer `1` for a month). So it is tested in both directions: the real LLM
answers must match the reference, and deliberately corrupted answers must not.
"""

from __future__ import annotations

import copy
import json

import pytest

from src import config, evaluate


@pytest.fixture(scope="module")
def payloads() -> tuple[dict, dict]:
    """Load the reference and LLM result sets.

    :returns: Tuple of (reference results, LLM results).
    """
    reference = json.loads(config.REFERENCE_RESULTS_JSON.read_text(encoding="utf-8"))["results"]
    llm = json.loads(config.LLM_RESULTS_JSON.read_text(encoding="utf-8"))["results"]
    return reference, llm


def test_every_question_has_an_expectation() -> None:
    """The evaluator must know how to compare all ten questions."""
    assert set(evaluate.EXPECTATIONS) == set(config.QUESTION_IDS)


def test_the_real_answers_match_the_reference(payloads: tuple[dict, dict]) -> None:
    """The recorded LLM answers must match the hand-written reference answers."""
    reference, llm = payloads
    for question_id in config.QUESTION_IDS:
        verdict = evaluate.evaluate_question(
            question_id, reference[question_id], llm.get(question_id)
        )
        assert verdict["verdict"] == "match", (
            f"{question_id}: {verdict['verdict']}, missing {verdict['missing'][:3]}"
        )


@pytest.mark.parametrize("question_id", ["Q1", "Q3", "Q5", "Q9"])
def test_a_wrong_number_is_caught(payloads: tuple[dict, dict], question_id: str) -> None:
    """Changing one measure in an answer must stop it matching.

    :param payloads: Reference and LLM results.
    :param question_id: Question whose answer is corrupted.
    """
    reference, llm = payloads
    corrupted = copy.deepcopy(llm[question_id])
    for row in corrupted["rows"]:
        for key, value in row.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                row[key] = value * 2 + 7   # not reachable by rounding
    verdict = evaluate.evaluate_question(question_id, reference[question_id], corrupted)
    assert verdict["verdict"] != "match", f"{question_id}: a doubled answer still matched"


def test_a_wrong_ranking_is_caught(payloads: tuple[dict, dict]) -> None:
    """Reversing a ranked answer must fail the order check, even with right values."""
    reference, llm = payloads
    corrupted = copy.deepcopy(llm["Q5"])
    corrupted["rows"] = list(reversed(corrupted["rows"]))
    verdict = evaluate.evaluate_question("Q5", reference["Q5"], corrupted)
    assert verdict["verdict"] != "match"
    assert verdict["order_ok"] is False


def test_a_truncated_answer_is_partial(payloads: tuple[dict, dict]) -> None:
    """Dropping rows must be reported as partial, naming what is missing."""
    reference, llm = payloads
    corrupted = copy.deepcopy(llm["Q1"])
    corrupted["rows"] = corrupted["rows"][:2]
    verdict = evaluate.evaluate_question("Q1", reference["Q1"], corrupted)
    assert verdict["verdict"] == "partial"
    assert len(verdict["missing"]) == verdict["expected_values"] - verdict["matched_values"] > 0


def test_an_empty_answer_is_a_mismatch(payloads: tuple[dict, dict]) -> None:
    """An answer with no rows must be a mismatch, not a vacuous match."""
    reference, llm = payloads
    corrupted = copy.deepcopy(llm["Q3"])
    corrupted["rows"] = []
    verdict = evaluate.evaluate_question("Q3", reference["Q3"], corrupted)
    assert verdict["verdict"] == "mismatch"


def test_a_missing_answer_is_not_executed(payloads: tuple[dict, dict]) -> None:
    """A question the model never answered is reported as NOT EXECUTED."""
    reference, _ = payloads
    verdict = evaluate.evaluate_question("Q2", reference["Q2"], None)
    assert verdict["verdict"] == "not_executed"
    assert verdict["matched_values"] == 0


def test_booleans_are_not_treated_as_numbers() -> None:
    """``True`` must not match a count of 1, which would create false matches."""
    assert evaluate.numeric(True) is None
    assert not evaluate.row_matches({"flag": True}, (), 1.0)
    assert evaluate.row_matches({"n": 1}, (), 1.0)


def test_tolerance_is_absolute_not_relative(payloads: tuple[dict, dict]) -> None:
    """A large money sum must not carry a proportionally large slack.

    The evaluator originally used a relative tolerance of 1e-4. On Q5's top
    district -- 115,130,200.10 CZK of incoming transactions -- that accepted an
    answer wrong by 11,513 CZK and called it a match. The tolerance exists
    only to absorb two-decimal rounding, so it is absolute.
    """
    reference, llm = payloads
    corrupted = copy.deepcopy(llm["Q5"])
    biggest = max(
        value
        for row in corrupted["rows"]
        for value in row.values()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    )
    assert biggest > 1_000_000, "expected Q5 to carry a large monetary sum"

    for row in corrupted["rows"]:
        for key, value in row.items():
            if value == biggest:
                row[key] = value + 1_000.0   # 0.00087% -- inside the old slack

    verdict = evaluate.evaluate_question("Q5", reference["Q5"], corrupted)
    assert verdict["verdict"] != "match", (
        "a 1,000 CZK error on a 115 m sum was accepted; the tolerance is relative again"
    )


def test_two_decimal_rounding_still_matches() -> None:
    """Tightening the tolerance must not break the case it exists for.

    A model that reports 43808.9388 where the reference rounds to 43808.94 is
    right, and must still match.
    """
    assert evaluate.close(43808.9388, 43808.94)
    assert evaluate.close(11.1437, 11.14)
    assert not evaluate.close(43808.94, 43810.00)
