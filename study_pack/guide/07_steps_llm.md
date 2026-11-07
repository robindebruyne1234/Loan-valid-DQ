# <span class="num">12</span>Step 10 — The LLM as a dumb and dangerous client {#step-llm}

<p class="lede">Design the AI path as if the assistant were a junior analyst with production
credentials and no judgement: it will guess at anything the data does not spell out, and
whatever it writes will run against customer data.</p>

## The threat model {#threat-model}

| "Dumb" — it will be wrong without knowing | "Dangerous" — it writes code that runs |
|---|---|
| Invents a column that sounds right (`gender` on a table that has `owner_gender`) | Emits DDL or DML (`DROP`, `UPDATE`) |
| Uses the wrong date (account open date for a loan question) | Smuggles a second statement past a filter (`SELECT/**/1; DELETE …`) |
| Joins to the many side and inflates a sum (loans × postings) | Reads internal schemas whose columns mean something else (`stg`, `raw`) |
| Counts instead of computing a share; ranks the wrong measure | Calls functions that read settings or files (`current_setting`, out-of-schema functions) |
| Confuses "Q1" the quarter with "Q1" the reference question | Returns millions of rows or runs for hours |
| Silently re-derives a definition (problematic, age, sign) | Tries to widen its own entitlement or impersonate another user |

## The defence, layer by layer {#defence}

<div class="defence">
<div class="h">Layer</div><div class="h">What it enforces</div><div class="h">What it does not do</div>
<div class="layer">Isolation</div><div>Claude CLI with no MCP servers, every tool disallowed, explicit system prompt, working directory outside the repository; one turn, one JSON object. The model never sees the database, the reference SQL or the evaluation</div><div>Make the model right</div>
<div class="layer">Semantic layer</div><div>Removes the reasons to guess: certified metrics, "is not" glossary, grains, join cardinality, caveats with counts, 12 query rules, a refusal path (QR10)</div><div>Check that the model followed it</div>
<div class="layer">SQL guard</div><div>sqlglot parse: one statement; SELECT only; every table schema-qualified in <code>ai</code>; a CTE named like a table cannot stand in for it; none of the blocklisted functions (<code>pg_read_file</code>, <code>pg_sleep</code>, <code>set_config</code>, <code>dblink</code> …); a blocklist, so <code>current_setting('data_directory')</code> passes and PostgreSQL refuses it (LOW-1); LIMIT added or tightened to the 10,000-row cap</div><div><b>Resolve columns or judge meaning</b></div>
<div class="layer">Execution envelope</div><div><code>BEGIN READ ONLY</code>; <code>SET LOCAL statement_timeout</code> 60 s; at most cap + 1 rows fetched; runs on the persona's own two-factor connection; SELECT-only grants</div><div>—</div>
<div class="layer">Row level security</div><div>Decides which rows exist for this user, whatever the SQL says</div><div>—</div>
<div class="layer">PostgreSQL itself</div><div>A name the schema does not have is an error, returned and recorded — never answered</div><div>Catch a wrong-but-valid query</div>
<div class="layer">Evaluation</div><div>Value-based comparison with independent reference SQL, after the fact</div><div>Protect a live user</div>
</div>

:::danger The sentence to never say
"The query passed the guard, so it is correct." The guard proves a query is *safe to run*; it
says nothing about whether it *answers the question*. In the delivered version the only
checks on meaning are the database rejecting unknown names and the offline evaluation. The
intent checker (`scripts/ir_check_prototype.py`) is a prototype and is not imported by the
application.
:::

## The observed failure that proves the point {#gender}

Asked through the application: *"Find male or female loans in Q1 1995."* The model wrote:

```sql
SELECT COUNT(*) AS total_loans,
       SUM(CASE WHEN T2.gender = 'male' THEN 1 ELSE 0 END) AS male_loans,
       SUM(CASE WHEN T2.gender = 'female' THEN 1 ELSE 0 END) AS female_loans
FROM ai.loan AS T1 INNER JOIN ai.account_owner AS T2 ON T1.account_id = T2.account_id
WHERE T1.loan_date >= '1995-01-01' AND T1.loan_date < '1995-04-01'
```

The guard allowed it — it is one safe SELECT on `ai`. PostgreSQL then raised `column t2.gender
does not exist`. Gender lives on `ai.client`; `ai.loan` and `ai.account_owner` expose it as
`owner_gender`. The root cause was in the semantic layer: the `gender_share` metric said
"any entity with a gender column". The delivery fixed the metric text and made the validator
refuse a metric that names a missing column; it did not add meaning verification. The
failure was **safe** — no rows, an error recorded — but it was a failure.

:::post After delivery (D029)
The model now returns an intent (IR) next to its SQL — metric, entity, counting grain,
half-open periods, grouping, filters — and `src/sql_ir.py` checks both before any database
session is opened: every column resolved against the semantic layer, the period filter
evaluated day by day, joins declared and not fanning out, grouping and filters as declared.
Then EXPLAIN, guarded execution under RLS, and the certified metric recomputed from the IR;
rows are shown only when both agree. The observed SQL is refused naming `owner_gender`, and
the corrected answer is 28 loans: 18 male-owned, 10 female-owned (A47, pending business
confirmation).
:::

## The local model shows what "dumb" looks like {#ollama}

The optional local model (Ollama `qwen2.5-coder:3b`, CPU, 2026-10-27, older pack) scored 6
match, 2 partial, 2 mismatch. Every miss was safe SQL that the guard correctly let through:

| Q | What the small model did | Why it is wrong |
|---|---|---|
| Q10 | `count(*) FILTER (WHERE is_problematic)` per frequency, `ORDER BY … LIMIT 1` → *monthly* | A count, not a share — exactly the trap the glossary warns about. The share answer is *after transaction*, 18.75% |
| Q6 | Joined `ai.account.open_date = ai.calendar.month_start` and grouped by month | Matches only accounts opened on the 1st, then fans out across the month's days: 279 "new accounts" in January instead of 106 |
| Q7 | Grouped by age *and* status, counted rows | Never averaged the age |
| Q3 | Returned 11.14% without the supporting counts | Right number; partial only because the evaluator also expects 76 and 682 (QR8) |

:::say What the two runs together show
"A strong model with a good semantic layer got all ten right; a small local model made exactly
the mistakes the semantic layer warns about — share versus count, a fan-out join. Every one of
those wrong queries was perfectly safe, which is the point: governance has to make wrong answers
detectable, not only dangerous queries impossible."
:::

# <span class="num">13</span>Step 11 — Asking the questions and evaluating {#step-eval}

<div class="stepcard">
<div><b>Commands</b><code>make questions</code>, <code>make evaluate</code>; local: <code>questions-local</code>, <code>evaluate-local</code></div>
<div><b>Code</b><code>src/run_questions.py</code>, <code>src/llm_client.py</code>, <code>src/evaluate.py</code></div>
<div><b>Output</b><code>llm_logs/</code>, <code>dq/results/llm_results.json</code>, <code>evaluation.json</code>; local run under <code>dq/results/local/</code></div>
</div>

## The runner {#runner}

For each question: build the prompt from the template and the rendered pack; call the model;
parse its JSON (tolerant of a markdown fence, not of a missing `sql`); guard the SQL; log in as
`cro_global` with both factors; execute under the envelope; record everything. **One retry** is
allowed when the JSON did not parse or the guard or database refused, with the reason fed back
— what a real text-to-SQL service does. Honesty rules enforced in code: no SQL is ever
hand-corrected; a failed call is `NOT EXECUTED` with an empty SQL cell; the result is whatever
the database returned, including an error. Every call — prompt, model, parameters, raw response,
timing, cost — is written to `llm_logs/`.

Why `cro_global`? It holds a portfolio of every client, so its answers are comparable with the
reference, while still passing through the policies like any user. The same SQL as `rm_north`
returns that manager's slice.

## The evaluation {#evaluation}

**Value-based, not text-based** (D011). Two correct queries name their columns differently and
may return extra columns; comparing SQL or column names would measure style. For each question
the evaluator extracts the reference's (dimension → measure) pairs and searches the model's rows
for each one: a matching dimension cell and, on the same row, a number equal within an
**absolute tolerance of 0.011** (enough for two-decimal rounding, not for a wrong number). Row
order is checked for the three ranking questions (Q5, Q6, Q10). Verdicts: match, partial,
mismatch, not executed.

Two evaluator lessons, both disclosed: a relative tolerance of 1e-4 (the first version) would
have accepted the Q5 top district wrong by 11,513 CZK; and Q6 once scored `mismatch` although the
counts were identical, because the model wrote `1996-01` where the evaluator looked for `1`. The
fix was to accept any published representation of a dimension — and that change was made after
seeing an answer, which is why it is written down in D011.

## The results {#results}

| Run | Provider / model | Date, commit, pack | Result |
|---|---|---|---|
| **Recorded (submission evidence)** | `claude_cli` / Claude Sonnet 5.5 | 2026-10-25, `a7da25a`, 29,500-character pack | 10 answered on the first attempt; **10 of 10 match**; about 2 minutes and USD 0.40 |
| Local (separate files) | `ollama` / qwen2.5-coder:3b | 2026-10-27, `5b13f2b`, 29,500-character pack | 6 match, 2 partial (Q3, Q7), 2 mismatch (Q6, Q10) |
| Live check at delivery | Ollama on the delivered pack | 2026-10-28 | Answered in contract and ran as the persona — evidence that the pack fits, not of accuracy |

:::weak Why 10/10 is weaker evidence than it sounds (L-08)
- The recorded run used the pack **before** the semantic audit; the delivered pack (33,662
  characters) was not re-run with Claude at delivery — no Claude CLI on the laptop. Disclosed.
- The pack names the questions ("Relevant to: Q1", "Answers Q2, Q3, Q4, Q7 and Q10 with no
  further joins"): it tells the model where to look, without numbers. There is no hold-out set.
- One sample per question, one key measure per question, order checked for three.
- The same build session wrote the semantic layer and the reference SQL.

The honest summary: *the semantic layer is good enough for a strong model to answer these ten
questions correctly; it does not yet show that it generalises.* The fix is a hold-out set of
paraphrased and new questions, question ids removed from the pack, repeated runs and full
result-set comparison. (After delivery: four new questions — gender of loans and calendar
quarters — were added as a separate suite and answered 4/4 with the verifier active.)
:::

# <span class="num">14</span>Step 12 — Demo, deliverables and the evidence chain {#step-deliver}

## How it is shown {#demo}

- **Console demo** (`make demo-login`): a seven-act walkthrough — password only → 0 rows;
  password + code → the user's slice; switching between users; a customer and their manager
  asking the same question and getting different, correct answers.
- **Web walkthrough** (`make web-open`, `http://localhost:8080`): seven steps — bronze,
  silver clean, silver grade, gold, access, login, ask. `/api/ask` accepts a completed two-step
  login only, never a role name. With Ollama it runs fully offline on the laptop.
- **Worked example** (`make demo`, `docs/WORKED_EXAMPLE.md`): one client followed from the line
  of text she arrives as, through cleaning, into the product and through the entitlement model.

## The deliverables and where their numbers come from {#deliverables}

| Deliverable | Content | Built by |
|---|---|---|
| `Berka_TakeHome_Submission.xlsx` (11 tabs) | Overview, Defect types, Model, Questions, Q detail, DQ rules, Cleaning, Assumptions, Decisions, Entitlements, Run log | `make workbook` from the result files and the database |
| `DDR.pdf` / `DDR.docx` (2 pages) | Seven decisions with options, choice, why, cost; what breaks at 100,000× | `make ddr`; **fails** if over two pages |
| `semantic_solution.zip` (183 members) | The semantic layer, code, SQL, tests, results, logs; `MANIFEST.md` says what to read first | `make zip` |
| `defects.csv`, `model_explanation.md` | The register and the model narrative | `make dq`, `make model` |
| `docs/DELIVERY_AUDIT.md` | Every claim → its authoritative source → the deliverables that repeat it; commands run; open items | Written at delivery |

Every command appends to `dq/results/run_log.jsonl` with its git commit; `STATUS_REPORT.md` is
generated from it, and a step that never ran shows `NOT EXECUTED`.

:::say If they ask "how do I know these numbers are real?"
"Every figure in the workbook was produced by a command whose run is logged with its commit.
The delivery audit maps each claim to the one place that is authoritative for it. And a step
that did not run is printed as NOT EXECUTED, never filled in."
:::
