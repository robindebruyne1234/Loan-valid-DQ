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
