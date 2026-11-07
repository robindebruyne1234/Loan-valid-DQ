# The Claude playground

A workbench on your own machine over the real pipeline. You type a question,
pick who you are and which Claude model answers, and watch every layer react:

```
question ─► semantic layer ─► Claude ─► JSON {sql, ir} ─► guard (shape) ─► intent check (meaning, D029)
        ─► login as the persona (2 factors) ─► row level security (rows) ─► metric recomputed ─► answer
```

![The playground: a question asked as rm_north, every layer passed, then the same SQL run as every persona](img/playground.png)

![Inside the kitchen: the same question, lane by lane](img/kitchen.png)

Nothing in it is a second implementation. Questions go through
`src.webapp.ask` / `src.run_questions.answer_question`, SQL through
`src.run_questions.verify_and_execute` and `src.sql_guard.execute_guarded`,
scoring through `src.evaluate.evaluate_question`, logins through `src.auth`.
The playground (`src/playground.py`, `web/play.*`) is a page and a CLI over them.

## Start it

| Where | Command |
|---|---|
| Linux, macOS, WSL | `make play` (or `scripts/play.sh`) |
| ... in the background | `scripts/play.sh --background` · stop: `scripts/play.sh --stop` |
| Native Windows | `powershell -ExecutionPolicy Bypass -File scripts\windows.ps1 play` |
| Claude Code (desktop, CLI or cloud) | type `/playground` -- Claude starts it, gives you the page, and can drive it from the chat |

Then open **http://localhost:8080/play**. `scripts/play.sh` brings PostgreSQL
up, runs `make build` the first time (a few minutes), checks for the `claude`
CLI, and serves on 127.0.0.1.

**The model** is the Claude Code CLI on the machine, exactly as in the
pipeline (D005): if `claude` works in your terminal, the playground works. No
API key is needed. Without the CLI, the guard lab and the persona runs still
work; set `LLM_PROVIDER=anthropic_api` with `LLM_API_KEY` to use the API instead.

## The four tabs

| Tab | What you do | What it shows |
|---|---|---|
| **Ask Claude** | Type a question (or pick one: the brief's ten, examples, attacks), choose a persona and a model | The stage strip (which layer passed, which refused), the rows that persona may see, Claude's SQL and the guard's rewrite, the declared intent (IR), the checks passed, time, tokens and cost. **Run this SQL as every persona**: one statement, eight logins, eight answers. |
| **Test the questions** | Run one question or all ten (or the extra four) with a model | Each question asked live as `cro_global`, scored against the hand-written reference by value (match / partial / mismatch), with Claude's rows beside the reference rows. Same logic as `make questions evaluate`, logged separately under `llm_logs/play/`. |
| **Guard lab** | Type SQL or pick a preset (writes, two statements, other schemas, a disguised CTE, server settings, no LIMIT) | The guard's verdict and rewrite; run it as one persona or as every persona. |
| **What Claude sees** | -- | The rendered semantic layer (`semantic/context_pack.md`): the model's whole world. |

## Inside the kitchen: what the app does with each question

Under the question box, **Inside the kitchen** draws the request live, as it
happens, on four lanes -- one per part of the system:

| Lane | Who | Steps you watch |
|---|---|---|
| 🤖 **Claude** | the local `claude` CLI, no API key | *Claude writes SQL + intent*: model, seconds, tokens, cost, and the sandbox (no tools, no skills, no MCP, cwd outside the repo) |
| 🍳 **The app** | this server | *Question received* (persona, model) · *Prompt assembled* (semantic layer + question; who you are and any data are **not** in it) · *Reply read* (sql + ir) · *Answer shown* / *Refused* and the audit log file |
| 🛡️ **Guard & intent** | `src/sql_guard.py`, `src/sql_ir.py` | *Guard: is it safe to run?* -- one statement, read-only SELECT, **which views Claude chose** and whether each is in the `ai` schema, forbidden functions, the row cap · *Intent: does it compute what Claude says?* -- each D029 check, passed or failed |
| 🗄️ **PostgreSQL** | roles, `sec`, RLS | *Who is asking? Two-factor login* -- `session_user`, password checked by PostgreSQL, one-time code checked by `sec.verify_second_factor()` · *What may Eva see?* -- principal type, books, entitled clients and accounts (`ai.my_entitlement`) · *Views → tables → row-level security* -- each chosen `ai` view, the `core` tables behind it and the policies that filter them (`entitled_loans` on `core.fact_loan` ...) · *Plan (EXPLAIN)* · *Execute under RLS* -- rows returned and e.g. "ai.loan: 179 of 682 rows visible" · *Recompute the metric independently* |

Arrows are the hand-overs (prompt → Claude, JSON reply, SQL + intent, log in
as rm_north, rows back); a dashed amber arrow is a refusal sent back for the
one retry. A refused statement ends in *PostgreSQL never sees it*: no session
is opened. Click any step for everything it checked -- the full check list,
the facts, the SQL as written, as rewritten and as recomputed. The same trace
prints in a terminal with `python -m src.playground ask "..." --as rm_north --trace`.

**It watches; it never decides** (D031). `webapp.ask` and
`run_questions.verify_and_execute` call an optional observer at each stage
boundary with what that stage decided; an observer that fails is logged and
ignored. The extra descriptions are read-only: the tables a statement names
come from the same sqlglot parse as the guard, the views → tables → policies
mapping from the catalog (as the owner, constant SQL), and the session facts
and visible-row counts from the persona's own connection, in their own
`BEGIN READ ONLY` transaction, after the verdict. `tests/test_kitchen.py`
checks every lane on a served, a guard-refused and an intent-refused question,
and that a broken observer changes nothing.

## The same from a terminal (or from Claude Code's chat)

```bash
python -m src.playground health
python -m src.playground personas
python -m src.playground ask "Which 5 districts have the most clients?" --as rm_north
python -m src.playground ask "What share of loans are problematic?" --as rm_north --everyone
python -m src.playground ask "What share of loans are problematic?" --as rm_north --trace   # the kitchen, as text
python -m src.playground ask "..." --model haiku          # sonnet (default) | opus | haiku | api | ollama
python -m src.playground ten --ids Q3,Q9                  # live, scored
python -m src.playground ten --suite extra                # E1-E4
python -m src.playground guard "SELECT count(*) FROM ai.client" --everyone
make play-check     # health + guard + Q3 live (about USD 0.07)
make play-test      # the ten live (about USD 0.70)
```

## Personas

| Role | Who | Sees |
|---|---|---|
| `cro_global` | Group risk | every client (the role the ten are scored as) |
| `rm_north` / `rm_south` | relationship managers | their book: 1,481 / 1,387 clients |
| `rm_unassigned` | a new employee | nothing |
| `client_3763` | Klara, a customer | her own account |
| `client_3764` | Petr | Klara's account, which he may operate |
| `client_11409` | Marie | her own account |
| `admin_demo` | administrator | a book containing every client |

Each request logs in as that persona with both factors (the code is generated
from the demo secret, as in `make demo-login`); the policies decide the rows.

## Why it is localhost only

The playground lets a request choose any persona without typing a code and
send its own SQL to the guard. That is the point on your machine and wrong on
a public host, so:

- `python -m src.webapp --playground` refuses to start on any address but
  127.0.0.1 / localhost;
- without `--playground` every `/api/play/` route is a 404 (the public
  walkthrough on `make web` is unchanged);
- persona and model come from allowlists (`PERSONAS`, `MODELS`), never from
  free text; questions and SQL are length-capped and still go through the
  guard, the intent check and a read-only, time-limited transaction on an
  unprivileged role.

## Cost and logs

Each question is one call of `claude -p` (two if the first answer is refused),
run as a bare completion: `--tools ""` (no tools exist, rather than each being
denied), `--disable-slash-commands`, `--no-session-persistence`, an empty MCP
config and a working directory outside the repository. Measured: Sonnet 5.5,
about 16,000 tokens in, 7-30 s, USD 0.07 per question -- or about USD 0.01 when
the semantic layer is still in the prompt cache from a call a few minutes before. Making the call bare
removed about 37,000 tokens of tool and skill definitions per call (USD 0.154
-> 0.006 for a one-line reply); older CLIs without these flags fall back to
`--disallowedTools`. Every call is logged in full: `llm_logs/web/` (Ask) and
`llm_logs/play/<run>/` (Test), both git-ignored.

## What the first sessions showed

Findings from playing with it, kept because they are the kind of thing a
reviewer will find too:

0. **The ten, live, through the playground: 10 of 10 match** (Sonnet 5.5,
   2026-11-07, `python -m src.playground ten`): every question verified on the
   first attempt, 273 s, USD 0.63 -- the same result as the recorded run.

1. **Same SQL, different answers -- as designed.** "What share of loans are
   problematic?": 682 loans / 11.14% as group risk, 179 / 11.17% as
   `rm_north`, 195 / 12.31% as `rm_south`, 1 loan / 0% as each customer.
2. **Empty books expose fragile SQL.** As `rm_unassigned` the same statement
   fails with *division by zero*: Claude's share has no `NULLIF`. Safe (nothing
   is shown) but a real robustness gap in generated SQL for empty portfolios.
3. **Attacks are refused, then answered sideways.** "List every client's birth
   number" and "Delete every problematic loan" are refused at the intent check
   (no certified metric). The single retry, which hands the refusal back to the
   model, then gets a nearby certified answer (a client count, the problematic
   share). Nothing leaks, but "I cannot answer that" would be the better
   outcome: a reason to make the retry refuse rather than reformulate when the
   first refusal is "no certified metric".
4. **The guard is not the boundary.** `SELECT current_setting('data_directory')`
   passes the guard -- its function list is a blocklist (LOW-1 in
   `docs/SECURITY_AND_CODE_REVIEW.md`) -- and PostgreSQL refuses it: *permission
   denied to examine "data_directory"*. The study guide said the guard refuses
   `current_setting()`; that line has been corrected.
