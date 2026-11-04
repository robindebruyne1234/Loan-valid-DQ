# <span class="num">10</span>Step 8 — Entitlements: where the filter sits {#step-rls}

<p class="lede">Task 3 asked for an explanation. It was built and tested instead: the filter is
a row level security policy on the base tables, the identity is the authenticated database
role, and access is data, so onboarding needs no code.</p>

<div class="stepcard">
<div><b>Command</b><code>make entitlements</code></div>
<div><b>Code</b><code>sql/40_ai_views.sql</code>, <code>sql/50_sec_rls.sql</code>, <code>sql/51_sec_auth.sql</code>, <code>src/build_security.py</code></div>
<div><b>Evidence</b><code>tests/test_rls.py</code>, workbook tab <i>Entitlements</i>, <code>docs/ACCESS_AND_AUTH.md</code></div>
</div>

<figure><img src="assets/05_where_the_filter_sits.png"><figcaption>Three places a filter can live (VISUAL_GUIDE figure 5). A prompt instruction is a request; a gateway is defeated by one
query shape it did not anticipate; a policy in the engine holds whatever SQL arrives.</figcaption></figure>

## The three answers the brief asked for {#three-answers}

**Where the filter sits.** Seven row level security policies on the seven client-bearing core
tables: `dim_client`, `dim_account`, `bridge_disposition`, `dim_card`, `fact_loan`,
`fact_transaction`, `fact_account_month_end_balance`. Every `ai` view, and every `core` view
between a consumer and a policy, is `security_invoker`, so the policy is evaluated as the
caller, not as the view's owner (D010). Reference data (districts, calendar, code list) is
deliberately unfiltered: it holds no client data and filtering it would break every
group-by (A22, A37).

**Why an LLM-generated query cannot bypass it.** The model produces text. The predicate is
not in that text, so no rewrite of the text removes it; the policy sits inside the plan of
every statement on the connection. The identity the policy reads is `session_user` — the
database role that logged in — which no SQL statement can change without a password the
model never sees (D009). A session variable such as `app.end_user` was rejected exactly
because any statement can set one. No consumer role has `BYPASSRLS` or superuser; the
bank-wide risk user `cro_global` is *a portfolio containing every client*, not an
exemption (`rolbypassrls = false`).

**How a new user or portfolio is onboarded without code.** Insert the principal into
`sec.app_user`, attach a portfolio in `sec.user_portfolio` (or put clients into a portfolio
in `sec.portfolio_client`), create the login role with its credential, enrol the second
factor. Grants are *derived live* from those rows, so the new user's access works
immediately. Offboarding is one `UPDATE` that deactivates the principal. No policy, view or
query changes.

## Four sources of access, one shape {#grant-sources}

<figure><img src="assets/11_access_model.png"><figcaption>The access model (VISUAL_GUIDE figure 11). Note: the figure says the disponent "cannot see her client record,
or anything else of hers"; the client record is right, "anything else" is not — see the weak spot below.</figcaption></figure>

| Source | Derived from | Grants | Decision |
|---|---|---|---|
| **Ownership** | `core.bridge_disposition` with `is_owner` | view + operate on the client and the accounts they own | D021 |
| **Disposition** | dispositions of type DISPONENT | view + operate on **that account only** — never the owner's client record or other accounts | D023, D024, A39, A40 |
| **Portfolio** | `sec.portfolio_client` + `sec.user_portfolio` | view only on the clients of the book (accountability is not payment authority) | D009, A41 |
| **Delegation** | `sec.access_delegation` — the only *stored* grant | what a human decided, with grantor, reason and expiry (holiday cover, power of attorney) | D027 |

All four flow into `sec.v_access_grant`; `sec.v_my_clients` / `sec.v_my_accounts` filter it to
`session_user` and to grants inside their validity window, **AND** `sec.has_verified_session()`
over the whole resolution, so a branch added later cannot skip the second factor. Two kinds of
principal share one policy set: staff, entitled to the union of their books, and self-service
customers, entitled to exactly themselves (a check constraint forbids "both" and "neither").
Adding the customer grain cost one column and one UNION and changed no policy — the test that
the filter really lives in one place.

D027 is a lesson worth telling: the grant set was first *materialised*, and granting a
portfolio inserted a membership row but no grant, so the new access did nothing until the
next rebuild while the tables said it should work. Deriving the grants live removed the
second description that could drift.

## Measured, by logging in as each role {#measured}

| Principal | Clients | Accounts | Loans | Transactions |
|---|---:|---:|---:|---:|
| `cro_global` (portfolio of every client) | 5,369 | 4,500 | 682 | 1,056,319 |
| `rm_north` | 1,481 | 1,241 | 179 | 294,622 |
| `rm_south` (1,386 in its book + 1 delegated client) | 1,387 | 1,158 | 195 | 272,770 |
| `rm_unassigned` (no portfolio) | **0** | 0 | 0 | 0 |
| `client_3764` (a disponent: one account, not its owner) | 1 | 1 | 1 | 439 |

A brand-new user with no portfolio sees **nothing**, not everything — the failure mode of a
badly built filter is the opposite.

## Tested by attacking it {#attacks}

`tests/test_rls.py` connects as restricted users and tries to get out: setting a session
variable to another user's name, `SET ROLE`, reading `core` directly instead of through the
views, reaching `raw`/`stg`, granting itself access, dropping or disabling a policy, writing,
widening the result through a join — nine bypass attempts, all refused. It also checks that
two customers of the *same* relationship manager cannot see each other (13 targeted attempts
including going around the views), the disponent and delegation cases, onboarding and
deactivation as pure data changes, that every protected table has RLS enabled, and that every
view between consumer and policy is `security_invoker`.

The security bug worth telling: before `security_invoker` was set on three curated `core`
views, `ai.loan` returned all 682 loans to a user entitled to none, while `core.fact_loan`
returned 0 in the same session. The design was right and the DDL was one setting short; it was
found only because the test counted rows as the restricted user (D010).

:::weak Privacy claims that go too far (verified 2026-11-04)
- **A disponent sees more of the owner than the documents say.** Logged in as `client_3764`
  (disponent on account 3112, owned by client 3763): `ai.client` correctly returns only 3764,
  but `ai.card` returns the owner's card (card 587, junior, issued 1996-08-05,
  `holder_client_id` 3763) and `core.bridge_disposition` returns the owner's disposition row.
  The card and disposition policies key on the account. (L-05)
- **Hidden data becomes false data.** For the same user, `ai.loan` shows the loan with
  `owner_card_type = 'no card'` and a NULL statement frequency — the truth is *junior* and
  *monthly*. The owner join returns nothing under RLS and the view's `coalesce(…, 'no card')`
  turns "not visible" into a wrong value. Q4 or Q10 asked by a disponent would be wrong, not
  merely restricted. (L-06)
- `sec.v_who_can_reach_client` has a latent bug: a `<> (SELECT … LIMIT 1)` branch returns
  NULL for a client without a login, silently dropping indirect grants; `u.db_role <> ''` is a
  no-op. Harmless with today's seed. (L-11)
- Not built: a read audit ("who *did* see"), field masking, connection pooling (a role per user
  conflicts with naive pooling — answer: a pool per role, or a trusted gateway doing `SET ROLE`).
:::

:::say Where the filter sits, in three sentences
"The filter is a row level security policy on the base tables, evaluated as the caller because
every view in between is security-invoker. The caller is the database role that authenticated,
which no SQL can change, so the model's text has nothing to remove. And access is rows in
`sec`, derived live, so onboarding is an insert and offboarding is an update."
:::

# <span class="num">11</span>Step 9 — Authentication: two factors, in the database {#step-auth}

<p class="lede">A password alone reaches nothing. The second factor is verified by the database
itself, so no application in front of it can skip it.</p>

<figure><img src="assets/12_auth_flow.png" style="max-height:110mm"><figcaption>The two-step login (VISUAL_GUIDE figure 12).</figcaption></figure>

## How it works {#auth-how}

1. **Factor 1** is the database password of the principal's own login role.
2. **Factor 2** is a time-based one-time code (TOTP, RFC 6238), implemented in SQL. The client
   calls `sec.verify_second_factor(code)`. The function takes *only a code*, never a principal:
   it uses `session_user`, so nobody can verify on someone else's behalf.
3. A correct code is **single use** (the last used time step is stored). Five committed
   failures lock the factor for 15 minutes; while locked, even the right code is refused.
4. Success opens a session in `sec.auth_session`, bound to the database role and the backend
   process of that connection, for 30 minutes.
5. `sec.has_verified_session()` is ANDed into the entitlement resolution. Without it every
   policy resolves to the empty set: **password only → 0 rows**.

Identifiers (D025): `client_id` for joins; `client_ref` (`BRK-XXXX-XXXX`, an HMAC under a secret
salt) to quote without enabling enumeration; `account_ref`, an IBAN with real mod-97 check
digits and a fictional bank code, for the number a customer recognises.

:::say Why in the database (D026)
"Most systems enforce the second factor in the application, which is a defensible
architecture — but it makes the control a property of the application rather than of the
data, the same mistake I rejected for entitlements. Here the claim is testable in the only way
that means anything: hold the correct password, present no code, and read nothing."
:::

:::weak Limits to state before you are asked
- **Rollback gap (found in the delivery audit).** The failure counter is written inside the
  caller's transaction. The project's own client commits every attempt, but someone who holds a
  principal's password and connects directly can roll each failed guess back and is never
  locked out. Recorded as a strict expected failure in `tests/test_auth.py`; fix: count attempts
  outside the caller's transaction, or accept logins only through a gateway. RLS itself is not
  affected: no factor, no rows. (L-09)
- **Session bound to the backend PID only.** `backend_start` is stored but never compared, so a
  reused PID for the same role within 30 minutes could inherit a session (A45, L-10).
- **TOTP secrets are stored recoverable** in `sec.auth_factor` (A44) — verification needs the
  secret; production would encrypt them with a key outside the database.
- **TOTP is phishable in real time** (A43); production should prefer WebAuthn/passkeys.
- **The demo shows its own codes** (`/api/code`, console) and personas share a demo password —
  a demo affordance, labelled as such, the first thing a deployment removes (A46).
:::
