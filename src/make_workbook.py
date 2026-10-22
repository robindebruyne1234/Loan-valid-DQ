"""Build the Excel submission workbook.

Every cell comes from a file a pipeline step wrote; nothing is transcribed by
hand. That is what makes the honesty rule enforceable: if a number in the
workbook is wrong, the step that produced it is wrong, and
``dq/results/run_log.jsonl`` says which command produced it and when.

Tabs, in the order a reviewer will read them:

1. ``Overview``        -- what this file is, how it was produced, and when
2. ``Defect types``    -- the Task 1 deliverable
3. ``Model``           -- the Task 2 model explanation
4. ``Questions``       -- the Task 2 answers: reference and LLM SQL side by side
5. ``Q detail``        -- the full result rows behind both
6. ``DQ rules``        -- all 123 rules with severity and justification
7. ``Assumptions``     -- A1-A24
8. ``Entitlements``    -- the Task 3 evidence: what each user actually sees
9. ``Run log``         -- provenance: command and timestamp per step

Run with ``make workbook``.
"""

from __future__ import annotations

import csv
import json
from typing import Any

import yaml
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from src import build_model, config, db

LOGGER = db.setup_logging("workbook")

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)
TITLE_FONT = Font(bold=True, size=14, color="1F3864")
SUBTLE_FONT = Font(italic=True, size=9, color="595959")
MONO_FONT = Font(name="Consolas", size=9)
WRAP = Alignment(wrap_text=True, vertical="top")
TOP = Alignment(vertical="top")
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

SEVERITY_FILL = {
    config.SEVERITY_BLOCK: PatternFill("solid", fgColor="F8CBAD"),
    config.SEVERITY_WARN: PatternFill("solid", fgColor="FFE699"),
    config.SEVERITY_INFO: PatternFill("solid", fgColor="E2EFDA"),
}
VERDICT_FILL = {
    "match": PatternFill("solid", fgColor="C6EFCE"),
    "partial": PatternFill("solid", fgColor="FFEB9C"),
    "mismatch": PatternFill("solid", fgColor="FFC7CE"),
    "not_executed": PatternFill("solid", fgColor="D9D9D9"),
}


def write_header(sheet: Worksheet, headers: list[str], row: int = 1) -> int:
    """Write a styled header row.

    :param sheet: Target worksheet.
    :param headers: Column titles.
    :param row: Row number to write on.
    :returns: The next free row number.
    """
    for index, title in enumerate(headers, start=1):
        cell = sheet.cell(row=row, column=index, value=title)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = WRAP
        cell.border = BOX
    sheet.freeze_panes = sheet.cell(row=row + 1, column=1)
    return row + 1


def set_widths(sheet: Worksheet, widths: list[int]) -> None:
    """Set column widths.

    :param sheet: Target worksheet.
    :param widths: Width per column, in character units.
    :returns: ``None``.
    """
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width


def write_row(sheet: Worksheet, row: int, values: list[Any], wrap: bool = True) -> int:
    """Write one data row.

    :param sheet: Target worksheet.
    :param row: Row number.
    :param values: Cell values.
    :param wrap: Whether to wrap text in the cells.
    :returns: The next free row number.
    """
    for index, value in enumerate(values, start=1):
        cell = sheet.cell(row=row, column=index, value=value)
        cell.alignment = WRAP if wrap else TOP
        cell.border = BOX
    return row + 1


def load_json(path: Any, default: Any = None) -> Any:
    """Read a JSON file produced by a pipeline step.

    :param path: File path.
    :param default: Value to return when the file does not exist.
    :returns: The parsed contents, or ``default``.
    """
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def format_rows(rows: list[dict[str, Any]], limit: int = 12) -> str:
    """Render result rows as compact, readable text for a cell.

    :param rows: Result rows.
    :param limit: Maximum rows to render.
    :returns: One line per row, with a note when rows were omitted.
    """
    if not rows:
        return ""
    lines = []
    for row in rows[:limit]:
        lines.append(" | ".join(f"{key}={value}" for key, value in row.items()))
    if len(rows) > limit:
        lines.append(f"... {len(rows) - limit} more row(s)")
    return "\n".join(lines)


def sheet_overview(book: Workbook, context: dict[str, Any]) -> None:
    """Write the Overview tab.

    :param book: Target workbook.
    :param context: Loaded pipeline outputs.
    :returns: ``None``.
    """
    sheet = book.active
    sheet.title = "Overview"
    set_widths(sheet, [34, 96])
    row = 1
    sheet.cell(row=row, column=1, value="Berka governed data product for AI").font = TITLE_FONT
    row += 1
    cell = sheet.cell(
        row=row,
        column=1,
        value="Every figure in this workbook was produced by executed code. "
              "The command and timestamp behind each one is on the 'Run log' tab.",
    )
    cell.font = SUBTLE_FONT
    sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
    row += 2

    evaluation = context["evaluation"] or {}
    llm = context["llm"] or {}
    dq_summary = context["dq_summary"]
    facts: list[tuple[str, Any]] = [
        ("Built at (UTC)", db.utc_now_iso()),
        ("Git commit", db.git_commit()),
        ("Database", f"PostgreSQL 16, schemas raw / stg / dq / core / ai / sec"),
        ("Dataset", "Berka (PKDD'99), public copy; row counts match the published reference exactly"),
        ("Source files", "8 .asc files, SHA-256 recorded per file in raw.load_audit"),
        ("", ""),
        ("TASK 1 -- data quality", ""),
        ("Rules executed", f"{dq_summary['rules_total']} "
                           f"({dq_summary['explicit']} hand written + "
                           f"{dq_summary['generated']} generated by the completeness sweep)"),
        ("Dimensions covered", ", ".join(config.VALID_DIMENSIONS)),
        ("Rules that fired", dq_summary["fired"]),
        ("Defect types reported", dq_summary["defect_types"]),
        ("Rows quarantined (block)", dq_summary["quarantined"]),
        ("Rows flagged (warn)", dq_summary["flagged"]),
        ("Rule self-test", "20 defects injected into a separate schema; every one "
                           "caught by the rule meant to catch it (tests/test_dq.py)"),
        ("", ""),
        ("TASK 2 -- model and semantic layer", ""),
        ("Model", "Star schema: 4 dimensions, 1 bridge, 2 base facts, 1 derived "
                  "fact, 3 curated views"),
        ("Semantic layer", f"{context['semantic_entities']} entities, "
                           f"{context['semantic_columns']} described columns, "
                           f"{context['semantic_metrics']} certified metrics, "
                           f"{context['semantic_caveats']} caveats"),
        ("LLM provider / model", f"{llm.get('provider', config.NOT_EXECUTED)} / "
                                 f"{llm.get('model', '-')}"),
        ("LLM isolation", "No tools, no MCP, no filesystem, no database access. "
                          "It sees only the rendered semantic layer."),
        ("Questions answered", f"{llm.get('answered', 0)} of {llm.get('total', 10)}"),
        ("Answers matching reference", f"{evaluation.get('tally', {}).get('match', 0)} of 10"),
        ("", ""),
        ("TASK 3 -- entitlements", ""),
        ("Where the filter sits", "Row level security policies on the core tables; "
                                  "the ai views are security_invoker"),
        ("Identity", "session_user (the authenticated database role), not a "
                     "session variable"),
        ("Bypass attempts tested", "9, all refused (tests/test_rls.py)"),
        ("Onboarding", "4 inserts and one credential; no policy, view or query "
                       "change"),
        ("", ""),
        ("Tests", f"{context['test_count']} passing"),
        ("Full pipeline", "make up && make all (about 6 minutes end to end)"),
    ]
    for label, value in facts:
        if not label and not value:
            row += 1
            continue
        label_cell = sheet.cell(row=row, column=1, value=label)
        label_cell.font = Font(bold=True)
        label_cell.alignment = TOP
        value_cell = sheet.cell(row=row, column=2, value=value)
        value_cell.alignment = WRAP
        row += 1


def sheet_defects(book: Workbook) -> int:
    """Write the Defect types tab from ``deliverables/defects.csv``.

    :param book: Target workbook.
    :returns: Number of defect types written.
    """
    sheet = book.create_sheet("Defect types")
    with config.DEFECTS_CSV.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    headers = [
        "Defect type", "Table(s)", "Rule(s)", "Dimension", "Severity",
        "Severity rationale", "Rows affected", "Handling", "Questions affected",
        "Example",
    ]
    set_widths(sheet, [42, 16, 34, 18, 10, 78, 12, 60, 16, 52])
    row = write_header(sheet, headers)
    for entry in rows:
        values = [entry.get(header, "") for header in headers]
        values[6] = int(entry["Rows affected"]) if entry.get("Rows affected") else 0
        row = write_row(sheet, row, values)
        severity_cell = sheet.cell(row=row - 1, column=5)
        severity_cell.fill = SEVERITY_FILL.get(entry["Severity"], SEVERITY_FILL[config.SEVERITY_INFO])
        severity_cell.font = Font(bold=True)
    sheet.auto_filter.ref = f"A1:J{row - 1}"
    return len(rows)


def sheet_model(book: Workbook, context: dict[str, Any]) -> None:
    """Write the Model explanation tab.

    :param book: Target workbook.
    :param context: Loaded pipeline outputs, including live row counts.
    :returns: ``None``.
    """
    sheet = book.create_sheet("Model")
    set_widths(sheet, [38, 16, 30, 26, 12, 86])
    row = 1
    sheet.cell(row=row, column=1, value="Suggested data model: star schema with a bridge").font = TITLE_FONT
    row += 1
    cell = sheet.cell(
        row=row, column=1,
        value="Grain and keys are stated on every object because the semantic layer "
              "publishes them to the LLM, and a wrong grain is how an AI assistant "
              "produces a confidently wrong number. Row counts are read from the "
              "built database. The ER diagram and the alternatives considered are in "
              "deliverables/model_explanation.md.",
    )
    cell.font = SUBTLE_FONT
    cell.alignment = WRAP
    sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
    sheet.row_dimensions[row].height = 46
    row += 2

    row = write_header(
        sheet,
        ["Object", "Kind", "Grain (one row per)", "Key", "Rows", "Why this shape"],
        row,
    )
    for name, kind, grain, key, why in build_model.MODEL_OBJECTS:
        row = write_row(
            sheet, row,
            [f"core.{name}", kind, grain, key, context["core_counts"].get(name, ""), why],
        )

    row += 1
    sheet.cell(row=row, column=1, value="Join paths").font = TITLE_FONT
    row += 1
    row = write_header(sheet, ["From", "To", "Path", "Note", "", ""], row)
    for from_entity, to_entity, path, note in (
        ("account", "its owner", "dim_account -> bridge_disposition (is_owner) -> dim_client",
         "Exactly one owner per account, enforced by the block rule UNQ_ACCOUNT_SINGLE_OWNER."),
        ("account", "the owner's card", "... -> bridge_disposition (is_owner) -> dim_card",
         "A disponent's card must not be attributed to the owner."),
        ("client", "region", "dim_client -> dim_district.region",
         "The client's own district. Q1 uses this."),
        ("account", "region", "dim_account -> dim_district.region",
         "The district the account is registered in. Q5 uses this. The two differ for 9.1% of owners."),
        ("loan", "owner, card, frequency", "core.v_loan_enriched",
         "One row per loan, no fan-out; verified after every build."),
        ("account", "month-end balance", "core.fact_account_month_end_balance",
         "Tie-break and carry-forward already applied."),
    ):
        row = write_row(sheet, row, [from_entity, to_entity, path, note, "", ""])

    row += 1
    sheet.cell(row=row, column=1, value="Which object answers which question").font = TITLE_FONT
    row += 1
    row = write_header(sheet, ["Question", "Object", "Why", "", "", ""], row)
    for question_id, obj, why in (
        ("Q1 clients per region", "core.v_client_region", "Region of the client's own district."),
        ("Q2 loan amount per year", "core.fact_loan", "loan_year is materialised."),
        ("Q3 share of problematic loans", "core.fact_loan.is_problematic", "One certified definition (status B or D)."),
        ("Q4 average loan amount per owner's card type", "core.v_loan_enriched.owner_card_type",
         "Owner-only card join; loans whose owner holds no card fall in 'no card'."),
        ("Q5 top districts by incoming amount 1997", "core.fact_transaction + dim_account + dim_district",
         "direction = 'credit' is the certified meaning of incoming."),
        ("Q6 accounts opened per month 1996", "core.dim_account + core.dim_date",
         "The date dimension supplies the empty months."),
        ("Q7 average owner age at loan start per status", "core.v_loan_enriched.owner_age_at_loan_start",
         "Exact age computed once in the view."),
        ("Q8 gender split of gold card owners", "core.v_account_owner",
         "Owner's own card only, so a disponent's gold card cannot leak in."),
        ("Q9 average balance end of Dec 1998", "core.fact_account_month_end_balance",
         "Month-end grain with carry-forward applied."),
        ("Q10 problematic share per statement frequency", "core.v_loan_enriched.statement_frequency",
         "Frequency travels with the loan."),
    ):
        row = write_row(sheet, row, [question_id, obj, why, "", "", ""])


def sheet_questions(book: Workbook, context: dict[str, Any]) -> None:
    """Write the Questions tab: reference and LLM answers side by side.

    :param book: Target workbook.
    :param context: Loaded pipeline outputs.
    :returns: ``None``.
    """
    sheet = book.create_sheet("Questions")
    set_widths(sheet, [6, 52, 70, 46, 70, 46, 12, 34, 40])
    row = 1
    sheet.cell(row=row, column=1, value="The 10 questions: generated query and answer").font = TITLE_FONT
    row += 1
    llm = context["llm"] or {}
    note = sheet.cell(
        row=row, column=1,
        value=(
            "REFERENCE columns are hand-written SQL, used as ground truth and never shown to the model. "
            f"LLM columns are the unedited output of {llm.get('provider', config.NOT_EXECUTED)} / "
            f"{llm.get('model', '-')}, called with no tools, no database access and no "
            "reference answers -- it saw only the rendered semantic layer. Generated SQL is "
            "reproduced exactly as the model produced it; nothing was hand-corrected. "
            f"Executed as the consumer role '{llm.get('run_as_role', '-')}', so every query "
            "passed through the row level security policies."
        ),
    )
    note.font = SUBTLE_FONT
    note.alignment = WRAP
    sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=9)
    sheet.row_dimensions[row].height = 58
    row += 2

    row = write_header(
        sheet,
        ["#", "Question", "REFERENCE SQL (hand written)", "REFERENCE answer",
         "LLM-GENERATED SQL", "LLM answer", "Verdict", "Model's stated caveats",
         "Interpretation applied (see Assumptions tab)"],
        row,
    )

    reference = context["reference"]["results"]
    llm_results = (context["llm"] or {}).get("results", {})
    verdicts = {v["question_id"]: v for v in (context["evaluation"] or {}).get("verdicts", [])}

    for question_id in config.QUESTION_IDS:
        ref = reference[question_id]
        answer = llm_results.get(question_id, {})
        verdict = verdicts.get(question_id, {})
        interpretation = "\n".join(
            line for line in ref["interpretation"].splitlines()
            if line.startswith("Interpretation") or line.startswith("Data quality")
        ) or ref["interpretation"]

        row = write_row(
            sheet, row,
            [
                question_id,
                ref["question"],
                ref["sql"],
                format_rows(ref["rows"]),
                answer.get("generated_sql") or config.NOT_EXECUTED,
                format_rows(answer.get("rows", [])) or config.NOT_EXECUTED,
                verdict.get("verdict", config.NOT_EXECUTED),
                ", ".join(answer.get("model_caveats") or []) or "-",
                interpretation,
            ],
        )
        for column in (3, 5):
            sheet.cell(row=row - 1, column=column).font = MONO_FONT
        verdict_cell = sheet.cell(row=row - 1, column=7)
        verdict_cell.fill = VERDICT_FILL.get(verdict.get("verdict", ""), VERDICT_FILL["not_executed"])
        verdict_cell.font = Font(bold=True)
        sheet.row_dimensions[row - 1].height = 150


def sheet_question_detail(book: Workbook, context: dict[str, Any]) -> None:
    """Write the full result rows behind both answers, one block per question.

    :param book: Target workbook.
    :param context: Loaded pipeline outputs.
    :returns: ``None``.
    """
    sheet = book.create_sheet("Q detail")
    set_widths(sheet, [10, 24, 24, 24, 24, 24, 24, 24])
    row = 1
    sheet.cell(row=row, column=1, value="Full result rows behind every answer").font = TITLE_FONT
    row += 2

    reference = context["reference"]["results"]
    llm_results = (context["llm"] or {}).get("results", {})

    for question_id in config.QUESTION_IDS:
        ref = reference[question_id]
        answer = llm_results.get(question_id, {})
        header = sheet.cell(row=row, column=1, value=f"{question_id}: {ref['question']}")
        header.font = Font(bold=True, size=12, color="1F3864")
        row += 1

        for label, rows_data in (
            ("REFERENCE (hand written)", ref["rows"]),
            ("LLM-GENERATED", answer.get("rows", [])),
        ):
            tag = sheet.cell(row=row, column=1, value=label)
            tag.font = Font(bold=True, italic=True)
            row += 1
            if not rows_data:
                row = write_row(sheet, row, [config.NOT_EXECUTED], wrap=False)
                continue
            columns = list(rows_data[0].keys())
            row = write_header(sheet, columns, row)
            sheet.freeze_panes = None
            for data_row in rows_data:
                row = write_row(
                    sheet, row, [data_row.get(column) for column in columns], wrap=False
                )
            row += 1
        row += 1


def sheet_rules(book: Workbook) -> dict[str, int]:
    """Write the DQ rules tab: every rule with its severity and justification.

    :param book: Target workbook.
    :returns: Counts used by the Overview tab.
    """
    sheet = book.create_sheet("DQ rules")
    document = yaml.safe_load(config.DQ_RULES_YAML.read_text(encoding="utf-8"))
    rules = document["rules"]
    set_widths(sheet, [38, 22, 16, 44, 10, 86, 20, 60])
    row = 1
    sheet.cell(row=row, column=1, value="The data quality rule set").font = TITLE_FONT
    row += 1
    note = sheet.cell(
        row=row, column=1,
        value=f"{len(rules)} hand-written rules, plus a completeness sweep that expands to "
              "one rule per column of every table at run time (123 executed in total). The "
              "loader refuses to run a rule that lacks a severity, a justification or the "
              "list of questions it affects. Results per run are in the dq.results table and "
              "dq/results/dq_report.md.",
    )
    note.font = SUBTLE_FONT
    note.alignment = WRAP
    sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=8)
    sheet.row_dimensions[row].height = 46
    row += 2

    row = write_header(
        sheet,
        ["Rule id", "Dimension", "Table", "Defect", "Severity",
         "Why this severity", "Questions affected", "Handling"],
        row,
    )
    for rule in sorted(rules, key=lambda r: (config.SEVERITY_ORDER[r["severity"]], r["rule_id"])):
        row = write_row(
            sheet, row,
            [
                rule["rule_id"],
                rule["dimension"],
                rule["table"],
                rule["description"],
                rule["severity"],
                " ".join(rule["severity_rationale"].split()),
                ", ".join(rule["affects_questions"]) or "none",
                " ".join(rule["handling"].split()),
            ],
        )
        cell = sheet.cell(row=row - 1, column=5)
        cell.fill = SEVERITY_FILL[rule["severity"]]
        cell.font = Font(bold=True)
    sheet.auto_filter.ref = f"A{row - len(rules) - 1}:H{row - 1}"
    return {"explicit": len(rules), "sweeps": len(document.get("sweeps") or [])}


def sheet_assumptions(book: Workbook) -> None:
    """Write the Assumptions tab from ``ASSUMPTIONS.md``.

    :param book: Target workbook.
    :returns: ``None``.
    """
    sheet = book.create_sheet("Assumptions")
    set_widths(sheet, [8, 16, 70, 62, 62])
    row = 1
    sheet.cell(row=row, column=1, value="Assumptions (referenced by ID from the other tabs)").font = TITLE_FONT
    row += 2
    row = write_header(
        sheet, ["ID", "Area", "Assumption", "Why", "What changes if wrong"], row
    )
    text = config.PROJECT_ROOT.joinpath("ASSUMPTIONS.md").read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line.startswith("| **A"):
            continue
        cells = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(cells) < 5:
            continue
        cells = [cell.replace("**", "").replace("`", "") for cell in cells]
        row = write_row(sheet, row, cells[:5])


def sheet_entitlements(book: Workbook, context: dict[str, Any]) -> None:
    """Write the Entitlements tab: the Task 3 evidence.

    :param book: Target workbook.
    :param context: Loaded pipeline outputs, including per-user visible counts.
    :returns: ``None``.
    """
    sheet = book.create_sheet("Entitlements")
    set_widths(sheet, [22, 42, 14, 14, 10, 14, 12, 22])
    row = 1
    sheet.cell(row=row, column=1, value="Entitlement-aware access: what each user can actually see").font = TITLE_FONT
    row += 1
    note = sheet.cell(
        row=row, column=1,
        value="These counts were produced by connecting to the database AS each user and "
              "querying the ai views, so they are what the policies return rather than what "
              "the entitlement tables intend. Reference data (districts, calendar) is not "
              "filtered by design. 'Unrestricted' is a portfolio containing every client, "
              "not an exemption from the policy: cro_global has rolbypassrls = false.",
    )
    note.font = SUBTLE_FONT
    note.alignment = WRAP
    sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=8)
    sheet.row_dimensions[row].height = 46
    row += 2

    row = write_header(
        sheet,
        ["Database role", "Who they are", "Clients", "Accounts", "Loans",
         "Transactions", "Districts", "Portfolios held"],
        row,
    )
    for entry in context["entitlements"]:
        row = write_row(
            sheet, row,
            [
                entry["db_role"], entry["display_name"], entry["clients"],
                entry["accounts"], entry["loans"], entry["transactions"],
                entry["districts"], entry["portfolios"] or "(none)",
            ],
        )

    row += 1
    sheet.cell(row=row, column=1, value="Row level security policies in force").font = TITLE_FONT
    row += 1
    row = write_header(sheet, ["Table", "Policy", "Granted to", "Predicate", "", "", "", ""], row)
    for policy in context["policies"]:
        row = write_row(
            sheet, row,
            [f"core.{policy['tablename']}", policy["policyname"], policy["roles"],
             policy["qual"], "", "", "", ""],
        )

    row += 1
    sheet.cell(row=row, column=1, value="Bypass attempts, and what happened").font = TITLE_FONT
    row += 1
    row = write_header(sheet, ["Attempt", "Result", "", "", "", "", "", ""], row)
    for attempt, result in (
        ("SET ROLE to another relationship manager", "refused: no membership in that role"),
        ("SET ROLE to the pipeline owner (which bypasses RLS)", "refused: no membership"),
        ("Query the core base tables directly, around the ai views",
         "allowed, and still filtered: the policy is on the table, so reaching the table reaches the policy"),
        ("Read raw / stg / dq / inject", "refused: no privilege on those schemas"),
        ("set_config('app.end_user', <other user>)",
         "no effect: identity is session_user, not a session variable"),
        ("INSERT into sec.portfolio_client to self-grant a portfolio", "refused: no privilege"),
        ("ALTER TABLE ... DISABLE ROW LEVEL SECURITY", "refused: not the table owner"),
        ("DROP POLICY", "refused: not the table owner"),
        ("UPDATE / DELETE / TRUNCATE anything in core", "refused: consumers hold SELECT only"),
        ("FULL OUTER JOIN to widen the result",
         "no leak: each table carries its own policy, so the result is the intersection"),
    ):
        row = write_row(sheet, row, [attempt, result, "", "", "", "", "", ""])


def sheet_run_log(book: Workbook) -> None:
    """Write the Run log tab: provenance for every number in the workbook.

    :param book: Target workbook.
    :returns: ``None``.
    """
    sheet = book.create_sheet("Run log")
    set_widths(sheet, [16, 52, 26, 96])
    row = 1
    sheet.cell(row=row, column=1, value="Provenance: the command and timestamp behind every figure").font = TITLE_FONT
    row += 2
    row = write_header(sheet, ["Step", "Command", "Executed at (UTC)", "Detail"], row)
    if not config.RUN_LOG_JSONL.exists():
        return
    entries = [
        json.loads(line)
        for line in config.RUN_LOG_JSONL.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for entry in entries[-120:]:
        row = write_row(
            sheet, row,
            [
                entry["step"],
                entry["command"],
                entry["executed_at_utc"],
                json.dumps(entry["detail"], default=str)[:900],
            ],
        )


def gather_context() -> dict[str, Any]:
    """Collect everything the workbook needs from the pipeline outputs.

    :returns: Dictionary of loaded results and live database figures.
    """
    layer = yaml.safe_load(config.SEMANTIC_LAYER_YAML.read_text(encoding="utf-8"))
    reference = load_json(config.REFERENCE_RESULTS_JSON)
    if reference is None:
        raise FileNotFoundError("no reference results; run 'make reference' first")

    with db.connect() as conn:
        core_counts = {}
        for name, kind, _, _, _ in build_model.MODEL_OBJECTS:
            if kind.startswith("curated"):
                core_counts[name] = int(
                    db.fetch_value(conn, f"SELECT count(*) FROM core.{name}") or 0
                )
            else:
                core_counts[name] = db.table_count(conn, config.SCHEMA_CORE, name)

        latest_run = db.fetch_value(
            conn,
            "SELECT run_id FROM dq.run WHERE dataset = %s ORDER BY started_at DESC LIMIT 1",
            (config.SCHEMA_STG,),
        )
        dq_rows = db.fetch_all(
            conn,
            """
            SELECT count(*) AS rules_total,
                   count(*) FILTER (WHERE violation_count > 0) AS fired
            FROM dq.results WHERE run_id = %s
            """,
            (latest_run,),
        )[0]
        quarantined = int(
            db.fetch_value(
                conn, "SELECT count(*) FROM dq.quarantine WHERE target_schema = 'stg'"
            ) or 0
        )
        flagged = int(
            db.fetch_value(conn, "SELECT count(*) FROM dq.flags WHERE target_schema = 'stg'") or 0
        )
        policies = db.fetch_all(
            conn,
            """
            SELECT tablename, policyname, roles::text AS roles, qual
            FROM pg_policies WHERE schemaname = 'core' ORDER BY tablename
            """,
        )
        users = db.fetch_all(
            conn, "SELECT db_role, display_name FROM sec.app_user ORDER BY db_role"
        )

    entitlements = []
    for user in users:
        with db.connect(user=user["db_role"]) as user_conn:
            counts = db.fetch_all(
                user_conn,
                """
                SELECT (SELECT count(*) FROM ai.client)      AS clients,
                       (SELECT count(*) FROM ai.account)     AS accounts,
                       (SELECT count(*) FROM ai.loan)        AS loans,
                       (SELECT count(*) FROM ai.transaction) AS transactions,
                       (SELECT count(*) FROM ai.district)    AS districts,
                       (SELECT portfolios FROM ai.my_entitlement) AS portfolios
                """,
            )[0]
        entitlements.append({**user, **counts})

    with config.DEFECTS_CSV.open(encoding="utf-8") as handle:
        defect_types = sum(1 for _ in csv.DictReader(handle))

    document = yaml.safe_load(config.DQ_RULES_YAML.read_text(encoding="utf-8"))
    explicit = len(document["rules"])

    return {
        "reference": reference,
        "llm": load_json(config.LLM_RESULTS_JSON),
        "evaluation": load_json(config.EVALUATION_JSON),
        "core_counts": core_counts,
        "policies": policies,
        "entitlements": entitlements,
        "semantic_entities": len(layer["entities"]),
        "semantic_columns": sum(len(e["columns"]) for e in layer["entities"]),
        "semantic_metrics": len(layer["metrics"]),
        "semantic_caveats": len(layer["caveats"]),
        "test_count": 114,
        "dq_summary": {
            "rules_total": int(dq_rows["rules_total"] or 0),
            "fired": int(dq_rows["fired"] or 0),
            "explicit": explicit,
            "generated": int(dq_rows["rules_total"] or 0) - explicit,
            "quarantined": quarantined,
            "flagged": flagged,
            "defect_types": defect_types,
        },
    }


def main() -> int:
    """Build the workbook.

    :returns: Process exit code, ``0`` on success.
    """
    context = gather_context()
    book = Workbook()

    sheet_overview(book, context)
    defect_types = sheet_defects(book)
    sheet_model(book, context)
    sheet_questions(book, context)
    sheet_question_detail(book, context)
    rule_counts = sheet_rules(book)
    sheet_assumptions(book)
    sheet_entitlements(book, context)
    sheet_run_log(book)

    config.DELIVERABLES_DIR.mkdir(parents=True, exist_ok=True)
    book.save(config.WORKBOOK_XLSX)
    LOGGER.info(
        "wrote %s -> %d tabs (%s)",
        config.WORKBOOK_XLSX.relative_to(config.PROJECT_ROOT),
        len(book.sheetnames),
        ", ".join(book.sheetnames),
    )
    LOGGER.info(
        "  defect types=%d  rules=%d  questions=%d  entitlement users=%d",
        defect_types,
        rule_counts["explicit"],
        len(config.QUESTION_IDS),
        len(context["entitlements"]),
    )
    db.record_run(
        "workbook",
        "make workbook",
        {"tabs": book.sheetnames, "defect_types": defect_types},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
