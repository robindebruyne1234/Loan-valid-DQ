"""Step 7 end to end: the page's question, through a model, the guard and RLS.

The model is :mod:`tests.fake_ollama`, which answers in Ollama's own HTTP
shapes with SQL the test chose. Everything after the model is real: the HTTP
handler, the two-factor login, the guard, PostgreSQL and its row level
security. What these tests establish is therefore not "the model is right"
-- the live run and ``questions-local`` measure that -- but that whatever a
model writes is executed as the logged-in persona, only as that persona, and
only if the guard allows it.
"""

from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer

import pytest

from src import auth, config, webapp
from tests import fake_ollama
from tests.test_webapp import get, post

QUESTION = "How many clients are there?"


@pytest.fixture(scope="module")
def base_url() -> str:
    """Run the app on an ephemeral port for the duration of the module.

    :yields: The base URL.
    """
    server = ThreadingHTTPServer(("127.0.0.1", 0), webapp.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(scope="module")
def sessions(base_url: str) -> dict[str, str]:
    """Log two unrelated customers in through the page's own login, once.

    :returns: role -> browser session token.
    """
    tokens = {}
    for role in ("client_3763", "client_11409"):
        status, body = post(f"{base_url}/api/login",
                            {"role": role, "code": auth.demo_fresh_code(role)})
        assert status == 200, body
        tokens[role] = body["session"]
    return tokens


@pytest.fixture()
def model(monkeypatch: pytest.MonkeyPatch) -> fake_ollama.FakeOllama:
    """Point the app at a fake Ollama.

    :yields: Its controller.
    """
    with fake_ollama.running() as fake:
        monkeypatch.setattr(config, "LLM_PROVIDER", "ollama")
        monkeypatch.setattr(config, "LLM_MODEL", fake_ollama.MODEL)
        monkeypatch.setattr(config, "OLLAMA_HOST", fake.url)
        yield fake


def ask(base_url: str, session: str, question: str = QUESTION) -> dict:
    """Ask through the HTTP API exactly as the page does.

    :returns: The response body; the status must be 200.
    """
    status, body = post(f"{base_url}/api/ask", {"session": session, "question": question},
                        timeout=120)
    assert status == 200, body
    return body


#: Both customers' ids in one statement: the cross-customer attempt and the
#: identity check, so each customer costs one login.
CROSS_CUSTOMER_SQL = (
    "SELECT client_id, current_user AS acting, session_user AS logged_in "
    "FROM ai.client WHERE client_id IN (3763, 11409) ORDER BY client_id"
)


@pytest.mark.parametrize("role,own_id", [("client_3763", 3763), ("client_11409", 11409)])
def test_the_same_sql_answers_each_customer_with_only_themselves(
    base_url: str, sessions: dict[str, str], model: fake_ollama.FakeOllama,
    role: str, own_id: int,
) -> None:
    """Request, model, guard, database, rendered rows -- as that persona only.

    The statement asks for both customers by id. Each gets exactly their own
    row, and the database reports the persona as the acting identity.
    """
    model.answers(CROSS_CUSTOMER_SQL)
    body = ask(base_url, sessions[role])

    assert body["stage"] == "done", body
    assert body["as_role"] == role
    assert body["provider"] == "ollama" and body["model"] == fake_ollama.MODEL
    assert body["sql"] == CROSS_CUSTOMER_SQL
    assert body["guard"]["allowed"] is True
    assert body["rows"] == [{"client_id": own_id, "acting": role, "logged_in": role}]
    assert body["row_count"] == 1
    for key in ("llm_sec", "login_sec", "guard_and_query_sec", "total_sec"):
        assert key in body["timings"], key
    assert body["tokens"]["prompt_eval_count"] == 8_000

    sent = model.requests[-1]
    assert QUESTION in sent["prompt"]
    assert role not in sent["prompt"], "the model must not be told who is asking"


@pytest.mark.parametrize("sql", [
    "SELECT * FROM core.dim_client",
    "WITH dim_client AS (SELECT 1) SELECT * FROM core.dim_client",
    "SELECT 1 FROM ai.client; DROP TABLE core.dim_client",
    "SELECT sec.verify_second_factor('000000')",
    "SET ROLE cro_global",
])
def test_unsafe_model_sql_is_refused_before_the_database(
    base_url: str, sessions: dict[str, str], model: fake_ollama.FakeOllama, sql: str,
) -> None:
    """The guard's refusal is the answer; no rows and no login are spent."""
    model.answers(sql)
    body = ask(base_url, sessions["client_3763"])
    assert body["stage"] == "guard", body
    assert body["guard"]["allowed"] is False
    assert body["guard"]["violations"]
    assert "rows" not in body
    assert "login_sec" not in body["timings"]


def test_an_unreachable_model_is_reported_not_invented(
    base_url: str, sessions: dict[str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No runtime: no SQL, no guard, a typed reason."""
    monkeypatch.setattr(config, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(config, "OLLAMA_HOST", fake_ollama.closed_port_url())
    body = ask(base_url, sessions["client_3763"])
    assert body["stage"] == "llm"
    assert body["error_kind"] == "runtime_unavailable"
    assert "sql" not in body and "guard" not in body


def test_a_missing_model_is_reported_with_the_fix(
    base_url: str, sessions: dict[str, str], model: fake_ollama.FakeOllama,
) -> None:
    """The page tells the operator which model to pull."""
    model.status = 404
    model.body = {"error": f"model '{fake_ollama.MODEL}' not found, try pulling it first"}
    body = ask(base_url, sessions["client_3763"])
    assert body["stage"] == "llm"
    assert body["error_kind"] == "model_missing"
    assert "ollama pull" in body["error"]


def test_prose_instead_of_json_stops_at_the_parse_step(
    base_url: str, sessions: dict[str, str], model: fake_ollama.FakeOllama,
) -> None:
    """A model that chats instead of answering produces no SQL."""
    model.body = fake_ollama.generate_payload("Sure! You have lots of clients.")
    body = ask(base_url, sessions["client_3763"])
    assert body["stage"] == "parse"
    assert body["error_kind"] == "malformed_output"
    assert "sql" not in body


def test_an_empty_model_answer_is_not_an_answer(
    base_url: str, sessions: dict[str, str], model: fake_ollama.FakeOllama,
) -> None:
    """Empty output is a model failure, reported as one."""
    model.body = fake_ollama.generate_payload("")
    body = ask(base_url, sessions["client_3763"])
    assert body["stage"] == "llm"
    assert body["error_kind"] == "empty_response"


def test_health_says_whether_the_local_model_is_ready(
    base_url: str, model: fake_ollama.FakeOllama,
) -> None:
    """The page can tell before anyone asks."""
    _status, body = get(f"{base_url}/api/health")
    assert body["llm"] == "ollama" and body["llm_ready"] is True

    model.models = []
    _status, body = get(f"{base_url}/api/health")
    assert body["llm_ready"] is False
    assert "ollama pull" in body["llm_detail"]
