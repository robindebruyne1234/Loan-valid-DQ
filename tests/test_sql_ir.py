"""Generated SQL must compute what the model declared, or it does not run (D029).

The guard (tests/test_guard.py) proves a statement is safe to execute. These
tests prove the other half: that a statement which is perfectly safe but
answers a different question -- a column that does not exist, the wrong date,
the wrong quarter, a join that repeats every loan -- is refused, with a reason,
before any number reaches a user. They start from the failure that was
actually observed:

    "Find male or female loans in Q1 1995."
    -> ... SUM(CASE WHEN T2.gender = 'male' ...) FROM ai.loan T1
           JOIN ai.account_owner T2 ...     -- guard: allowed
    -> column t2.gender does not exist      -- database: error

Correct results are checked against SQL written here, on the core tables, not
against the verifier's own recomputation, so a defect shared by the semantic
layer and the verifier cannot make a wrong answer pass.
"""

from __future__ import annotations

import json
import shutil
from contextlib import contextmanager
from typing import Any, Iterator

import pytest

from src import auth, config, db, llm_client, run_questions, sql_guard, sql_ir, webapp
from tests import support

GENDER_Q = "Find male or female loans in Q1 1995."
GENDER_IR = {
    "metric": "loan_count", "entity": "ai.loan", "counting_grain": "loan_id",
    "time": {"column": "loan_date", "periods": [{"from": "1995-01-01", "to": "1995-04-01"}]},
    "group_by": ["owner_gender"], "filters": [], "order": None, "limit": None,
}
#: The statement the application actually produced.
OBSERVED_SQL = """SELECT COUNT(*) AS total_loans,
       SUM(CASE WHEN T2.gender = 'male' THEN 1 ELSE 0 END) AS male_loans,
       SUM(CASE WHEN T2.gender = 'female' THEN 1 ELSE 0 END) AS female_loans
FROM ai.loan AS T1 INNER JOIN ai.account_owner AS T2 ON T1.account_id = T2.account_id
WHERE T1.loan_date >= '1995-01-01' AND T1.loan_date < '1995-04-01'"""
GENDER_SQL = """SELECT owner_gender, count(*) AS loans FROM ai.loan
WHERE loan_date >= DATE '1995-01-01' AND loan_date < DATE '1995-04-01'
GROUP BY owner_gender"""

QUARTERS_Q = "Compare the total amount of loans granted in Q1-Q3 of 1995 with Q1-Q3 of 1998."
QUARTERS_IR = {
    "metric": "total_loan_amount", "entity": "ai.loan", "counting_grain": "loan_id",
    "time": {"column": "loan_date", "periods": [{"from": "1995-01-01", "to": "1995-10-01"},
                                                {"from": "1998-01-01", "to": "1998-10-01"}]},
    "group_by": ["year"],
}


def _ir(**changes: Any) -> dict[str, Any]:
    return {**GENDER_IR, **changes}


def _static(sql: str, ir: Any = GENDER_IR, question: str = GENDER_Q) -> sql_ir.Verification:
    return sql_ir.verify_static(sql, ir, question)


def _refused(sql: str, ir: Any = GENDER_IR, question: str = GENDER_Q) -> sql_ir.Verification:
    result = _static(sql, ir, question)
    assert not result.ok, f"should have been refused: {sql}"
    assert result.findings, "a refusal must say why"
    return result


@pytest.fixture(scope="module")
def independent() -> dict[str, Any]:
    """Answers computed here from the core tables, independently of ai.* and the verifier."""
    with db.connect() as conn:
        gender = {r["gender"]: r["loans"] for r in db.fetch_all(conn, """
            SELECT c.gender, count(*) AS loans
            FROM core.fact_loan l
            JOIN core.bridge_disposition d ON d.account_id = l.account_id AND d.is_owner
            JOIN core.dim_client c ON c.client_id = d.client_id
            WHERE l.loan_date >= DATE '1995-01-01' AND l.loan_date < DATE '1995-04-01'
            GROUP BY c.gender""")}
        loans_q1 = db.fetch_value(conn, """
            SELECT count(*) FROM core.fact_loan
            WHERE loan_date >= DATE '1995-01-01' AND loan_date < DATE '1995-04-01'""")
        totals = {r["y"]: float(r["total"]) for r in db.fetch_all(conn, """
            SELECT extract(year FROM loan_date)::int AS y, sum(amount) AS total
            FROM core.fact_loan WHERE extract(year FROM loan_date) IN (1995, 1998)
              AND extract(month FROM loan_date) <= 9 GROUP BY 1""")}
    return {"gender": gender, "loans_q1_1995": loans_q1, "q1_q3_totals": totals}


# ---------------------------------------------------------------------------
# 1. The observed failure: a nonexistent column, caught before execution
# ---------------------------------------------------------------------------


def test_the_guard_alone_allows_the_observed_statement() -> None:
    """The premise: a guard pass is not evidence of correctness."""
    assert sql_guard.guard(OBSERVED_SQL).allowed


def test_a_nonexistent_gender_column_is_refused_before_execution(monkeypatch) -> None:
    def no_login(*_args, **_kwargs):  # pragma: no cover - reaching this is the failure
        raise AssertionError("a database session was opened for unverified SQL")

    monkeypatch.setattr(auth, "login", no_login)
    verdict, verification = run_questions.verify_and_execute(
        OBSERVED_SQL, GENDER_IR, GENDER_Q, "cro_global")
    assert verdict.allowed                      # the guard says it may run ...
    assert not verification.ok                  # ... the verifier says it must not
    assert verification.stage == "columns"
    assert verification.rows is None
    finding = verification.reason
    assert "t2.gender" in finding.lower() and "ai.account_owner" in finding
    assert "owner_gender" in finding            # the nearest real column is named


def test_the_gender_attribute_lives_on_the_client_only() -> None:
    """Established from the live schema, not assumed: the basis of A47."""
    with db.connect() as conn:
        rows = db.fetch_all(conn, """
            SELECT table_name, column_name FROM information_schema.columns
            WHERE table_schema = 'ai' AND column_name IN ('gender', 'owner_gender')
            ORDER BY 1, 2""")
    where = {(r["table_name"], r["column_name"]) for r in rows}
    assert ("client", "gender") in where
    assert ("loan", "owner_gender") in where and ("account_owner", "owner_gender") in where
    assert ("loan", "gender") not in where and ("account_owner", "gender") not in where


# ---------------------------------------------------------------------------
# 2-3. The correct path, at the correct grain, against an independent answer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sql", [
    GENDER_SQL,
    """SELECT o.owner_gender, count(*) AS loans FROM ai.loan l
       JOIN ai.account_owner o ON o.account_id = l.account_id
       WHERE l.loan_date >= DATE '1995-01-01' AND l.loan_date < DATE '1995-04-01'
       GROUP BY o.owner_gender""",
    """SELECT l.owner_gender, count(*) FROM ai.loan l JOIN ai.calendar c ON c.date_key = l.loan_date
       WHERE c.year = 1995 AND c.quarter = 1 GROUP BY l.owner_gender""",
], ids=["loan.owner_gender", "via account_owner", "via calendar"])
def test_the_owner_gender_path_verifies_and_matches_the_core_tables(sql, independent) -> None:
    with support.consumer("cro_global") as conn:
        result = sql_ir.run_verified(conn, sql, GENDER_IR, GENDER_Q)
    assert result.ok, result.findings
    assert result.stage == "verified"
    got = {r["owner_gender"]: r[[k for k in r if k != "owner_gender"][0]] for r in result.rows}
    assert got == independent["gender"]
    assert sum(got.values()) == independent["loans_q1_1995"]     # every loan once


def test_counting_the_wrong_grain_is_refused() -> None:
    # counts accounts, not loans
    _refused("""SELECT owner_gender, count(DISTINCT account_id) FROM ai.loan
                WHERE loan_date >= DATE '1995-01-01' AND loan_date < DATE '1995-04-01'
                GROUP BY owner_gender""")
    # an IR that declares a different grain for the metric
    assert any("counting_grain" in f for f in _refused(GENDER_SQL, _ir(counting_grain="account_id")).findings)


def test_counting_loan_client_pairs_through_disponents_is_refused() -> None:
    """The alternative reading of A47 must not slip in unannounced."""
    result = _refused("""SELECT c.gender, count(*) FROM ai.loan l
        JOIN ai.card k ON k.account_id = l.account_id
        JOIN ai.client c ON c.client_id = k.holder_client_id
        WHERE l.loan_date >= DATE '1995-01-01' AND l.loan_date < DATE '1995-04-01'
        GROUP BY c.gender""")
    assert result.stage in ("columns", "consistency")


# ---------------------------------------------------------------------------
# 4. Quarter inclusion and exclusion, evaluated day by day
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("where", [
    "loan_date >= DATE '1995-01-01' AND loan_date < DATE '1995-04-01'",
    "loan_date >= '1995-01-01' AND loan_date <= '1995-03-31'",
    "loan_date BETWEEN DATE '1995-01-01' AND DATE '1995-03-31'",
    "extract(year FROM loan_date) = 1995 AND extract(quarter FROM loan_date) = 1",
    "loan_year = 1995 AND extract(month FROM loan_date) IN (1, 2, 3)",
])
def test_every_correct_spelling_of_q1_1995_is_accepted(where) -> None:
    result = _static(f"SELECT owner_gender, count(*) FROM ai.loan WHERE {where} GROUP BY owner_gender")
    assert result.ok, result.findings


@pytest.mark.parametrize("where, why", [
    ("loan_date >= DATE '1995-01-01' AND loan_date < DATE '1995-03-31'", "drops 31 March"),
    ("loan_date BETWEEN DATE '1995-01-01' AND DATE '1995-04-01'", "adds 1 April"),
    ("loan_date > DATE '1995-01-01' AND loan_date < DATE '1995-04-01'", "drops 1 January"),
    ("loan_year = 1995", "the whole year"),
    ("extract(quarter FROM loan_date) = 1", "Q1 of every year"),
    ("loan_date >= DATE '1995-04-01' AND loan_date < DATE '1995-07-01'", "Q2 instead"),
    ("loan_date >= DATE '1996-01-01' AND loan_date < DATE '1996-04-01'", "another year"),
])
def test_a_wrong_period_is_refused(where, why) -> None:
    result = _refused(f"SELECT owner_gender, count(*) FROM ai.loan WHERE {where} GROUP BY owner_gender")
    assert result.stage == "consistency", why


def test_an_ir_for_the_wrong_quarter_contradicts_the_question() -> None:
    q2 = _ir(time={"column": "loan_date", "periods": [{"from": "1995-04-01", "to": "1995-07-01"}]})
    sql = """SELECT owner_gender, count(*) FROM ai.loan
             WHERE loan_date >= DATE '1995-04-01' AND loan_date < DATE '1995-07-01' GROUP BY owner_gender"""
    result = _refused(sql, q2)
    assert result.stage == "ir" and "Q1" in result.reason


def test_q1_read_as_reference_question_1_is_refused() -> None:
    """The context pack labels reference questions Q1-Q10; a user's Q1 is a quarter."""
    _refused("SELECT region, count(*) FROM ai.client GROUP BY region", QUARTERS_IR, QUARTERS_Q)


@pytest.mark.parametrize("sql, ok", [
    ("""SELECT loan_year, sum(amount) FROM ai.loan
        WHERE (loan_date >= DATE '1995-01-01' AND loan_date < DATE '1995-10-01')
           OR (loan_date >= DATE '1998-01-01' AND loan_date < DATE '1998-10-01') GROUP BY loan_year""", True),
    ("""SELECT loan_year, sum(amount) FROM ai.loan
        WHERE loan_year IN (1995, 1998) AND extract(quarter FROM loan_date) <= 3 GROUP BY loan_year""", True),
    ("SELECT loan_year, sum(amount) FROM ai.loan WHERE loan_year IN (1995, 1998) GROUP BY loan_year", False),
    ("""SELECT loan_year, sum(amount) FROM ai.loan
        WHERE loan_year = 1998 AND extract(quarter FROM loan_date) <= 3 GROUP BY loan_year""", False),
    ("""SELECT loan_year, sum(amount) FROM ai.loan
        WHERE extract(quarter FROM loan_date) <= 3 GROUP BY loan_year""", False),
], ids=["half-open", "extract", "quarter bound dropped", "1995 dropped", "years dropped"])
def test_multi_period_quarter_comparisons(sql, ok, independent) -> None:
    result = _static(sql, QUARTERS_IR, QUARTERS_Q)
    assert result.ok is ok, result.findings
    if ok:
        with support.consumer("cro_global") as conn:
            verified = sql_ir.run_verified(conn, sql, QUARTERS_IR, QUARTERS_Q)
        assert verified.ok, verified.findings
        got = {r["loan_year"]: r["sum"] for r in verified.rows}
        assert got == pytest.approx(independent["q1_q3_totals"])


def test_relative_years_in_a_question_are_not_mistaken_for_its_period() -> None:
    ir = {"metric": "account_count", "entity": "ai.account", "counting_grain": "account_id",
          "time": {"column": "open_date", "periods": [{"from": "1993-01-01", "to": "1995-01-01"}]},
          "group_by": []}
    result = _static("SELECT count(*) FROM ai.account WHERE open_date < DATE '1995-01-01'",
                     ir, "How many accounts were opened before 1995?")
    assert result.ok, result.findings


# ---------------------------------------------------------------------------
# 5. The wrong date column
# ---------------------------------------------------------------------------


def test_substituting_the_account_open_date_is_refused() -> None:
    result = _refused("""SELECT l.owner_gender, count(*) FROM ai.loan l
        JOIN ai.account a ON a.account_id = l.account_id
        WHERE a.open_date >= DATE '1995-01-01' AND a.open_date < DATE '1995-04-01'
        GROUP BY l.owner_gender""")
    assert result.stage == "consistency"


def test_an_ir_naming_the_wrong_date_column_is_refused() -> None:
    wrong = _ir(time={"column": "open_date", "periods": GENDER_IR["time"]["periods"]})
    result = _refused(GENDER_SQL, wrong)
    assert result.stage == "ir" and "loan_date" in result.reason


# ---------------------------------------------------------------------------
# 6. One-to-many joins cannot inflate a count or a sum
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("join", [
    "JOIN ai.transaction t ON t.account_id = l.account_id",
    "JOIN ai.card k ON k.account_id = l.account_id",
])
def test_a_fan_out_join_is_refused(join) -> None:
    for measure, ir in (("count(*)", GENDER_IR),
                        ("sum(l.amount)", _ir(metric="total_loan_amount"))):
        result = _refused(f"""SELECT l.owner_gender, {measure} FROM ai.loan l {join}
            WHERE l.loan_date >= DATE '1995-01-01' AND l.loan_date < DATE '1995-04-01'
            GROUP BY l.owner_gender""", ir)
        assert result.stage in ("columns", "consistency"), result.findings


# ---------------------------------------------------------------------------
# 7. Missing periods, wrong grouping, wrong entity
# ---------------------------------------------------------------------------


def test_a_missing_period_filter_is_refused() -> None:
    _refused("SELECT owner_gender, count(*) FROM ai.loan GROUP BY owner_gender")


def test_an_ir_without_the_period_the_question_names_is_refused() -> None:
    result = _refused("SELECT owner_gender, count(*) FROM ai.loan GROUP BY owner_gender", _ir(time=None))
    assert result.stage == "ir"


def test_missing_grouping_is_refused() -> None:
    _refused("""SELECT count(*) FROM ai.loan
                WHERE loan_date >= DATE '1995-01-01' AND loan_date < DATE '1995-04-01'""")


def test_one_column_per_value_is_refused_with_an_instruction() -> None:
    pivot = OBSERVED_SQL.replace("T2.gender", "T2.owner_gender")
    result = _refused(pivot)
    assert "GROUP BY" in result.reason


def test_the_wrong_entity_is_refused() -> None:
    _refused("""SELECT owner_gender, count(*) FROM ai.account_owner
                GROUP BY owner_gender""")
    assert _refused(GENDER_SQL, _ir(entity="ai.account")).stage == "ir"


def test_an_unrequested_filter_is_refused() -> None:
    _refused("""SELECT owner_gender, count(*) FROM ai.loan
                WHERE loan_date >= DATE '1995-01-01' AND loan_date < DATE '1995-04-01'
                  AND status_code = 'A' GROUP BY owner_gender""")


# ---------------------------------------------------------------------------
# 8. A missing, malformed or contradictory IR fails safe
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ir", [
    None, "loan_count", [], {},
    _ir(metric="loans_by_gender"),
    _ir(metric=None),
    _ir(time={"column": "loan_date", "periods": []}),
    _ir(time={"column": "loan_date", "periods": [{"from": "1995-04-01", "to": "1995-01-01"}]}),
    _ir(time={"column": "loan_date", "periods": [{"from": "Q1", "to": "1995-04-01"}]}),
    _ir(time={"column": "loan_date", "periods": [{"from": "2001-01-01", "to": "2001-04-01"}]}),
    _ir(group_by=["gender"]),
    _ir(filters=[{"column": "nope", "op": "=", "value": 1}]),
    _ir(filters=[{"column": "owner_gender", "op": "LIKE", "value": "m%"}]),
    _ir(limit=-1),
], ids=["none", "string", "list", "empty", "uncertified metric", "no metric", "no periods",
        "inverted period", "not a date", "outside the book", "unknown group column",
        "unknown filter column", "unsupported operator", "bad limit"])
def test_a_missing_or_malformed_ir_is_refused_at_the_ir_stage(ir) -> None:
    result = _refused(GENDER_SQL, ir)
    assert result.stage == "ir"


def test_a_verifier_that_cannot_parse_the_sql_refuses() -> None:
    assert _refused("SELEC owner_gender FROM ai.loan").stage == "columns"


def test_the_result_must_equal_the_certified_recomputation() -> None:
    canonical = [{"g0": "male", "value": 18}, {"g0": "female", "value": 10}]
    assert sql_ir.compare_with_canonical(canonical, [{"g": "male", "n": 18}, {"g": "female", "n": 10}]) == []
    problems = sql_ir.compare_with_canonical(canonical, [{"g": "male", "n": 36}, {"g": "female", "n": 20}])
    assert problems and "certified computation" in problems[0]


Q9_SQL = """SELECT round(avg(closing_balance), 2) AS average_month_end_balance
FROM ai.account_month_end_balance
WHERE month_end_date >= DATE '1998-12-31' AND month_end_date < DATE '1999-01-01'"""
Q9_IR = {"metric": "average_month_end_balance", "entity": "ai.account_month_end_balance",
         "time": {"column": "month_end_date", "periods": [{"from": "1998-12-31", "to": "1999-01-01"}]}}


@pytest.mark.parametrize("grain", [["account_id", "month_end_date"], ["month_end_date", "account_id"],
                                   "account_id, month_end_date", "account_id,month_end_date"])
def test_a_composite_grain_may_be_written_as_a_list_or_a_string(grain) -> None:
    """Found in the first verified run: Q9 was refused for writing the grain as a string."""
    result = _static(Q9_SQL, {**Q9_IR, "counting_grain": grain},
                     "What was the average account balance at the end of December 1998?")
    assert result.ok, result.findings


def test_a_different_composite_grain_is_still_refused() -> None:
    result = _refused(Q9_SQL, {**Q9_IR, "counting_grain": "account_id"},
                      "What was the average account balance at the end of December 1998?")
    assert result.stage == "ir"


def test_months_reported_as_numbers_verify() -> None:
    """Found in the first verified run: Q6 grouped by month number was refused at recompute."""
    sql = """SELECT c.month AS month, count(a.account_id) AS account_count FROM ai.calendar c
             LEFT JOIN ai.account a ON a.open_date = c.date_key
             WHERE c.date_key >= DATE '1996-01-01' AND c.date_key < DATE '1997-01-01'
             GROUP BY c.month ORDER BY c.month"""
    ir = {"metric": "account_count", "entity": "ai.account", "counting_grain": "account_id",
          "time": {"column": "open_date", "periods": [{"from": "1996-01-01", "to": "1997-01-01"}]},
          "group_by": ["month"], "order": "asc"}
    with support.consumer("cro_global") as conn:
        result = sql_ir.run_verified(conn, sql, ir, "How many new accounts were opened per month in 1996?")
    assert result.ok, (result.stage, result.findings)
    assert len(result.rows) == 12


def test_the_brief_s_ten_recorded_answers_still_verify() -> None:
    """The verifier must not refuse correct answers: the recorded SQL of the audited run."""
    irs = {
        "Q1": {"metric": "client_count", "entity": "ai.client", "counting_grain": "client_id", "group_by": ["region"]},
        "Q2": {"metric": "total_loan_amount", "entity": "ai.loan", "counting_grain": "loan_id", "group_by": ["year"]},
        "Q3": {"metric": "problematic_loan_share", "entity": "ai.loan", "counting_grain": "loan_id"},
        "Q4": {"metric": "average_loan_amount", "entity": "ai.loan", "counting_grain": "loan_id",
               "group_by": ["owner_card_type"]},
        "Q5": {"metric": "incoming_transaction_amount", "entity": "ai.transaction", "counting_grain": "trans_id",
               "time": {"column": "trans_date", "periods": [{"from": "1997-01-01", "to": "1998-01-01"}]},
               "group_by": ["account_district_name"], "order": "desc", "limit": 10},
        "Q6": {"metric": "account_count", "entity": "ai.account", "counting_grain": "account_id",
               "time": {"column": "open_date", "periods": [{"from": "1996-01-01", "to": "1997-01-01"}]},
               "group_by": ["month"]},
        "Q7": {"metric": "average_age_at_loan_start", "entity": "ai.loan", "counting_grain": "loan_id",
               "group_by": ["status_code"]},
        "Q8": {"metric": "gender_share", "entity": "ai.account_owner", "counting_grain": "account_id",
               "group_by": ["owner_gender"], "filters": [{"column": "owner_card_type", "op": "=", "value": "gold"}]},
        "Q9": {"metric": "average_month_end_balance", "entity": "ai.account_month_end_balance",
               "counting_grain": ["account_id", "month_end_date"],
               "time": {"column": "month_end_date", "periods": [{"from": "1998-12-31", "to": "1999-01-01"}]}},
        "Q10": {"metric": "problematic_loan_share", "entity": "ai.loan", "counting_grain": "loan_id",
                "group_by": ["statement_frequency"]},
    }
    archive = config.DQ_RESULTS_DIR / "archive" / "2026-10-28_before_D028" / "llm_results.json"
    recorded = json.loads(archive.read_text(encoding="utf-8"))["results"]
    with support.consumer("cro_global") as conn:
        for qid, ir in irs.items():
            result = sql_ir.run_verified(conn, recorded[qid]["generated_sql"], ir, recorded[qid]["question"])
            assert result.ok, (qid, result.stage, result.findings)


# ---------------------------------------------------------------------------
# The application paths: the runner and the web app, with a scripted model
# ---------------------------------------------------------------------------


def _reply(sql: str, ir: Any) -> str:
    body: dict[str, Any] = {"sql": sql, "reasoning": "scripted", "assumptions": [], "caveats": []}
    if ir is not ...:
        body["ir"] = ir
    return json.dumps(body)


@pytest.fixture
def scripted(monkeypatch, request):
    """Replace the model with a list of replies and record each prompt it receives."""
    # Call logs go to an ignored scratch directory inside the repository (the
    # log writer reports paths relative to it), never among the evidence.
    logs = config.PROJECT_ROOT / "scratch" / "pytest_llm_logs" / request.node.name
    shutil.rmtree(logs, ignore_errors=True)
    logs.mkdir(parents=True)
    request.addfinalizer(lambda: shutil.rmtree(logs, ignore_errors=True))
    with support.consumer("cro_global"):
        pass                                   # log in once, before login is redirected
    logins: list[str] = []

    @contextmanager
    def reuse_session(role: str, demo_autocode: bool = False) -> Iterator[Any]:
        logins.append(role)
        with support.consumer(role) as conn:
            yield conn

    monkeypatch.setattr(auth, "login", reuse_session)
    monkeypatch.setattr(config, "LLM_LOG_DIR", logs)
    replies: list[str] = []
    prompts: list[str] = []

    def complete(prompt: str, provider: str | None = None, model: str | None = None):
        prompts.append(prompt)
        return llm_client.LLMResponse(provider="scripted", model="scripted", executed=True,
                                      text=replies.pop(0), user_prompt=prompt)

    monkeypatch.setattr(llm_client, "complete", complete)
    return {"replies": replies, "prompts": prompts, "logins": logins, "logs": logs}


def test_runner_refuses_the_observed_sql_then_answers_the_corrected_retry(scripted, independent) -> None:
    scripted["replies"] += [_reply(OBSERVED_SQL, GENDER_IR), _reply(GENDER_SQL, GENDER_IR)]
    result = run_questions.answer_question("pack", "E1", GENDER_Q, "cro_global", "scripted", "scripted")
    first, second = result["attempts"]
    assert first["status"] == "sql_rejected"
    assert first["guard_allowed"] is True                    # the guard did not catch it
    assert "rows" not in first
    assert "owner_gender" in scripted["prompts"][1]          # the reason was fed back
    assert scripted["logins"] == ["cro_global"]              # no session for the refused SQL
    assert result["status"] == "answered" and result["attempts_used"] == 2
    assert result["verification"]["ok"] and result["ir"] == GENDER_IR
    assert {r["owner_gender"]: r["loans"] for r in result["rows"]} == independent["gender"]
    assert (scripted["logs"] / "E1_attempt1.json").exists()


def test_runner_records_no_rows_when_the_ir_is_missing(scripted) -> None:
    scripted["replies"] += [_reply(GENDER_SQL, ...), _reply(GENDER_SQL, ...)]
    result = run_questions.answer_question("pack", "E1", GENDER_Q, "cro_global", "scripted", "scripted")
    assert result["status"] == "ir_rejected"
    assert result["rows"] == [] and result["row_count"] is None
    assert "no IR" in result["error"]
    assert scripted["logins"] == []


def test_runner_writes_a_separate_run_to_its_own_log_directory(scripted) -> None:
    scripted["replies"] += [_reply(GENDER_SQL, GENDER_IR)]
    run_questions.answer_question("pack", "E1", GENDER_Q, "cro_global", "scripted", "scripted",
                                  log_prefix="llm_results_ollama")
    assert (scripted["logs"] / "llm_results_ollama" / "E1_attempt1.json").exists()
    assert not (scripted["logs"] / "E1_attempt1.json").exists()


def test_web_ask_shows_no_rows_for_unverified_sql(scripted, monkeypatch) -> None:
    monkeypatch.setattr(webapp, "context_pack", lambda: "pack")
    scripted["replies"] += [_reply(OBSERVED_SQL, GENDER_IR), _reply(OBSERVED_SQL, GENDER_IR)]
    result = webapp.ask("cro_global", GENDER_Q)
    assert result["stage"] == "sql"
    assert result["guard"]["allowed"] is True
    assert result["verification"]["ok"] is False
    assert "owner_gender" in result["error"]
    assert "rows" not in result
    assert scripted["logins"] == []


def test_web_ask_answers_through_the_verifier_as_the_persona(scripted, monkeypatch, independent) -> None:
    monkeypatch.setattr(webapp, "context_pack", lambda: "pack")
    scripted["replies"] += [_reply(GENDER_SQL, GENDER_IR)]
    result = webapp.ask("cro_global", GENDER_Q)
    assert result["stage"] == "done", result.get("error")
    assert result["verification"]["ok"] and result["ir"] == GENDER_IR
    assert {r["owner_gender"]: r["loans"] for r in result["rows"]} == independent["gender"]
    assert scripted["logins"] == ["cro_global"]
    assert any(scripted["logs"].joinpath("web").iterdir())
