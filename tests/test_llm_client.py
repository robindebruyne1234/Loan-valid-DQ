"""Test the local Ollama provider without needing a model.

Every way a local runtime fails has to come back as a typed, actionable
error with ``executed = False``, because the page and the question runner
both turn ``executed = False`` into "no answer" rather than inventing one.
The fake server in :mod:`tests.fake_ollama` plays Ollama's HTTP API; the
live model is exercised separately, in ``tests/test_llm_live.py``.
"""

from __future__ import annotations

import pytest

from src import config, llm_client, run_questions, sql_guard
from tests import fake_ollama

PROMPT = "SEMANTIC LAYER ... QUESTION (Q1): How many clients do we have per region?"


@pytest.fixture()
def fake(monkeypatch: pytest.MonkeyPatch) -> fake_ollama.FakeOllama:
    """A fake Ollama the provider is pointed at.

    :yields: Its controller.
    """
    with fake_ollama.running() as server:
        monkeypatch.setattr(config, "OLLAMA_HOST", server.url)
        yield server


def test_a_good_answer_is_returned_with_its_timings(fake: fake_ollama.FakeOllama) -> None:
    """The happy path: executed, text intact, timings in seconds, zero cost."""
    fake.answers("SELECT region, count(*) FROM ai.client GROUP BY region")
    response = llm_client.call_ollama(PROMPT, fake_ollama.MODEL, timeout=10)
    assert response.executed, response.error
    assert response.error_kind is None
    parsed, error = run_questions.parse_model_output(response.text)
    assert error is None and parsed["sql"].startswith("SELECT region")
    assert response.usage["prompt_eval_count"] == 8_000
    assert response.usage["prompt_eval_sec"] == 1.5
    assert response.usage["cost_usd"] == 0.0


def test_the_request_constrains_the_answer_and_sizes_the_context(
    fake: fake_ollama.FakeOllama,
) -> None:
    """What is sent: the schema, an explicit window, the system prompt, no stream."""
    fake.answers("SELECT 1 FROM ai.client")
    llm_client.call_ollama(PROMPT, fake_ollama.MODEL, timeout=10)
    sent = fake.requests[-1]
    assert sent["format"] == llm_client.ANSWER_SCHEMA
    assert sent["options"]["num_ctx"] == config.OLLAMA_NUM_CTX
    assert sent["options"]["num_predict"] == config.OLLAMA_NUM_PREDICT
    assert sent["options"]["temperature"] == config.LLM_TEMPERATURE
    assert sent["system"] == llm_client.SYSTEM_PROMPT
    assert sent["stream"] is False
    assert sent["keep_alive"] == config.OLLAMA_KEEP_ALIVE


def test_gpu_layers_are_left_to_ollama_unless_configured(
    fake: fake_ollama.FakeOllama, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unset: Ollama decides. Set: sent as num_gpu, so 0 means CPU only."""
    fake.answers("SELECT 1 FROM ai.client")
    monkeypatch.setattr(config, "OLLAMA_NUM_GPU", None)
    llm_client.call_ollama(PROMPT, fake_ollama.MODEL, timeout=10)
    assert "num_gpu" not in fake.requests[-1]["options"]

    monkeypatch.setattr(config, "OLLAMA_NUM_GPU", 0)
    llm_client.call_ollama(PROMPT, fake_ollama.MODEL, timeout=10)
    assert fake.requests[-1]["options"]["num_gpu"] == 0


def test_no_secret_reaches_the_model(fake: fake_ollama.FakeOllama) -> None:
    """The real prompt carries the semantic layer, and no credential or salt."""
    from src import semantic_context  # noqa: PLC0415

    pack = semantic_context.render_context_pack(semantic_context.load_semantic_layer())
    prompt = run_questions.build_prompt(pack, "Q1", "How many clients do we have per region?")
    fake.answers("SELECT 1 FROM ai.client")
    llm_client.call_ollama(prompt, fake_ollama.MODEL, timeout=10)
    sent = str(fake.requests[-1])
    for secret in (config.PGPASSWORD, config.DEMO_USER_PASSWORD, config.REF_SALT):
        assert secret not in sent
    assert "ai.client" in sent, "the semantic layer was not sent"


def test_the_token_id_array_is_not_kept_in_the_audit_record(
    fake: fake_ollama.FakeOllama,
) -> None:
    """Ollama returns the conversation as token ids; the log keeps the text."""
    fake.answers("SELECT 1 FROM ai.client")
    response = llm_client.call_ollama(PROMPT, fake_ollama.MODEL, timeout=10)
    assert "context" not in response.raw


def test_a_runtime_that_is_not_running_says_how_to_start_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing listening: runtime_unavailable, with the fix in the message."""
    monkeypatch.setattr(config, "OLLAMA_HOST", fake_ollama.closed_port_url())
    response = llm_client.call_ollama(PROMPT, fake_ollama.MODEL, timeout=5)
    assert not response.executed
    assert response.error_kind == "runtime_unavailable"
    assert "ollama serve" in response.error


def test_a_missing_model_says_which_pull_to_run(fake: fake_ollama.FakeOllama) -> None:
    """Ollama's 404 for an unpulled model becomes the exact command to run."""
    fake.status = 404
    fake.body = {"error": f"model '{fake_ollama.MODEL}' not found, try pulling it first"}
    response = llm_client.call_ollama(PROMPT, fake_ollama.MODEL, timeout=10)
    assert not response.executed
    assert response.error_kind == "model_missing"
    assert f"ollama pull {fake_ollama.MODEL}" in response.error


def test_a_server_error_is_reported_with_ollamas_own_message(
    fake: fake_ollama.FakeOllama,
) -> None:
    """Any other HTTP failure keeps the detail Ollama gave."""
    fake.status, fake.body = 500, {"error": "llama runner process has terminated"}
    response = llm_client.call_ollama(PROMPT, fake_ollama.MODEL, timeout=10)
    assert response.error_kind == "http_error"
    assert "llama runner process has terminated" in response.error


def test_a_slow_model_times_out(fake: fake_ollama.FakeOllama) -> None:
    """A reply later than the timeout is a timeout, not a hang."""
    fake.answers("SELECT 1 FROM ai.client")
    fake.delay = 3.0
    response = llm_client.call_ollama(PROMPT, fake_ollama.MODEL, timeout=1)
    assert not response.executed
    assert response.error_kind == "timeout"
    assert "LLM_TIMEOUT_SECONDS" in response.error


def test_an_empty_answer_is_a_failure_not_an_answer(fake: fake_ollama.FakeOllama) -> None:
    """Nothing produced must never look like something produced."""
    fake.status, fake.body = 200, fake_ollama.generate_payload("   ")
    response = llm_client.call_ollama(PROMPT, fake_ollama.MODEL, timeout=10)
    assert not response.executed
    assert response.error_kind == "empty_response"


def test_an_answer_cut_off_by_the_token_limit_is_refused(
    fake: fake_ollama.FakeOllama,
) -> None:
    """A truncated JSON object is a failure with a fix, not a parse puzzle."""
    fake.body = fake_ollama.generate_payload('{"sql": "SELECT', done_reason="length")
    response = llm_client.call_ollama(PROMPT, fake_ollama.MODEL, timeout=10)
    assert not response.executed
    assert response.error_kind == "output_truncated"
    assert "OLLAMA_NUM_PREDICT" in response.error


def test_a_prompt_that_fills_the_context_window_is_refused(
    fake: fake_ollama.FakeOllama,
) -> None:
    """If the semantic layer may have been cut, the answer is not trusted."""
    fake.body = fake_ollama.generate_payload(fake_ollama.answer("SELECT 1 FROM ai.client"),
                                             prompt_eval_count=config.OLLAMA_NUM_CTX)
    response = llm_client.call_ollama(PROMPT, fake_ollama.MODEL, timeout=10)
    assert not response.executed
    assert response.error_kind == "context_overflow"
    assert "OLLAMA_NUM_CTX" in response.error


def test_a_prompt_too_large_for_the_window_is_never_sent(
    fake: fake_ollama.FakeOllama,
) -> None:
    """Refused before the call: Ollama would truncate it without saying so."""
    fake.answers("SELECT 1 FROM ai.client")
    oversized = "x" * int(config.OLLAMA_NUM_CTX * llm_client.PROMPT_CHARS_PER_TOKEN_LOW)
    response = llm_client.call_ollama(oversized, fake_ollama.MODEL, timeout=10)
    assert not response.executed
    assert response.error_kind == "context_overflow"
    assert fake.requests == [], "an oversized prompt reached the runtime"


def test_a_silently_truncated_prompt_is_refused(fake: fake_ollama.FakeOllama) -> None:
    """The case measured on Ollama 0.40.11: HTTP 200, a fluent answer, and
    only 1,026 of 7,979 prompt tokens evaluated. The answer must not count."""
    from src import semantic_context  # noqa: PLC0415

    pack = semantic_context.render_context_pack(semantic_context.load_semantic_layer())
    prompt = run_questions.build_prompt(pack, "Q1", "How many clients do we have per region?")
    fake.body = fake_ollama.generate_payload(
        fake_ollama.answer("SELECT region, count(*) FROM ai.client GROUP BY region"),
        prompt_eval_count=1026)
    response = llm_client.call_ollama(prompt, fake_ollama.MODEL, timeout=10)
    assert not response.executed
    assert response.error_kind == "context_overflow"
    assert "1026 tokens" in response.error


def test_a_body_that_is_not_json_is_a_malformed_response(
    fake: fake_ollama.FakeOllama,
) -> None:
    """A broken envelope is reported as such, not as an empty answer."""
    fake.status, fake.body = 200, "<html>proxy error</html>"
    response = llm_client.call_ollama(PROMPT, fake_ollama.MODEL, timeout=10)
    assert response.error_kind == "malformed_response"


@pytest.mark.parametrize("text,expected", [
    ("Sure! Here is the query you asked for.", "no JSON object"),
    ('{"sql": ""}', "no non-empty 'sql' field"),
    ('["SELECT 1"]', "no JSON object"),
    ('{"sql": "SELECT 1", ', "not valid JSON"),
])
def test_malformed_model_output_is_rejected_with_a_reason(text: str, expected: str) -> None:
    """Output that is not the contract never reaches the guard as SQL."""
    parsed, error = run_questions.parse_model_output(text)
    assert parsed is None
    assert expected in error


@pytest.mark.parametrize("sql", [
    "DELETE FROM ai.client",
    "SELECT * FROM core.dim_client",
    "WITH dim_client AS (SELECT 1) SELECT * FROM core.dim_client",
    "SELECT sec.end_session()",
    "SELECT 1 FROM ai.client; DROP TABLE core.dim_client",
])
def test_well_formed_but_unsafe_output_stops_at_the_guard(sql: str) -> None:
    """The contract being valid says nothing about the SQL inside it."""
    parsed, error = run_questions.parse_model_output(fake_ollama.answer(sql))
    assert error is None
    assert not sql_guard.guard(parsed["sql"]).allowed


def test_status_reports_a_present_model(fake: fake_ollama.FakeOllama) -> None:
    """Reachable and pulled: no error."""
    status = llm_client.ollama_status(fake_ollama.MODEL)
    assert status["reachable"] and status["model_present"]
    assert status["error"] is None


def test_status_reports_a_missing_model(fake: fake_ollama.FakeOllama) -> None:
    """Reachable but not pulled: the pull command."""
    fake.models = []
    status = llm_client.ollama_status(fake_ollama.MODEL)
    assert status["reachable"] and not status["model_present"]
    assert f"ollama pull {fake_ollama.MODEL}" in status["error"]


def test_status_reports_an_absent_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not running: says so, quickly."""
    monkeypatch.setattr(config, "OLLAMA_HOST", fake_ollama.closed_port_url())
    status = llm_client.ollama_status(fake_ollama.MODEL, timeout=2)
    assert not status["reachable"]
    assert "not reachable" in status["error"]


def test_choosing_ollama_alone_never_sends_a_claude_model_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider override without a model gets that provider's default."""
    seen: dict[str, str] = {}

    def capture(prompt: str, model: str, timeout: int) -> llm_client.LLMResponse:
        seen["model"] = model
        return llm_client.LLMResponse(provider="ollama", model=model, executed=False)

    monkeypatch.setattr(config, "LLM_PROVIDER", "claude_cli")
    monkeypatch.setattr(llm_client, "call_ollama", capture)
    llm_client.complete(PROMPT, provider="ollama")
    assert seen["model"] == config.LLM_DEFAULT_MODELS["ollama"]


@pytest.mark.parametrize("value,expected", [
    ("http://127.0.0.1:11434", "http://127.0.0.1:11434"),
    ("http://localhost:11434/", "http://localhost:11434"),
    ("0.0.0.0:11434", "http://127.0.0.1:11434"),
    ("127.0.0.1:11500", "http://127.0.0.1:11500"),
])
def test_the_ollama_address_is_normalised(value: str, expected: str) -> None:
    """OLLAMA_HOST is also Ollama's own bind setting, often without a scheme."""
    assert config._http_url(value) == expected
