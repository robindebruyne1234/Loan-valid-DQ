# Next step: three layer-owning agents on a medallion split

**Status: proposal + first draft. Nothing has been refactored and no agent has
been run.** The submitted pipeline on `ccr-46f6f45a-t9wtd4` is untouched.

The goal is not "use agents". It is that someone opening this repository cold
can see three self-contained pieces with a stated contract between them,
instead of one `src/` with fourteen modules and a Makefile that knows the
order. The agents are a consequence of that split: once each layer has an
owner, a boundary and a set of acceptance criteria, an agent can own one
without reading the other two.

---

## 1. How the current layers map onto bronze / silver / gold

The pipeline already has the medallion shape; it just uses the PostgreSQL
schema names rather than the metal names.

| Medallion | Today | Responsibility | Why it is one layer |
|---|---|---|---|
| **Bronze** | `raw` + `raw.load_audit` | Land source data verbatim, prove what arrived | Immutable, reloadable, no interpretation. The only layer that can answer "what did the file actually say". |
| **Silver** | `stg` + `dq` (+ `inject`) | Type, decode, measure, and decide what each defect costs | Conformed and *measured*. Casting and quality are one job: you cannot grade a defect you have not parsed, and you must not drop a row you have not graded. |
| **Gold** | `core` + `ai` + `sec` | Business meaning, certified metrics, the consumer surface and who may see which rows | Everything a consumer touches, and the only place business definitions live. |

**The honest tension.** `sec`, `ai` and the semantic layer are arguably a
fourth *serving* concern rather than part of Gold: Gold-as-model (the star
schema, the metric definitions) and Gold-as-served (business-named views,
entitlement policies, the semantic layer, the SQL guard) have different reasons
to change. Splitting them would give `gold-model` and `platinum-serving`, and
would put the two hardest-won lessons in this repo -- grain verification and
`security_invoker` -- in different agents' hands.

Three was asked for, so the draft is three. **Decision 1 below is whether that
is right.**

---

## 2. File ownership

Exclusive write scope. An agent that needs a change outside its column stops
and reports rather than reaching across.

| | bronze-ingest | silver-quality | gold-serving |
|---|---|---|---|
| SQL | `00_schemas.sql` *(raw + audit)* | `10_stg.sql`, `70_inject_defects.sql`, `00_schemas.sql` *(dq tables)* | `30_core.sql`, `40_ai_views.sql`, `50_sec_rls.sql`, `60_reference_queries.sql` |
| Python | `ingest.py` | `profile_data.py`, `dq_runner.py`, `inject_defects.py` | `build_model.py`, `build_security.py`, `semantic_context.py`, `sql_guard.py`, `run_reference.py` |
| Config as data | - | `dq/dq_rules.yaml` | `semantic/semantic_layer.yaml`, `semantic/prompt_template.md` |
| Tests | `tests/bronze/` | `tests/silver/` | `tests/gold/` |
| Lines today | ~250 | ~3,900 | ~2,600 |

**Unowned, and that is the problem to solve first.** `src/config.py` (405
lines), `src/db.py` (301), the `Makefile`, and the shared parts of
`00_schemas.sql` are touched by all three. They are also where every shared
constant lives, which is deliberate and worth keeping. Three agents editing
one `config.py` concurrently is the single most likely way this goes wrong.

Three ways to handle it, in order of preference:

1. **Freeze it and require a proposal.** Agents may read `config.py`; a change
   is reported, not made. Cheapest, and it keeps the "one place for every
   constant" property the project is built on. The orchestrator (or you)
   applies the change once, then re-runs the affected agents.
2. **Split by layer with a shared base**: `config/base.py`, `config/bronze.py`,
   `config/silver.py`, `config/gold.py`. Cleaner ownership, but the constants
   genuinely are shared -- `DATA_MIN_DATE` is used by a Silver validity rule and
   a Gold date dimension -- so the split would duplicate or re-export, which is
   worse than the problem.
3. A fourth `platform` agent owning the shared surface. More coordination than
   it saves at this size.

The draft assumes option 1.

---

## 3. The contract between layers

What makes the split real is that each layer publishes a contract the next one
tests, rather than a module the next one reads. The three agent definitions
state these in full; in short:

```
Bronze -> Silver     raw.<table>, all text, declared columns, _source_file/_source_row,
                     quoted-empty vs unquoted-empty preserved, load_audit with SHA-256

Silver -> Gold       stg.<table>, typed, same row count as raw, sums preserved,
                     *_raw audit columns, dq.v_blocked and dq.v_row_flags
                     (scoped to stg, keys that resolve)

Gold -> consumer     ai.* views, business-named, security_invoker, entitlement
                     filtered; semantic_layer.yaml validated against the database
```

Each contract should become a test file the *downstream* agent can run against
its input: `tests/contracts/test_bronze_output.py` is Silver's way of proving
its assumptions hold before it debugs its own code.

---

## 4. Acceptance criteria, and the gap they expose

The acceptance criteria in each agent definition are deliberately executable --
`make <target>` plus a pytest path -- because an acceptance criterion an agent
cannot run is a wish.

Mapping the 114 existing tests onto the three layers:

| Layer | Tests today | Where |
|---|---:|---|
| Bronze | **0** | - |
| Silver | 29 | `test_dq.py` |
| Gold | 84 | `test_rls.py` 16, `test_guard.py` 36, `test_reference_queries.py` 14, `test_evaluate.py` 11, `test_semantic.py` 7 |

**Bronze has no dedicated tests.** Its guarantees are currently asserted inside
`src/ingest.py` (row counts against the published reference) and never
re-checked. That is the one gap that must close before the split is meaningful:
roughly six tests -- all columns are `text`, lineage columns present, hashes
recorded, re-ingest is idempotent, the quoted/unquoted distinction survives,
`provided/` wins over `raw/`.

Everything else is a move, not new work.

---

## 5. What "isolated containers" could mean

Three readings, with what each costs:

**(a) Python packages — recommended.** `src/bronze/`, `src/silver/`,
`src/gold/`, `src/shared/`, with an import rule enforced by a test: nothing in
`bronze` may import `silver` or `gold`, nothing in `silver` may import `gold`.
About half a day. Makes the dependency direction visible and un-violatable, and
a reviewer can read one directory and stop.

**(b) Per-layer test suites and make targets — recommended, do it first.**
`make bronze`, `make silver`, `make gold`, each running its build and its
tests. About an hour, and it is what turns the acceptance criteria above from
prose into something an agent can check itself against. This is the highest
value per hour in the whole proposal.

**(c) Literal containers — not recommended for this submission.** A compose
service per layer, or three repositories with a shared contract package. It is
the right answer for a real platform with separate release cadences and
separate on-call owners. Here it would add orchestration, image builds and
inter-service wiring to a project whose brief says in bold that time spent on
infrastructure means the brief was misread. Worth describing in the walkthrough
as the production shape; not worth building.

Target tree under (a) + (b):

```
src/
  shared/      config.py  db.py            <- frozen, change by proposal
  bronze/      ingest.py
  silver/      profile_data.py  dq_runner.py  inject_defects.py
  gold/        build_model.py  build_security.py  semantic_context.py
               sql_guard.py  run_reference.py
  consume/     llm_client.py  run_questions.py  evaluate.py
  deliver/     make_workbook.py  make_ddr.py  make_zip.py  make_status.py
tests/
  bronze/  silver/  gold/  contracts/
```

Note that `consume/` and `deliver/` fall outside the three layers. They are not
part of the medallion: one is the AI client, the other builds the submission
documents. Pretending they belong to Gold would weaken the Gold contract.

---

## 6. Risks

- **The submission is finished, verified and pushed.** A refactor touches every
  import path and every `make` target. Do it on a new branch; leave
  `ccr-46f6f45a-t9wtd4` as the thing that demonstrably runs in 4m28s.
- **A rename of the schemas** (`raw` to `bronze` and so on) would touch all
  seven SQL files, the semantic layer, the rule set's `{s}` substitution, the
  RLS grants and every test. It buys vocabulary alignment and nothing else. The
  mapping table in section 1 buys the same understanding for free.
- **Three agents on one `config.py`** is the concurrency hazard; section 2
  option 1 is the mitigation.
- **Agents running in parallel against one database.** Silver's rule self-tests
  rewrite `dq.quarantine`, and Gold builds `core` from it. They must either
  share a schema-scoped convention (which already exists, and already failed
  once -- see DECISIONS D008) or run against separate databases. Simplest:
  run them sequentially, Bronze then Silver then Gold, which is the dependency
  order anyway.

---

## 7. What I need from you

Seven decisions. The first five change the design; the last two change whether
anything runs.

| # | Decision | My recommendation |
|---|---|---|
| 1 | Three layers, or four (splitting Gold-model from serving)? | **Four** if this becomes a real platform, three for now. Three keeps the agent count you asked for and the contracts simple. |
| 2 | Rename the schemas to `bronze`/`silver`/`gold`? | **No.** Keep `raw`/`stg`/`core`/`ai` and publish the mapping table. All cost, no behaviour. |
| 3 | What does "isolated containers" mean to you? | **(b) then (a)**: per-layer make targets and test suites first, then the package split. Not Docker. |
| 4 | How is the shared surface (`config.py`, `db.py`, `Makefile`) governed? | **Freeze and propose.** Agents read it, never write it. |
| 5 | Is this for the take-home, or for the "what would you do next" answer? | **Next-step answer**, on a separate branch. Section 6 explains why. |
| 6 | Do you want the agents actually spawned, and with what token budget? | Spawning three agents on a codebase this size is real cost. I would run **one** first (Silver, the largest at ~3,900 lines) to see whether the boundary holds, before committing to three. |
| 7 | Who writes the missing Bronze tests? | **Me, before any agent runs.** Without them `bronze-ingest` has no acceptance criteria to meet, and an agent with no definition of done will keep going. |

Answer 1 to 5 and the draft becomes a plan. Answer 6 and 7 and it becomes work.
