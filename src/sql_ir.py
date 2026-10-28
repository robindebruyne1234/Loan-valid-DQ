"""Verify generated SQL against the intent the model declared (DECISIONS.md D029).

The SQL guard (:mod:`src.sql_guard`) decides whether a statement may run. It
cannot tell whether the statement answers the question: a query on a column
that does not exist, on the wrong date, over the wrong quarter or through a
join that repeats every loan once per posting is perfectly well-formed SQL.

So the model returns, next to its SQL, a small intermediate representation
(IR) of what it intends to compute::

    {"metric": "loan_count", "entity": "ai.loan", "counting_grain": "loan_id",
     "time": {"column": "loan_date",
              "periods": [{"from": "1995-01-01", "to": "1995-04-01"}]},
     "group_by": ["owner_gender"], "filters": [], "order": null, "limit": null}

and this module checks, in order, before anything reaches the database:

1. the IR itself, against the semantic layer: the metric is certified, entity,
   counting grain and time column are the metric's own, periods are valid
   half-open ranges inside the book, grouping and filter columns exist, and
   the years and quarters the question names are the ones the IR covers;
2. every column the SQL references, resolved scope by scope against the
   semantic layer -- an unknown column is rejected with the nearest names;
3. the SQL against the IR: the metric's entity and aggregate are present, every
   join is a declared path that cannot repeat the counted entity, the period
   filter selects exactly the IR's days (evaluated day by day over the book's
   calendar), the requested grouping, filters and limit are present, and no
   unrequested filter or date column narrows the result.

:func:`run_verified` then has PostgreSQL plan the statement (EXPLAIN, no
execution), executes it under the guard on the caller's own authenticated
connection, and recomputes the metric from the IR alone with SQL written here
(:func:`canonical_sql`). The two results must agree before an answer is
returned. Anything missing, malformed, contradictory or not verifiable fails
with the reason -- a refusal, never an unverified number.

Passing these checks is evidence that the SQL implements the declared intent
with the certified definitions. It is not proof that the intent is what the
user meant; that is what the question cross-check and the reported IR are for.
"""

from __future__ import annotations

import calendar as _calendar
import difflib
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from typing import Any, Callable

import psycopg
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import Scope, traverse_scope

from src import config, db, semantic_context, sql_guard

LOGGER = db.setup_logging("sql_ir")

PERIOD_GRAINS = ("year", "quarter", "month")
FILTER_OPS = ("=", "!=", "<>", "<", "<=", ">", ">=", "in", "not in", "is null", "is not null")
CALENDAR = "ai.calendar"

#: How each ai.calendar column reads a day, so a calendar predicate can be
#: evaluated on the day it is joined to.
CALENDAR_COLUMNS: dict[str, tuple[str, Callable[[date], Any]]] = {
    "date_key": ("date", lambda d: d),
    "year": ("year", lambda d: d.year),
    "quarter": ("quarter", lambda d: (d.month - 1) // 3 + 1),
    "month": ("month", lambda d: d.month),
    "month_name": ("month", lambda d: _calendar.month_name[d.month]),
    "year_month": ("month", lambda d: f"{d.year:04d}-{d.month:02d}"),
    "month_start": ("month", lambda d: d.replace(day=1)),
    "month_end": ("month", lambda d: d.replace(day=_calendar.monthrange(d.year, d.month)[1])),
    "is_month_end": ("day", lambda d: d.day == _calendar.monthrange(d.year, d.month)[1]),
}


class Unverifiable(Exception):
    """A construct the verifier cannot evaluate, so it must not vouch for it."""


@dataclass
class Verification:
    """Outcome of verifying one statement.

    :ivar ok: True only when every check passed.
    :ivar stage: Where it stopped: ``ir``, ``columns``, ``consistency``,
        ``guard``, ``plan``, ``execute``, ``recompute`` or ``verified``.
    :ivar findings: Human-readable reasons, each one actionable.
    :ivar checks: Names of the checks that passed, for the record.
    """

    ok: bool = False
    stage: str = "ir"
    findings: list[str] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] | None = None
    executed_sql: str | None = None
    canonical_sql: str | None = None

    @property
    def reason(self) -> str:
        """All findings as one sentence, for logs and retry feedback."""
        return "; ".join(self.findings)

    def as_dict(self) -> dict[str, Any]:
        """JSON-friendly summary for llm_results.json and the web API."""
        return {"ok": self.ok, "stage": self.stage, "findings": list(self.findings),
                "checks": list(self.checks), "canonical_sql": self.canonical_sql}


# ---------------------------------------------------------------------------
# The semantic layer as a lookup structure
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Catalog:
    """What the verifier needs from the semantic layer, indexed."""

    columns: dict[str, dict[str, str]]           # entity -> column -> type
    keys: dict[str, tuple[str, ...]]
    joins: dict[tuple[str, str], dict[str, Any]]  # (from, to) -> declared join, both directions
    period_columns: dict[str, dict[str, str]]     # entity -> {"year": "loan_year"}
    metrics: dict[str, dict[str, Any]]
    book_from: date
    book_to: date


def build_catalog(layer: dict[str, Any]) -> Catalog:
    """Index the semantic layer; reverse every declared join as well."""
    reverse = {"one-to-many": "many-to-one", "many-to-one": "one-to-many", "one-to-one": "one-to-one"}
    columns, keys, joins, periods = {}, {}, {}, {}
    for entity in layer["entities"]:
        name = entity["name"]
        columns[name] = {c["name"]: c["type"] for c in entity["columns"]}
        keys[name] = tuple(entity.get("primary_key") or [])
        periods[name] = dict(entity.get("period_columns") or {})
        for join in entity.get("joins") or []:
            left, right = semantic_context._join_columns(join["on"])  # noqa: SLF001
            joins[(name, join["to"])] = {"left": left, "right": right,
                                         "cardinality": join["cardinality"]}
            joins.setdefault((join["to"], name), {"left": right, "right": left,
                                                  "cardinality": reverse[join["cardinality"]]})
    rng = layer["meta"]["date_range"]
    return Catalog(columns, keys, joins, periods, {m["name"]: m for m in layer["metrics"]},
                   date.fromisoformat(rng["from"]), date.fromisoformat(rng["to"]))


@lru_cache(maxsize=1)
def default_catalog() -> Catalog:
    """The catalog of the semantic layer on disk (cached per process)."""
    return build_catalog(semantic_context.load_semantic_layer())


def _grain(value: Any) -> tuple[str, ...]:
    """A counting grain as a sorted tuple of key columns.

    A composite grain is a set of columns, so ``["a", "b"]``, ``"a, b"`` and
    ``"b,a"`` are the same grain.
    """
    if isinstance(value, str):
        value = value.split(",")
    return tuple(sorted(str(v).strip() for v in value or () if str(v).strip()))


# ---------------------------------------------------------------------------
# 1. The IR on its own
# ---------------------------------------------------------------------------

def _parse_day(value: Any, what: str, problems: list[str]) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        problems.append(f"IR {what} '{value}' is not a YYYY-MM-DD date")
        return None


def ir_days(ir: dict[str, Any], cat: Catalog) -> set[date] | None:
    """The set of book days the IR's periods cover, or None for no period."""
    time = ir.get("time")
    if not time:
        return None
    days: set[date] = set()
    for period in time["periods"]:
        day, end = date.fromisoformat(period["from"]), date.fromisoformat(period["to"])
        while day < end:
            if cat.book_from <= day <= cat.book_to:
                days.add(day)
            day += timedelta(days=1)
    return days


#: Words that make a year a boundary rather than the period itself ("before
#: 1995", "born in 1960", "between 1995 and 1997"). With any of them the
#: question's years are not cross-checked; the SQL-against-IR checks still are.
RELATIVE_PERIOD = re.compile(
    r"\b(before|after|since|until|till|prior|between|from|through|born|older|younger|age)\b",
    flags=re.I)


def question_periods(question: str) -> tuple[set[int], set[int]]:
    """Years and calendar quarters a question names, e.g. 'Q1-Q3 of 1995 and 1998'."""
    years = {int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", question)}
    quarters: set[int] = set()
    for first, last in re.findall(r"\bQ([1-4])\s*(?:-|–|—|to|through)\s*Q?([1-4])\b", question, flags=re.I):
        quarters.update(range(int(first), int(last) + 1))
    quarters.update(int(q) for q in re.findall(r"\bQ([1-4])\b", question, flags=re.I))
    return years, quarters


def check_ir(ir: Any, cat: Catalog, question: str = "") -> list[str]:
    """Problems with the IR itself. Empty list = a usable, consistent IR."""
    if not isinstance(ir, dict):
        return ["no IR: the answer must include an 'ir' object describing the metric, "
                "entity, counting grain, periods, grouping and filters"]
    problems: list[str] = []
    metric_name = ir.get("metric")
    metric = cat.metrics.get(metric_name)
    if metric is None:
        known = ", ".join(sorted(cat.metrics))
        return [f"IR metric '{metric_name}' is not a certified metric, so the answer cannot be "
                f"verified (certified: {known})"]
    entity = metric["entity"]
    if ir.get("entity") != entity:
        problems.append(f"IR entity '{ir.get('entity')}' contradicts metric {metric_name}, "
                        f"which is defined on {entity}")
    if _grain(ir.get("counting_grain")) != _grain(metric.get("counting_grain")):
        problems.append(f"IR counting_grain {ir.get('counting_grain')!r} contradicts metric "
                        f"{metric_name}, which counts {metric.get('counting_grain')!r}")

    allowed_columns = set(cat.columns.get(entity, {}))
    for other in metric.get("permitted_joins") or []:
        allowed_columns |= set(cat.columns.get(other, {}))

    time = ir.get("time")
    if time:
        if not isinstance(time, dict) or not isinstance(time.get("periods"), list) or not time["periods"]:
            problems.append("IR time must be null or {'column': ..., 'periods': [{'from', 'to'}, ...]}")
        else:
            if not metric.get("time_column"):
                problems.append(f"metric {metric_name} has no date, so it cannot be restricted to a period")
            elif time.get("column") != metric["time_column"]:
                problems.append(f"IR time column '{time.get('column')}' contradicts metric {metric_name}, "
                                f"whose periods are defined on {metric['time_column']}")
            spans = []
            for period in time["periods"]:
                if not isinstance(period, dict):
                    problems.append("IR period must be {'from': 'YYYY-MM-DD', 'to': 'YYYY-MM-DD'}")
                    continue
                start = _parse_day(period.get("from"), "period start", problems)
                end = _parse_day(period.get("to"), "period end", problems)
                if start and end:
                    if start >= end:
                        problems.append(f"IR period {start}..{end} is empty: 'to' is exclusive and must be after 'from'")
                    elif end <= cat.book_from or start > cat.book_to:
                        problems.append(f"IR period {start}..{end} lies outside the book "
                                        f"({cat.book_from} to {cat.book_to})")
                    spans.append((start, end))
            spans.sort()
            for (s1, e1), (s2, e2) in zip(spans, spans[1:]):
                if s2 < e1:
                    problems.append(f"IR periods {s1}..{e1} and {s2}..{e2} overlap")

    for item in ir.get("group_by") or []:
        if item in PERIOD_GRAINS:
            if not metric.get("time_column"):
                problems.append(f"IR groups by {item}, but metric {metric_name} has no date")
        elif item not in allowed_columns:
            problems.append(f"IR groups by '{item}', which is not a column of {entity} or of its "
                            f"permitted joins{_suggest(item, allowed_columns)}")
    for flt in ir.get("filters") or []:
        if not isinstance(flt, dict) or flt.get("column") not in allowed_columns:
            col = flt.get("column") if isinstance(flt, dict) else flt
            problems.append(f"IR filter on '{col}' is not a column of {entity} or of its permitted "
                            f"joins{_suggest(str(col), allowed_columns)}")
        elif str(flt.get("op", "=")).lower() not in FILTER_OPS:
            problems.append(f"IR filter operator '{flt.get('op')}' is not supported")
    limit = ir.get("limit")
    if limit is not None and (not isinstance(limit, int) or limit <= 0):
        problems.append("IR limit must be null or a positive integer")
    if ir.get("order") not in (None, "asc", "desc"):
        problems.append("IR order must be null, 'asc' or 'desc'")

    # The question's own years and quarters must be the IR's.
    if question and not problems:
        years, quarters = question_periods(question)
        days = ir_days(ir, cat)
        in_book = all(cat.book_from.year <= y <= cat.book_to.year for y in years)
        if years and in_book and not RELATIVE_PERIOD.search(question):
            if days is None:
                problems.append(f"the question names {sorted(years)} but the IR has no period")
            else:
                covered = {d.year for d in days}
                if covered != years:
                    problems.append(f"the question names years {sorted(years)} but the IR periods "
                                    f"cover {sorted(covered)}")
                elif quarters:
                    wanted = {d for y in years for d in _year_days(y, cat) if (d.month - 1) // 3 + 1 in quarters}
                    if days != wanted:
                        label = f"Q{min(quarters)}" if len(quarters) == 1 else f"Q{min(quarters)}-Q{max(quarters)}"
                        problems.append(f"the question names {label} of {sorted(years)} but the IR "
                                        f"periods cover {_ranges(days)}")
    return problems


def _year_days(year: int, cat: Catalog) -> set[date]:
    day, out = date(year, 1, 1), set()
    while day.year == year:
        if cat.book_from <= day <= cat.book_to:
            out.add(day)
        day += timedelta(days=1)
    return out


def _suggest(name: str, candidates: set[str]) -> str:
    close = difflib.get_close_matches(name, sorted(candidates), n=3, cutoff=0.5)
    near = [c for c in sorted(candidates) if name and (name in c or c in name) and c not in close]
    hints = (close + near)[:3]
    return f" (did you mean {', '.join(hints)}?)" if hints else ""


def _ranges(days: set[date] | None) -> str:
    """Compress a day set into readable ranges."""
    if days is None:
        return "no period"
    if not days:
        return "no day"
    ordered = sorted(days)
    runs, start, prev = [], ordered[0], ordered[0]
    for day in ordered[1:]:
        if day != prev + timedelta(days=1):
            runs.append((start, prev))
            start = day
        prev = day
    runs.append((start, prev))
    text = ", ".join(f"{a}..{b}" for a, b in runs[:4])
    return text + (f" (+{len(runs) - 4} more ranges)" if len(runs) > 4 else "")


# ---------------------------------------------------------------------------
# 2. Columns, resolved scope by scope
# ---------------------------------------------------------------------------

@dataclass
class Source:
    """What an alias in a FROM clause stands for."""

    entity: str | None = None      # an ai.* view
    scope: Scope | None = None     # a derived table or CTE


def _sources(scope: Scope, cat: Catalog, problems: list[str]) -> dict[str, Source]:
    out: dict[str, Source] = {}
    for alias, src in scope.sources.items():
        if isinstance(src, exp.Table):
            name = f"{(src.db or '').lower()}.{src.name.lower()}"
            if name not in cat.columns:
                problems.append(f"{name} is not an entity of the semantic layer")
            out[alias] = Source(entity=name)
        elif isinstance(src, Scope):
            out[alias] = Source(scope=src)
    return out


def _projected(scope: Scope) -> set[str] | None:
    """Output column names of a derived scope; None when it selects *."""
    select = scope.expression
    if not isinstance(select, exp.Select):
        return None
    if any(isinstance(e, exp.Star) or (isinstance(e, exp.Column) and isinstance(e.this, exp.Star))
           for e in select.expressions):
        return None
    return set(select.named_selects)


def _lookup(col: exp.Column, scope: Scope, cat: Catalog) -> tuple[str, Any] | None:
    """Resolve a column: ('entity', entity) / ('derived', scope) / ('alias', None)."""
    current: Scope | None = scope
    while current is not None:
        sources = _sources(current, cat, [])
        if col.table:
            src = sources.get(col.table)
            if src is not None:
                return ("entity", src.entity) if src.entity else ("derived", src.scope)
        else:
            hits = []
            for src in sources.values():
                if src.entity and col.name in cat.columns.get(src.entity, {}):
                    hits.append(("entity", src.entity))
                elif src.scope is not None:
                    names = _projected(src.scope)
                    if names is None or col.name in names:
                        hits.append(("derived", src.scope))
            if len(hits) >= 1:
                return hits[0]
            if isinstance(current.expression, exp.Select) and col.name in current.expression.named_selects:
                return ("alias", None)
        current = current.parent
    return None


def check_columns(tree: exp.Expression, cat: Catalog) -> list[str]:
    """Every column reference must exist where the SQL says it does."""
    problems: list[str] = []
    for scope in traverse_scope(tree):
        sources = _sources(scope, cat, problems)
        named = set(scope.expression.named_selects) if isinstance(scope.expression, exp.Select) else set()
        for col in scope.columns:
            name = col.name
            if col.table:
                src = sources.get(col.table)
                if src is None:
                    if _lookup(col, scope, cat) is None:
                        problems.append(f"'{col.sql()}' uses the alias '{col.table}', which is not "
                                        f"defined in its FROM clause")
                    continue
                if src.entity:
                    cols = cat.columns.get(src.entity, {})
                    if cols and name not in cols:
                        problems.append(f"{src.entity} has no column '{name}' (in '{col.sql()}')"
                                        f"{_suggest(name, set(cols))}")
                elif src.scope is not None:
                    names = _projected(src.scope)
                    if names is not None and name not in names:
                        problems.append(f"the derived table '{col.table}' has no column '{name}'")
                continue
            matches = [s for s in sources.values()
                       if (s.entity and name in cat.columns.get(s.entity, {}))
                       or (s.scope is not None and (_projected(s.scope) is None or name in _projected(s.scope)))]
            entity_matches = [s.entity for s in matches if s.entity]
            if len(set(entity_matches)) > 1 and len(entity_matches) == len(matches):
                problems.append(f"column '{name}' is ambiguous: it exists in {sorted(set(entity_matches))}; "
                                f"qualify it with a table alias")
            elif not matches and name not in named and _lookup(col, scope, cat) is None:
                everywhere = set().union(*(cat.columns.get(s.entity, {}) for s in sources.values() if s.entity)) \
                    if sources else set()
                tables = sorted(s.entity for s in sources.values() if s.entity)
                problems.append(f"column '{name}' does not exist in {tables or 'the FROM clause'}"
                                f"{_suggest(name, everywhere)}")
    return problems


# ---------------------------------------------------------------------------
# 3. SQL against IR
# ---------------------------------------------------------------------------

@dataclass
class _Ctx:
    """What the period evaluator needs to know about the entity's scope."""

    cat: Catalog
    entity: str
    time_column: str | None
    year_column: str | None
    entity_aliases: set[str]
    calendar_aliases: dict[str, dict[str, str]]   # alias -> {projected name -> calendar column}
    linked: bool = False
    stray_dates: list[str] = field(default_factory=list)
    scope: Scope | None = None
    filter_columns: set[str] = field(default_factory=set)


def _literal(node: exp.Expression) -> Any:
    """Constant value of an expression, or raise Unverifiable."""
    node = node.unnest() if isinstance(node, exp.Paren) else node
    if isinstance(node, exp.Literal):
        if node.is_string:
            text = node.this
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                return date.fromisoformat(text)
            return text
        number = float(node.this)
        return int(number) if number.is_integer() else number
    if isinstance(node, exp.Boolean):
        return bool(node.this)
    if isinstance(node, exp.Neg):
        return -_literal(node.this)
    if isinstance(node, exp.Cast):
        value = _literal(node.this)
        if node.to.is_type(*exp.DataType.TEMPORAL_TYPES) and isinstance(value, str):
            return date.fromisoformat(value[:10])
        return value
    if isinstance(node, exp.Anonymous) and node.name.lower() == "make_date":
        y, m, d = (_literal(a) for a in node.expressions)
        return date(int(y), int(m), int(d))
    if isinstance(node, (exp.Add, exp.Sub)):
        base, step = _literal(node.this), node.expression
        if isinstance(base, date) and isinstance(step, exp.Interval):
            return _shift(base, step, -1 if isinstance(node, exp.Sub) else 1)
    raise Unverifiable(f"'{node.sql()}' is not a constant the verifier can evaluate")


def _shift(day: date, interval: exp.Interval, sign: int) -> date:
    text = f"{interval.this.this if isinstance(interval.this, exp.Literal) else interval.this} " \
           f"{interval.unit.sql() if interval.unit else ''}".lower().replace("'", "")
    match = re.fullmatch(r"\s*(\d+)\s*(day|days|month|months|mon|mons|year|years)\s*", text)
    if not match:
        raise Unverifiable(f"interval '{interval.sql()}' is not supported")
    n, unit = int(match.group(1)) * sign, match.group(2)
    if unit.startswith("day"):
        return day + timedelta(days=n)
    months = n * (12 if unit.startswith("year") else 1)
    y, m = divmod(day.month - 1 + months, 12)
    y += day.year
    return date(y, m + 1, min(day.day, _calendar.monthrange(y, m + 1)[1]))


def _column_source(col: exp.Column, ctx: _Ctx) -> tuple[str, str] | None:
    """('entity'|'calendar'|'other', column) for a column in the entity scope."""
    if col.table:
        if col.table in ctx.entity_aliases:
            return ("entity", col.name)
        if col.table in ctx.calendar_aliases:
            mapped = ctx.calendar_aliases[col.table].get(col.name)
            return ("calendar", mapped) if mapped else ("other", col.name)
        return ("other", col.name)
    if col.name in ctx.cat.columns.get(ctx.entity, {}):
        return ("entity", col.name)
    for mapping in ctx.calendar_aliases.values():
        if col.name in mapping:
            return ("calendar", mapping[col.name])
    return ("other", col.name)


def _time_expr(node: exp.Expression, ctx: _Ctx) -> tuple[str, Callable[[date], Any]] | None:
    """If the expression is a function of the period date, return (grain, f(day))."""
    node = node.unnest() if isinstance(node, exp.Paren) else node
    if isinstance(node, exp.Cast):
        return _time_expr(node.this, ctx)
    if isinstance(node, exp.Column):
        where = _column_source(node, ctx)
        if where is None:
            return None
        kind, name = where
        if kind == "entity" and name == ctx.time_column:
            return ("date", lambda d: d)
        if kind == "entity" and name == ctx.year_column:
            return ("year", lambda d: d.year)
        if kind == "calendar" and name in CALENDAR_COLUMNS:
            return CALENDAR_COLUMNS[name]
        return None
    if isinstance(node, exp.Extract):
        inner = _time_expr(node.expression, ctx)
        unit = node.this.name.lower() if node.this else ""
        if inner and inner[0] == "date":
            if unit == "year":
                return ("year", lambda d: d.year)
            if unit == "quarter":
                return ("quarter", lambda d: (d.month - 1) // 3 + 1)
            if unit == "month":
                return ("month", lambda d: d.month)
            if unit == "day":
                return ("day", lambda d: d.day)
        if inner:
            raise Unverifiable(f"'{node.sql()}' is not supported")
        return None
    if isinstance(node, (exp.TimestampTrunc, exp.DateTrunc)):
        inner = _time_expr(node.this, ctx)
        unit = (node.args.get("unit").name if node.args.get("unit") is not None else "").lower()
        if inner and inner[0] == "date":
            if unit == "year":
                return ("year", lambda d: date(d.year, 1, 1))
            if unit == "quarter":
                return ("quarter", lambda d: date(d.year, 3 * ((d.month - 1) // 3) + 1, 1))
            if unit == "month":
                return ("month", lambda d: d.replace(day=1))
        if inner:
            raise Unverifiable(f"'{node.sql()}' is not supported")
        return None
    if any(_time_expr(c, ctx) for c in node.find_all(exp.Column) if c is not node):
        raise Unverifiable(f"the period column is used inside '{node.sql()}', which the verifier "
                           f"cannot evaluate; compare it directly with DATE literals")
    return None


def _mentions_time(node: exp.Expression, ctx: _Ctx) -> bool:
    """True when the expression references the period column or a calendar column."""
    columns = [node] if isinstance(node, exp.Column) else list(node.find_all(exp.Column))
    for col in columns:
        where = _column_source(col, ctx)
        if where and (where[0] == "calendar" or (where[0] == "entity" and where[1] in
                                                 (ctx.time_column, ctx.year_column))):
            return True
    return False


_OPS: dict[type, Callable[[Any, Any], bool]] = {
    exp.EQ: lambda a, b: a == b, exp.NEQ: lambda a, b: a != b,
    exp.GT: lambda a, b: a > b, exp.GTE: lambda a, b: a >= b,
    exp.LT: lambda a, b: a < b, exp.LTE: lambda a, b: a <= b,
}
_FLIP = {exp.GT: exp.LT, exp.LT: exp.GT, exp.GTE: exp.LTE, exp.LTE: exp.GTE, exp.EQ: exp.EQ, exp.NEQ: exp.NEQ}


def _coerce(value: Any, sample: Any) -> Any:
    if isinstance(sample, date) and isinstance(value, str):
        return date.fromisoformat(value[:10])
    if isinstance(sample, int) and isinstance(value, str) and value.isdigit():
        return int(value)
    if isinstance(sample, bool) and isinstance(value, str):
        return value.lower() in ("true", "t", "1")
    return value


def _is_date_column(node: exp.Expression, ctx: _Ctx) -> str | None:
    """Name of a date column of some entity referenced by the node (not the period column)."""
    if not isinstance(node, exp.Column):
        return None
    where = _column_source(node, ctx)
    if where and where[0] == "calendar":
        return None
    for entity, cols in ctx.cat.columns.items():
        if cols.get(node.name) == "date" and node.name != ctx.time_column:
            if where and where[0] == "entity" and entity != ctx.entity:
                continue
            return node.name
    return None


def _days(node: exp.Expression | None, ctx: _Ctx, universe: list[date]) -> set[date] | None:
    """Days of the book a boolean condition admits, or None when it has no period part."""
    if node is None:
        return None
    if isinstance(node, exp.Paren):
        return _days(node.this, ctx, universe)
    if isinstance(node, exp.And):
        parts = [p for p in (_days(node.left, ctx, universe), _days(node.right, ctx, universe)) if p is not None]
        if not parts:
            return None
        return set.intersection(*parts)
    if isinstance(node, exp.Or):
        left, right = _days(node.left, ctx, universe), _days(node.right, ctx, universe)
        if left is None and right is None:
            return None
        if left is None or right is None:
            raise Unverifiable("an OR mixes a period condition with another condition; "
                               "put the periods in their own parenthesised OR")
        return left | right
    if isinstance(node, exp.Not):
        inner = _days(node.this, ctx, universe)
        return None if inner is None else set(universe) - inner
    if isinstance(node, exp.Between):
        expr = _time_expr(node.this, ctx)
        if expr is None:
            return None
        _, f = expr
        low, high = _literal(node.args["low"]), _literal(node.args["high"])
        return {d for d in universe if _coerce(low, f(d)) <= f(d) <= _coerce(high, f(d))}
    if isinstance(node, exp.In):
        expr = _time_expr(node.this, ctx)
        if expr is None:
            return None
        if node.args.get("query"):
            raise Unverifiable("a period IN (subquery) cannot be verified")
        _, f = expr
        values = [_literal(v) for v in node.expressions]
        return {d for d in universe if any(_coerce(v, f(d)) == f(d) for v in values)}
    if type(node) in _OPS:
        left, right = node.this, node.expression
        if _mentions_time(left, ctx) and _mentions_time(right, ctx):
            ctx.linked = True       # period column joined to the calendar: a link, not a filter
            return None
        lt, rt = _time_expr(left, ctx), _time_expr(right, ctx)
        if not lt and not rt:
            for side, other in ((left, right), (right, left)):
                stray = _is_date_column(side, ctx)
                if stray and stray not in ctx.filter_columns:
                    try:
                        _literal(other)
                    except Unverifiable:
                        continue
                    ctx.stray_dates.append(stray)
            return None
        op = type(node)
        if rt and not lt:
            left, right, op, lt = right, left, _FLIP[op], rt
        _, f = lt
        try:
            value = _literal(right)
        except Unverifiable:
            if isinstance(right, exp.Column) or right.find(exp.Column):
                ctx.linked = True
                return None
            raise
        return {d for d in universe if _OPS[op](f(d), _coerce(value, f(d)))}
    if isinstance(node, exp.Boolean):
        return None
    for col in node.find_all(exp.Column):
        if _time_expr(col, ctx):
            raise Unverifiable(f"the period column is used in '{node.sql()}', which the verifier "
                               f"cannot evaluate")
    return None


def _calendar_aliases(scope: Scope, cat: Catalog) -> dict[str, dict[str, str]]:
    """Aliases in the scope that are ai.calendar, or a derived table selecting from it."""
    out: dict[str, dict[str, str]] = {}
    for alias, src in scope.sources.items():
        if isinstance(src, exp.Table) and f"{(src.db or '').lower()}.{src.name.lower()}" == CALENDAR:
            out[alias] = {c: c for c in cat.columns[CALENDAR]}
        elif isinstance(src, Scope) and isinstance(src.expression, exp.Select):
            inner = [s for s in src.sources.values() if isinstance(s, exp.Table)]
            if len(inner) == 1 and f"{(inner[0].db or '').lower()}.{inner[0].name.lower()}" == CALENDAR:
                mapping = {}
                for projection in src.expression.expressions:
                    target = projection.unalias() if isinstance(projection, exp.Alias) else projection
                    if isinstance(target, exp.Column) and target.name in cat.columns[CALENDAR]:
                        mapping[projection.alias_or_name] = target.name
                out[alias] = mapping
    return out


def _conditions(scope: Scope) -> list[exp.Expression]:
    select = scope.expression
    out = []
    if select.args.get("where") is not None:
        out.append(select.args["where"].this)
    for join in select.args.get("joins") or []:
        if join.args.get("on") is not None:
            out.append(join.args["on"])
    return out


def _conjuncts(node: exp.Expression) -> list[exp.Expression]:
    node = node.unnest() if isinstance(node, exp.Paren) else node
    if isinstance(node, exp.And):
        return _conjuncts(node.left) + _conjuncts(node.right)
    return [node]


def _aggregates(tree: exp.Expression) -> list[exp.Expression]:
    return [a for a in tree.find_all(exp.AggFunc)]


def _metric_signature(metric: dict[str, Any]) -> list[tuple[str, str]]:
    """(function, column or *) pairs the metric's expression aggregates."""
    tree = sqlglot.parse_one(f"SELECT {metric['expression']}", read="postgres")
    out = []
    for agg in tree.find_all(exp.AggFunc):
        if agg.find_ancestor(exp.Window) is not None and agg.parent is not None and isinstance(agg.parent, exp.Window):
            continue
        name = agg.key.lower()
        arg = agg.this
        if isinstance(arg, exp.Distinct):
            arg = arg.expressions[0] if arg.expressions else None
        column = "*" if arg is None or isinstance(arg, exp.Star) else (arg.name if isinstance(arg, exp.Column) else arg.sql())
        if (name, column) not in out:
            out.append((name, column))
    return out


def _is_period_template(metric: dict[str, Any]) -> bool:
    """True when the metric's 'filter' only says which date to restrict (a template)."""
    flt = metric.get("filter") or ""
    return bool(metric.get("time_column")) and metric["time_column"] in flt and "YYYY" in flt


def check_consistency(tree: exp.Expression, ir: dict[str, Any], cat: Catalog) -> tuple[list[str], list[str]]:
    """The SQL against the IR. Returns (problems, checks that passed)."""
    problems: list[str] = []
    passed: list[str] = []
    metric = cat.metrics[ir["metric"]]
    entity = metric["entity"]
    permitted = set(metric.get("permitted_joins") or [])
    grain = _grain(metric.get("counting_grain"))

    scopes = list(traverse_scope(tree))
    entity_scopes = [s for s in scopes if any(
        isinstance(src, exp.Table) and f"{(src.db or '').lower()}.{src.name.lower()}" == entity
        for src in s.sources.values())]
    if not entity_scopes:
        tables = sorted({f"{t.db}.{t.name}" for t in tree.find_all(exp.Table) if t.db})
        return [f"metric {ir['metric']} is defined on {entity}, but the SQL reads {tables}"], passed
    if len(entity_scopes) > 1:
        problems.append(f"{entity} is read in more than one place; the verifier needs it in one query block")
    scope = entity_scopes[0]
    passed.append("entity")

    # Joins: declared, permitted, and following the declared columns.
    aliases = {a for a, s in scope.sources.items() if isinstance(s, exp.Table)
               and f"{(s.db or '').lower()}.{s.name.lower()}" == entity}
    others = {a: f"{(s.db or '').lower()}.{s.name.lower()}" for a, s in scope.sources.items()
              if isinstance(s, exp.Table) and a not in aliases}
    if len(aliases) > 1:
        problems.append(f"{entity} is joined to itself, which repeats rows")
    for alias, other in others.items():
        if other in permitted:
            continue
        card = cat.joins.get((entity, other), {}).get("cardinality")
        if card and card.endswith("to-many"):
            problems.append(f"joining {entity} to {other} is {card}: it repeats every {entity} row once per "
                            f"{other} row and inflates counts and sums; aggregate {other} in a subquery first "
                            f"or answer from {entity} alone")
        elif card:
            problems.append(f"{other} is not a permitted join for metric {ir['metric']} "
                            f"(permitted: {sorted(permitted) or 'none'})")
        else:
            problems.append(f"{other} is not a permitted join for metric {ir['metric']} (permitted: "
                            f"{sorted(permitted) or 'none'}): there is no declared to-one path from {entity}, "
                            f"so the join can repeat or drop {entity} rows")
    for alias, src in scope.sources.items():
        if isinstance(src, Scope) and alias not in _calendar_aliases(scope, cat):
            inner_group = src.expression.args.get("group") if isinstance(src.expression, exp.Select) else None
            if inner_group is None and not src.expression.args.get("distinct"):
                problems.append(f"the derived table '{alias}' is joined to {entity} without being aggregated "
                                f"to one row per join key, so it can repeat rows")
    if not any(p.startswith(("joining", "there is no declared", "the derived", f"{entity} is joined"))
               or "permitted join" in p for p in problems):
        passed.append("joins")

    # Periods: evaluate the filter day by day over the book.
    universe = [d for d in (cat.book_from + timedelta(days=i)
                            for i in range((cat.book_to - cat.book_from).days + 1))]
    ctx = _Ctx(cat=cat, entity=entity, time_column=metric.get("time_column"),
               year_column=cat.period_columns.get(entity, {}).get("year"),
               entity_aliases=aliases, calendar_aliases=_calendar_aliases(scope, cat), scope=scope,
               filter_columns={f.get("column") for f in ir.get("filters") or [] if isinstance(f, dict)})
    try:
        day_sets = [s for s in (_days(c, ctx, universe) for c in _conditions(scope)) if s is not None]
        for alias, src in scope.sources.items():
            if isinstance(src, Scope) and alias in ctx.calendar_aliases and isinstance(src.expression, exp.Select):
                inner_where = src.expression.args.get("where")
                if inner_where is not None:
                    cal_ctx = _Ctx(cat=cat, entity=CALENDAR, time_column="date_key", year_column="year",
                                   entity_aliases=set(src.sources), calendar_aliases={a: {c: c for c in cat.columns[CALENDAR]} for a in src.sources})
                    inner = _days(inner_where.this, cal_ctx, universe)
                    if inner is not None:
                        day_sets.append(inner)
                        ctx.linked = ctx.linked or True
        sql_days = set.intersection(*day_sets) if day_sets else None
        if ctx.calendar_aliases and not ctx.linked and sql_days is not None and ctx.time_column:
            problems.append(f"ai.calendar is filtered but never joined to {ctx.time_column}, so the "
                            f"filter does not restrict {entity}")
        wanted = ir_days(ir, cat)
        if wanted is None:
            if sql_days is not None and sql_days != set(universe):
                problems.append(f"the SQL restricts {ctx.time_column} to {_ranges(sql_days)}, but the IR asks "
                                f"for no period")
        elif sql_days is None:
            problems.append(f"the SQL has no filter on {ctx.time_column}; the IR asks for {_ranges(wanted)}")
        elif sql_days != wanted:
            problems.append(f"the SQL selects {ctx.time_column} {_ranges(sql_days)}, but the IR asks for "
                            f"{_ranges(wanted)}")
        else:
            passed.append("periods")
    except Unverifiable as exc:
        problems.append(f"cannot verify the period filter: {exc}")
    for stray in sorted(set(ctx.stray_dates)):
        problems.append(f"the SQL filters on {stray}, but metric {ir['metric']} defines its period on "
                        f"{ctx.time_column or 'no date'}; declare it in the IR filters if it is intended")

    # Measure: the metric's aggregates, at the metric's grain.
    aggs = _aggregates(tree)
    found = []
    for agg in aggs:
        arg = agg.this
        distinct = isinstance(arg, exp.Distinct)
        if distinct:
            arg = arg.expressions[0] if arg.expressions else None
        column = "*" if arg is None or isinstance(arg, (exp.Star, exp.Literal)) \
            else (arg.name if isinstance(arg, exp.Column) else arg.sql())
        found.append((agg.key.lower(), column, distinct, agg))
    plain_counts = [c for f, c, d, _ in found if f == "count" and (not d or c in grain)]
    distinct_other = [c for f, c, d, _ in found if f == "count" and d and c not in grain and c != "*"]
    if ("count", "*") in _metric_signature(metric) and distinct_other and not plain_counts:
        problems.append(f"count(DISTINCT {distinct_other[0]}) counts {distinct_other[0]}, but metric "
                        f"{ir['metric']} counts {', '.join(grain)}")
    missing = []
    for name, column in _metric_signature(metric):
        ok = any(f == name and (c == column or (column == "*" and name == "count" and (c in grain or c == "*")))
                 for f, c, _, _ in found)
        if not ok:
            missing.append(f"{name}({column})")
    if missing:
        problems.append(f"the SQL does not compute metric {ir['metric']} = {metric['expression']} "
                        f"(missing {', '.join(missing)})")
    if metric.get("expression") and "is_problematic" in metric["expression"]:
        if not any("is_problematic" in agg.sql() or (agg.find_ancestor(exp.Filter) is not None
                   and "is_problematic" in agg.find_ancestor(exp.Filter).sql()) for agg in aggs) \
                and "is_problematic" not in tree.sql():
            problems.append("the SQL does not use is_problematic, the certified definition")
    if metric.get("filter") and not _is_period_template(metric):
        flt = sqlglot.parse_one(metric["filter"], read="postgres")
        column = next(flt.find_all(exp.Column)).name
        value = next(flt.find_all(exp.Literal)).this
        if not any(isinstance(node, exp.EQ) and column in {c.name for c in node.find_all(exp.Column)}
                   and value in {lit.this for lit in node.find_all(exp.Literal)} for node in tree.find_all(exp.EQ)):
            problems.append(f"the SQL does not apply the metric's filter {metric['filter']}")
    if not any(p.startswith(("the SQL does not compute", "count(DISTINCT", "the SQL does not use",
                             "the SQL does not apply")) for p in problems):
        passed.append("measure")

    # Grouping.
    group_exprs = _group_expressions(scopes)
    pivots = [c.name for agg in aggs for case in agg.find_all(exp.Case) for c in case.find_all(exp.Column)]
    pivots += [c.name for f in tree.find_all(exp.Filter) for c in f.find_all(exp.Column)]
    for item in ir.get("group_by") or []:
        if item in PERIOD_GRAINS:
            if not any(_period_grain(g, s, ctx, cat) == item for g, s in group_exprs):
                problems.append(f"the IR groups by {item}, but the SQL does not group by the {item} of "
                                f"{ctx.time_column}")
        elif not any(item in {c.name for c in g.find_all(exp.Column)} or
                     (isinstance(g, exp.Column) and g.name == item) for g, _ in group_exprs):
            if item in pivots:
                problems.append(f"the IR groups by {item}, but the SQL spreads {item} across columns "
                                f"(CASE/FILTER per value); return one row per {item} with GROUP BY {item}")
            else:
                problems.append(f"the IR groups by {item}, but the SQL does not")
    if not ir.get("group_by"):
        named = [g.sql() for g, _ in group_exprs if g.find(exp.Column) is not None]
        if named:
            problems.append(f"the IR asks for one total, but the SQL groups by {', '.join(named)}")
    if not any(p.startswith(("the IR groups by", "the IR asks for one total")) for p in problems):
        passed.append("grouping")

    # Filters: every requested one present; nothing unrequested narrowing the entity.
    for flt in ir.get("filters") or []:
        col, value = flt.get("column"), flt.get("value")
        hit = False
        for node in tree.find_all(exp.EQ, exp.In, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.Is):
            if col in {c.name for c in node.find_all(exp.Column)}:
                lits = {str(l.this).lower() for l in node.find_all(exp.Literal)}
                values = value if isinstance(value, list) else [value]
                if value is None or all(str(v).lower() in lits for v in values) or isinstance(node, exp.Is):
                    hit = True
        if not hit:
            problems.append(f"the IR filters {col} {flt.get('op', '=')} {value!r}, but the SQL does not")
    allowed_filter = ctx.filter_columns | {ctx.time_column, ctx.year_column}
    if metric.get("filter") and not _is_period_template(metric):
        allowed_filter |= {c.name for c in sqlglot.parse_one(metric["filter"], read="postgres").find_all(exp.Column)}
    for condition in _conditions(scope):
        for atom in _conjuncts(condition):
            if isinstance(atom, exp.Is) or (isinstance(atom, exp.Not) and isinstance(atom.this, exp.Is)):
                continue
            cols = [c for c in atom.find_all(exp.Column)]
            if len(cols) != 1:
                continue
            where = _column_source(cols[0], ctx)
            if where and where[0] == "calendar":
                continue
            if cols[0].name not in allowed_filter and cols[0].name not in grain:
                try:
                    for lit in atom.find_all(exp.Literal):
                        _literal(lit)
                except Unverifiable:
                    continue
                if any(True for _ in atom.find_all(exp.Literal)):
                    problems.append(f"the SQL filters on {cols[0].name} ('{atom.sql()}'), which the IR does "
                                    f"not ask for")
    if not any(p.startswith(("the IR filters", "the SQL filters on")) for p in problems):
        passed.append("filters")

    # Limit.
    outer = tree if isinstance(tree, exp.Select) else tree.find(exp.Select)
    limit = outer.args.get("limit") if outer is not None else None
    limit_value = None
    if limit is not None:
        try:
            limit_value = int(_literal(limit.expression))
        except (Unverifiable, TypeError, ValueError):
            limit_value = -1
    if ir.get("limit") and limit_value != ir["limit"]:
        problems.append(f"the IR asks for the top {ir['limit']}, but the SQL limit is {limit_value}")
    elif not ir.get("limit") and limit_value is not None and limit_value < config.GUARD_MAX_ROWS:
        problems.append(f"the SQL keeps only {limit_value} rows, but the IR asks for all of them")
    else:
        passed.append("limit")
    return problems, passed


def _group_expressions(scopes: list[Scope]) -> list[tuple[exp.Expression, Scope]]:
    """GROUP BY expressions of every scope, with ordinals and aliases resolved."""
    out = []
    for scope in scopes:
        select = scope.expression
        if not isinstance(select, exp.Select) or select.args.get("group") is None:
            continue
        projections = select.expressions
        by_alias = {p.alias: p.unalias() for p in projections if isinstance(p, exp.Alias)}
        for g in select.args["group"].expressions:
            if isinstance(g, exp.Literal) and not g.is_string:
                index = int(g.this) - 1
                if 0 <= index < len(projections):
                    g = projections[index].unalias() if isinstance(projections[index], exp.Alias) else projections[index]
            elif isinstance(g, exp.Column) and not g.table and g.name in by_alias:
                g = by_alias[g.name]
            out.append((g, scope))
    return out


def _period_grain(expr: exp.Expression, scope: Scope, ctx: _Ctx, cat: Catalog) -> str | None:
    """year / quarter / month when a GROUP BY expression is a period of the date."""
    local = _Ctx(cat=cat, entity=ctx.entity, time_column=ctx.time_column, year_column=ctx.year_column,
                 entity_aliases=ctx.entity_aliases | {a for a, s in scope.sources.items()
                                                     if isinstance(s, exp.Table) and
                                                     f"{(s.db or '').lower()}.{s.name.lower()}" == ctx.entity},
                 calendar_aliases={**ctx.calendar_aliases, **_calendar_aliases(scope, cat)})
    try:
        found = _time_expr(expr, local)
    except Unverifiable:
        found = None
    if found:
        return {"date": None, "day": None}.get(found[0], found[0])
    if isinstance(expr, exp.Case) and any(_time_expr(c, local) for c in expr.find_all(exp.Column)):
        return "year"
    if isinstance(expr, exp.Column) and scope.sources.get(expr.table) is not None:
        src = scope.sources[expr.table]
        if isinstance(src, Scope) and isinstance(src.expression, exp.Select):
            for projection in src.expression.expressions:
                if projection.alias_or_name == expr.name:
                    return _period_grain(projection.unalias() if isinstance(projection, exp.Alias) else projection,
                                         src, ctx, cat)
    return None


def verify_static(sql: str, ir: Any, question: str = "", cat: Catalog | None = None) -> Verification:
    """Everything that can be checked without the database. Never raises."""
    cat = cat or default_catalog()
    result = Verification()
    result.findings = check_ir(ir, cat, question)
    if result.findings:
        return result
    result.checks.append("ir")
    try:
        tree = sqlglot.parse_one(sql, read="postgres")
    except sqlglot.errors.ParseError as exc:
        result.stage, result.findings = "columns", [f"the SQL does not parse: {str(exc).splitlines()[0]}"]
        return result
    result.stage = "columns"
    result.findings = list(dict.fromkeys(check_columns(tree, cat)))
    if result.findings:
        return result
    result.checks.append("columns")
    result.stage = "consistency"
    try:
        problems, passed = check_consistency(tree, ir, cat)
    except Unverifiable as exc:
        problems, passed = [f"cannot verify: {exc}"], []
    except Exception as exc:  # noqa: BLE001 - a verifier crash is a refusal, not an answer
        LOGGER.exception("verifier error")
        problems, passed = [f"the verifier could not analyse this SQL ({type(exc).__name__}); "
                            f"write it as one SELECT over the metric's entity"], []
    result.findings, result.checks = list(dict.fromkeys(problems)), result.checks + passed
    if not problems:
        result.ok = True
    return result


# ---------------------------------------------------------------------------
# 4. Recompute from the IR, and the complete verified run
# ---------------------------------------------------------------------------

def canonical_sql(ir: dict[str, Any], cat: Catalog | None = None) -> str:
    """SQL written from the IR alone, with the certified metric expression."""
    cat = cat or default_catalog()
    metric = cat.metrics[ir["metric"]]
    entity = metric["entity"]
    time_col = metric.get("time_column")
    expression = sqlglot.parse_one(metric["expression"], read="postgres")
    expression = expression.transform(
        lambda n: exp.column(n.name, table="e") if isinstance(n, exp.Column) and not n.table else n)
    joins, selects, groups = [], [], []
    needed: dict[str, str] = {}

    def ref(column: str) -> str:
        if column in cat.columns[entity]:
            return f"e.{column}"
        for other in metric.get("permitted_joins") or []:
            if column in cat.columns.get(other, {}):
                alias = needed.setdefault(other, f"j{len(needed)}")
                return f"{alias}.{column}"
        raise ValueError(f"column {column} is not reachable from {entity}")

    for index, item in enumerate(ir.get("group_by") or []):
        if item == "year":
            expr = f"extract(year FROM e.{time_col})::int"
        elif item == "quarter":
            expr = f"extract(quarter FROM e.{time_col})::int"
        elif item == "month":
            expr = f"to_char(e.{time_col}, 'YYYY-MM')"
            # other spellings a correct answer may use for the same month
            for alt, alt_expr in enumerate((f"date_trunc('month', e.{time_col})::date",
                                            f"trim(to_char(e.{time_col}, 'Month'))",
                                            f"extract(month FROM e.{time_col})::int"), start=1):
                selects.append(f"{alt_expr} AS g{index}_alt{alt}")
                groups.append(alt_expr)
        else:
            expr = ref(item)
        selects.append(f"{expr} AS g{index}")
        groups.append(expr)
    conditions = []
    if metric.get("filter") and not _is_period_template(metric):
        conditions.append(f"({sqlglot.parse_one(metric['filter'], read='postgres').transform(lambda n: exp.column(n.name, table='e') if isinstance(n, exp.Column) and not n.table else n).sql()})")
    if ir.get("time"):
        spans = [f"(e.{time_col} >= DATE '{p['from']}' AND e.{time_col} < DATE '{p['to']}')"
                 for p in ir["time"]["periods"]]
        conditions.append("(" + " OR ".join(spans) + ")")
    for flt in ir.get("filters") or []:
        col, op, value = ref(flt["column"]), str(flt.get("op", "=")).lower(), flt.get("value")
        if op in ("is null", "is not null"):
            conditions.append(f"{col} {op.upper()}")
        elif op in ("in", "not in"):
            values = ", ".join(_quote(v) for v in (value if isinstance(value, list) else [value]))
            conditions.append(f"{col} {op.upper()} ({values})")
        else:
            conditions.append(f"{col} {op} {_quote(value)}")
    for other, alias in needed.items():
        join = cat.joins[(entity, other)]
        joins.append(f"LEFT JOIN {other} {alias} ON {alias}.{join['right']} = e.{join['left']}")
    sql = (f"SELECT {', '.join(selects + [expression.sql() + ' AS value'])} FROM {entity} e "
           + " ".join(joins)
           + (f" WHERE {' AND '.join(conditions)}" if conditions else "")
           + (f" GROUP BY {', '.join(groups)}" if groups else ""))
    if ir.get("limit"):
        sql += f" ORDER BY value {'ASC' if ir.get('order') == 'asc' else 'DESC'} LIMIT {int(ir['limit'])}"
    return sql


def _quote(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def compare_with_canonical(canonical: list[dict[str, Any]], generated: list[dict[str, Any]]) -> list[str]:
    """Every (group, value) the IR implies must appear in the generated result."""
    from src import evaluate  # noqa: PLC0415 - avoid an import cycle at module load

    missing = []
    for row in canonical:
        value = evaluate.numeric(row["value"])
        if value is None:
            continue
        dims: dict[str, list[Any]] = {}
        for key, cell in row.items():
            if re.fullmatch(r"g\d+(_alt\d+)?", key) and cell is not None:
                dims.setdefault(key.split("_")[0], []).append(cell)
        alternatives = [tuple(v) for _, v in sorted(dims.items())]

        def matches(generated_row: dict[str, Any], alternatives=alternatives, value=value) -> bool:
            cells = list(generated_row.values())
            if not all(any(evaluate.cell_is_key(c, alts) for c in cells) for alts in alternatives):
                return False
            return any((n := evaluate.numeric(c)) is not None and evaluate.close(n, value) for c in cells)

        if not any(matches(g) for g in generated):
            label = " / ".join(str(a[0]) for a in alternatives)
            missing.append(f"{label} = {value}" if label else f"{value}")
    if missing:
        sample = "; ".join(missing[:3]) + (f" (+{len(missing) - 3} more)" if len(missing) > 3 else "")
        return [f"the result does not match the certified computation of the declared IR "
                f"({len(missing)} of {len(canonical)} expected values absent: {sample}); "
                f"check joins, filters and grouping"]
    return []


def explain(conn: psycopg.Connection, sql: str) -> str | None:
    """Have PostgreSQL plan the statement without executing it."""
    try:
        with conn.cursor() as cur:
            cur.execute("BEGIN READ ONLY")
            cur.execute(f"SET LOCAL statement_timeout = {config.GUARD_STATEMENT_TIMEOUT_MS}")
            cur.execute(f"EXPLAIN {sql}")
            cur.execute("COMMIT")
        return None
    except psycopg.Error as exc:
        conn.rollback()
        return str(exc).strip().splitlines()[0]


def _jsonable(value: Any) -> Any:
    from decimal import Decimal  # noqa: PLC0415
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def run_verified(conn: psycopg.Connection, sql: str, ir: Any, question: str = "",
                 cat: Catalog | None = None) -> Verification:
    """Verify, plan, execute and recompute. Rows are returned only when all agree.

    :param conn: The caller's own authenticated connection, so row level
        security applies to both the generated and the recomputed query.
    :param sql: The model's SQL.
    :param ir: The model's IR (any type; malformed input is a finding).
    :param question: The user's question, for the years/quarters cross-check.
    :returns: A :class:`Verification`; ``rows`` is set only when ``ok``.
    """
    cat = cat or default_catalog()
    result = verify_static(sql, ir, question, cat)
    if not result.ok:
        return result
    result.ok = False
    verdict = sql_guard.guard(sql)
    if not verdict.allowed:
        result.stage, result.findings = "guard", [f"the SQL guard rejected it: {verdict.reason}"]
        return result
    result.checks.append("guard")
    result.executed_sql = verdict.rewritten_sql
    problem = explain(conn, verdict.rewritten_sql)
    if problem:
        result.stage, result.findings = "plan", [f"PostgreSQL rejected the plan before execution: {problem}"]
        return result
    result.checks.append("plan")
    _, rows, error = sql_guard.execute_guarded(conn, sql)
    if error:
        result.stage, result.findings = "execute", [f"the database rejected it: {error}"]
        return result
    generated = [{k: _jsonable(v) for k, v in row.items()} for row in rows or []]
    result.canonical_sql = canonical_sql(ir, cat)
    _, canonical_rows, error = sql_guard.execute_guarded(conn, result.canonical_sql)
    if error:
        result.stage, result.findings = "recompute", [f"the certified recomputation failed: {error}"]
        return result
    canonical = [{k: _jsonable(v) for k, v in row.items()} for row in canonical_rows or []]
    result.stage = "recompute"
    result.findings = compare_with_canonical(canonical, generated)
    if result.findings:
        return result
    result.checks.append("recompute")
    result.stage, result.ok, result.rows = "verified", True, generated
    return result
