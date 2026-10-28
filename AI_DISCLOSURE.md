# AI disclosure

The brief requires full disclosure of AI tooling. This is it.

## What was used

| Tool | Model | What it did |
|---|---|---|
| Claude Code (CLI), interactive | Claude Opus 5 (`claude-opus-5`) | Wrote this repository: the pipeline, the SQL, the rule set, the semantic layer, the tests and the documents, under direction, with every step executed and verified against the database rather than asserted. |
| Claude Code, later interactive sessions | Claude Opus 5.5 and Claude Sonnet 5.5 | The Windows/Ollama work, the semantic model audit (`docs/SEMANTIC_MODEL_AUDIT.md`) and the delivery review (`docs/DELIVERY_AUDIT.md`), under the same rule: executed and checked, never typed from memory. The `Co-Authored-By` line of each commit names the model. |
| Claude CLI, non-interactive (`claude -p`) | Claude Sonnet 5.5 (`claude-sonnet-5-5`) | **The LLM under test, and the submission evidence.** Generated the SQL for the 10 questions from the semantic layer (run of 2026-10-25, `dq/results/llm_results.json`). |
| Ollama, local | qwen2.5-coder:3b | **A second LLM under test, optional and free.** Answers the same questions on a laptop CPU through the same guard and login (`dq/results/local/`). Kept separate from the submission evidence; never merged into it. |

A secondary model (`claude-haiku-5-5`) appears in the usage accounting of the
non-interactive calls. That is the CLI's own internal housekeeping, not part of
answering the question; the answer comes from the model named in `--model`, and
each call's `modelUsage` block in `llm_logs/` shows both.

## How the LLM under test was isolated

Every call in `llm_logs/` was made with:

- `--strict-mcp-config --mcp-config '{"mcpServers":{}}'` -- no MCP servers;
- `--disallowedTools` covering Bash, Read, Write, Edit, Glob, Grep, WebFetch,
  WebSearch, Task, TodoWrite, NotebookEdit and the rest -- no tools at all;
- an explicit `--system-prompt`, so no project or user instructions apply;
- a working directory outside the repository, so no `CLAUDE.md`, settings or
  source file could be picked up.

The model therefore had no database connection, no filesystem and no search. It
received the rendered semantic layer (`semantic/context_pack.md`: 29,500
characters for the recorded run; the semantic audit has since grown it to about
33,500, and the recorded run was not repeated on that version) and one
question, and returned one JSON object. The recorded
transcripts show `num_turns: 1` and `permission_denials: []` on every call,
which is what a pure text completion looks like.

This matters for the result: an agent that could read the tables would answer
the questions by looking, and the exercise would measure the agent rather than
the semantic layer.

## What the LLM under test was never shown

- the reference answers, or any answer;
- the reference SQL (`sql/60_reference_queries.sql`);
- the database, in any form;
- the evaluation code or its criteria.

`tests/test_semantic.py::test_context_pack_contains_no_answers` asserts that no
reference figure leaks into the context pack.

## What is model-generated in the deliverables, and what is not

| Artefact | Author |
|---|---|
| `sql/60_reference_queries.sql` and the REFERENCE columns in the workbook | Hand written. Ground truth. |
| The LLM-GENERATED SQL column and LLM answer column in the workbook | Claude Sonnet 5.5, unedited. Where the model's SQL was imperfect it would stay imperfect; it is reproduced exactly. |
| `llm_logs/*.json` | The raw record of each call, written by the runner. |
| Everything else (pipeline, rules, model, semantic layer, tests, documents) | Written with Claude Opus 5 in an interactive session, reviewed and executed. |

No answer, number or SQL statement anywhere in this submission was invented. A
step that did not execute is marked `NOT EXECUTED` in `STATUS_REPORT.md` and
its cells are left empty.

## Reproducing the LLM run

```
make semantic     # render the context pack from the semantic layer
make questions    # ask the 10 questions; writes llm_logs/ and llm_results.json
make evaluate     # compare against the hand-written reference answers
```

The provider is swappable with one environment variable:
`LLM_PROVIDER=anthropic_api LLM_MODEL=... LLM_API_KEY=... make questions`, or
`LLM_PROVIDER=none` to export the prompt pack without calling anything. A
different model's run belongs in its own files, so it can never replace the
recorded one: on Windows `scripts\windows.ps1 questions-local` and
`evaluate-local` (Ollama), elsewhere
`python -m src.run_questions --provider ollama --output dq/results/local/llm_results.json --log-subdir local`
then `python -m src.evaluate --llm-results dq/results/local/llm_results.json --output dq/results/local/evaluation.json`.
A model that answers is not evidence that it answers correctly; only the
evaluation against the reference is.

## Cost and timing of the measured run

10 questions, one call each, no retries: about 2 minutes wall clock and roughly
USD 0.40 in total, recorded per call in `llm_logs/*.json` under
`usage.total_cost_usd`.
