"""Tests for the kitchen view (src/kitchen.py): what the app does, step by step.

The kitchen observes the real code path, so the tests drive the real path with
a scripted model (no paid call) and check two things: that every layer shows
up with what it actually decided -- identity, entitlement, the views and the
policies behind them, the RLS effect -- and that watching never changes an
outcome, including when the observer itself breaks.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from typing import Any

import pytest

from src import auth, config, kitchen, llm_client, playground, run_questions, webapp
from tests import support

QUESTION = "What share of loans are problematic?"
SQL = ("SELECT round(100.0 * count(*) FILTER (WHERE is_problematic) / count(*), 2) "
       "AS problematic_loan_share FROM ai.loan")
IR = {"metric": "problematic_loan_share", "entity": "ai.loan", "counting_grain": "loan_id",
      "time": None, "group_by": [], "filters": [], "order": None, "limit": None}


def _reply(sql: str, ir: Any = IR) -> str:
    return json.dumps({"sql": sql, "ir": ir, "reasoning": "scripted", "assumptions": [], "caveats": []})


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> dict[str, Any]:
    """A scripted model, logins reusing the test sessions, logs in an ignored scratch directory."""
    logs = config.PROJECT_ROOT / "scratch" / "pytest_llm_logs" / request.node.name
    shutil.rmtree(logs, ignore_errors=True)
    logs.mkdir(parents=True)
    request.addfinalizer(lambda: shutil.rmtree(logs, ignore_errors=True))
    for role in ("cro_global", "rm_north", "client_3764"):
        with support.consumer(role):
            pass                                   # log in once, before login is redirected
    logins: list[str] = []

    @contextmanager
    def reuse_session(role: str, demo_autocode: bool = False) -> Iterator[Any]:
        logins.append(role)
        with support.consumer(role) as conn:
            yield conn

    monkeypatch.setattr(auth, "login", reuse_session)
    monkeypatch.setattr(config, "LLM_LOG_DIR", logs)
    replies: list[str] = []

    def complete(prompt: str, provider: str | None = None, model: str | None = None) -> llm_client.LLMResponse:
        return llm_client.LLMResponse(provider="scripted", model=model or "scripted", executed=True,
                                      text=replies.pop(0), user_prompt=prompt, duration_sec=0.01,
                                      usage={"usage": {"input_tokens": 10, "output_tokens": 5},
                                             "total_cost_usd": 0.001})

    monkeypatch.setattr(llm_client, "complete", complete)
    return {"replies": replies, "logins": logins}


def _by_id(steps: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {s["id"]: s for s in steps}


def test_a_served_question_shows_every_layer(scripted: dict[str, Any]) -> None:
    scripted["replies"].append(_reply(SQL))
    result = playground.ask(QUESTION, "rm_north", "sonnet")
    assert result["stage"] == "done"
    steps = result["kitchen"]
    order = [s["id"] for s in steps]
    assert order == ["received", "prompt-1", "a-prompt-1", "llm-1", "a-reply-1", "parse-1", "a-checks-1",
                     "guard-1", "intent-1", "a-login-1", "login-1", "ent-1", "views-1", "plan-1", "exec-1",
                     "recompute-1", "a-rows-1", "answer"]
    s = _by_id(steps)
    assert all(x["status"] == "pass" for x in steps if x["kind"] == "step")
    assert {x["lane"] for x in steps if x["kind"] == "step"} == set(kitchen.LANES)
    # what Claude chose, and that the guard allowed it
    assert s["guard-1"]["chips"] == [{"text": "ai.loan", "ok": True}]
    # who is asking, and what they may see
    assert "session_user = rm_north" in s["login-1"]["lines"]
    assert any("1,481 clients" in line for line in s["ent-1"]["lines"])
    # the view, the tables and the policies behind it
    assert any(c["text"] == "entitled_loans on core.fact_loan" for c in s["views-1"]["chips"])
    assert any("core.fact_loan" in line for line in s["views-1"]["lines"])
    # the effect of row level security
    assert "ai.loan: 179 of 682 rows visible" in s["exec-1"]["lines"]
    # the prompt never carries the identity
    assert "rm_north" not in s["prompt-1"]["detail"]["code"]


def test_a_refused_statement_never_reaches_the_database(scripted: dict[str, Any]) -> None:
    scripted["replies"] += [_reply("DELETE FROM ai.loan"), _reply("DELETE FROM ai.loan")]
    result = playground.ask("Delete every problematic loan.", "client_3764", "sonnet")
    s = _by_id(result["kitchen"])
    assert s["guard-1"]["status"] == "fail" and s["guard-2"]["status"] == "fail"
    assert s["never-1"]["status"] == "skip" and s["never-2"]["status"] == "skip"
    assert s["a-retry-1"]["kind"] == "arrow"
    assert s["answer"]["status"] == "fail"
    assert not any(x["id"].startswith("login-") for x in result["kitchen"])
    assert scripted["logins"] == []
    assert "rows" not in result


def test_a_meaning_refusal_is_shown_at_the_intent_check(scripted: dict[str, Any]) -> None:
    wrong_ir = {**IR, "filters": [{"column": "is_problematic", "op": "=", "value": True}]}
    scripted["replies"] += [_reply(SQL, wrong_ir), _reply(SQL, wrong_ir)]
    result = playground.ask(QUESTION, "rm_north", "sonnet")
    s = _by_id(result["kitchen"])
    assert s["guard-1"]["status"] == "pass"
    assert s["intent-1"]["status"] == "fail"
    assert any(not ok for ok, _ in s["intent-1"]["detail"]["checks"])
    assert scripted["logins"] == []


def test_watching_never_changes_the_outcome(scripted: dict[str, Any]) -> None:
    def boom(name: str, data: dict[str, Any]) -> None:
        raise RuntimeError(f"observer broke on {name}")

    verdict, verification = run_questions.verify_and_execute(SQL, IR, QUESTION, "cro_global", boom)
    _plain_verdict, plain = run_questions.verify_and_execute(SQL, IR, QUESTION, "cro_global")
    assert verdict.allowed and verification.ok
    assert verification.rows == plain.rows and verification.checks == plain.checks


def test_the_live_endpoint_lets_the_page_watch(scripted: dict[str, Any]) -> None:
    scripted["replies"].append(_reply(SQL))
    server = ThreadingHTTPServer(("127.0.0.1", 0), webapp.Handler)
    server.playground = True  # type: ignore[attr-defined]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        request = urllib.request.Request(base + "/api/play/ask_live", method="POST",
                                         data=json.dumps({"question": QUESTION, "role": "rm_north"}).encode(),
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as response:
            first = json.loads(response.read())
        deadline = time.time() + 60
        while True:
            with urllib.request.urlopen(f"{base}/api/play/live/{first['id']}", timeout=30) as response:
                state = json.loads(response.read())
            if state["done"] or time.time() > deadline:
                break
            time.sleep(0.1)
        assert state["done"] and state["result"]["stage"] == "done"
        assert state["steps"][-1]["id"] == "answer"
        assert state["version"] >= first["version"]
    finally:
        server.shutdown()
        server.server_close()


def test_an_unknown_live_id_is_refused() -> None:
    assert playground.handle("GET", "/api/play/live/nope", {})[0] == 400


def test_parse_shape_names_tables_not_ctes() -> None:
    shape = kitchen.parse_shape("WITH x AS (SELECT * FROM ai.loan) SELECT count(*) FROM x JOIN ai.account a ON true")
    assert shape["tables"] == ["ai.account", "ai.loan"] and shape["statements"] == 1
    assert kitchen.parse_shape("SELECT 1; SELECT 2")["statements"] == 2
    assert kitchen.parse_shape("SELECT * FROM sec.principal")["tables"] == ["sec.principal"]


def test_the_catalog_maps_ai_loan_to_its_tables_and_policies() -> None:
    profile = kitchen.view_profile("ai.loan")
    assert profile["security_invoker"] is True
    assert "core.fact_loan" in profile["tables"]
    assert any(p["policy"] == "entitled_loans" and "sec.v_my_accounts" in p["keyed_on"] for p in profile["policies"])
    assert profile["total"] == 682


@pytest.mark.parametrize("name", ["ai.nope", "sec.principal", "ai.loan; DROP TABLE core.dim_client"])
def test_the_catalog_reads_only_real_ai_views(name: str) -> None:
    profile = kitchen.view_profile(name)
    assert profile["tables"] == [] and profile["total"] is None
