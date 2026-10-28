# STATUS REPORT

Generated at 2026-10-28T16:12:37+00:00 (git b5b18f2).

This report exists because of the honesty rules: a step that did not run
is marked `NOT EXECUTED` here and its cells in the deliverables are left
empty, rather than being filled with something plausible.

## Pipeline steps

| step | command | status | last run (UTC) | evidence |
|---|---|---|---|---|
| ingest | `make ingest` | executed | 2026-10-27T14:17:55+00:00 | database only |
| profile | `make profile` | executed | 2026-10-27T14:19:54+00:00 | dq\results\profile.json |
| dq | `make dq` | executed | 2026-10-28T15:56:34+00:00 | deliverables\defects.csv |
| model | `make model` | executed | 2026-10-27T14:20:58+00:00 | deliverables\model_explanation.md |
| reference | `make reference` | executed | 2026-10-27T14:21:10+00:00 | dq\results\reference_results.json |
| semantic | `make semantic` | executed | 2026-10-28T15:44:16+00:00 | semantic\context_pack.md |
| entitlements | `make entitlements` | executed | 2026-10-27T14:21:23+00:00 | database only |
| questions | `make questions` | executed | 2026-10-25T21:00:32+00:00 | dq\results\llm_results.json |
| evaluate | `make evaluate` | executed | 2026-10-25T21:00:47+00:00 | dq\results\evaluation.json |
| workbook | `make workbook` | executed | 2026-10-28T16:11:51+00:00 | deliverables\Berka_TakeHome_Submission.xlsx |
| ddr | `make ddr` | executed | 2026-10-28T16:12:27+00:00 | deliverables\DDR.docx |
| zip | `make zip` | executed | 2026-10-28T15:57:56+00:00 | deliverables\semantic_solution.zip |

## LLM execution

- provider: `claude_cli`
- model: `claude-sonnet-5-5`
- recorded: 2026-10-25T11:21:30+00:00 at commit `a7da25a`
- isolation: no tools, no MCP servers, no filesystem, no database access; the model received the rendered semantic layer (29,500 characters) and the question, and nothing else
- executed as consumer role: `cro_global` (so every query passed through the row level security policies)
- questions answered: **10 of 10**
- answered on the first attempt: **10**
- SQL hand-corrected: **none**. The Questions tab shows what the model produced.
- call logs: `llm_logs/` (20 files, each with the full prompt, parameters, raw response, timing and cost)

The semantic pack has changed since this run (33,662 characters now). The recorded answers are evidence for the pack they were given, not for the current one, until `make questions` is run again.

A separate local run, never merged with the one above: `ollama` / `qwen2.5-coder:3b` at commit `5b13f2b`, match 6, mismatch 2, partial 2 (`dq/results/local/`).

## Evaluation against the hand-written reference answers

- comparison: value based: every (dimension, measure) pair in the reference answer must appear on some row of the LLM answer, within an absolute tolerance of 0.011 (enough to absorb two-decimal rounding, not enough to absorb a wrong number); row order is additionally checked for the three questions that ask for a ranking

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
- **The SQL guard proves a query is safe, not that it answers the question.**
  The intent checker (`scripts/ir_check_prototype.py`) is a prototype that
  neither the runner nor the web app calls.
- **The month-end balance breaks same-day ties by the highest `trans_id`**,
  which is not chronological (A14, caveat C2): per-account balances can be
  off even though the Q9 average barely moves.
- **A local Ollama model is an optional provider.** Its run is kept apart in
  `dq/results/local/` and is not the submission evidence.
- **Two build environments.** PostgreSQL 16 on Linux (docker compose or a
  native cluster) and PostgreSQL 18 on native Windows; the DDL, the policies
  and the tests are identical.
- Claims, evidence and the remaining open items: `docs/DELIVERY_AUDIT.md`.
- **`core.v_*` views and `ai.*` views are rebuilt on every `make model`**,
  which drops and recreates the consumer surface. The target restores it.

