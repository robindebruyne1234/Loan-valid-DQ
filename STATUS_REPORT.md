# STATUS REPORT

Generated at 2026-10-22T10:49:22+00:00 (git 95de493).

This report exists because of the honesty rules: a step that did not run
is marked `NOT EXECUTED` here and its cells in the deliverables are left
empty, rather than being filled with something plausible.

## Pipeline steps

| step | command | status | last run (UTC) | evidence |
|---|---|---|---|---|
| ingest | `make ingest` | executed | 2026-10-22T09:40:30+00:00 | database only |
| profile | `make profile` | executed | 2026-10-22T09:49:54+00:00 | dq/results/profile.json |
| dq | `make dq` | executed | 2026-10-22T10:31:52+00:00 | deliverables/defects.csv |
| model | `make model` | executed | 2026-10-22T10:32:03+00:00 | deliverables/model_explanation.md |
| reference | `make reference` | executed | 2026-10-22T10:32:20+00:00 | dq/results/reference_results.json |
| semantic | `make semantic` | executed | 2026-10-22T10:24:15+00:00 | semantic/context_pack.md |
| entitlements | `make entitlements` | executed | 2026-10-22T10:36:21+00:00 | database only |
| questions | `make questions` | executed | 2026-10-22T10:38:40+00:00 | dq/results/llm_results.json |
| evaluate | `make evaluate` | executed | 2026-10-22T10:40:15+00:00 | dq/results/evaluation.json |
| workbook | `make workbook` | executed | 2026-10-22T10:44:08+00:00 | deliverables/Berka_TakeHome_Submission.xlsx |
| ddr | `make ddr` | executed | 2026-10-22T10:47:20+00:00 | deliverables/DDR.docx |
| zip | `make zip` | executed | 2026-10-22T10:45:18+00:00 | deliverables/semantic_solution.zip |

## LLM execution

- provider: `claude_cli`
- model: `claude-sonnet-5-5`
- isolation: no tools, no MCP servers, no filesystem, no database access; the model received the rendered semantic layer (27,592 characters) and the question, and nothing else
- executed as consumer role: `cro_global` (so every query passed through the row level security policies)
- questions answered: **10 of 10**
- answered on the first attempt: **10**
- SQL hand-corrected: **none**. The Questions tab shows what the model produced.
- call logs: `llm_logs/` (20 files, each with the full prompt, parameters, raw response, timing and cost)

## Evaluation against the hand-written reference answers

- comparison: value based: every (dimension, measure) pair in the reference answer must appear on some row of the LLM answer, within a relative tolerance of 1e-4; row order is additionally checked for the three questions that ask for a ranking

| verdict | questions |
|---|---:|
| match | 10 |
| partial | 0 |
| mismatch | 0 |
| not_executed | 0 |

## Steps that were planned and did not run

None. Every planned step executed.

## Known limitations, stated rather than hidden

- **No bank-supplied copy of the data was received**, so `data/raw/provided/`
  is empty and the public copy is the primary dataset. Its row counts match
  the published reference exactly, which means it carries none of the
  injected defects the assessment may compare against. The rules are proven
  against a deliberately corrupted copy instead (20 seeded defects, schema
  `inject`), and running them on the bank's copy needs no change: drop the
  files in `data/raw/provided/` and re-run `make all`.
- **Ollama was the documented default LLM** and is not reachable from the
  build environment (not installed, and the model download hosts are not on
  the egress allow-list). The provider abstraction keeps it, untested.
- **Docker was not available** (CLI present, no daemon), so PostgreSQL 16
  runs from a native cluster. The DDL, the policies and the tests are
  identical; `docker-compose.yml` is shipped and `make up` prefers it.
- **`core.v_*` views and `ai.*` views are rebuilt on every `make model`**,
  which drops and recreates the consumer surface. The target restores it.

