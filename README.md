# The Governed Data Product for AI -- Berka (PKDD'99)

Raw banking tables turned into a trusted, documented, entitlement-aware data
product that an AI assistant can query correctly. Take-home submission.

```
make up     # PostgreSQL 16 (docker compose if a daemon is available, else a native cluster)
make all    # the whole pipeline and every deliverable, 4m28s from an empty database
make test   # 114 tests
```

## What is here

| Deliverable | Where | Covers |
|---|---|---|
| Defect types | `deliverables/Berka_TakeHome_Submission.xlsx`, tab **Defect types** (also `deliverables/defects.csv`) | Task 1 |
| Model explanation | same workbook, tab **Model** (full version with ER diagram: `deliverables/model_explanation.md`) | Task 2 |
| Generated queries and answers | same workbook, tabs **Questions** and **Q detail** | Task 2 |
| Semantic solution and code | `deliverables/semantic_solution.zip` | Task 2 |
| Design Decision Record | `deliverables/DDR.pdf` (2 pages, verified) and `DDR.docx`; source text `DDR_source.md` | all |

Supporting: `STATUS_REPORT.md` (what ran, what did not), `DECISIONS.md` (12
decisions with options, cost and consequence), `ASSUMPTIONS.md` (A1-A24),
`AI_DISCLOSURE.md`, `WALKTHROUGH_NOTES.md`.

## Results

**Task 1 -- data quality.** 123 rules executed across all six dimensions
(completeness, uniqueness, referential integrity, validity, cross-table
consistency, reconciliation): 88 hand written in `dq/dq_rules.yaml`, plus a
completeness sweep that expands to one rule per column at run time. Every rule
carries a severity *and* the reason for that severity written in terms of the
ten questions; the loader refuses to run a rule that lacks one. 19 rules fire,
giving 14 defect types; 1 row is quarantined and 440 are flagged.

The three findings worth reading first are not in the dataset documentation:

- the per-account balance chain does not reconcile. Tested order-independently,
  3,869 of 4,500 accounts differ between the sum of their postings and their
  last reported balance. Most of that is rounding (every amount carries one
  decimal), but **55 accounts are off by more than 100 CZK** and one by exactly
  1,200.00 with only 55 postings -- a missing or extra posting;
- **`trans_id` is not chronological within a day**, so for 183 accounts the
  closing balance of their last active day is a documented choice rather than a
  fact. That is precisely what Q9 asks for;
- **one duplicate transaction by business key** -- same account, date, type,
  amount and resulting balance, different id -- which no primary key can catch.

Proof the rules work: `sql/70_inject_defects.sql` builds a corrupted copy of
staging with 20 deterministic seeded defects, one per rule family, and
`tests/test_dq.py` asserts each is caught by the rule meant to catch it.

**Task 2 -- model and semantic layer.** A star schema (4 dimensions, 1 bridge,
2 base facts, 1 derived fact, 3 curated views), verified after every build:
9 primary keys, 8 foreign keys, three declared grains, and
`core = stg - quarantine` on both row counts and amount sums. The semantic
layer (`semantic/semantic_layer.yaml`) is validated against the live database,
so a described column that does not exist or a declared grain that is false
fails the build.

The LLM answered **10 of 10 questions on the first attempt**, and **10 of 10
match the hand-written reference answers**. No retry was used and no SQL was
hand-corrected.

**Task 3 -- entitlements.** Row level security policies on the core tables,
`security_invoker` views on top, identity from `session_user`. Measured by
connecting as each role:

| role | clients | accounts | loans | transactions |
|---|---:|---:|---:|---:|
| `cro_global` (holds every client) | 5,369 | 4,500 | 682 | 1,056,319 |
| `rm_north` | 1,481 | 1,241 | 179 | 294,622 |
| `rm_south` | 1,386 | 1,157 | 194 | 272,331 |
| `rm_unassigned` (no portfolio) | 0 | 0 | 0 | 0 |

Nine bypass attempts are in `tests/test_rls.py` and all nine fail. Onboarding a
user or a portfolio is four inserts and one credential.

## Layout

```
brief/        the original brief and the dataset description
data/raw/     the 8 source .asc files (trans.asc gzipped); provided/ is empty
sql/          numbered SQL in execution order:
              00 schemas | 10 staging | 30 core | 40 ai views | 50 security
              60 reference queries | 70 defect injector
semantic/     semantic_layer.yaml, the rendered context_pack.md, prompt_template.md
src/          Python orchestration; config.py holds every shared constant
dq/           dq_rules.yaml and every result the runs produced
llm_logs/     one audited record per LLM call: prompt, model, parameters, response
tests/        114 tests
deliverables/ the workbook, the DDR, the ZIP, defects.csv, model_explanation.md
```

## How to re-run one step

```
make ingest        # load the raw files, verify counts, hash each file
make profile       # build stg, profile 102 columns, list candidate defects
make dq            # run all 123 rules, quarantine, flag, write the defect report
make model         # build core, verify it, restore the ai views
make reference     # run the hand-written reference queries (ground truth)
make semantic      # validate the semantic layer and render the context pack
make entitlements  # apply the policies and seed the demo portfolios
make questions     # ask the LLM the 10 questions
make evaluate      # compare the LLM answers to the reference answers
make deliverables  # workbook + DDR + ZIP
```

## Environment notes

- **PostgreSQL 16.** `scripts/db_up.sh` prefers `docker compose` and falls back
  to a native cluster; this submission was built on the fallback path, because
  the build container has the Docker CLI but no daemon. Identical DDL, policies
  and tests either way.
- **The data.** The eight original `.asc` files are in `data/raw/`, from the
  public mirror `github.com/jlacko/berka-dataset`, verified against the
  published row counts (4,500 / 5,369 / 5,369 / 892 / 682 / 6,471 / 1,056,320 /
  77 -- all exact). `trans.asc` is gzipped (69 MB to 17 MB) and hashed on its
  decompressed stream.
- **No bank-supplied copy was received**, so `data/raw/provided/` is empty and
  the public copy is primary. To process the bank's copy, drop the files there
  and re-run `make all`: the loader prefers that directory and the rules do not
  change.
- **The LLM** is the local Claude CLI called as a sandboxed completion -- no
  tools, no MCP, no filesystem, no database. Swap it with
  `LLM_PROVIDER=anthropic_api|ollama|none`. Full disclosure in
  `AI_DISCLOSURE.md`.

## Python dependencies

`psycopg[binary]`, `PyYAML`, `sqlglot`, `openpyxl`, `python-docx`, and `pytest`
for the tests. `make deps` installs them. LibreOffice is used only to convert
the Design Decision Record to PDF and to verify its page count.
