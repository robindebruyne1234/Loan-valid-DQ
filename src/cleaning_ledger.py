"""Build docs/CLEANING_LEDGER.md: every cleaning step, with what it did measured.

This exists because "the data was cleaned" is not a statement anyone can check.
The ledger names each transformation between the source file and the published
product, says why it happens and what it costs, and then *measures* its effect
by running a probe against the live database. Nothing here is asserted from
memory; if a step stops doing anything, its row goes to zero and says so.

Each step carries:

``step``
    Stable identifier, referenced from DECISIONS.md and the workbook.
``layer``
    Where it happens: ``raw`` (bronze), ``stg`` / ``dq`` (silver) or ``core``
    (gold).
``target``
    The table and column(s) it touches.
``action``
    What is done to the value, in one phrase.
``why``
    The reason, in terms of what breaks without it.
``reversible``
    Where the pre-cleaning value can still be read, or ``-`` when the step
    adds information rather than replacing it.
``watched_by``
    The data quality rule that reports on this step's residue, so a cleaning
    step that silently stops working is not silent.
``probe``
    SQL returning a single ``measure`` column. This is the number in the
    ledger.

It is importable: :data:`STEPS` and :func:`measure` are what the workbook's
Cleaning tab renders, so the tab and the document can never disagree.

Usage: python -m src.cleaning_ledger
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from src import config, db

TARGET = config.PROJECT_ROOT / "docs" / "CLEANING_LEDGER.md"

LOGGER = db.setup_logging("ledger")


@dataclass(frozen=True)
class Step:
    """One cleaning step, with the probe that measures it.

    :param step: Stable identifier (C01, C02, ...).
    :param layer: raw, stg, dq or core.
    :param target: Table and columns the step touches.
    :param action: What the step does to the value.
    :param why: Why it is done, in terms of what breaks without it.
    :param probe: SQL returning one row with a ``measure`` column.
    :param unit: What the measure counts.
    :param reversible: Where the original value survives, or ``-``.
    :param watched_by: Rule ids that report on this step's residue.
    """

    step: str
    layer: str
    target: str
    action: str
    why: str
    probe: str
    unit: str
    reversible: str = "-"
    watched_by: tuple[str, ...] = field(default_factory=tuple)


STEPS: tuple[Step, ...] = (
    # ---------------------------------------------------------------- bronze
    Step(
        "C01", "raw", "all 8 tables",
        "Land every field as text, unchanged",
        "A cast at load time destroys the evidence of the defect it trips over. "
        "Bronze is deliberately the one layer that cleans nothing.",
        # Scoped to the LATEST ingest. raw.load_audit keeps one row per file
        # per run, so summing the whole table reports every build this
        # database has ever seen: after three `make build` runs it claimed
        # 3,239,040 rows from 24 files. A ledger that counts its own history
        # is worse than no ledger, and these two numbers reach a deliverable.
        """
        SELECT sum(rows_loaded) AS measure FROM raw.load_audit
        WHERE run_id = (SELECT run_id FROM raw.load_audit
                        ORDER BY loaded_at DESC LIMIT 1)
        """,
        "rows landed verbatim",
        "the source file itself, SHA-256 in raw.load_audit",
        ("RI_RAW_ROWCOUNT_MATCHES",),
    ),
    Step(
        "C02", "raw", "all 8 tables -> _source_file, _source_row",
        "Stamp every row with its file and line number",
        "Without it no cleaned value can be traced back, and a reviewer has to "
        "take the rest of this ledger on trust.",
        """
        SELECT count(*) AS measure FROM raw.load_audit
        WHERE counts_match
          AND run_id = (SELECT run_id FROM raw.load_audit
                        ORDER BY loaded_at DESC LIMIT 1)
        """,
        "files whose row count matched the file",
    ),
    # ---------------------------------------------------------------- silver
    Step(
        "C03", "stg", "every text column (stg.norm_text)",
        "Trim, then map '', '?', 'NA', 'N/A', 'NULL', '-', 'unknown' to NULL",
        "The source spells 'missing' seven ways. Left alone, '?' counts as a "
        "value and every completeness number is wrong.",
        """
        SELECT (SELECT count(*) FROM stg.district WHERE cardinality(_conversion_notes) > 0)
             + (SELECT count(*) FROM stg."order" WHERE cardinality(_conversion_notes) > 0)
               AS measure
        """,
        "rows where a placeholder became NULL",
        "<column>_raw audit column, plus _conversion_notes",
        ("COMP_DISTRICT_1995_PLACEHOLDER", "COMP_RAW_MISSING_ENCODING_INCONSISTENT"),
    ),
    Step(
        "C04", "stg", "every numeric column (stg.parse_numeric, parse_int)",
        "Cast to numeric, returning NULL rather than raising",
        "A cast that throws aborts the load and hides the bad value. Returning "
        "NULL keeps the row and lets a rule count the loss.",
        """
        SELECT count(*) AS measure FROM stg.trans
        WHERE amount_raw IS NOT NULL OR balance_raw IS NOT NULL
        """,
        "transaction amounts that failed to cast",
        "amount_raw / balance_raw",
        ("VAL_TRANS_AMOUNT_POSITIVE", "VAL_LOAN_AMOUNT_POSITIVE"),
    ),
    Step(
        "C05", "stg", "account.date, loan.date, trans.date, card.issued",
        "Parse YYMMDD into a real date, two-digit year read as 19xx",
        "Six digits are not a date. The century is an assumption (A25) and it "
        "is safe only because the dataset window is 1993-1998.",
        """
        SELECT (SELECT count(trans_date) FROM stg.trans)
             + (SELECT count(open_date) FROM stg.account)
             + (SELECT count(loan_date) FROM stg.loan)
             + (SELECT count(issued_date) FROM stg.card) AS measure
        """,
        "dates parsed from YYMMDD text",
        "<column>_raw where the parse failed",
        ("VAL_TRANS_DATE_UNPARSABLE", "VAL_DATE_OUT_OF_RANGE"),
    ),
    Step(
        "C06", "stg", "card.issued",
        "Strip the trailing clock time before parsing",
        "card.issued is '931107 00:00:00' while every other date is bare. One "
        "format rule for all four columns, applied in one function.",
        """
        SELECT count(*) AS measure FROM raw.card WHERE issued LIKE '% %'
        """,
        "card issue dates carrying a clock time",
        "raw.card.issued",
        ("VAL_CARD_ISSUED_UNPARSABLE",),
    ),
    Step(
        "C07", "stg", "client.birth_number -> birth_date",
        "Decode YYMMDD, subtracting 50 from the month for women",
        "The source packs two facts into one number. Leaving it packed means "
        "every age question has to re-implement the decoding.",
        "SELECT count(birth_date) AS measure FROM stg.client",
        "birth dates decoded",
        "birth_number is kept in full beside it",
        ("VAL_BIRTH_NUMBER_DECODABLE", "VAL_BIRTH_DATE_PLAUSIBLE"),
    ),
    Step(
        "C08", "stg", "client.birth_number -> gender",
        "Derive gender from the same month offset",
        "The dataset has no gender column. It is derived, not given, which is "
        "why it is recorded here and in A26 rather than presented as fact.",
        """
        SELECT count(*) AS measure FROM stg.client WHERE gender IS NOT NULL
        """,
        "clients whose gender was derived",
        "birth_number",
        ("VAL_GENDER_DOMAIN",),
    ),
    Step(
        "C09", "stg", "7 coded columns across 5 tables",
        "Decode each Czech code to an English label from one map",
        "An LLM asked for 'withdrawals' cannot know VYDAJ. The map lives in "
        "src/config.py only, and the build fails if the data holds a code it "
        "does not know.",
        """
        SELECT (SELECT count(frequency_label)  FROM stg.account)
             + (SELECT count(disp_type_label)  FROM stg.disp)
             + (SELECT count(status_label)     FROM stg.loan)
             + (SELECT count(trans_type_label) FROM stg.trans)
             + (SELECT count(operation_label)  FROM stg.trans)
             + (SELECT count(k_symbol_label)   FROM stg.trans)
             + (SELECT count(k_symbol_label)   FROM stg."order") AS measure
        """,
        "coded values given an English label",
        "the code column is kept beside every label",
        ("VAL_KSYMBOL_DOMAIN", "VAL_ORDER_KSYMBOL_DOMAIN", "VAL_TRANS_TYPE_DOMAIN",
         "VAL_TRANS_OPERATION_DOMAIN", "VAL_LOAN_STATUS_DOMAIN", "VAL_FREQUENCY_DOMAIN",
         "VAL_DISP_TYPE_DOMAIN"),
    ),
    Step(
        "C10", "stg", "trans.type + trans.amount -> signed_amount, direction",
        "Resolve the sign once: credits positive, debits negative",
        "This is the single most valuable cleaning step for AI-readiness. The "
        "source states direction in a Czech word and leaves the amount "
        "unsigned, so every 'net flow' query has to encode that VYDAJ and "
        "VYBER are both outgoing. Resolved here, it cannot be got wrong there.",
        "SELECT count(signed_amount) AS measure FROM stg.trans",
        "postings given an unambiguous sign",
        "amount and trans_type_code are both kept",
        ("VAL_TRANS_AMOUNT_NEGATIVE", "CON_BALANCE_RECONCILIATION_MATERIAL"),
    ),
    Step(
        "C11", "stg", "loan.status -> is_problematic",
        "Materialise the B-or-D definition as a boolean",
        "Q3 and Q10 both turn on what 'problematic' means. Defining it once in "
        "the data stops the model inventing a different definition per answer.",
        "SELECT count(*) AS measure FROM stg.loan WHERE is_problematic",
        "loans marked problematic (status B or D)",
        "status_code and status_label",
        ("VAL_LOAN_STATUS_DOMAIN",),
    ),
    Step(
        "C12", "stg", "_conversion_notes on all 8 tables",
        "Record every value the cleaning changed or dropped, in place",
        "A cleaning step with no receipt is indistinguishable from data loss.",
        """
        SELECT (SELECT count(*) FROM stg.district WHERE cardinality(_conversion_notes) > 0)
             + (SELECT count(*) FROM stg."order"  WHERE cardinality(_conversion_notes) > 0)
             + (SELECT count(*) FROM stg.client   WHERE cardinality(_conversion_notes) > 0)
             + (SELECT count(*) FROM stg.trans    WHERE cardinality(_conversion_notes) > 0)
               AS measure
        """,
        "rows carrying a conversion note",
    ),
    # ------------------------------------------------------- silver: grading
    Step(
        "C13", "dq", "every staged table",
        "Grade each defect block / warn / info; change no value",
        "Cleaning that silently repairs is cleaning nobody can audit. The rule "
        "layer decides what happens to a bad row; it never edits one.",
        """
        SELECT count(*) AS measure FROM dq.results
        WHERE run_id = (SELECT run_id FROM dq.run WHERE dataset = 'stg'
                        ORDER BY started_at DESC LIMIT 1)
        """,
        "rules executed against the real data",
    ),
    Step(
        "C14", "dq", "dq.quarantine",
        "Hold back the rows that fail a block rule",
        "The only step in the whole pipeline that removes a row from the "
        "product, which is why it is counted, reversible and reconciled.",
        """
        SELECT count(*) AS measure FROM dq.quarantine WHERE target_schema = 'stg'
        """,
        "rows held back from the product",
        "dq.quarantine holds the row and the reason",
        ("UNQ_TRANS_BUSINESS_KEY",),
    ),
    Step(
        "C15", "dq", "dq.flags",
        "Attach a warn flag to the row it concerns",
        "A row that is suspect but usable should travel with its warning "
        "rather than be dropped or silently trusted.",
        """
        SELECT count(DISTINCT (target_table, business_key)) AS measure
        FROM dq.flags WHERE target_schema = 'stg'
        """,
        "distinct rows carrying at least one warn flag",
        "-",
        ("CON_BALANCE_RECONCILIATION_MATERIAL", "CON_INTRADAY_ORDER_AMBIGUOUS",
         "VAL_OWNER_AGE_AT_ACCOUNT_OPEN", "VAL_OWNER_AGE_AT_LOAN_START"),
    ),
    # ------------------------------------------------------------------ gold
    Step(
        "C16", "core", "every core table",
        "Publish staging minus the blocked rows",
        "One subtraction, applied identically everywhere, so 'why is this row "
        "missing' always has the same answer.",
        """
        SELECT (SELECT count(*) FROM stg.trans) - (SELECT count(*) FROM core.fact_transaction)
               AS measure
        """,
        "transactions excluded from the product",
        "dq.quarantine, and stg.trans still holds the row",
    ),
    Step(
        "C17", "core", "_dq_flags on 4 core tables",
        "Carry the warn flags onto the published row",
        "The caveat has to reach the answer. A flag that stops at the quality "
        "schema is a flag nobody acts on.",
        """
        SELECT (SELECT count(*) FROM core.dim_account       WHERE cardinality(_dq_flags) > 0)
             + (SELECT count(*) FROM core.dim_client        WHERE cardinality(_dq_flags) > 0)
             + (SELECT count(*) FROM core.fact_loan         WHERE cardinality(_dq_flags) > 0)
             + (SELECT count(*) FROM core.fact_transaction  WHERE cardinality(_dq_flags) > 0)
               AS measure
        """,
        "published rows carrying a visible caveat",
    ),
    Step(
        "C18", "core", "core.ref_codes",
        "Re-resolve every label from one published catalogue",
        "Staging decodes inline for speed; core resolves against the catalogue "
        "and the build fails if the two disagree. Deliberate redundancy, "
        "checked rather than trusted.",
        "SELECT count(*) AS measure FROM core.ref_codes",
        "codes published with a label and a note",
        "-",
    ),
    Step(
        "C19", "core", "core.dim_date",
        "Generate a row per calendar day in the dataset window",
        "'Per month in 1996' must report twelve months, including the quiet "
        "ones. Without a date dimension the query has to invent them.",
        "SELECT count(*) AS measure FROM core.dim_date",
        "calendar days generated (no source table)",
        "-",
    ),
    Step(
        "C20", "core", "core.fact_account_month_end_balance",
        "Derive a month-end balance per account, carried forward",
        "The source has no month-end balance: it has postings. Deriving it "
        "once, with the tie-break written down, is what stops two answers to "
        "the same question.",
        """
        SELECT count(*) FILTER (WHERE is_carried_forward) AS measure
        FROM core.fact_account_month_end_balance
        """,
        "month ends inherited from an earlier posting (marked as such)",
        "is_carried_forward and balance_as_of_month_end",
        ("CON_INTRADAY_ORDER_AMBIGUOUS",),
    ),
    Step(
        "C21", "core", "dq.reconciliation",
        "Prove core = staging - quarantine, on rows and on money",
        "The closing check on the whole chain: if cleaning lost a row or a "
        "koruna without a quarantine entry to explain it, this is where it "
        "shows up.",
        """
        SELECT count(*) FILTER (WHERE is_balanced) AS measure
        FROM dq.reconciliation
        WHERE run_id = (SELECT run_id FROM dq.run WHERE dataset = 'stg'
                        ORDER BY started_at DESC LIMIT 1)
        """,
        "reconciliation checks balanced (of 11; any shortfall is a cleaning leak)",
    ),
)


def measure(conn, step: Step) -> int | None:
    """Run a step's probe and return its single measure.

    :param conn: Open connection.
    :param step: The step to measure.
    :returns: The measured count, or ``None`` when the probe failed.
    """
    try:
        value = db.fetch_value(conn, step.probe)
    except Exception as exc:  # noqa: BLE001 - a broken probe must not be silent
        LOGGER.error("probe failed for %s -> %s", step.step, exc)
        return None
    return int(value) if value is not None else None


def render(rows: list[tuple[Step, int | None]]) -> str:
    """Render the ledger as Markdown.

    :param rows: Steps paired with their measured value.
    :returns: The document text.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    layer_names = {
        "raw": ("Bronze -- `raw`", "Land it exactly as it arrived. Nothing is cleaned here, on purpose."),
        "stg": ("Silver -- `stg`", "Type it, normalise it, decode it, derive what the source left implicit. Nothing is filtered."),
        "dq": ("Silver -- `dq`", "Grade every defect and decide its consequence. No value is ever edited."),
        "core": ("Gold -- `core`", "Publish staging minus the blocked rows, with the caveats attached and the derived facts built."),
    }

    out: list[str] = [
        "# Cleaning ledger",
        "",
        "Every transformation between the source file and the published product,",
        "what it does, why, and how much it actually did -- measured by running a",
        "probe against the database rather than written down from memory.",
        "",
        f"Generated by `src/cleaning_ledger.py` at {stamp}.",
        "Re-run it after `make all` and every number below is current.",
        "",
        "**How to read a row.** *Reversible* says where the pre-cleaning value can",
        "still be read, because a cleaning step you cannot undo is a cleaning step",
        "you have to trust. *Watched by* names the rule that reports on whatever the",
        "step could not clean, so a step that quietly stops working is not quiet.",
        "",
    ]

    for layer in ("raw", "stg", "dq", "core"):
        title, blurb = layer_names[layer]
        out += [f"## {title}", "", blurb, ""]
        for step, value in rows:
            if step.layer != layer:
                continue
            shown = f"**{value:,}** {step.unit}" if value is not None else "_probe failed_"
            out += [
                f"### {step.step} -- {step.action}",
                "",
                f"| | |",
                f"|---|---|",
                f"| Target | `{step.target}` |",
                f"| Measured | {shown} |",
                f"| Why | {step.why} |",
                f"| Reversible | {step.reversible} |",
                f"| Watched by | "
                + (", ".join(f"`{r}`" for r in step.watched_by) if step.watched_by else "-")
                + " |",
                "",
            ]

    out += [
        "## What this ledger does not claim",
        "",
        "Three honest limits, stated here rather than left to be discovered.",
        "",
        "1. **No value is repaired.** Nothing in this pipeline guesses a missing",
        "   amount, imputes a balance or corrects a date. Cleaning here means",
        "   typing, normalising, decoding and deriving; a value that is wrong in",
        "   the source is wrong in the product, with a flag on it.",
        "2. **One step removes rows, and only one.** C14 is the single place a row",
        "   leaves the product, it is counted, and C21 proves the arithmetic.",
        "3. **Derived columns are derived, not observed.** Gender (C08), the",
        "   problematic-loan flag (C11), the sign (C10) and every month-end",
        "   balance (C20) are this build's conclusions about the data, not facts",
        "   the bank recorded. Each is listed in ASSUMPTIONS.md with what would",
        "   change if the assumption behind it is wrong.",
        "",
    ]
    return "\n".join(out) + "\n"


def main() -> int:
    """Measure every step and write the ledger.

    :returns: Process exit code; non-zero when a probe failed.
    """
    with db.connect() as conn:
        rows = [(step, measure(conn, step)) for step in STEPS]
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(render(rows), encoding="utf-8")
    failed = [step.step for step, value in rows if value is None]
    LOGGER.info("wrote %s -> %d steps, %d probes failed",
                TARGET.relative_to(config.PROJECT_ROOT), len(rows), len(failed))
    for step, value in rows:
        LOGGER.info("  %-5s %-5s %12s  %s", step.step, step.layer,
                    f"{value:,}" if value is not None else "FAILED", step.action)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
