# Access and authentication: who may reach whose data, and how they prove it

Two questions that are easy to confuse and must not be answered together:

| | |
|---|---|
| **Authentication** | *Are you who you say you are?* Two factors, both checked by the database. |
| **Authorisation** | *Given that you are you, what may you reach, and why?* One grant set, four sources. |

They meet in exactly one place — `sec.v_my_clients` — and nowhere else.

Figures: **`docs/diagrams/11_access_model.svg`** (the grant model) and
**`docs/diagrams/12_auth_flow.svg`** (the two-step login and what each step
stops). Run it yourself with `make demo-login`.

---

## 1. Three kinds of name for the same person

Before any of this: *what do we call a client?* The original model had one
answer, `client_id`, a dense sequential integer. Row level security already
stopped one customer reading another's rows, so exposing it was not a breach
— but it was still the wrong thing to publish:

- it is **guessable**, so a customer-facing surface that takes an id in a URL
  invites enumeration, and every probe becomes an access attempt to refuse
  rather than one never made;
- it **leaks the shape of the book**: ids run 1 to 13,998, so the population
  size is readable off the identifier space;
- it is a **stable handle** for correlating the same person across any other
  system that ever receives one.

So there are now three names, with different exposure:

| Name | Example | Who sees it | What it is for |
|---|---|---|---|
| `client_id` | `3763` | internal | joins, foreign keys, policy predicates |
| `client_ref` | `BRK-TQ8D-RCB3` | the customer, a URL, a letter | the thing to quote |
| `account_ref` | `CZ84 8888 0000 0000 0000 3112` | the customer | the number a person recognises |

`client_ref` is HMAC-SHA256 over the id under a secret salt, rendered in
Crockford base32 (no `I`, `L`, `O` or `U`, so nothing reads as a digit or as a
word nobody wants on a statement). It is deterministic, so rebuilds are
stable, and unguessable without the salt — which is set only on the pipeline
owner's session, never on a consumer's, so a consumer cannot derive anyone
else's reference from an id.

`account_ref` is an IBAN with **genuine ISO 13616 mod-97 check digits** and a
deliberately fictional bank code (`8888`: this is public research data and
must not carry a real bank's routing code). The check digits are real so that
a typo in a demo fails the way a typo in production would.
`tests/test_rls.py` validates all of them against an independent mod-97
implementation and confirms a corrupted one is rejected.

The semantic layer tells the model which to use: *join on `client_id`, refer
to people by `client_ref`*.

---

## 2. Who may reach what: one grant set, four sources

Every right any principal holds is a row in `sec.v_access_grant`, in one
shape: **who**, **over what**, **which permission**, **from which source**,
**granted by whom**, **for how long**.

| Source | Derived or stored | Permission | Reaches |
|---|---|---|---|
| `ownership` | derived from `bridge_disposition` | view + operate | the client record **and** the accounts they own |
| `disposition` | derived from `bridge_disposition` | view + operate | **that one account only** |
| `portfolio` | derived from `portfolio_client` | **view only** | the clients in a book granted to staff |
| `delegation` | **stored** in `sec.access_delegation` | as granted | whatever the grantor named |

Three design points worth defending:

**Disposition is per-account, and that containment is the whole reason.**
Client 3764 is authorised to operate account 3112, which client 3763 owns. He
reaches the account, its transactions, its loan and its balances. He does
**not** reach her client record, her other accounts, or anything else of hers.
Being able to use an account is not being able to see the person who owns it.
A per-client grant would have conflated them.

**Portfolio grants are `view` only.** A relationship manager is accountable
for a client, which is not authority to move their money. Flattening the two
is how a reporting tool quietly becomes a payment instrument. The product is
read-only today, so nothing acts on `operate` — the distinction is recorded
because it is the one the business makes, and a model that loses it cannot
get it back later.

**Three sources are derived live, and that was a correction.** The first cut
materialised every grant into a table, rebuilt per pipeline run. The test
suite caught the consequence: granting a portfolio inserted a row in
`sec.user_portfolio` but no matching grant, so the entitlement did nothing
until the next rebuild. That silently broke the claim this design exists to
make — onboarding is data, effective on the next statement — and introduced
exactly the failure a single access model removes: two descriptions of who may
see what, drifting apart. Now only `delegation` is stored, because only
delegation is a human decision with no other record.

### Answering the privacy question

`sec.v_who_can_reach_client` turns the model into the answer to *"who can see
this customer?"*. For client 3763 today:

| Principal | Kind | May | Because | Reason |
|---|---|---|---|---|
| `client_3763` | client | view, operate | ownership | The principal is this client |
| `client_3764` | client | view, operate | disposition | Authorised to operate this account |
| `rm_north` | relationship manager | view | portfolio | Client is in portfolio NORTH_BOOK |
| `rm_south` | relationship manager | view | delegation | Covering the northern book while rm_north is on leave |
| `admin_demo` | administrator | view | portfolio | Client is in portfolio ALL_CLIENTS |
| `cro_global` | risk | view | portfolio | Client is in portfolio ALL_CLIENTS |

Note the fourth row: a cross-book grant, with a named grantor, a reason, and
an expiry fourteen days out. It is the only row a human chose, and it is the
only row that can be wrong in a way the banking records cannot reveal — which
is why the table demands all three.

---

## 3. Two factors, both enforced by the database

**Factor 1** is the database role password, checked by PostgreSQL itself. It
is what makes `session_user` unforgeable: no statement the caller — or a
language model — can emit will change it.

**Factor 2** is a time-based one-time code (RFC 6238), verified by
`sec.verify_second_factor()` *inside* the database, against a secret that
never crosses the wire.

The claim worth testing is what sits between them:

> A principal holding the correct password, and nothing else, can read **no
> customer data at all**.

Not fewer rows, and not an error: the connection works, the queries run, and
every one returns empty. `tests/test_auth.py` asserts this for all eight
principals, across seven consumer views. A stolen password is therefore not a
breach by itself.

That holds because `sec.v_my_clients` ANDs `sec.has_verified_session()` over
the **whole** resolution rather than inside one branch — so a branch added
later cannot quietly skip the second factor.

### The details that make it a control rather than a gesture

- **Real TOTP.** `sec.totp_code()` is checked against the published RFC 6238
  test vectors, in both the SQL and the Python implementation. An
  authenticator app will not interoperate with an almost-TOTP, and a code
  generator that is subtly wrong is a control nobody else can re-implement.
- **Single use.** A code is valid for thirty seconds, and `last_step` marks it
  spent. Without that, anyone who observes a code has half a minute to replay
  it. The cost is real and the demo pays it: logging in twice as the same
  principal inside one window waits for the next code rather than weakening
  the check.
- **Bound to the connection.** A session records `pg_backend_pid()` and is
  valid only there, so a copied session id is useless on another connection —
  and one user completing a login does not authorise every other connection
  open as the same role.
- **Lockout.** Five committed failures lock the factor for fifteen minutes, and
  while it is locked even the right code is refused
  (`test_five_committed_failures_lock_the_factor_even_against_the_right_code`).
  **Known gap:** the counter is written in the caller's transaction. The
  project's client commits every attempt, but someone holding a principal's
  password can connect directly, roll each failed guess back, and is never
  locked out (`test_a_rolled_back_failure_still_counts_towards_the_lockout` is a
  strict expected failure that records this). The fix is to count attempts
  outside the caller's transaction, or to accept consumer logins only through
  a gateway **[REC]**.
- **The function takes a code, never a principal.** Whose factor is checked
  comes from `session_user` alone, so there is no parameter that lets a caller
  verify a second factor on somebody else's behalf. A test pins the signature.
- **Verification writes durably -- through the project's client.** Both
  outcomes write — a session on success, an attempt counter on failure — and
  `src/auth.py` commits both before it returns. An earlier version left them in
  the caller's transaction, where a rollback silently revoked the login and
  discarded the spent-code marker. The database cannot force a direct client
  to commit; see the lockout gap above.

---

## 4. Onboarding and offboarding

| Act | What it takes |
|---|---|
| New staff user | `CREATE ROLE` (a credential) + one insert into `sec.app_user` |
| New customer login | the same, with `user_type = 'client'` and `subject_client_id`. No portfolio |
| Enrol their second factor | one insert into `sec.auth_factor` — a separate act, as it is in life |
| New portfolio | one insert into `sec.portfolio`, plus its members |
| Grant a book | one insert into `sec.user_portfolio` |
| A delegation | one insert into `sec.access_delegation`, with grantor, reason and expiry |
| **Revoke everything** | **one `UPDATE`: `is_active = false`** |

No policy, view, query or deployment changes for any of them. `make demo`
performs the whole customer sequence live, including the step where the new
user **cannot log in yet** because they have not enrolled an authenticator —
a credential is not a login.

---

## 5. What a consumer cannot do

Verified by attempting it as `client_11409`, on every run of `make demo`:

| Attempt | Outcome |
|---|---|
| Read another customer's client record, account, loan, transactions, balances, cards | **0 rows** — policy |
| Go around the `ai` views to `core.fact_transaction` | **0 rows** — the policy is on the table |
| Read `stg` or `raw`, where no policy exists | refused — privilege |
| Read `sec.app_user`, `sec.auth_factor`, `sec.auth_session`, `sec.v_access_grant` | refused — privilege |
| Generate a TOTP code (`sec.totp_code`) | refused — privilege |
| Grant themselves another client | refused — privilege |
| Disable the policy, or `SET ROLE` to someone else | refused — privilege |

The two kinds of block are not equally strong and the distinction matters: a
privilege refusal stops the statement; a policy lets the statement **run** and
has already narrowed the answer. The second is what makes this safe for an AI
assistant, because a generated query never has to be inspected for whose data
it asks about.

---

## 6. What this is not

Stated here rather than left to be discovered.

1. **TOTP secrets are stored recoverable.** They must be, to verify a code.
   `sec.auth_factor.secret` is the most sensitive column in the schema; a real
   deployment encrypts it with a key held outside the database.
2. **The demo console prints the one-time code.** A system that can show you
   your own second factor has one factor. It exists so a walkthrough needs no
   phones, it is marked as a demo affordance everywhere it appears, and it is
   the first thing a deployment removes.
3. **There is no read audit.** This model controls who *can* read. It does not
   record who *did*. For a bank that is a regulatory gap, not a
   simplification, and it is the largest missing control in this build.
4. **Nothing is masked.** A customer sees their own birth date in full, and a
   relationship manager sees it for all 1,481 of their clients.
5. **The identity mapping is assumed correct** (A35). The product enforces the
   `db_role → client_id` mapping it is given; if that mapping is wrong, the
   wrong person sees a complete, correct-looking view of someone else's
   finances and nothing here could detect it.
6. **Role-per-user does not pool connections.** Correct at this size, and the
   first real engineering problem the moment a customer portal with concurrent
   users is put in front of it.
7. **The pipeline owner is exempt from the policies.** That is what makes the
   build possible. It is a deployment identity, never an application login,
   and a real deployment separates the build role from the owning role.
