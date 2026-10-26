"""A guided walkthrough of the data product, served over HTTP.

Everything this project does happens on a console, which makes it hard to
show and easy to disbelieve. This serves the same pipeline as a page you can
click through: the raw text that arrives, what the cleaning does to it, how a
defect is graded, the published model, who may read it, and finally a real
question answered by a real model under the real entitlement filter.

**It is a window onto the pipeline, not a second implementation.** Every step
reads the live database, the login is :mod:`src.auth`, the generated SQL goes
through :mod:`src.sql_guard`, and the answer is produced on a connection
authenticated as whichever persona the visitor chose. Nothing is precomputed
and nothing is faked; if the pipeline has not been built, the page says so
rather than showing a plausible picture of a database that is not there.

Two rules shape the code, both because this is the one part of the project
that faces the internet:

* **No visitor input is ever interpolated into SQL.** The tour's queries are
  constants. The only free text a visitor can send is a question for the
  model, and that path runs through the guard and then onto a low-privilege
  connection, where the policies apply whatever the model wrote.
* **The owner connection never serves a visitor's query.** The tour needs to
  read ``raw`` and ``stg``, which only the owner can; those reads are fixed
  statements with no parameters from the request. Everything a visitor can
  influence runs as a consumer.

Run it with ``make web``. See docs/DEPLOYMENT.md for putting it on a host.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import threading
import time
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import psycopg

from src import auth, config, db, llm_client, sql_guard

LOGGER = db.setup_logging("web")

WEB_DIR = config.PROJECT_ROOT / "web"

#: Personas a visitor may become. An allowlist, not a lookup: the role name
#: reaches `auth.login`, so it must never be whatever the request said.
PERSONAS: tuple[dict[str, str], ...] = (
    {"role": "client_3763", "name": "Klara",
     "kind": "Customer", "blurb": "Owns account 3112."},
    {"role": "client_3764", "name": "Petr",
     "kind": "Customer",
     "blurb": "Owns nothing. May OPERATE Klara's account."},
    {"role": "client_11409", "name": "Marie",
     "kind": "Customer", "blurb": "Unrelated to the other two."},
    {"role": "rm_north", "name": "Eva",
     "kind": "Relationship manager", "blurb": "Holds the northern book."},
    {"role": "rm_unassigned", "name": "Tomas",
     "kind": "New employee", "blurb": "Granted nothing yet."},
    {"role": "admin_demo", "name": "Administrator",
     "kind": "Administrator", "blurb": "A book containing every client."},
)
PERSONA_ROLES = {p["role"] for p in PERSONAS}

#: How long a browser session may hold a logged-in persona before it must log
#: in again. Shorter than the database session so the page never holds a
#: handle to something the database has already forgotten.
SESSION_TTL_SECONDS = 15 * 60

#: Visitor sessions: token -> {role, expires}. In memory on purpose; this is a
#: demonstration, and a restart logging everyone out is the correct behaviour
#: for it.
_SESSIONS: dict[str, dict[str, Any]] = {}
_SESSION_LOCK = threading.Lock()

#: One question at a time, process-wide. A small model on a free-tier box is
#: the scarcest thing here, and letting three visitors start a generation at
#: once is how the instance falls over.
_ASK_LOCK = threading.Lock()


class PipelineNotBuilt(RuntimeError):
    """Raised when the database has not been through ``make build``."""


# ---------------------------------------------------------------------------
# Reading the pipeline. Every statement here is a constant.
# ---------------------------------------------------------------------------


def _owner_rows(sql: str, params: tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
    """Run a FIXED statement as the pipeline owner.

    :param sql: A constant defined in this module. Never request-derived.
    :param params: Bound parameters, themselves from module constants.
    :returns: The rows.
    :raises PipelineNotBuilt: When the schemas are missing.
    """
    try:
        with db.connect() as conn:
            return db.fetch_all(conn, sql, params)
    except psycopg.errors.UndefinedTable as exc:
        raise PipelineNotBuilt(str(exc).splitlines()[0]) from exc
    except psycopg.OperationalError as exc:
        raise PipelineNotBuilt(f"cannot reach the database: {str(exc).splitlines()[0]}") from exc


def step_bronze() -> dict[str, Any]:
    """Step 1: the lines of text the bank's files actually contain.

    :returns: The step payload.
    """
    client = _owner_rows(
        "SELECT _source_file, _source_row, client_id, birth_number, district_id "
        "FROM raw.client WHERE client_id = %s", (str(config.EXAMPLE_CLIENT_ID),))
    account = _owner_rows(
        'SELECT _source_file, _source_row, account_id, district_id, frequency, "date" '
        "FROM raw.account WHERE account_id = %s", ("9265",))
    loan = _owner_rows(
        'SELECT _source_file, _source_row, loan_id, account_id, "date", amount, '
        "duration, payments, status FROM raw.loan WHERE account_id = %s", ("9265",))
    audit = _owner_rows(
        """
        SELECT source_name, rows_loaded, rows_expected, counts_match,
               substr(file_sha256, 1, 16) AS sha256_head
        FROM raw.load_audit
        WHERE run_id = (SELECT run_id FROM raw.load_audit ORDER BY loaded_at DESC LIMIT 1)
        ORDER BY source_name
        """)
    return {
        "records": {"client": client, "account": account, "loan": loan},
        "audit": audit,
        "total_rows": sum(int(r["rows_loaded"]) for r in audit),
    }


def step_silver_clean() -> dict[str, Any]:
    """Step 2: what the cleaning does to that one client.

    :returns: The step payload.
    """
    return {
        "client": _owner_rows(
            "SELECT client_id, birth_number, birth_date, gender, birth_number_valid, "
            "district_id FROM stg.client WHERE client_id = %s",
            (config.EXAMPLE_CLIENT_ID,)),
        "account": _owner_rows(
            "SELECT account_id, frequency_code, frequency_label, open_date "
            "FROM stg.account WHERE account_id = %s", (9265,)),
        "loan": _owner_rows(
            "SELECT loan_id, loan_date, amount, duration_months, status_code, "
            "status_label, is_problematic FROM stg.loan WHERE account_id = %s", (9265,)),
        "postings": _owner_rows(
            "SELECT trans_id, trans_date, trans_type_code, trans_type_label, direction, "
            "amount, signed_amount, balance_after FROM stg.trans WHERE account_id = %s "
            "ORDER BY trans_date, trans_id LIMIT 4", (9265,)),
    }


def step_silver_grade() -> dict[str, Any]:
    """Step 3: the defects, their severity, and what each one costs.

    :returns: The step payload.
    """
    summary = _owner_rows(
        """
        SELECT severity, count(*) AS rules, sum(violation_count) AS rows_affected
        FROM dq.results
        WHERE run_id = (SELECT run_id FROM dq.run WHERE dataset = 'stg'
                        ORDER BY started_at DESC LIMIT 1)
          AND violation_count > 0
        GROUP BY severity ORDER BY severity
        """)
    fired = _owner_rows(
        """
        SELECT rule_id, dimension, target_table, severity, violation_count, total_count
        FROM dq.results
        WHERE run_id = (SELECT run_id FROM dq.run WHERE dataset = 'stg'
                        ORDER BY started_at DESC LIMIT 1)
          AND violation_count > 0
        ORDER BY CASE severity WHEN 'block' THEN 1 WHEN 'warn' THEN 2 ELSE 3 END,
                 violation_count DESC
        """)
    this_client = _owner_rows(
        """
        SELECT rule_id, severity, flag, reason FROM dq.flags
        WHERE target_schema = 'stg'
          AND ((target_table = 'client'  AND business_key = %s)
            OR (target_table = 'account' AND business_key = %s))
        ORDER BY rule_id
        """, (str(config.EXAMPLE_CLIENT_ID), "9265"))
    return {"summary": summary, "fired": fired, "this_client": this_client,
            "quarantined": _owner_rows(
                "SELECT count(*) AS n FROM dq.quarantine WHERE target_schema = 'stg'")[0]["n"]}


def step_gold() -> dict[str, Any]:
    """Step 4: the published model, and the same client inside it.

    :returns: The step payload.
    """
    tables = _owner_rows(
        """
        SELECT c.relname AS table_name, c.reltuples::bigint AS approx_rows,
               obj_description(c.oid) AS note
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'core' AND c.relkind = 'r'
        ORDER BY c.relname
        """)
    exact = _owner_rows(
        """
        SELECT 'dim_client' AS t, count(*) AS n FROM core.dim_client
        UNION ALL SELECT 'dim_account', count(*) FROM core.dim_account
        UNION ALL SELECT 'fact_loan', count(*) FROM core.fact_loan
        UNION ALL SELECT 'fact_transaction', count(*) FROM core.fact_transaction
        UNION ALL SELECT 'fact_account_month_end_balance', count(*)
                    FROM core.fact_account_month_end_balance
        """)
    counts = {r["t"]: int(r["n"]) for r in exact}
    for row in tables:
        if row["table_name"] in counts:
            row["approx_rows"] = counts[row["table_name"]]
    return {
        "tables": tables,
        "client": _owner_rows(
            "SELECT client_id, client_ref, birth_date, gender, _dq_flags "
            "FROM core.dim_client WHERE client_id = %s", (config.EXAMPLE_CLIENT_ID,)),
        "account": _owner_rows(
            "SELECT account_id, account_ref, open_date, statement_frequency, _dq_flags "
            "FROM core.dim_account WHERE account_id = %s", (9265,)),
        # The core reconciliation is written by build_model under its own
        # run id, not the quality run's -- joining to dq.run by dataset
        # therefore finds only the raw-to-staging rows, which carry no
        # core_value. Pick the latest batch that actually has one.
        "reconciliation": _owner_rows(
            """
            SELECT metric, entity, stg_value, quarantined, core_value, is_balanced
            FROM dq.reconciliation
            WHERE run_id = (SELECT run_id FROM dq.reconciliation
                            WHERE core_value IS NOT NULL
                            ORDER BY checked_at DESC LIMIT 1)
            ORDER BY metric, entity LIMIT 10
            """),
    }


def step_access() -> dict[str, Any]:
    """Step 5: who may reach this client, and on what grounds.

    :returns: The step payload.
    """
    return {
        "who": _owner_rows(
            """
            SELECT DISTINCT db_role, user_type, permission, grant_source, reason, valid_to
            FROM sec.v_who_can_reach_client
            WHERE client_id = %s AND is_live
            ORDER BY grant_source, db_role, permission
            """, (config.EXAMPLE_OTHER_CLIENT_ID,)),
        "sources": _owner_rows(
            """
            SELECT grant_source, permission, count(*) AS n
            FROM sec.v_access_grant
            WHERE sec.grant_is_live(valid_from, valid_to)
            GROUP BY 1, 2 ORDER BY 1, 2
            """),
        "subject": config.EXAMPLE_OTHER_CLIENT_ID,
    }


#: ``(id, short label for the rail, full title, loader)``. The short label is
#: separate because two steps are both "Silver" and a rail that says so twice
#: tells a visitor nothing about where they are.
TOUR: tuple[tuple[str, str, str, Callable[[], dict[str, Any]]], ...] = (
    ("bronze", "Bronze · land it",
     "Bronze - what actually arrives", step_bronze),
    ("silver-clean", "Silver · clean it",
     "Silver - making every value mean one thing", step_silver_clean),
    ("silver-grade", "Silver · grade it",
     "Silver - grading what is still broken", step_silver_grade),
    ("gold", "Gold · model it",
     "Gold - the published model", step_gold),
    ("access", "Access · who, and why",
     "Access - who may read it, and why", step_access),
    ("login", "Log in · two steps",
     "Authentication - two steps, and what each stops", lambda: {}),
    ("ask", "Ask · the real thing",
     "Ask - a real question, under the real filter", lambda: {}),
)
TOUR_IDS = [step_id for step_id, _short, _title, _fn in TOUR]


# ---------------------------------------------------------------------------
# Becoming a persona: the same two steps as the console
# ---------------------------------------------------------------------------


def persona_state(role: str) -> dict[str, Any]:
    """What a persona can reach, read on a connection authenticated as them.

    :param role: A role from :data:`PERSONA_ROLES`, already validated.
    :returns: Their entitlement and reach, as the policies return it.
    """
    with auth.login(role, demo_autocode=True) as conn:
        entitlement = db.fetch_all(conn, "SELECT * FROM ai.my_entitlement")[0]
        reach = db.fetch_all(
            conn,
            """
            SELECT (SELECT count(*) FROM ai.client)      AS clients,
                   (SELECT count(*) FROM ai.account)     AS accounts,
                   (SELECT count(*) FROM ai.loan)        AS loans,
                   (SELECT count(*) FROM ai.transaction) AS transactions
            """)[0]
        sample = db.fetch_all(
            conn,
            "SELECT client_id, client_ref, gender, region FROM ai.client "
            "ORDER BY client_id LIMIT 5")
    return {"entitlement": entitlement, "reach": reach, "sample": sample}


def unauthenticated_reach(role: str) -> dict[str, Any]:
    """What the same role can reach with the password alone.

    This exists to be shown, not to be useful: it is the step that makes the
    second factor something a visitor can watch rather than be told about.

    :param role: A role from :data:`PERSONA_ROLES`, already validated.
    :returns: The counts, which should all be zero.
    """
    with db.connect(user=role, password=config.DEMO_USER_PASSWORD) as conn:
        verified = bool(db.fetch_value(conn, "SELECT sec.has_verified_session()"))
        reach = db.fetch_all(
            conn,
            """
            SELECT (SELECT count(*) FROM ai.client)      AS clients,
                   (SELECT count(*) FROM ai.account)     AS accounts,
                   (SELECT count(*) FROM ai.loan)        AS loans,
                   (SELECT count(*) FROM ai.transaction) AS transactions
            """)[0]
    return {"verified": verified, "reach": reach}


def issue_session(role: str) -> str:
    """Mint a browser session for a persona that has completed both factors.

    :param role: The authenticated role.
    :returns: An opaque token.
    """
    import secrets  # noqa: PLC0415

    token = secrets.token_urlsafe(24)
    with _SESSION_LOCK:
        now = time.time()
        for key, value in list(_SESSIONS.items()):
            if value["expires"] < now:
                del _SESSIONS[key]
        _SESSIONS[token] = {"role": role, "expires": now + SESSION_TTL_SECONDS}
    return token


def session_role(token: str | None) -> str | None:
    """Resolve a browser session token to a persona.

    :param token: The token the page sent, if any.
    :returns: The role, or ``None`` when absent or expired.
    """
    if not token:
        return None
    with _SESSION_LOCK:
        entry = _SESSIONS.get(token)
        if entry is None or entry["expires"] < time.time():
            _SESSIONS.pop(token, None)
            return None
        return str(entry["role"])


# ---------------------------------------------------------------------------
# Asking a question
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def context_pack() -> str:
    """The semantic layer, rendered once per process.

    :returns: The text the model is given, and the only thing it is given.
    """
    path = config.PROJECT_ROOT / "semantic" / "context_pack.md"
    if not path.exists():
        raise PipelineNotBuilt("semantic/context_pack.md is missing; run `make semantic`")
    return path.read_text(encoding="utf-8")


def load_questions() -> list[dict[str, str]]:
    """The ten questions from the brief.

    :returns: One dictionary per question.
    """
    from src.run_questions import load_questions as _load  # noqa: PLC0415

    return _load()


def ask(role: str, question: str) -> dict[str, Any]:
    """Put a question to the model and run its SQL as the chosen persona.

    The whole point of this function is the last clause. The model writes SQL
    with no knowledge of who is asking; the guard checks its shape; and it
    then executes on a connection that has passed two factors as this
    persona, so the row level security policies narrow the result to whatever
    that persona may see. A customer and their relationship manager get
    different, correct answers to the same words.

    :param role: A validated role from :data:`PERSONA_ROLES`.
    :param question: The visitor's question, in English.
    :returns: The prompt metadata, the generated SQL, the guard verdict and
        the rows, or an explanation of which step refused.
    """
    from src.run_questions import build_prompt, parse_model_output  # noqa: PLC0415

    started = time.time()
    prompt = build_prompt(context_pack(), "WEB", question)
    with _ASK_LOCK:
        response = llm_client.complete(prompt)
    # Audited exactly like a pipeline call: prompt, model, parameters and raw
    # response to disk. A question asked through a web page is no less a
    # model call than one asked by the question runner.
    #
    # Written under llm_logs/web/ rather than beside the pipeline's own logs:
    # those ten files are the evidence behind the Questions tab, and visitors
    # idly asking things should not be filed among them or overwrite them.
    # The ZIP's glob is not recursive, so this directory stays out of the
    # submission.
    try:
        (config.LLM_LOG_DIR / "web").mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
        llm_client.write_call_log(
            f"web/{stamp}-{role}", response,
            {"question": question, "as_role": role, "surface": "walkthrough"})
    except Exception:  # noqa: BLE001 - logging must never fail the request
        LOGGER.exception("could not write the call log")

    result: dict[str, Any] = {
        "question": question,
        "as_role": role,
        "provider": response.provider,
        "model": response.model,
        "executed": response.executed,
        "elapsed_sec": round(time.time() - started, 1),
        "raw_response": (response.text or "")[:4000],
    }
    if not response.executed:
        result["error"] = response.error or config.NOT_EXECUTED
        result["stage"] = "llm"
        return result

    parsed, parse_error = parse_model_output(response.text or "")
    if parsed is None:
        result["error"] = parse_error or "the model did not return the expected JSON"
        result["stage"] = "parse"
        return result

    sql = str(parsed.get("sql", "")).strip()
    result["sql"] = sql
    result["model_explanation"] = parsed.get("explanation")

    with auth.login(role, demo_autocode=True) as conn:
        verdict, rows, error = sql_guard.execute_guarded(conn, sql)
    result["guard"] = {
        "allowed": verdict.allowed,
        "violations": list(verdict.violations),
        "rewritten_sql": verdict.rewritten_sql,
    }
    if not verdict.allowed:
        result["stage"] = "guard"
        result["error"] = "; ".join(verdict.violations)
        return result
    if error:
        result["stage"] = "execute"
        result["error"] = error
        return result

    result["stage"] = "done"
    result["rows"] = [
        {k: _jsonable(v) for k, v in row.items()} for row in (rows or [])[:50]
    ]
    result["row_count"] = len(rows or [])
    return result


def _jsonable(value: Any) -> Any:
    """Make a database value JSON-safe.

    :param value: Any value from a cursor.
    :returns: Something ``json.dumps`` accepts.
    """
    from datetime import date, datetime, timedelta  # noqa: PLC0415
    from decimal import Decimal  # noqa: PLC0415

    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# The HTTP layer
# ---------------------------------------------------------------------------

#: Only these characters may appear in a question. Not a security control --
#: the guard and the policies are -- but it keeps obvious junk out of a
#: prompt and caps the size of what reaches a small model.
QUESTION_RE = re.compile(r"^[\w\s,.:;?!'\"()%/+\-–—£$€]{3,300}$", re.UNICODE)


class Handler(BaseHTTPRequestHandler):
    """Serves the page and a small JSON API."""

    server_version = "berka-walkthrough"
    sys_version = ""

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        """Route access logs through the project logger.

        :param fmt: Printf-style format.
        :param args: Its arguments.
        :returns: ``None``.
        """
        LOGGER.info("%s %s", self.address_string(), fmt % args)

    # -- helpers ----------------------------------------------------------

    def handle_one_request(self) -> None:
        """Serve one request, treating a vanished client as unremarkable.

        A browser that navigates away mid-response, or a proxy that times
        out, closes the socket under us. The default handler logs a traceback
        for that, which fills the log of a public demo with noise about
        something entirely normal.

        :returns: ``None``.
        """
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        """Write one response.

        :param status: HTTP status.
        :param body: Body bytes.
        :param content_type: MIME type.
        :returns: ``None``.
        """
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # This page embeds nothing and is embedded nowhere.
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:",
        )
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        """Write a JSON response.

        :param status: HTTP status.
        :param payload: The object to serialise.
        :returns: ``None``.
        """
        self._send(status, json.dumps(payload, default=str).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _body(self) -> dict[str, Any]:
        """Read and parse a JSON request body.

        :returns: The parsed object, or an empty dict.
        """
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 16_384:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def _persona(self, body: dict[str, Any]) -> str | None:
        """Resolve the persona for a request, by session or by explicit role.

        Always returns a value from the allowlist or ``None``. This is the
        only place a request can influence which role is used.

        :param body: The parsed request body.
        :returns: A valid role, or ``None``.
        """
        role = session_role(body.get("session"))
        if role:
            return role
        requested = body.get("role")
        return requested if requested in PERSONA_ROLES else None

    # -- routes -----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        """Serve the page, the static files and the read-only API.

        :returns: ``None``.
        """
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            return self._api_get(path)
        return self._static(path)

    def do_HEAD(self) -> None:  # noqa: N802
        """Answer HEAD the same way as GET, without a body.

        :returns: ``None``.
        """
        self.do_GET()

    def _api_get(self, path: str) -> None:
        """Handle the read-only endpoints.

        :param path: The request path.
        :returns: ``None``.
        """
        try:
            if path == "/api/health":
                return self._json(200, self._health())
            if path == "/api/tour":
                return self._json(200, {
                    "steps": [{"id": sid, "short": short, "title": title}
                              for sid, short, title, _fn in TOUR],
                    "personas": list(PERSONAS),
                    "example_client": config.EXAMPLE_CLIENT_ID,
                })
            if path == "/api/questions":
                return self._json(200, {"questions": load_questions()})
            if path.startswith("/api/step/"):
                step_id = path.rsplit("/", 1)[-1]
                for sid, _short, title, fn in TOUR:
                    if sid == step_id:
                        return self._json(200, {"id": sid, "title": title, "data": fn()})
                return self._json(404, {"error": f"no step {step_id!r}"})
        except PipelineNotBuilt as exc:
            return self._json(503, {
                "error": "pipeline_not_built",
                "detail": str(exc),
                "hint": "Run `make build` against this database, then reload.",
            })
        except Exception as exc:  # noqa: BLE001 - a demo must not 500 silently
            LOGGER.exception("GET %s failed", path)
            return self._json(500, {"error": type(exc).__name__, "detail": str(exc)[:300]})
        return self._json(404, {"error": "not found"})

    def _health(self) -> dict[str, Any]:
        """Report whether the pipeline and the model are actually there.

        :returns: The health payload.
        """
        state: dict[str, Any] = {"ok": False, "database": False, "llm": config.LLM_PROVIDER}
        try:
            rows = _owner_rows("SELECT count(*) AS n FROM core.dim_client")
            state["database"] = True
            state["clients"] = int(rows[0]["n"])
            state["ok"] = True
        except PipelineNotBuilt as exc:
            state["detail"] = str(exc)
        state["llm_configured"] = config.LLM_PROVIDER != "none"
        state["llm_model"] = config.LLM_MODEL
        return state

    def do_POST(self) -> None:  # noqa: N802
        """Handle the endpoints that do something.

        :returns: ``None``.
        """
        path = urlparse(self.path).path
        body = self._body()
        try:
            if path == "/api/peek":
                role = self._persona(body)
                if role is None:
                    return self._json(400, {"error": "unknown persona"})
                return self._json(200, unauthenticated_reach(role))

            if path == "/api/code":
                # The authenticator app, stood in for. Demo only, and the
                # page says so every time it shows one.
                requested = body.get("role")
                if requested not in PERSONA_ROLES:
                    return self._json(400, {"error": "unknown persona"})
                # Non-blocking: a code may be used once, so if this
                # principal already spent the current window the honest
                # answer is "wait", not a thirty-second hung request.
                code, wait = auth.demo_code_state(requested)
                if code is None:
                    return self._json(200, {
                        "role": requested, "code": None, "wait_seconds": wait,
                        "note": "That code has been used. A code works once, "
                                "even inside its own 30-second window -- "
                                "otherwise anyone who sees one can replay it.",
                    })
                return self._json(200, {
                    "role": requested,
                    "code": code,
                    "valid_for_seconds": auth.seconds_remaining(),
                    "note": "A real deployment never shows this. See docs/ACCESS_AND_AUTH.md.",
                })

            if path == "/api/login":
                requested = body.get("role")
                code = str(body.get("code") or "")
                if requested not in PERSONA_ROLES:
                    return self._json(400, {"error": "unknown persona"})
                if not re.fullmatch(r"\d{6}", code):
                    return self._json(400, {"error": "a one-time code is six digits"})
                try:
                    with db.connect(user=requested,
                                    password=config.DEMO_USER_PASSWORD) as conn:
                        auth.verify_second_factor(conn, code)
                except auth.AuthenticationError as exc:
                    return self._json(401, {"error": str(exc).split(": ", 1)[-1]})
                token = issue_session(requested)
                return self._json(200, {"session": token, "role": requested,
                                        **persona_state(requested)})

            if path == "/api/ask":
                role = self._persona(body)
                if role is None:
                    return self._json(401, {"error": "log in as a persona first"})
                question = str(body.get("question") or "").strip()
                if not QUESTION_RE.fullmatch(question):
                    return self._json(400, {
                        "error": "a question is 3 to 300 ordinary characters"})
                return self._json(200, ask(role, question))
        except PipelineNotBuilt as exc:
            return self._json(503, {"error": "pipeline_not_built", "detail": str(exc)})
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("POST %s failed", path)
            return self._json(500, {"error": type(exc).__name__, "detail": str(exc)[:300]})
        return self._json(404, {"error": "not found"})

    def _static(self, path: str) -> None:
        """Serve a file from ``web/``, and nothing outside it.

        :param path: The request path.
        :returns: ``None``.
        """
        relative = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (WEB_DIR / relative).resolve()
        if not str(target).startswith(str(WEB_DIR.resolve())) or not target.is_file():
            return self._send(404, b"not found", "text/plain; charset=utf-8")
        guessed, _ = mimetypes.guess_type(target.name)
        self._send(200, target.read_bytes(), guessed or "application/octet-stream")


def main(argv: list[str] | None = None) -> int:
    """Start the server.

    :param argv: Command-line arguments.
    :returns: Process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind address; 0.0.0.0 to accept from the network")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)

    health = Handler._health(Handler)  # type: ignore[arg-type]
    if not health.get("database"):
        LOGGER.warning("the pipeline is not built in this database -> %s",
                       health.get("detail", "unknown"))
        LOGGER.warning("the page will load and say so. Run `make build` to fix it.")
    else:
        LOGGER.info("database ok -> %s clients published", f"{health['clients']:,}")
    if not health.get("llm_configured"):
        LOGGER.warning("LLM_PROVIDER=none -> the Ask step will explain that rather "
                       "than inventing an answer")
    else:
        LOGGER.info("llm -> %s / %s", config.LLM_PROVIDER, config.LLM_MODEL)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    LOGGER.info("serving the walkthrough on http://%s:%d", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("stopping")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
