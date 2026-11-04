# Semantic correctness and balance integrity (D028-D029)

## D028 - The closing posting of a day is the end of its running-balance chain

**Context.** D019 broke ties between postings on the same date with the highest
`trans_id`, on the belief that the source records no intra-day order. It
records no time and no sequence, but it does record the running balance: each
posting starts at `balance_after - signed_amount` and ends at `balance_after`.
Measured over all 185,057 posted account-months, the postings of the closing
day form a chain with a single end in 154,713 cases, close on a single posting
in 28,041, and do not resolve in 2,303. Where the chain resolves, the highest
`trans_id` picks the true closing balance 694 times (0.4%), the lowest 96.9%,
and file order about half the time. Interest postings carry high ids and are
posted before the statement fee, so the old rule read the balance before the
fee: account 31 closed November 1998 at 13,312.90 instead of 13,298.30.

**Options.** (a) Keep the highest-id tie-break. (b) Use file order. (c) Take
the end of the balance chain, and use a documented fallback only where the
chain does not resolve, marking those rows. (d) Report NULL where ambiguous.

**Choice.** (c), with the lowest `trans_id` among the chain ends as the
fallback and `closing_basis` ('single posting' / 'balance chain' /
'ambiguous') on every month-end row.

**Reason.** It implements A14 ("the balance after the last posting") with the
only evidence of order the source holds, instead of a proxy that is wrong 99.6%
of the time. (d) would silently shrink Q9's population; (a) and (b) fabricate
an order. The fallback is a measured heuristic, not a claim of chronology, so
the 1.2% of account-months it decides stay visibly marked.

**Cost.** Q9 moves from 43,808.94 to 43,810.47. The same correction applies to
the two reconciliation rules, which read the "last reported balance" the same
way: material breaks fall from 55 to 14 and the rounding band from 81 to 70,
because 52 of the old flags were a mid-day balance read as the final one. The
data owner should confirm the fallback for the 2,303 ambiguous account-months.

**Consequence.** `tests/test_month_end.py` runs the production SQL block
against synthetic postings (same-day chains, gaps, first and last months,
ambiguity) and checks the real table against an independent derivation.

## D029 - Generated SQL must match a declared intent before it runs

**Context.** The guard decides whether a statement may run, never whether it
answers the question. A query for "male or female loans in Q1 1995" passed the
guard and failed in the database on `t2.gender`, a column `ai.account_owner`
does not have (it has `owner_gender`); worse queries, a wrong quarter or a
fan-out join, would have run and returned plausible numbers.

**Options.** (a) More prompt text. (b) EXPLAIN the query before running it.
(c) Make the model state its intent as a small intermediate representation
(IR) and verify the SQL against the IR, the semantic layer and the database
before execution. (d) Compile SQL from the IR and drop model SQL entirely.

**Choice.** (c), with (b) as part of it: the IR is checked against the
certified metrics, every column the SQL references is resolved against the
semantic layer, the period filter is evaluated day by day against the IR's
half-open ranges, joins must be declared and must not fan out the counted
entity, required grouping and filters must be present, and PostgreSQL plans
the query (EXPLAIN) before it executes. After execution, a certified metric is
recomputed from the IR alone and must agree before the answer is shown.
Anything missing, malformed or unverifiable fails with the reason.

**Reason.** (a) is advice, not a control. (d) is the long-term target for
certified metrics but removes the model from questions it handles well today.
(c) catches every failure class seen so far while keeping the model's SQL.

**Cost.** Questions outside the certified metrics are refused rather than
answered unverified, and some correct but unusual SQL is rejected and retried.
One metric per answer: a second measure in the same SELECT runs but is not
verified. A verified answer proves the SQL computes the declared intent with the
certified definitions; whether the intent is what the user meant is shown, not
proven, which is why the IR is reported beside the answer.

**Consequence.** `src/sql_ir.py` is the only verifier. The question runner and
the web app reach it through one function, `run_questions.verify_and_execute`:
guard, IR, columns, consistency, then (only then) the two-factor login, EXPLAIN,
guarded execution and recomputation on the caller's own RLS-bound connection.
A refusal records the stage and the reason, keeps the SQL, returns no rows, and
is fed back for the single retry. Only a fully verified answer is recorded as
`answered` and evaluated. `tests/test_sql_ir.py` covers the observed failure,
quarters, date columns, fan-out, grouping, malformed IRs and both application
paths with a scripted model; the brief's ten recorded answers still verify.

