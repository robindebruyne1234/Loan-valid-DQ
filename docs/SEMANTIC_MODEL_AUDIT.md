# Semantic model audit: text-to-SQL correctness

Status: audit completed 2026-10-28 on branch `ccr-46f6f45a-t9wtd4`, starting from
commit `c40d611`. The database had been built from the same SQL. The scope was
semantic correctness: dimensions, grain, joins, business definitions, SQL
generation and verification. No new runtime features were added.

**Evidence labels used below**

| Label | Meaning |
|---|---|
| **[RUN]** | Executed during this audit (read-only against the database, or a test run) |
| **[CODE]** | Read in the source at the cited line |
| **[LLM]** | Live call through the project's sandboxed provider (`claude_cli`, `claude-sonnet-5-5`); outputs kept outside the repository |
| **[REC]** | Recommendation, not implemented |
| **[ASSUMED]** | Needs business confirmation |

The Ollama model you run locally was **not** available here. Every live-model result
below comes from Claude Sonnet 5.5, not from Ollama.

---

## 1. Current design: how a question becomes SQL

```
question ──► build_prompt()            src/run_questions.py:58  (template: semantic/prompt_template.md)
              └─ context pack            semantic/context_pack.md, rendered from semantic/semantic_layer.yaml
                                         by render_context_pack()  src/semantic_context.py:242
          ──► llm_client.complete()    one sandboxed call: no tools, no database
          ──► parse_model_output()     src/run_questions.py:77   JSON {sql, reasoning, assumptions, caveats}
          ──► sql_guard.guard()        src/sql_guard.py:125      shape only: one SELECT, ai.* only, LIMIT, timeout
          ──► execute as the persona   row level security narrows the rows
          ──► evaluate (offline only)  src/evaluate.py:65        the 10 reference questions, one key measure each
```

- **The web app uses the same path**: `src/webapp.py:411`, with question id `"WEB"` at
  `:429` and the guard at `:475` **[CODE]**.
- **The pipeline runner**: `answer_question()` at `src/run_questions.py:126` **[CODE]**.
- **Nothing between the parser and execution compares the SQL with what the user
  asked.** The guard decides only whether a statement may run, not whether it answers
  the question **[CODE]**. The quarter probe in §2.5 shows this.

---

## 2. Findings for the six critical questions

### 2.1 Schema and dimensions: are the calendar and transaction fact described accurately?

The data is right. The description had gaps.

| Check | Result |
|---|---|
| `ai.calendar` content **[RUN]** | 2,191 days, 1993-01-01 to 1998-12-31. Quarter 1 = months 1–3, 2 = 4–6, 3 = 7–9, 4 = 10–12. 0 rows where quarter ≠ month bucket, year ≠ year(date_key) or `is_month_end` is wrong |
| Declared column types vs `information_schema` **[RUN]** | All 105 columns match |
| `ai.transaction` | Grain is one row per posting (1,056,319 rows). The join `trans_date = date_key` was declared and holds (many-to-one, no unmatched rows) **[RUN]** |

**Defects in what the model was told** (all fixed in §5 unless marked):

| # | Defect | Evidence |
|---|---|---|
| S1 | **"Q1" collides.** The context pack labels the ten reference questions "Q1"–"Q10" ("Relevant to: Q1", "the region Q1 groups by"). A user's "Q1" means a calendar quarter, and nothing told the model which reading applies | Old `semantic/context_pack.md`, entity sections **[RUN grep]** |
| S2 | **Quarter meaning was implicit.** The column was described only as "Calendar quarter, 1 to 4". The calendar entity and QR6 mentioned only "per month or per year" | Old `semantic_layer.yaml` (calendar entity and QR6) |
| S3 | **Metrics had no time anchor.** No metric said which date its periods are filtered on (`loan_date`, `open_date`, `trans_date`, `month_end_date`). For a loan question, an account's `open_date` is a plausible wrong anchor | Old `metrics:` block |
| S4 | **Join paths from loan and account dates to the calendar were missing.** Only the transaction→calendar join was declared | Old `joins:` blocks |
| S5 | **One instruction was false.** The glossary said a calendar-year age difference "reports ages about half a year too high". Measured per status, the calendar-year difference is within 0.11 years of the exact average; it is truncated whole years that read about 0.5 years **low** (A: 37.07 exact, 37.04 calendar-year, 36.59 truncated). The same claim was in `ASSUMPTIONS.md` A10 | **[RUN]** |
| S6 | **`client_ref` was described twice**, with different wording | Validator run on the old file **[RUN]** |
| S7 | **Stale figures and values:** `ai.code_reference` row count 27 (actual 28); "123 data quality rules" (actual 124); `principal_type` allowed values lacked `administrator` (present in `sec.app_user`) | **[RUN]** |
| S8 | **Month-end balance coverage was unstated.** Rows start at each account's first posting month (185,615 rows, not 4,500 × 72), so an average at an early month end covers only accounts active by then | **[RUN]** |

### 2.2 Grain and joins: can joins multiply rows or lose records?

**Declared grain vs actual.** The validator checks every declared key for uniqueness,
and all eleven entities pass **[RUN]**:

| Entity | Declared grain |
|---|---|
| `ai.loan` | `loan_id` |
| `ai.transaction` | `trans_id` |
| `ai.account_month_end_balance` | (`account_id`, `month_end_date`) |
| `ai.calendar` | `date_key` |

**Join cardinality, measured** (owner session, unfiltered) **[RUN]**:

| Join (as declared) | Actual | Risk |
|---|---|---|
| `ai.account` → `ai.transaction` on `account_id` | 1 : up to 675 | **Fan-out**: sums and counts on the account side multiply |
| `ai.account_owner` → `ai.account_month_end_balance` | 1 : up to 72 | **Fan-out** unless `month_end_date` is filtered first |
| `ai.loan` → `ai.transaction` (via `account_id`) | not declared | Inflates the Q1–Q3 loan total from 9,033,564 to 3,673,719,060 for 1995 (×406) and from 21,046,932 to 3,142,960,068 for 1998 (×149). Counts loans as postings (26,078 "loans") |
| `ai.client` → `ai.account_owner` | 1 : 0..1 here | **Row loss**: 869 clients own no account, and an INNER JOIN drops them |
| `ai.account` / `ai.account_owner` → `ai.loan` | 1 : 0..1 | **Row loss**: 3,818 accounts have no loan |
| All many-to-one joins (to district, account, client, calendar) | Target unique, no unmatched rows | Safe |

- **Before the audit:** cardinality and row loss were neither documented nor enforced.
  The `joins:` entries carried only an `on` clause, and the validator compared column
  names only (`validate()`, `src/semantic_context.py:46`) **[CODE]**.
- **After:** every join declares a cardinality and an `optional` flag, both rendered
  into the pack. The validator measures them on every build (`_validate_joins()`,
  `src/semantic_context.py:197`). A wrong declaration fails `make semantic` and
  `tests/test_semantic.py` **[RUN]**.

### 2.3 Business semantics: is "problematic loan" consistent?

Yes. It is defined once in meaning, but in two places in code.

| Layer | Definition | Location |
|---|---|---|
| Staging | `upper(norm_text(status)) IN ('B','D')` | `sql/10_stg.sql:330` |
| Core | `status_code IN ('B','D')` | `sql/30_core.sql:344` |
| AI view | passes `is_problematic` through | `sql/40_ai_views.sql:163` |
| Semantic layer | glossary (B or D; NOT A/C; "only B" is a different number), metric `problematic_loan_share`, column description | `semantic/semantic_layer.yaml` glossary and metrics |
| Reference SQL | `count(*) FILTER (WHERE is_problematic)` / `count(*)` | `sql/60_reference_queries.sql:67-68,245-246` |
| Generated SQL (recorded) | uses `is_problematic` for Q3 and Q10 | `dq/results/llm_results.json` |

- **Status mapping:** A paid, B unpaid default, C running OK, D running in debt
  (`core.ref_codes`) **[RUN]**.
- **Unknown statuses:** blocked by `VAL_LOAN_STATUS_DOMAIN` **[CODE]**.
- **Agreement:** staging and core agree on all 682 loans **[RUN]**.
- **Remaining risk:** two code sites for one rule. Core should reuse
  `stg.is_problematic` **[REC]**.

The other definitions are consistent between layer, reference and generated SQL:
- **incoming** = `direction='credit'`, `sum(amount)`;
- **loan amount** = principal, dated by `loan_date`;
- **age** = pre-computed `owner_age_at_loan_start`.

The month-end balance definition is consistent, but its tie-break is wrong at row level
(§6, risk 1).

### 2.4 Analytical requirements: an intermediate representation (IR)

The simplest form that fits the current architecture is a small JSON object the model
returns in the **same** response as the SQL. The prompt already asks for one JSON
object, so this adds one key and no extra call.

```json
{
  "metric":        "total_loan_amount",
  "entity":        "ai.loan",
  "counting_grain":"loan_id",
  "aggregation":   "sum(amount)",
  "time": {
    "column":         "loan_date",
    "calendar_grain": "quarter",
    "quarters":       [1, 2, 3],
    "periods": [
      {"label": 1995, "from": "1995-01-01", "to": "1995-10-01"},
      {"label": 1998, "from": "1998-01-01", "to": "1998-10-01"}
    ]
  },
  "group_by":   ["period"],
  "filters":    [],
  "comparison": {"type": "period_vs_period", "periods": [1995, 1998]}
}
```

This is the example question, *"Compare the total amount of loans granted in Q1–Q3 of
1995 with Q1–Q3 of 1998."*

- **Correct answer [RUN]:** 1995: 63 loans, 9,033,564 CZK; 1998: 132 loans, 21,046,932
  CZK.
- **Q1 only:** 28 loans / 4,233,552 and 50 loans / 8,087,640.

**What each field buys.** Every field corresponds to one check in §2.5.

| Field | Check it enables |
|---|---|
| `metric` | Must name a certified metric; otherwise the question is out of coverage |
| `entity` / `counting_grain` | The fan-out and wrong-entity checks |
| `time.column` | Must equal the metric's `time_column` |
| `periods` | Become required predicates, one per year, each with its quarter bound |

**Recommended rollout [REC]:**
1. **Verify.** The model returns the IR alongside the SQL. A deterministic verifier
   checks the SQL against the IR (static checks plus differential execution), and the
   question text is cross-checked for years and quarters with a regex. A failure
   triggers the existing single retry with the reason (`MAX_ATTEMPTS = 2`), then
   "cannot answer reliably".
2. **Route.** For certified metrics, compile SQL from the IR (`compile_ir()` in the
   prototype) and use the model only to fill the IR. Questions outside the metric list
   go to free SQL marked "unverified", or to a polite decline. This matches the
   "semantic router" pattern in your reference diagram.

The prototype covers metric × time-periods only. Group-by dimensions, filters and
ratios still need writing **[REC]**.

### 2.5 SQL verification: does the IR survive generation?

**The current guard does not check semantics [RUN].** All of these were *allowed* and
ran (probe script kept outside the repository):

| Variant | Guard | Result | What is wrong |
|---|---|---|---|
| A: half-open ranges on `loan_date` | allowed | 1995: 9,033,564 · 1998: 21,046,932 | correct |
| B: quarter bound dropped | allowed | 1995: 13,344,372 · 1998: 24,869,148 | full years |
| C: 1995 dropped | allowed | 1998 only | missing comparison side |
| D: year filter dropped | allowed | 6 rows, every year | wrong periods |
| E: loan joined to transactions | allowed | 3.67 bn and 3.14 bn | fan-out |
| F: account `open_date` as the anchor | allowed | 1995: 11,906,016, no 1998 row | wrong date |
| G: "Q1" read as reference question 1 | allowed | clients per region | wrong entity |

**With the IR, every defect is caught before an answer is trusted [RUN].** The
prototype is `scripts/ir_check_prototype.py`: read-only, not imported by the app.
(Superseded by `src/sql_ir.py`, now active in the runner and the web app; see §8.)

| Case | Static check | Differential check | Verdict |
|---|---|---|---|
| A correct ranges / A′ correct via `ai.calendar` | – | – | PASS |
| H "Q1 only" (own IR) | – | – | PASS |
| I the model's SQL with the old pack (`make_date` form) | – | – | PASS |
| B quarter bound dropped | no quarter/month bound | values missing | FLAG |
| C 1995 dropped | year 1995 absent | 1995 missing | FLAG |
| D years dropped | years absent | *passes* (result contains extra rows) | FLAG |
| E fan-out | undeclared join loan→transaction | values missing | FLAG |
| F wrong date | time_column `loan_date` not filtered | values missing | FLAG |
| G wrong entity | entity not queried, years absent | values missing | FLAG |

How each class of error is detected:
- **Missing predicates:** every IR year must appear, and a quarter bound or month bound
  must be present. This check is lexical, so it can misjudge unusual but correct
  forms; the differential check covers that.
- **Incorrect joins:** a join must be a declared path, and a `to-many` path from the
  counted entity is a fan-out unless the aggregate is `DISTINCT`.
- **Wrong aggregation grain:** the differential result must contain the canonical
  (period, value) pairs.
- **Unsupported metrics:** the IR metric must be in `metrics:`.

The two layers cover each other's gaps: the differential check alone misses D, and the
static check alone is heuristic.

### 2.6 Evidence and evaluation

**How generated SQL is compared:**
- `src/evaluate.py` compares the LLM's result rows with the hand-written reference
  results (`sql/60_reference_queries.sql`).
- It checks one key measure per question (`EXPECTATIONS`, `:65`), with an absolute
  tolerance of 0.011 (`:49`).
- Row order is checked for Q5, Q6 and Q10.
- It compares values, not SQL structure, and only for the ten known questions.

**Tests that prove semantic correctness today:**
- `tests/test_reference_queries.py` (14): the reference answers' internal consistency.
- `tests/test_evaluate.py` (13): the evaluator catches wrong numbers, rankings and
  truncation.
- `tests/test_semantic.py`: declared grain, schema agreement, required definitions in
  the pack, no answer leakage.

**Missing regression cases, now added [RUN]** (all in `tests/test_semantic.py`):

| Test | Line | Guards |
|---|---|---|
| `test_validator_catches_join_grain_and_metadata_drift` | `:110` | Fan-out declared as one-to-one, undeclared row loss, duplicate column, stale row count, wrong metric `time_column` |
| `test_context_pack_defines_quarters_and_time_anchors` | `:141` | Quarter definitions, the Q-label disambiguation, time anchors, cardinalities in the pack |
| `test_calendar_quarters_agree_with_date_ranges` | `:161` | Calendar quarter semantics, and the two correct formulations of the example agreeing row for row |
| `test_the_traps_the_pack_warns_about_are_real` | `:186` | The age-bias direction, the >100× fan-out claim and the 869 dropped clients, measured |

**Still missing [REC]:**
- A hold-out set of new or paraphrased questions, including period comparisons.
- An IR verifier wired into the runtime, with its own tests.
- Repeated-sample stability for the model.
- Q-label leakage: question ids remain in the pack.

---

## 3. Design choices

**C1. Disambiguate "Q1" with an explicit rule rather than renaming question ids.**
- **Rationale:** a new rule (QR11) and a glossary entry state that Q1–Q4 in a question
  are calendar quarters and that Q1–Q10 in the pack only name reference questions.
  This is additive, so the ten questions' behaviour is preserved.
- **Alternatives:**
  - Remove all question ids from the pack. This is cleaner and also removes evaluation
    leakage, but changes what the recorded 10/10 run saw.
  - Rename them to "RQ1". Same issue.
- **Trade-off:** the collision text stays, now explained.
- **Evidence:** after the change, 10/10 still match **[LLM]**, and both quarter
  questions come back in canonical half-open form **[LLM]**. Sonnet 5.5 also answered
  them correctly *before* the change **[LLM]**: the collision is a risk for weaker
  models, not an observed failure for this one. Ollama behaviour is untested here.

**C2. Give each metric a `time_column`.**
- **Rationale:** the period filter belongs to the metric, not to the question wording.
  It is the anchor the IR and verifier need.
- **Alternatives:** rely on column descriptions, which said "loan_date is when a loan
  is granted" but nothing for transactions or balances. Or materialise a quarter column
  per fact, which is a schema change and unnecessary because `ai.calendar` exists.
- **Trade-off:** one more field to maintain. The validator checks that it exists on the
  metric's entity.

**C3. Declare join cardinality and optionality, and measure both on every build.**
- **Rationale:** a join path is advice the model cannot check, so a wrong one silently
  double-counts or drops rows.
- **Alternatives:** document in prose only (unenforced), or block joins in the guard
  (too blunt: one-to-many joins are legitimate after pre-aggregation).
- **Trade-off:** seventeen extra GROUP BY queries per validation, a few seconds.
- **Evidence:** run against the old YAML, the hardened validator reports 19 problems
  (1 duplicate, 17 joins without a cardinality, 1 stale row count); against the new
  one, 0 **[RUN]**.

**C4. Verifier as a prototype, not wired in.**
- **Rationale:** wiring changes the prompt contract (the model must return the IR) and
  the runtime path, which would need a fresh evaluation and was out of scope for "no
  new features". The prototype proves feasibility on real data.
- **Trade-off:** today's application still cannot detect a semantically wrong query.
  That is stated as risk 2.

**C5. Leave the month-end tie-break unchanged; correct its caveat.**
- **Rationale:** fixing it changes 154,018 rows of a certified fact and the Q9
  reference (by +1.79 CZK). The recorded LLM answers and both workbooks would then need
  regenerating, which is not low-risk the day before delivery.
- **Action taken:** caveat C2 now states the known limitation instead of claiming it
  cannot be resolved.

**C6. Correct false and stale metadata in place** (S5–S8).
- **Rationale:** a false instruction is worse than a missing one.
- **Trade-off:** none; the content is measured.

---

## 4. Answers to the delivery checks in your notes

- **Q9 "76 vs 7" carried-forward count.** In every committed artefact both sides say
  76 **[RUN]**: `reference_results.json` (`accounts_carried_forward=76`),
  `llm_results.json` (`carried_forward_balances=76`), and both workbooks. Both measure
  the same thing: accounts whose 1998-12-31 balance is inherited. That is one row per
  account at that month end, so rows equal accounts. The different figure 558 counts
  carried-forward rows across *all* month ends. A "7" must come from your local copy
  (possibly a narrow cell or a local-model run). Check that file.
- **A36 / D022.** Now labelled superseded by A39 / D023 in `ASSUMPTIONS.md` and in the
  D022 heading in `DECISIONS.md`.

---

## 5. Changes made, tests run, results

| File | Change |
|---|---|
| `semantic/semantic_layer.yaml` | QR6 now covers quarters. New QR11 (time anchor, half-open ranges, calendar quarters, Q-label disambiguation) and QR12 (counting grain and fan-out). Glossary `quarter` added. False age claim corrected. `time_column` on 10 metrics. Cardinality and `optional` on all 17 joins, plus 2 new calendar joins. Calendar and month-end-balance descriptions completed. Duplicate `client_ref` removed. Row count 28, 124 rules, `administrator` added. C2 caveat corrected |
| `src/semantic_context.py` | Validator: duplicate columns, row-count drift, join cardinality and optionality measured, metric `time_column` exists. Renderer: prints `time_column` and join cardinality |
| `semantic/context_pack.md` | Regenerated (431 lines, about 8,300 tokens). This is the text the model now receives |
| `tests/test_semantic.py` | 4 regression tests (§2.6) |
| `ASSUMPTIONS.md` | A10's alternative corrected with measured figures; A36 marked superseded |
| `DECISIONS.md` | D022 marked superseded by D023 / D024 |
| `scripts/ir_check_prototype.py` | Prototype IR verifier for §2.5. Read-only; not imported anywhere |
| `dq/results/run_log.jsonl` | Two `make semantic` run records, appended by the tool |

**Results:**

| Run | Result |
|---|---|
| `pytest` (full suite) | **245 passed** in 173 s **[RUN]**. Before: 241; the 4 new tests account for the difference |
| `tests/test_semantic.py` | 11 passed **[RUN]** |
| Ten questions with the **new** pack, scored by `src/evaluate.py` | **10/10 match**, one attempt each **[LLM]**. Executed as the owner in a read-only transaction; `cro_global` sees every client, so its rows are identical. Outputs kept outside the repository |
| Quarter probe, new pack | Canonical SQL; results verified against an independent calendar join (334 accounts in Q1 1996 = 106 + 104 + 124) **[LLM][RUN]** |

**Not regenerated (deliberately):**
- `deliverables/*.xlsx` and `semantic_solution.zip` still embed the old pack and A10
  text. Regenerate with `make workbook`, `make zip` and
  `python scripts/make_summary_workbook.py` after pulling, and after reconciling your
  local 9-tab copy.
- `dq/results/llm_results.json` and `evaluation.json` are the old-pack run. To make the
  official evidence match the delivered pack, run `make questions && make evaluate`.

---

## 6. Unresolved assumptions (need a business answer)

1. "Q1–Q3" means **calendar** quarters **[ASSUMED]**. The book has no fiscal calendar.
   If the bank's year is fiscal, QR11, the glossary and `ai.calendar` need a fiscal
   column.
2. **The shape of a period comparison:** one row per year, or also a difference or
   ratio? The IR has a `comparison` field, but the expected output is not defined
   **[ASSUMED]**: rows per year with counts.
3. **Does "incoming" include bank interest (`UROK`)?** It does today (A7). It does not
   change the Q5 top ten, but it does change totals.
4. **Are 1,082 repeated identical interest postings duplicates?** See
   `docs/INTERVIEW_PREPARATION.md` §4.3. Unconfirmed.
5. **Accepting the chain-based month-end tie-break** (risk 1) changes certified
   numbers. It needs the data owner's sign-off.

---

## 7. Remaining risks, prioritised

| # | Risk | Severity | Next step |
|---|---|---|---|
| 1 | **Month-end balance tie-break is wrong at row level.** Highest `trans_id` disagrees with the balance chain on 154,018 of 185,057 posted month ends. Q9's average moves only 1.79 CZK, but per-account balances do not | High (data) | Order same-day postings by the balance chain, fall back to highest id where the chain is ambiguous, add a test, regenerate Q9 and the deliverables |
| 2 | **No pre-execution semantic verification.** A wrong-but-valid query reaches the user (probe B–G) | High (AI) | Wire the IR and verifier (§2.4 step 1), then compile certified metrics (step 2) |
| 3 | **Weaker local models (Ollama) are untested** against the new pack. Sonnet's results do not transfer | Medium | Run `make questions && make evaluate` with `LLM_PROVIDER=ollama` into a separate output, and compare |
| 4 | **Evaluation is tuned to the ten questions.** Question ids are in the pack, there is no hold-out, and one measure is checked per question | Medium | Hold-out set of 10–20 questions including period comparisons; remove ids from the pack and re-evaluate |
| 5 | **RLS-dependent NULLs**: for a disponent, `ai.loan` shows `'no card'` and a NULL frequency (`docs/INTERVIEW_PREPARATION.md` §8 S2) | Medium | Do not coalesce hidden joins; declare "hidden" explicitly |
| 6 | **`is_problematic` is coded twice** (staging and core) | Low | Core reuses `stg.is_problematic` |
| 7 | **`evaluate.numeric()` ignores `Decimal`.** Harmless today because rows are converted first, but a trap for reuse | Low | Accept `Decimal` |

---

## 8. Follow-up (2026-10-28, after this audit)

This record describes the audited version and is otherwise left as written.
What changed since, and where the evidence is:

| Audit item | Outcome | Evidence |
|---|---|---|
| Risk 1, month-end tie-break | **Fixed (D028).** The closing posting is the end of the day's running-balance chain; where it cannot be ordered (2,303 of 185,057 posted month ends; 42 accounts at 1998-12-31) the lowest `trans_id` is used and the row says `closing_basis = 'ambiguous'`. Q9: 43,808.94 → **43,810.47**. Material reconciliation breaks 55 → 14, rounding band 81 → 70 | `tests/test_month_end.py` (production SQL on synthetic postings; independent derivation, 0 disagreements); `ASSUMPTIONS.md` A14, A20; archive `dq/results/archive/2026-10-28_before_D028/` |
| Risk 2, no pre-execution semantic verification | **Fixed (D029).** The model returns an IR with its SQL; `src/sql_ir.py` verifies IR, columns and SQL-against-IR before any session is opened, then EXPLAIN, guarded execution under RLS and recomputation from the IR. One entry point for the runner and the web app (`run_questions.verify_and_execute`) | `tests/test_sql_ir.py` (66 tests); `DECISIONS.md` D029 |
| The observed failure: `t2.gender` on `ai.account_owner` | Refused at the `columns` stage with the nearest real column named (`owner_gender`); no database session opened. Correct path: `ai.loan.owner_gender` = `core.dim_client.gender` of the account's single `OWNER` disposition (A47) | `tests/test_sql_ir.py::test_a_nonexistent_gender_column_is_refused_before_execution` |
| Risk 3, Ollama untested | **Still open.** No Ollama server was reachable in the environment used; nothing is claimed for it. The runner and evaluator now take `--out`/`--llm`, so an Ollama run writes `llm_results_ollama.json` and cannot overwrite or merge with the Claude run | `src/run_questions.py`, `src/evaluate.py` |
| Risk 4, evaluation tuned to the ten | Partly addressed: four additional questions (gender of loans, Q1–Q3 comparison, Q1 1996 accounts, loans per quarter) with independent reference SQL on the core tables | `data/questions_extra.csv`, `sql/61_reference_extra.sql` |
| §2.5 IR prototype | Superseded by `src/sql_ir.py`; the prototype is kept unchanged as this section's evidence | `scripts/ir_check_prototype.py` docstring |

**Re-evaluation** (Claude Sonnet 5.5 via `claude_cli`, run as `cro_global`, code
at commit `49059c0`): the brief's ten answered and verified on the first
attempt, **10 of 10 match** the reference; the four additional questions
answered and verified on the first attempt, **4 of 4 match**. A first run on the
same day exposed two verifier defects that refused correct answers (Q9's
composite grain written as a string; Q6 months as numbers). Both were fixed and
pinned by tests before the run above; that first run is archived with its
explanation in `dq/results/archive/2026-10-28_first_verified_run/`.

**Still awaiting business confirmation:** A47 (loans by the owner's gender, not
loan-client pairs), A48 (calendar quarters; one row per period), A49 (interest
counts as incoming money), and the D028 fallback for the ambiguous
account-months.

