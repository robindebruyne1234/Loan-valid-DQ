"""The kitchen: what the app does with one question, step by step, as it happens.

The playground's Ask tab shows the answer; the kitchen shows the cooking. It is
an *observer* of the real code path -- :func:`src.webapp.ask` and
:func:`src.run_questions.verify_and_execute` call it at every stage boundary
(``on_event``) -- and turns those events into steps on four lanes:

``claude``  the model, through the local ``claude`` CLI (no API key)
``app``     this server: builds the prompt, reads the reply, keeps the log
``checks``  the guard (shape) and the intent check (meaning, D029)
``db``      PostgreSQL: the two-factor login, the entitlement, the views and
            the row level security policies behind them, plan, execute, recompute

**It watches; it never decides.** Every verdict on a step is the one the
pipeline reached. What the kitchen adds are *descriptions*: which tables a
statement names (the same sqlglot parse the guard uses), which ``core`` tables
and policies sit behind each ``ai`` view (the catalog), and -- after the
verdict, in its own read-only transaction on the persona's own connection --
who the session is and how many rows of each view that persona can see. If an
observation fails, the step says so and the answer is unaffected.
"""

from __future__ import annotations

import re
import secrets
import shutil
import threading
import time
from functools import lru_cache
from typing import Any

import psycopg
import sqlglot
from psycopg import sql as pgsql
from sqlglot import exp

from src import config, db, llm_client, sql_guard

LOGGER = db.setup_logging("kitchen")

LANES = ("claude", "app", "checks", "db")

#: The intent checker's stage keys (src/sql_ir.py), in words.
CHECK_TEXT: dict[str, str] = {
    "ir": "The intent (IR) is complete and names a certified metric",
    "columns": "Every column used exists in the semantic layer",
    "entity": "It counts the metric's own entity at the declared grain",
    "joins": "Every join is declared in the semantic layer and cannot fan out",
    "periods": "The date filter covers exactly the IR's period, day by day",
    "measure": "The measure is the certified expression for that metric",
    "grouping": "The GROUP BY matches the IR",
    "filters": "The filters match the IR",
    "limit": "Ordering and LIMIT match the IR",
    "guard": "The guard passes again on the database path",
    "plan": "PostgreSQL planned it (EXPLAIN) without error",
    "recompute": "Recomputed from the IR alone: the same numbers",
}

#: Guard violations, matched to the sub-check they belong to.
_GUARD_RULES = (
    ("statements", re.compile(r"exactly one statement", re.IGNORECASE)),
    ("select", re.compile(r"only SELECT|forbidden .* node|SELECT statements", re.IGNORECASE)),
    ("schema", re.compile(r"schema|qualified", re.IGNORECASE)),
    ("functions", re.compile(r"forbidden function", re.IGNORECASE)),
)


# ---------------------------------------------------------------------------
# Observations: descriptions read from the catalog and the session
# ---------------------------------------------------------------------------


def parse_shape(sql: str) -> dict[str, Any]:
    """What a statement names: statements, their kind, tables and functions.

    The same parser and dialect as the guard; used to *describe*, never to decide.

    :param sql: The statement.
    :returns: ``statements``, ``kinds``, ``tables`` (schema.name, CTEs excluded),
        ``functions``; ``error`` when it does not parse.
    """
    try:
        parsed = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except sqlglot.errors.ParseError as exc:
        return {"statements": 0, "kinds": [], "tables": [], "functions": [],
                "error": str(exc).splitlines()[0]}
    tables: set[str] = set()
    functions: set[str] = set()
    for statement in parsed:
        ctes = {c.alias_or_name.lower() for c in statement.find_all(exp.CTE)}
        for table in statement.find_all(exp.Table):
            name = (table.name or "").lower()
            if name and not (not table.db and name in ctes):
                tables.add(f"{(table.db or '?').lower()}.{name}")
        for fn in statement.find_all(exp.Anonymous, exp.Func):
            name = fn.name if isinstance(fn, exp.Anonymous) else fn.sql_name()
            if name:
                functions.add(name.lower())
    return {"statements": len(parsed), "kinds": [type(s).__name__.upper() for s in parsed],
            "tables": sorted(tables), "functions": sorted(functions)}


@lru_cache(maxsize=1)
def ai_views() -> frozenset[str]:
    """Every relation in the ``ai`` schema, as ``ai.name``.

    :returns: The names; an observation is only ever made on one of these.
    """
    with db.connect() as conn:
        rows = db.fetch_all(conn, "SELECT relname FROM pg_class WHERE relnamespace = 'ai'::regnamespace "
                                  "AND relkind IN ('v', 'm', 'r')")
    return frozenset(f"ai.{r['relname']}" for r in rows)


def _short_qual(qual: str) -> str:
    return re.sub(r"\s+", " ", qual or "").strip()


@lru_cache(maxsize=64)
def view_profile(view: str) -> dict[str, Any]:
    """Behind one ``ai`` view: its options, the base tables, their policies, its size.

    Read by the owner from the catalog (constant SQL, the view name as a
    parameter or a quoted identifier from :func:`ai_views`).

    :param view: ``ai.name``.
    :returns: ``security_invoker``, ``tables`` (base tables reached through any
        nested views), ``via`` (the views in between), ``policies`` and ``total``
        (rows the owner sees, i.e. before any row level security).
    """
    out: dict[str, Any] = {"view": view, "security_invoker": False, "tables": [], "via": [],
                           "policies": [], "total": None}
    if view not in ai_views():
        return out
    with db.connect() as conn:
        opts = db.fetch_value(conn, "SELECT coalesce(array_to_string(reloptions, ','), '') "
                                    "FROM pg_class WHERE oid = %s::regclass", (view,)) or ""
        out["security_invoker"] = "security_invoker=true" in opts or "security_invoker=on" in opts
        seen, todo = set(), [view]
        while todo:
            current = todo.pop()
            if current in seen:
                continue
            seen.add(current)
            for dep in db.fetch_all(conn, """
                    SELECT DISTINCT d.refobjid::regclass::text AS rel, t.relkind
                    FROM pg_rewrite r
                    JOIN pg_depend d ON d.objid = r.oid AND d.classid = 'pg_rewrite'::regclass
                                    AND d.refclassid = 'pg_class'::regclass
                    JOIN pg_class t ON t.oid = d.refobjid
                    WHERE r.ev_class = %s::regclass AND d.refobjid <> r.ev_class
                      AND t.relkind IN ('r', 'p', 'v', 'm')""", (current,)):
                if dep["relkind"] in ("v", "m"):
                    out["via"].append(dep["rel"])
                    todo.append(dep["rel"])
                elif dep["rel"] not in out["tables"]:
                    out["tables"].append(dep["rel"])
        out["tables"].sort()
        out["via"] = sorted(set(out["via"]))
        if out["tables"]:
            out["policies"] = [
                {"table": r["tbl"], "policy": r["policyname"], "roles": r["roles"],
                 "using": _short_qual(r["qual"]),
                 "keyed_on": sorted(set(re.findall(r"sec\.\w+", r["qual"] or "")))}
                for r in db.fetch_all(conn, """
                    SELECT schemaname || '.' || tablename AS tbl, policyname, roles::text AS roles, qual
                    FROM pg_policies WHERE schemaname || '.' || tablename = ANY(%s)
                    ORDER BY 1, 2""", (out["tables"],))]
        schema, name = view.split(".", 1)
        out["total"] = db.fetch_value(conn, pgsql.SQL("SELECT count(*) FROM {}.{}").format(
            pgsql.Identifier(schema), pgsql.Identifier(name)))
        conn.rollback()
    return out


def observe_session(conn: psycopg.Connection, views: list[str]) -> dict[str, Any]:
    """Describe the persona's session, on its own connection, after the verdict.

    Its own read-only transaction with a short timeout, so it can neither
    write nor hang; called only once the answer has been decided.

    :param conn: The persona's authenticated connection.
    :param views: ``ai`` views the statement named (validated against :func:`ai_views`).
    :returns: ``who``, ``pid``, ``verified``, ``entitlement`` and ``visible``
        (rows of each view this persona can see); ``error`` if it could not.
    """
    out: dict[str, Any] = {"visible": {}}
    try:
        with conn.cursor() as cur:
            cur.execute("BEGIN READ ONLY")
            cur.execute("SET LOCAL statement_timeout = 8000")
            cur.execute("SELECT session_user AS who, current_user AS acting_as, "
                        "pg_backend_pid() AS pid, sec.has_verified_session() AS verified")
            out.update(cur.fetchone() or {})
            cur.execute("SELECT * FROM ai.my_entitlement")
            out["entitlement"] = cur.fetchone()
            for view in views:
                if view in ai_views():
                    schema, name = view.split(".", 1)
                    cur.execute(pgsql.SQL("SELECT count(*) AS n FROM {}.{}").format(
                        pgsql.Identifier(schema), pgsql.Identifier(name)))
                    out["visible"][view] = (cur.fetchone() or {}).get("n")
            cur.execute("COMMIT")
    except psycopg.Error as exc:
        conn.rollback()
        out["error"] = str(exc).strip().splitlines()[0]
    return out


# ---------------------------------------------------------------------------
# The kitchen: events in, steps out
# ---------------------------------------------------------------------------


class Kitchen:
    """Collects one question's steps; safe to read while it is being cooked.

    :param question: The question.
    :param persona: ``{"role", "name", "kind"}``.
    :param model: The model identifier asked.
    """

    def __init__(self, question: str, persona: dict[str, str], model: str) -> None:
        self.id = secrets.token_hex(6)
        self.question = question
        self.persona = persona
        self.model = model
        self.started = time.time()
        self.attempt = 1
        self.views: list[str] = []
        self.done = False
        self.result: dict[str, Any] | None = None
        self.error: str | None = None
        self._steps: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._t: dict[str, float] = {}
        self.version = 0
        self.log = "—"

    # -- plumbing --------------------------------------------------------

    def _now(self) -> float:
        return round(time.time() - self.started, 2)

    def put(self, step: dict[str, Any]) -> None:
        """Add a step, or update the one with the same id."""
        with self._lock:
            for i, existing in enumerate(self._steps):
                if existing["id"] == step["id"]:
                    self._steps[i] = {**existing, **step}
                    break
            else:
                self._steps.append(step)
            self.version += 1

    def step(self, sid: str, lane: str, title: str, status: str = "pass", **kw: Any) -> None:
        """Record a step on a lane (``status``: running, pass, fail, skip, info)."""
        self._t[sid] = time.time()
        self.put({"kind": "step", "id": sid, "lane": lane, "title": title, "status": status,
                  "t": self._now(), **kw})

    def finish(self, sid: str, status: str, **kw: Any) -> None:
        """Close a running step, with its duration."""
        started = self._t.get(sid, time.time())
        self.put({"id": sid, "status": status, "dt": round(time.time() - started, 2), **kw})

    def arrow(self, sid: str, src: str, dst: str, label: str, status: str = "pass") -> None:
        """A hand-over between lanes."""
        self.put({"kind": "arrow", "id": sid, "from": src, "to": dst, "label": label,
                  "status": status, "t": self._now()})

    def snapshot(self) -> dict[str, Any]:
        """Everything so far, for the page to draw.

        :returns: ``id``, ``version``, ``done``, ``elapsed``, ``steps``, and the
            ``result`` once finished.
        """
        with self._lock:
            steps = [dict(s) for s in self._steps]
        out = {"id": self.id, "version": self.version, "done": self.done,
               "elapsed": round(time.time() - self.started, 1), "steps": steps, "error": self.error}
        if self.done and self.result is not None:
            out["result"] = self.result
        return out

    def __call__(self, name: str, data: dict[str, Any]) -> None:
        """The ``on_event`` hook. Unknown events are ignored."""
        handler = getattr(self, f"_on_{name}", None)
        if handler is not None:
            handler(**data)

    @property
    def who(self) -> str:
        return f"{self.persona['name']} ({self.persona['role']})"

    # -- the app and the model --------------------------------------------

    def _on_prompt(self, attempt: int, prompt: str, pack_chars: int, feedback: str | None,
                   role: str, question: str) -> None:
        self.attempt = attempt
        if attempt == 1:
            self.step("received", "app", "Question received",
                      lines=[f"“{question[:90]}”", f"as {self.who}", f"model {self.model}"],
                      detail={"facts": [["Question", question],
                                        ["Asked as", f"{self.persona['name']} · {self.persona['kind']} ({role})"],
                                        ["Model", self.model]],
                              "note": "The persona decides which rows come back. Claude is never told who is asking."})
        lines = [f"semantic layer: {pack_chars:,} chars", "+ your question"]
        if feedback:
            lines.append("+ why the last answer was refused")
        lines.append("not in it: who you are, any data")
        self.step(f"prompt-{attempt}", "app", "Prompt assembled" if attempt == 1 else "Retry prompt assembled",
                  lines=lines,
                  detail={"facts": [["Prompt", f"{len(prompt):,} characters ≈ {len(prompt) // 4:,} tokens"],
                                    ["Semantic layer", (f"{pack_chars:,} characters: entities, columns, joins, "
                                                       "certified metrics, caveats (semantic/context_pack.md)")],
                                    ["System prompt", llm_client.SYSTEM_PROMPT],
                                    ["Never in the prompt", ("who is asking, any row of data, any password "
                                                            "or connection string")]]
                          + ([["Refusal sent back", feedback]] if feedback else []),
                          "code": prompt[-700:], "code_label": "The end of the prompt"})
        self.arrow(f"a-prompt-{attempt}", "app", "claude", "prompt → claude -p" if attempt == 1 else "retry prompt")

    def _on_llm_start(self, attempt: int, provider: str, model: str) -> None:
        sandbox = []
        if provider == "claude_cli":
            binary = shutil.which("claude")
            flags = llm_client.cli_supported_flags(binary) if binary else frozenset()
            sandbox = ["no tools (--tools \"\")" if "--tools" in flags else "tools denied (--disallowedTools)",
                       "no skills" if "--disable-slash-commands" in flags else "skills not disabled (old CLI)",
                       "no MCP servers", "working directory outside the repository"]
        self.step(f"llm-{attempt}", "claude", "Claude writes SQL + intent", "running",
                  lines=[model, "local claude CLI · no API key" if provider == "claude_cli" else provider,
                         "it only has the prompt"],
                  detail={"facts": [["Provider", provider], ["Model", model],
                                    ["Sandbox", ", ".join(sandbox) or "—"]],
                          "note": "Claude cannot read the database, the files or the internet: "
                                  "it can only answer with text, and that text is checked next."})

    def _on_llm_done(self, attempt: int, response: Any) -> None:
        usage = response.usage or {}
        inner = usage.get("usage") or {}
        tin = sum(int(inner.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                    "cache_read_input_tokens"))
        tout = int(inner.get("output_tokens") or 0)
        cost = float(usage.get("total_cost_usd") or 0.0)
        facts = [["Duration", f"{response.duration_sec:.1f} s"], ["Tokens", f"{tin:,} in · {tout:,} out"],
                 ["Cost", f"USD {cost:.4f}"]]
        facts += [[f"Parameter: {k}", str(v)] for k, v in (response.parameters or {}).items()]
        if response.executed:
            self.finish(f"llm-{attempt}", "pass",
                        lines=[response.model, f"{response.duration_sec:.1f} s · {tin:,} tokens in · {tout} out",
                               f"USD {cost:.4f}"],
                        detail={"facts": facts, "code": (response.text or "")[:3000], "code_label": "Raw reply"})
            self.arrow(f"a-reply-{attempt}", "claude", "app", "JSON reply")
        else:
            self.finish(f"llm-{attempt}", "fail", lines=[response.error or config.NOT_EXECUTED],
                        detail={"facts": facts + [["Error", response.error or config.NOT_EXECUTED]],
                                "note": "No answer is invented: without a model reply nothing runs."})

    def _on_parse(self, attempt: int, parsed: dict[str, Any] | None, error: str | None) -> None:
        if parsed is None:
            self.step(f"parse-{attempt}", "app", "Reply read", "fail", lines=[(error or "not JSON")[:120]],
                      detail={"facts": [["Problem", error or "the reply is not the expected JSON"]]})
            return
        ir = parsed.get("ir") if isinstance(parsed.get("ir"), dict) else {}
        self.step(f"parse-{attempt}", "app", "Reply read",
                  lines=["one JSON object: sql + ir", f"metric: {ir.get('metric', '—')}"],
                  detail={"facts": [["Keys", ", ".join(sorted(parsed))],
                                    ["Claude's reasoning", str(parsed.get("reasoning") or "—")[:600]]],
                          "code": str(parsed.get("sql", "")), "code_label": "SQL Claude wrote"})
        self.arrow(f"a-checks-{attempt}", "app", "checks", "SQL + intent")

    # -- the checks ------------------------------------------------------

    def _on_guard(self, sql: str, verdict: sql_guard.GuardVerdict) -> None:
        a = self.attempt
        shape = parse_shape(sql)
        failed: dict[str, list[str]] = {}
        unmatched: list[str] = []
        for violation in verdict.violations:
            for key, pattern in _GUARD_RULES:
                if pattern.search(violation):
                    failed.setdefault(key, []).append(violation)
                    break
            else:
                unmatched.append(violation)
        allowed_schemas = set(config.GUARD_ALLOWED_SCHEMAS)
        checks = [
            [not failed.get("statements"), f"Exactly one statement (found {shape['statements']})"],
            [not failed.get("select"), f"Read-only SELECT (found {', '.join(shape['kinds']) or '—'})"],
        ]
        for table in shape["tables"]:
            ok = table.split(".", 1)[0] in allowed_schemas
            checks.append([ok, f"{table}: " + ("in the ai schema, allowed" if ok else
                                                "outside the ai schema, refused")])
        if not shape["tables"]:
            checks.append([not failed.get("schema"), "Names no table outside ai"])
        checks.append([not failed.get("functions"),
                       "No forbidden function (pg_read_file, pg_sleep, set_config, dblink …)"
                       + (f" — uses {', '.join(shape['functions'])}" if shape["functions"] else "")])
        checks += [[False, v] for v in failed.get("schema", []) + unmatched]
        if verdict.allowed:
            checks += [[True, n] for n in verdict.notes]
        self.views = [t for t in shape["tables"] if t.startswith("ai.")]
        chips = [{"text": t, "ok": t.split(".", 1)[0] in allowed_schemas} for t in shape["tables"]]
        self.step(f"guard-{a}", "checks", "Guard: is it safe to run?", "pass" if verdict.allowed else "fail",
                  lines=[f"{shape['statements']} statement · {', '.join(shape['kinds']) or '—'}",
                         "allowed" + (f" · {verdict.notes[0]}" if verdict.notes else "") if verdict.allowed
                         else verdict.reason[:120]],
                  chips=chips, chips_label="views Claude chose",
                  detail={"checks": checks,
                          "facts": [["Verdict", verdict.reason]],
                          "code": verdict.rewritten_sql or sql,
                          "code_label": "As it will run (the guard's rewrite)" if verdict.allowed else "Refused SQL",
                          "note": "The guard judges shape only: one read-only statement, only the ai schema, "
                                  "no dangerous function, a row cap. Whether it means the right thing is next."})
        if not verdict.allowed:
            self._never(a, "the guard refused it")

    def _on_intent(self, ir: Any, verification: Any) -> None:
        a = self.attempt
        ir = ir if isinstance(ir, dict) else {}
        checks = [[True, CHECK_TEXT.get(c, c)] for c in verification.checks]
        checks += [[False, f] for f in verification.findings]
        facts = [[k, str(ir.get(k))] for k in ("metric", "entity", "counting_grain", "time", "group_by",
                                               "filters", "order", "limit") if k in ir]
        if verification.ok:
            lines = [f"{ir.get('metric', '—')} on {ir.get('entity', '—')}",
                     f"{len(verification.checks)} checks passed"]
        else:
            lines = [(verification.findings or ["refused"])[0][:140]]
        self.step(f"intent-{a}", "checks", "Intent: does it compute what Claude says?",
                  "pass" if verification.ok else "fail", lines=lines,
                  detail={"checks": checks, "facts": facts,
                          "note": "D029: Claude declares its intent (the IR) next to its SQL. The SQL must "
                                  "match it -- certified metric, declared joins, exact period, grouping, "
                                  "filters -- or it is refused before any database session exists."})
        if verification.ok:
            self.arrow(f"a-login-{a}", "checks", "db", f"log in as {self.persona['role']}")
        else:
            self._never(a, "the intent check refused it")

    def _never(self, attempt: int, why: str) -> None:
        self.step(f"never-{attempt}", "db", "PostgreSQL never sees it", "skip",
                  lines=[why, "no database session is opened"],
                  detail={"note": "A refused statement never reaches the database: no login, no plan, "
                                  "no rows. The refusal reason goes back to Claude once (one retry)."})

    # -- the database ----------------------------------------------------

    def _on_login_start(self, role: str) -> None:
        self.step(f"login-{self.attempt}", "db", "Who is asking? Two-factor login", "running",
                  lines=[f"connect as role {role}", "factor 1: password …", "factor 2: one-time code …"])

    def _on_login(self, role: str) -> None:
        self.finish(f"login-{self.attempt}", "pass",
                    lines=[f"session_user = {role}", "✓ password (a PostgreSQL LOGIN role)",
                           "✓ one-time code, checked in the database"],
                    detail={"facts": [
                        ["Identity", f"{role} — {self.persona['name']}, {self.persona['kind']}"],
                        ["Factor 1", ("the password is checked by PostgreSQL itself: each persona is a real "
                                     "database role, not a name the app passes along")],
                        ["Factor 2", ("a 6-digit TOTP code verified inside the database by "
                                     "sec.verify_second_factor(); a code works once, and the verified "
                                     "session is bound to this connection")],
                        ["Without factor 2", "every policy returns 0 rows: sec.has_verified_session() is false"],
                        ["Demo note", ("the code is generated from the enrolled secret, standing in for the "
                                      "user's phone (as in make demo-login)")]]})

    def _on_login_failed(self, role: str, error: str) -> None:
        self.finish(f"login-{self.attempt}", "fail", lines=[error[:140]],
                    detail={"facts": [["Error", error]]})

    def _on_executed(self, role: str, conn: psycopg.Connection, verification: Any) -> None:
        a = self.attempt
        session = observe_session(conn, self.views)
        profiles = [view_profile(v) for v in self.views]
        name = self.persona["name"]

        # who is this, and what may they see
        ent = session.get("entitlement") or {}
        observed = [["Observation failed", session["error"]]] if session.get("error") else []
        self.step(f"ent-{a}", "db", f"What may {name} see?",
                  lines=[str(ent.get("principal_type", "—")),
                         (f"{int(ent.get('entitled_clients') or 0):,} clients · "
                         f"{int(ent.get('entitled_accounts') or 0):,} accounts"),
                         f"book: {ent.get('portfolios') or '—'}"],
                  detail={"facts": [["session_user", str(session.get("who", "—"))],
                                    ["Verified second factor", str(session.get("verified", "—"))],
                                    ["Backend process", str(session.get("pid", "—"))],
                                    ["Principal type", str(ent.get("principal_type", "—"))],
                                    ["Books (portfolios)", str(ent.get("portfolios") or "—")],
                                    ["Entitled clients", f"{int(ent.get('entitled_clients') or 0):,}"],
                                    ["Entitled accounts", f"{int(ent.get('entitled_accounts') or 0):,}"]]
                          + observed,
                          "note": "Read from ai.my_entitlement. The set is derived in the database: "
                                  "sec.v_my_clients / sec.v_my_accounts = live grants WHERE db_role = "
                                  "SESSION_USER AND the user is active AND sec.has_verified_session(), plus "
                                  "the accounts their clients own (D009, D026, D027)."})

        # which views, which tables, which policies
        lines, chips, facts = [], [], []
        for p in profiles:
            lines.append(f"{p['view']} → {', '.join(p['tables']) or '—'}")
            facts.append([p["view"], ("security_invoker ✓ — " if p["security_invoker"] else "not security_invoker — ")
                          + "reads " + ", ".join(p["tables"]) + (f" (via {', '.join(p['via'])})" if p["via"] else "")])
            for pol in p["policies"]:
                chips.append({"text": f"{pol['policy']} on {pol['table']}", "ok": True})
                facts.append([f"policy {pol['policy']}", (f"on {pol['table']}, for {pol['roles']}: "
                                                         f"USING {pol['using'][:220]}")])
        self.step(f"views-{a}", "db", "Views → tables → row-level security",
                  lines=lines or ["no ai view named"], chips=chips, chips_label="policies that filter the rows",
                  detail={"facts": facts,
                          "note": "Every ai view is security_invoker, so the policies on the core tables are "
                                  "evaluated as the persona. The filter is in the engine, not in Claude's "
                                  "SQL -- nothing Claude writes can remove it (D009, D010)."})

        reached = set(verification.checks)
        stage = verification.stage

        def status(key: str) -> str:
            if key in reached:
                return "pass"
            return "fail" if stage == key else "skip"

        self.step(f"plan-{a}", "db", "Plan (EXPLAIN)", status("plan"),
                  lines=["PostgreSQL plans it, runs nothing", "rejects unknown columns, bad types"],
                  detail={"facts": [["Result", "planned" if "plan" in reached else
                                     (verification.reason if stage == "plan" else "not reached")]]})

        executed = "recompute" in reached or stage in ("recompute", "verified")
        rows = verification.rows or []
        vis_lines = []
        vis_facts = []
        for p in profiles:
            seen = session.get("visible", {}).get(p["view"])
            total = p.get("total")
            if seen is not None and total is not None:
                vis_lines.append(f"{p['view']}: {seen:,} of {total:,} rows visible")
                vis_facts.append([p["view"], (f"{seen:,} of {total:,} rows visible to {name} "
                                             f"({(100 * seen / total) if total else 0:.1f}%)")])
        self.step(f"exec-{a}", "db", f"Execute under RLS, as {name}",
                  "pass" if executed else ("fail" if stage == "execute" else "skip"),
                  lines=(["read-only · 60 s limit · ≤ 10,000 rows"]
                         + ([f"{len(rows):,} row(s) returned"] if verification.ok else [])
                         + vis_lines)[:4] if executed or stage == "execute" else ["not reached"],
                  detail={"facts": vis_facts + [["Transaction", ("BEGIN READ ONLY, statement_timeout "
                                                 f"{config.GUARD_STATEMENT_TIMEOUT_MS // 1000} s, LIMIT "
                                                 f"{config.GUARD_MAX_ROWS:,}")]]
                          + ([["Error", verification.reason]] if stage == "execute" else []),
                          "code": getattr(verification, "executed_sql", None) or "",
                          "code_label": "Executed SQL"})

        self.step(f"recompute-{a}", "db", "Recompute the metric independently", status("recompute"),
                  lines=["certified SQL written from the IR alone", "must give the same numbers"],
                  detail={"facts": [["Result", "identical" if "recompute" in reached else
                                     (verification.reason if stage == "recompute" else "not reached")]],
                          "code": verification.canonical_sql or "", "code_label": "Certified SQL from the IR"})
        if verification.ok:
            self.arrow(f"a-rows-{a}", "db", "app", f"{len(rows):,} row(s) as {self.persona['role']}")

    # -- the end ---------------------------------------------------------

    def _on_attempt_end(self, attempt: int, result: dict[str, Any], last: bool, log: str,
                        feedback: str | None = None) -> None:
        self.log = log
        if result.get("stage") != "done" and not last:
            self.arrow(f"a-retry-{attempt}", "app", "claude", "refused: the reason goes back (retry)", "info")

    def _on_done(self, result: dict[str, Any]) -> None:
        ok = result.get("stage") == "done"
        self.step("answer", "app", "Answer shown" if ok else "Refused: nothing shown", "pass" if ok else "fail",
                  lines=([f"{result.get('row_count', 0):,} row(s) to {self.persona['name']}"] if ok
                         else [f"stopped at: {result.get('stage')}", str(result.get('error') or '')[:110]])
                  + [f"{result.get('elapsed_sec', 0)} s · USD {result.get('usage', {}).get('cost_usd', 0):.4f}"],
                  detail={"facts": [["Audit log", self.log],
                                    ["Attempts", str(len(result.get("attempts", [])))],
                                    ["Total time", f"{result.get('elapsed_sec', 0)} s"]],
                          "note": "Every model call is logged in full: prompt, parameters, raw reply, "
                                  "verdict, cost."})
