# <span class="num">1</span>The brief, and the way of working {#brief}

<p class="lede">What was asked, what was handed in for each part of it, and the working rules
that explain most of the design choices before anyone asks.</p>

## What the brief asked for {#asked}

The brief ("The Governed Data Product for AI") has three tasks on the public Berka (PKDD'99)
Czech bank dataset and ten business questions in `questions.csv`.

| Task | The brief's words | What was delivered | Where |
|---|---|---|---|
| **1. Data quality and reconciliation** | Rules for at least completeness, uniqueness, referential integrity, validity and cross-table consistency; defect types with the rule broken and a severity (block / warn / info); *justify the severity* | 124 rules in six dimensions (the five plus reconciliation), every one with a severity rationale written in terms of the questions; 14 defect types | Workbook tabs *Defect types* and *DQ rules*; `dq/dq_rules.yaml`; `dq/results/dq_report.md` |
| **2. AI-ready data product with a semantic layer** | A data model on the cleaned data; a semantic solution to guide an AI; use an LLM with it to answer the 10 questions; submit generated SQL and result per question | Star schema in `core`; curated `ai` views; validated YAML semantic layer rendered to a context pack; Claude's SQL and results, evaluated against reference SQL | Workbook tabs *Model*, *Questions*, *Q detail*; `deliverables/model_explanation.md`; ZIP |
| **3. Entitlement-aware access** | *Explain* how each user sees only their own clients; where the filter sits; why an LLM query cannot bypass it; onboarding without code changes | Implemented, not only explained: row level security on the base tables, identity from `session_user`, two-factor login, grants derived from data, bypass tests | Workbook tab *Entitlements*; `docs/ACCESS_AND_AUTH.md`; DDR §6 |

The deliverables table asks for Excel tabs for defects, model explanation and questions; the
semantic solution and code as a ZIP; and a **Design Decision Record of at most two pages**
covering options considered, choice, why, cost, and *what breaks at 100,000× the data
volume*. Expected effort: **1–2 days**. Return within 7 days. Any LLM or AI coding assistant
is allowed, with full disclosure. One sentence in the brief matters for the walkthrough:
*"If you spend most of your time on infrastructure or tooling setup, you have misread the
brief."*

:::weak The scope question you will almost certainly get
The repository goes well beyond 1–2 days: a two-factor login in the database, a web
walkthrough, a deployment guide, a 55-slide deck, simulated layer agents. Do not deny it and
do not apologise for it. The honest answer has three parts: (1) the three tasks were built
and evaluated first; (2) the extras were added on explicit request and each one demonstrates
a governance point rather than infrastructure (the second factor is enforced where the data
is; onboarding is a data change); (3) the stack itself stayed minimal — one database, SQL
files, plain Python, a Makefile — exactly so that the time went into the data, not tooling.
If asked what you would cut: the deployment guide and the simulated agents first, then the
web page (keep the console demo).
:::

## The way of working, as nine rules {#rules}

These rules are the shortest honest answer to "how did you work?". Most design decisions
follow from one of them.

1. **Executed, not asserted.** Every number in a deliverable is produced by a command whose
   run is logged (`dq/results/run_log.jsonl` → `STATUS_REPORT.md`). Claims carry a label:
   RUN, CODE, LLM, REC, ASSUMED. A step that did not run is printed `NOT EXECUTED`, never
   filled in.
2. **Land verbatim, never repair.** Bronze keeps the files as text with a SHA-256 per file.
   Silver converts, but every changed value keeps its original in a `_raw` column and a
   conversion note (D013, D014). A repaired value is indistinguishable from an observed one a
   week later.
3. **Grade, do not gate.** Staging filters nothing (D020). The rule layer decides afterwards,
   so the quality report describes the source, not what survived the loader.
4. **A severity must have a consequence.** `block` quarantines, `warn` flags and the flag
   travels to the answer, `info` logs. A severity without a mechanical effect is a comment.
5. **One definition, in one place.** "Problematic loan", "account owner", "incoming",
   "month-end balance" are decided once in the model and once in the semantic layer, and the
   duplication that remains is checked by the build (D006, D017).
6. **Distrust your own build.** The model is verified after every build (keys, grains,
   foreign keys, `core = stg − quarantine` on rows and money). Rules are proven by seeding 20
   defects into a separate schema (D004). Security is tested by logging in as the restricted
   user and counting rows, not by reading the DDL (D010).
7. **The LLM is an untrusted query author.** It sees the semantic layer and the question,
   nothing else; its output is parsed and bounded; the filter sits where its text cannot reach
   (D009, D011).
8. **Evidence is kept apart.** Reference SQL and model output are never mixed; a second
   provider's run goes to separate files and never overwrites the recorded one.
9. **Write the decision down with its cost.** Every decision record has options, choice,
   reason and cost; every interpretation is an assumption with "what changes if wrong".
   Superseded decisions stay, marked (A36 → A39, D022 → D023).

:::say The one-line version
"I built it so that every number can be traced to a command that produced it, nothing is
silently repaired or dropped, and the AI is never trusted with anything it could get wrong
quietly."
:::

## How AI tools were used {#ai-use}

Full disclosure is a requirement of the brief, and the disclosure is in `AI_DISCLOSURE.md`.
Be precise about three different roles:

| Role | Tool | What it did |
|---|---|---|
| Builder | Claude Code (Claude Opus 5, later Opus 5.5 and Sonnet 5.5), interactive, under your direction | Wrote the repository: pipeline, SQL, rules, semantic layer, tests, documents — every step executed and checked against the database |
| **LLM under test** | Claude CLI non-interactive, **Claude Sonnet 5.5** (`claude-sonnet-5-5`) | Generated the SQL for the ten questions from the context pack only: no tools, no MCP, no filesystem, no database, working directory outside the repository, `num_turns: 1` |
| Second LLM under test | Ollama, `qwen2.5-coder:3b`, local on the laptop CPU | Same questions through the same guard and login; results kept in `dq/results/local/` |

:::weak "Hand written" reference SQL
`AI_DISCLOSURE.md` labels `sql/60_reference_queries.sql` "Hand written", and two documents
say "a person worked out all ten answers by hand". The accurate statement is narrower: the
reference SQL was **not generated by the model under test**; it was written in the same
AI-assisted build session, independently of the evaluated run, and every reference answer
was later **re-derived from the raw text tables with independent SQL** and matched exactly.
Say it that way before anyone else does. (Lessons Learned, L-12.)
:::

## Why this stack {#stack}

| Choice | Alternatives | Why | Cost |
|---|---|---|---|
| **PostgreSQL** (16 on Linux/Docker, 18.6 on native Windows; identical DDL) | Cloud warehouse + dbt + orchestrator; DuckDB; SQLite | Task 3 is about *enforcement*. The only honest proof that a generated query cannot bypass a filter is to put the filter in the engine and connect as a restricted user. DuckDB has no row level security, so Task 3 would have become prose (D002, DDR §1) | Single node, no built-in lineage or scheduler; fine at this volume |
| **Numbered SQL files + plain Python + Makefile** (`scripts\windows.ps1` on Windows) | dbt, Airflow, Dagster | The brief warns against tooling; ordered SQL is readable in a review and each step is one command | Hand-rolled orchestration and checks |
| **sqlglot** for the SQL guard | Regular expressions; no guard | A parser counts and types statements; `SELECT/**/1; DROP TABLE x` is two statements to a parser and one line to a regex | A parser dependency; some legitimate SQL is refused (tables must be schema-qualified) |
| **Claude CLI as a sandboxed completion** (D005) | Anthropic API; local model only; an agent with database access | The exercise tests the *semantic layer*: an agent that could read tables would answer by looking. One interface (`src/llm_client.py`) keeps all providers swappable by one variable | A subprocess wrapper and a CLI dependency |
| **Natural keys** (D007) | Surrogate keys | One source, one extract, no history: surrogates would buy a join per dimension and longer LLM-written SQL | Revisit with history (SCD2) |
