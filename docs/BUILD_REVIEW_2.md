# Build review 2: identity, access grants and two-factor authentication

Written immediately after the build, against the repository and the database
rather than from memory.

---

## 1. What was asked, and what was built

Five things, all delivered:

| Asked | Built |
|---|---|
| Switch customers to include disponent accounts | `disposition` is a first-class grant source. Client 3764 reaches account 3112, which he may operate and does not own |
| Other ways to identify clients than `client_id` | `client_ref` (`BRK-TQ8D-RCB3`, HMAC under a secret salt) and `account_ref` (IBAN with genuine mod-97 check digits) |
| A clear system in the data model for who can see and operate whose | `sec.v_access_grant`: four sources, `view`/`operate`, a grantor, a reason and a validity window, in one shape |
| Two-factor authentication | RFC 6238 TOTP, verified in the database. Without the second factor, every entitlement resolves to nothing |
| A demo that switches between accounts with a two-step login | `make demo-login` (scripted, 7 acts) and `make demo-interactive` (audience-driven), with `docs/DEMO_SCRIPT.md` |
| Everything documented and visualised | `docs/ACCESS_AND_AUTH.md`, two new figures, D023-D027, A39-A46, six deck slides |

State of the build: **202 tests passing**, `make clean all` green from an empty
database, 12 of 12 steps, **10 of 10** LLM answers still matching, DDR still
two pages.

---

## 2. The two judgement calls I made without asking

**Two-factor is enforced in the database, not in an application gateway.**
A gateway is where most production systems put it and would have been easier;
it also makes the control a property of the application rather than of the
data, which is the mistake this project already rejected for entitlements
(D009). Enforcing it in the database makes the claim testable in the only way
that means anything: hold the correct password, present nothing else, read
nothing. The cost is that every consumer path now logs in — the question
runner, the workbook, the worked example and the test suite — and that two
logins as the same principal inside thirty seconds must wait for a fresh code.

**The customer/disponent change applies to the customer, not to staff.**
A relationship manager's book is still resolved from their portfolio. The
alternative — managers also seeing accounts their clients may merely operate —
would have widened every book for a reason nobody asked for.

---

## 3. What was verified, and how

**The headline claim, tested for every principal.** `test_the_password_alone_reveals_nothing`
is parametrised over all eight logins and seven consumer views: 56 assertions
that a correct password with no second factor returns zero rows. The companion
test asserts the same logins *do* return rows once the factor is presented, so
the control cannot pass by everything being broken.

**The TOTP is real.** Both the SQL and the Python implementations are checked
against the six published RFC 6238 test vectors, and against each other on a
fresh secret. An almost-TOTP would not interoperate with an authenticator app
and could not be re-implemented by anyone else.

**Replay, session theft, guessing and logout** each have a test: a spent code
is refused inside its own window; a second connection as the same role is not
authorised by the first one's login; five failures lock the factor; ending the
session takes the data away on the same connection.

**The disposition containment** is tested by name in both directions: 3764
reads account 3112 and its postings, and gets zero rows for client 3763.

**The IBANs** are validated against an independently written mod-97 check, and
a deliberately corrupted one is confirmed to fail.

---

## 4. What this build got wrong

Four defects, all mine, all found during the work.

### 4.1 A headline claim quietly became false

The first implementation materialised every access grant into a table, rebuilt
per pipeline run. Granting a portfolio inserted a row in `sec.user_portfolio`
and no matching grant — so the new entitlement did **nothing** until the next
rebuild, while the entitlement tables said it should work.

That is worse than an ordinary bug. It silently falsified the claim the design
exists to make (*onboarding is data, effective on the next statement*) and it
introduced the exact failure a single access model is supposed to remove: two
descriptions of who may see what, drifting apart.

Caught by `test_onboarding_a_user_and_a_portfolio_is_pure_insert`, which
survives because it asserts a *behaviour* rather than a row count. Fixed by
deriving the three derivable sources live in a view (D027). Nothing can drift,
because there is nothing to keep in step.

### 4.2 Session writes were not durable

`sec.verify_second_factor()` writes on both outcomes — a session on success, an
attempt counter on failure — and both were left inside the caller's
transaction. A rollback therefore silently revoked a completed login, and the
spent-code marker never persisted, so replay protection appeared to work
within one connection and failed across two.

Found by a test that failed for a reason I could not explain from the code,
which is the right reason to keep digging rather than adjust the test. Fixed
by committing before returning.

### 4.3 A clock-drift bug I introduced while fixing 4.2

Once replay protection persisted, the demo helper had to wait for a fresh code.
I compared the local clock against the step the server had recorded as spent —
but the verifier accepts adjacent steps, so the recorded step can be one ahead
of the step the client thought it generated. The helper then produced an
already-spent code, intermittently. Fixed by requiring **both** clocks to pass
the spent step. Worth recording because the symptom was a flaky test and the
easy "fix" would have been a retry loop hiding a real asymmetry.

### 4.4 The test suite poisoned itself

The authentication tests deliberately present wrong and replayed codes; five
failures lock a principal out for fifteen minutes. Nothing reset the counters,
so the suite passed on a clean database and failed on the second run with a
lockout unrelated to the code under test. Fixed with a session-scoped
autouse fixture. A test suite whose failures depend on how recently it last ran
is a suite nobody will trust.

### 4.5 Two gates fired, correctly

Not defects — the project's own checks doing their job, recorded because they
are evidence the gates are load-bearing. `make semantic` refused to build twice
until the new columns (`principal_type`, then the four reference columns) were
documented. Each cost two minutes.

---

## 5. What is weak

**The demo console prints the one-time code.** A system that can show you your
own second factor has one factor. It is marked as a demo affordance at every
call site, it is stated on the figure and in the demo script, and it is the
first thing a deployment removes — but it is the single largest gap between
this and something I would put in front of customers.

**TOTP is phishable.** A victim relaying a live code to an attacker in real
time defeats it. For a bank moving real money the right factor is
phishing-resistant (WebAuthn/passkeys). The session model would not change;
only the factor would. Recorded as A43.

**The secrets are stored recoverable.** They must be, to verify a code.
`sec.auth_factor.secret` is now the most sensitive column in the schema and it
is protected by nothing but privileges. A deployment encrypts it with a key
held outside the database.

**Still no read audit.** Unchanged from the last review, and now more
conspicuous: the model answers *who can reach this customer* precisely, and
cannot answer *who did*. For a bank that is a regulatory gap.

**The pid binding is good, not perfect.** Backend pids are reused after
wraparound. A replay would need the same pid, the same role, and the session
still inside its thirty-minute window — thin, but a production system would add
the backend start time to the binding. The column is already there; the
predicate does not use it.

**Shared connections in the test suite.** Each principal logs in once and the
connection is reused, because a fresh login per assertion would spend the run
waiting for codes. Tests are therefore not fully isolated from each other; the
reuse wrapper rolls back after every block, but a test that left a session
ended would affect the next. The authentication tests open their own
connections for exactly that reason.

**`sec.v_access_grant` is unindexed by construction.** It is a view over four
sources, evaluated per query, and the portfolio branch resolves 13,605 rows.
Fine at this size, and the first thing to materialise — carefully, with the
drift problem of 4.1 in mind — if it ever becomes slow.

---

## 6. What I would do next

1. **Add the read audit.** Still the largest missing control, now the only one
   whose absence the model makes obvious.
2. **Replace the printed code** with a real enrolment flow (a QR code and an
   authenticator), so the demo stops being the weakest link in its own story.
3. **Encrypt the TOTP secrets** with a key outside the database.
4. **Add the backend start time to the session binding** — one predicate, and
   it closes the pid-reuse gap properly.
5. **Property-test the isolation**: for a random sample of customer logins,
   assert each sees exactly one client and any two see disjoint sets. A fixed
   pair cannot catch a whole class of bug.

---

## 7. Would I ship it?

For the brief: yes, and `make demo-login` is what I would run first. It makes
the abstract claim concrete in forty seconds, and the act where the
administrator holds the right password and reads an empty database is the one
people remember.

As a customer-facing system: not yet, and the reasons are now a short list
rather than a vague unease — print the code no more, encrypt the secrets, add
the audit log, and take the factor choice to someone who has thought about
phishing. The authorisation model underneath I would ship as it stands; it is
the part I am most confident in, because it is enforced by the engine,
derived from records that cannot drift, and every right it grants carries the
reason it exists.
