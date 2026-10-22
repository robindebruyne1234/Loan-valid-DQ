# Next step: three layer-owning agents on a medallion split

**Status: decided, and simulated. No production code has been refactored and
no live agent has been run.** The submitted pipeline is untouched; the three
layers now also exist as isolated Python packages running against a control
dataset, so the structure can be judged before anything is migrated.

Decisions taken (sections 8 and 9 record the reasoning and what is left):

| | |
|---|---|
| Layers | **Three: bronze, silver, gold.** Sub-topics live inside a layer, not as a fourth. |
| Isolated containers | **Isolated Python packages**, so one layer -- or one intermediate step -- can be changed and verified alone. Not Docker. |
| Shared surface | **A control dataset**, frozen, changed only by proposal. |
| Execution | **Simulated.** The agents are not triggered; the harness runs them with dummy work so the boundary can be tested without a model in the loop. |

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

**Decided: three.** Gold holds model, serving and entitlement as sub-topics of
one layer rather than as separate layers. The consequence is accepted and worth
stating: `gold-serving` owns both the grain verification and the
`security_invoker` rule, which are the two failures this project actually hit.
That agent's definition therefore carries both explicitly, and its acceptance
criteria check both, because one owner with two known hazards needs them named
rather than assumed.

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

**Decided: the surface is a control dataset, frozen, changed by proposal.**

The move that makes this work is that the shared surface stopped being code. A
shared `config.py` is a module three agents are each tempted to edit; a control
dataset is data they read. `packages/berka_control/src/berka_control/control_dataset.yaml`
carries the shared constants, the ownership matrix, the import rules and the
contract each layer publishes -- and `ControlDataset` has no setter. An agent
reaching for one gets a `FrozenSurfaceError` whose message names the
alternative:

```
the control surface is frozen: 'shared_constants.balance_tolerance_czk' cannot
be set to 5.0 from a layer agent. Raise a proposal instead --
LayerAgent.propose(target, current, proposed, reason) -- and a human applies it
and bumps the surface version.
```

`make simulate` with `--scenario propose` runs that path end to end: Silver
tries the edit, is refused, raises `prop_xxxxxxxx`, finishes its work, and the
proposal is listed for a human. The run still passes -- being refused is not a
failure, it is the design.

The control dataset carries a second meaning that turned out to matter more
than the governance one. It is also a **control dataset in the experimental
sense**: a handful of rows with one planted defect per severity and the
known-correct answer at each layer. That is what makes a layer verifiable on
its own -- Silver is checked against a stated answer in 13 milliseconds, with
no database, no Bronze run and no other agent.

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

## 5. What "isolated containers" means here

**Decided: isolated Python distributions, one per layer**, each able to be
changed and verified on its own. Not Docker -- a compose service per layer would
add orchestration and image builds to a project whose brief says in bold that
time spent on infrastructure means the brief was misread. It is the right shape
for a real platform with separate release cadences and separate on-call owners,
and it belongs in the walkthrough as that, not in this repository.

What exists now, built and runnable:

```
packages/
  berka_control/    pyproject.toml   the governed surface
    control_dataset.yaml             constants, ownership, contracts, known answers
    dataset.py                       read-only access; set() always refuses
    contracts.py                     the guarantees, and their verification
    runtime.py                       the five gates every agent passes through
    proposals.py                     raise a change instead of making one
  berka_bronze/     depends on berka-control only
  berka_silver/     depends on berka-control only
  berka_gold/       depends on berka-control only
scripts/simulate_agents.py           the ONLY module that imports all three
tests/agentsim/                      21 tests
```

The dependency direction is a straight line into the surface, and it is
enforced rather than documented: each agent's scope gate parses its own
package with `ast` and fails on an import of a sibling layer. Each
`pyproject.toml` is tested too, so a layer cannot acquire a sibling dependency
at the distribution level either.

Three things fall **outside** the medallion and say so: the LLM client, the
question runner and the deliverable builders. One is a consumer of Gold, the
others produce submission documents. Folding them into Gold to make the diagram
tidy would weaken the Gold contract, which is the one that has to mean
something.

---

## 6. The five gates, and the proof they work

Every agent, in the simulation and in production, passes the same five gates:

| Gate | What it catches | How it is proved |
|---|---|---|
| **Scope** | the layer imported a sibling | `--fault scope` writes a real `import berka_gold` into the Silver package; the gate reads the source and refuses |
| **Input contract** | the upstream artefact is not what was promised | a layer that consumes a contract it did not receive stops before doing any work |
| **Work** | - | the layer's own transformation, the only thing the agent writes |
| **Output contract** | this layer broke what it declared | `--fault contract` drops one row and trips "this layer never filters"; `--fault dangling-flag` records a flag whose key resolves to nothing |
| **Acceptance** | the output disagrees with the known answer | `--fault acceptance` miscomputes a certified metric |

A harness that always passes demonstrates nothing, which is the same argument
as the defect injector in the production pipeline. `make simulate-faults` runs
all four and asserts each is caught; `tests/agentsim` asserts it again, plus
that a failed layer hands **no artefact** downstream -- passing broken work on
is how one layer's defect becomes three layers' debugging.

The healthy run: 29 acceptance criteria across three layers, in about 20
milliseconds.

```
bronze-agent [PASS]   5 criteria    silver-agent [PASS]  10 criteria
gold-agent   [PASS]  14 criteria
```

`--only silver` re-runs one layer against the saved Bronze artefact. That is
the practical payoff of the split and the reason artefacts are written to disk:
changing Silver costs 13 milliseconds and needs neither a database nor the
other two agents.

---

## 7. Risks

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

## 8. What would be done next, and why that order

This is the part worth arguing about, because the order is the decision.

**1. Write the Bronze tests first, before any migration.** Bronze has zero
dedicated tests today; its guarantees are asserted inside `src/ingest.py` and
never re-checked. Until they exist, `bronze-ingest` has no definition of done,
and an agent with no stopping condition does not stop. Six tests, named in
section 4. This is first because everything after it is verified *by* it.

**2. Split the test suite by layer, and leave the code alone.** `tests/bronze`,
`tests/silver`, `tests/gold`, plus `make bronze|silver|gold` running each
layer's build and its own tests. An hour of work, no production code moves, and
it converts the acceptance criteria from prose into something an agent can run
against itself. The ordering matters: a test suite that is already partitioned
makes the later package move boring, while moving packages first means
debugging two changes at once.

**3. Move the code into the packages, one layer at a time, Bronze first.**
Bronze is 250 lines and has exactly one downstream consumer, so if the contract
idea is wrong, it is wrong cheaply. Silver is 3,900 lines and should move last
despite being the most valuable to isolate, because it is where a mistake is
most expensive to find.

**4. Promote the control dataset from simulation to production.** The constants
in `src/config.py` become the `shared_constants` block; `src/config.py` becomes
a thin reader over it. This is the step that makes freeze-and-propose real
rather than demonstrated, and it is deliberately late: the surface should be
frozen only once the layer boundaries have stopped moving, or every boundary
change becomes a proposal.

**5. Only then consider running a real agent**, on one layer, with the
acceptance criteria already executable. My recommendation remains Silver, and
remains one before three.

**What I would not do.** Rename the database schemas to `bronze`/`silver`/
`gold`; the mapping table buys the same understanding for nothing. Build
containers. Split Gold into a fourth layer before someone has actually felt the
pain of its two sub-topics sharing an owner.

**The honest caveat on the whole exercise.** The simulation proves the boundary
is *checkable*, not that it is *correct*. Its dummy work is 50 lines a layer
against four tables; the real Silver is 3,900 lines against eight. What it
genuinely de-risks is the design -- contracts, gates, the frozen surface,
single-layer re-runs -- all of which would otherwise be discovered during the
migration, which is the worst time to discover them. That is why it was worth
building before the refactor rather than after.

---

## 9. What still needs a human

Five decisions are taken and built. Four remain, and all four are judgement
calls about cost and intent rather than about design:

| # | Open question | What it changes |
|---|---|---|
| 1 | Is the migration (step 3 above) in scope at all, or does the simulation answer the "what would you do next" question on its own? | If the simulation is enough, nothing further is needed: it is committed, runs in 20 ms and is covered by 21 tests. The migration is roughly a day and touches every import path in `src/`. |
| 2 | Which branch? | The submitted pipeline runs in 4m28s and is pushed. I would keep it as the thing that demonstrably works and migrate on a branch of its own. |
| 3 | Do you want a real agent run at any point, and with what budget? | Three agents against a 12,000-line codebase is real token cost. One, on Silver, with the acceptance criteria already executable, is the cheap way to find out whether the boundary holds under a model rather than under a script. |
| 4 | Should the fixture in the control dataset grow? | It is four tables and six transactions, enough to exercise one defect per severity. Growing it makes the known answers more convincing and more tedious to maintain by hand -- worth doing only if the simulation becomes the main verification route rather than a design probe. |

Nothing above blocks the submission. Everything above is reversible.
