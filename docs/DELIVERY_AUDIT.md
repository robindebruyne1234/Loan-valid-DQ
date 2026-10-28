# Delivery audit: claims, evidence and limitations

The single current review of the submission. Every important claim is mapped
to the source that is authoritative for it and to the deliverables that repeat
it; every check below says how it was run. Earlier reviews are kept, not
maintained, in `docs/history/` (in the repository; left out of the ZIP).

| Label | Meaning |
|---|---|
| **[RUN]** | Executed on the delivery machine for this audit |
| **[CODE]** | Read in the current source at the cited place |
| **[LLM]** | Output of the named provider and model |
| **[REC]** | Recommended, not implemented |
| **[ASSUMED]** | Business definition awaiting confirmation |

## 1. What was delivered, from which code

| | |
|---|---|
| Branch | `ccr-46f6f45a-t9wtd4` (local; not pushed) |
| Code commits | `1b837fd` (the delivery changes) and `b5b18f2` (the lockout tests and their disclosure; the only code change is `tests/test_auth.py`). The workbook, DDR, status report and ZIP were generated from `b5b18f2` with a clean tree; the DQ report, defect register and model explanation from `1b837fd`, whose build code is identical. The commit after `b5b18f2` adds only generated files and this audit |
| Built on | Windows 11, Python 3.13, PostgreSQL 18.6 (service `postgresql-x64-18`), Ollama with `qwen2.5-coder:3b`; no Claude CLI, no LibreOffice (Microsoft Word converts the DDR) |
| Date | 2026-10-28 |

**How the tree was reconciled.** The Windows/Ollama work existed only as
uncommitted changes on the laptop, on top of `5b13f2b`. It was committed first
(`6d10363`, plus a backup branch `backup/local-windows-ollama-5b13f2b-wip`), then
origin was merged **up to `c855be4` only** (the semantic model audit, the
init-db fix and a summary workbook). The later origin commits `49059c0`,
`a308fc1` and `6943873` (a month-end correction that changes Q9, an integrated
intent verifier, a re-run) were deliberately **not** merged: this delivery keeps
the month-end calculation and its reference results unchanged, and the intent
checker is a prototype. Nothing local was discarded.

**The database was not rebuilt.** It was built on this machine from `5b13f2b`
on 2026-10-27 (PostgreSQL 18.6). Between that build and `1b837fd`, `sql/`,
`dq/dq_rules.yaml`, `src/ingest.py`, `src/profile_data.py` and
`src/build_security.py` are unchanged, and `src/build_model.py` and
`src/dq_runner.py` changed only in the wording of the reports they write
[RUN `git diff 5b13f2b 1b837fd`]. The data quality rules were re-run at
delivery to regenerate their report, and the model checks and reconciliation
were re-run read-only (§4, §5).

## 2. Consistency matrix

| Claim | Value | Authoritative source | Evidence | Appears in |
|---|---|---|---|---|
| Source rows | 1,079,680 in 8 files; trans 1,056,320, client 5,369, disp 5,369, account 4,500, card 892, loan 682, order 6,471, district 77 | `raw.load_audit` | [RUN] `make ingest` counts_match for all 8 (run log 2026-10-27) | README, DDR context, workbook Overview |
| Rules executed / fired | 124 (89 hand written + 35 completeness sweep) / 19 | `dq/dq_rules.yaml`, `dq.results` | [RUN] §5 | README, DDR §4, workbook Overview and DQ rules |
| Rules firing by severity | block 1, warn 6, info 12 | `dq.results` of the last run | [RUN] `dq/results/dq_report.md` | dq_report |
| Defect types by severity | 14: block 1, warn 4, info 9 | `deliverables/defects.csv` (written by `make dq`) | [RUN] §5; verify script | workbook Defect types, README |
| Quarantined / flagged | 1 row (`UNQ_TRANS_BUSINESS_KEY`) / 440 rows | `dq.quarantine`, `dq.flags` | [RUN] §5 | README, DDR §2 and §4, workbook Overview |
| Reconciliation | 9 checks balanced: 7 row counts (trans 1,056,320 - 1 = 1,056,319), 2 money sums (transactions 6,257,793,560.30; loans 103,261,740.00) | `build_model.reconcile_core` | [RUN] §5, rolled back | README, DDR §2, model_explanation |
| Model shape and grains | 4 dimensions, 1 bridge, 2 base facts, 1 derived fact, 3 curated views; keys, FKs, grains verified | `sql/30_core.sql`, `build_model.MODEL_OBJECTS` | [RUN] §5: 0 key, FK, grain or code problems | workbook Model, model_explanation, DDR §3 |
| Join cardinality and row loss | 19 declared joins, cardinality and optionality measured on every build; fan-outs (account -> transaction, up to 675 postings per account, measured by the semantic audit) and row loss (869 clients without an owned account, re-measured by `tests/test_semantic.py`) disclosed | `semantic/semantic_layer.yaml` joins | [RUN] `make semantic`: 0 problems | context pack, SEMANTIC_MODEL_AUDIT §2.2 |
| Semantic layer | 11 entities, 105 columns, 12 metrics, 7 caveats; validated against the live schema | `semantic/semantic_layer.yaml` | [RUN] 0 problems | workbook Overview, DDR §5 |
| Problematic loan | status B or D; 76 of 682 = 11.14% (B 31, D 45); denominator all loans | `sql/10_stg.sql:330`, `sql/30_core.sql:344`, semantic glossary and `problematic_loan_share` | [RUN] live count; [CODE] same predicate in stg, core, ai view, reference SQL and Claude's Q3/Q10 SQL; [ASSUMED] A4 | README, DDR §5, workbook Model and Questions |
| Month-end balance rule | last posting on or before the month end; same-day ties by highest `trans_id`; carried forward when no posting; 185,615 rows | `sql/30_core.sql` (`fact_account_month_end_balance`) | [CODE]; limitation A14, caveat C2 | workbook Model, DDR §3, semantic caveat C2 |
| Ten reference answers | Q1 south Moravia 937 ... (8 rows), Q2 6 years, Q3 11.14%, Q4 4 card types, Q5 top 10 (Hl.m. Praha first), Q6 12 months (Jan 106), Q7 4 statuses (A 37.07), Q8 male 60.23%, Q9 43,808.94 CZK over 4,500 accounts (76 carried forward), Q10 'after transaction' 18.75% | `sql/60_reference_queries.sql` | [RUN] re-executed at delivery: all ten identical to `reference_results.json` | workbook Questions and Q detail |
| Recorded evaluation | Claude Sonnet 5.5: 10 answered first attempt, 10 of 10 match | `dq/results/llm_results.json` (2026-10-25, commit `a7da25a`, 29,500-character pack), `evaluation.json` | [LLM]; [RUN] re-scored at delivery: 10 match | README, DDR §7, workbook Overview and Questions |
| Secondary evaluation | Ollama qwen2.5-coder:3b: 6 match, 2 partial (Q3, Q7), 2 mismatch (Q6, Q10) | `dq/results/local/` (2026-10-27, commit `5b13f2b`, 29,500-character pack) | [LLM]; [RUN] re-scored: same tally | README, DDR §7, workbook Questions (separate table) |
| Access policies | 7 RLS policies on 7 core tables; ai views `security_invoker`; identity `session_user` after two factors | `sql/50_sec_rls.sql`, `sql/51_sec_auth.sql` | [RUN] tests §4; [CODE] | workbook Entitlements, ACCESS_AND_AUTH, DDR §6 |
| Second-factor lockout | 5 committed failures lock the factor for 15 minutes, the right code refused while locked; a failure the caller rolls back is not counted | `sec.verify_second_factor` (`sql/51_sec_auth.sql:252-292`) | [RUN] new test passes; the rollback gap is a strict expected failure | ACCESS_AND_AUTH §3, DEMO_SCRIPT, VISUAL_GUIDE, DDR residual risks |
| Visible rows per principal | cro_global 5,369 / 4,500 / 682 / 1,056,319; rm_north 1,481 / 1,241 / 179 / 294,622; rm_south 1,387 / 1,158 / 195 / 272,770 (1,386 in its book + client 3763 by delegation, valid to 2026-11-11); rm_unassigned 0; client_3764 1 / 1 / 1 / 439 | logins as each principal | [RUN] `make entitlements` and workbook build | README, workbook Entitlements |
| Delegated (disponent) access | a disposition grants that one account, never its owner | `sec.v_access_grant` (`sql/51_sec_auth.sql:444-451`); D023, D024, A39 | [RUN] `test_a_disponent_reaches_the_account_but_not_its_owner` | DECISIONS, ASSUMPTIONS, workbook Decisions and Entitlements, DDR §6 |
| Superseded rules | A36 and D022 superseded by A39 / D023 / D024 | `ASSUMPTIONS.md`, `DECISIONS.md` | [CODE] policy matches D023/D024 | workbook Assumptions and Decisions (status column) |
| SQL controls | one read-only SELECT on `ai.*`; no function outside allowed schemas; row cap 10,000 that the model cannot raise; 60 s timeout; read-only transaction; persona's own two-factor connection | `src/sql_guard.py`, `src/config.py:516-525` | [RUN] `tests/test_guard.py`; [CODE] §3 | DDR §7, ZIP manifest |
| Semantic verification | not implemented: the guard checks safety, not meaning; IR checker is a prototype | `scripts/ir_check_prototype.py` | [CODE] not imported by `src/` | DDR §7, README, SEMANTIC_MODEL_AUDIT |
| Tests | see §4 | `tests/` | [RUN] | workbook Overview (collected count), this file |
| Provider and model names | claude_cli / claude-sonnet-5-5 (recorded); ollama / qwen2.5-coder:3b (local, optional) | result files' `provider` and `model` fields | [CODE] | every deliverable |
| Assumptions and decisions | A1-A46, D001-D027 | `ASSUMPTIONS.md`, `DECISIONS.md` | verify script | workbook Assumptions and Decisions |

## 3. SQL and execution controls

What each layer enforces, and what it does not:

| Layer | Enforces | Does not |
|---|---|---|
| `sql_guard.guard()` [CODE `src/sql_guard.py:194`] | one statement; SELECT only; tables schema-qualified in `ai`; a CTE name cannot stand in for a real table; no forbidden or out-of-schema function; LIMIT added or tightened to the cap | resolve columns; judge meaning |
| `execute_guarded()` [CODE `:282-313`] | `BEGIN READ ONLY`; `SET LOCAL statement_timeout`; fetches at most cap + 1 rows and refuses more | -- |
| PostgreSQL | column and relation resolution (a name that does not exist is an error, returned and never answered); RLS on every core table; SELECT-only grants | -- |
| CLI path [CODE `src/run_questions.py:215-218`] | the guard, then `auth.login(run_as)` (two factors), then `execute_guarded`; one retry with the refusal reason; parse and database errors recorded as such | -- |
| Web path [CODE `src/webapp.py:494-505`, `:779`] | the same, after `session_role()`: `/api/ask` accepts a completed two-step login only, never a role name | -- |

New at delivery: the semantic validator refuses a metric whose entity is not
described, or whose expression, filter or grouping names a column that does
not exist (`gender_share` had said "any entity with a gender column"; it now
names `ai.client.gender` and points to `owner_gender` elsewhere), and
`tests/test_guard.py::test_a_name_the_schema_does_not_have_fails_safely` shows
an unknown column, view or join key comes back as the database's error with no
rows, the connection still usable.

## 4. Tests and checks run for this delivery

All on the delivery machine, `PYTHONUTF8=1`, the project virtual environment.

| Command | Result |
|---|---|
| `python -m pytest` on the merged tree, before any fix | 309 passed, **13 failed**, 1 skipped. All 13 had one cause: the grown semantic pack no longer fit the default Ollama window (fixed, §3 and `src/config.py`) |
| `python -m pytest` on `1b837fd` (clean tree) | **327 passed, 1 skipped**, exit 0, 9 min 18 s. The skip is the opt-in live-model test. An earlier run on the same source before the last generator edits: 327 passed, 1 skipped |
| `python -m pytest tests/test_auth.py` on `b5b18f2` | 40 passed, **1 xfailed**: the new lockout test passes; the strict expected failure records the rollback gap (§8 item 4) |
| `python -m pytest tests/test_dq.py tests/test_llm_client.py tests/test_semantic.py tests/test_ask_local.py`, after the last generator edits and before `1b837fd` | 95 passed |
| `BERKA_LIVE_LLM=1 python -m pytest tests/test_llm_live.py` (real Ollama, CPU) | 1 passed in 9 min 30 s: the model answered in contract on the current pack and its SQL ran as the persona. Not evidence of answer accuracy |
| `python -m src.semantic_context --write` | 0 problems: 11 entities, 105 columns, 19 joins (cardinality and optionality measured), 12 metrics, 7 caveats |
| Reference SQL re-executed against the live database, compared with `reference_results.json` | all ten identical |
| `python -m src.evaluate` on the recorded Claude run, output to a scratch file | match 10 |
| `python -m src.evaluate` on the local run, output to a scratch file | match 6, partial 2, mismatch 2 |
| `python -m src.dq_runner` (twice; the second from `1b837fd`) | 124 executed, 19 fired (block 1, warn 6, info 12), 1 quarantined, 440 flagged, 0 errored; raw = stg on 11 checks |
| Model checks and `reconcile_core`, in a rolled-back transaction, after the DQ re-run | 0 code, key, foreign key or grain problems; 9 reconciliation checks, every delta 0 |
| `python -m src.make_ddr` | 2 pages (Word's count and the PDF's agree) |
| Deliverable check script (reopens the workbook, DDR and ZIP and compares them with their sources) | all checks pass (§6) |

330 tests are collected at `b5b18f2` (the workbook's Overview reports that count).

Security-relevant tests inside the full run: `tests/test_rls.py` (nine bypass
attempts, cross-client attempts for both customers, the disponent and
delegation cases, onboarding and deactivation as pure data changes, every
protected table has RLS and every view between consumer and policy is
`security_invoker`), `tests/test_auth.py` (password alone reveals nothing, a
code cannot be reused, an expired session stops working, a consumer cannot
reach the authentication machinery, five committed failures lock the factor), `tests/test_guard.py` (hostile SQL,
CTE-name and function-schema bypasses, the row cap, timeout, read-only
transaction, unknown names) and `tests/test_webapp.py` (no session, a forged
token, or a persona name instead of a login is refused).

## 5. Data quality and reconciliation

- **Rule coverage.** Every rule in `dq/dq_rules.yaml` carries a dimension, a
  severity, a severity rationale written in terms of the questions, a handling
  and the questions it affects; the loader refuses a rule without them, and
  `tests/test_dq.py` checks that every dimension is covered and that each of 20
  seeded defects is caught by the rule meant to catch it [RUN].
- **What a severity does.** `block`: the row is quarantined with a reason and
  excluded from core and from the ai views (1 row, a duplicate transaction by
  business key). `warn`: kept, flagged in `dq.flags`, the flag travels to the
  core row and a caveat to the semantic layer (440 rows across 6 rules, 4 defect
  types). `info`: standardised or logged, no answer changes (12 rules, 9 defect
  types) [RUN].
- **Register and report agree.** `deliverables/defects.csv` (14 types),
  `dq/results/dq_report.md` (19 firing rules) and the workbook's Defect types tab
  come from the same run; the report now says that it counts rules, not defect
  types (it used to label the rule count "defect types") [RUN].
- **Reconciliation.** raw = stg on 11 checks at the DQ step; core = stg minus
  quarantine on 7 row counts and 2 money sums at the model step [RUN, §4].
  Separate and meaningful: the per-account balance chain does not reconcile for
  55 accounts beyond 100 CZK (`CON_BALANCE_RECONCILIATION_MATERIAL`, warn), and
  that is reported, not corrected (A30).

## 6. Deliverables

| Deliverable | Path | Status | Evidence |
|---|---|---|---|
| Workbook | `deliverables/Berka_TakeHome_Submission.xlsx` (11 tabs) | VERIFIED WITH DISCLOSED LIMITATIONS | Built from `b5b18f2`. Check script: tab list, no hidden sheets; Defect types equals `defects.csv` (14 rows, severities, rationale and handling present); Overview figures equal the last DQ run; the ten official questions with question text, reference SQL, generated SQL and verdict equal their sources; attribution names provider, model, date, commit and pack; local run separate with its own verdicts; 46 assumptions, 27 decisions, A36/D022 superseded; entitlement counts equal the last measurement; no placeholder, over-long or NOT EXECUTED cell. Limitation: limitation 1 below |
| Design Decision Record | `deliverables/DDR.pdf` (2 pages) and `DDR.docx`; source `deliverables/DDR_source.md` | VERIFIED WITH DISCLOSED LIMITATIONS | Built from `b5b18f2`; page count by Word and by the PDF. Covers context, options, choice, reasons, costs and 100,000x as reasoning. States the intent checker is a prototype and the month-end fix is not made |
| Semantic solution ZIP | `deliverables/semantic_solution.zip` | VERIFIED WITH DISCLOSED LIMITATIONS | Members equal the packaging rules, byte-identical to the working tree at the final commit, forward-slash names, no secrets, caches, raw data, prep or history. Its checksum is not recorded here because this file is inside it. Extracted into an empty folder [RUN]: every Python file parses and every relative Markdown link resolves inside the archive. A rebuild from the extracted ZIP was not run (it needs the raw data, which the ZIP leaves out by design). The Windows steps it documents (`setup`, `init-db`, `build`) built this machine's database on 2026-10-27 (run log) and were not re-run for this audit |
| Defect register | `deliverables/defects.csv` | VERIFIED | Regenerated by the DQ run; 14 rows with counts, severities and handling identical to the committed register (one illustrative example differs, §8 item 9) |
| Model explanation | `deliverables/model_explanation.md` | VERIFIED | Regenerated from the live database by `build_model.write_model_explanation` at `1b837fd`; row counts unchanged |

## 7. Documentation: one source per subject

The canonical document per subject is listed in the README. Consolidated at
delivery:

| Change | Why |
|---|---|
| `WALKTHROUGH_NOTES.md` merged into `docs/INTERVIEW_PREPARATION.md` and removed | Two walkthrough-prep documents; the notes carried stale figures (123 rules, 114 tests, 1,386) |
| `PLAN.md`, `docs/BUILD_REVIEW.md`, `docs/BUILD_REVIEW_2.md`, `docs/REVIEW_AND_NEXT_STEPS.md`, `docs/SECURITY_AND_CODE_REVIEW.md` moved to `docs/history/` with a banner | Dated reviews whose figures and open items competed with the current state; kept for traceability |
| `deliverables/Berka_Summary_Workbook.xlsx` and `scripts/make_summary_workbook.py` removed; its Decisions tab folded into the submission workbook | Two workbooks with overlapping tabs |
| README rewritten as an index | It carried stale counts (114 tests, 1,386, PostgreSQL 16 only) |
| `docs/GETTING_STARTED.md` Option B | It told the reader to run `make questions` with Ollama, which would overwrite the recorded Claude run; now `make questions-local` |
| `docs/SEMANTIC_MODEL_AUDIT.md` | Status-at-delivery note; its "not regenerated" list updated |
| `AI_DISCLOSURE.md` | Later Claude sessions and the local Ollama model disclosed; the local-run commands no longer overwrite the evidence |

Left out of the ZIP, kept in the repository: `docs/INTERVIEW_PREPARATION.md`,
`docs/history/`, `scripts/make_pitch_deck.py`, `scripts/make_setup_workbook.py`
(the deck and the setup workbook are not deliverables).

## 8. Known limitations and open items

| # | Item | Priority | Status |
|---|---|---|---|
| 1 | The recorded Claude run used the 29,500-character pack from before the semantic audit; the delivered pack is about 33,700 characters. The audit reports a 10/10 re-run on its new pack whose outputs are not in the repository, and no Claude CLI was available here | P1 | Disclosed in the workbook, README, DDR. Re-run `make questions && make evaluate` where the CLI is available [REC] |
| 2 | The guard proves a query is safe, not that it answers the question; the IR checker is a prototype | P1 | Disclosed; wiring it in is [REC] (SEMANTIC_MODEL_AUDIT §2.4) |
| 3 | Month-end tie-break by highest `trans_id`, which is not chronological: per-account month-end balances can be off; Q9's average moves about 2 CZK under a chain-based rule (audit measurement) | P1 | Unchanged by decision; disclosed as A14, caveat C2, DDR §3 [REC] |
| 4 | The second-factor lockout counts only failures the client commits. The project's client commits every attempt, but anyone holding a principal's password can connect directly, roll failed guesses back and never be locked out, so the second factor does not stop a direct-connection guesser. Row level security itself is unaffected: no factor, no rows | P1 | Found in this audit; disclosed in ACCESS_AND_AUTH, DEMO_SCRIPT, VISUAL_GUIDE and the DDR; recorded as a strict expected failure. Fix [REC]: count attempts outside the caller's transaction, or accept consumer logins only through a gateway |
| 5 | The local Ollama run predates the current pack; small-model interpretation errors (Q3, Q6, Q7, Q10) | P2 | Out of scope; kept separate. The live test shows the current pack is accepted and answered in contract [RUN], not that answers are right |
| 6 | `rm_south`'s count includes a time-bound delegation that expires 2026-11-11; a build after that date shows 1,386 | P2 | Documented here and in the README |
| 7 | Demo credentials (`berka_owner_pw`, persona passwords, TOTP secrets) are fixed demo defaults | P2 | Never production; overridable by environment; no real secret in the ZIP [RUN scan] |
| 8 | No read audit log, no field masking | P2 | [REC], DDR §6 |
| 9 | The "Example" column of the defect register and report is sampled without an ORDER BY, so it can change between runs (one example changed between the two delivery DQ runs); counts, severities and handling did not | P2 | Cosmetic; a deterministic sample is a one-line change [REC] |
| 10 | Business definitions: problematic = B or D (A4), interest counts as incoming (A7), CZK only (A19), calendar quarters not fiscal | -- | [ASSUMED], all in ASSUMPTIONS.md |
| 11 | 4m28s for `make all` was measured once on the Linux build | -- | Labelled historical; not re-measured |
