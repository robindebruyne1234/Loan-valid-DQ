# Demo script: showing stakeholders that the data is private

A fifteen-minute walkthrough proving one thing from several angles: **the data
a person can reach is decided by who they proved themselves to be, and by
nothing else.**

Everything below is a real login against the real database. The only thing
simulated is the authenticator app — the console prints the code a customer's
phone would show, because an audience cannot pass six phones around. Say that
out loud once, early. It is the first thing a sceptical person will ask.

---

## Before they arrive (5 minutes)

```bash
make up                 # start PostgreSQL. Takes a few seconds.
make demo-login         # the full scripted walkthrough, ~40 seconds
```

If `make demo-login` prints seven acts and ends with `=== END ===`, you are
ready. If it errors, see **If something breaks** at the bottom.

Two things to have open:

1. A terminal, font size up. The output is 78 columns wide.
2. `docs/diagrams/11_access_model.png` and `12_auth_flow.png`, for the two
   moments where someone asks *how*.

**Know these three names.** The whole demo turns on them:

| | |
|---|---|
| **Klara** (`client_3763`) | A customer. Owns account 3112. |
| **Petr** (`client_3764`) | A customer. Owns nothing, but the bank authorised him to **operate** Klara's account. |
| **Eva** (`rm_north`) | Their relationship manager. Both are in her book. |

Klara and Petr are a real relationship in the source data — a disposition of
type DISPONENT — not something invented for the demo.

---

## The walkthrough

Run `make demo-login` and talk over it. The acts below match the output.

### Act 1 — a customer logs in (2 min)

**Point at:** the line that says `can reach : 1 clients | 1 accounts`.

> "This is Klara's entire view of the bank. One client — herself. One account.
> Her 439 transactions. She is not reading a filtered copy of the bank's data;
> as far as her connection is concerned, this *is* the bank's data."

**Point at:** `BRK-TQ8D-RCB3` and `CZ84 8888 0000 0000 0000 3112`.

> "Two things she can quote on the phone. Neither is a row number. You cannot
> count the bank's customers from them, and you cannot guess her neighbour's."

### Act 2 — the second customer, and the interesting one (3 min)

> "Petr owns nothing. But the bank authorised him to use Klara's account — a
> joint arrangement, a business partner, a carer. Watch which account he gets."

**Point at:** his account line — the **same** `CZ84 ... 3112`.

Then the note underneath, and pause on it:

> "He reaches the account. He does **not** reach Klara. Being able to use
> someone's account is not being able to see them. That is a deliberate choice
> in the model: the right is granted over the *account*, not over the person."

This is the moment where someone usually says *"but could he…"* — go to Act 3.

### Act 3 — one customer trying to read another (3 min)

**Point at:** the column of results, then at the two words that differ.

> "Seven attempts, by name, for data that is not theirs. Look at the right
> column: some say *refused*, some say *0 rows*. Those are different, and the
> second is the stronger one."
>
> "*Refused* means the statement was blocked — they were never allowed to ask.
> *0 rows* means the statement **ran**, and the database had already narrowed
> the answer before it came back."
>
> "That second one is why we can let an AI write the query. It doesn't matter
> what it asks for. The filter isn't in the question."

Include the fourth line deliberately: *the base table, going around the
views*. The protection is not a view someone can step around.

### Act 4 — the people who look after them (2 min)

> "Eva sees 1,481 clients — her book, including both Klara and Petr. Neither
> of them can see the other. Same database, same moment, same query."

**Point at:** `rm_unassigned`, `0 clients`.

> "A new employee on their first morning. The default is **see nothing**, not
> see everything. Access is something you are given, one grant at a time."

### Act 5 — the password on its own is worthless (3 min)

**This is the act to slow down for.** It is the one people remember.

> "This is the administrator. They can see every client in the bank — 5,369 of
> them. Now watch what happens when someone has their password but not their
> phone."

**Point at:** `BETWEEN STEPS: authenticated, but can reach 0 clients.`

> "Correct password. Connection open. Zero clients, zero accounts, zero rows.
> Not an error message — the queries ran and came back empty."

Then the wrong code, then the real one:

> "A stolen password here is not a breach. It is a login that returns an empty
> database. And then with the second factor: 5,369 clients, immediately."

If you show **one** screen from this demo, show this one.

### Act 6 — why each person can reach what they reach (2 min)

**Point at:** the `because` column.

> "This is the answer to the question a regulator actually asks: *who can see
> this customer?* Six principals, and each one has a reason — they are the
> client, they were authorised to operate the account, the client is in their
> book, or someone granted it."

**Point at:** the `rm_south` / `delegation` row.

> "That one is a human decision — a manager covering another's book while
> they're on leave. It names who granted it, why, and it expires in fourteen
> days by itself. It's the only kind of access a person chooses, so it's the
> only kind that carries a reason."

### Act 7 — what the model is (1 min)

> "Four sources of access, one shape. Three are derived from records the bank
> already keeps — who owns an account, who may operate it, whose book a client
> is in — so they cannot drift out of date. Only delegation is stored, and
> every one of those has a name against it."

---

## Taking questions

**"Could a developer just query the database directly?"**
Someone with the *owner* credential, yes — that identity owns the tables and
is exempt from their policies, which is what makes the nightly build possible.
It is a deployment secret in a vault, never an application login. Every
*application* identity, including the administrator, goes through the policies.
Point at Act 5: `admin_demo` is an ordinary consumer with a portfolio that
happens to contain everyone, and `rolbypassrls` is false for all of them.

**"What if the AI writes a malicious query?"**
It cannot widen what it sees, because the predicate is not in its query. Act 3
line 4 is the proof: going around the published views to the underlying table
returns nothing either. Separately, its SQL is parsed before execution and
must be a single read-only statement.

**"Is this real two-factor, or a mock-up?"**
Real RFC 6238 — the same algorithm as any authenticator app — checked against
the standard's own published test vectors. Codes are single use, locked out
after five failures, and a session is bound to one connection. The only
pretend part is that the console prints the code instead of a phone showing
it, and that is the first thing a deployment removes. Be ready for the
follow-up: the lockout counts failures this application commits; someone
connecting directly with a stolen password can roll failures back, so that
gap is named in `docs/ACCESS_AND_AUTH.md` rather than hidden.

**"How long to add a new customer?"**
One insert, plus a credential, plus their authenticator enrolment. No
deployment, no policy change. Run `make demo` — it onboards one live, shows
them blocked until they enrol, then shows them seeing exactly their own data,
then revokes them with a single `UPDATE`.

**"Can a customer see their own data if they log in from two devices?"**
Yes — each connection does its own second factor. A session is bound to the
connection that created it, so one login does not silently authorise another.

**"What is missing?"** *(Answer this honestly; it buys more credit than it costs.)*
Three things. There is no record of who actually **read** a row — only of who
could, which for a bank is a regulatory gap and the largest hole here. Nothing
is masked, so a manager sees full birth dates for their whole book. And the
mapping from a real person to a customer record is assumed correct: it comes
from the bank's identity process, and if it is wrong this system cannot tell.

---

## Driving it yourself

```bash
make demo-interactive
```

Pick a persona, type the code the console shows, then run any SQL you like as
that person. Good things to let an audience try:

```sql
SELECT count(*) FROM ai.client;                      -- their reach
SELECT * FROM ai.my_entitlement;                     -- what kind of principal they are
SELECT * FROM ai.client WHERE client_id = 3763;      -- ask for someone else by name
SELECT count(*) FROM core.fact_transaction;          -- go around the views
SELECT count(*) FROM stg.trans;                      -- try the uncleaned copy
```

Hand the keyboard over for the third one. Someone typing the attempt
themselves and watching it return nothing is worth more than watching you do
it.

Other useful commands:

```bash
make demo                      # the written worked example, one client end to end
python3 -m src.demo_console --as client_3764      # a single login, nothing else
python3 -m pytest tests/test_auth.py -q           # the 39 authentication tests
```

---

## If something breaks

| Symptom | Cause | Fix |
|---|---|---|
| `connection refused` | the database stopped (it does on container restart) | `make up` |
| `no second factor enrolled` | the principal exists but has not enrolled | `make entitlements` |
| `code already used` | two logins as the same person inside one 30-second window | wait 30 seconds; this is the replay protection working |
| `locked until HH:MM` | five failed codes | wait, or `make entitlements` to reset the counters |
| A persona sees 0 when it should see rows | the security layer was rebuilt without the model | `make model` then `make entitlements` |
| Everything looks empty | the pipeline has not been run in this container | `make all` (about five minutes) |

**If it fails live:** the written walkthrough in `docs/WORKED_EXAMPLE.md`
contains the captured output of a real run, including the isolation attempts
and their results. Switch to it rather than debugging in front of people.

---

## The three sentences to land

1. **A password on its own returns an empty database.**
2. **Two customers of the same manager cannot see each other, and one of them
   can even use the other's account without being able to see her.**
3. **Every right anyone holds has a reason recorded against it, and the one
   kind a human chose is the one that carries a name, a justification and an
   expiry.**
