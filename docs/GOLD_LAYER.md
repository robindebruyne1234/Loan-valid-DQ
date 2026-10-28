# The gold layer: what is built, and what the cleaned data will still carry

Written as the answer to a direct question: *given everything that has been
cleaned, what can a gold layer be made of right now?*

The short version is that the gold layer currently built is the part the ten
questions needed, and the cleaned data supports roughly twice as much without
a single new source file. The gap is not cleaning that has not happened -- it
is cleaned data that nothing consumes yet.

Every figure below was measured against the database on the current build.

---

## 1. What "gold" means here

Three things, and the third is the one usually skipped.

1. **Shaped for a question, not for a loader.** A gold table has a stated
   grain, resolved keys and no decoding left to do.
2. **One definition per business term.** "Problematic loan", "the account
   owner", "month-end balance" are settled in the table, not argued in each
   query.
3. **Safe to be wrong about.** Every caveat the quality layer raised travels
   with the row (`_dq_flags`), so an answer built on a suspect row can say so.

A table that satisfies the first two but not the third is a mart. The third is
what makes it a *governed* product, and it is the reason the cleaning ledger
and this document are the same piece of work seen from two ends.

---

## 2. What is in gold today

Ten tables and eleven consumer views, built because the ten questions needed
them.

| Table | Grain | Rows | Built for |
|---|---|---|---|
| `core.dim_client` | one client | 5,369 | Q1, Q7, Q8 |
| `core.dim_account` | one account | 4,500 | Q6, Q10 |
| `core.dim_district` | one district | 77 | Q1, Q5 |
| `core.dim_card` | one issued card | 892 | Q4, Q8 |
| `core.dim_date` | one calendar day | 2,191 | Q6, Q9 |
| `core.bridge_disposition` | one client-account-capacity triple | 5,369 | the join every question needs |
| `core.fact_loan` | one loan | 682 | Q2, Q3, Q4, Q7, Q10 |
| `core.fact_transaction` | one posting | 1,056,319 | Q5, Q9 |
| `core.fact_account_month_end_balance` | account x month end | 185,615 | Q9 |
| `core.ref_codes` | one code | 28 | every label in the product |

That is a complete star for the questions asked. It is not a complete product
for the data held.

---

## 3. What is cleaned and currently consumed by nothing

This is the honest inventory, and the first item is the large one.

### 3.1 Standing orders -- an entire cleaned table with no consumer

`stg."order"` is loaded, typed, normalised, decoded, profiled and covered by
rules. It reaches no core table and no consumer view.

| | |
|---|---|
| Rows | **6,471** standing orders |
| Accounts covered | **3,758** of 4,500 (**83.5%**) |
| Committed value | **21,228,994 CZK** |
| Categories | household payment 3,502 - loan payment 717 - insurance 532 - leasing 341 - uncategorised 1,379 |

This is the bank's record of what its customers have *committed* to pay every
month, as opposed to what they happened to pay. For any question about
affordability, disposable income, or why an account's balance behaves as it
does, it is the most informative table in the dataset -- and it is the one
table a reader of the current product cannot see at all.

It is also where the `LEASING` decode gap was found (D017), which is not a
coincidence: a table nothing consumes is a table whose defects nobody meets.

### 3.2 Counterparty information on transactions

`partner_bank` and `partner_account` are cleaned on **273,508** postings
across **13** distinct banks. Nothing groups by them.

### 3.3 The district socio-economics, half-used

`dim_district` publishes all sixteen source columns, but only `region`,
`average_salary` and the district name are reached by any question. The
unemployment and crime columns are each a **pair** (1995 and 1996) -- a tiny
two-period history flattened into one row, which is a shape no consumer can
pivot without knowing the trick.

### 3.4 Card issue dates

`dim_card.issued_date` is cleaned on all **892** cards. Q4 and Q8 use the card
*type*; nothing uses when it was issued, so card tenure is unavailable.

---

## 4. Gold tables buildable from what is already cleaned

Eight candidates. None needs a new source file; all inputs are already typed,
decoded and rule-checked. Ordered by value per unit of work.

### G1 -- `fact_standing_order`
- **Grain** one standing order. **~6,471 rows.**
- **Inputs** `stg."order"` (cleaned, rule-checked, currently unpublished).
- **Serves** committed monthly outgoings, affordability, commitment mix by
  district, "which accounts are committed beyond their inflow".
- **Work** small: the staging table is finished. This is a core table, a
  consumer view, a semantic entry and a foreign key check.
- **Why first** the largest gap between what is cleaned and what is published,
  and the only one where a whole business concept is missing rather than an
  attribute.

### G2 -- `fact_account_month`
- **Grain** account x month. **~185,057 rows** (measured: account-months with
  activity), aligned with the existing month-end balance grid.
- **Inputs** `core.fact_transaction`, `core.dim_date`.
- **Columns** credits, debits, net flow, posting count, and the same split per
  category and per operation.
- **Serves** every trend, seasonality and "months where X exceeded Y" question
  in one scan instead of a 1.06 m-row aggregation.
- **Why** it is the single biggest reduction in what a generated query has to
  get right, and it pairs with the month-end balance table already built --
  flow beside stock, on the same grain.

### G3 -- `dim_client_profile` (the customer 360)
- **Grain** one client. **5,369 rows.**
- **Inputs** `dim_client`, `bridge_disposition`, `dim_account`, `dim_card`,
  `fact_loan`, `dim_district`, plus first and last activity from the fact.
- **Columns** age, gender, district and region, accounts owned (4,500 owner
  relationships) and accounts held as disponent (**869** clients hold one),
  cards, loans, tenure, flags.
- **Serves** collapses the four-table join every "clients who..." question
  currently needs into one table.
- **Caveat worth stating** it is a convenience, not a new fact. The bridge
  stays the source of truth for the many-to-many; this flattens the common
  path, and the grain has to be defended or it silently becomes "one row per
  client per account".

### G4 -- `fact_loan_performance`
- **Grain** one loan. **682 rows**, from **13,580** loan-payment postings.
- **Inputs** `fact_loan` plus `fact_transaction` filtered to category `UVER`.
- **Columns** payments observed against payments scheduled, months paid, first
  and last payment, a shortfall measure.
- **Serves** the credit-risk questions the current product can only answer by
  status code. Q3 and Q10 ask *whether* a loan is problematic; this is the
  table that could say *how*.
- **Caveat** it is a reconstruction. A `UVER` posting is attributed to the
  account's loan, which is safe here only because this extract has exactly one
  loan per account (682 loans, 682 distinct accounts) -- a property that holds
  today and must be asserted by a rule before anything depends on it.

### G5 -- `fact_district_year`
- **Grain** district x year. **154 rows** (77 x 2).
- **Inputs** `dim_district`, unpivoting the 1995/1996 column pairs.
- **Serves** "did unemployment rise", and removes a real trap: a column named
  `unemployment_rate_1995` invites a generated query to hard-code a year into
  a column name instead of a filter.
- **Why** tiny, and it fixes a modelling smell rather than adding data.

### G6 -- `fact_card_activity`
- **Grain** card x month, from **8,036** `VYBER KARTOU` postings and 892 cards.
- **Serves** card usage, dormancy, tenure from `issued_date`.
- **Caveat, and it is the limiting one** postings carry no card identifier.
  Attribution is by account, so an account whose owner and disponent both hold
  cards cannot be split. The honest version of this table publishes activity
  per *account with a card*, not per card, and says so in its grain.

### G7 -- `fact_interbank_flow`
- **Grain** partner bank x month x direction, from **273,508** postings and 13
  banks.
- **Serves** counterparty concentration, which is a question a bank actually
  asks and this product currently cannot answer at all.

### G8 -- a published metric layer
- Not a table of rows: the certified definitions (`is_problematic`, "the
  account owner", "month-end balance", "incoming volume") promoted out of the
  semantic YAML into a first-class object with an owner and a test each.
- **Serves** the governance half of "governed data product". Today a metric is
  correct because the semantic layer says so; after this it is correct because
  a test says so.

---

## 5. What cannot be built from this data, and should not be faked

Stated so the list above is not read as a claim that everything is possible.

- **No product or channel dimension.** There is no product catalogue; card
  type is the only product-like attribute in the whole extract.
- **No customer contact, segment or demographic beyond derived gender and
  age.** Any "segment" would be this pipeline's invention.
- **No history on any dimension** (A31). Districts, clients and accounts each
  appear once. A slowly changing dimension cannot be built from a snapshot --
  it can only be started from today.
- **No intra-day ordering** (A33). 183 accounts have several postings on their
  last day. The running balance orders 141 of them (D028); for 42 no derived
  table can resolve what the source did not record.
- **No balance before an account's first posting.** The opening balance is
  unknown, which is why `fact_account_month_end_balance` starts at the first
  active month rather than at the account open date.

---

## 6. The order I would build them in

1. **G1 `fact_standing_order`.** A whole cleaned table currently invisible.
   Largest gap, smallest effort.
2. **G5 `fact_district_year`.** An hour, and it removes a trap that would
   otherwise catch a generated query.
3. **G2 `fact_account_month`.** The highest-value aggregate, and the one that
   changes what the product costs to query.
4. **G3 `dim_client_profile`.** Only after G2, because the profile should read
   activity from the monthly aggregate rather than re-scan the fact.
5. **G8 the metric layer.** Once there are enough derived tables that two of
   them could disagree.
6. **G4, G6, G7** as the questions arrive. Each carries a caveat that has to be
   agreed with a business owner first -- an attribution rule, a grain
   compromise, a reconstruction -- and building any of them before that
   conversation is how a data product acquires a number nobody trusts.

A note on the shape of this list. Every item is a *modelling* step on data that
is already clean. That is the point the current build makes and this document
makes explicit: the expensive, irreversible work is the cleaning and the
grading, and it is done. What is left is cheap, additive, and safe to get
wrong once, because the ledger says what each table is made of and the
reconciliation says it still adds up.
