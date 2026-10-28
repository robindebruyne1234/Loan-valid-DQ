"""Parse, judge and rewrite LLM-generated SQL before it reaches the database.

This is the **second** line of defence, and it is important to be clear about
which line does what:

* The entitlement filter is a row level security policy in the database
  (``sql/50_sec_rls.sql``). It holds whatever SQL arrives, so the guard is not
  what keeps a user inside their portfolio.
* The guard enforces the *shape* of a generated query: one read-only
  statement, on the governed ``ai`` surface, bounded in rows and in time. It
  turns a model that is wrong or hostile into a rejected query rather than a
  slow one, a mutating one, or one that quietly reads an internal schema whose
  columns mean something else.

The parse is done with sqlglot rather than with regular expressions, because a
blocklist of strings is defeated by comments, casing and string literals,
whereas an abstract syntax tree is not: ``SELECT/**/1; DROP TABLE x`` is two
statements to a parser and one line to a regex.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import psycopg
import sqlglot
from sqlglot import exp

from src import config, db

LOGGER = db.setup_logging("guard")

#: Expression types that may never appear anywhere in a generated statement.
#: Everything that writes, changes structure, grants, or reaches outside the
#: query.
FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Grant,
    exp.TruncateTable,
    exp.Merge,
    exp.Command,       # SET, COPY, CALL, VACUUM, and anything sqlglot cannot type
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Use,
    exp.Into,          # SELECT ... INTO creates a table
    exp.Lock,          # FOR UPDATE takes row locks on a read-only surface
)

#: Functions that read the server's environment rather than the data product.
#: Lower-case; matched on the function name.
FORBIDDEN_FUNCTIONS: frozenset[str] = frozenset(
    {
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "pg_stat_file",
        "pg_sleep",
        "pg_sleep_for",
        "lo_import",
        "lo_export",
        "dblink",
        "dblink_exec",
        "query_to_xml",
        "set_config",
        "pg_terminate_backend",
        "pg_cancel_backend",
        "pg_reload_conf",
        "pg_logical_emit_message",
        "dblink_connect",
        "copy_from_program",
        "current_setting",   # reads server and session configuration
    }
)

#: Schemas a function may be qualified with, beyond the allowed data schemas.
#: ``pg_catalog`` holds the built-ins, which an unqualified call reaches anyway.
FUNCTION_SCHEMAS: frozenset[str] = frozenset({"pg_catalog"})


@dataclass
class GuardVerdict:
    """The outcome of guarding one generated statement.

    :ivar allowed: Whether the statement may be executed.
    :ivar sql: The statement as the model produced it.
    :ivar rewritten_sql: The statement actually sent to the database, with a
        row limit applied. ``None`` when the statement was rejected.
    :ivar violations: One entry per rule the statement broke.
    :ivar notes: Changes the guard made, for the audit trail.
    """

    allowed: bool
    sql: str
    rewritten_sql: str | None = None
    violations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def reason(self) -> str:
        """Human-readable summary of the verdict.

        :returns: ``"allowed"`` or the list of violations, joined.
        """
        if self.allowed:
            return "allowed" + (f" ({'; '.join(self.notes)})" if self.notes else "")
        return "; ".join(self.violations)


def _cte_names(statement: exp.Expression) -> set[str]:
    """Collect the names defined by WITH clauses anywhere in the statement.

    :param statement: Parsed statement.
    :returns: Lower-cased CTE names, which are not real tables and must not be
        checked against the allowed schemas.
    """
    names: set[str] = set()
    for cte in statement.find_all(exp.CTE):
        alias = cte.alias_or_name
        if alias:
            names.add(alias.lower())
    return names


def _function_schema_violations(
    statement: exp.Expression, allowed_schemas: tuple[str, ...]
) -> list[str]:
    """Find functions called through a schema the query may not use.

    The table check sees ``FROM sec.app_user`` but not ``sec.end_session()``:
    a schema-qualified call is a dotted expression, or, in a FROM clause, a
    table whose body is a function. Both are checked here. Unqualified calls
    resolve to the built-ins and are judged by name in the forbidden list.

    :param statement: Parsed statement.
    :param allowed_schemas: Schemas the statement may reference.
    :returns: One message per offending call.
    """
    permitted = set(allowed_schemas) | FUNCTION_SCHEMAS
    violations: list[str] = []
    for dot in statement.find_all(exp.Dot):
        if not isinstance(dot.expression, exp.Func):
            continue
        qualifier = dot.this
        if isinstance(qualifier, exp.Dot):
            violations.append(f"calls {dot.expression.name}() through a three-part name")
        elif (qualifier.name or "").lower() not in permitted:
            violations.append(f"calls {qualifier.name}.{dot.expression.name}(), outside "
                              f"the allowed schemas")
    for table in statement.find_all(exp.Table):
        schema = (table.db or "").lower()
        if isinstance(table.this, exp.Func) and schema and schema not in permitted:
            violations.append(f"reads from the function {schema}.{table.this.name}(), "
                              "outside the allowed schemas")
    return violations


def _bound_rows(statement: exp.Expression, verdict: GuardVerdict) -> None:
    """Make sure the statement returns at most the row cap.

    A bound the model wrote is kept only when it is a plain number no larger
    than the cap. ``LIMIT ALL``, a computed limit, ``FETCH ... PERCENT`` or
    ``WITH TIES``, and anything above the cap are replaced -- otherwise the
    cap holds only for models that forget to write a limit.

    :param statement: Parsed statement, modified in place.
    :param verdict: Receives a note describing any change.
    :returns: ``None``.
    """
    cap = config.GUARD_MAX_ROWS
    bound = statement.args.get("limit")
    if bound is None:
        statement.set("limit", exp.Limit(expression=exp.Literal.number(cap)))
        verdict.notes.append(f"row limit {cap} applied")
        return
    count = None
    if isinstance(bound, exp.Limit):
        count = bound.expression
    elif isinstance(bound, exp.Fetch):
        options = bound.args.get("limit_options")
        if not (options and (options.args.get("percent") or options.args.get("with_ties"))):
            count = bound.args.get("count")
    if isinstance(count, exp.Literal) and count.is_int and int(count.this) <= cap:
        return
    statement.set("limit", exp.Limit(expression=exp.Literal.number(cap)))
    verdict.notes.append(f"row limit {cap} replaced the model's '{bound.sql(dialect='postgres')}'")


def guard(sql: str, allowed_schemas: tuple[str, ...] = config.GUARD_ALLOWED_SCHEMAS) -> GuardVerdict:
    """Judge one generated statement and return a verdict.

    :param sql: The SQL the model produced.
    :param allowed_schemas: Schemas the statement may reference.
    :returns: A :class:`GuardVerdict`. When allowed, ``rewritten_sql`` carries
        the statement to execute, which has a row limit applied.
    """
    verdict = GuardVerdict(allowed=False, sql=sql)
    text = (sql or "").strip()
    if not text:
        verdict.violations.append("empty statement")
        return verdict

    try:
        statements = sqlglot.parse(text, read="postgres")
    except Exception as exc:  # noqa: BLE001 - a parse failure is a verdict, not a crash
        verdict.violations.append(f"does not parse as PostgreSQL: {exc}")
        return verdict

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        verdict.violations.append(
            f"expected exactly one statement, found {len(statements)} "
            "(statement batching is how a read-only surface gets written to)"
        )
        return verdict

    statement = statements[0]

    # 1. The statement must be a query.
    if not isinstance(statement, (exp.Select, exp.Union, exp.Subquery, exp.With)):
        verdict.violations.append(
            f"only {'/'.join(config.GUARD_ALLOWED_STATEMENTS)} statements are allowed, "
            f"this is {type(statement).__name__.upper()}"
        )
        return verdict

    # 2. No forbidden node anywhere in the tree, including inside subqueries.
    for node_type in FORBIDDEN_NODES:
        found = list(statement.find_all(node_type))
        if found:
            verdict.violations.append(
                f"contains a forbidden {node_type.__name__.upper()} node"
            )

    # 3. No environment-reading functions.
    for function in statement.find_all(exp.Anonymous, exp.Func):
        name = (getattr(function, "name", "") or "").lower()
        if name in FORBIDDEN_FUNCTIONS:
            verdict.violations.append(f"calls the forbidden function {name}()")

    # 4. Every table reference must be an explicitly qualified allowed schema.
    #    A CTE name only stands in for an UNqualified reference: a CTE called
    #    dim_client must not wave core.dim_client through.
    cte_names = _cte_names(statement)
    for table in statement.find_all(exp.Table):
        name = (table.name or "").lower()
        schema = (table.db or "").lower()
        if not name or (not schema and name in cte_names):
            continue
        if not schema:
            verdict.violations.append(
                f"table '{name}' is not schema-qualified; write "
                f"{allowed_schemas[0]}.{name}"
            )
        elif schema not in allowed_schemas:
            verdict.violations.append(
                f"reads schema '{schema}', which is not allowed "
                f"(allowed: {', '.join(allowed_schemas)})"
            )

    # 5. No function reached through a schema the query may not read.
    verdict.violations.extend(_function_schema_violations(statement, allowed_schemas))

    if verdict.violations:
        return verdict

    # 6. Bound the result. A missing or too-loose limit is not a violation, it
    #    is something the guard fixes, because an unbounded result is a cost
    #    problem rather than a correctness or safety one.
    _bound_rows(statement, verdict)

    verdict.allowed = True
    verdict.rewritten_sql = statement.sql(dialect="postgres", pretty=True)
    return verdict


def execute_guarded(
    conn: psycopg.Connection, sql: str, allowed_schemas: tuple[str, ...] | None = None
) -> tuple[GuardVerdict, list[dict] | None, str | None]:
    """Guard a statement and, if allowed, execute it under hard limits.

    The statement runs inside a read-only transaction with a statement timeout,
    so a query that passes the guard still cannot write and cannot run forever.
    Belt and braces: the consumer role has no write privileges either, and at
    most one row beyond the cap is ever fetched.

    :param conn: Open connection, normally authenticated as a consumer role.
    :param sql: The SQL the model produced.
    :param allowed_schemas: Override for the allowed schema list.
    :returns: Tuple of (verdict, rows or ``None``, error message or ``None``).
    """
    verdict = guard(sql, allowed_schemas or config.GUARD_ALLOWED_SCHEMAS)
    if not verdict.allowed:
        LOGGER.warning("guard REJECTED -> %s", verdict.reason)
        return verdict, None, None

    try:
        with conn.cursor() as cur:
            cur.execute("BEGIN READ ONLY")
            cur.execute(f"SET LOCAL statement_timeout = {config.GUARD_STATEMENT_TIMEOUT_MS}")
            cur.execute(verdict.rewritten_sql)
            rows = list(cur.fetchmany(config.GUARD_MAX_ROWS + 1))
            cur.execute("COMMIT")
        if len(rows) > config.GUARD_MAX_ROWS:
            # The rewrite should make this impossible. If it ever happens the
            # honest outcome is a refusal, not a silently shortened answer.
            LOGGER.error("guarded query returned more than %d rows", config.GUARD_MAX_ROWS)
            return verdict, None, f"the result exceeded the {config.GUARD_MAX_ROWS}-row cap"
        return verdict, rows, None
    except psycopg.Error as exc:
        conn.rollback()
        message = str(exc).strip().splitlines()[0]
        LOGGER.warning("guarded query failed in the database -> %s", message)
        return verdict, None, message


def main() -> int:
    """Demonstrate the guard on a set of statements, for the walkthrough.

    :returns: Always ``0``.
    """
    examples = [
        ("a legitimate query", "SELECT region, count(*) FROM ai.client GROUP BY region"),
        ("two statements", "SELECT 1 FROM ai.client; DROP TABLE core.dim_client"),
        ("a comment-hidden batch", "SELECT 1 FROM ai.client/**/;/**/DELETE FROM core.fact_loan"),
        ("an update", "UPDATE ai.client SET gender = 'male'"),
        ("reading an internal schema", "SELECT count(*) FROM stg.trans"),
        ("reading the entitlement tables", "SELECT * FROM sec.portfolio_client"),
        ("an unqualified table", "SELECT count(*) FROM client"),
        ("a forbidden function", "SELECT pg_read_file('/etc/passwd')"),
        ("a session variable", "SELECT set_config('app.end_user', 'cro_global', false)"),
        ("a hidden write in a CTE", "WITH x AS (DELETE FROM core.fact_loan RETURNING 1) SELECT * FROM x"),
        ("a CTE named like a table", "WITH dim_client AS (SELECT 1) SELECT * FROM core.dim_client"),
        ("an internal function", "SELECT sec.end_session()"),
        ("an unbounded query", "SELECT * FROM ai.transaction"),
        ("a limit above the cap", "SELECT * FROM ai.transaction LIMIT 100000000"),
    ]
    for label, sql in examples:
        verdict = guard(sql)
        LOGGER.info("%-30s %-8s %s", label, "ALLOW" if verdict.allowed else "REJECT", verdict.reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
