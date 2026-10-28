# DECISIONS

One entry per decision: context, options, choice, reason, consequence.
This file is the raw material for the Design Decision Record and for the
45-minute walkthrough. Newest decisions are appended at the end.

---

## D001 - Repository lives at the git root, not in a nested project folder

**Context.** The brief asks for "a Git repository or zip file following the
structure in section 4". The working repository is `Loan-valid-DQ`.

**Options.** (a) Nest everything under `berka-governed-data-product/`.
(b) Put the project at the repository root.

**Choice.** (b) Project at the root.

**Reason.** The repository *is* the submission. A nested folder adds one path
segment to every command in the README and buys nothing; `make all` from the
clone root is what a reviewer will try first.

**Consequence.** `src/config.py` derives `PROJECT_ROOT` from its own location,
so the layout can still be moved without touching any other module.

---

## D002 - PostgreSQL 16, run natively where no Docker daemon exists

**Context.** Task 3 is about entitlement-aware access. The only way to show
that an LLM-generated query *cannot* bypass the filter is to put the filter in
the database engine and prove it with a real connection as a real low-privilege
user. The build container has the Docker CLI but no Docker daemon
(`/var/run/docker.sock` is absent), and it does have a PostgreSQL 16 cluster.

**Options.** (a) PostgreSQL 16 in `docker compose`. (b) DuckDB file, shipping
the PostgreSQL row level security DDL as untested scripts. (c) PostgreSQL 16
from the native cluster, keeping `docker-compose.yml` for portability.

**Choice.** (c), with (a) as the preferred path when a daemon is present.
`scripts/db_up.sh` tries `docker compose` first and falls back automatically.

**Reason.** DuckDB has no row level security, so option (b) would reduce
Task 3 to prose and untested SQL -- the weakest possible answer to the one task
that is purely about enforcement. The native cluster runs the identical DDL,
identical policies and identical tests, so nothing about the submission is
hypothetical.

**Cost.** One shell script (about 50 lines) to paper over the difference, and a
`make up` that is slightly less hermetic than a pure compose stack.

**Consequence.** `make up` works in both worlds. Every row level security claim
in this submission is backed by a test that actually connects as a restricted
role (`tests/test_rls.py`).

---

## D003 - Data acquired from a verified public GitHub mirror of the PKDD'99 files

**Context.** The documented acquisition order was: the CTU relational
repository (MySQL on `relational.fel.cvut.cz:3306`), then the author's archive
at `sorry.vse.cz`, then a Kaggle mirror. In this environment outbound traffic
goes through a policy-enforcing proxy that allows HTTPS to a host allow-list
only: `sorry.vse.cz` and `relational.fel.cvut.cz` are both refused (HTTP 403 on
CONNECT), and raw MySQL on port 3306 cannot be tunnelled at all.

**Options.** (a) Stop and ask for the files to be placed in `data/raw/`.
(b) Use a public mirror that is reachable, and verify it is byte-equivalent in
substance to the original.

**Choice.** (b) `github.com/jlacko/berka-dataset`, which ships the original
eight `*.asc` files (semicolon separated, quoted headers) plus the original
"Financial Data description.pdf".

**Reason.** The mirror is verifiable against published figures, which is what
matters for trust: row counts came out at 4,500 accounts / 5,369 clients /
5,369 dispositions / 892 cards / 682 loans / 77 districts / 6,471 orders /
1,056,320 transactions -- every one an exact match to the reference counts in
the brief's dataset. The files are the unmodified `.asc` originals, not a
re-exported CSV with renamed columns, so no column mapping guesswork is needed.

**Consequence.** `raw.load_audit` stores a SHA-256 per source file, so the
exact bytes behind every number in this submission are identifiable.
`trans.asc` is stored gzipped (69 MB -> 17 MB) and hashed on its *decompressed*
stream, so the hash identifies the data rather than the compression settings.

---

## D004 - Public copy is primary; defects are injected reproducibly in a separate schema (HD1)

**Context.** The brief says the bank "may have injected extra defects into its
copy", and the assessment compares findings against those injected defects. No
bank-supplied copy was received, so `data/raw/provided/` is empty and the
public copy matches the reference counts exactly -- meaning it carries no
injected defects beyond the ones the original dataset has always had.

**Options.** (a) Run the rules on the clean public copy only, accepting that
most rules report zero and the defect tab is thin. (b) Also build a
reproducible defect injector in a separate schema and report both.

**Choice.** (b) -- confirmed with the candidate at decision point HD1.

**Reason.** A rule that has never fired is not evidence of anything. The
injector (`sql/70_inject_defects.sql`, seeded and deterministic) corrupts a
copy of `stg` in schema `inject` with one defect per rule family, and
`tests/test_dq.py` asserts that the matching rule catches each one. The
certified answers to the 10 questions are still computed on the untouched data,
and every injected row is labelled as injected everywhere it appears.

**Consequence.** Two numbers per rule in the report: what fired on the real
data, and what fired on the injected copy. When the bank's own copy arrives,
`make dq` on `data/raw/provided/` is the only step needed -- the rules do not
change.

---

## D005 - The LLM is the local Claude CLI, called as a sandboxed text completion (HD2)

**Context.** Task 2 requires an LLM to generate the SQL for the 10 questions
using the semantic layer. The documented default was a local open-weight model
through Ollama; Ollama is not installed in the build container and the model
download hosts are not on the proxy allow-list.

**Options.** (a) Hosted API behind `LLM_PROVIDER` / `LLM_MODEL` /
`LLM_API_KEY`, which needs a key this environment does not hold. (b) Export
the prompt pack and mark the step `NOT EXECUTED`. (c) Use the authenticated
Claude CLI that is present, invoked as a plain completion endpoint.

**Choice.** (c) -- confirmed with the candidate at decision point HD2.
`src/llm_client.py` keeps all three behind one interface, so switching provider
is one environment variable.

**Reason.** The point of the exercise is whether the *semantic layer* is good
enough for a model to produce correct SQL. That needs a real model call. The
CLI is invoked with `--strict-mcp-config`, an empty MCP config, an explicit
system prompt and every tool disallowed, so the model has no database
connection, no filesystem and no search: it sees only the rendered semantic
context pack and the question, exactly like an API call would. Without that
sandboxing the result would prove nothing, because an agent could simply go and
read the tables.

**Cost.** One subprocess wrapper, and a dependency on a CLI rather than an SDK.

**Consequence.** Every call writes `llm_logs/<question>.json` with the full
prompt, model id, parameters, raw response and timing. Nothing in the Questions
tab is hand-written: where a call fails, the cell says `NOT EXECUTED`.

**Later (2026-10-27, native Windows build).** Ollama became available on the
laptop, and `qwen2.5-coder:3b` was added as an optional, free local provider
for the walkthrough page and for a second measurement. Its run is written to
`dq/results/local/` and `llm_logs/local/` and never replaces the Claude run,
which remains the submission evidence (6 match, 2 partial, 2 mismatch against
Claude's 10 of 10).

---

## D006 - Code-to-label mapping lives in one place, and the redundancy is checked

**Context.** The seven Czech code sets (statement frequency, loan status, card
type, disposition type, transaction type, operation, category) have to be
readable in staging for profiling, available in SQL for the model, and
available to the LLM in the semantic layer. Three places to write the same
mapping.

**Options.** (a) Repeat the mapping in each place. (b) One source, and derive
the rest. (c) One source for the product, with any convenience copy verified.

**Choice.** (c). `src/config.py` holds the mapping; `src/build_model.py`
publishes it as `core.ref_codes`; `sql/30_core.sql` joins that table for every
label; the semantic layer renders its allowed-value lists from the same place.
The staging layer additionally decodes labels inline while casting, which is a
convenience copy -- so `build_model.check_codes_against_staging` asserts that
staging's labels equal `ref_codes`, and that no code exists in the data that
the catalogue does not publish.

**Reason.** The failure mode that matters is not duplication, it is *silent*
duplication: two places disagreeing and nobody noticing until a report and a
dashboard show different words for the same loan. A checked copy fails the
build instead.

**Cost.** One verification function, about 60 lines, and one extra join per
labelled column in the core build.

---

## D007 - Natural keys, not surrogate keys

**Context.** The source keys (`account_id`, `client_id`, `trans_id`, ...) are
stable integers with no gaps in meaning and no reuse.

**Options.** (a) Surrogate integer keys per dimension with the natural key as
an attribute. (b) Use the natural keys as primary keys.

**Choice.** (b).

**Reason.** Surrogate keys buy conformance across multiple source systems and
the ability to track slowly changing dimensions. There is one source system
here and a single extract with no history, so they would buy a join per
dimension and nothing else. They also make every example query longer, which
matters when the queries are written by an LLM reading a context pack.

**Consequence.** At 100,000x this is one of the first things to revisit --
along with partitioning the transaction fact by month. It is called out in the
Design Decision Record for exactly that reason.

---

## D008 - The rule self-test nearly deleted real data; the fix is schema scoping

**Context.** `core` is built from `stg` minus the rows block rules rejected,
read through the view `dq.v_blocked`. The identical rule set also runs against
schema `inject` (the corrupted copy that proves the rules fire), and writes its
verdicts to the same `dq.quarantine` table.

**What happened.** The first version of `dq.v_blocked` selected every
block-severity quarantine row regardless of which schema it came from. Running
the rule self-tests therefore made the *injected* defects exclude *real* rows
from the data product: `core.dim_district` came out at 76 rows instead of 77,
`dim_account` at 4,457 instead of 4,500, and 11,024 transactions lost their
account. Nothing in the data was wrong; the control plane was.

**How it was caught.** `build_model` verifies the declared foreign keys and
grains after every build, and it failed with eight problems before any
deliverable was produced.

**Choice.** `dq.v_blocked` and `dq.v_row_flags` filter `target_schema = 'stg'`,
and the comment in `sql/00_schemas.sql` says why the filter is load-bearing.

**Reason and consequence.** This is the argument for verifying a model rather
than trusting a build: the pipeline ran green, produced plausible row counts,
and was quietly wrong. It is also the argument for keeping the test data in a
separate schema rather than mutating staging in place. Kept in this record on
purpose -- it is a better answer to "how do you know your pipeline is right"
than any clean run.

---

## D009 - The entitlement filter sits in the database, and identity comes from `session_user`

**Context.** Task 3: expose the data product so each user sees only rows for
their own clients, say where the filter sits, say why an LLM-generated query
cannot bypass it, and onboard a new user or portfolio without code changes.

**Options for where the filter sits.**
(a) In the prompt: tell the model to add `WHERE client_id IN (...)`.
(b) In the application: a gateway rewrites or wraps every generated query.
(c) In the database: row level security policies on the tables themselves.

**Choice.** (c), with (b) kept as a secondary control (`src/sql_guard.py`).

**Reason.** (a) is not a control, it is a request: the thing being filtered is
also the thing being asked to apply the filter. (b) is real, but it is defeated
by one query shape nobody thought of, and the blast radius of a mistake is
every user. (c) puts the predicate inside the plan of every statement on that
connection. The LLM never holds the connection -- it emits text -- and the
predicate is not in the text, so no rewriting of the text can remove it.
`tests/test_rls.py` runs nine bypass attempts (switch role, read the base
tables, read the raw layer, set a session variable, edit the entitlement
tables, disable the policy, drop the policy, write, join outwards) and all nine
fail.

**Options for identity.** (i) `current_setting('app.user')`, set by a pooling
gateway. (ii) `session_user`, the authenticated database role.

**Choice.** (ii).

**Reason.** A GUC can be set by anything that can send SQL, so an entitlement
resolved from one is exactly as strong as the guard in front of it -- and the
guard is a Python function, which is a weaker place to stand than the engine.
`session_user` cannot be re-pointed without a password the model never sees.
`tests/test_rls.py::test_setting_a_session_variable_does_not_change_visibility`
sets `app.end_user` to another user's name and shows the visible row count
does not move.

**Cost.** Role-per-user conflicts with naive connection pooling: a pool keyed
only by DSN cannot be shared across users. The practical answer is a pool per
role (banks run hundreds of roles routinely) or `SET ROLE` performed by a
trusted gateway on a privileged connection, where the gateway -- not the model
-- decides the role. Discussed in the Design Decision Record.

**Onboarding.** Four inserts and no code: a user is a row in `sec.app_user`, a
portfolio a row in `sec.portfolio`, its clients rows in `sec.portfolio_client`,
and the grant a row in `sec.user_portfolio`. The only DDL is `CREATE ROLE`,
which is a credential rather than business logic. Deactivation is one UPDATE.
`tests/test_rls.py::test_onboarding_a_user_and_a_portfolio_is_pure_insert`
onboards a user, grants a book, checks the visible rows change on the next
statement, deactivates them and checks access is gone.

---

## D010 - Every view between the consumer and the policy must be `security_invoker`

**Context.** The `ai` views were created `WITH (security_invoker = true)` so
that the row level security policies on `core` are evaluated as the calling
user. The three curated views in `core` (`v_account_owner`, `v_loan_enriched`,
`v_client_region`) were not.

**What happened.** A PostgreSQL view normally reads its base tables with its
*owner's* rights, and a table owner is exempt from its own policies. So
`ai.loan` -- an invoker view -- read `core.v_loan_enriched` -- an owner view --
and the policy was evaluated as `berka_owner`. Measured on a user entitled to
nothing: `ai.loan` returned **all 682 loans** and `ai.account_owner` **all
4,500 accounts**, while `core.fact_loan` correctly returned **0** for the same
user in the same session. The base table was right and the view chain was
wrong.

**Choice.** Every view on the path from a consumer to a policy carries
`security_invoker = true`, and
`tests/test_rls.py::test_every_view_between_the_consumer_and_the_policy_is_security_invoker`
reads `pg_class.reloptions` and fails if any of them does not. The one
deliberate exception, `ai.my_entitlement`, is named in the test with its
reason.

**Reason and consequence.** This is the most useful thing in this submission to
be asked about. The design was right, the DDL was one setting short, and the
symptom was invisible from the owner's connection -- the only way to see it was
to connect as a restricted user and count rows. That is why the entitlement
claims here are backed by tests that authenticate as real low-privilege roles,
rather than by a description of the policies.

---

## D011 - The LLM runs sandboxed, and the evaluation is value-based

**Context.** Task 2 asks for an LLM to answer the 10 questions using the
semantic layer, and for the generated SQL and the result per question.

**Choice on isolation.** The model is called with no tools, no MCP servers, an
explicit system prompt and a working directory outside the repository. It
receives the rendered context pack and the question, and nothing else.

**Reason.** An agent that can read the database or the repository would answer
the questions by looking, and the exercise would measure the agent rather than
the semantic layer. The recorded transcripts in `llm_logs/` show
`permission_denials: []` and a single turn per question, which is what a pure
completion looks like.

**Choice on comparison.** Value-based: every (dimension, measure) pair in the
reference answer must appear on some row of the model's answer within a
relative tolerance of 1e-4, and for the three ranked questions the order is
checked too.

**Reason.** Two correct queries name their columns differently -- `clients`
versus `client_count` -- and a correct answer may carry extra supporting
columns. Comparing SQL text or column names would measure style. What matters
is whether the number the business user reads is right.

**Honest note on one evaluator change.** On the first run Q6 scored
`mismatch`. The model's counts were identical to the reference for all twelve
months; it had labelled the months `1996-01` while the evaluator was looking
for the integer `1`. That was a defect in the evaluator, not in the answer, so
the evaluator now accepts any published representation of a dimension (a month
as `1996-01`, `1` or `January`; a district by name or id). To keep that change
from quietly becoming "loosen until it passes", `tests/test_evaluate.py`
corrupts the recorded answers and asserts the evaluator rejects them: doubled
measures, a reversed ranking, truncated rows, an empty result and a missing
answer all fail, and `True` is not allowed to match a count of 1.

**Result.** 10 of 10 questions answered on the first attempt, 10 of 10 matching
the hand-written reference answers, no retries used and no SQL hand-corrected
(Claude Sonnet 5.5, run of 2026-10-25, on the semantic pack as it was before the
semantic audit changed it).

---

## D012 - Rebuilding core restores the AI surface in the same target

**Context.** `sql/30_core.sql` rebuilds the core tables with
`DROP TABLE ... CASCADE`, which also drops the `ai` views that depend on them.
Running `make model` on its own therefore left the consumer surface missing,
which surfaced as `relation "ai.transaction" does not exist` in the middle of
the question run.

**Choice.** The `model` target runs `src.build_security` after
`src.build_model`, so the ai views, the policies and the grants are restored by
the same command that invalidated them.

**Reason.** A target that leaves the database in a state no other target
expects is a trap for the next person -- and `make all` ordering would have
hidden it, because `entitlements` runs after `model` there anyway. The failure
only appeared when a single step was re-run, which is exactly how someone
iterates.

**Consequence.** Both `make model` and `make all` leave a complete, queryable
surface. The ai views are cheap to rebuild (they are views), so the extra step
costs about a second.

---

# Cleaning decisions (D013-D020)

The first twelve decisions were written while the pipeline was being built, and
they over-record one half of the brief. Five of them (D005, D009, D010, D011,
D012) are about access and LLM control; two (D006, D007) are about modelling;
**none** recorded what the cleaning actually does. That is the wrong balance for
a brief whose subject is making data AI-ready: the controls are a property of
the serving surface, while the cleaning is the product.

These eight entries close that gap. They were reconstructed from the code and
checked against the database, and every number in them comes from the probe of
the same name in `docs/CLEANING_LEDGER.md`.

---

## D013 - Cleaning never repairs a value in place

**Context.** Eight source files, 1,079,680 rows, with placeholders, undecodable
codes, unparsable dates and a balance chain that does not always reconcile. The
textbook options for a bad value are repair it, drop it, or keep it and say so.

**Options.** (a) Repair: impute the missing unemployment rate, infer the
intended balance, correct the duplicate. (b) Drop every row with any defect.
(c) Type, normalise, decode and derive -- but never overwrite an observation --
and let a separately graded rule layer decide the consequence.

**Choice.** (c).

**Reason.** A repaired value is indistinguishable from an observed one a week
later. That is tolerable in a model you train and throw away, and not tolerable
in a bank's data product where someone will eventually reconcile a number
against a statement. Dropping is worse: it silently changes every denominator.
The chosen shape means that of the cleaning steps in the ledger, exactly one
(C14, quarantine) removes a row from the product, it removed **1**, and C21
proves the arithmetic on both rows and money.

**Consequence.** The product carries known-bad rows with flags on them, so a
consumer has to be willing to read a caveat. The 55 accounts whose balance
chain does not reconcile are still in `core`, still answerable, and still
marked -- which is the honest result, and also the one that costs the reader
more attention than a quietly cleaned number would.

---

## D014 - Placeholders become NULL; the original text survives beside them

**Context.** The source writes "missing" at least seven ways: empty string,
quoted empty string, a single space, `?`, `NA`, `-`, and the word `unknown`.
District 69 (Jesenik) carries `?` in both the 1995 unemployment rate and the
1995 crime count.

**Options.** (a) Leave the text as it is and let every consumer handle it.
(b) Map the known placeholder set to NULL and lose the original. (c) Map to
NULL and keep the original in a `<column>_raw` audit column, with a note.

**Choice.** (c), with the placeholder list in `src/config.NULL_PLACEHOLDERS`
and mirrored by `stg.norm_text`.

**Reason.** Option (a) makes every completeness number wrong, because `?`
counts as a value. Option (b) makes the cleaning unfalsifiable. Option (c)
costs two columns per affected table and leaves the step checkable: C03
measured **1,380** rows where a placeholder became NULL (1,379 standing orders
with no category, and the one district), and each of them can still be read in
its raw form.

**Consequence.** The audit columns are dead weight on tables with no
placeholders, which is most of them. A real warehouse would carry this as one
side table rather than per-column, and that is the shape to move to at volume.

---

## D015 - Two-digit years are read as 19xx, and an unparsable date is NULL

**Context.** Every date in the source is `YYMMDD` with no century. `card.issued`
additionally carries a clock time (`931107 00:00:00`) that no other date column
has.

**Options.** (a) A sliding window (`<= 30` means 20xx). (b) Hard-code the 20th
century. (c) Refuse to parse and keep the text.

**Choice.** (b), with the trailing clock time stripped before parsing, and a
failed parse returning NULL rather than raising.

**Reason.** The dataset window is 1993-1998 and `VAL_DATE_OUT_OF_RANGE` fires
if anything lands outside it, so the sliding window would add a rule for a case
that cannot occur in this extract. The NULL-on-failure part matters more than
the century: a cast that throws aborts the load and hides the defect it tripped
over, which is precisely the value a quality report needs to see. C05 parsed
**1,062,394** dates and C04 found **0** amounts that failed to cast.

**Consequence.** This assumption (A17) is the one that breaks first if the
dataset is ever extended past 1999. The fix is one function, and the rule that
would catch the breakage already exists.

---

## D016 - Gender and birth date are derived from `birth_number`, and labelled as derived

**Context.** The source has no gender column and no birth date. It has
`birth_number`, a Czech national identifier that packs both: `YYMMDD`, with 50
added to the month for women.

**Options.** (a) Publish `birth_number` and let consumers decode it.
(b) Decode it into `birth_date` and `gender` and drop the original.
(c) Decode it, keep the original, and publish a validity flag beside both.

**Choice.** (c).

**Reason.** Leaving it packed means every age question re-implements the
decoding, and an LLM writing that arithmetic from a context pack will get the
month offset wrong. Dropping the original removes the only evidence the
decoding was right. C07 decoded **5,369** birth dates and C08 derived
**5,369** genders, with `birth_number_valid` true for all of them -- so the
derivation is complete on this extract, which is worth knowing precisely
because it will not be true of the next one.

**Consequence.** Gender here is an inference from an identifier format, not a
self-reported attribute, and the ledger and A18 both say so. Any analysis that
groups by it inherits that caveat. It is also personal data derived from
personal data, which is a question a real deployment has to answer before it
publishes the column; this submission publishes it because the ten questions
need age, and records the concern rather than pretending it does not exist.

---

## D017 - Codes are decoded to labels from one map, and the code is kept beside the label

**Context.** Five tables carry Czech codes: `POPLATEK MESICNE`, `VYDAJ`,
`PREVOD NA UCET`, `SIPO`, loan status `A`/`B`/`C`/`D`. An LLM asked about
"withdrawals" cannot be expected to know `VYDAJ`.

**Options.** (a) Publish codes only. (b) Replace codes with labels.
(c) Publish both, from one map, and fail the build if the data holds a code the
map does not know.

**Choice.** (c). The map lives in `src/config.py`, is published as
`core.ref_codes`, and `build_model.check_codes_against_staging` compares the
catalogue against every coded column.

**Reason.** Codes only, and the semantic layer has to carry a glossary the
model may ignore. Labels only, and the join back to the source is gone. Both,
from one place, and the redundancy becomes a test: if the inline label in
staging disagrees with the catalogue, the build stops. C09 labelled
**2,466,175** coded values against **28** published codes.

**Consequence, and the one this decision was actually written for.** The check
is only as good as its list of columns, and the first build's list had
`stg.trans.k_symbol_code` in it but not `stg."order".k_symbol_code`. The code
`LEASING` therefore sat on **341** standing orders with no English label
through the entire first submission. Nothing failed: the profiler reported the
code in `dq/results/profile.md`, and the only rule that noticed was the
null-label completeness sweep, which reads as "this column is often empty"
rather than "a cleaning step did not happen".

The fix is three lines and the lesson is bigger than they are: a cleaning
guarantee that is enforced per column has to be enumerated per column, and an
enumeration maintained by hand will miss one. `LEASING` is now in the map,
`stg."order"` is in the catalogue check, `VAL_ORDER_KSYMBOL_DOMAIN` reports
unknown order categories the way its transaction twin always did, and
`tests/test_dq.py` now asserts both that no staged row carries a code without a
label and that every coded column appears in the catalogue check -- so the next
coded column cannot be added without being covered.

---

## D018 - The sign of a transaction is resolved once, in staging

**Context.** `trans.amount` is unsigned. Direction lives in a separate Czech
code: `PRIJEM` increases the balance, `VYDAJ` and `VYBER` decrease it. Two
different words mean "outgoing".

**Options.** (a) Publish amount and type, and let each query apply the sign.
(b) Publish a `direction` label and let each query apply the sign.
(c) Publish `signed_amount` computed once, with amount and type kept beside it.

**Choice.** (c).

**Reason.** This is the single most valuable cleaning step in the build for
AI-readiness, and it is worth being plain about why. Every "net flow", "total
out", "largest withdrawal" question turns on a `CASE` over two Czech words. A
query that gets it wrong does not fail -- it returns a confident, plausible,
wrong number, and the most likely way for that to happen is an LLM that saw
`VYDAJ` in a context pack and did not see `VYBER`. Resolving it once in the
data removes the failure mode rather than guarding against it. C10 signed
**1,056,320** postings.

**Consequence.** One derived column on the largest table, and three columns
that can in principle disagree. `VAL_TRANS_AMOUNT_NEGATIVE` and the balance
reconciliation rules are what keep them honest. This is also the clearest
example of the general point: the way to stop a generated query being wrong is
to make the right answer the easy one to write, not to inspect the query
afterwards.

---

## D019 - A month-end balance is derived, with the tie-break written down

**Context.** Q9 asks for a closing balance. The source has no month-end
balance; it has postings with a running `balance_after`. Worse,
`trans_id` is not chronological within a day, so "the last posting of the
month" is genuinely ambiguous for **183** accounts
(`CON_INTRADAY_ORDER_AMBIGUOUS`).

**Options.** (a) Make the consumer derive it per query. (b) Derive it and
leave months with no activity missing. (c) Derive it, fill the gaps by carrying
the last known balance forward, and mark the carried rows.

**Choice.** (c): latest `trans_date` in the month, ties broken by highest
`trans_id`, gaps carried forward with `is_carried_forward` and
`balance_as_of_month_end` exposed.

**Reason.** (a) guarantees two answers to the same question. (b) makes "average
closing balance" silently exclude quiet accounts, which biases it upward. (c)
costs one pre-computed table and makes the ambiguity visible rather than
arbitrary: C20 shows **558** month ends inherited from an earlier posting, each
marked as such.

**Consequence.** The tie-break is a choice, not a fact, and for those 183
accounts a different tie-break gives a different number. That is stated in the
semantic layer as a caveat so it reaches the answer, and it is the reason the
rule is `warn` rather than `info`.

---

## D020 - Cleaning is graded, not gated: nothing is filtered before the rules run

**Context.** The staging layer could reject bad rows as it types them -- it is
the natural place to put a filter, and it would make `core` cleaner.

**Options.** (a) Filter in staging as part of the cast. (b) Filter nowhere, and
publish everything. (c) Stage everything, grade it in a separate layer, and let
the grade decide what reaches the product.

**Choice.** (c). `sql/10_stg.sql` states it as a contract: *nothing is filtered
out here*.

**Reason.** A rule layer cannot report on rows it cannot see. If staging drops
the duplicate transaction, the uniqueness rule has nothing to count and the
defect report says the data is clean. Separating the two means the quality
report describes the source rather than describing what survived the loader --
which is the difference between a data quality report and a data quality
anecdote.

**Consequence.** `stg` is the larger of the two layers and holds rows that will
never be published. That is the intended cost, and it is also what makes C21's
reconciliation meaningful: `core` = `stg` - quarantine is checkable precisely
because `stg` kept everything.

---

# Privacy at client grain (D021-D022)

---

## D021 - A self-service customer is a principal that IS one client, not one that HOLDS a book

**Context.** The brief words Task 3 as "each user sees only rows for their own
clients", which describes a relationship manager with a book. The sharper
question underneath it is whether one bank customer can see another's data.
Those are two different grains of principal and the model had only the first.

**Options.** (a) Give each customer a portfolio containing exactly themselves,
so nothing in the model changes at all. (b) Add `subject_client_id` to
`sec.app_user` and resolve it in `sec.v_my_clients` alongside the portfolio
path. (c) Keep identity out of the database and filter per customer in an
application layer above it.

**Choice.** (b).

**Reason.** (c) is the option this project already rejected for relationship
managers (D009) and it is worse here, not better: a self-service surface is
the one most likely to face the open internet, so it is the last place the
filter should live in application code. (a) is genuinely tempting -- zero
schema change -- but it models a customer as a degenerate book, which means
5,369 portfolios of one row each, an administrative surface where a customer's
"book" could be edited to contain somebody else, and a `portfolio_client` table
whose rows mean two different things. (b) says what is true: this principal is
that client. The cost is one column, one `UNION` and one check constraint.

**Consequence, and the claim worth testing.** The seven row level security
policies did not change, and neither did any consumer view. The policies ask
`sec.v_my_clients` which clients the caller may see; for a customer the answer
is one row, and no policy needs to know that customer logins exist.
`tests/test_rls.py::test_the_client_grain_added_no_policy` pins both the policy
count and the fact that no policy mentions `subject_client_id`.

The check constraint is not decoration. Without it, setting
`subject_client_id` on a staff user would quietly add a client to their
entitlement that no portfolio ever granted, and nothing else in the model would
notice -- the `UNION` would simply return one more row. It is the kind of
privilege gain that passes code review because it looks like a data fix.

**What it costs.** Two kinds of row in one table, which is a modelling
compromise: `user_type` plus a nullable column is weaker than two tables with a
shared supertype. At this size the constraint carries it. If a third kind of
principal appears (a service account, an auditor with read-everything-but-log
semantics), the table should be split rather than given a third flavour.

---

## D022 - The customer's view is narrowed to ownership, matching the manager's (superseded by D023)

> **Superseded by D023** (a customer also sees the accounts they may operate) and
> D024 (a disposition grants the account, never the person). Kept as history.

**Context.** `sec.v_my_accounts` resolves accounts from entitled clients
`WHERE is_owner` (A21). For a relationship manager that is right: their book is
defined by who they are accountable for. For a self-service customer it is a
real choice, because 869 clients hold a *disponent* relationship -- they may
operate an account they do not own.

**Options.** (a) Ownership only, identical to the staff rule. (b) Ownership
plus disponent, so a customer sees every account they can actually operate.

**Choice.** (a), for now, and deliberately.

**Reason.** (b) is arguably the better product: in a real bank, an account you
are authorised to transact on appears in your app. But it means the two grains
of principal resolve accounts by *different* rules, and a reviewer asking "why
does a customer see more kinds of account than their manager" deserves a better
answer than "it seemed friendlier". Narrower is also the safer default for a
privacy boundary: the failure mode of (a) is a customer who cannot see
something they should, which is a support ticket; the failure mode of (b), if
the disponent join is ever wrong, is a customer seeing an account that is not
theirs.

**Consequence.** It is one predicate in one view, not a design change, and the
rule to change is named here so the change is a decision rather than a patch.
Any real deployment should make this call with the business before launch,
because the two readings are both defensible and only one matches what the
bank tells its customers their app will show.

---

# Identity, access and authentication (D023-D027)

---

## D023 - A customer sees the accounts they may operate, not only those they own

**Context.** D022 narrowed a self-service customer to accounts they own,
consistent with the staff rule (A21/A36), and recorded that the alternative
should be settled with the business. It has been: a customer sees what they
are authorised to use.

**Options.** (a) Ownership only, as before. (b) Ownership plus disposition.

**Choice.** (b).

**Reason.** It is what the bank tells its customers their app will show, and
the narrow reading produces a support ticket every time somebody cannot see an
account they transact on daily. The safety argument for (a) was real but it is
answered by *where* the right is granted rather than by withholding it -- see
D024.

**Consequence.** 869 clients hold a disposition on an account they do not own.
In the demo, client 3764 reaches account 3112 and its 439 postings; before this
change he reached nothing at all.

---

## D024 - A disposition grants the account, never the person

**Context.** Having decided a disponent sees the account, the question is what
else comes with it. The entitlement chain elsewhere runs client -> accounts, so
the lazy implementation would grant the client and let the accounts follow.

**Options.** (a) Grant the owning client, and let their accounts resolve.
(b) Grant that one account, and nothing else.

**Choice.** (b), and it is the most important line in the access model.

**Reason.** (a) would mean that authorising someone to pay a bill from your
account lets them read *you*: your other accounts, your loans, your date of
birth. That is not what the arrangement means, and nobody signing it would
expect it. The right is over the account, so the grant is over the account.

**Consequence.** `sec.v_access_grant` carries `subject_kind` so a grant can be
either shape, and disposition grants are always `account`. Proven by
`test_a_disponent_reaches_the_account_but_not_its_owner`: client 3764 reads
account 3112 and its transactions, and gets zero rows for client 3763.

---

## D025 - Three names for a client, with different exposure

**Context.** `client_id` is a dense sequential integer and was the only name
the product had. Row level security already stops one customer reading
another's rows, so exposing it is not a breach -- but it is guessable, it
leaks the size of the book, and it is a stable handle for correlation.

**Options.** (a) Keep `client_id` as the only identifier and rely on the
policies. (b) Replace it with an opaque reference. (c) Keep the integer
internally and add an opaque external reference, plus a recognisable account
number.

**Choice.** (c): `client_id` for joins, `client_ref` (`BRK-XXXX-XXXX`, HMAC
under a secret salt) to quote, `account_ref` (IBAN with real mod-97 check
digits, fictional bank code) for the number a customer recognises.

**Reason.** (a) leaves an enumeration surface that costs nothing to remove:
every guess is an access attempt the system must refuse rather than one never
made. (b) would make every join and every policy predicate longer and slower
for no gain, because the internal key is never exposed anyway. (c) separates
the identifier used for plumbing from the identifier used for people, and the
semantic layer tells the model which is which.

**Consequence.** The salt is set only on the owner's session, so a consumer
cannot derive another client's reference from an id. A rebuild under a
different salt reissues every reference, which is the intended behaviour if
one is believed to have leaked. The IBAN check digits are genuine, so a typo
in a demo fails the way a typo in production would.

---

## D026 - The second factor is enforced by the database, not by an application

**Context.** The brief asks for entitlement-aware access; a self-service
customer surface raises the next question, which is how the system knows the
person at the other end is who the role says they are.

**Options.** (a) Authenticate in an application gateway and let it open a
trusted connection. (b) Record that two-factor authentication "would be
required" and demonstrate the entitlements only. (c) Enforce it in the
database: no verified session, no rows.

**Choice.** (c).

**Reason.** (a) is where most real systems put it, and it is a defensible
production architecture -- but it makes the control a property of the
application rather than of the data, which is the same mistake this project
rejected for entitlements in D009. (b) is a diagram, not a control. (c) makes
the claim testable in the only way that means anything: hold the correct
password, present no second factor, and read nothing. That is asserted for all
eight principals across seven consumer views in `tests/test_auth.py`.

**Reason for the shape, which is the subtle part.** Identity still comes from
`session_user`, which no statement can forge. The session token is a *second*
thing, and a bearer secret, so it is bound to `pg_backend_pid()`: a copied
token is useless on another connection, and one user completing a login does
not authorise every other connection open as the same role. The session check
is ANDed over the whole of `sec.v_my_clients` rather than inside one branch,
so a branch added later cannot quietly skip it.

**Consequence.** Every consumer path now logs in -- the question runner, the
workbook, the worked example and the tests. That is more machinery than a
demo strictly needs, and it is the price of the control being real rather than
described. It also costs wall-clock time: a code may be used once, so two
logins as the same principal inside thirty seconds wait for the next code.
Weakening that to make a script faster would be removing the control in order
to demonstrate it.

---

## D027 - Derive the grant set; store only what a human decided

**Context.** The first implementation of `sec.access_grant` was a table,
rebuilt on each pipeline run from the banking records and the portfolios.

**Options.** (a) Keep the materialised table and rebuild it. (b) Derive the
derivable sources live in a view, and store only delegations.

**Choice.** (b), after (a) failed a test.

**Reason, which is the useful part.** The materialised version broke a
headline claim and did so silently. Granting a portfolio inserted a row in
`sec.user_portfolio` and no matching grant, so the new entitlement did
*nothing* until the next rebuild -- while the entitlement tables said it
should. That is precisely the failure a single access model is supposed to
remove: two descriptions of who may see what, drifting apart between runs.
`test_onboarding_a_user_and_a_portfolio_is_pure_insert` caught it, which is
the argument for having written that test as an assertion about behaviour
rather than about rows.

**Consequence.** Ownership, disposition and portfolio rights are computed from
the records that already define them, so there is nothing to keep in step.
`sec.access_delegation` stores the one source a human chooses, and demands a
grantor, a reason and usually an expiry -- because it is the only source that
can be wrong in a way the banking records cannot reveal.
