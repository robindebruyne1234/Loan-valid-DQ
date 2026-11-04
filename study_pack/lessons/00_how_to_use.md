# <span class="num">1</span>How to use this document {#use}

<p class="lede">A walkthrough that defends design choices always reaches the question "what went
wrong?". This document prepares that conversation: every mistake, weak spot and sloppy detail
found in the delivered version, checked against the code, the evidence files or the database,
with its impact, its status and a way to say it.</p>

## What was checked, and how {#method}

- The **delivered version** is branch `delivery-freeze-2026-10-28`, commit `fc0c281` (code
  `b5b18f2`). Every finding refers to that version unless it is marked as history or as work
  after delivery.
- Code claims were read in the delivered tree at the cited line. Data claims were re-run on
  2026-11-04 against a database whose `sql/` is identical to the delivered one except for the
  month-end fact (changed after delivery); figures that depend on the old month-end rule were
  recomputed with the old rule explicitly.
- Findings already listed in `docs/DELIVERY_AUDIT.md` are marked as **disclosed**. Findings
  that the delivered documents do not mention, or state wrongly, are marked **not disclosed**.
  That second group is the one to prepare most carefully.

## Status and severity {#legend}

| Status | Meaning |
|---|---|
| <span class="tag fixed">FIXED BEFORE DELIVERY</span> | Found and fixed during the build; a test or a decision record guards it |
| <span class="tag disc">DISCLOSED</span> | Open in the delivered version, and the delivered documents say so |
| <span class="tag open">NOT DISCLOSED</span> | Open in the delivered version, and the delivered documents do not say so — or say the opposite |
| <span class="tag post">FIXED AFTER DELIVERY</span> | Fixed on branch `ccr-46f6f45a-t9wtd4` after the freeze; not in what was submitted |

| Severity | Meaning |
|---|---|
| **High** | Changes a delivered number, a stated defect, or a security or correctness claim |
| **Medium** | Weakens the evidence behind a claim, or a privacy property for some users |
| **Low** | Labelling, wording, hygiene; no number or property changes |

## How to talk about a mistake {#talk}

Use the same five beats every time, and keep each to one sentence:

1. **What happened** — plainly, without softening words.
2. **How it was found** — ideally by a check you built, which is itself the point.
3. **What it cost** — measured: which number moved and by how much, who was affected.
4. **What changed** — the fix, or why it is not fixed yet and what fixing it takes.
5. **The lesson** — the general rule you now apply.

:::say An example, the month-end tie-break
"I broke same-day ties by the highest transaction id and documented it as a limitation. When I
went back, I found the running balance actually records the order, and the highest id was right
only 0.4% of the time. The average barely moved — 1.53 CZK — but 107 accounts' closing balances
were wrong by up to 1,200 CZK, and one of my own 'defects' turned out to be that artefact. I
fixed it after delivery with the balance chain and a test. The lesson: 'unknowable' is a
hypothesis; test it before you document it."
:::

:::danger Avoid
Minimising ("it's only 2 CZK"), blaming the tool ("the AI wrote it"), or apologising at length.
You directed the build and you checked it; own the result, give the number, give the fix.
:::

## The five to raise yourself {#raise}

Interviewers trust a candidate who names the weak spots before being asked. Raise these during
the presentation, at the slide where they belong:

| # | Raise it at | Finding |
|---:|---|---|
| 1 | The model / Q9 | The month-end tie-break, and that the "1,200 CZK missing posting" was its artefact (L-01, L-02) |
| 2 | The LLM path | A guard pass is not correctness; the gender query that passed the guard and failed in the database (L-07) |
| 3 | The results | Why 10/10 is weaker evidence than it sounds (L-08) |
| 4 | Entitlements | The disponent sees the owner's card, and hidden values become false values (L-05, L-06) |
| 5 | The opening or the close | Scope against a 1–2 day brief, and what you would cut (L-19) |
