# Berka governed data product -- semantic layer v1.0.0

A governed, entitlement-aware view of a Czech retail bank's 1993-1998 book: clients, accounts, dispositions, cards, loans, standing orders and 1.06 million transactions. Every entity below has been cleaned against 124 data quality rules; rows that broke a key, a join path or a certified metric were quarantined and are not present.

- SQL dialect: **postgresql 16**
- Query only the **`ai`** schema.
- All money is in **CZK**. Every monetary column is in Czech koruna. There is no currency column and no conversion anywhere in the product (assumption A19).
- Data covers **1993-01-01 to 1998-12-31**. The book ends on 1998-12-31. A question about a later period has no data, and the honest answer is to say so rather than to return an empty result as if it were a zero.

## Rules you must follow

QR1. **Read only from the `ai` schema. Never reference `core`, `stg`, `raw`, `dq`, `sec` or `inject`.**  
   _Why:_ The ai schema is the governed surface: business names, decoded labels, documented grains. The other schemas are internal and their shapes change.
QR2. **Emit exactly one statement, a single SELECT (a leading WITH is fine). No semicolon-separated batches.**  
   _Why:_ Anything else is rejected by the guard before execution.
QR3. **Never emit DDL or DML -- no INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, GRANT, SET, COPY or CALL.**  
   _Why:_ The data product is read only for consumers; such a statement is rejected and logged.
QR4. **Do not try to widen what you can see, and do not mention entitlements in the SQL.**  
   _Why:_ Results are already filtered to the caller's entitled clients by a database policy. Nothing you can write changes that, so an attempt only produces a rejected query.
QR5. **Use the certified metric definitions below verbatim. Never re-derive `is_problematic`, `direction` or an age.**  
   _Why:_ These are the definitions the bank has agreed. Re-deriving them is how two reports end up disagreeing about the same word.
QR6. **When a question asks "per month", "per quarter" or "per year", join `ai.calendar` so periods with no activity are returned as zero.**  
   _Why:_ An omitted period reads as "no data", which is a different claim from "nothing happened". Q6 is exactly this case.
QR7. **Prefer the pre-joined entity over assembling the join yourself. `ai.loan` and `ai.account_owner` already carry the owner, their card type and the statement frequency.**  
   _Why:_ The owner join is the one most likely to go wrong: a card can belong to a disponent rather than to the account owner, and these entities have already resolved that.
QR8. **Return the supporting counts next to a percentage or an average, and surface the relevant caveat from `caveats` below.**  
   _Why:_ A share over a small denominator and a share over a large one are different facts. A number whose caveat is missing is not a governed answer.
QR9. **Round percentages to two decimals. Do not round monetary sums.**  
   _Why:_ Consistency with the rest of the product's reporting.
QR10. **If a question cannot be answered from the entities below, say exactly what is missing instead of guessing a column.**  
   _Why:_ An invented column name produces an error; an invented *meaning* produces a plausible wrong answer, which is worse.
QR11. **Filter time on the metric's own date column (its `time_column` below) with half-open ranges, for example `loan_date >= DATE '1995-01-01' AND loan_date < DATE '1995-10-01'`. In a user's question, Q1 to Q4 are CALENDAR QUARTERS: Q1 = January-March, Q2 = April-June, Q3 = July-September, Q4 = October-December (`ai.calendar.quarter` 1 to 4). "Q1-Q3 of 1995 and 1998" means 1 January to 30 September of EACH named year, one group per year, and every named year must appear in the filter. The labels "Q1" to "Q10" used elsewhere in this document only name the bank's ten reference questions; they never mean quarters.**  
   _Why:_ A date filter that drops the quarter bound, drops one of the years, or uses another date column (an account's open_date for a loan question) still runs and returns a plausible number. The guard cannot see that; only the query author can.
QR12. **Count and sum at the grain of the entity the question is about. Never aggregate a measure after joining that entity to a table on the "many" side of a join (see the cardinality on each join below): joining ai.loan to ai.transaction repeats every loan once per posting. Aggregate the many side first in a subquery, or use count(DISTINCT key) for counts.**  
   _Why:_ A fan-out join multiplies sums and counts silently. On this data, joining loans to transactions inflates a loan total more than a hundredfold, and the query is still valid SQL.
QR13. **Return one row per group with GROUP BY, never one column per value (no CASE or FILTER pivots such as male_loans / female_loans), and write period filters as DATE literals on the time_column. Gender is ai.client.gender, ai.account_owner.owner_gender or ai.loan.owner_gender: no other entity has a gender column.**  
   _Why:_ The application verifies the SQL against the intent you declare before it runs (D029). Row-per-group results and literal date ranges are what it can verify; anything it cannot verify is refused rather than shown.

## Business glossary

**account owner** -- The single client who legally holds the account: the disposition of type OWNER. Exactly one per account, guaranteed by a block-severity data quality rule.
  - NOT: A disponent, who may operate the account but does not own it. A card held by a disponent does NOT make the owner a card holder (assumption A5).
  - Where: `ai.account_owner (one row per account), ai.loan (owner columns)`

**disponent** -- A client authorised to transact on an account they do not own, for example a spouse. 869 of 4,500 accounts have one.
  - Where: `ai.card.holder_is_account_owner = false`

**problematic loan** -- A loan with status B (finished, not repaid) or D (running, client in debt). Available as the boolean `is_problematic`.
  - NOT: Status A (finished, paid in full) or C (running, no problem). Counting only B -- realised losses -- is a different and much smaller number (assumption A4).
  - Where: `ai.loan.is_problematic`

**incoming transaction** -- A credit posting: `direction = 'credit'` (source type PRIJEM). Money arriving in the account.
  - NOT: A net flow. For "incoming amount" sum the positive `amount`, not `signed_amount` (assumption A7).
  - Where: `ai.transaction.direction`

**new account** -- An account whose `open_date` falls in the period asked about.
  - Where: `ai.account.open_date`

**region** -- One of eight Czech regions, from the district. A client's region is the region of the district the CLIENT lives in (`ai.client.region`); an account's region is the region of the district the ACCOUNT is registered in (`ai.account.region`).
  - Careful: The two differ for 409 of 4,500 account owners (9.1 percent). A question about clients uses the client's region (assumption A1); a question about money arriving at accounts uses the account's region (assumption A8).
  - Where: `ai.client.region, ai.account.region, ai.district.region`

**statement frequency** -- How often the bank issues a statement for the account: monthly, weekly or after transaction. Already in English.
  - Where: `ai.account.statement_frequency, ai.loan.statement_frequency`

**month-end balance** -- The account balance after the last posting on or before the last day of that month, and carried forward from the last known balance for months with no posting. When several postings share the last date, the closing one is the end of that day's running-balance chain (each posting starts at balance_after - signed_amount); closing_basis says how it was decided.
  - Careful: Use this entity rather than computing a balance from ai.transaction: the closing-posting rule and the carry-forward are already applied here, consistently with every other balance figure the bank reports (assumption A14).
  - Where: `ai.account_month_end_balance`

**quarter** -- A calendar quarter: Q1 = January-March, Q2 = April-June, Q3 = July-September, Q4 = October-December. "Q1-Q3 of a year" is 1 January to 30 September of that year.
  - NOT: A fiscal quarter, a rolling three months, or one of the bank's reference questions (labelled Q1-Q10 in this document).
  - Where: `ai.calendar.quarter, or extract(quarter FROM <date column>)`

**age at loan start** -- The account owner's exact age in years, including the fractional part, on the loan start date. Pre-computed.
  - Careful: Do not recompute it. Truncating to completed years reports ages about half a year too low, and a difference of calendar years is wrong for any individual loan (assumption A10).
  - Where: `ai.loan.owner_age_at_loan_start`

## Certified metrics -- use these expressions verbatim

**client_count** on `ai.client`: Number of clients.
  - expression: `count(*)`
  - counting_grain: `client_id` (one row of `ai.client` per value)
  - permitted joins: `ai.district` -- any other join is rejected
  - caveats: C4
  - grain: ai.client is one row per client, so no DISTINCT is needed.

**account_count** on `ai.account`: Number of accounts.
  - expression: `count(*)`
  - time_column: `open_date` (filter and group periods on this date)
  - counting_grain: `account_id` (one row of `ai.account` per value)
  - permitted joins: `ai.district`, `ai.account_owner`, `ai.calendar` -- any other join is rejected
  - caveats: C4

**loan_count** on `ai.loan`: Number of loans.
  - expression: `count(*)`
  - time_column: `loan_date` (filter and group periods on this date)
  - counting_grain: `loan_id` (one row of `ai.loan` per value)
  - permitted joins: `ai.account_owner`, `ai.account`, `ai.calendar` -- any other join is rejected
  - grain: ai.loan is one row per loan, not per account. In this book every account has at most one loan, but the model does not rely on that.

**total_loan_amount** on `ai.loan`: Total principal granted.
  - expression: `sum(amount)`
  - time_column: `loan_date` (filter and group periods on this date)
  - counting_grain: `loan_id` (one row of `ai.loan` per value)
  - permitted joins: `ai.account_owner`, `ai.account`, `ai.calendar` -- any other join is rejected
  - careful: The principal, not `monthly_payment * duration_months`, which is the gross repayment including interest (assumption A3).

**average_loan_amount** on `ai.loan`: Average principal per loan.
  - expression: `round(avg(amount), 2)`
  - time_column: `loan_date` (filter and group periods on this date)
  - counting_grain: `loan_id` (one row of `ai.loan` per value)
  - permitted joins: `ai.account_owner`, `ai.account`, `ai.calendar` -- any other join is rejected

**problematic_loan_share** on `ai.loan`: Share of loans that are problematic, as a percentage.
  - expression: `round(100.0 * count(*) FILTER (WHERE is_problematic) / count(*), 2)`
  - time_column: `loan_date` (filter and group periods on this date)
  - counting_grain: `loan_id` (one row of `ai.loan` per value)
  - permitted joins: `ai.account_owner`, `ai.account`, `ai.calendar` -- any other join is rejected
  - careful: Always report `count(*)` and `count(*) FILTER (WHERE is_problematic)` beside it, so the denominator is visible.

**incoming_transaction_amount** on `ai.transaction`: Total amount arriving in accounts.
  - expression: `sum(amount)`
  - filter: `direction = 'credit'`
  - time_column: `trans_date` (filter and group periods on this date)
  - counting_grain: `trans_id` (one row of `ai.transaction` per value)
  - permitted joins: `ai.account`, `ai.calendar` -- any other join is rejected
  - caveats: C5, C6, C7

**outgoing_transaction_amount** on `ai.transaction`: Total amount leaving accounts.
  - expression: `sum(amount)`
  - filter: `direction = 'debit'`
  - time_column: `trans_date` (filter and group periods on this date)
  - counting_grain: `trans_id` (one row of `ai.transaction` per value)
  - permitted joins: `ai.account`, `ai.calendar` -- any other join is rejected
  - caveats: C5, C7

**net_flow** on `ai.transaction`: Net movement, credits minus debits.
  - expression: `sum(signed_amount)`
  - time_column: `trans_date` (filter and group periods on this date)
  - counting_grain: `trans_id` (one row of `ai.transaction` per value)
  - permitted joins: `ai.account`, `ai.calendar` -- any other join is rejected
  - caveats: C5, C7

**average_month_end_balance** on `ai.account_month_end_balance`: Average closing balance across accounts at a given month end.
  - expression: `round(avg(closing_balance), 2)`
  - filter: `month_end_date = DATE 'YYYY-MM-DD'`
  - time_column: `month_end_date` (filter and group periods on this date)
  - counting_grain: `account_id, month_end_date` (one row of `ai.account_month_end_balance` per value)
  - permitted joins: `ai.account`, `ai.account_owner` -- any other join is rejected
  - caveats: C1, C2
  - careful: Average over accounts that have a known balance on that date. An account with no posting has no balance and must not be counted as zero (assumption A15). Report `count(*)` and `count(*) FILTER (WHERE is_carried_forward)` beside the average.

**average_age_at_loan_start** on `ai.loan`: Average exact age of the account owner when the loan started.
  - expression: `round(avg(owner_age_at_loan_start), 2)`
  - time_column: `loan_date` (filter and group periods on this date)
  - counting_grain: `loan_id` (one row of `ai.loan` per value)
  - permitted joins: `ai.account_owner`, `ai.account`, `ai.calendar` -- any other join is rejected
  - caveats: C3

**gender_share** on `ai.account_owner`: Share of account owners by gender, as a percentage. Group by owner_gender.
  - expression: `round(100.0 * count(*) / sum(count(*)) OVER (), 2)`
  - counting_grain: `account_id` (one row of `ai.account_owner` per value)
  - permitted joins: `ai.client` -- any other join is rejected
  - careful: Percentages must sum to 100; report the counts as well. The gender column is named differently per entity: ai.client.gender, ai.account_owner.owner_gender, ai.loan.owner_gender. There is no column called gender on ai.account_owner or ai.loan. For loans by gender use loan_count grouped by ai.loan.owner_gender (the account owner's gender).

## Entities

### `ai.client` -- Client

A person who banks with us. One row per client, including clients who hold no account.

- **Grain: one row per client** (key: client_id)
- Rows when unfiltered: 5,369
- Relevant to: Q1

| column | type | meaning | allowed values |
|---|---|---|---|
| `client_ref` | text | The client's EXTERNAL reference (BRK-XXXX-XXXX). This is the identifier to QUOTE in an answer, on a statement or in a link: it is opaque, so unlike client_id it cannot be guessed, enumerated or counted. Join on client_id; refer to people by client_ref. |  |
| `client_id` | bigint | Unique client identifier. The entitlement key. |  |
| `birth_date` | date | Date of birth, decoded from the source birth number. |  |
| `gender` | text | Gender, decoded from the source birth number. | `male`, `female` |
| `district_id` | bigint | District the client lives in. |  |
| `district_name` | text | Name of the district the client lives in. |  |
| `region` | text | Region the client lives in. This is the region Q1 groups by. | `Prague`, `central Bohemia`, `east Bohemia`, `north Bohemia`, `south Bohemia`, `west Bohemia`, `north Moravia`, `south Moravia` |
| `is_account_owner` | boolean | True when this client legally owns at least one account (rather than only being a disponent). |  |
| `data_quality_flags` | text[] | Warn-level data quality flags on this row; empty array when clean. |  |

Joins:
- to `ai.district` on `district_id` (many-to-one) -- The client's own district.
- to `ai.account_owner` on `client_id = owner_client_id` (one-to-many; optional: not every row has a match) -- 869 clients own no account (disponents only); an INNER JOIN drops them, so never count clients through this join. The accounts this client owns.

### `ai.account` -- Account

A current account held at the bank. One row per account.

- **Grain: one row per account** (key: account_id)
- Rows when unfiltered: 4,500
- Relevant to: Q6

| column | type | meaning | allowed values |
|---|---|---|---|
| `account_ref` | text | The account number in IBAN form, with valid check digits. This is what a customer recognises and what an answer should quote; account_id is an internal key. |  |
| `account_id` | bigint | Unique account identifier. |  |
| `open_date` | date | Date the account was opened. This is what 'new account' means. |  |
| `statement_frequency` | text | How often a statement is issued, in English. | `monthly`, `weekly`, `after transaction` |
| `district_id` | bigint | District the ACCOUNT is registered in (not necessarily where its owner lives). |  |
| `district_name` | text | Name of the account's district. |  |
| `region` | text | Region of the account's district. Q5 uses this one. |  |
| `data_quality_flags` | text[] | Warn-level data quality flags on this row. |  |

Joins:
- to `ai.district` on `district_id` (many-to-one) -- The account's own district.
- to `ai.account_owner` on `account_id` (one-to-one) -- Who owns the account.
- to `ai.transaction` on `account_id` (one-to-many) -- Fan-out: up to hundreds of postings per account. Aggregate transactions before joining them to another entity (QR12).
- to `ai.loan` on `account_id` (one-to-many; optional: not every row has a match) -- Most accounts have no loan; an INNER JOIN keeps only accounts that do.
- to `ai.calendar` on `open_date = date_key` (many-to-one)

### `ai.account_owner` -- Account with its owner

Each account together with its single legal owner, the owner's own region, and the card the OWNER holds. The entity to use for anything phrased "of the account owner".

- **Grain: one row per account** (key: account_id)
- Rows when unfiltered: 4,500
- Relevant to: Q8

| column | type | meaning | allowed values |
|---|---|---|---|
| `account_ref` | text | The account number in IBAN form, with valid check digits. This is what a customer recognises and what an answer should quote; account_id is an internal key. |  |
| `account_id` | bigint | Account identifier. |  |
| `account_open_date` | date | Date the account was opened. |  |
| `statement_frequency` | text | Statement frequency of the account. | `monthly`, `weekly`, `after transaction` |
| `account_district_id` | bigint | District the account is registered in. |  |
| `account_district_name` | text | Name of the account's district. |  |
| `account_region` | text | Region of the account's district. |  |
| `owner_client_ref` | text | External reference of the owning client. Quote this rather than owner_client_id. |  |
| `owner_client_id` | bigint | Client who legally owns the account. |  |
| `owner_birth_date` | date | Owner's date of birth. |  |
| `owner_gender` | text | Owner's gender. | `male`, `female` |
| `owner_district_name` | text | Name of the district the OWNER lives in. |  |
| `owner_region` | text | Region the OWNER lives in. Differs from account_region for 9.1 percent of accounts. |  |
| `owner_card_id` | bigint | The owner's card, NULL when the owner holds no card. |  |
| `owner_card_type` | text | Type of the card held by the OWNER. NULL means the owner holds no card; a card held by a disponent is deliberately not shown here. | `junior`, `classic`, `gold` |
| `owner_card_issued_date` | date | When the owner's card was issued. |  |
| `data_quality_flags` | text[] | Warn-level data quality flags on the account, owner or disposition. |  |

Joins:
- to `ai.client` on `owner_client_id = client_id` (many-to-one)
- to `ai.loan` on `account_id` (one-to-many; optional: not every row has a match) -- Most accounts have no loan; an INNER JOIN keeps only accounts that do.
- to `ai.account_month_end_balance` on `account_id` (one-to-many) -- Fan-out: one row per month end. Filter month_end_date before aggregating.

### `ai.card` -- Payment card

An issued payment card with its holder. A card belongs to a disposition, so its holder is not always the account owner.

- **Grain: one row per card** (key: card_id)
- Rows when unfiltered: 892

| column | type | meaning | allowed values |
|---|---|---|---|
| `card_id` | bigint | Unique card identifier. |  |
| `card_type` | text | Product tier of the card. | `junior`, `classic`, `gold` |
| `issued_date` | date | Date the card was issued. |  |
| `holder_client_id` | bigint | Client holding the card. |  |
| `account_id` | bigint | Account the card operates on. |  |
| `holder_is_account_owner` | boolean | True when the holder is the account OWNER; false when the holder is a disponent. Filter on true for any question about the owner's card. |  |

Joins:
- to `ai.account` on `account_id` (many-to-one)
- to `ai.client` on `holder_client_id = client_id` (many-to-one)

### `ai.loan` -- Loan

A loan, pre-joined to its account owner, the owner's card type, the owner's exact age at loan start and the account's statement frequency. Answers Q2, Q3, Q4, Q7 and Q10 with no further joins.

- **Grain: one row per loan** (key: loan_id)
- Rows when unfiltered: 682
- Relevant to: Q2, Q3, Q4, Q7, Q10

| column | type | meaning | allowed values |
|---|---|---|---|
| `loan_id` | bigint | Unique loan identifier. |  |
| `account_id` | bigint | Account carrying the loan. |  |
| `loan_date` | date | Date the loan started. This is the date a loan is 'granted' on. |  |
| `loan_year` | integer | Year of loan_date, materialised so a yearly grouping needs no date function. |  |
| `amount` | numeric | Principal granted, in CZK. This is what 'loan amount' means. |  |
| `duration_months` | bigint | Term in months. | `12`, `24`, `36`, `48`, `60` |
| `monthly_payment` | numeric | Scheduled monthly repayment, in CZK. |  |
| `status_code` | text | Source status code. | `A`, `B`, `C`, `D` |
| `loan_status` | text | Status in business language. | `finished, paid in full`, `finished, unpaid (default)`, `running, no problem`, `running, client in debt` |
| `is_problematic` | boolean | The certified definition of a problematic loan: status B or D. Use this column, never a status comparison of your own. |  |
| `statement_frequency` | text | Statement frequency of the loan's account. Q10 groups by this. | `monthly`, `weekly`, `after transaction` |
| `owner_client_id` | bigint | Client who owns the loan's account. |  |
| `owner_gender` | text | Gender of the account owner. | `male`, `female` |
| `owner_birth_date` | date | Date of birth of the account owner. |  |
| `owner_age_at_loan_start` | numeric | Exact age in years of the account owner on the loan start date, including the fractional part. Pre-computed; do not recompute. |  |
| `owner_card_type` | text | Card type of the account OWNER. The literal value 'no card' is used where the owner holds none, so grouping by this column covers every loan. | `junior`, `classic`, `gold`, `no card` |
| `account_district_name` | text | District the loan's account is registered in. |  |
| `account_region` | text | Region of the account's district. |  |
| `owner_region` | text | Region the account owner lives in. |  |
| `data_quality_flags` | text[] | Warn-level flags, for example 'val_owner_age_at_loan_start' on the 6 loans whose owner is recorded as under 15. |  |

Joins:
- to `ai.account_owner` on `account_id` (many-to-one)
- to `ai.account` on `account_id` (many-to-one)
- to `ai.calendar` on `loan_date = date_key` (many-to-one)

### `ai.transaction` -- Transaction

One posting on an account. 1.06 million rows, the largest entity. Pre-joined to the account's district and region.

- **Grain: one row per posting** (key: trans_id)
- Rows when unfiltered: 1,056,319
- Relevant to: Q5

| column | type | meaning | allowed values |
|---|---|---|---|
| `trans_id` | bigint | Unique posting identifier. Not chronological within a date. |  |
| `account_id` | bigint | Account the posting belongs to. |  |
| `trans_date` | date | Date of the posting. |  |
| `direction` | text | Whether money came in or went out. 'credit' is an incoming amount, which is what Q5 asks for. | `credit`, `debit` |
| `transaction_type` | text | Posting type in business language. | `credit`, `debit`, `withdrawal (legacy debit)` |
| `amount` | numeric | Amount of the posting, always positive. Sum this for 'incoming amount'. |  |
| `signed_amount` | numeric | Positive for credits, negative for debits. Sum this for a NET flow only. |  |
| `balance_after` | numeric | Account balance after this posting. Can be negative (overdraft), which is normal and must not be clipped. |  |
| `operation` | text | How the money moved. NULL means 'not applicable': the posting was generated by the bank's interest run, which has no customer operation. It is not a missing value. | `cash deposit`, `cash withdrawal`, `credit card withdrawal`, `collection from another bank`, `remittance to another bank` |
| `category` | text | What the posting was for. NULL where the source gives no category. | `insurance payment`, `payment for statement`, `interest credited`, `sanction interest for negative balance`, `household payment`, `old age pension`, `loan payment` |
| `account_district_id` | bigint | District of the account the posting belongs to. |  |
| `account_district_name` | text | Name of that district. Q5 ranks by this. |  |
| `account_region` | text | Region of that district. |  |

Joins:
- to `ai.account` on `account_id` (many-to-one)
- to `ai.calendar` on `trans_date = date_key` (many-to-one)

### `ai.account_month_end_balance` -- Account balance at month end

The closing balance of each account at each month end, with the closing posting (end of the last day's running-balance chain) and the carry-forward already applied. The right source for any question about the balance at the end of a period. Rows start at the account's first posting month: before it the balance is unknown and there is no row, so an average at an early month end covers only the accounts active by then.

- **Grain: one row per account per month end** (key: account_id, month_end_date)
- Rows when unfiltered: 185,615
- Relevant to: Q9

| column | type | meaning | allowed values |
|---|---|---|---|
| `account_id` | bigint | Account identifier. |  |
| `month_end_date` | date | Last calendar day of the month this balance refers to, for example 1998-12-31. |  |
| `closing_balance` | numeric | Balance after the last posting on or before month_end_date, in CZK. Can be negative. |  |
| `is_carried_forward` | boolean | True when the account had no posting in that month and the balance is inherited from an earlier month. Report how many rows this applies to. |  |
| `balance_as_of_month_end` | date | The month end the balance was actually observed at. Equals month_end_date when is_carried_forward is false. |  |
| `closing_basis` | text | How the closing posting of the observed month was identified. 'single posting': one posting that day. 'balance chain': several postings, ordered by their running balances. 'ambiguous': the running balances do not order that day's postings, so the documented fallback (lowest transaction id among the chain ends) was used. Report how many balances are 'ambiguous' when they matter. | `single posting`, `balance chain`, `ambiguous` |
| `account_data_quality_flags` | text[] | Warn-level flags on the account, including 'con_balance_reconciliation_material' for the 14 accounts whose flows disagree with their reported balance by more than 100 CZK. |  |

Joins:
- to `ai.account` on `account_id` (many-to-one)
- to `ai.account_owner` on `account_id` (many-to-one)

### `ai.district` -- District

Administrative district reference data, including the region. Not entitlement filtered: it contains no client information.

- **Grain: one row per district** (key: district_id)
- Rows when unfiltered: 77
- Relevant to: Q1, Q5

| column | type | meaning | allowed values |
|---|---|---|---|
| `district_id` | bigint | Unique district identifier. |  |
| `district_name` | text | District name. |  |
| `region` | text | Region the district belongs to. |  |
| `inhabitants` | bigint | Population of the district. |  |
| `average_salary` | numeric | Average salary in the district, in CZK. |  |
| `unemployment_rate_1996` | numeric | Unemployment rate in 1996, as a percentage. |  |
| `entrepreneurs_per_1000` | numeric | Entrepreneurs per 1,000 inhabitants. |  |
| `crimes_1996` | bigint | Crimes committed in 1996. |  |

### `ai.calendar` -- Calendar

One row per day in the book's window. Join to it when a question asks per month, per quarter or per year, so that periods with no activity come back as zero instead of being omitted. Join a date column to date_key, for example loan_date = date_key.

- **Grain: one row per calendar day** (key: date_key)
- Rows when unfiltered: 2,191
- Relevant to: Q6

| column | type | meaning | allowed values |
|---|---|---|---|
| `date_key` | date | The calendar day. |  |
| `year` | integer | Calendar year, 1993 to 1998. |  |
| `quarter` | integer | Calendar quarter, 1 to 4: 1 = January-March, 2 = April-June, 3 = July-September, 4 = October-December. Q1 to Q4 in a question mean these values. |  |
| `month` | integer | Month number, 1 to 12. |  |
| `month_name` | text | Month name in English, for example 'January'. |  |
| `year_month` | text | Year and month as text, for example '1996-01'. Useful as a stable sort key. |  |
| `month_start` | date | First day of the month this day belongs to. |  |
| `month_end` | date | Last day of the month this day belongs to. |  |
| `is_month_end` | boolean | True when this day is the last day of its month. Filter on it to get one row per month. |  |

### `ai.code_reference` -- Code catalogue

The published mapping from source codes to business labels. The entities above already expose the labels, so this is for explaining an answer rather than for joining.

- **Grain: one row per code per code set** (key: code_set, code)
- Rows when unfiltered: 28

| column | type | meaning | allowed values |
|---|---|---|---|
| `code_set` | text | Which code set the code belongs to, for example 'loan_status'. |  |
| `code` | text | The source code. |  |
| `label` | text | The business label. |  |
| `code_set_note` | text | What the code set means. |  |

### `ai.my_entitlement` -- My entitlement

One row describing the calling user's own entitlement. Query it to tell "there are no such rows" apart from "you are not entitled to those rows".

- **Grain: one row**
- Rows when unfiltered: 1

| column | type | meaning | allowed values |
|---|---|---|---|
| `database_role` | text | The role the caller is authenticated as. |  |
| `principal_type` | text | What kind of principal is asking. 'client' is a self-service customer entitled to exactly themselves; anything else is a staff user entitled to the union of their portfolios. Use it to word an answer appropriately: a customer asking 'how many accounts do I have' means their own, and should not be told it is a portfolio total. | `client`, `relationship_manager`, `risk`, `administrator` |
| `entitled_clients` | bigint | How many clients the caller may see. |  |
| `entitled_accounts` | bigint | How many accounts the caller may see. |  |
| `portfolios` | text | The portfolios the caller holds, comma separated. For a self-service customer there is no portfolio, so this reads 'SELF:<client_id>' instead. NULL only when the caller has been granted nothing at all. |  |

## Data quality caveats to repeat in your answer

**C1** [warn, 14 rows, rule `CON_BALANCE_RECONCILIATION_MATERIAL`] (affects metric `average_month_end_balance`): For 14 of 4,500 accounts the sum of all postings disagrees with the last reported balance by more than 100 CZK (at most 488.30 CZK). The balance column is used as reported, because it is what the bank's own statements showed; the discrepancy means the flows cannot reproduce it. Flagged as 'con_balance_reconciliation_material' in account_data_quality_flags.

**C2** [warn, 183 rows, rule `CON_INTRADAY_ORDER_AMBIGUOUS`] (affects metric `average_month_end_balance`): Transaction ids are not chronological and the source has no time of day. When an account has several postings on its last active day, the closing posting is derived from the running-balance chain. On the last day of the book this applies to 183 accounts: 141 are resolved by the chain, and for 42 the chain cannot order the postings, so a documented fallback is used and the row says closing_basis = 'ambiguous'. Report that count when a balance figure depends on it.

**C3** [warn, 6 rows, rule `VAL_OWNER_AGE_AT_LOAN_START`] (affects metric `average_age_at_loan_start`): 6 loans were granted to account owners recorded as under 15 years old (minimum 10.3 years), which is not legally possible. The loans are kept because their amount and status are sound, and they are flagged as 'val_owner_age_at_loan_start'. Report the average age with and without them when asked about age.

**C4** [info, 409 rows, rule `CON_CLIENT_ACCOUNT_DISTRICT_MISMATCH`]: 409 of 4,500 account owners (9.1 percent) live in a different district than their account is registered in. This is not a defect. It means a question about regions must say whose region it means: use ai.client.region for clients, ai.account.region for accounts and the money in them.

**C5** [block, 1 rows, rule `UNQ_TRANS_BUSINESS_KEY`]: One posting was a duplicate by business key (same account, date, type, amount and resulting balance as another posting with a different id). It was quarantined, so ai.transaction holds 1,056,319 rows rather than the 1,056,320 in the source file.

**C6** [info, 183,114 rows, rule `COMP_TRANS_OPERATION_STRUCTURAL`]: 183,114 postings have no operation. All of them are interest credits from the bank's own interest run, which has no customer operation behind it. The NULL means "not applicable" and must not be filtered out as missing data, nor imputed.

**C7** [info, 14 rows, rule `VAL_TRANS_AMOUNT_POSITIVE`]: 14 postings have an amount of exactly zero. They are interest runs that accrued nothing. They are genuine events and change no sum.

## Entitlements

Every entity except ai.district, ai.calendar and ai.code_reference is filtered to the clients the calling user is entitled to. The filter is a row level security policy inside the database, applied to every statement on the connection.

- The filter is already applied. Never add an entitlement predicate, and never try to remove one.
- Two users running your identical SQL will correctly get different numbers. That is not an error.
- An empty result may mean "not entitled" rather than "nothing matches". ai.my_entitlement distinguishes them.
- The caller may be a bank CUSTOMER rather than a member of staff (ai.my_entitlement.principal_type = 'client'). Such a caller sees exactly one client - themselves - so a bank-wide question asked by one of them is answerable only about their own data, and the answer should say so rather than presenting one row as a total.
- A percentage or a share is computed over what the caller may see, so it is a statement about their portfolio.

## Phrase hints

| if the question says | use | watch out for |
|---|---|---|
| clients per region / how many clients | `ai.client` | Use the client's own region, not the account's (assumption A1). |
| loans per year / amount granted | `ai.loan with loan_year` | Sum amount (the principal), not monthly_payment * duration_months. |
| problematic / bad / defaulted loans | `ai.loan.is_problematic` | Do not redefine it from status_code; B and D are both problematic. |
| per card type of the account owner | `ai.loan.owner_card_type` | It already means the OWNER's card and already contains the literal 'no card', so every loan is in exactly one group. Do not join ai.card. |
| incoming transaction amount / money received | `ai.transaction with direction = 'credit'` | Sum amount, not signed_amount, and take the district from the account. |
| new accounts per month | `ai.account.open_date joined to ai.calendar` | Join the calendar so a month with no new accounts is reported as zero. |
| age of the owner at loan start | `ai.loan.owner_age_at_loan_start` | Pre-computed and exact; do not derive it from birth dates. |
| gender split of gold card holders | `ai.account_owner with owner_card_type = 'gold'` | Owners only. A disponent's gold card is not the owner's, and ai.card would include it unless holder_is_account_owner is filtered. |
| balance at the end of <month> | `ai.account_month_end_balance` | Filter month_end_date to the last day of that month, and report how many balances were carried forward. |
| which statement frequency has the highest share | `ai.loan grouped by statement_frequency` | A within-group rate (problematic / all loans of that frequency), not the group's share of all problematic loans. Return the full ranking. |
