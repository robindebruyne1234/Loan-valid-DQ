# PLAN

> **Historical record** -- the original build plan, kept for traceability. Its figures, file paths and open items are as of when it was written and are **not** maintained. The current state, with evidence, is [`docs/DELIVERY_AUDIT.md`](../DELIVERY_AUDIT.md); current decisions are [`DECISIONS.md`](../../DECISIONS.md).

Take-home: **The Governed Data Product for AI** (Berka / PKDD'99 Czech bank data).
Goal: raw banking tables -> trusted, documented, entitlement-aware data product
that an LLM can query correctly, plus the four deliverables the brief asks for.

Guiding constraint from the brief: *"If you spend most of your time on
infrastructure or tooling setup, you have misread the brief."* So: one database,
plain Python + numbered SQL files + a Makefile. No orchestrator, no warehouse,
no dbt, no vector store.

## Phases

| # | Phase | Entry point | Key outputs |
|---|-------|-------------|-------------|
| 0 | Scaffold | - | `src/config.py`, `Makefile`, `PLAN.md`, `DECISIONS.md`, `ASSUMPTIONS.md` |
| 1 | Acquire + ingest | `make ingest` | schema `raw` (all columns text), `raw.load_audit` (row counts + SHA-256) |
| 2 | Stage + profile | `make profile` | schema `stg` (typed, lineage, decoded birth numbers), `dq/results/profile.{md,json}`, `candidates.md` |
| 3 | Data quality | `make dq` | `dq/dq_rules.yaml`, `dq.results`, `dq.quarantine`, `deliverables/defects.csv`, `dq/results/dq_report.md`, defect injector |
| 4 | Core model | `make model` | schema `core` star schema + curated views, `core.ref_codes`, `deliverables/model_explanation.md` |
| 5 | Reference answers | `make reference` | `sql/60_reference_queries.sql`, `dq/results/reference_results.json` (ground truth) |
| 6 | Semantic layer | `make semantic` | `semantic/semantic_layer.yaml`, context pack renderer, `src/sql_guard.py` |
| 7 | LLM answers | `make questions` | `llm_logs/*.json` (prompt, model, params, raw response), `dq/results/llm_results.json` |
| 8 | Entitlements | `make entitlements` | schema `sec`, RLS policies, `ai` views with `security_invoker`, consumer roles |
| 9 | Deliverables | `make deliverables` | `Berka_TakeHome_Submission.xlsx`, `DDR.docx`/`DDR.pdf`, `semantic_solution.zip` |

## Files this plan creates

```
README.md PLAN.md DECISIONS.md ASSUMPTIONS.md AI_DISCLOSURE.md WALKTHROUGH_NOTES.md STATUS_REPORT.md
Makefile docker-compose.yml pyproject.toml scripts/db_up.sh
brief/                      original brief + dataset description
data/raw/*.asc(.gz)         the 8 source files (trans.asc gzipped, 69 MB -> 17 MB)
data/raw/provided/          empty: no bank-supplied copy was received (HD1)
data/questions.csv          the 10 business questions
sql/00_schemas.sql 10_stg.sql 20_dq_quarantine.sql 30_core.sql 40_ai_views.sql
    50_sec_rls.sql 60_reference_queries.sql 70_inject_defects.sql
semantic/semantic_layer.yaml semantic/prompt_template.md
src/config.py db.py ingest.py profile_data.py dq_runner.py build_model.py
    build_security.py semantic_context.py sql_guard.py llm_client.py
    run_questions.py run_reference.py evaluate.py inject_defects.py
    make_workbook.py make_ddr.py make_zip.py make_status.py
dq/dq_rules.yaml dq/results/
tests/test_dq.py test_guard.py test_rls.py test_reference_queries.py test_semantic.py
deliverables/
```

## Risks and how they are handled

| Risk | Handling |
|------|----------|
| No Docker daemon in the build container | `scripts/db_up.sh` falls back to a native PostgreSQL 16 cluster; same DDL, RLS still executes for real (D002) |
| Public copy carries no injected defects, so rules could look untested | Reproducible, clearly-labelled defect injector in schema `inject` + seeded-defect tests prove every rule family fires (D004) |
| LLM not reachable / fabrication risk | Provider abstraction; the sandboxed Claude CLI is the executed default; every call logs prompt, model, parameters and raw response; unexecuted steps are marked `NOT EXECUTED`, never invented (D005) |
| LLM-generated SQL could be wrong *or* hostile | `src/sql_guard.py` (sqlglot): one read-only statement, `ai` schema only, row cap, statement timeout; and the entitlement filter sits in the database, not in the prompt (D008) |
| Q9 / month-end balance is ambiguous | Explicit `core.fact_account_month_end_balance` with carry-forward and an `is_carried_forward` flag; interpretation recorded as an assumption |
| Deliverable numbers drifting from the code | Every number is written by a pipeline step; `dq/results/run_log.jsonl` records the command and timestamp behind each one |
| 2-page limit on the Design Decision Record | `src/make_ddr.py` converts with LibreOffice and asserts the PDF page count |
