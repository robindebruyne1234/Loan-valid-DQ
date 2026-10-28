-- ============================================================================
-- 61_reference_extra.sql -- REFERENCE answers for the additional questions
--
-- The same rules as 60_reference_queries.sql: hand written against the core
-- model, executed by `python -m src.run_reference --suite extra`, stored in
-- dq/results/reference_results_extra.json, never shown to the model.
--
-- These questions were added after the brief's ten because each one exposed a
-- failure the ten did not: a gender column that is not where the model looked
-- (E1), calendar quarters that were dropped or misread as question labels
-- (E2, E3), and grouping by quarter (E4). They are kept in a separate suite so
-- the brief's ten, and the evidence already produced for them, stay as they are.
--
-- Independence: these read the core tables (fact_loan, bridge_disposition,
-- dim_client, dim_account), not the ai views the model writes against, and
-- spell periods with extract() or explicit date bounds rather than the
-- calendar view, so a defect in the ai surface or the semantic layer cannot
-- make the reference agree with it.
--
-- Machine-readable markers: each query starts with "-- @@<question id>".
-- ============================================================================

-- @@E1
-- E1: Find male or female loans in Q1 1995.
--
-- Interpretation (A47): loans are counted once each and grouped by the gender
-- of the ACCOUNT OWNER (the client whose disposition on the loan's account is
-- OWNER), the convention of A5/A11 for every loan-by-client-attribute
-- question. Gender is an attribute of the client (core.dim_client.gender); a
-- loan reaches it only through the account's owner disposition. Disponents
-- are not borrowers in the source and are not counted -- counting every
-- client on the account would give loan-client pairs, not loans (A47 records
-- the alternative and its size). Interpretation (A48): Q1 1995 is the
-- calendar quarter, loan_date >= 1995-01-01 AND < 1995-04-01.
-- distinct_loans = loans proves the owner join does not repeat a loan.
SELECT
    c.gender                                              AS gender,
    count(*)                                              AS loans,
    count(DISTINCT l.loan_id)                             AS distinct_loans,
    sum(l.amount)                                         AS total_amount
FROM core.fact_loan l
JOIN core.bridge_disposition d ON d.account_id = l.account_id AND d.is_owner
JOIN core.dim_client c         ON c.client_id = d.client_id
WHERE l.loan_date >= DATE '1995-01-01'
  AND l.loan_date <  DATE '1995-04-01'
GROUP BY c.gender
ORDER BY c.gender;

-- @@E2
-- E2: Compare the total amount of loans granted in Q1-Q3 of 1995 with Q1-Q3 of 1998.
--
-- Interpretation (A3, A48): granted = loan_date; Q1-Q3 = calendar quarters 1
-- to 3, i.e. January to September of each named year, one row per year.
SELECT
    extract(year FROM loan_date)::int                     AS year,
    count(*)                                              AS loans,
    sum(amount)                                           AS total_amount
FROM core.fact_loan
WHERE (loan_date >= DATE '1995-01-01' AND loan_date < DATE '1995-10-01')
   OR (loan_date >= DATE '1998-01-01' AND loan_date < DATE '1998-10-01')
GROUP BY 1
ORDER BY 1;

-- @@E3
-- E3: How many new accounts were opened in Q1 1996?
--
-- Interpretation (A10, A48): an account is new on its open_date; Q1 1996 is
-- the calendar quarter 1996-01-01 to 1996-03-31 inclusive.
SELECT count(*)                                           AS new_accounts
FROM core.dim_account
WHERE open_date >= DATE '1996-01-01'
  AND open_date <  DATE '1996-04-01';

-- @@E4
-- E4: How many loans were granted per quarter in 1996?
--
-- Interpretation (A3, A48): granted = loan_date; quarters are calendar
-- quarters; one row per quarter of 1996.
SELECT
    extract(quarter FROM loan_date)::int                  AS quarter,
    count(*)                                              AS loans,
    sum(amount)                                           AS total_amount
FROM core.fact_loan
WHERE loan_date >= DATE '1996-01-01'
  AND loan_date <  DATE '1997-01-01'
GROUP BY 1
ORDER BY 1;
