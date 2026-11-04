# <span class="num">4</span>Security and privacy {#security}

## L-05 · A disponent sees more of the owner than promised {#l05}

**Area** privacy · **Severity** Medium · <span class="tag open">NOT DISCLOSED</span>

**What.** D024 says a disposition grants *the account, never the person*.
`docs/ACCESS_AND_AUTH.md` and figure 11 say the disponent "cannot see her client record, or
anything else of hers". The client record is correctly hidden; "anything else" is not true.

**Evidence (logged in as `client_3764`, 2026-11-04).** Client 3764 is a disponent on account 3112,
owned by client 3763.

| View | What 3764 sees |
|---|---|
| `ai.client` | only client 3764 — correct |
| `ai.card` | the owner's card: card 587, *junior*, issued 1996-08-05, `holder_client_id` 3763 |
| `core.bridge_disposition` | both dispositions on the account: 3763 as owner, 3764 as disponent |

**Root cause.** The `entitled_cards` and `entitled_dispositions` policies key on the *account*,
which the disponent is entitled to, rather than on the card holder or the disposition's own
client. The test checks only `ai.client`.

**Fix.** Cards visible when the holder is in the caller's clients (or the caller is staff);
dispositions visible for the caller's own rows (or staff). Add tests for both, from the
disponent's side.

:::say
"I claimed a disposition grants the account and nothing about the owner. That holds for the
owner's client record, but the card and disposition policies key on the account, so a disponent
sees the owner's card type, issue date and client id. Small, but it's a privacy claim I made too
broadly; the fix is a holder-based policy and two tests."
:::

## L-06 · Hidden values become false values {#l06}

**Area** correctness under RLS · **Severity** Medium · <span class="tag open">NOT DISCLOSED</span>

**What.** For the same disponent, `ai.loan` returns loan 5610 with `owner_card_type = 'no card'`,
`statement_frequency` NULL and `owner_gender` NULL. The truth is *junior* and *monthly*. The owner
join returns nothing under RLS (the owner's client row is invisible), and the view's
`coalesce(owner_card_type, 'no card')` (`sql/40_ai_views.sql:169`) turns "not visible to you" into
a confident wrong value.

**Impact.** Q4 or Q10 asked by a disponent is *wrong*, not merely *restricted*. The semantic layer
does not tell the model that a NULL can mean "hidden". This is the most interesting finding for an
AI audience: entitlement filtering changed the meaning of a column.

**Fix.** Never coalesce over a join that RLS can empty; expose an explicit "not visible" value or
leave NULL, and describe that in the semantic layer; test the pre-joined views as each persona.

:::say
"Row level security can change the meaning of a column, not just the number of rows. A disponent
asking my Q4 gets 'no card' for a loan whose owner has a junior card, because the owner is hidden
and the view coalesces the missing value. Hidden is not the same as absent, and the view should
never say otherwise."
:::

## L-09 · The second-factor lockout can be rolled back {#l09}

**Area** authentication · **Severity** Medium · <span class="tag disc">DISCLOSED</span>

The failure counter is written inside the caller's transaction. The project's own client commits
every attempt, so five failures lock the factor for 15 minutes (tested since `b5b18f2`). But anyone
holding a principal's password can connect directly, roll each failed guess back, and is never
locked out. Found by the delivery audit when the lockout test was finally written; recorded as a
strict expected failure so the test turns red on the day it is fixed; disclosed in
ACCESS_AND_AUTH, the demo script, the visual guide, the README and the DDR. Row level security is
unaffected: without the second factor a principal still reads no rows. Fix: count attempts outside
the caller's transaction (an autonomous write via a separate connection or `dblink`), or accept
consumer logins only through a gateway.

**Lesson.** A documented control without a test is a hope. The lockout was documented for weeks
before a test existed; writing the test found the gap.

## L-10 · The session is bound to the backend PID only {#l10}

**Area** authentication · **Severity** Low · <span class="tag disc">PARTLY DISCLOSED (A45)</span>

`sec.has_verified_session()` matches `db_role` and `pg_backend_pid()`; `backend_start` is stored
when the session is opened but never compared (`sql/51_sec_auth.sql:205`, `:303–313`). If a PID is
reused by the same role within the 30-minute window, the new connection inherits the session. A45
names the PID-reuse risk; the unused column is the cheap fix.

## L-11 · `sec.v_who_can_reach_client` {#l11}

**Area** access reporting · **Severity** Low (latent) · <span class="tag open">NOT DISCLOSED</span>

The view that answers "who can reach this client, and why" has a branch with
`g.db_role <> (SELECT … LIMIT 1)`: for a client without a login the subquery is NULL, the
comparison is NULL, and indirect grants silently drop out. `u.db_role <> ''` is a no-op
(`sql/51_sec_auth.sql:570–572`). It is latent with today's seed (every relevant client has a login)
and it also over-states one reach (it lists `client_3763` as able to view and operate client
3764's record). Fix: `IS DISTINCT FROM` or `NOT EXISTS`, and a test with a client that has no login.

## L-17 · Deployment hardening {#l17}

**Area** operations · **Severity** Low–Medium · <span class="tag disc">PARTLY DISCLOSED</span>

| Gap | Where | Note |
|---|---|---|
| The Docker path makes `berka_owner` the image's superuser and publishes 5432 on all interfaces | `docker-compose.yml:15–18` | `docs/DEPLOYMENT.md` says not to open 5432; bind to 127.0.0.1 |
| A SECURITY DEFINER function's `search_path` puts `public` before `pg_catalog` | `sql/51_sec_auth.sql:230` | Low risk where consumers cannot create in `public`; schema-qualify the pgcrypto calls |
| The web process holds owner credentials for the fixed tour pages | `src/webapp.py` | A code-execution bug there is owner compromise; pre-render those pages instead |
| TOTP secrets stored recoverable | `sec.auth_factor` | A44; encrypt with a key outside the database |
| Demo prints codes; personas share a demo password | `/api/code`, console | A46; demo affordances, labelled |

# <span class="num">5</span>The AI path and the evaluation {#ai}

## L-07 · A guard pass is not a correct answer {#l07}

**Area** AI · **Severity** High · <span class="tag disc">DISCLOSED</span> <span class="tag post">FIXED AFTER DELIVERY (D029)</span>

**What.** The guard parses the model's SQL and enforces its shape; it does not resolve columns or
judge meaning. In the delivered version the intent checker is a prototype
(`scripts/ir_check_prototype.py`) not imported by the application. Disclosed as delivery audit
item 2 and in the DDR.

**Evidence — the observed failure.** *"Find male or female loans in Q1 1995."* The model joined
`ai.loan` to `ai.account_owner` and used `T2.gender`. The guard allowed it; PostgreSQL raised
`column t2.gender does not exist`. Gender lives on `ai.client`; `ai.loan` and `ai.account_owner`
expose `owner_gender`. The semantic layer's `gender_share` metric had said "any entity with a
gender column"; the delivery corrected that text and made the validator refuse a metric naming a
missing column, but did not verify meaning. The failure was safe — no rows, an error recorded — but
the same class of mistake with a column that *does* exist (a wrong date, the wrong quarter, a
fan-out join) would have returned a plausible wrong number. The local model's Q6 (a fan-out to
every calendar day: 279 "new accounts" in January instead of 106) is exactly that.

**Fix (after delivery).** D029: the model returns an intent (IR) with its SQL; `src/sql_ir.py`
verifies IR and SQL together before any session is opened, then plans, executes and recomputes the
certified metric from the IR; rows only when both agree. Active in the runner and the web app.

:::say
"The guard is a shape filter, not a correctness check. The gender question proved it: one safe
SELECT, allowed, then rejected by the database for a column that doesn't exist. That one failed
safely — the dangerous version is the query that is valid and wrong. That's why I added intent
verification after submitting."
:::

## L-08 · Why 10/10 is weaker evidence than it sounds {#l08}

**Area** evaluation · **Severity** Medium · <span class="tag disc">PARTLY DISCLOSED</span>

| Weakness | Status in the delivery |
|---|---|
| The recorded Claude run (2026-10-25, `a7da25a`) used the 29,500-character pack from **before** the semantic audit; the delivered pack is 33,662 characters and was not re-run with Claude | Disclosed (P1 item 1) |
| The pack names the questions: "Relevant to: Q1", "Answers Q2, Q3, Q4, Q7 and Q10 with no further joins" (19 lines carry a question id) — it shows the model where to look, without numbers | Not disclosed |
| "Q1" in the pack means a reference question; in a user's question it means a quarter (the audit added QR11 to disambiguate) | Addressed by the audit |
| No hold-out set: no unseen question was evaluated | Not disclosed |
| One sample per question; one key measure per question; order checked for three questions | Not disclosed as a limitation |
| The same build session wrote the semantic layer and the reference SQL | See L-12 |

**After delivery.** Claude was re-run on the new pack (10/10, with the verifier active) and four new
questions — gender of loans and calendar quarters — were added as a separate suite (4/4).

**Lesson.** An evaluation tuned to its own test set measures the author, not the system. Keep a
hold-out set and keep question ids out of the context.

## L-12 · "Hand written" {#l12}

**Area** disclosure · **Severity** Medium · <span class="tag open">NOT CORRECTED</span>

`AI_DISCLOSURE.md` labels `sql/60_reference_queries.sql` "Hand written. Ground truth."; the
plain-words document says "a person worked out all ten answers the slow, careful way"; the deck
says "the answers a person had worked out by hand beforehand". The same disclosure says the
pipeline, rules, semantic layer and tests were written with Claude in an interactive session — and
so was the reference SQL. What is true and sufficient: the reference SQL was **not generated by the
model under test**, never entered its context, and every reference answer was independently
**re-derived from the raw text tables** and matched.

:::say
"To be precise about authorship: I built everything with an AI coding assistant under my direction,
including the reference SQL. 'Hand written' in my disclosure means not written by the model under
test — and I re-derived every reference answer from the raw text with separate SQL, so the model and
the reference cannot be wrong in the same way."
:::

## L-16 · The prompt's JSON example had doubled braces {#l16}

**Area** AI · **Severity** Low · <span class="tag post">FIXED AFTER DELIVERY</span>

`semantic/prompt_template.md` writes its example JSON with `{{` and `}}` (as if for Python's
`format`), but the runner fills the template with `str.replace`, so the model received `{{ "sql":
… }}` literally — an invalid JSON example. Strong models ignored it; it is still a defect in the
one artefact the model reads besides the pack.
