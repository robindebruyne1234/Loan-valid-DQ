"""Tests for the walkthrough's HTTP surface.

This is the one part of the project that faces the internet, so the tests
here are weighted towards what a visitor must *not* be able to do: name a
role that is not a persona, reach a file outside ``web/``, run a query
without logging in, or have anything they typed reach SQL.

The happy path is tested too, but it is the cheaper half: if the tour steps
break, a person looking at the page notices immediately. If the persona
allowlist breaks, nobody notices at all.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from src import config, webapp


@pytest.fixture(scope="module")
def base_url() -> str:
    """Run the app on an ephemeral port for the duration of the module.

    :yields: The base URL.
    """
    server = ThreadingHTTPServer(("127.0.0.1", 0), webapp.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def get(url: str) -> tuple[int, dict]:
    """GET a URL, returning the status and the decoded body.

    :param url: Absolute URL.
    :returns: ``(status, payload)``; the payload is ``{}`` for non-JSON.
    """
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            return exc.code, json.loads(body or b"{}")
        except ValueError:
            return exc.code, {}


def post(url: str, payload: dict, timeout: int = 60) -> tuple[int, dict]:
    """POST JSON to a URL.

    :param url: Absolute URL.
    :param payload: The body.
    :param timeout: Seconds.
    :returns: ``(status, payload)``.
    """
    request = urllib.request.Request(
        url, method="POST", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


# ---------------------------------------------------------------------------
# What a visitor must not be able to do
# ---------------------------------------------------------------------------

#: Roles that exist in the database but are not personas, plus outright
#: nonsense. None may be usable through the API.
FORBIDDEN_ROLES = ("berka_owner", "postgres", "cro_global", "ai_consumer",
                   "", "../admin_demo", "admin_demo; DROP TABLE core.dim_client")


@pytest.mark.parametrize("role", FORBIDDEN_ROLES)
@pytest.mark.parametrize("endpoint", ["peek", "code"])
def test_only_personas_can_be_named(base_url: str, endpoint: str, role: str) -> None:
    """The role a request names must come from the allowlist or be refused.

    ``cro_global`` is in the list deliberately: it is a real, fully entitled
    login that the walkthrough does not offer. A request naming it must be
    refused for being absent from PERSONAS, not accepted for existing.
    """
    status, body = post(f"{base_url}/api/{endpoint}", {"role": role})
    assert status == 400, f"{endpoint} accepted role {role!r}"
    assert body.get("error") == "unknown persona"


def test_the_persona_list_excludes_the_pipeline_owner(base_url: str) -> None:
    """The owner is exempt from every policy; it must never be offerable."""
    _status, body = get(f"{base_url}/api/tour")
    roles = {p["role"] for p in body["personas"]}
    assert config.PGUSER not in roles
    assert "postgres" not in roles
    assert roles <= set(config.DEMO_USERS), "a persona names a role that does not exist"


def test_asking_without_logging_in_is_refused(base_url: str) -> None:
    """No session, no query -- even with a valid-looking question."""
    status, body = post(f"{base_url}/api/ask",
                        {"question": "How many clients are there?"})
    assert status == 401
    assert "log in" in body.get("error", "").lower()


@pytest.mark.parametrize("role", ["admin_demo", "client_3763", "rm_north"])
def test_naming_a_persona_does_not_replace_logging_in_as_one(base_url: str, role: str) -> None:
    """A valid persona name is not a session.

    ``/api/ask`` once accepted ``{"role": ...}`` in place of a session, which
    let a request skip the two-step login and ask as the administrator.
    """
    status, body = post(f"{base_url}/api/ask",
                        {"role": role, "question": "How many clients are there?"})
    assert status == 401, f"asked as {role} without logging in"
    assert "log in" in body.get("error", "").lower()


def test_a_forged_session_token_is_refused(base_url: str) -> None:
    """A made-up token must not resolve to a persona."""
    status, _body = post(f"{base_url}/api/ask",
                         {"session": "not-a-real-token", "question": "How many clients?"})
    assert status == 401


@pytest.mark.parametrize("question", [
    "",
    "ab",
    "x" * 301,
    "SELECT * FROM stg.client; -- \x00",
    "drop\ntable\tcore.dim_client",
])
def test_malformed_questions_are_refused_before_the_model(
    base_url: str, question: str
) -> None:
    """Junk is rejected at the edge, so it never reaches a prompt.

    Not a security control -- the guard and the policies are -- but the edge
    is the cheapest place to stop an empty or enormous request.
    """
    status, _body = post(f"{base_url}/api/ask",
                         {"session": "x", "question": question})
    assert status in (400, 401)


@pytest.mark.parametrize("path", [
    "/../src/config.py",
    "/..%2f..%2fsrc/config.py",
    "/../../etc/passwd",
    "/web/../src/auth.py",
])
def test_static_files_outside_the_web_directory_are_not_served(
    base_url: str, path: str
) -> None:
    """The static handler must not escape ``web/``."""
    status, _body = get(base_url + path)
    assert status == 404, f"{path} was served"


def test_a_six_digit_code_is_required(base_url: str) -> None:
    """The login must not pass arbitrary text to the verifier."""
    for code in ("", "abc", "12345", "1234567", "12 34 56"):
        status, body = post(f"{base_url}/api/login",
                            {"role": "client_3763", "code": code})
        assert status == 400, f"code {code!r} was accepted"
        assert "six digits" in body.get("error", "")


# ---------------------------------------------------------------------------
# That it also works
# ---------------------------------------------------------------------------


def test_health_reports_the_pipeline(base_url: str) -> None:
    """The page needs to know whether there is anything to show."""
    status, body = get(f"{base_url}/api/health")
    assert status == 200
    assert body["database"] is True
    assert body["clients"] == config.REFERENCE_ROW_COUNTS["client"]


@pytest.mark.parametrize("step_id", ["bronze", "silver-clean", "silver-grade",
                                     "gold", "access"])
def test_every_data_step_returns_something(base_url: str, step_id: str) -> None:
    """Each tour step must read the live database and come back populated."""
    status, body = get(f"{base_url}/api/step/{step_id}")
    assert status == 200
    assert body["id"] == step_id
    assert body["data"], f"step {step_id} returned no data"


def test_the_gold_step_shows_a_balanced_reconciliation(base_url: str) -> None:
    """A regression guard: this query once matched the wrong run and was empty."""
    _status, body = get(f"{base_url}/api/step/gold")
    rows = body["data"]["reconciliation"]
    assert rows, "the reconciliation panel is empty"
    assert all(r["is_balanced"] for r in rows)
    assert all(r["core_value"] is not None for r in rows)


def test_the_password_alone_reaches_nothing_through_the_api(base_url: str) -> None:
    """The headline claim, as the page demonstrates it."""
    status, body = post(f"{base_url}/api/peek", {"role": "admin_demo"})
    assert status == 200
    assert body["verified"] is False
    assert body["reach"] == {"clients": 0, "accounts": 0, "loans": 0, "transactions": 0}


def test_a_full_login_reaches_exactly_that_persona(base_url: str) -> None:
    """Both factors over HTTP, then the reach the policies allow."""
    from src import auth  # noqa: PLC0415

    code = auth.demo_fresh_code("client_3763")
    status, body = post(f"{base_url}/api/login", {"role": "client_3763", "code": code})
    assert status == 200, body
    assert body["session"]
    assert body["reach"]["clients"] == 1
    assert body["entitlement"]["portfolios"] == "SELF:3763"
    assert [r["client_id"] for r in body["sample"]] == [3763]


def test_an_unknown_step_is_a_404(base_url: str) -> None:
    """A step id from the URL must not reach anything."""
    status, _body = get(f"{base_url}/api/step/../../etc/passwd")
    assert status == 404
