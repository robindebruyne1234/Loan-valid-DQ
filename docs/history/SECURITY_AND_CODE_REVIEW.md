# Security review and code review

> **Historical record** -- the security and code review, kept for traceability. Its figures, file paths and open items are as of when it was written and are **not** maintained. The current state, with evidence, is [`docs/DELIVERY_AUDIT.md`](../DELIVERY_AUDIT.md); current decisions are [`DECISIONS.md`](../../DECISIONS.md).

Run at the end of the build. Both were done by reading the code and **testing
it against the running database**, not by reasoning about it.

**A note on method.** The review skills collect a diff against `origin/HEAD`.
Every commit here is on one branch with no base, so that diff was empty and
the skills had nothing to work with. The review below therefore targets the
security-critical files directly. It was done inline rather than by spawning
sub-agents, per the instruction that no agents be tokenized.

---

## Part 1 — Security review

Scope: `sql/50_sec_rls.sql`, `sql/40_ai_views.sql`, `src/sql_guard.py`,
`src/build_security.py`, `src/llm_client.py`, `src/run_questions.py`,
`src/db.py`, `src/config.py`, `scripts/db_up.sh`.

### Result: no HIGH or MEDIUM exploitable findings. Three LOW items.

That is a claim, so here is the evidence behind it.

### What was tested, not assumed

**20 attempts to get past the SQL bouncer.** Each was written as something a
model could plausibly emit, then run through `sql_guard.guard()`:

| Attempt | Outcome |
|---|---|
| `SELECT pg_catalog.pg_sleep(1)` — schema-qualified forbidden function | rejected |
| `... WHERE pg_sleep(1) IS NULL` — forbidden function buried in an expression | rejected |
| `SELECT pg_read_file('/etc/passwd')` | rejected |
| `SELECT * FROM ONLY core.fact_loan` — ONLY modifier | rejected |
| `SELECT * FROM ai.client, pg_tables` — cross join to a catalogue | rejected |
| `SELECT * FROM information_schema.tables` | rejected |
| `SELECT 1 FROM ai.client UNION SELECT 1 FROM stg.trans` — forbidden schema in one branch | rejected |
| `SELECT * FROM ai.client c, LATERAL (SELECT 1 FROM raw.trans) z` | rejected |
| `DO $$ ... $$` — dollar-quoted block | rejected |
| `COPY ai.client TO PROGRAM 'cat'` | rejected |
| `SELECT pg_sleep((SELECT 1 FROM ai.client LIMIT 1))` — nested in an argument | rejected |
| `VALUES (1),(2)` / `TABLE ai.client` — non-SELECT statement forms | rejected |

**Then the ones that got through, tested against the real database** as the
restricted role `rm_north`:

| Got past the bouncer | What PostgreSQL did |
|---|---|
| `SELECT pg_ls_waldir()` | **permission denied for function** |
| `SELECT pg_ls_logdir()` | **permission denied for function** |
| `SELECT current_setting('data_directory')` | **permission denied to examine** |
| `SELECT pg_stat_get_activity(NULL)` | ran, but its columns cannot even be named by this role, and other sessions' queries are masked |
| `SELECT version()`, `generate_series(1,3)` | ran; harmless |

This is the design working as intended, and it is worth stating plainly: **the
bouncer is not the security boundary.** The boundary is that the consumer is an
unprivileged database role. Everything dangerous that slipped past the first
control was stopped by the second.

### LOW-1 — The guard's function list is a blocklist, not an allowlist

`src/sql_guard.py`, `FORBIDDEN_FUNCTIONS`. Unlisted functions pass, as
`pg_ls_waldir()` did.

*Impact:* none demonstrated. Every dangerous function tested was refused by
PostgreSQL for the consumer role. A blocklist is nevertheless the weaker
shape, because it has to anticipate.

*Recommendation:* invert it to an allowlist of the aggregate, date and string
functions the semantic layer actually advertises. Not urgent while the role
stays unprivileged; worth doing before the role is ever widened.

### LOW-2 — A set-returning function in `FROM` is not schema-checked

`SELECT * FROM generate_series(1,3)` is allowed, because the schema rule
applies to tables and this parses as a function call.

*Impact:* none found. The data-reading functions that would matter here
(`pg_ls_dir`, `pg_read_file`, `pg_stat_file`) are already blocked by name, and
the privilege check stops the rest.

*Recommendation:* fold into LOW-1 — an allowlist covers both.

### LOW-3 — Hardcoded default credentials, and a predictable working directory

`src/config.py:72,80` default to `berka_owner_pw` and `demo_pw` when the
environment does not override them. `src/llm_client.py:99` uses a fixed
`/tmp/berka_llm_sandbox` as the model's working directory, created with
`exist_ok=True`.

*Impact:* both are local-only and scoped to a take-home that runs against a
throwaway database. The passwords are overridable by environment variable and
the role they protect exists only on a local cluster. The fixed temp path is a
standard symlink/plant concern on a shared machine.

*Recommendation:* for anything beyond this exercise, require the passwords from
the environment with no default and fail loudly if absent, and create the
sandbox with `tempfile.mkdtemp()`. Flagged despite being out of scope because
"what would this take to deploy" is a fair question from a bank.

### What was checked and found clean

- **SQL injection.** Every dynamic statement either uses psycopg parameters or
  `psycopg.sql` composition. The handful of f-string identifier interpolations
  (`db.qualified`, the quarantine snapshot, the reconciliation query) take
  their values from internal constant dictionaries, never from input.
  `create_login_role` composes with `Identifier`/`Literal` because `CREATE ROLE`
  takes no bind parameters.
- **Command injection.** The only subprocess calls are the model CLI and
  LibreOffice, both with argument lists and no shell.
- **The entitlement model.** Policies sit on the base tables; the serving views
  are `security_invoker`; identity comes from the authenticated role, not a
  session variable. Nine bypass attempts in `tests/test_rls.py` all fail,
  including querying the base tables directly, which is still filtered.
- **Deserialization.** YAML is loaded with `safe_load` throughout. No pickle,
  no `eval`.
- **Model output handling.** The model's JSON is parsed by brace matching and
  `json.loads`; its SQL is parsed before execution and never interpolated.

---

## Part 2 — Code review

### Two real defects found, both fixed. Both are checks that could not fail.

### FIXED-1 — The idempotence check was tautological

`packages/berka_bronze/src/berka_bronze/agent.py`

```python
payload["digest"] = self._digest(payload)
payload["second_run_digest"] = payload["digest"]   # <- the same value
```

The acceptance criterion *"landing twice produces the same digest"* compared a
value with itself. It could never fail, and it was presented as evidence that
the Bronze layer is idempotent.

A check that cannot fail is worse than no check, because it reads as coverage.

*Fixed:* the sources are now landed a second time independently via a
`_land()` method and the two digests compared. The check still passes — the
layer really is idempotent — but now it could tell us if it stopped being so.

### FIXED-2 — The evaluator's tolerance was 11,513 CZK wide

`src/evaluate.py`

The comparison used a **relative** tolerance of 1e-4. On Q5's largest value —
Prague's 115,130,200.10 CZK of incoming payments — that accepts an answer wrong
by **11,513 CZK** and reports it as a match.

The tolerance exists for one reason only: the reference answers round to two
decimals and a model's answer may not, so 43808.9388 must match 43808.94. That
needs an *absolute* half-cent, not a proportional slack.

*Fixed:* `ABSOLUTE_TOLERANCE = 0.011`, relative term dropped to 1e-9 for
floating-point representation only. **All ten questions still match**, which is
the useful part: the model's answers were genuinely exact, not merely inside a
generous band. Two regression tests pin it — one injects a 1,000 CZK error on
Q5 and asserts it is now caught, one asserts two-decimal rounding still passes.

### Known limits, accepted and already documented

Not re-raised as findings because the Design Decision Record already names
them: `dq_runner` materialises every violating row in Python before sampling
(fine at 1.06 m rows, named as one of the four things that break at 100,000x);
four modules exceed 500 lines; the DDR page count is checked by regexing PDF
bytes; there is no CI.

### Smaller observations, not fixed

- `run_questions.parse_model_output` finds the JSON object by counting braces,
  which would mis-cut if a brace appeared inside a SQL string literal. Has not
  happened in 20 logged calls; a real JSON scanner would be sturdier.
- `make_zip.MANIFEST_TEMPLATE` is rendered with `str.format`, so adding a
  literal `{` to the manifest text would break the build. Harmless today,
  surprising later.

---

## Verification after the fixes

```
137 tests passing   (135 before, plus the two tolerance regressions)
10 of 10 questions still match, under the tightened comparison
simulation: all layers pass scope, contract and acceptance
all four injected faults still caught
```
