# Data quality report

- run_id: `116e896d-afb0-4ddf-8119-c059382d5394`
- dataset: `stg`
- executed at: 2026-10-25T07:51:23+00:00 (git da3e93f)
- command: `make dq`
- rules executed: **124** (19 fired, 105 clean, 0 errored)

## Executive summary

| severity | defect types firing | rows affected | what it means |
|---|---:|---:|---|
| **block** | 1 | 1 | rows quarantined, excluded from core and from the ai views |
| **warn** | 6 | 440 | rows kept and flagged, metrics carry a caveat |
| **info** | 12 | 2,556,194 | standardised and logged, no answer changes |

Rows quarantined this run: **1** (trans: 1)

## Findings by severity

### block (1 firing)

| rule | table | rows | rate | questions | defect |
|---|---|---:|---:|---|---|
| `UNQ_TRANS_BUSINESS_KEY` | trans | 1 | 0.0001% | Q5, Q9 | Duplicate transaction by business key (distinct id, identical content) |

**`UNQ_TRANS_BUSINESS_KEY`** -- Duplicate transaction by business key (distinct id, identical content)

- severity rationale: Two postings on the same account, same date, same type, same operation, same amount and the same resulting balance are the same event recorded twice: a genuinely distinct second posting would have moved the balance. The primary key cannot catch this, which is exactly why the rule exists. It double counts flows in Q5 and breaks the balance chain behind Q9. One instance fires on this copy of the data.
- handling: Keep the lowest trans_id, quarantine the rest with the reason naming the surviving row, so the decision is auditable rather than implicit.
- example: key `3507085` -- identical to trans_id 3456218 (account 9051, 1998-02-28, amount 0.00, balance 1367.10); group size 2

### warn (6 firing)

| rule | table | rows | rate | questions | defect |
|---|---|---:|---:|---|---|
| `CON_INTRADAY_ORDER_AMBIGUOUS` | trans | 183 | 4.0667% | Q9 | Closing balance of the account's last day is not uniquely determined |
| `VAL_OWNER_AGE_AT_ACCOUNT_OPEN` | client | 114 | 2.5333% | Q7, Q8 | Account owner was younger than 15 at account opening |
| `CON_BALANCE_RECONCILIATION_ROUNDING` | trans | 81 | 1.8000% | Q9 | Per-account balance chain off by more than 1 CZK but at most 100 CZK |
| `CON_BALANCE_RECONCILIATION_MATERIAL` | trans | 55 | 1.2222% | Q9 | Per-account balance chain off by more than 100 CZK |
| `VAL_OWNER_AGE_AT_LOAN_START` | loan | 6 | 0.8798% | Q7 | Account owner was younger than 15 at loan start |
| `COMP_TRANS_PARTNER_ON_TRANSFER` | trans | 1 | 0.0004% | - | Counterparty missing on a transfer posting |

**`CON_INTRADAY_ORDER_AMBIGUOUS`** -- Closing balance of the account's last day is not uniquely determined

- severity rationale: trans_id is not chronological within a date, so when an account has several postings on one day there is no way to tell which one closed the day. For 183 accounts that ambiguity falls on their most recent date, which is precisely the balance Q9 reports. The answer is therefore a documented choice (highest trans_id on the latest date) rather than a fact, and the count of affected accounts belongs next to the answer. Warn: the data is not wrong, the determinism is missing.
- handling: Tie-break documented in the semantic layer and applied identically in the reference SQL and in core.fact_account_month_end_balance; affected accounts flagged so the caveat can be quantified.
- example: key `19` -- account has 2 postings on its latest date 1998-12-31; the closing balance depends on the tie-break

**`VAL_OWNER_AGE_AT_ACCOUNT_OPEN`** -- Account owner was younger than 15 at account opening

- severity rationale: 114 owners were under 15 when their account was opened, the youngest 10.3 years. A ten year old cannot be the legal holder of a current account, so either the birth number or the owner flag is wrong. It is warn rather than block because the accounts and their transactions are otherwise well-formed and feed Q5, Q6 and Q9 correctly: quarantining 114 accounts to protect the age metric would damage four answers to improve one. Q7 and Q8 report their coverage instead.
- handling: Rows kept and flagged (_dq_flags carries 'owner_age_implausible'); the semantic layer attaches the caveat to the age metric so the LLM can repeat it.
- example: key `12` -- owner was 11.9 years old when account 9 was opened

**`CON_BALANCE_RECONCILIATION_ROUNDING`** -- Per-account balance chain off by more than 1 CZK but at most 100 CZK

- severity rationale: Tested order independently: the sum of all signed amounts on an account should equal its last reported balance, whatever order the postings are read in. 136 accounts breach a 1 CZK tolerance; 81 of those are within 100 CZK and sit in the rounding band (every amount in the source carries a single decimal, so residuals accumulate). Warn, because the account is still usable and the Q9 average moves by cents; the band is reported so nobody confuses it with the material tier below.
- handling: Account flagged; the month-end balance fact carries the residual so a user can see the size of the discrepancy next to the balance.
- example: key `31` -- sum(signed_amount) = 13298.70 but last reported balance = 13312.90 (difference -14.20)

**`CON_BALANCE_RECONCILIATION_MATERIAL`** -- Per-account balance chain off by more than 100 CZK

- severity rationale: 55 accounts are off by more than 100 CZK and one by exactly 1,200.00 CZK with only 55 postings, which is a missing or extra posting rather than rounding. This is the single most material finding for Q9, because the answer is an average balance and these accounts' balances cannot be derived from their own flows. It stays warn rather than block on purpose: the balance column is what Q9 reads, and it is internally plausible -- it is the *flows* that disagree with it. Quarantining the accounts would remove real balances from an average; blocking the postings would break the chain further. The defensible treatment is to publish the answer with the affected population and the residual attached, which is what the semantic layer makes the LLM do.
- handling: Account flagged as balance_unreconciled; Q9 reports the average together with the number of affected accounts and the total residual, so the reader can size the uncertainty instead of guessing at it.
- example: key `1012` -- sum(signed_amount) = 43350.40 but last reported balance = 43192.30 (difference 158.10)

**`VAL_OWNER_AGE_AT_LOAN_START`** -- Account owner was younger than 15 at loan start

- severity rationale: 6 loans were granted to owners recorded as under 15. Q7 reports exactly this number -- the average age of the owner at loan start, per status -- so these rows pull the answer directly. Warn rather than block because the loan amount and status are themselves sound and feed Q2, Q3, Q4 and Q10: removing the loans would make the certified loan total disagree with the source. Q7 publishes the flagged count next to the average, which is the honest treatment of a value that is probably wrong but not certainly so.
- handling: Rows kept and flagged; Q7 reports the average with and without the flagged loans so the sensitivity is visible.
- example: key `6153` -- owner was 14.6 years old at loan start

**`COMP_TRANS_PARTNER_ON_TRANSFER`** -- Counterparty missing on a transfer posting

- severity rationale: This is the non-structural half of the rule above: a remittance or collection (PREVOD NA UCET / PREVOD Z UCTU) with no counterparty is a genuine gap, because a transfer by definition has another side. No certified metric reads it today, but it is evidence of a broken feed rather than a design choice, so it is warn and not info.
- handling: Row kept and flagged; counted separately from the structural NULLs.
- example: key `236564` -- transfer posting without counterparty; operation = PREVOD NA UCET

### info (12 firing)

| rule | table | rows | rate | questions | defect |
|---|---|---:|---:|---|---|
| `COMP_TRANS_PARTNER_STRUCTURAL` | trans | 760,931 | 72.0360% | - | Counterparty bank and account absent for non-transfer postings |
| `COMP_RAW_MISSING_ENCODING_INCONSISTENT` | trans | 535,314 | 50.6773% | - | The same column encodes 'missing' three different ways in the source |
| `COMP_NULL__trans__k_symbol_code` | trans | 535,314 | 50.6773% | - | Missing value in trans.k_symbol_code |
| `COMP_NULL__trans__k_symbol_label` | trans | 535,314 | 50.6773% | - | Missing value in trans.k_symbol_label |
| `COMP_TRANS_OPERATION_STRUCTURAL` | trans | 183,114 | 17.3351% | - | Transaction operation absent (structurally, for interest postings) |
| `VAL_TRANS_BALANCE_NEGATIVE` | trans | 2,999 | 0.2839% | Q9 | Balance after the transaction is negative (overdraft) |
| `COMP_NULL__order__k_symbol_code` | order | 1,379 | 21.3105% | - | Missing value in order.k_symbol_code |
| `COMP_NULL__order__k_symbol_label` | order | 1,379 | 21.3105% | - | Missing value in order.k_symbol_label |
| `CON_CLIENT_ACCOUNT_DISTRICT_MISMATCH` | disp | 409 | 9.0889% | Q1, Q5 | Owner's own district differs from the district of the account they own |
| `UNQ_CLIENT_SAME_BIRTH_DISTRICT` | client | 26 | 0.4843% | Q1, Q8 | Two clients share birth number and district (possible duplicate person) |
| `VAL_TRANS_AMOUNT_POSITIVE` | trans | 14 | 0.0013% | - | Transaction amount is zero or negative |
| `COMP_DISTRICT_1995_PLACEHOLDER` | district | 1 | 1.2987% | - | Placeholder '?' in the 1995 unemployment and crime columns |

**`COMP_TRANS_PARTNER_STRUCTURAL`** -- Counterparty bank and account absent for non-transfer postings

- severity rationale: 760,931 postings have neither partner bank nor partner account. These are cash operations and bank-generated postings, which have no counterparty by construction. No question reads the counterparty. Reported as info with the cross-check that it never happens on a transfer operation, which is the version of this that *would* be a defect.
- handling: Left as NULL by design; documented as structural in the semantic layer.
- example: key `695247` -- partner_bank and partner_account are both NULL; operation = VKLAD

**`COMP_RAW_MISSING_ENCODING_INCONSISTENT`** -- The same column encodes 'missing' three different ways in the source

- severity rationale: In raw.trans.k_symbol, "no category" arrives as a quoted empty string (481,871 rows), as an unquoted empty field that loads as NULL (10 rows) and as a single space. The three spellings mean one thing. No answer changes because stg collapses them, but it is reported because any consumer reading raw directly -- including an LLM pointed at the wrong layer -- would have to know about all three to filter correctly. That is exactly the kind of knowledge a semantic layer exists to remove.
- handling: Collapsed to a single NULL by stg.norm_text; the raw spelling is kept in k_symbol_raw. Rule runs against raw, so it keeps reporting even after stg is clean.
- example: key `695247` -- k_symbol encodes missing as []

**`COMP_NULL__trans__k_symbol_code`** -- Missing value in trans.k_symbol_code

- severity rationale: No answer to the 10 questions reads this column, so a null here cannot change a reported number. It is logged with its null rate so that the next metric built on this column starts from a known baseline, and it is promoted to warn or block the moment a metric does read it.
- handling: Normalised to a real NULL in stg (placeholders '?', '', 'NA' and a bare space all collapse), original text preserved in the matching *_raw audit column, null rate published in dq/results/profile.md.
- example: key `808671` -- k_symbol_code is NULL

**`COMP_NULL__trans__k_symbol_label`** -- Missing value in trans.k_symbol_label

- severity rationale: No answer to the 10 questions reads this column, so a null here cannot change a reported number. It is logged with its null rate so that the next metric built on this column starts from a known baseline, and it is promoted to warn or block the moment a metric does read it.
- handling: Normalised to a real NULL in stg (placeholders '?', '', 'NA' and a bare space all collapse), original text preserved in the matching *_raw audit column, null rate published in dq/results/profile.md.
- example: key `808671` -- k_symbol_label is NULL

**`COMP_TRANS_OPERATION_STRUCTURAL`** -- Transaction operation absent (structurally, for interest postings)

- severity rationale: 183,114 postings have no operation. Every one of them is an interest credit (k_symbol = UROK): the bank's own interest run has no customer operation behind it, so the NULL means "not applicable" rather than "unknown". None of the 10 questions groups by operation. It is reported as info precisely so that nobody later imputes a value into it, which would invent an operation that never happened.
- handling: Left as NULL by design, labelled 'not applicable (bank-generated posting)' in the semantic layer so an LLM does not treat it as missing.
- example: key `3591421` -- operation_code is NULL; k_symbol = UROK

**`VAL_TRANS_BALANCE_NEGATIVE`** -- Balance after the transaction is negative (overdraft)

- severity rationale: 2,999 postings leave a negative balance. This is overdraft, which is normal banking, not a defect -- and it matters that the rule says so, because the tempting "fix" (clipping balances at zero) would bias the Q9 average upwards. Reported as info so the number is known and explicitly not acted on.
- handling: Logged only; balances are never clipped.
- example: key `3452127` -- balance_after = -13466.40

## Rules that did not fire

These rules found nothing on this copy of the data. They ship anyway:
the bank's own copy may carry exactly these defects, and a rule that
only exists after the incident is not a control.

| rule | severity | defect |
|---|---|---|
| `COMP_ACCOUNT_FREQUENCY_MISSING` | warn | Statement frequency missing |
| `COMP_ACCOUNT_ID_MISSING` | block | Account identifier missing |
| `COMP_ACCOUNT_OPEN_DATE_MISSING` | block | Account opening date missing |
| `COMP_CARD_TYPE_MISSING` | warn | Card type missing |
| `COMP_CLIENT_BIRTH_MISSING` | warn | Client birth date or gender not derivable from birth_number |
| `COMP_CLIENT_DISTRICT_MISSING` | warn | Client district missing |
| `COMP_CLIENT_ID_MISSING` | block | Client identifier missing |
| `COMP_DISP_KEY_MISSING` | block | Disposition key, client or account missing |
| `COMP_DISP_TYPE_MISSING` | block | Disposition type (owner or disponent) missing |
| `COMP_DISTRICT_REGION_MISSING` | block | District name or region missing |
| `COMP_LOAN_AMOUNT_MISSING` | block | Loan amount missing |
| `COMP_LOAN_DATE_MISSING` | block | Loan start date missing |
| `COMP_LOAN_KEY_MISSING` | block | Loan identifier or account reference missing |
| `COMP_LOAN_STATUS_MISSING` | block | Loan status missing |
| `COMP_TRANS_AMOUNT_MISSING` | block | Transaction amount missing |
| `COMP_TRANS_BALANCE_MISSING` | warn | Balance after transaction missing |
| `COMP_TRANS_DATE_MISSING` | block | Transaction date missing |
| `COMP_TRANS_KEY_MISSING` | block | Transaction identifier or account reference missing |
| `CON_CARD_BEFORE_ACCOUNT_OPEN` | warn | Card issued before the account was opened |
| `CON_CARD_HELD_BY_DISPONENT` | info | Card is held by a disponent rather than by the account owner |
| `CON_GENDER_MATCHES_BIRTH_NUMBER` | block | Decoded gender disagrees with the birth_number month encoding |
| `CON_INTEREST_WITHOUT_OPERATION` | info | Interest posting carries an operation (or a non-interest posting carries none) |
| `CON_LOAN_BEFORE_ACCOUNT_OPEN` | block | Loan starts before the account was opened |
| `CON_LOAN_PAYMENT_SCHEDULE` | warn | monthly_payment * duration does not equal the loan amount |
| `CON_TRANS_BEFORE_ACCOUNT_OPEN` | warn | Transaction posted before the account was opened |
| `CON_TYPE_OPERATION_DIRECTION` | block | Operation contradicts the credit/debit direction of the transaction type |
| `REC_AMOUNT_SUM_RAW_TO_STG` | block | Sum of amounts differs between raw and stg |
| `REC_LOAN_STATUS_DISTRIBUTION` | info | Problematic loan count differs from the published reference figure |
| `REC_ROWCOUNT_RAW_TO_STG` | block | Row count differs between raw and stg |
| `RI_ACCOUNT_DISTRICT` | block | Account references a district that does not exist |
| `RI_ACCOUNT_WITHOUT_OWNER` | block | Account has no OWNER disposition |
| `RI_ACCOUNT_WITHOUT_TRANS` | warn | Account has no transactions |
| `RI_CARD_DISP` | block | Card references a disposition that does not exist |
| `RI_CLIENT_DISTRICT` | block | Client references a district that does not exist |
| `RI_CLIENT_WITHOUT_DISP` | warn | Client has no disposition on any account |
| `RI_DISP_ACCOUNT` | block | Disposition references an account that does not exist |
| `RI_DISP_CLIENT` | block | Disposition references a client that does not exist |
| `RI_DISTRICT_WITHOUT_CLIENT` | info | District has no clients and no accounts |
| `RI_LOAN_ACCOUNT` | block | Loan references an account that does not exist |
| `RI_ORDER_ACCOUNT` | block | Standing order references an account that does not exist |
| `RI_TRANS_ACCOUNT` | block | Transaction references an account that does not exist |
| `UNQ_ACCOUNT_PK` | block | Duplicate account_id |
| `UNQ_ACCOUNT_SINGLE_OWNER` | block | Account has more than one OWNER disposition |
| `UNQ_CARD_ONE_PER_DISP` | warn | Disposition holds more than one card |
| `UNQ_CARD_PK` | block | Duplicate card_id |
| `UNQ_CLIENT_PK` | block | Duplicate client_id |
| `UNQ_DISP_PK` | block | Duplicate disp_id |
| `UNQ_DISTRICT_PK` | block | Duplicate district_id |
| `UNQ_LOAN_ONE_PER_ACCOUNT` | warn | Account has more than one loan |
| `UNQ_LOAN_PK` | block | Duplicate loan_id |
| `UNQ_ORDER_PK` | block | Duplicate order_id |
| `UNQ_TRANS_PK` | block | Duplicate trans_id |
| `VAL_ACCOUNT_OPEN_DATE_UNPARSABLE` | block | Account opening date present in the source but not a real date |
| `VAL_BIRTH_DATE_PLAUSIBLE` | warn | Client birth date outside a plausible range for a 1990s bank client |
| `VAL_BIRTH_NUMBER_DECODABLE` | warn | birth_number does not decode (bad month, impossible day, wrong length) |
| `VAL_CARD_ISSUED_UNPARSABLE` | warn | Card issue date present in the source but not a real date |
| `VAL_CARD_TYPE_DOMAIN` | block | Card type outside the allowed set junior, classic, gold |
| `VAL_DATE_OUT_OF_RANGE` | block | Business date outside the dataset's plausibility window (1993-01-01 to 1998-12-31) |
| `VAL_DISP_TYPE_DOMAIN` | block | Disposition type outside the allowed set OWNER, DISPONENT |
| `VAL_DISTRICT_NUMERIC_NONNEGATIVE` | info | District demographic figure is negative |
| `VAL_FREQUENCY_DOMAIN` | block | Statement frequency outside the allowed set |
| `VAL_GENDER_DOMAIN` | block | Decoded gender outside the allowed set |
| `VAL_KSYMBOL_DOMAIN` | info | Transaction category (k_symbol) outside the documented set |
| `VAL_LOAN_AMOUNT_POSITIVE` | block | Loan amount is zero or negative |
| `VAL_LOAN_DATE_UNPARSABLE` | block | Loan start date present in the source but not a real date |
| `VAL_LOAN_DURATION_DOMAIN` | block | Loan duration outside the offered terms (12, 24, 36, 48, 60 months) |
| `VAL_LOAN_PAYMENT_POSITIVE` | warn | Monthly payment is zero or negative |
| `VAL_LOAN_STATUS_DOMAIN` | block | Loan status outside the allowed set A, B, C, D |
| `VAL_ORDER_AMOUNT_POSITIVE` | info | Standing order amount is zero or negative |
| `VAL_ORDER_KSYMBOL_DOMAIN` | info | Standing order category (k_symbol) outside the documented set |
| `VAL_TRANS_AMOUNT_NEGATIVE` | block | Transaction amount is negative |
| `VAL_TRANS_DATE_UNPARSABLE` | block | Transaction date present in the source but not a real date |
| `VAL_TRANS_OPERATION_DOMAIN` | warn | Transaction operation outside the documented set |
| `VAL_TRANS_TYPE_DOMAIN` | block | Transaction type outside the allowed set PRIJEM, VYDAJ, VYBER |

## Reconciliation

| metric | entity | raw | stg | quarantined | balanced |
|---|---|---:|---:|---:|---|
| row_count | account | 4,500 | 4,500 | 0 | yes |
| row_count | client | 5,369 | 5,369 | 0 | yes |
| row_count | disp | 5,369 | 5,369 | 0 | yes |
| row_count | card | 892 | 892 | 0 | yes |
| row_count | loan | 682 | 682 | 0 | yes |
| row_count | order | 6,471 | 6,471 | 0 | yes |
| row_count | trans | 1,056,320 | 1,056,320 | 1 | yes |
| row_count | district | 77 | 77 | 0 | yes |
| amount_sum | trans.amount | 6,257,793,560.30 | 6,257,793,560.30 | - | yes |
| amount_sum | loan.amount | 103,261,740.00 | 103,261,740.00 | - | yes |
| amount_sum | order.amount | 21,228,993.60 | 21,228,993.60 | - | yes |

