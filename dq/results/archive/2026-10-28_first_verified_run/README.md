# First run through the IR verifier (2026-10-28) -- superseded

Claude (`claude_cli`, `claude-sonnet-5-5`), run as `cro_global`, with the
verifier of D029 active, before two defects in the verifier were fixed.
Kept because it is the honest record of what the verifier refused and why.

| Question | Outcome | Cause |
|----------|---------|-------|
| Q1-Q5, Q7, Q8, Q10, E1-E4 | answered on the first attempt | -- |
| Q6 | refused at `recompute` on attempt 1, answered on attempt 2 | **Verifier defect.** The model grouped by month number (1-12); the certified recomputation accepted `1996-01`, the first day of the month or the month name, but not the number. The answer was correct. |
| Q9 | refused at `ir` on both attempts, so not answered | **Verifier defect.** The model wrote the composite counting grain as the string `"account_id, month_end_date"`; the check compared it with the list `[account_id, month_end_date]` without normalising. The SQL was correct. |

Both are fixed in `src/sql_ir.py` (`_grain` normalises a composite grain; the
month recomputation also accepts the month number) and pinned by
`tests/test_sql_ir.py::test_a_composite_grain_may_be_written_as_a_list_or_a_string`
and `::test_months_reported_as_numbers_verify`. Both suites were then re-run in
full on the fixed code; those results are the ones in `dq/results/`.

Files: `llm_results.json`, `llm_results_extra.json` and the per-attempt call
logs exactly as written by that run.
