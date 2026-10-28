"""The real local model, end to end. Opt-in, because it is slow on a laptop.

Without ``BERKA_LIVE_LLM=1`` this skips and says why. With it, an absent
runtime or model is a FAILURE rather than a skip: the claim under test is
that the local model works, and a skip would let that claim pass untested.

What is asserted is the contract -- a call that completes, JSON in the
agreed shape, SQL that passes the guard and runs as the persona. Whether the
numbers are right is measured against the reference answers by
``scripts\\windows.ps1 questions-local`` and ``evaluate-local``.
"""

from __future__ import annotations

import os

import pytest

from src import config, llm_client, run_questions, semantic_context, sql_guard
from tests import support

pytestmark = pytest.mark.skipif(
    os.environ.get("BERKA_LIVE_LLM") != "1",
    reason="live model test is opt-in: set BERKA_LIVE_LLM=1 with Ollama running "
           "(it takes minutes on a laptop CPU)",
)

MODEL = os.environ.get("LLM_MODEL") or config.LLM_DEFAULT_MODELS["ollama"]


def test_the_local_model_answers_in_contract_and_its_sql_runs_as_the_persona() -> None:
    """Q1 through the real model, the real guard and the real policies."""
    status = llm_client.ollama_status(MODEL)
    assert status["error"] is None, status["error"]

    question = next(q for q in run_questions.load_questions() if q["id"] == "Q1")
    pack = semantic_context.render_context_pack(semantic_context.load_semantic_layer())
    prompt = run_questions.build_prompt(pack, "Q1", question["question"])
    response = llm_client.complete(prompt, provider="ollama", model=MODEL)
    assert response.executed, f"[{response.error_kind}] {response.error}"

    parsed, error = run_questions.parse_model_output(response.text)
    assert error is None, error
    verdict = sql_guard.guard(parsed["sql"])
    assert verdict.allowed, f"guard refused the model's SQL: {verdict.reason}"

    with support.consumer("rm_north") as conn:
        _, rows, db_error = sql_guard.execute_guarded(conn, parsed["sql"])
    assert db_error is None, f"the model's SQL failed in the database: {db_error}"
    assert rows, "the model's SQL returned nothing for a manager with a book"
