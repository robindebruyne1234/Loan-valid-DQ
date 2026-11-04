# <span class="num">0</span>Start here {#start-here}

<p class="lede">This guide is the long form of the study pack. It explains every step of the
project, from the eight raw files to an AI assistant that is treated as a dumb and
dangerous client, and for each step it gives the decision, the reason, the cost, the
evidence and the weak spot you should expect to be asked about.</p>

## What is in the study pack {#pack}

| File | Use it for | When |
|---|---|---|
| **01 Study Guide** (this file) | Understanding every step deeply; the decision and assumption registers; the question bank | Days 1 to 3 |
| **02 Lessons Learned and Self-Audit** | The mistakes and sloppy spots, each verified, with how to talk about them | Day 3, then skim again on day 4 |
| **03 Walkthrough Deck** (.pptx and .pdf) | The 30 minutes you present in the 45-minute walkthrough, with speaker notes | Rehearse days 2 to 4 |
| **04 Cheat Sheet** | One page of figures and one-liners, to print | Day 4 and Monday morning |

The brief's follow-up is a **45-minute technical walkthrough in which you defend your
design choices, with 15 minutes of questions**. The deck is sized for about 30 minutes of
talking. Everything else in the pack exists so that the 15 minutes of questions go well.

## A four-day plan to Monday {#plan}

| Day | Study | Practise |
|---|---|---|
| **Thursday** | Chapters 0 to 3 (story, way of working, architecture) and steps 1 to 5 (ingest, profile, clean, rules, model). The lessons-learned summary table | The 60-second story out loud, three times. Draw the six layers from memory |
| **Friday** | Steps 6 to 12 (reference answers, semantic layer, security, authentication, the LLM path, evaluation, demo). The ten questions | Present the deck once, untimed. Explain "where the filter sits" without slides |
| **Saturday** | The full Lessons Learned document. The question bank (chapter 17) | Deck timed at 30 minutes. Answer 15 random questions from the bank aloud. Practise the five "raise it yourself" items |
| **Sunday** | Cheat sheet; skim the decision and assumption registers | Dry run of the demo on the laptop (checklist below). One full mock walkthrough with somebody asking questions. Then stop |
| **Monday** | Cheat sheet only | Arrive with the demo already running |

:::key Demo checklist for Sunday evening
- Start the PostgreSQL service and run `scripts\windows.ps1 test` once: you want to know it is green before you are in the room.
- The demo delegation (`rm_south` covering client 3763) was seeded for 14 days at the last `entitlements` run and lapses around **10–11 November**. Check it with `SELECT valid_to FROM sec.access_delegation;` and re-run `scripts\windows.ps1 entitlements` the day before if needed. After it lapses, `rm_south` shows 1,386 clients instead of 1,387.
- If you demo the web page with Ollama, warm the model up first (the first call loads about 1.9 GB). Expect a small model to get some questions wrong; that is part of the story, not a failure of the governance.
- Have `docs/DELIVERY_AUDIT.md` open in a tab: it is the single document that maps every claim to its evidence.
:::

## Which version you are defending {#versions}

There are two lines of work, and you must not mix them up in the room.

| | Delivered version | Work after delivery |
|---|---|---|
| Where | Branch `delivery-freeze-2026-10-28`, commit `fc0c281` (code `b5b18f2`), built on the Windows laptop, PostgreSQL 18.6 | Branch `ccr-46f6f45a-t9wtd4`, commits `49059c0`, `a308fc1`, `6943873` (2026-10-28, not merged into the delivery) |
| Month-end balance | Same-day ties broken by the **highest `trans_id`** (A14, D019). Known limitation, disclosed | Closing posting = end of the running-balance chain, ambiguous days marked (D028) |
| Q9 | **43,808.94** CZK | 43,810.47 CZK |
| Material balance breaks | 55 accounts | 14 accounts (41 of the 55 were artefacts of the tie-break) |
| Meaning of generated SQL | Guard checks **shape only**; intent checker is a **prototype** (`scripts/ir_check_prototype.py`) | Intent (IR) verified before and after execution in both CLI and web (D029) |
| LLM evidence | Claude Sonnet 5.5, run 2026-10-25 on the older 29,500-character pack: 10/10. Ollama qwen2.5-coder:3b: 6 match, 2 partial, 2 mismatch | Claude re-run on the new pack: 10/10 verified, plus 4 extra questions 4/4 |
| Decisions / assumptions | D001–D027, A1–A46 | Adds D028, D029, A47–A49 |

:::say How to handle the two versions
"What I submitted keeps the month-end calculation and its reference answers unchanged,
and says plainly that the tie-break is a known limitation and that the intent checker is a
prototype. After submitting I fixed both on a separate branch, and I can show you the
before and after." Present the delivered numbers as the answer; present the later work as
what you learned and did next. Never quote 43,810.47 as the delivered Q9.
:::

## The story in 60 seconds {#story}

> Business users want to ask a bank's data questions in plain English. An AI assistant can
> only answer correctly if the data is clean, the words mean one thing, and every user sees
> only their own clients. I treated the assistant as a **dumb and dangerous client**: dumb,
> because it will guess at anything the data does not spell out; dangerous, because it
> writes code that runs against customer data. So every layer either removes a reason to
> guess or removes a way to do harm.
>
> The eight raw files land verbatim, hashed. Staging types and decodes them but never
> repairs or drops anything; 124 rules then grade every defect as block, warn or info, and
> each severity has a mechanical consequence. A star schema with one definition per business
> term sits on top, and a validated semantic layer tells the model what every entity,
> metric and word means, and what it does *not* mean. The model sees only that, never the
> data. Its SQL is parsed and bounded, and it runs on the user's own two-factor database
> session, where row level security on the base tables decides which rows exist. The
> filter is not in the query, so nothing the model writes can remove it. Claude answered
> all ten questions and all ten matched hand-written reference SQL; I can show you exactly
> where that evidence is weaker than it sounds.

## Figures you should know without looking {#numbers}

<div class="stats">
<div><span class="n">1,079,680</span><span class="l">source rows in 8 files, counts match the published reference exactly</span></div>
<div><span class="n">124</span><span class="l">rules executed: 89 hand written + 35 completeness sweep; 19 fire</span></div>
<div><span class="n">14</span><span class="l">defect types: 1 block, 4 warn, 9 info</span></div>
<div><span class="n">1 / 440</span><span class="l">row quarantined / warn flags (on 352 distinct rows)</span></div>
<div><span class="n">21</span><span class="l">cleaning steps; exactly one removes a row (C14)</span></div>
<div><span class="n">20</span><span class="l">seeded defects, each caught by the rule meant to catch it</span></div>
<div><span class="n">7</span><span class="l">row level security policies on 7 core tables</span></div>
<div><span class="n">10 / 10</span><span class="l">Claude answers matching the reference (recorded 2026-10-25)</span></div>
</div>

| Area | Figure |
|---|---|
| Source tables | trans 1,056,320 · client 5,369 · disp 5,369 · account 4,500 · card 892 · loan 682 · order 6,471 · district 77 |
| Reconciliation | raw = stg on 11 checks; core = stg − quarantine on 9 (7 row counts, 2 money sums: transactions 6,257,793,560.30, loans 103,261,740.00) |
| Model | 4 dimensions from the source tables + a generated calendar (`dim_date`), 1 bridge, 2 base facts, 1 derived month-end fact (185,615 rows, 558 carried forward), 3 curated views |
| Semantic layer | 11 entities, 105 columns, 19 joins, 12 metrics, 7 caveats, 12 query rules, 10 glossary terms; delivered pack 33,662 characters |
| Problematic loans | status B or D: 76 of 682 = 11.14% (B 31, D 45) — A4, awaiting business confirmation |
| Visible rows | `cro_global` 5,369 clients · `rm_north` 1,481 · `rm_south` 1,387 (1,386 + 1 delegated) · `rm_unassigned` 0 · `client_3764` 1 |
| LLM runs | Claude Sonnet 5.5: 10 answered first attempt, 10 match. Ollama qwen2.5-coder:3b: 6 match, 2 partial (Q3, Q7), 2 mismatch (Q6, Q10) |
| Tests (delivered) | 327 passed, 1 skipped (full suite at `1b837fd`); `test_auth.py` 40 passed, 1 strict xfail (`b5b18f2`); 330 collected |
| Deliverables | Workbook 11 tabs · DDR 2 pages · ZIP 183 members · defect register 14 rows |

:::weak Numbers that differ between documents
Some delivered documents still quote older figures (137, 202 or 241 tests; "88 rules";
"PostgreSQL 16"; a 4m28s build time measured once on Linux). The authoritative figures are
the ones in `docs/DELIVERY_AUDIT.md` and on this page. If someone quotes an old number back
at you, say which one is current and where it is measured. Chapter 6 of the Lessons Learned document (L-14) lists every stale figure.
:::

## How evidence is labelled in this pack {#labels}

The project labels every claim by how it is known, and so does this guide.

| Label | Meaning |
|---|---|
| <span class="tag run">RUN</span> | Executed: a query, a build step or a test produced it |
| <span class="tag">CODE</span> | Read in the source at the cited place |
| <span class="tag">LLM</span> | Output of the named provider and model |
| <span class="tag disc">REC</span> | Recommended, not implemented |
| <span class="tag open">ASSUMED</span> | A business definition awaiting confirmation |
| <span class="tag post">POST</span> | Done after delivery; not in the delivered version |
