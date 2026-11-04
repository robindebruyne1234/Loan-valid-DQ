# <span class="num">15</span>The ten questions, one by one {#questions}

<p class="lede">For each question: the delivered reference answer, the interpretation it
implements, the trap, how sensitive the answer is to the interpretation, what Claude wrote, and
how to say it in two sentences. Reference figures are from the delivered
<code>reference_results.json</code>; sensitivities were measured on the same data.</p>

## Q1 — How many clients do we have per region? {#q1}

[[ref_table:Q1]]

- **Interpretation:** the region of the **client's own district** (A1), counting **all 5,369
  clients**, including the 869 who only hold a disponent relationship (A2). Region via
  `ai.client` → district.
- **Trap:** counting through dispositions or accounts (4,500, or duplicates); using the
  account's district; forgetting disponent-only clients.
- **Sensitivity:** places 3–5 are within four clients (664 / 663 / 660), so the order depends on
  the definition. Owners only, by client district: east Bohemia (556) passes Prague (547). Owners
  only, by account district: north Moravia (793) passes south Moravia (778). 409 owners live in a
  different district from their account's (info rule, caveat C4).
- [[verdicts:Q1]]

[[llm_sql:Q1]]

:::say
"A client is a person and a person lives in one district, so I count all 5,369 by where they
live. 409 owners bank elsewhere; the other reading is one join away and changes places 3 to 5."
:::

## Q2 — What is the total amount of loans granted per year? {#q2}

[[ref_table:Q2]]

- **Interpretation:** "granted" is dated by the loan start date, the only date the loan table
  has; "total amount" is the sum of the **principal**, not payments × duration (A3).
- **Trap:** summing `monthly_payment × duration` (the total repayable, 10–20% higher); dating
  by the account; treating the date as text.
- **Watch:** 1993 is a half year — the earliest loan is 1993-07-05. 1997 is the peak at
  30.7 million. Total 103,261,740 over 682 loans.
- [[verdicts:Q2]]

[[llm_sql:Q2]]

## Q3 — What percentage of our loans are problematic? {#q3}

[[ref_table:Q3]]

- **Interpretation:** status **B** (finished, unpaid) or **D** (running, in debt), divided by
  **all** loans (A4, **awaiting business confirmation**). Certified as `is_problematic`.
- **Trap:** only B (31/682 = 4.55%), only D, integer division, mixing count and amount.
- **Sensitivity:** by **value** instead of count it is 15.09% — problematic loans are larger.
  95% Wilson interval for the count share: 9.0–13.7%.
- [[verdicts:Q3]]

[[llm_sql:Q3]]

## Q4 — What is the average loan amount per card type of the account owner? {#q4}

[[ref_table:Q4]]

- **Interpretation:** the card on the **owner's** disposition (A5); loans whose owner has no card
  are an explicit `no card` group, so the counts add up to 682 (A6). Per loan, not per card.
- **Critical reading:** *junior* tops it on only 21 loans whose owners average 17.4 years old at
  loan start (10 under 18). It is mechanically correct and probably a data artefact, not an
  insight — report it with n and the age caveat. On this data no card is held by a disponent, so
  "owner's card vs any card" changes nothing.
- [[verdicts:Q4]]

[[llm_sql:Q4]]

## Q5 — Which 10 districts had the highest total incoming transaction amount in 1997? {#q5}

[[ref_table:Q5,10]]

- **Interpretation:** credits only (`direction = 'credit'`, source `PRIJEM`), unsigned amount,
  postings dated 1997, grouped by the **account's** district (A7, A8). Ranked with `rank()` so
  ties would show.
- **Trap:** treating `VYBER` as incoming; summing `signed_amount` (net flow is a different
  question); using the client's district without saying so.
- **Sensitivity:** excluding bank interest (`UROK`) keeps the same ten in the same order (A7;
  whether interest is "incoming money" is an open business question). By the owner's district,
  ranks 2–3 swap and the tenth place changes. Number 11 (Louny, 12,134,490.00) is 28,657 behind.
- [[verdicts:Q5]]

[[llm_sql:Q5]]

## Q6 — How many new accounts were opened per month in 1996? {#q6}

[[ref_table:Q6]]

- **Interpretation:** accounts by month of `open_date`, all twelve months shown, driven from the
  calendar so a month without accounts would read 0 (A9). Total 1,363.
- **Trap:** grouping only accounts (an empty month disappears); grouping month names across
  years; the fan-out the local model fell into (joining to every day of the month).
- [[verdicts:Q6]]

[[llm_sql:Q6]]

## Q7 — Average age of the account owner at loan start, per loan status {#q7}

[[ref_table:Q7]]

- **Interpretation:** the owner (OWNER disposition, A11) at the loan date, in **exact
  fractional years** (A10); the six loans to owners recorded as under 15 are reported with and
  without (warn rule, caveat C3).
- **Trap:** not decoding the women's birth month (+50); using today's date; truncating to whole
  years (about 0.5 years low); using a disponent.
- **Small difference to know:** Claude's answer shows B = 39.61 against the reference 39.60,
  because `ai.loan` rounds each row's age to two decimals before the model averages it. Within
  the 0.011 tolerance; name it if asked (L-13).
- [[verdicts:Q7]]

[[llm_sql:Q7]]

## Q8 — Gender split of account owners holding a gold card {#q8}

[[ref_table:Q8]]

- **Interpretation:** owner rows whose own disposition holds a gold card (A12); the unit is the
  owner row, with distinct clients reported beside it (A13). Gender is derived from the birth
  number (A18, D016) — labelled derived, not observed.
- **Robustness:** all 88 gold cards are on owner dispositions; no client holds two.
- [[verdicts:Q8]]

[[llm_sql:Q8]]

## Q9 — Average account balance at the end of December 1998 {#q9}

[[ref_table:Q9]]

- **Interpretation:** each account's balance after its last posting on or before 1998-12-31,
  from the month-end fact (A14); the average is over accounts with a known balance — none counted
  as zero (A15). 76 accounts had no December posting and carry November forward.
- **Typical wrong answers:** joining on `max(date)` without a tie-break duplicates rows (4,707
  rows, average 43,508.31); only accounts with a December posting (4,424, 44,209.53); averaging
  every December posting (23,553 rows, 46,908.00).
- **The known limitation:** same-day ties are broken by the highest `trans_id`, which is not
  chronological (C2). Disclosed at delivery. Under the balance-chain rule implemented after
  delivery the average is 43,810.47 (+1.53 CZK); 107 accounts close differently, by up to
  1,200.00 CZK — the "missing posting" of caveat C1 (L-01, L-02).
- [[verdicts:Q9]]

[[llm_sql:Q9]]

:::say
"43,809 CZK over all 4,500 accounts, 76 of them carried forward from November. I disclosed that
the closing posting of a busy day is decided by a tie-break; after submitting I replaced it with
the running-balance chain — the average moves by 1.53 CZK, individual accounts by up to 1,200."
:::

## Q10 — Which statement frequency has the highest share of problematic loans? {#q10}

[[ref_table:Q10]]

- **Interpretation:** a **within-frequency rate** — problematic loans divided by all loans of
  accounts with that frequency (A16) — not each frequency's share of all problematic loans.
- **Trap:** the share of all problematic loans makes *monthly* the winner (59 of 76 = 77.6%):
  the wrong question. The local model made a related mistake (absolute count → monthly).
- **Critical reading:** the winner rests on 6 of 32 loans; 95% Wilson interval 8.9–35.3%; Fisher
  exact test against the rest, two-sided p ≈ 0.155. *Highest observed, not significant.*
- [[verdicts:Q10]]

[[llm_sql:Q10]]

:::say
"After-transaction statements have the highest observed rate, 18.75% — but on 32 loans with an
interval of 9 to 35%, so I would not tell the business it is riskier, only that it is worth
watching."
:::
