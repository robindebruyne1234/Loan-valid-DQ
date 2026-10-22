"""Write ``STATUS_REPORT.md``: what ran, what it produced, what did not run.

The honesty rules in the brief require that any step which did not execute is
marked ``NOT EXECUTED`` rather than described as if it had. This module reads
the run log and the result files and reports the state of the submission as it
actually is -- including, if it happens, that the LLM was never reachable.

Run with ``make status``.
"""

from __future__ import annotations

import json
from typing import Any

from src import config, db

LOGGER = db.setup_logging("status")

#: Pipeline steps in order, with the file that proves each one ran.
STEPS: tuple[tuple[str, str, Any], ...] = (
    ("ingest", "make ingest", None),
    ("profile", "make profile", config.PROFILE_JSON),
    ("dq", "make dq", config.DEFECTS_CSV),
    ("model", "make model", config.MODEL_EXPLANATION_MD),
    ("reference", "make reference", config.REFERENCE_RESULTS_JSON),
    ("semantic", "make semantic", config.SEMANTIC_DIR / "context_pack.md"),
    ("entitlements", "make entitlements", None),
    ("questions", "make questions", config.LLM_RESULTS_JSON),
    ("evaluate", "make evaluate", config.EVALUATION_JSON),
    ("workbook", "make workbook", config.WORKBOOK_XLSX),
    ("ddr", "make ddr", config.DDR_DOCX),
    ("zip", "make zip", config.SEMANTIC_ZIP),
)


def load_run_log() -> dict[str, dict[str, Any]]:
    """Read the most recent run log entry per step.

    :returns: Mapping of step name to its latest log entry.
    """
    if not config.RUN_LOG_JSONL.exists():
        return {}
    latest: dict[str, dict[str, Any]] = {}
    for line in config.RUN_LOG_JSONL.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        latest[entry["step"]] = entry
    return latest


def main() -> int:
    """Write the status report.

    :returns: Process exit code, ``0`` on success.
    """
    log = load_run_log()
    llm = (
        json.loads(config.LLM_RESULTS_JSON.read_text(encoding="utf-8"))
        if config.LLM_RESULTS_JSON.exists()
        else {}
    )
    evaluation = (
        json.loads(config.EVALUATION_JSON.read_text(encoding="utf-8"))
        if config.EVALUATION_JSON.exists()
        else {}
    )

    lines = [
        "# STATUS REPORT",
        "",
        f"Generated at {db.utc_now_iso()} (git {db.git_commit()}).",
        "",
        "This report exists because of the honesty rules: a step that did not run",
        "is marked `NOT EXECUTED` here and its cells in the deliverables are left",
        "empty, rather than being filled with something plausible.",
        "",
        "## Pipeline steps",
        "",
        "| step | command | status | last run (UTC) | evidence |",
        "|---|---|---|---|---|",
    ]
    for step, command, artefact in STEPS:
        entry = log.get(step)
        exists = artefact is None or artefact.exists()
        if entry and exists:
            status = "executed"
        elif entry and not exists:
            status = "executed, artefact missing"
        else:
            status = f"**{config.NOT_EXECUTED}**"
        evidence = (
            str(artefact.relative_to(config.PROJECT_ROOT))
            if artefact is not None and artefact.exists()
            else ("database only" if artefact is None and entry else "-")
        )
        lines.append(
            f"| {step} | `{command}` | {status} | "
            f"{entry['executed_at_utc'] if entry else '-'} | {evidence} |"
        )

    lines += [
        "",
        "## LLM execution",
        "",
    ]
    if llm:
        results = llm.get("results", {})
        answered = [r for r in results.values() if r.get("status") == "answered"]
        first_try = [r for r in answered if r.get("attempts_used") == 1]
        lines += [
            f"- provider: `{llm.get('provider')}`",
            f"- model: `{llm.get('model')}`",
            f"- isolation: no tools, no MCP servers, no filesystem, no database access; "
            f"the model received the rendered semantic layer "
            f"({llm.get('context_pack_chars', 0):,} characters) and the question, and nothing else",
            f"- executed as consumer role: `{llm.get('run_as_role')}` (so every query "
            f"passed through the row level security policies)",
            f"- questions answered: **{len(answered)} of {llm.get('total', 10)}**",
            f"- answered on the first attempt: **{len(first_try)}**",
            f"- SQL hand-corrected: **none**. The Questions tab shows what the model produced.",
            f"- call logs: `llm_logs/` ({len(list(config.LLM_LOG_DIR.glob('*.json')))} files, "
            f"each with the full prompt, parameters, raw response, timing and cost)",
            "",
        ]
        unanswered = [r for r in results.values() if r.get("status") != "answered"]
        if unanswered:
            lines.append("Questions without an answer:")
            lines.append("")
            for result in unanswered:
                lines.append(
                    f"- **{result['question_id']}**: {result.get('status')} -- "
                    f"{result.get('error') or result.get('guard_reason')}"
                )
            lines.append("")
    else:
        lines += [
            f"**{config.NOT_EXECUTED}** -- no LLM call was made. The runner, the",
            "provider abstraction and the context pack are built and testable; the",
            "generated-SQL cells in the Questions tab are empty.",
            "",
        ]

    if evaluation:
        tally = evaluation.get("tally", {})
        lines += [
            "## Evaluation against the hand-written reference answers",
            "",
            f"- comparison: {evaluation.get('comparison_method')}",
            "",
            "| verdict | questions |",
            "|---|---:|",
        ]
        for verdict in ("match", "partial", "mismatch", "not_executed"):
            lines.append(f"| {verdict} | {tally.get(verdict, 0)} |")
        lines.append("")

    lines += [
        "## Steps that were planned and did not run",
        "",
    ]
    not_run = [
        f"- `{command}` ({step})"
        for step, command, artefact in STEPS
        if step not in log
    ]
    if not_run:
        lines += not_run
    else:
        lines.append("None. Every planned step executed.")
    lines += [
        "",
        "## Known limitations, stated rather than hidden",
        "",
        "- **No bank-supplied copy of the data was received**, so `data/raw/provided/`",
        "  is empty and the public copy is the primary dataset. Its row counts match",
        "  the published reference exactly, which means it carries none of the",
        "  injected defects the assessment may compare against. The rules are proven",
        "  against a deliberately corrupted copy instead (20 seeded defects, schema",
        "  `inject`), and running them on the bank's copy needs no change: drop the",
        "  files in `data/raw/provided/` and re-run `make all`.",
        "- **Ollama was the documented default LLM** and is not reachable from the",
        "  build environment (not installed, and the model download hosts are not on",
        "  the egress allow-list). The provider abstraction keeps it, untested.",
        "- **Docker was not available** (CLI present, no daemon), so PostgreSQL 16",
        "  runs from a native cluster. The DDL, the policies and the tests are",
        "  identical; `docker-compose.yml` is shipped and `make up` prefers it.",
        "- **`core.v_*` views and `ai.*` views are rebuilt on every `make model`**,",
        "  which drops and recreates the consumer surface. The target restores it.",
        "",
    ]

    config.STATUS_REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("wrote %s", config.STATUS_REPORT_MD.relative_to(config.PROJECT_ROOT))
    executed = sum(1 for step, _, _ in STEPS if step in log)
    LOGGER.info("  steps executed: %d of %d", executed, len(STEPS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
