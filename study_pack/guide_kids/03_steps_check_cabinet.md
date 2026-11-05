# <span class="num">6</span>Step 4 — Traffic-light checks 🚦 {#k-step-checks}

<p class="lede">Check everything, give every kind of mistake a colour, and make sure the colour
actually does something.</p>

We wrote **124 checks** (89 written by hand, each with a reason, plus 35 automatic "is anything
empty?" checks). They look for empty boxes that should be filled, things written twice, entries
that point to a record book that doesn't exist, impossible values, and lists that disagree with
each other.

<div class="lights">
<div class="red"><b>🔴 Red — do not use</b>The line goes into the <b>"do not use" tray</b> with a note saying why. It never reaches the filing cabinet. 1 check fired, on <b>1 line</b>.</div>
<div class="orange"><b>🟠 Orange — careful</b>The line stays, but gets a <b>warning sticker</b>. The sticker travels all the way to the answer, so whoever reads it is warned. 6 checks fired: <b>440 stickers</b> on 352 lines.</div>
<div class="green"><b>🟢 Green — just noted</b>Untidy, but no answer changes. We tidy it and write it in the logbook. 12 checks fired.</div>
</div>

On the real paperwork, **19 checks** found something, which adds up to **14 kinds of mistakes**.

## The best example: same check, opposite colour {#k-zero}

> 14 entries are worth **zero points**. A check saying "an entry must be more than zero" sounds
> obviously right. But those 14 are real: bonus-point days where the bonus worked out to nothing.
> Making them red would break the running totals of 14 record books — to fix nothing. So they are
> **green**.
>
> An entry with **negative** points where it should be positive would be **red**, because then
> points move the wrong way.

## Proving the checks work {#k-prove}

- **The practice room:** 20 mistakes hidden on purpose, one for each kind of check. A test makes
  sure each one is caught by the check that is supposed to catch it. All 20 are caught.
- **Nothing lost:** the tidy pile has the same number of lines and the same point totals as the
  copy (11 comparisons). The filing cabinet equals the tidy pile minus the "do not use" tray
  (9 comparisons: 1,056,320 − 1 = 1,056,319 entries, and every point total equal).

:::weak Oops! — the practice mistakes almost removed real files
At one point the "do not use" tray did not say which pile a line came from. So when we ran the
practice room, its fake mistakes started blocking **real** lines: 76 topics instead of 77, and
11,024 entries pointing nowhere. The cabinet checks noticed before anything was handed in. Lesson:
a green tick doesn't mean it is right — check the result. (D008)
:::

:::weak Oops! — the red check can only catch zero-point twins
The "written twice" check needs two entries with the same book, day, type, points **and the same
total afterwards**. But a real double entry changes the total, so the second copy never matches.
The check can only catch twins worth zero points — and the one line in the tray is a 0.00 entry.
Meanwhile 1,081 groups of identical bonus-point entries on the same day have no sticker at all
(157,289.70 points). Are they mistakes? Only the school office can say. (L-04)
:::

:::weak Oops! — some orange stickers were our own fault
Of the 55 record books whose totals "didn't add up by more than 100", **41** only looked wrong
because of the "who wrote last?" puzzle in chapter 7. (L-03)
:::

:::evidence In grown-up words
`dq/dq_rules.yaml` (89 rules) + 35 completeness sweep = 124 executed; 19 fire (block 1, warn 6,
info 12) = 14 defect types. Quarantine 1 row (`UNQ_TRANS_BUSINESS_KEY`), 440 warn flags on 352
rows, injector 20/20 (`tests/test_dq.py`). Reconciliation 11 + 9 checks. D004, D008, A20, A30.
:::

# <span class="num">7</span>Step 5 — The filing cabinet 🗄️ {#k-step-cabinet}

<p class="lede">Neat drawers, each with a clear rule about what one card means, and every important
word decided in exactly one place.</p>

## The drawers {#k-drawers}

| Drawer | One card means | Cards |
|---|---|---:|
| Pupils | one pupil | 5,369 |
| Record books | one record book | 4,500 |
| Topics | one topic | 77 |
| Calendar | one day (1993–1998) | 2,191 |
| Badges | one badge | 892 |
| Who may use which book | one owner-or-helper link | 5,369 |
| Entries | one entry | 1,056,319 |
| Study plans | one study plan | 682 |
| Month-end totals | one record book on one last-day-of-the-month | 185,615 |

**Why "one card means one thing" matters.** If the pupil drawer accidentally had a pupil twice,
*every* count of pupils would be too high, and nothing would warn you. The robot would happily
give a confident wrong number. So we check this every time.

**Why drawers instead of one giant list?** The questions are about four different things —
pupils, record books, study plans, entries. In one giant list, a pupil would appear once for
every entry, and every "how many pupils" would need a trick (`count distinct`) that robots often
get wrong without noticing.

## One word, one meaning, decided here {#k-words}

| Word | Means |
|---|---|
| The **owner** of a record book | The one pupil the book belongs to — exactly one per book. A helper who may sign in it is *not* the owner |
| A study plan that **went wrong** | Status B (finished, not passed) or D (running, falling behind): 76 of 682 |
| **Points coming in** | Entries that add points (`PRIJEM`), counted as positive numbers |
| The **month-end total** | The total after the last entry on or before the last day of the month; if there was no entry that month, last month's total is carried over |

## The puzzle: who wrote last? 🧩 {#k-puzzle}

Sometimes a record book has several entries **on the same day**, and the paperwork doesn't say at
what time. So which one was last — and what was the total at the end of that day?

We decided: *the one with the highest entry number*. But entry numbers are **not** in time order.
The school's bonus points get high numbers, yet they are written *before* the end-of-month fee.

There was a better clue all along: every entry says what the total was **after** it. So the next
entry must start where the previous one ended — like dominoes.

<div class="dominoes">
<div>start: 10,500.00</div><span>→</span>
<div>+1.30 bonus<br><small>number 3,467,643</small><br>total 10,501.30</div><span>→</span>
<div class="last">−1,200.00 taken out<br><small>number 1,137,901</small><br>total 9,301.30</div>
</div>

That is record book **3888** on 31 January 1998. The bonus has the higher number, so our rule said
"10,501.30". The dominoes say the withdrawal came last: **9,301.30**.

:::weak Oops! — our most exciting mistake was our own
Our report said this record book was "off by exactly 1,200 — an entry must be missing!". It wasn't
missing at all: it was our own wrong "who was last" rule. That story is even written in the robot's
dictionary. The highest number was right only **0.4%** of the times the dominoes could decide.
(L-01, L-02)
:::

:::post Later we fixed it
After handing in the homework, we switched to the domino rule: the end of the chain is the last
entry; if the dominoes can't decide, we mark the day "ambiguous". The average month-end total in
December 1998 moved from 43,808.94 to 43,810.47 (+1.53), but 107 record books changed, by up to
1,200. Material "doesn't add up" stickers went from 55 to 14. (D028)
:::

:::say Try saying it
"The average was robust to the rule — within two points — but individual record books were not.
That's why the rule had to change, and why 'we can't know the order' should have been tested
instead of written down."
:::

:::evidence In grown-up words
`core` star schema: `dim_client`, `dim_account`, `dim_district`, `dim_date`, `dim_card`,
`bridge_disposition`, `fact_transaction`, `fact_loan`, `fact_account_month_end_balance` (185,615
rows, 558 carried forward), curated views `v_account_owner`, `v_loan_enriched`, `v_client_region`.
D007 natural keys, D019 month-end with highest-`trans_id` tie-break (A14, caveat C2), D012
rebuild restores the ai views.
:::
