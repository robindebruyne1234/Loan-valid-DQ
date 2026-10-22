# Walkthrough notes

Preparation for the 45-minute technical walkthrough. Not a deliverable --
working notes on what to show, what to expect to be challenged on, and what the
honest answer is.

## The 10-minute version

1. `make up && make all` -- one command, 4m28s measured from an empty
   database, from eight `.asc` files to every deliverable.
2. **Task 1**: 123 rules across all six dimensions, every one with a severity
   *and* the reason for that severity written in terms of the ten questions.
   Show `deliverables/defects.csv`, then show `tests/test_dq.py` proving the
   rules fire against 20 seeded defects.
3. **Task 2**: show `semantic/semantic_layer.yaml`, then
   `semantic/context_pack.md` (what the model actually saw), then the Questions
   tab: 10 of 10 answered on the first attempt, 10 of 10 matching the
   hand-written reference answers.
4. **Task 3**: open two terminals, `psql` as `rm_north` and as `rm_unassigned`,
   run the same query, show 1,481 clients and 0. Then try to bypass it.

## The three findings I would lead with

**The balance chain does not reconcile, and the reason is interesting.**
Testing order-independently -- the sum of all signed amounts on an account
should equal its last reported balance -- 3,869 of 4,500 accounts disagree. Most
are rounding: every amount in the source carries exactly one decimal place, and
the residuals cluster at 0.1 to 0.5 CZK. But 55 accounts are off by more than
100 CZK and one by exactly 1,200.00 CZK with only 55 postings, which is a
missing or extra transaction, not rounding. That is why the rule has two tiers
and a tolerance in `config.py`, and why Q9 reports the affected population next
to the average instead of a clean-looking number.

**Intra-day order is undefined, and Q9 depends on it.** `trans_id` is not
chronological within a date. For 183 accounts the ambiguity falls on their last
active day, so "the closing balance" is a documented choice (highest
`trans_id`), not a fact. The number is right; what matters is that the
submission says which choice it made and how many accounts it affects.

**One duplicate transaction no primary key could catch.** Same account, same
date, same type, same amount, same resulting balance, different `trans_id`. A
genuinely distinct second posting would have moved the balance. It is the one
`block` rule that fires on this data, so `core.fact_transaction` has 1,056,319
rows against 1,056,320 in the file -- and the difference is explained by a named
rule in `dq.quarantine`.

## Questions I expect, and the answers

**"Why is `amount = 0` only `info` when you have a rule saying amounts must be positive?"**
Because the consequence of `block` would be worse than the defect. The 14 zero
postings are interest runs that accrued nothing; quarantining them would remove
14 valid events and break 14 accounts' balance chains to fix nothing. Negative
amounts *are* blocked, in a separate rule, because there the sign has been
applied twice and the posting would flip a debit into a credit. The split is
the point: severity is about consequence, not about tidiness.

**"Your public copy has no injected defects. How do you know the rules work?"**
I did not rely on knowing. `sql/70_inject_defects.sql` builds a corrupted copy
of staging in its own schema with 20 deterministic seeded defects, one per rule
family, and `tests/test_dq.py` asserts each is caught by the rule meant to catch
it. On the bank's copy, `make dq` runs unchanged against
`data/raw/provided/`.

**"Why not DuckDB? It would have been faster to set up."**
Task 3 is enforcement. DuckDB has no row level security, so the entitlement
answer would have been prose plus untested SQL -- the weakest possible answer to
the one task that is purely about control. The cost of PostgreSQL was a 50-line
shell script.

**"Why `session_user` rather than a session variable?"**
Because a session variable can be set by anything that can send SQL, so an
entitlement built on one is only as strong as the guard in front of it -- and
the guard is a Python function. There is a test that sets `app.end_user` to
another user's name and shows the visible row count does not move. The cost is
real: role-per-user conflicts with naive pooling, and the answer is a pool per
role or `SET ROLE` by a trusted gateway.

**"Isn't the LLM just doing well because you made it easy?"**
Partly, and deliberately: the semantic layer exists to make it easy. The honest
test is whether it is easy in the right way. The traps are real -- a card can
belong to a disponent rather than the account owner, "region" means two
different things in Q1 and Q5, "problematic" could reasonably mean only
realised losses, and Q6 needs a calendar join or a month disappears. The layer
names each trap without giving an answer, and the context pack is asserted to
contain no reference figures.

**"What would you do differently?"**
Three things. Put the entitlement resolution in a materialised table from the
start rather than a view, because that is the part that will not scale. Build
the month-end balance fact incrementally from the beginning, for the same
reason. And write `tests/test_rls.py` before the views rather than after -- it
is what found the `security_invoker` leak, and it would have found it an hour
earlier.

## Two bugs worth owning, because they make the better argument

**The rule self-test nearly deleted real data.** `dq.v_blocked` was not scoped
by schema, so running the rule tests made the *injected* defects exclude *real*
rows from the product: 76 districts instead of 77, 11,024 transactions
orphaned. The foreign key and grain checks in `build_model` failed before any
deliverable was written. It is the argument for verifying a model rather than
trusting a build: the pipeline ran green and was quietly wrong.

**The entitlement filter leaked through a view.** The `ai` views were
`security_invoker`; the three curated `core` views they read were not. A view
normally reads its base tables with its owner's rights, and the owner is exempt
from its own policies -- so `ai.loan` returned all 682 loans to a user entitled
to none, while `core.fact_loan` correctly returned 0 for the same user in the
same session. The design was right and the DDL was one setting short. It is the
argument for testing security by connecting as a restricted user and counting
rows, rather than by reading the policies.

## Numbers to have ready

| | |
|---|---|
| Source rows | 4,500 accounts / 5,369 clients / 5,369 dispositions / 892 cards / 682 loans / 6,471 orders / 1,056,320 transactions / 77 districts |
| Rules | 123 executed (88 hand written + 35 generated), 19 fire, 14 defect types |
| Quarantined / flagged | 1 row / 440 rows |
| Q3 | 76 of 682 problematic = 11.14% (matches the published figure) |
| Q9 | 4,500 accounts, average 43,808.94 CZK, 76 carried forward, 55 unreconciled |
| LLM | 10 of 10 answered first attempt, 10 of 10 match, ~2 minutes, ~USD 0.40 |
| Entitlements | 1,481 / 1,386 / 5,369 / 0 clients visible to the four demo users |
| Tests | 114 passing, including 9 bypass attempts and 20 seeded defects |
| Pipeline | 4m28s end to end, from an empty database |
