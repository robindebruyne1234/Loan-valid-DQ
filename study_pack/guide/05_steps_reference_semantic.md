# <span class="num">8</span>Step 6 — Reference answers, the marking scheme {#step-reference}

<p class="lede">Before any model is asked anything, write the ten answers as SQL against the
core model, state the interpretation each one implements, and keep them away from the
model.</p>

<div class="stepcard">
<div><b>Command</b><code>make reference</code></div>
<div><b>Code</b><code>sql/60_reference_queries.sql</code>, <code>src/run_reference.py</code></div>
<div><b>Output</b><code>dq/results/reference_results.json</code></div>
</div>

- One query per question, each preceded by its **interpretation** (A1–A16): which district
  for "region", what "problematic" means, which date "granted" uses, how the owner is found,
  how age is computed, what the balance at a date is.
- Where a question can reasonably be read another way, the alternative and its size are
  written next to the query and in `ASSUMPTIONS.md` — so a reviewer who prefers the other
  reading can see exactly what changes.
- The reference SQL, the reference figures and the evaluation criteria are **never in the
  model's context**; `tests/test_semantic.py::test_context_pack_contains_no_answers` asserts
  that no reference figure leaks into the pack.
- At delivery, all ten reference queries were re-executed against the live database and were
  identical to the stored results. Separately, every reference answer was **re-derived from
  the raw text tables with independent SQL** (no `stg`, no `core`) and matched exactly.

:::weak Who wrote the reference SQL
It was written in the AI-assisted build session, not by the model under test, and not
literally by hand. That is enough to keep the evaluation meaningful — the model never saw it
— but the words "hand written" and "a person worked it out" in some documents overstate it.
The independent re-derivation from raw is the stronger argument; use it (L-12).
:::

:::say Why write the answers first
"An evaluation is only as good as its marking scheme. I wrote the reference answers with
their interpretations before the model was asked anything, kept them out of its context, and
then rebuilt each one from the raw text with separate SQL to make sure the model and the
reference were not wrong in the same way."
:::

# <span class="num">9</span>Step 7 — The semantic layer {#step-semantic}

<p class="lede">One YAML file holds every business meaning the model is allowed to use, and
the build refuses it if it disagrees with the live database.</p>

<div class="stepcard">
<div><b>Command</b><code>make semantic</code></div>
<div><b>Code</b><code>semantic/semantic_layer.yaml</code>, <code>src/semantic_context.py</code>, <code>semantic/prompt_template.md</code></div>
<div><b>Output</b><code>semantic/context_pack.md</code> (33,662 characters at delivery)</div>
</div>

## What is in the file {#semantic-contents}

| Section | Content at delivery |
|---|---|
| `meta` | Dialect (PostgreSQL), query schema `ai`, currency CZK, date range 1993-01-01..1998-12-31 |
| `query_rules` | 12 rules, QR1–QR12 (below) |
| `glossary` | 10 terms, each with what it **is** and what it is **not**: account owner, disponent, problematic loan, incoming transaction, new account, region, statement frequency, month-end balance, quarter, age at loan start |
| `metrics` | 12 certified metrics with their entity, expression, time column: `client_count`, `account_count`, `loan_count`, `total_loan_amount`, `average_loan_amount`, `problematic_loan_share`, `incoming_transaction_amount`, `outgoing_transaction_amount`, `net_flow`, `average_month_end_balance`, `average_age_at_loan_start`, `gender_share` |
| `entities` | 11 `ai` views with grain, primary key, every column described, allowed values, 19 joins with cardinality and optionality |
| `caveats` | 7 caveats C1–C7, each tied to a rule, with a severity and a row count |
| `entitlements` | Tells the model that a filter exists inside the database, that it must not add or remove one, and what a restricted answer means |
| `question_patterns` | Worked patterns for common question shapes |

## The query rules the model is given {#query-rules}

| Rule | Instruction |
|---|---|
| QR1 | Read only from `ai`; never reference `core`, `stg`, `raw`, `dq`, `sec` or `inject` |
| QR2 | Exactly one statement, a single SELECT (a leading WITH is fine) |
| QR3 | No DDL or DML — no INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, GRANT, SET, COPY, CALL |
| QR4 | Do not try to widen what you can see; do not mention entitlements in the SQL |
| QR5 | Use the certified metric definitions verbatim; never re-derive `is_problematic`, `direction` or an age |
| QR6 | For "per month / quarter / year", join `ai.calendar` so empty periods show as zero |
| QR7 | Prefer the pre-joined entity (`ai.loan`, `ai.account_owner` carry owner, card type, frequency) |
| QR8 | Return supporting counts next to a percentage or an average; surface the relevant caveat |
| QR9 | Round percentages to two decimals; do not round monetary sums |
| QR10 | If the question cannot be answered from the entities, say what is missing instead of guessing a column |
| QR11 | Filter time on the metric's own date column with half-open ranges; Q1–Q4 in a user's question are calendar quarters |
| QR12 | Count and sum at the grain of the entity asked about; never aggregate after joining to the "many" side |

QR11 and QR12 came from the semantic model audit (2026-10-28), together with the `quarter`
glossary entry, a `time_column` on every metric and measured cardinality on every join.

## Validated against the live database {#semantic-validation}

`src/semantic_context.py` checks the YAML against `information_schema` and the data on every
build. Any of these **fails the build**:

- a described column that does not exist, or an existing column that is not described;
- a declared grain that is not one row per key;
- a join whose measured cardinality or optionality differs from the declared one;
- a stale row count;
- a metric whose entity is not described, or whose expression, filter or grouping names a
  column that does not exist (added at delivery — `gender_share` had said "any entity with a
  gender column").

At delivery: 0 problems; 11 entities, 105 columns, 19 joins, 12 metrics, 7 caveats.

:::say Why a validated file instead of prompt text
"A semantic layer that has drifted from the schema is worse than none: it gives the model
confident, wrong information that the model has no way to check. So the layer is a build
artefact. If someone renames a column or a grain stops holding, the build fails before any
answer is produced."
:::

## What makes the layer AI-ready, specifically {#ai-ready}

- **Business names and decoded labels** on every `ai` column; codes kept beside labels.
- **Pre-joined views**: `ai.loan` carries the owner, the owner's card type, exact age at loan
  start and the account's statement frequency, so Q2, Q3, Q4, Q7 and Q10 need no joins.
- **"Is not" definitions** in the glossary: *a disponent is not the owner*; *incoming is not
  a net flow*; *a quarter is not a reference question*.
- **Caveats with counts** that the model is told to surface (QR8), so the warn flags of step
  4 reach the person reading the answer.
- **A refusal path** (QR10): the model is told to say what is missing rather than invent a
  column.

:::weak Questions to expect
- *Doesn't pre-joining for the questions over-fit?* Partly. The pack even says which entity
  "answers Q2, Q3, Q4, Q7 and Q10". It shows the model where to look without giving numbers;
  a hold-out set of unseen questions is the honest remedy (L-08).
- *What stops the model from using a column that is not there?* Before delivery: only the
  database, which raises an error the runner records — a safe failure, but a failure. The
  observed case was `T2.gender` on `ai.account_owner` (the column is `owner_gender`). After
  delivery, the intent verifier rejects it before execution (D029, L-07).
- *Is the 1,200 CZK in caveat C1 right?* No — it is an artefact of the month-end tie-break,
  and it is in the text the model reads (L-02).
:::
