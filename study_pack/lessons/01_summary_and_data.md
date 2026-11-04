# <span class="num">2</span>All findings at a glance {#summary}

<div class="compact-wrap" markdown="1">

| ID | Finding | Area | Severity | Status |
|---|---|---|---|---|
| <span class="nw">L-01</span> | Month-end closing posting chosen by highest `trans_id`, wrong for most busy closing days | Data | High | <span class="tag disc">DISCLOSED</span> <span class="tag post">FIXED AFTER</span> |
| <span class="nw">L-02</span> | The "account off by exactly 1,200 CZK" defect is an artefact of L-01 — and it is in the text the LLM reads | Data / DQ | High | <span class="tag open">NOT DISCLOSED</span> <span class="tag post">FIXED AFTER</span> |
| <span class="nw">L-03</span> | Reconciliation rules and profiling inherited L-01: 41 of 55 material breaks are artefacts; "order independent" claim | DQ | High | <span class="tag open">NOT DISCLOSED</span> <span class="tag post">FIXED AFTER</span> |
| <span class="nw">L-04</span> | The duplicate rule can only catch zero-amount duplicates; 1,081 repeated interest groups unflagged | DQ | Medium | <span class="tag open">NOT DISCLOSED</span> |
| <span class="nw">L-05</span> | A disponent sees the owner's card and disposition row — the documents say "nothing else of hers" | Security | Medium | <span class="tag open">NOT DISCLOSED</span> |
| <span class="nw">L-06</span> | For RLS-restricted users, hidden values become false values (`'no card'`, NULL frequency) | Security / AI | Medium | <span class="tag open">NOT DISCLOSED</span> |
| <span class="nw">L-07</span> | The guard proves shape, not meaning: the gender query passed it and failed in the database | AI | High | <span class="tag disc">DISCLOSED</span> <span class="tag post">FIXED AFTER</span> |
| <span class="nw">L-08</span> | The 10/10 evaluation is narrower than it sounds (old pack, question labels in the pack, no hold-out, one sample) | Evaluation | Medium | <span class="tag disc">PARTLY DISCLOSED</span> |
| <span class="nw">L-09</span> | Second-factor lockout can be avoided by a direct client that rolls back failed guesses | Security | Medium | <span class="tag disc">DISCLOSED</span> |
| <span class="nw">L-10</span> | The verified session is bound to the backend PID only; `backend_start` is stored but never compared | Security | Low | <span class="tag disc">PARTLY (A45)</span> |
| <span class="nw">L-11</span> | `sec.v_who_can_reach_client` has a NULL branch that drops grants, and over-states one reach | Security | Low | <span class="tag open">NOT DISCLOSED</span> |
| <span class="nw">L-12</span> | Reference SQL described as "hand written" / "worked out by a person" | Disclosure | Medium | <span class="tag open">NOT CORRECTED</span> |
| <span class="nw">L-13</span> | `ai.loan` rounds ages per row, so Q7 status B reads 39.61 instead of 39.60 | Data / AI | Low | <span class="tag open">NOT DISCLOSED</span> |
| <span class="nw">L-14</span> | Documentation drift: stale test counts, figures and diagrams in delivered files | Docs | Low–Medium | <span class="tag disc">PARTLY FIXED</span> |
| <span class="nw">L-15</span> | Mislabels in generated reports (wrong assumption id, reconciliation step, "440 rows", counts that are not rows) | Docs | Low | <span class="tag open">NOT DISCLOSED</span> |
| <span class="nw">L-16</span> | The prompt's JSON example reached the model with doubled braces `{{ }}` | AI | Low | <span class="tag post">FIXED AFTER</span> |
| <span class="nw">L-17</span> | Deployment hardening gaps: Docker superuser on an open port, `public` in a SECURITY DEFINER path, owner credentials in the web process | Security | Low–Medium | <span class="tag disc">PARTLY</span> |
| <span class="nw">L-18</span> | Code hygiene: `is_problematic` computed twice; the evaluator ignores `Decimal` | Code | Low | <span class="tag open">NOT DISCLOSED</span> |
| <span class="nw">L-19</span> | Scope well beyond a 1–2 day brief that warns against infrastructure | Process | Medium | <span class="tag open">TALK TRACK</span> |
| <span class="nw">L-20</span> | Two working copies diverged; the delivery was reconciled by a partial merge | Process | Medium | <span class="tag disc">DISCLOSED</span> |

</div>

Bugs found and fixed **before** delivery (chapter 7) and the work done **after** delivery (chapter 8)
are listed separately.

# <span class="num">3</span>Data and data quality {#data}

## L-01 · The month-end closing posting {#l01}

**Area** data · **Severity** High · <span class="tag disc">DISCLOSED</span> <span class="tag post">FIXED AFTER DELIVERY (D028)</span>

**What.** `core.fact_account_month_end_balance` takes, per account and month, the balance after
the latest posting. When several postings share that date, the delivered rule picks the one with
the **highest `trans_id`** (D019, A14). The source has no time of day and `trans_id` is not
chronological.

**Evidence (re-run 2026-11-04).** Each posting starts at `balance_after − signed_amount`, so the
postings of a day form a chain and its end is the true closing posting. Over 185,057 posted
account-months: 154,713 have a unique chain end, 28,041 close on a single posting, 2,303 cannot be
ordered. Where the chain resolves, the highest id picks the closing posting **694 times (0.4%)**;
the lowest id 96.9%. Interest postings carry high ids but are booked before the month's
statement fee, so the old rule usually reads the balance *before* the fee. Example: account 31,
November 1998, recorded as 13,312.90; after the 14.60 fee the true closing balance is 13,298.30.

| Q9 at 1998-12-31 under … | Average balance |
|---|---:|
| the delivered rule (highest id) | **43,808.94** |
| the balance chain, lowest id where ambiguous (D028, after delivery) | 43,810.47 |
| the balance chain, highest id where ambiguous | 43,810.73 |
| lowest id only | 43,808.90 |

107 accounts close differently at 1998-12-31 under D028 (65 where the chain resolves, 42 where it
cannot); the largest difference is 1,200.00 CZK. The maximum balance moves from 138,317.20 to
137,829.50.

**Root cause.** The design accepted "the source does not record intra-day order" as a fact and
documented a tie-break, instead of testing whether the data held indirect evidence of order. Two
delivered documents state the stronger, wrong claim that "no derived table can resolve what the
source did not record" (`docs/GOLD_LAYER.md`, the deck).

**Status.** Disclosed at delivery as a known limitation (A14, caveat C2, DDR §3, delivery audit
item 3: "Q9's average moves about 2 CZK"). Deliberately not changed in the freeze because it
changes a certified number. Fixed after delivery with the chain rule, a `closing_basis` column
marking `single posting` / `balance chain` / `ambiguous`, and `tests/test_month_end.py` (the
production SQL run on synthetic postings, plus an independent re-derivation over 180,000+
balances with 0 disagreements).

**Lesson.** "Unknowable" is a hypothesis. Before writing a tie-break down, look for indirect
evidence in the data and measure how often the tie-break matters.

:::say
"My month-end rule broke same-day ties by the highest transaction id. I disclosed that as a
limitation. Later I found the running balance encodes the order, and the highest id was right
only 0.4% of the time. Q9's average moved 1.53 CZK; 107 individual balances moved, by up to
1,200 CZK. I fixed it after submitting, with the chain rule and a test."
:::

## L-02 · The 1,200 CZK "missing posting" was our own artefact {#l02}

**Area** data quality · **Severity** High · <span class="tag open">NOT DISCLOSED</span> <span class="tag post">FIXED AFTER DELIVERY</span>

**What.** The delivered documents present a showcase finding: *"55 accounts are off by more than
100 CZK and one by exactly 1,200.00 CZK with only 55 postings, which is a missing or extra
posting rather than rounding."* That account is **3888**, and the gap is created by L-01.

**Evidence.** Account 3888, last day 1998-01-31: an interest credit of +1.30 (id 3,467,643,
balance 10,500.00 → 10,501.30) and a cash withdrawal of −1,200.00 (id 1,137,901, 10,501.30 →
9,301.30). The chain shows the withdrawal came last; the highest id is the interest posting. The
delivered "last reported balance" is therefore 10,501.30, against a net flow of 9,301.30 — a
1,200.00 "gap". Under the chain rule the closing balance is 9,301.30 and the account reconciles
exactly.

**Where the claim appears in the delivered version.** Caveat **C1** in
`semantic/semantic_layer.yaml` — and therefore in the context pack the model reads
("one by 1,200 CZK"); the severity rationale of `CON_BALANCE_RECONCILIATION_MATERIAL` in
`dq/dq_rules.yaml` and `dq/results/dq_report.md`; `docs/HOW_WE_WORKED_SIMPLY.md`; the deck and
its speaker notes ("That is not rounding, that is a posting"); `scripts/make_defect_catalogue.py`.

**Root cause.** A defect count computed from a derived value inherits the bugs of that
derivation. The story was compelling, so it was repeated rather than re-checked.

**Lesson.** When a number makes a good story, check it twice — and check whether it is a property
of the source or of your own logic.

:::say
"The best-sounding defect in my report — an account off by exactly 1,200 — was my own tie-break.
On its last day a 1.30 interest credit has a higher id than a 1,200 withdrawal that came after
it. Under the chain rule it reconciles to the cent. I like this one because it shows why a
derived check can't be trusted more than the derivation it reads."
:::

## L-03 · The reconciliation rules and the profiler inherited the tie-break {#l03}

**Area** data quality · **Severity** High · <span class="tag open">NOT DISCLOSED</span> <span class="tag post">FIXED AFTER DELIVERY</span>

**What.** `CON_BALANCE_RECONCILIATION_MATERIAL` / `_ROUNDING` and the profiler's candidates compare
the sum of an account's postings with its "last reported balance", taking the last posting by
highest id. `dq/results/candidates.md` calls this an "order independent test". It is order
dependent exactly where L-01 bites.

**Evidence.** With the chain rule: material breaks **55 → 14** (the largest now 488.30); rounding
band **81 → 70**; accounts reconciling exactly 631 → 637, within 1 CZK 4,364 → 4,416. In the
delivered version, 440 warn flags (183 + 114 + 81 + 55 + 6 + 1) fall to 388.

**Impact.** The data quality report over-states the material defects almost fourfold, and caveat C1
tells the model (and any reader) that 55 accounts cannot be reproduced from their flows. The Q9
reference reports "55 unreconciled" next to the average.

**Lesson.** A rule that reads a derived value must be tested against an independent derivation,
or it reports the derivation's bugs as source defects.

## L-04 · The only blocking rule can only catch zero-amount duplicates {#l04}

**Area** data quality · **Severity** Medium · <span class="tag open">NOT DISCLOSED</span>

**What.** `UNQ_TRANS_BUSINESS_KEY` treats two postings as duplicates when account, date, type,
operation, amount **and resulting balance** are equal. A genuine duplicated payment moves the
balance, so the second copy has a different `balance_after` and is never caught. By construction
the rule catches only duplicates that did not move the balance: zero-amount postings. The one row
it quarantines is a 0.00 CZK posting (account 9051, 1998-02-28).

**Evidence.** 1,082 groups in staging (1,081 in core, after the quarantine) of identical repeated
interest postings — same account, same date, same amount, category `UROK` — worth 157,289.70 CZK
beyond the first posting of each group. No rule flags them. Whether they are duplicates or
legitimate split interest runs is a business question; it is unverified.

**Impact.** The delivered narrative uses this rule as the example of a `block` that "double counts
a flow and no primary key catches it"; in practice it protected 0.00 CZK.

**Fix.** A `warn` rule on repeated identical batches (same account, date, amount, category),
routed to the data owner; keep the exact-duplicate `block`.

:::say
"My block rule needs the same resulting balance, which means it can only ever catch a duplicate
that didn't move money — the one it caught is 0.00. Repeated identical interest postings, a
thousand-odd groups worth 157,000 CZK, aren't flagged at all. I'd add a warn rule and ask the bank
whether those are duplicates."
:::

## L-13 · Q7 rounds before it averages {#l13}

**Area** data / AI surface · **Severity** Low · <span class="tag open">NOT DISCLOSED</span>

`ai.loan` exposes `round(owner_age_at_loan_start, 2)` (`sql/40_ai_views.sql:168`). A model that
averages that column averages rounded values: status B reads **39.61** against the exact
**39.60** (A 37.07, C 38.70, D 37.00 are unaffected). The evaluator's 0.011 tolerance absorbs it,
so the verdict is still `match`. Fix: expose the unrounded value and round in presentation.

## L-18 · Code hygiene {#l18}

**Area** code · **Severity** Low · <span class="tag open">NOT DISCLOSED</span>

- `is_problematic` is computed in staging (`sql/10_stg.sql:330`) and again in core
  (`sql/30_core.sql:344`) with the same predicate. One meaning, two implementations: core should
  reuse the staged column.
- `evaluate.numeric()` does not treat `Decimal` as a number. Harmless today because rows are
  converted to floats before evaluation; a trap for anyone who reuses it.
