# <span class="num">2</span>The architecture in one picture {#architecture}

<p class="lede">Six schemas in one PostgreSQL database are the spine. Each has one job and a
contract with the next, and the security schema sits beside the model rather than on top of
it.</p>

<div class="layers">
<div class="l-raw"><b>raw</b>Bronze. The 8 files verbatim, every column text, file and line number on every row, SHA-256 per file in <code>raw.load_audit</code>.</div>
<div class="l-stg"><b>stg</b>Silver. Typed, decoded, sign resolved, gender and birth date derived. Same row count as raw. Nothing filtered, originals kept.</div>
<div class="l-dq"><b>dq</b>Control plane. 124 rules, results per run, quarantine (block), flags (warn), reconciliation, run log.</div>
<div class="l-core"><b>core</b>Gold. Star schema = stg minus quarantine, flags carried onto rows, one definition per term. Verified after every build.</div>
<div class="l-ai"><b>ai</b>The only consumer surface: 11 business-named views, all <code>security_invoker</code>, pre-joined for the common questions.</div>
<div class="l-sec"><b>sec</b>Who may see what: principals, portfolios, delegations, derived grants, TOTP factor and sessions. Read by the 7 RLS policies on core.</div>
</div>

There is a seventh schema, `inject`, used only by the test suite: a corrupted copy of staging
with 20 seeded defects that proves the rules fire. It can never reach `core` (D004, D008).

## What runs, in order {#order}

| # | Command (`make …` or `scripts\windows.ps1 …`) | Builds | Code |
|---:|---|---|---|
| 1 | `ingest` | `raw.*`, `raw.load_audit` | `src/ingest.py`, `sql/00_schemas.sql` |
| 2 | `profile` | `stg.*`, `dq/results/profile.md`, `candidates.md` | `sql/10_stg.sql`, `src/profile_data.py` |
| 3 | `dq` | `dq.results`, `dq.quarantine`, `dq.flags`, `dq.reconciliation`, `dq_report.md`, `defects.csv` | `src/dq_runner.py`, `dq/dq_rules.yaml` |
| 4 | `model` | `core.*`, model checks, `model_explanation.md`; then restores the `ai` views and policies (D012) | `sql/30_core.sql`, `src/build_model.py` |
| 5 | `ledger` | `docs/CLEANING_LEDGER.md`, measured from the database | `src/cleaning_ledger.py` |
| 6 | `reference` | `dq/results/reference_results.json` | `sql/60_reference_queries.sql`, `src/run_reference.py` |
| 7 | `semantic` | validation against the live schema; `semantic/context_pack.md` | `semantic/semantic_layer.yaml`, `src/semantic_context.py` |
| 8 | `entitlements` | `ai.*` views, roles, grants, 7 policies, demo principals, TOTP enrolment | `sql/40_ai_views.sql`, `sql/50_sec_rls.sql`, `sql/51_sec_auth.sql`, `src/build_security.py` |
| 9 | `questions` | `llm_logs/*.json`, `dq/results/llm_results.json` | `src/run_questions.py`, `src/llm_client.py`, `src/sql_guard.py` |
| 10 | `evaluate` | `dq/results/evaluation.json` | `src/evaluate.py` |
| 11 | `deliverables` | workbook, DDR (fails if over 2 pages), ZIP | `src/make_workbook.py`, `src/make_ddr.py`, `src/make_zip.py` |
| 12 | `status` | `STATUS_REPORT.md` from the run log | `src/make_status.py` |

`make build` runs steps 1–8 plus the tests, without an LLM; `make all` runs everything.

## One question, end to end {#one-question}

Take Q3, *"What percentage of our loans are problematic?"*, asked by a relationship manager.

1. **The question** is put into `semantic/prompt_template.md` together with the rendered
   semantic layer (`semantic/context_pack.md`). That text is the model's whole world: it
   has no tools, no files and no database.
2. **The model** returns one JSON object: `sql`, `reasoning`, `assumptions`, `caveats`. It
   reads in the pack that "problematic" is status B or D, already materialised as
   `is_problematic` on `ai.loan`, and that the denominator is all loans (A4).
3. **The guard** (`src/sql_guard.py`) parses the SQL with sqlglot: exactly one read-only
   SELECT, every table schema-qualified in `ai`, no forbidden or out-of-schema function, no
   CTE named like a table to smuggle one in, and a LIMIT forced to the 10,000-row cap.
4. **The login.** The SQL runs on a connection that authenticated as the user: database
   password, then a TOTP code verified *in the database* (`sec.verify_second_factor`). Until
   that succeeds, every entitlement resolves to nothing.
5. **Execution** happens inside `BEGIN READ ONLY` with a 60-second `statement_timeout`; at
   most cap + 1 rows are fetched.
6. **Row level security** on `core.fact_loan` (reached through the `security_invoker` view
   `ai.loan`) keeps only the loans of accounts this user is entitled to. The model never sees
   that predicate; it is not in the query, so it cannot be removed from the query.
7. **The answer** is the manager's own portfolio: `rm_north` sees 179 of the 682 loans. The
   same SQL run as `cro_global` (a portfolio holding every client) returns 76 of 682 =
   11.14%, which is what the evaluation compares with the reference.
8. **Evidence.** The prompt, model, parameters and raw response go to `llm_logs/`, the
   result to `llm_results.json`, and `evaluate` compares values, not SQL text.

:::say Where each kind of protection lives
"Three things stand between the question and the data and they do different jobs. The
semantic layer removes the reasons to guess. The guard removes the ways to do harm with the
*shape* of a query. The policy decides which rows exist for this user. Only the third is a
security boundary; it would hold even if the first two failed."
:::

## Three contracts that hold the layers together {#contracts}

| Contract | Checked by | What a failure would mean |
|---|---|---|
| **raw = stg** on row counts and money (11 checks) | DQ step, `dq.reconciliation` | Staging lost or invented rows or koruna |
| **core = stg − quarantine** on 7 row counts and 2 money sums | `build_model.reconcile_core` after every build | Cleaning leaked a row or an amount without a quarantine entry to explain it |
| **The semantic layer matches the live schema** — every column exists and is described, grains hold, join cardinality as declared, metrics name real columns, row counts current | `src/semantic_context.py` on every `make semantic` | The model would be given confident wrong information it cannot check |
