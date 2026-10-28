# Evidence before D028 (archived 2026-10-28)

Copies of the evidence files as they stood at commit `c855be4`, before the
month-end closing-posting correction (D028) and the IR verifier (D029)
changed the outputs they describe:

| File | What it is |
|---|---|
| `reference_results.json` | Hand-written reference answers, Q9 computed with the highest-trans_id tie-break |
| `llm_results.json`, `evaluation.json`, `llm_logs/` | The LLM run of 2026-10-25 (Claude Sonnet 5.5 via claude CLI, commit a7da25a), scored at 97c2cde |
| `dq_report.md`, `defects.csv` | Data quality report with the reconciliation rules using the old tie-break (55 material breaks) |

Kept unchanged so every number quoted from earlier documents can still be traced.
