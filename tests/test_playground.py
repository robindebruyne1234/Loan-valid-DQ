"""Tests for the localhost playground (src/playground.py, /api/play/*).

Weighted, like the walkthrough's tests, towards what must not happen: the
playground existing on a server started without it, or on a public address;
a role or model outside the allowlists; an answer appearing when no model was
asked. The happy paths that reach the database are tested too -- the guard and
the row level security through the playground's own routes -- but never a paid
model call: the tests swap the model for provider ``none``.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from src import config, llm_client, playground, webapp


def _serve(play: bool) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), webapp.Handler)
    server.playground = play  # type: ignore[attr-defined]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


@pytest.fixture(scope="module")
def play_url() -> str:
    """A server started with ``--playground``.

    :yields: Its base URL.
    """
    server, url = _serve(True)
    try:
        yield url
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(scope="module")
def public_url() -> str:
    """A server started without it, as ``make web`` does.

    :yields: Its base URL.
    """
    server, url = _serve(False)
    try:
        yield url
    finally:
        server.shutdown()
        server.server_close()


def call(url: str, payload: dict | None = None, timeout: int = 120) -> tuple[int, dict]:
    """GET (no payload) or POST JSON; return the status and the decoded body.

    :param url: Absolute URL.
    :param payload: Body for a POST.
    :param timeout: Seconds.
    :returns: ``(status, payload)``.
    """
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="GET" if data is None else "POST",
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            return response.status, (json.loads(body) if body[:1] in (b"{", b"[") else {})
    except urllib.error.HTTPError as exc:
        body = exc.read()
        return exc.code, (json.loads(body) if body[:1] == b"{" else {})


@pytest.fixture
def no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every playground model at provider ``none``: no call, no cost."""
    patched = {k: {**v, "provider": "none"} for k, v in playground.MODELS.items()}
    monkeypatch.setattr(playground, "MODELS", patched)


# ---------------------------------------------------------------------------
# Where it may exist
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path,payload", [
    ("/api/play/health", None), ("/api/play/setup", None), ("/api/play/pack", None),
    ("/api/play/guard", {"sql": "SELECT 1"}),
    ("/api/play/ask", {"question": "How many clients?", "role": "cro_global"}),
    ("/api/play/everyone", {"sql": "SELECT count(*) FROM ai.client"}),
    ("/api/play/suite", {"suite": "core", "ids": ["Q3"]}),
])
def test_the_playground_does_not_exist_on_a_public_server(public_url: str, path: str, payload: dict | None) -> None:
    status, body = call(public_url + path, payload)
    assert status == 404
    assert body == {"error": "not found"}


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "example.org"])
def test_the_playground_refuses_to_start_on_a_non_loopback_address(host: str) -> None:
    assert webapp.main(["--playground", "--host", host, "--port", "0"]) == 2


def test_the_page_is_served(play_url: str) -> None:
    with urllib.request.urlopen(play_url + "/play", timeout=30) as response:
        assert response.status == 200
        assert "Claude Playground" in response.read().decode("utf-8")


# ---------------------------------------------------------------------------
# Allowlists
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("role", ["berka_owner", "postgres", "ai_consumer", "../cro_global",
                                  "rm_north; DROP TABLE core.dim_client"])
def test_only_listed_personas_can_be_used(play_url: str, role: str) -> None:
    status, body = call(play_url + "/api/play/guard", {"sql": "SELECT count(*) FROM ai.client", "role": role})
    assert status == 400 and "unknown persona" in body["error"]
    status, body = call(play_url + "/api/play/ask", {"question": "How many clients?", "role": role})
    assert status == 400 and "unknown persona" in body["error"]


def test_the_pipeline_owner_is_not_a_persona() -> None:
    assert config.PGUSER not in playground.PERSONA_ROLES


@pytest.mark.parametrize("model", ["gpt-4", "claude-sonnet-5-5", "--dangerously-skip-permissions"])
def test_only_listed_models_can_be_asked(play_url: str, model: str) -> None:
    status, body = call(play_url + "/api/play/ask", {"question": "How many clients?", "role": "cro_global", "model": model})
    assert status == 400 and "unknown model" in body["error"]


@pytest.mark.parametrize("question", ["", "hi", "x" * (playground.MAX_QUESTION + 1)])
def test_questions_are_length_capped(play_url: str, question: str) -> None:
    status, _ = call(play_url + "/api/play/ask", {"question": question, "role": "cro_global"})
    assert status == 400


# ---------------------------------------------------------------------------
# The layers, through the playground
# ---------------------------------------------------------------------------

def test_health_reports_the_pipeline(play_url: str) -> None:
    status, body = call(play_url + "/api/play/health")
    assert status == 200 and body["database"] is True
    assert body["clients"] == 5369 and body["policies"] >= 7 and body["pack_chars"] > 1000


@pytest.mark.parametrize("sql", [
    "DELETE FROM ai.loan", "SELECT 1; DROP TABLE core.dim_client", "SELECT * FROM sec.principal",
    "WITH client AS (SELECT * FROM core.dim_client) SELECT count(*) FROM client",
])
def test_the_guard_refuses_and_nothing_runs(play_url: str, sql: str) -> None:
    status, body = call(play_url + "/api/play/guard", {"sql": sql, "role": "cro_global"})
    assert status == 200 and body["guard"]["allowed"] is False
    assert body["rows"] == [] and body["row_count"] is None


def test_one_statement_gives_each_persona_its_own_answer(play_url: str) -> None:
    status, body = call(play_url + "/api/play/everyone", {"sql": "SELECT count(*) AS n FROM ai.client"})
    assert status == 200 and body["guard"]["allowed"]
    counts = {r["role"]: r["rows"][0]["n"] for r in body["runs"]}
    assert counts["cro_global"] == 5369
    assert counts["rm_north"] == 1481 and counts["rm_south"] == 1387
    assert counts["rm_unassigned"] == 0
    assert counts["client_3763"] == counts["client_3764"] == counts["client_11409"] == 1


def test_postgres_not_the_guard_stops_a_server_setting(play_url: str) -> None:
    """LOW-1, shown live: the blocklist lets it through, the role does not."""
    status, body = call(play_url + "/api/play/guard",
                        {"sql": "SELECT current_setting('data_directory')", "role": "rm_north"})
    assert status == 200 and body["guard"]["allowed"] is True
    assert "permission denied" in (body["error"] or "")


def test_no_model_means_no_answer(play_url: str, no_model: None) -> None:
    status, body = call(play_url + "/api/play/ask", {"question": "What share of loans are problematic?", "role": "rm_north"})
    assert status == 200
    assert body["stage"] == "llm" and body["executed"] is False
    assert "rows" not in body and "sql" not in body
    assert body["attempts"][0]["cost_usd"] == 0.0


def test_a_suite_run_without_a_model_is_not_executed_not_invented(no_model: None) -> None:
    job = playground.start_suite("core", ["Q3"], "sonnet")
    deadline = time.time() + 60
    while (state := playground.job_summary(job["id"]))["status"] == "running" and time.time() < deadline:
        time.sleep(0.2)
    assert state["status"] == "finished"
    assert [r["verdict"] for r in state["results"]] == ["not_executed"]
    assert state["results"][0]["rows"] == []


def test_unknown_suite_questions_are_refused() -> None:
    with pytest.raises(playground.PlaygroundError):
        playground.start_suite("core", ["Q99"], "sonnet")


# ---------------------------------------------------------------------------
# The bare CLI call
# ---------------------------------------------------------------------------

def _fake_cli(monkeypatch: pytest.MonkeyPatch, path: str, help_text: str) -> list[list[str]]:
    calls: list[list[str]] = []

    def run(cmd, **_kwargs):
        calls.append(list(cmd))
        if cmd[1:] == ["--help"]:
            return SimpleNamespace(returncode=0, stdout=help_text, stderr="")
        return SimpleNamespace(returncode=0, stdout=json.dumps({"result": "{}", "is_error": False}), stderr="")

    monkeypatch.setattr(llm_client.shutil, "which", lambda _name: path)
    monkeypatch.setattr(llm_client.subprocess, "run", run)
    return calls


def test_the_cli_is_called_with_no_tools_when_it_supports_that(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_cli(monkeypatch, "/fake/new/claude",
                      "--tools <tools...>\n--disable-slash-commands\n--no-session-persistence\n")
    llm_client.call_claude_cli("prompt", "claude-sonnet-5-5", 30)
    command = calls[-1]
    assert command[command.index("--tools") + 1] == ""
    assert "--disable-slash-commands" in command and "--no-session-persistence" in command
    assert "--disallowedTools" in command  # kept as a second lock


def test_an_older_cli_gets_no_flags_it_would_reject(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_cli(monkeypatch, "/fake/old/claude", "--disallowedTools <tools...>\n")
    llm_client.call_claude_cli("prompt", "claude-sonnet-5-5", 30)
    command = calls[-1]
    assert "--tools" not in command and "--disable-slash-commands" not in command
    assert "--disallowedTools" in command


def test_usage_is_summed_whatever_the_provider_reports() -> None:
    cli = {"usage": {"input_tokens": 2, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 50,
                     "output_tokens": 7}, "total_cost_usd": 0.01}
    assert webapp.usage_summary(cli) == {"cost_usd": 0.01, "input_tokens": 152, "output_tokens": 7}
    assert webapp.usage_summary({}) == {"cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0}
    assert webapp.usage_summary(None)["cost_usd"] == 0.0


def test_subprocess_is_real_outside_the_fakes() -> None:
    """Guard against a fake leaking out of the tests above."""
    assert llm_client.subprocess.run is subprocess.run
