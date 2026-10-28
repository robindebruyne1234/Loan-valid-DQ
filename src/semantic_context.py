"""Render the semantic layer into the LLM context pack, and validate it.

Two responsibilities:

* **Render.** Turn ``semantic/semantic_layer.yaml`` into the Markdown block
  that goes into the prompt. The renderer, not the prompt template, decides
  what the model is told, so there is one place to look when an answer comes
  back wrong.
* **Validate.** Check the semantic layer against the live database. A semantic
  layer that drifts from the schema is worse than none: it gives the model
  confident, wrong information. ``--validate`` fails when a described entity or
  column does not exist, when an existing column is undescribed, or when a
  declared grain is not actually one row per key.

Run with ``make semantic`` (renders and validates).
"""

from __future__ import annotations

import argparse
from typing import Any

import psycopg
import sqlglot
import yaml
from sqlglot import exp

from src import config, db

LOGGER = db.setup_logging("semantic")

#: Rendered context pack, written next to the semantic layer so it can be
#: inspected and diffed. This exact text is what the model receives.
CONTEXT_PACK_MD = config.SEMANTIC_DIR / "context_pack.md"


def load_semantic_layer(path: Any = None) -> dict[str, Any]:
    """Load the semantic layer YAML.

    :param path: Optional path; defaults to
        :data:`src.config.SEMANTIC_LAYER_YAML`.
    :returns: The parsed semantic layer.
    """
    path = path or config.SEMANTIC_LAYER_YAML
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def validate(layer: dict[str, Any], conn: psycopg.Connection) -> list[str]:
    """Check the semantic layer against the database it claims to describe.

    :param layer: Parsed semantic layer.
    :param conn: Open connection.
    :returns: List of problems; empty when the layer and the schema agree.
    """
    problems: list[str] = []

    live = db.fetch_all(
        conn,
        """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = %s
        ORDER BY table_name, ordinal_position
        """,
        (config.SCHEMA_AI,),
    )
    live_columns: dict[str, dict[str, str]] = {}
    for row in live:
        live_columns.setdefault(row["table_name"], {})[row["column_name"]] = row["data_type"]

    described: set[str] = set()
    for entity in layer["entities"]:
        name = entity["name"]
        if not name.startswith(f"{config.SCHEMA_AI}."):
            problems.append(f"{name}: entities must live in the {config.SCHEMA_AI} schema")
            continue
        view = name.split(".", 1)[1]
        described.add(view)
        if view not in live_columns:
            problems.append(f"{name}: described in the semantic layer but does not exist")
            continue

        names = [column["name"] for column in entity["columns"]]
        for duplicate in sorted({n for n in names if names.count(n) > 1}):
            problems.append(f"{name}.{duplicate}: described more than once")
        described_columns = set(names)
        actual_columns = set(live_columns[view])
        for missing in sorted(described_columns - actual_columns):
            problems.append(f"{name}.{missing}: described but not present in the view")
        for undescribed in sorted(actual_columns - described_columns):
            problems.append(
                f"{name}.{undescribed}: present in the view but not described "
                f"(an undocumented column is one the model will guess at)"
            )
        for column in entity["columns"]:
            if not column.get("description"):
                problems.append(f"{name}.{column['name']}: no business description")

        # A declared grain is a promise to the model; verify it.
        key = entity.get("primary_key") or []
        if key:
            key_list = ", ".join(f'"{part}"' for part in key)
            duplicates = db.fetch_value(
                conn,
                f"""
                SELECT count(*) FROM (
                    SELECT {key_list} FROM {name} GROUP BY {key_list} HAVING count(*) > 1
                ) d
                """,
            )
            if duplicates:
                problems.append(
                    f"{name}: declared grain '{entity['grain']}' is false -- "
                    f"{duplicates} duplicate values of ({', '.join(key)})"
                )

        # The row count is published to the model as a sense check, so it
        # must be today's figure. Run as the owner, so it is unfiltered.
        declared_rows = entity.get("row_count_unfiltered")
        if declared_rows is not None:
            actual_rows = int(db.fetch_value(conn, f"SELECT count(*) FROM {name}") or 0)
            if actual_rows != int(declared_rows):
                problems.append(
                    f"{name}: row_count_unfiltered says {declared_rows}, the view has {actual_rows}"
                )

        problems += _validate_joins(entity, conn)

    entity_columns = {
        entity["name"]: {column["name"] for column in entity["columns"]}
        for entity in layer["entities"]
    }
    for metric in layer["metrics"]:
        columns = entity_columns.get(metric["entity"])
        if columns is None:
            # An entity nobody described is an entity nothing checks: the
            # columns the metric relies on could be invented.
            problems.append(
                f"metric {metric['name']}: entity '{metric['entity']}' is not a described entity"
            )
            continue
        time_column = metric.get("time_column")
        if time_column and time_column not in columns:
            problems.append(
                f"metric {metric['name']}: time_column {time_column} is not a column "
                f"of {metric['entity']}"
            )
        for missing in sorted(_metric_columns(metric) - columns - {time_column}):
            problems.append(
                f"metric {metric['name']}: uses {missing}, which is not a column of "
                f"{metric['entity']}"
            )

    for view in sorted(set(live_columns) - described):
        problems.append(
            f"{config.SCHEMA_AI}.{view}: exists but is not described in the semantic layer"
        )

    # Every question must be claimed by at least one entity.
    claimed = {q for entity in layer["entities"] for q in (entity.get("answers") or [])}
    for question_id in config.QUESTION_IDS:
        if question_id not in claimed:
            problems.append(f"{question_id}: no entity declares that it answers this question")

    # Every caveat must name a rule that exists in the rule file.
    rule_ids = {
        rule["rule_id"]
        for rule in yaml.safe_load(config.DQ_RULES_YAML.read_text(encoding="utf-8"))["rules"]
    }
    for caveat in layer["caveats"]:
        if caveat["rule_id"] not in rule_ids:
            problems.append(
                f"caveat {caveat['id']}: rule_id {caveat['rule_id']} is not in dq_rules.yaml"
            )

    if problems:
        for problem in problems:
            LOGGER.error("semantic layer -> %s", problem)
    else:
        LOGGER.info(
            "semantic layer validated -> %d entities, %d columns, %d caveats all "
            "agree with the database",
            len(layer["entities"]),
            sum(len(e["columns"]) for e in layer["entities"]),
            len(layer["caveats"]),
        )
    return problems


def _metric_columns(metric: dict[str, Any]) -> set[str]:
    """Columns a metric's expression, filter and grouping refer to.

    Parsed, not pattern-matched, so a function name or a string literal is
    never mistaken for a column.

    :param metric: One entry of the ``metrics:`` block.
    :returns: Column names, unqualified.
    """
    referenced = {metric["group_by"]} if metric.get("group_by") else set()
    for key in ("expression", "filter"):
        if metric.get(key):
            tree = sqlglot.parse_one(str(metric[key]), dialect="postgres")
            referenced |= {column.name for column in tree.find_all(exp.Column)}
    return referenced


#: Join cardinalities the semantic layer may declare, and what each promises:
#: (left side unique on its join column, right side unique on its join column).
CARDINALITIES: dict[str, tuple[bool, bool]] = {
    "one-to-one": (True, True),
    "one-to-many": (True, False),
    "many-to-one": (False, True),
}


def _join_columns(on: str) -> tuple[str, str]:
    """Split a declared join condition into its left and right column.

    :param on: ``"column"`` (same name on both sides) or ``"left = right"``.
    :returns: Tuple of (left column, right column).
    """
    if "=" in on:
        left, right = (part.strip() for part in on.split("=", 1))
        return left, right
    return on.strip(), on.strip()


def _validate_joins(entity: dict[str, Any], conn: psycopg.Connection) -> list[str]:
    """Check each declared join against the data: columns, cardinality, coverage.

    A join path is advice the model follows without being able to check it,
    so a wrong cardinality is a silent double count and an undeclared
    unmatched side is a silent row loss. Both are measured, not trusted.

    :param entity: One entity from the semantic layer.
    :param conn: Open connection (owner, so unfiltered).
    :returns: Problems found; empty when every join is as declared.
    """
    problems: list[str] = []
    name = entity["name"]
    for join in entity.get("joins") or []:
        target, label = join["to"], f"{name} -> {join['to']}"
        cardinality = join.get("cardinality")
        if cardinality not in CARDINALITIES:
            problems.append(f"{label}: cardinality must be one of {sorted(CARDINALITIES)}")
            continue
        left, right = _join_columns(join["on"])
        try:
            left_max = int(db.fetch_value(conn, f'SELECT coalesce(max(n), 0) FROM (SELECT count(*) n FROM {name} GROUP BY "{left}") z') or 0)
            right_max = int(db.fetch_value(conn, f'SELECT coalesce(max(n), 0) FROM (SELECT count(*) n FROM {target} GROUP BY "{right}") z') or 0)
            unmatched = int(db.fetch_value(
                conn,
                f'SELECT count(*) FROM {name} x WHERE NOT EXISTS '
                f'(SELECT 1 FROM {target} y WHERE y."{right}" = x."{left}")',
            ) or 0)
        except psycopg.Error as exc:
            conn.rollback()
            problems.append(f"{label} on {join['on']}: does not run ({exc.diag.message_primary})")
            continue
        left_unique, right_unique = CARDINALITIES[cardinality]
        if left_unique and left_max > 1:
            problems.append(f"{label}: declared {cardinality}, but {left} repeats up to {left_max} times in {name}")
        if right_unique and right_max > 1:
            problems.append(f"{label}: declared {cardinality}, but {right} repeats up to {right_max} times in {target}")
        if unmatched and not join.get("optional"):
            problems.append(
                f"{label}: {unmatched} rows of {name} have no match, so an INNER JOIN drops "
                f"them; declare optional: true"
            )
    return problems


def render_context_pack(layer: dict[str, Any]) -> str:
    """Render the semantic layer as the Markdown context pack for the prompt.

    :param layer: Parsed semantic layer.
    :returns: The context pack text.
    """
    meta = layer["meta"]
    out: list[str] = [
        f"# {meta['name']} -- semantic layer v{meta['version']}",
        "",
        meta["description"].strip(),
        "",
        f"- SQL dialect: **{meta['dialect']} {meta['dialect_version']}**",
        f"- Query only the **`{meta['query_schema']}`** schema.",
        f"- All money is in **{meta['currency']}**. {meta['currency_note'].strip()}",
        f"- Data covers **{meta['date_range']['from']} to {meta['date_range']['to']}**. "
        f"{meta['date_range_note'].strip()}",
        "",
        "## Rules you must follow",
        "",
    ]
    for rule in layer["query_rules"]:
        out.append(f"{rule['id']}. **{rule['rule'].strip()}**  ")
        out.append(f"   _Why:_ {rule['why'].strip()}")
    out.append("")

    out += ["## Business glossary", ""]
    for term in layer["glossary"]:
        out.append(f"**{term['term']}** -- {term['definition'].strip()}")
        if term.get("not"):
            out.append(f"  - NOT: {term['not'].strip()}")
        if term.get("careful"):
            out.append(f"  - Careful: {term['careful'].strip()}")
        if term.get("where"):
            out.append(f"  - Where: `{term['where']}`")
        out.append("")

    out += ["## Certified metrics -- use these expressions verbatim", ""]
    for metric in layer["metrics"]:
        out.append(f"**{metric['name']}** on `{metric['entity']}`: {metric['description'].strip()}")
        out.append(f"  - expression: `{metric['expression']}`")
        if metric.get("filter"):
            out.append(f"  - filter: `{metric['filter']}`")
        if metric.get("time_column"):
            out.append(f"  - time_column: `{metric['time_column']}` (filter and group periods on this date)")
        if metric.get("group_by"):
            out.append(f"  - group by: `{metric['group_by']}`")
        if metric.get("grain_note"):
            out.append(f"  - grain: {metric['grain_note'].strip()}")
        if metric.get("careful"):
            out.append(f"  - careful: {metric['careful'].strip()}")
        out.append("")

    out += ["## Entities", ""]
    for entity in layer["entities"]:
        out.append(f"### `{entity['name']}` -- {entity['business_name']}")
        out.append("")
        out.append(entity["description"].strip())
        out.append("")
        out.append(f"- **Grain: {entity['grain']}**"
                   + (f" (key: {', '.join(entity['primary_key'])})" if entity.get("primary_key") else ""))
        out.append(f"- Rows when unfiltered: {entity['row_count_unfiltered']:,}")
        if entity.get("answers"):
            out.append(f"- Relevant to: {', '.join(entity['answers'])}")
        out.append("")
        out.append("| column | type | meaning | allowed values |")
        out.append("|---|---|---|---|")
        for column in entity["columns"]:
            allowed = column.get("allowed_values")
            allowed_text = (
                ", ".join(f"`{value}`" for value in allowed) if allowed else ""
            )
            out.append(
                f"| `{column['name']}` | {column['type']} | "
                f"{column['description'].strip()} | {allowed_text} |"
            )
        out.append("")
        if entity.get("joins"):
            out.append("Joins:")
            for join in entity["joins"]:
                note = f" -- {join['note']}" if join.get("note") else ""
                shape = join.get("cardinality", "")
                if join.get("optional"):
                    shape += "; optional: not every row has a match"
                shape = f" ({shape})" if shape else ""
                out.append(f"- to `{join['to']}` on `{join['on']}`{shape}{note}")
            out.append("")

    out += ["## Data quality caveats to repeat in your answer", ""]
    for caveat in layer["caveats"]:
        metric = f" (affects metric `{caveat['metric']}`)" if caveat.get("metric") else ""
        out.append(
            f"**{caveat['id']}** [{caveat['severity']}, {caveat['rows']:,} rows, "
            f"rule `{caveat['rule_id']}`]{metric}: {caveat['caveat'].strip()}"
        )
        out.append("")

    out += ["## Entitlements", "", layer["entitlements"]["model"].strip(), ""]
    for implication in layer["entitlements"]["implications_for_the_query_author"]:
        out.append(f"- {implication.strip()}")
    out.append("")

    out += ["## Phrase hints", "", "| if the question says | use | watch out for |", "|---|---|---|"]
    for pattern in layer["question_patterns"]:
        out.append(
            f"| {pattern['phrase']} | `{pattern['use']}` | {pattern['trap'].strip()} |"
        )
    out.append("")
    return "\n".join(out)


def main() -> int:
    """Validate the semantic layer and render the context pack.

    :returns: Process exit code: ``0`` when the layer agrees with the database.
    """
    parser = argparse.ArgumentParser(description="Render and validate the semantic layer.")
    parser.add_argument("--write", action="store_true",
                       help="write the rendered context pack to semantic/context_pack.md")
    parser.add_argument("--no-validate", action="store_true",
                       help="skip validation against the database")
    args = parser.parse_args()

    layer = load_semantic_layer()
    problems: list[str] = []
    if not args.no_validate:
        with db.connect() as conn:
            problems = validate(layer, conn)

    pack = render_context_pack(layer)
    if args.write or not problems:
        CONTEXT_PACK_MD.write_text(pack, encoding="utf-8")
        LOGGER.info(
            "wrote %s -> %d lines, %d characters (about %d tokens)",
            CONTEXT_PACK_MD.relative_to(config.PROJECT_ROOT),
            pack.count("\n") + 1,
            len(pack),
            len(pack) // 4,
        )

    db.record_run(
        "semantic",
        "make semantic",
        {
            "entities": len(layer["entities"]),
            "columns": sum(len(e["columns"]) for e in layer["entities"]),
            "context_pack_chars": len(pack),
            "problems": problems,
        },
    )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
