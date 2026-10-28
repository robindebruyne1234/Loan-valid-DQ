"""Ask the LLM the 10 business questions through the semantic layer.

The loop per question is: render the prompt from the semantic layer, call the
model, parse its JSON, guard the SQL, verify it against the intent (IR) the
model declared, execute it as a consumer role, recompute the certified metric
from the IR, record everything (:mod:`src.sql_ir`, DECISIONS.md D029). One
retry is allowed, when the JSON did not parse or the SQL was refused at any
step: the reason is fed back, which is what a real text-to-SQL service does.
Both attempts are logged, and the deliverable says which attempt produced the
answer.

A question counts as ``answered`` only when every check passed. Passing the
guard alone says the statement may run, not that it answers the question.

Honesty rules enforced in code, not by convention:

* no SQL is ever hand-corrected -- the cell contains what the model produced;
* a question whose call failed is recorded as ``NOT EXECUTED`` with the reason,
  and its SQL cell stays empty;
* the executed result is whatever the database returned, including an error;
* rows are recorded only for SQL that passed verification -- a refused query
  keeps its SQL and the reason, never a number.

The queries run as a consumer role (``cro_global`` by default), so they pass
through the row level security policies exactly as a business user's would.
That role holds a portfolio containing every client, so its numbers are
comparable with the reference answers -- and ``--as-user rm_north`` shows the
same SQL returning that manager's slice instead.

Run with ``make questions``; ``--suite extra`` runs the additional questions
into their own results file.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from src import auth, config, db, llm_client, semantic_context, sql_guard, sql_ir

LOGGER = db.setup_logging("questions")

#: Consumer role the generated SQL is executed as. Entitled to every client,
#: so results are comparable with the reference answers while still being
#: produced through the policy path rather than around it.
DEFAULT_RUN_AS = "cro_global"

#: Maximum attempts per question. The second attempt is only used when the
#: model's output could not be parsed or its SQL was refused.
MAX_ATTEMPTS = 2

#: The status recorded for a statement, by the verification stage it reached.
STATUS_BY_STAGE = {
    "ir": "ir_rejected",
    "columns": "sql_rejected",
    "consistency": "sql_rejected",
    "guard": "guard_rejected",
    "plan": "plan_rejected",
    "execute": "database_error",
    "recompute": "result_mismatch",
    "verified": "answered",
}


def load_questions(suite: str = "core") -> list[dict[str, str]]:
    """Read a question suite: the brief's ten, or the additional ones.

    :param suite: A key of :data:`config.SUITES`.
    :returns: List of ``{"id": ..., "question": ...}`` dictionaries.
    """
    with config.SUITES[suite]["questions"].open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build_prompt(context_pack: str, question_id: str, question: str) -> str:
    """Fill the prompt template with the context pack and one question.

    :param context_pack: Rendered semantic layer.
    :param question_id: Question identifier, for example ``Q3``.
    :param question: The question text.
    :returns: The full user prompt sent to the model.
    """
    template = config.PROMPT_TEMPLATE_MD.read_text(encoding="utf-8")
    # Strip the HTML comment block, which is documentation for the reader of
    # the repository and not instruction for the model.
    template = re.sub(r"<!--.*?-->\s*", "", template, flags=re.DOTALL)
    # The JSON example is written with doubled braces; the model should see JSON.
    template = template.replace("{{", "{").replace("}}", "}")
    return (
        template.replace("{context_pack}", context_pack)
        .replace("{question_id}", question_id)
        .replace("{question}", question)
    )


def parse_model_output(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """Extract the JSON object the model was asked for.

    Tolerant of a markdown fence or surrounding prose, because that is a
    formatting slip rather than a wrong answer; not tolerant of a missing
    ``sql`` field, which is a failure to answer.

    :param text: The model's raw response.
    :returns: Tuple of (parsed object or ``None``, error message or ``None``).
    """
    candidate = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", candidate, flags=re.DOTALL)
    if fenced:
        candidate = fenced.group(1).strip()
    if not candidate.startswith("{"):
        brace = candidate.find("{")
        if brace == -1:
            return None, "no JSON object in the response"
        candidate = candidate[brace:]
        depth = 0
        for index, char in enumerate(candidate):
            depth += {"{": 1, "}": -1}.get(char, 0)
            if depth == 0:
                candidate = candidate[: index + 1]
                break
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return None, f"response is not valid JSON: {exc}"
    if not isinstance(parsed, dict):
        return None, "the JSON is not an object"
    if not parsed.get("sql"):
        return None, "the JSON object has no non-empty 'sql' field"
    return parsed, None


def jsonable(value: Any) -> Any:
    """Make a database value JSON-serialisable.

    :param value: Value from a query result.
    :returns: JSON-friendly equivalent.
    """
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def retry_prompt(base_prompt: str, feedback: str | None) -> str:
    """The prompt for a further attempt, carrying the reason the last one failed.

    :param base_prompt: The prompt of the first attempt.
    :param feedback: Why the previous answer was refused, or ``None``.
    :returns: The prompt to send.
    """
    if not feedback:
        return base_prompt
    return (
        f"{base_prompt}\n\n"
        f"Your previous answer was refused. Reason: {feedback}\n"
        f"Return a corrected JSON object, with an ir that states what the corrected "
        f"SQL computes. Do not explain the refusal."
    )


def verify_and_execute(
    sql: str, ir: Any, question: str, run_as: str
) -> tuple[sql_guard.GuardVerdict, sql_ir.Verification]:
    """Guard, verify against the IR, and only then execute as ``run_as``.

    No database session is opened for a statement the guard or the static
    checks refuse. Shared by the question runner and the web app, so both
    apply exactly the same checks.

    :param sql: The model's SQL.
    :param ir: The model's declared intent (any type; malformed is a finding).
    :param question: The question, for the years/quarters cross-check.
    :param run_as: Consumer role to authenticate as.
    :returns: The guard verdict and the verification; rows are on the
        verification, and only when it is ``ok``.
    """
    verdict = sql_guard.guard(sql)
    if not verdict.allowed:
        return verdict, sql_ir.Verification(
            stage="guard", findings=[f"the SQL guard rejected it: {verdict.reason}"])
    verification = sql_ir.verify_static(sql, ir, question)
    if not verification.ok:
        return verdict, verification
    # Both factors. The generated SQL runs on a session that had to
    # authenticate like any other consumer -- an assistant does not get a
    # standing connection that skipped the login.
    with auth.login(run_as, demo_autocode=True) as conn:
        return verdict, sql_ir.run_verified(conn, sql, ir, question)


def answer_question(
    context_pack: str,
    question_id: str,
    question: str,
    run_as: str,
    provider: str,
    model: str,
    log_prefix: str = "",
) -> dict[str, Any]:
    """Ask the model one question, verify the SQL it produces and execute it.

    :param context_pack: Rendered semantic layer, the model's only knowledge.
    :param question_id: Question identifier.
    :param question: Question text.
    :param run_as: Consumer role the generated SQL is executed as.
    :param provider: LLM provider name.
    :param model: Model identifier.
    :param log_prefix: Subdirectory of ``llm_logs/`` for the call logs, so a
        separate run cannot overwrite the evidence of the official one.
    :returns: A result dictionary for ``llm_results.json``.
    """
    base_prompt = build_prompt(context_pack, question_id, question)
    attempts: list[dict[str, Any]] = []
    feedback: str | None = None
    if log_prefix:
        (config.LLM_LOG_DIR / log_prefix).mkdir(parents=True, exist_ok=True)
    log_name = f"{log_prefix}/{question_id}" if log_prefix else question_id

    for attempt in range(1, MAX_ATTEMPTS + 1):
        prompt = retry_prompt(base_prompt, feedback)

        response = llm_client.complete(prompt, provider=provider, model=model)
        record: dict[str, Any] = {
            "attempt": attempt,
            "executed_call": response.executed,
            "call_error": response.error,
            "duration_sec": round(response.duration_sec, 3),
            "feedback_given": feedback,
        }

        if not response.executed:
            record["status"] = config.NOT_EXECUTED
            llm_client.write_call_log(f"{log_name}_attempt{attempt}", response, record)
            attempts.append(record)
            break

        parsed, parse_error = parse_model_output(response.text)
        if parse_error:
            record.update({"status": "unparsable_response", "parse_error": parse_error})
            llm_client.write_call_log(f"{log_name}_attempt{attempt}", response, record)
            attempts.append(record)
            feedback = parse_error
            continue

        generated_sql = str(parsed["sql"]).strip()
        ir = parsed.get("ir")
        verdict, verification = verify_and_execute(generated_sql, ir, question, run_as)
        status = STATUS_BY_STAGE[verification.stage]
        record.update(
            {
                "generated_sql": generated_sql,
                "ir": ir,
                "model_reasoning": parsed.get("reasoning"),
                "model_assumptions": parsed.get("assumptions"),
                "model_caveats": parsed.get("caveats"),
                "guard_allowed": verdict.allowed,
                "guard_reason": verdict.reason,
                "executed_sql": verdict.rewritten_sql,
                "verification": verification.as_dict(),
                "status": status,
            }
        )
        if status == "database_error":
            record["database_error"] = verification.reason

        if not verification.ok:
            llm_client.write_call_log(f"{log_name}_attempt{attempt}", response, record)
            attempts.append(record)
            feedback = f"it was refused at the {verification.stage} check: {verification.reason}"
            continue

        clean_rows = [{k: jsonable(v) for k, v in row.items()} for row in (verification.rows or [])]
        record.update(
            {
                "row_count": len(clean_rows),
                "columns": list(clean_rows[0].keys()) if clean_rows else [],
                "rows": clean_rows,
            }
        )
        llm_client.write_call_log(f"{log_name}_attempt{attempt}", response, record)
        attempts.append(record)
        break

    final = attempts[-1] if attempts else {"status": config.NOT_EXECUTED}
    status = final.get("status", config.NOT_EXECUTED)
    error = (final.get("call_error") or final.get("parse_error")
             or "; ".join((final.get("verification") or {}).get("findings") or []) or None)
    LOGGER.info(
        "%-4s %-18s attempts=%d rows=%s %s",
        question_id,
        status,
        len(attempts),
        final.get("row_count", "-"),
        f"| {error}" if status != "answered" and error else "",
    )
    return {
        "question_id": question_id,
        "question": question,
        "label": "LLM-GENERATED",
        "provider": provider,
        "model": model,
        "run_as_role": run_as,
        "status": status,
        "attempts": attempts,
        "attempts_used": len(attempts),
        "generated_sql": final.get("generated_sql", ""),
        "ir": final.get("ir"),
        "verification": final.get("verification"),
        "executed_sql": final.get("executed_sql"),
        "rows": final.get("rows", []),
        "row_count": final.get("row_count"),
        "columns": final.get("columns", []),
        "model_reasoning": final.get("model_reasoning"),
        "model_assumptions": final.get("model_assumptions"),
        "model_caveats": final.get("model_caveats"),
        "guard_reason": final.get("guard_reason"),
        "error": error,
        "executed_at_utc": db.utc_now_iso(),
    }


def main() -> int:
    """Run a question suite through the semantic layer and the LLM.

    :returns: Process exit code: ``0`` when every question was answered,
        ``1`` when any question could not be.
    """
    parser = argparse.ArgumentParser(description="Ask the LLM a question suite.")
    parser.add_argument("--as-user", default=DEFAULT_RUN_AS,
                        help="consumer role to execute the generated SQL as")
    parser.add_argument("--provider", default=config.LLM_PROVIDER)
    parser.add_argument("--model", default=config.LLM_MODEL)
    parser.add_argument("--only", help="comma-separated question ids to run")
    parser.add_argument("--suite", choices=sorted(config.SUITES), default="core",
                        help="core: the brief's ten; extra: the additional questions")
    parser.add_argument("--out", type=Path,
                        help="results file (default: the suite's own); use a separate "
                             "file for another provider, so its results are never "
                             "merged with or mistaken for the official run")
    parser.add_argument("--log-prefix",
                        help="subdirectory of llm_logs/ for the call logs (default: "
                             "none for the official core run, else derived from --out "
                             "or the suite)")
    args = parser.parse_args()

    out_path: Path = args.out or config.SUITES[args.suite]["llm_json"]
    official = out_path.resolve() == config.SUITES[args.suite]["llm_json"].resolve()
    log_prefix = args.log_prefix
    if log_prefix is None:
        log_prefix = (out_path.stem if not official
                      else "" if args.suite == "core" else args.suite)

    layer = semantic_context.load_semantic_layer()
    context_pack = semantic_context.render_context_pack(layer)
    questions = load_questions(args.suite)
    if args.only:
        wanted = {q.strip().upper() for q in args.only.split(",")}
        questions = [q for q in questions if q["id"].upper() in wanted]

    LOGGER.info(
        "--- asking %d questions (%s) | provider=%s model=%s run_as=%s | context pack %d chars ---",
        len(questions), args.suite, args.provider, args.model, args.as_user, len(context_pack),
    )

    results: dict[str, Any] = {}
    existing: dict[str, Any] = {}
    if out_path.exists():
        previous = json.loads(out_path.read_text(encoding="utf-8"))
        # Only merge results from the same provider and model: one file must
        # never mix the answers of two models under one label.
        if (previous.get("provider"), previous.get("model")) == (args.provider, args.model):
            existing = previous.get("results", {})
    results.update(existing)

    for question in questions:
        results[question["id"]] = answer_question(
            context_pack,
            question["id"],
            question["question"],
            args.as_user,
            args.provider,
            args.model,
            log_prefix,
        )

    answered = [r for r in results.values() if r["status"] == "answered"]
    payload = {
        "generated_at_utc": db.utc_now_iso(),
        "git_commit": db.git_commit(),
        "label": "LLM-GENERATED (never hand-corrected)",
        "provider": args.provider,
        "model": args.model,
        "run_as_role": args.as_user,
        "context_pack_chars": len(context_pack),
        "command": f"make questions (provider={args.provider}, model={args.model})",
        "suite": args.suite,
        "verification": "src/sql_ir.py (D029): answered = guard, IR, columns, "
                        "consistency, plan, execution and recomputation all passed",
        "llm_log_dir": str((config.LLM_LOG_DIR / log_prefix).relative_to(config.PROJECT_ROOT)),
        "answered": len(answered),
        "total": len(results),
        "results": results,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    LOGGER.info("wrote %s", out_path)

    first_attempt = sum(1 for r in results.values()
                        if r["status"] == "answered" and r["attempts_used"] == 1)
    LOGGER.info("___ question run summary ___")
    LOGGER.info("  answered            : %d of %d", len(answered), len(results))
    LOGGER.info("  answered first try  : %d", first_attempt)
    LOGGER.info("  needed a retry      : %d", len(answered) - first_attempt)
    for result in results.values():
        if result["status"] != "answered":
            LOGGER.warning("  ! %s -> %s (%s)", result["question_id"],
                           result["status"], result.get("error"))

    db.record_run(
        "questions",
        f"make questions (suite={args.suite}, provider={args.provider}, model={args.model})",
        {
            "suite": args.suite,
            "out": str(out_path),
            "answered": len(answered),
            "total": len(results),
            "answered_first_attempt": first_attempt,
            "run_as": args.as_user,
        },
    )
    return 0 if len(answered) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
