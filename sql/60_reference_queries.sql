-- ============================================================================
-- 60_reference_queries.sql -- REFERENCE answers, hand written
--
-- These are the ground truth for evaluating the LLM. They are written by hand
-- against the core model, executed by src/run_reference.py, and stored in
-- dq/results/reference_results.json.
--
-- They are kept strictly separate from the LLM's output: nothing in this file
-- is ever shown to the model, and the LLM's queries live in llm_logs/ and in
-- dq/results/llm_results.json under their own labels. Mixing the two would
-- make the evaluation meaningless.
--
-- Every query carries the interpretation it implements. Where a question could
-- reasonably be read another way, the alternative is named here and recorded
-- in ASSUMPTIONS.md with an ID.
--
-- Machine-readable markers: each query starts with "-- @@<question id>".
-- ============================================================================

-- @@Q1
-- Q1: How many clients do we have per region?
--
-- Interpretation (A1): "region" is the region of the CLIENT'S OWN district
-- (district.A3 reached through client.district_id), not the region of the
-- district their account is registered in. The two differ for 409 of 4,500
-- account owners (9.1 percent), so the choice is material -- see dq rule
-- CON_CLIENT_ACCOUNT_DISTRICT_MISMATCH. The alternative reading (account
-- district) is reported in ASSUMPTIONS.md A1.
-- All clients are counted (A2), including the ones holding no account, because
-- the question says "clients" and not "clients with an account". Clients whose
-- district cannot be resolved would appear as 'unknown region' rather than
-- being dropped; there are none in this copy.
SELECT
    region,
    count(*)                                              AS clients,
    round(100.0 * count(*) / sum(count(*)) OVER (), 2)    AS pct_of_clients
FROM core.v_client_region
GROUP BY region
ORDER BY clients DESC, region;

-- @@Q2
-- Q2: What is the total amount of loans granted per year?
--
-- Interpretation (A3): "granted" is dated by loan.date (the loan start date),
-- the only date the loan table carries, and "total amount" is the sum of the
-- principal amount, not of amount * duration or of the outstanding balance.
-- Years with no loans would be absent; every year 1993-1998 has loans here.
SELECT
    loan_year                                             AS year,
    count(*)                                              AS loans,
    sum(amount)                                           AS total_amount,
    round(avg(amount), 2)                                 AS average_amount
FROM core.fact_loan
GROUP BY loan_year
ORDER BY loan_year;

-- @@Q3
-- Q3: What percentage of our loans are problematic?
--
-- Interpretation (A4): "problematic" = loan status B (finished, not repaid) or
-- D (running, client in debt). A and C are healthy. This is the single
-- certified definition, materialised as core.fact_loan.is_problematic, so no
-- consumer can redefine it silently.
-- Cross-check: the public copy is documented as 76 of 682 = 11.14 percent.
SELECT
    count(*)                                                        AS total_loans,
    count(*) FILTER (WHERE is_problematic)                          AS problematic_loans,
    round(100.0 * count(*) FILTER (WHERE is_problematic) / count(*), 2)
                                                                    AS problematic_pct,
    count(*) FILTER (WHERE status_code = 'B')                       AS status_b_finished_unpaid,
    count(*) FILTER (WHERE status_code = 'D')                       AS status_d_running_in_debt
FROM core.fact_loan;

-- @@Q4
-- Q4: What is the average loan amount per card type of the account owner?
--
-- Interpretation (A5): the card is the card held by the account's OWNER
-- disposition. A card held by a disponent on the same account is deliberately
-- not attributed to the owner, which is why the join runs through
-- v_account_owner and not through disp directly.
-- Loans whose owner holds no card are reported as the explicit category
-- 'no card' (A6) rather than dropped, so the loan counts add up to the 682
-- loans reported by Q2 and Q3.
SELECT
    coalesce(owner_card_type, 'no card')                  AS owner_card_type,
    count(*)                                              AS loans,
    round(avg(amount), 2)                                 AS average_loan_amount,
    sum(amount)                                           AS total_loan_amount
FROM core.v_loan_enriched
GROUP BY coalesce(owner_card_type, 'no card')
ORDER BY average_loan_amount DESC;

-- @@Q5
-- Q5: Which 10 districts had the highest total incoming transaction amount in 1997?
--
-- Interpretation (A7): "incoming" = transaction type PRIJEM, that is
-- direction = 'credit'. The unsigned amount is summed, because the question
-- asks for incoming volume and not for a net flow.
-- Interpretation (A8): the district is the district the ACCOUNT is registered
-- in, because the money arrives at an account and not at a person. (Q1 uses
-- the client's own district; the two differ for 9.1 percent of owners.)
-- Ties: rank() is reported alongside the row number so that a tie at the
-- boundary is visible rather than silently truncated.
WITH district_totals AS (
    SELECT
        d.district_id,
        d.district_name,
        d.region,
        sum(t.amount)                                     AS total_incoming_amount,
        count(*)                                          AS incoming_transactions,
        count(DISTINCT t.account_id)                      AS accounts
    FROM core.fact_transaction t
    JOIN core.dim_account  a ON a.account_id = t.account_id
    JOIN core.dim_district d ON d.district_id = a.district_id
    WHERE t.direction = 'credit'
      AND t.trans_date BETWEEN DATE '1997-01-01' AND DATE '1997-12-31'
    GROUP BY d.district_id, d.district_name, d.region
)
SELECT
    rank() OVER (ORDER BY total_incoming_amount DESC)     AS rank,
    district_id,
    district_name,
    region,
    total_incoming_amount,
    incoming_transactions,
    accounts
FROM district_totals
ORDER BY total_incoming_amount DESC
LIMIT 10;

-- @@Q6
-- Q6: How many new accounts were opened per month in 1996?
--
-- Interpretation (A9): "new account" is dated by account.date (the opening
-- date). All twelve months are reported, with zero where no account was
-- opened, by driving the query from the date dimension -- a query that groups
-- only the accounts would silently omit an empty month, and an omitted month
-- reads as "no data" rather than "no accounts".
SELECT
    m.year_month,
    m.month                                               AS month_number,
    m.month_name,
    count(a.account_id)                                   AS accounts_opened
FROM (
    SELECT DISTINCT year_month, month, month_name, month_start
    FROM core.dim_date
    WHERE year = 1996
) m
LEFT JOIN core.dim_account a
       ON date_trunc('month', a.open_date) = m.month_start
GROUP BY m.year_month, m.month, m.month_name
ORDER BY m.month;

-- @@Q7
-- Q7: What was the average age of the account owner at loan start, per loan status?
--
-- Interpretation (A10): age is exact, computed from the owner's date of birth
-- to the loan start date in years including the fractional part, not as a
-- difference of calendar years.
-- Interpretation (A11): the owner is the OWNER disposition of the loan's
-- account. Owners whose birth number does not decode would be excluded and
-- reported in owners_with_known_age; there are none in this copy.
-- Data quality caveat: 6 loans were granted to owners recorded as under 15
-- (dq rule VAL_OWNER_AGE_AT_LOAN_START, severity warn). The average is
-- reported both with and without those flagged loans, so the sensitivity is
-- visible instead of buried.
SELECT
    status_code,
    loan_status,
    count(*)                                              AS loans,
    count(owner_age_at_loan_start)                        AS owners_with_known_age,
    round(avg(owner_age_at_loan_start), 2)                AS average_age_at_loan_start,
    round(avg(owner_age_at_loan_start) FILTER (
        WHERE NOT ('val_owner_age_at_loan_start' = ANY (_dq_flags))
    ), 2)                                                 AS average_age_excluding_flagged,
    count(*) FILTER (
        WHERE 'val_owner_age_at_loan_start' = ANY (_dq_flags)
    )                                                     AS loans_flagged_implausible_age
FROM core.v_loan_enriched
GROUP BY status_code, loan_status
ORDER BY status_code;

-- @@Q8
-- Q8: What is the gender split of account owners holding a gold card?
--
-- Interpretation (A12): the population is account OWNERS whose own disposition
-- holds a gold card. A gold card held by a disponent does not make the owner a
-- gold card holder.
-- Interpretation (A13): the unit counted is the owner (one row per account in
-- v_account_owner). A client who owns two accounts each with a gold card would
-- be counted twice as a card holder; count(distinct owner_client_id) is
-- reported alongside so both readings are available.
SELECT
    owner_gender                                          AS gender,
    count(*)                                              AS gold_card_owners,
    count(DISTINCT owner_client_id)                       AS distinct_clients,
    round(100.0 * count(*) / sum(count(*)) OVER (), 2)    AS pct_of_gold_card_owners
FROM core.v_account_owner
WHERE owner_card_type = 'gold'
GROUP BY owner_gender
ORDER BY gold_card_owners DESC;

-- @@Q9
-- Q9: What was the average account balance at the end of December 1998?
--
-- Interpretation (A14): the balance of an account at 1998-12-31 is the balance
-- after the last posting on or before that date, taken from
-- core.fact_account_month_end_balance (month-end grain, carry-forward applied).
-- When several postings share that date, the closing one is the end of the
-- day's running-balance chain (D028); accounts_closing_ambiguous counts the
-- balances where the chain could not order the postings and the documented
-- fallback decided. tests/test_month_end.py re-derives these balances
-- independently of the fact table.
-- Interpretation (A15): the average is over accounts that have a known balance
-- on that date -- that is, accounts with at least one posting on or before it.
-- An account with no posting has no balance and is not counted as zero, which
-- would bias the average downwards.
-- Data quality caveats, both reported next to the number rather than in a
-- footnote: accounts_carried_forward had no posting in December 1998 and
-- inherit their last known balance; accounts_balance_unreconciled are the
-- accounts whose flows disagree with their reported balance by more than
-- 100 CZK (dq rule CON_BALANCE_RECONCILIATION_MATERIAL).
SELECT
    count(*)                                              AS accounts_with_known_balance,
    round(avg(b.closing_balance), 2)                      AS average_balance,
    round(percentile_cont(0.5) WITHIN GROUP (ORDER BY b.closing_balance)::numeric, 2)
                                                          AS median_balance,
    min(b.closing_balance)                                AS min_balance,
    max(b.closing_balance)                                AS max_balance,
    count(*) FILTER (WHERE b.is_carried_forward)          AS accounts_carried_forward,
    count(*) FILTER (WHERE 'con_balance_reconciliation_material' = ANY (a._dq_flags))
                                                          AS accounts_balance_unreconciled,
    count(*) FILTER (WHERE b.closing_balance < 0)         AS accounts_overdrawn,
    count(*) FILTER (WHERE b.closing_basis = 'ambiguous') AS accounts_closing_ambiguous
FROM core.fact_account_month_end_balance b
JOIN core.dim_account a ON a.account_id = b.account_id
WHERE b.month_end_date = DATE '1998-12-31';

-- @@Q10
-- Q10: Which statement frequency has the highest share of problematic loans?
--
-- Interpretation (A16): the share is problematic loans divided by all loans
-- carried by accounts with that statement frequency -- a within-frequency
-- rate, not each frequency's share of all problematic loans.
-- The full ranking is returned, not only the winner, because with 682 loans
-- spread over three frequencies the top group can rest on a small denominator;
-- the loan count next to the share is what makes that visible.
SELECT
    statement_frequency,
    count(*)                                              AS loans,
    count(*) FILTER (WHERE is_problematic)                AS problematic_loans,
    round(100.0 * count(*) FILTER (WHERE is_problematic) / count(*), 2)
                                                          AS problematic_pct,
    rank() OVER (
        ORDER BY 1.0 * count(*) FILTER (WHERE is_problematic) / count(*) DESC
    )                                                     AS rank_by_problematic_share
FROM core.v_loan_enriched
GROUP BY statement_frequency
ORDER BY problematic_pct DESC;
