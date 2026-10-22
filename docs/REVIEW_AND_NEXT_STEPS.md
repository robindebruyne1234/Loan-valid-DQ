# Review and next steps

Written at the end of the build session. Everything below was checked against
the repository and the database rather than recalled; where a claim could not
be verified, it says so.

---

## 1. State of the submission

| | |
|---|---|
| Branch | `ccr-46f6f45a-t9wtd4`, clean, in sync with origin |
| Pipeline | `make clean all` from an empty database: **4m28s**, 12 of 12 steps |
| Tests | **135 passing** (114 pipeline + 21 agent simulation) |
| Deliverables | workbook (9 tabs), DDR (2 pages, verified), ZIP (123 files), `defects.csv`, `model_explanation.md` |
| LLM | 10 of 10 questions answered first attempt, 10 of 10 matching the hand-written reference answers |
| Entitlements | 5,369 / 1,481 / 1,386 / 0 clients visible to the four demo roles; nine bypass attempts all refused |

The three tasks the brief sets are answered, and each answer is backed by
something executable rather than by prose:

- **Task 1** -- 123 rules over six dimensions, each with a severity *and* its
  justification in terms of the ten questions. Proven by 20 seeded defects in
  a separate schema, each caught by the rule meant to catch it.
- **Task 2** -- a verified star schema and a semantic layer validated against
  the live database, with the model answering all ten questions correctly on
  the first attempt from the semantic layer alone.
- **Task 3** -- row level security on the base tables, proven by connecting as
  restricted roles and counting rows, not by reading the policies.

---

## 2. What this review found

Four findings. The first is the one worth owning.

### 2.1 A hard-coded number had gone stale in a deliverable (fixed)

The workbook's Overview tab said **"Tests: 114 passing"**. The real figure was
135. The count was a literal in `src/make_workbook.py`, so it went stale the
moment the simulation tests were added.

This is a direct breach of the rule the submission makes most loudly about
itself -- *every number in a deliverable comes from code that was executed* --
and it was in the tab a reviewer reads first. It is worse than an ordinary
stale figure precisely because the Run log tab sits three tabs away asserting
that nothing is transcribed by hand.

Fixed by deriving it: `count_tests()` collects the suite and sums the result,
and the Overview now reads 135 because that is what pytest reported.

Two more of the same class were found by grepping the generators for literals
and fixed the same way: the DQ rules tab's "123 executed" now comes from
`dq.results` for the last run, and the ZIP manifest's "88 hand-written rules"
now counts `dq/dq_rules.yaml`. Remaining literals in the generators are prose
in docstrings, which no deliverable renders.

**What this says about the method, honestly:** the honesty rule held
everywhere a pipeline step produced the number, and failed in the one place a
human typed it. The lesson is not "be more careful" -- it is that the rule only
works where it is mechanised.

### 2.2 The ZIP had fallen behind the repository (fixed)

`semantic_solution.zip` was built at 12:22 and the medallion work landed from
12:45 onwards, so the archive had no `packages/`, no `tests/agentsim/`, no
agent definitions and no `MEDALLION_REFACTOR.md`.

Fixed by extending the archive and, more usefully, by making the manifest say
what that material *is*: a section headed "Not part of the assessed pipeline"
explains that the agent simulation is next-step work, that no production code
was refactored for it, and that `make all` does not touch it. A reviewer should
never have to guess which half of an archive is being submitted.

### 2.3 The status report was stale (fixed)

`STATUS_REPORT.md` was generated at 10:54 and still described a 114-test
submission. Regenerated; it is produced from the run log, so it was only stale
because nothing had re-run it.

### 2.4 The database stopped three times during the session

The PostgreSQL cluster went down on each container restart and needed a manual
`scripts/db_up.sh`. Nothing was lost -- the pipeline is reproducible from the
raw files in 4m28s -- but a reviewer cloning this into a fresh cloud session
hits the same thing. This is unfixed and is the first item in section 4.

---

## 3. What is genuinely strong, and what is thin

Stated plainly, because the walkthrough will probe both.

**Strong.**

- *The severity framework has consequences, not labels.* `block` quarantines
  and the exclusion is counted and reversible, `warn` puts a flag on the row
  that travels into the semantic layer and out through the answer, `info`
  changes no number. The zero-amount case is the worked example of why the
  severity is the hard part, not the rule.
- *Three findings that are not in the dataset documentation*: the per-account
  balance chain does not reconcile (55 accounts beyond 100 CZK, one at exactly
  1,200 with 55 postings); intra-day ordering is undefined, so the Q9 closing
  balance is a documented choice for 183 accounts; one duplicate transaction by
  business key that no primary key can catch.
- *The entitlement claims are tested by authenticating as restricted roles.*
  That is what caught the `security_invoker` leak, which reading the policies
  never would have.
- *Verification caught two self-inflicted defects before they shipped* -- the
  unscoped quarantine view and the view that dropped the filter -- and both are
  written up rather than quietly fixed.

**Thin.**

- *Bronze has no dedicated tests.* Its guarantees live as assertions inside
  `src/ingest.py` and are never re-checked. This is the largest hole in the
  test suite and the reason `bronze-ingest` has no definition of done.
- *Four modules are over 500 lines* (`make_workbook` 812, `dq_runner` 800,
  `build_model` 719, `profile_data` 597). None is incoherent, but
  `dq_runner` in particular mixes execution, quarantine, flagging,
  reconciliation and two report writers.
- *`dq_runner` materialises every violating row in Python* before sampling.
  Fine at 1.06 m rows, and the Design Decision Record already names it as one
  of the four things that break at 100,000x -- but it is a known limit shipped
  as-is.
- *The DDR page count is checked by regexing `/Type /Page` out of the PDF
  bytes.* It works on LibreOffice output and would not survive a different
  producer.
- *No CI.* Everything is reproducible by one command and nothing runs it
  automatically.
- *The agent simulation proves the boundary is checkable, not that it is
  correct.* Fifty lines a layer against four tables is not 3,900 lines against
  eight.

---

## 4. Next steps, in order

Ordered by what unblocks what, not by appeal.

**Before the walkthrough**

1. **Build the deck.** `WALKTHROUGH_NOTES.md` is already the narrative and the
   six figures are rendered at 2x for exactly this. This is the biggest gap
   between what exists and what you will be standing in front of.
2. **Run `/security-review` and `/code-review` on the branch.** Task 3 is a
   security claim and this repository has already shipped one RLS leak; an
   independent pass is the cheapest insurance against a second being found
   live. Offered twice, not yet taken up.
3. **Rehearse the three questions that will be asked**: why `info` for
   zero amounts, how you know the rules work when the public copy is clean, and
   why `session_user` rather than a session variable. Answers are drafted in
   `WALKTHROUGH_NOTES.md`; what is missing is saying them out loud.

**If the work continues**

4. **Write the six Bronze tests.** Nothing else in the layered plan can be
   verified until they exist.
5. **Split the test suite by layer** (`tests/bronze|silver|gold`, `make
   bronze|silver|gold`). An hour, no production code moves, and it turns the
   agents' acceptance criteria into something runnable.
6. **Add a session-start hook** so `make up` runs automatically in a fresh
   cloud session. Finding 2.4, and about fifteen minutes of work.
7. **Then the package migration**, Bronze first because it is 250 lines with
   one consumer, Silver last because it is where a mistake costs most. The
   reasoning is in `MEDALLION_REFACTOR.md` section 8.
8. **Promote the control dataset to production** only once the boundaries have
   stopped moving -- freezing a surface that is still shifting turns every
   change into a proposal.

**Deliberately not doing**

- Renaming the database schemas to `bronze`/`silver`/`gold`. The mapping table
  buys the same understanding for nothing.
- Containers per layer. Right for a platform with separate release cadences;
  wrong for a brief that warns about infrastructure time in bold.
- Splitting Gold into a fourth layer before anyone has felt the pain of its
  sub-topics sharing an owner.

---

## 5. Open questions for you

None of these block the submission.

1. Is the package migration in scope at all, or does the simulation answer the
   "what would you do next" question on its own?
2. Do you want a real agent run at any point, and at what budget? One, on
   Silver, with acceptance criteria already executable, is the cheap way to
   learn whether the boundary holds under a model rather than a script.
3. Should the next-step material stay in the submission ZIP? It is in, and
   labelled as not part of the assessed pipeline. Removing it is one line.
