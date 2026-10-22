-- ============================================================================
-- 70_inject_defects.sql -- build a deliberately corrupted copy of staging
--
-- WHY THIS EXISTS
-- The brief says the bank may have injected defects into its copy of the data,
-- and the assessment compares findings against those defects. No bank-supplied
-- copy was received, and the public copy matches the published reference counts
-- exactly, so most rules legitimately report zero. A rule that has never fired
-- is not evidence of anything.
--
-- This script therefore creates schema `inject`: a full copy of `stg` with one
-- seeded defect per rule family. `make test` runs the identical rule set
-- against it and asserts that each seeded defect is caught by the rule that is
-- supposed to catch it (tests/test_dq.py).
--
-- GUARANTEES
--   * deterministic: every target row is selected by an explicit ORDER BY, so
--     two runs corrupt exactly the same rows;
--   * isolated: `inject` is never read by core, by the ai views or by any
--     answer. The reported answers come from untouched data;
--   * labelled: every injected row is recorded in inject.injected_defect, with
--     the rule_id it is meant to trigger.
-- ============================================================================

DROP SCHEMA IF EXISTS inject CASCADE;
CREATE SCHEMA inject;

COMMENT ON SCHEMA inject IS
    'Deliberately corrupted copy of stg, used only to prove the data quality '
    'rules fire. Never feeds core or the ai views.';

CREATE TABLE inject.account  AS SELECT * FROM stg.account;
CREATE TABLE inject.client   AS SELECT * FROM stg.client;
CREATE TABLE inject.disp     AS SELECT * FROM stg.disp;
CREATE TABLE inject.card     AS SELECT * FROM stg.card;
CREATE TABLE inject.loan     AS SELECT * FROM stg.loan;
CREATE TABLE inject."order"  AS SELECT * FROM stg."order";
CREATE TABLE inject.trans    AS SELECT * FROM stg.trans;
CREATE TABLE inject.district AS SELECT * FROM stg.district;

CREATE INDEX ix_inject_trans_account_date ON inject.trans (account_id, trans_date, trans_id);
CREATE INDEX ix_inject_disp_account       ON inject.disp (account_id);
CREATE INDEX ix_inject_loan_account       ON inject.loan (account_id);

-- Register of what was injected, so the test suite can assert rule by rule.
CREATE TABLE inject.injected_defect (
    defect_no        integer PRIMARY KEY,
    expected_rule_id text    NOT NULL,
    dimension        text    NOT NULL,
    target_table     text    NOT NULL,
    business_key     text,
    description      text    NOT NULL
);

-- ---------------------------------------------------------------------------
-- 1. UNIQUENESS -- duplicate primary key (account)
-- ---------------------------------------------------------------------------
INSERT INTO inject.account
SELECT * FROM inject.account ORDER BY account_id LIMIT 1;

INSERT INTO inject.injected_defect VALUES (
    1, 'UNQ_ACCOUNT_PK', 'uniqueness', 'account',
    (SELECT min(account_id)::text FROM inject.account),
    'Lowest account_id duplicated as a second identical row'
);

-- ---------------------------------------------------------------------------
-- 2. UNIQUENESS -- duplicate primary key (client)
-- ---------------------------------------------------------------------------
INSERT INTO inject.client
SELECT * FROM inject.client ORDER BY client_id LIMIT 1;

INSERT INTO inject.injected_defect VALUES (
    2, 'UNQ_CLIENT_PK', 'uniqueness', 'client',
    (SELECT min(client_id)::text FROM inject.client),
    'Lowest client_id duplicated as a second identical row'
);

-- ---------------------------------------------------------------------------
-- 3. UNIQUENESS -- a second OWNER disposition on one account
-- ---------------------------------------------------------------------------
INSERT INTO inject.disp (disp_id, client_id, account_id, disp_type_code,
                         disp_type_label, _conversion_notes, _source_file, _source_row)
SELECT 900001, d.client_id, d.account_id, 'OWNER', 'owner', NULL, 'injected', -1
FROM inject.disp d
WHERE d.disp_type_code = 'OWNER'
ORDER BY d.account_id
LIMIT 1;

INSERT INTO inject.injected_defect VALUES (
    3, 'UNQ_ACCOUNT_SINGLE_OWNER', 'uniqueness', 'disp',
    (SELECT account_id::text FROM inject.disp WHERE disp_id = 900001),
    'Second OWNER disposition added to the lowest-numbered owned account'
);

-- ---------------------------------------------------------------------------
-- 4. REFERENTIAL INTEGRITY -- disposition pointing at a client that is gone
-- ---------------------------------------------------------------------------
WITH victim AS (
    SELECT disp_id FROM inject.disp
    WHERE disp_type_code = 'DISPONENT' ORDER BY disp_id LIMIT 1
)
UPDATE inject.disp SET client_id = 9999999
WHERE disp_id IN (SELECT disp_id FROM victim);

INSERT INTO inject.injected_defect VALUES (
    4, 'RI_DISP_CLIENT', 'referential_integrity', 'disp',
    (SELECT disp_id::text FROM inject.disp WHERE client_id = 9999999 LIMIT 1),
    'Disposition repointed at non-existent client_id 9999999'
);

-- ---------------------------------------------------------------------------
-- 5. REFERENTIAL INTEGRITY -- reference data row deleted while still used
-- ---------------------------------------------------------------------------
CREATE TEMP TABLE _deleted_district AS
SELECT district_id FROM inject.district
WHERE district_id IN (SELECT district_id FROM inject.account)
ORDER BY district_id DESC LIMIT 1;

DELETE FROM inject.district WHERE district_id IN (SELECT district_id FROM _deleted_district);

INSERT INTO inject.injected_defect VALUES (
    5, 'RI_ACCOUNT_DISTRICT', 'referential_integrity', 'account',
    (SELECT district_id::text FROM _deleted_district),
    'District row deleted although accounts and clients still reference it'
);

-- ---------------------------------------------------------------------------
-- 6. REFERENTIAL INTEGRITY -- account left without an OWNER
-- ---------------------------------------------------------------------------
CREATE TEMP TABLE _orphaned_account AS
SELECT a.account_id
FROM inject.account a
JOIN inject.disp d ON d.account_id = a.account_id AND d.disp_type_code = 'OWNER'
WHERE a.account_id <> (SELECT min(account_id) FROM inject.account)
ORDER BY a.account_id DESC
LIMIT 1;

DELETE FROM inject.disp
WHERE disp_type_code = 'OWNER'
  AND account_id IN (SELECT account_id FROM _orphaned_account);

INSERT INTO inject.injected_defect VALUES (
    6, 'RI_ACCOUNT_WITHOUT_OWNER', 'referential_integrity', 'account',
    (SELECT account_id::text FROM _orphaned_account),
    'OWNER disposition deleted, leaving the account with no owner'
);

-- ---------------------------------------------------------------------------
-- 7. VALIDITY -- date that is six digits but not a real calendar date
-- ---------------------------------------------------------------------------
CREATE TEMP TABLE _bad_date_account AS
SELECT account_id FROM inject.account
WHERE account_id <> (SELECT min(account_id) FROM inject.account)
ORDER BY account_id LIMIT 1;

UPDATE inject.account
SET open_date = NULL,
    open_date_raw = '930231',
    _conversion_notes = ARRAY['open_date: unparsable 930231']
WHERE account_id IN (SELECT account_id FROM _bad_date_account);

INSERT INTO inject.injected_defect VALUES (
    7, 'VAL_ACCOUNT_OPEN_DATE_UNPARSABLE', 'validity', 'account',
    (SELECT account_id::text FROM _bad_date_account),
    'Opening date replaced with 930231 (31 February), which does not parse'
);

-- ---------------------------------------------------------------------------
-- 8. VALIDITY -- date outside the 1993-1998 window (century error)
-- ---------------------------------------------------------------------------
CREATE TEMP TABLE _out_of_range_loan AS
SELECT loan_id FROM inject.loan ORDER BY loan_id LIMIT 1;

UPDATE inject.loan SET loan_date = DATE '2003-05-01'
WHERE loan_id IN (SELECT loan_id FROM _out_of_range_loan);

INSERT INTO inject.injected_defect VALUES (
    8, 'VAL_DATE_OUT_OF_RANGE', 'validity', 'loan',
    (SELECT loan_id::text FROM _out_of_range_loan),
    'Loan date moved to 2003-05-01, outside the datasets 1993-1998 window'
);

-- ---------------------------------------------------------------------------
-- 9. VALIDITY -- status outside the allowed list
-- ---------------------------------------------------------------------------
CREATE TEMP TABLE _bad_status_loan AS
SELECT loan_id FROM inject.loan
WHERE loan_id NOT IN (SELECT loan_id FROM _out_of_range_loan)
ORDER BY loan_id LIMIT 1;

UPDATE inject.loan
SET status_code = 'X', status_label = NULL, is_problematic = NULL
WHERE loan_id IN (SELECT loan_id FROM _bad_status_loan);

INSERT INTO inject.injected_defect VALUES (
    9, 'VAL_LOAN_STATUS_DOMAIN', 'validity', 'loan',
    (SELECT loan_id::text FROM _bad_status_loan),
    'Loan status set to X, which is not one of A, B, C, D'
);

-- ---------------------------------------------------------------------------
-- 10. VALIDITY -- negative transaction amount (sign applied twice)
-- ---------------------------------------------------------------------------
CREATE TEMP TABLE _negative_trans AS
SELECT trans_id FROM inject.trans
WHERE trans_type_code = 'VYDAJ' AND amount > 0
ORDER BY trans_id LIMIT 1;

UPDATE inject.trans
SET amount = -amount, signed_amount = amount
WHERE trans_id IN (SELECT trans_id FROM _negative_trans);

INSERT INTO inject.injected_defect VALUES (
    10, 'VAL_TRANS_AMOUNT_NEGATIVE', 'validity', 'trans',
    (SELECT trans_id::text FROM _negative_trans),
    'Transaction amount negated, so direction is encoded twice'
);

-- ---------------------------------------------------------------------------
-- 11. VALIDITY -- loan duration outside the offered terms
-- ---------------------------------------------------------------------------
CREATE TEMP TABLE _bad_duration_loan AS
SELECT loan_id FROM inject.loan
WHERE loan_id NOT IN (SELECT loan_id FROM _out_of_range_loan)
  AND loan_id NOT IN (SELECT loan_id FROM _bad_status_loan)
ORDER BY loan_id LIMIT 1;

UPDATE inject.loan SET duration_months = 18
WHERE loan_id IN (SELECT loan_id FROM _bad_duration_loan);

INSERT INTO inject.injected_defect VALUES (
    11, 'VAL_LOAN_DURATION_DOMAIN', 'validity', 'loan',
    (SELECT loan_id::text FROM _bad_duration_loan),
    'Loan duration set to 18 months, which the bank does not offer'
);

-- ---------------------------------------------------------------------------
-- 12. VALIDITY -- card type outside the allowed list
-- ---------------------------------------------------------------------------
CREATE TEMP TABLE _bad_card AS
SELECT card_id FROM inject.card ORDER BY card_id LIMIT 1;

UPDATE inject.card SET card_type = 'platinum'
WHERE card_id IN (SELECT card_id FROM _bad_card);

INSERT INTO inject.injected_defect VALUES (
    12, 'VAL_CARD_TYPE_DOMAIN', 'validity', 'card',
    (SELECT card_id::text FROM _bad_card),
    'Card type set to platinum, which is not junior, classic or gold'
);

-- ---------------------------------------------------------------------------
-- 13. COMPLETENESS -- loan amount removed
-- ---------------------------------------------------------------------------
CREATE TEMP TABLE _null_amount_loan AS
SELECT loan_id FROM inject.loan
WHERE loan_id NOT IN (SELECT loan_id FROM _out_of_range_loan)
  AND loan_id NOT IN (SELECT loan_id FROM _bad_status_loan)
  AND loan_id NOT IN (SELECT loan_id FROM _bad_duration_loan)
ORDER BY loan_id LIMIT 1;

UPDATE inject.loan SET amount = NULL
WHERE loan_id IN (SELECT loan_id FROM _null_amount_loan);

INSERT INTO inject.injected_defect VALUES (
    13, 'COMP_LOAN_AMOUNT_MISSING', 'completeness', 'loan',
    (SELECT loan_id::text FROM _null_amount_loan),
    'Loan amount set to NULL, so SUM and AVG silently skip the loan'
);

-- ---------------------------------------------------------------------------
-- 14. COMPLETENESS -- region removed from reference data
-- ---------------------------------------------------------------------------
CREATE TEMP TABLE _null_region_district AS
SELECT district_id FROM inject.district ORDER BY district_id DESC LIMIT 1;

UPDATE inject.district SET region = NULL
WHERE district_id IN (SELECT district_id FROM _null_region_district);

INSERT INTO inject.injected_defect VALUES (
    14, 'COMP_DISTRICT_REGION_MISSING', 'completeness', 'district',
    (SELECT district_id::text FROM _null_region_district),
    'Region removed from one district, which silently empties a Q1 group'
);

-- ---------------------------------------------------------------------------
-- 15. CONSISTENCY -- loan starting before its account was opened
-- ---------------------------------------------------------------------------
CREATE TEMP TABLE _early_loan AS
SELECT l.loan_id FROM inject.loan l
JOIN inject.account a ON a.account_id = l.account_id
WHERE a.open_date IS NOT NULL
  AND l.loan_id NOT IN (SELECT loan_id FROM _out_of_range_loan)
  AND l.loan_id NOT IN (SELECT loan_id FROM _bad_status_loan)
  AND l.loan_id NOT IN (SELECT loan_id FROM _bad_duration_loan)
  AND l.loan_id NOT IN (SELECT loan_id FROM _null_amount_loan)
ORDER BY l.loan_id LIMIT 1;

UPDATE inject.loan l SET loan_date = a.open_date - INTERVAL '30 days'
FROM inject.account a
WHERE a.account_id = l.account_id AND l.loan_id IN (SELECT loan_id FROM _early_loan);

INSERT INTO inject.injected_defect VALUES (
    15, 'CON_LOAN_BEFORE_ACCOUNT_OPEN', 'consistency', 'loan',
    (SELECT loan_id::text FROM _early_loan),
    'Loan start date moved 30 days before the account opening date'
);

-- ---------------------------------------------------------------------------
-- 16. CONSISTENCY -- running balance broken materially
-- ---------------------------------------------------------------------------
CREATE TEMP TABLE _broken_balance_trans AS
SELECT t.trans_id, t.account_id
FROM inject.trans t
WHERE t.account_id = (
    SELECT account_id FROM inject.trans
    GROUP BY account_id HAVING count(*) BETWEEN 20 AND 60
    ORDER BY account_id LIMIT 1
)
ORDER BY t.trans_date DESC, t.trans_id DESC
LIMIT 1;

UPDATE inject.trans SET balance_after = balance_after + 5000
WHERE trans_id IN (SELECT trans_id FROM _broken_balance_trans);

INSERT INTO inject.injected_defect VALUES (
    16, 'CON_BALANCE_RECONCILIATION_MATERIAL', 'consistency', 'trans',
    (SELECT account_id::text FROM _broken_balance_trans),
    'Last reported balance of one account raised by 5000 CZK with no matching posting'
);

-- ---------------------------------------------------------------------------
-- 17. CONSISTENCY -- operation contradicting the credit/debit direction
-- ---------------------------------------------------------------------------
CREATE TEMP TABLE _contradictory_trans AS
SELECT trans_id FROM inject.trans
WHERE trans_type_code = 'VYDAJ' AND operation_code = 'VYBER'
  AND trans_id NOT IN (SELECT trans_id FROM _negative_trans)
ORDER BY trans_id LIMIT 1;

UPDATE inject.trans
SET operation_code = 'VKLAD', operation_label = 'cash deposit'
WHERE trans_id IN (SELECT trans_id FROM _contradictory_trans);

INSERT INTO inject.injected_defect VALUES (
    17, 'CON_TYPE_OPERATION_DIRECTION', 'consistency', 'trans',
    (SELECT trans_id::text FROM _contradictory_trans),
    'Cash deposit operation placed on a debit transaction type'
);

-- ---------------------------------------------------------------------------
-- 18. CONSISTENCY -- payment schedule arithmetic broken
-- ---------------------------------------------------------------------------
CREATE TEMP TABLE _bad_schedule_loan AS
SELECT loan_id FROM inject.loan
WHERE loan_id NOT IN (SELECT loan_id FROM _out_of_range_loan)
  AND loan_id NOT IN (SELECT loan_id FROM _bad_status_loan)
  AND loan_id NOT IN (SELECT loan_id FROM _bad_duration_loan)
  AND loan_id NOT IN (SELECT loan_id FROM _null_amount_loan)
  AND loan_id NOT IN (SELECT loan_id FROM _early_loan)
ORDER BY loan_id LIMIT 1;

UPDATE inject.loan SET monthly_payment = monthly_payment * 2
WHERE loan_id IN (SELECT loan_id FROM _bad_schedule_loan);

INSERT INTO inject.injected_defect VALUES (
    18, 'CON_LOAN_PAYMENT_SCHEDULE', 'consistency', 'loan',
    (SELECT loan_id::text FROM _bad_schedule_loan),
    'Monthly payment doubled, so payment * duration no longer equals the amount'
);

-- ---------------------------------------------------------------------------
-- 19. COMPLETENESS -- loan status removed
-- ---------------------------------------------------------------------------
CREATE TEMP TABLE _null_status_loan AS
SELECT loan_id FROM inject.loan
WHERE status_code IS NOT NULL
  AND loan_id NOT IN (SELECT loan_id FROM _out_of_range_loan)
  AND loan_id NOT IN (SELECT loan_id FROM _bad_status_loan)
  AND loan_id NOT IN (SELECT loan_id FROM _bad_duration_loan)
  AND loan_id NOT IN (SELECT loan_id FROM _null_amount_loan)
  AND loan_id NOT IN (SELECT loan_id FROM _early_loan)
  AND loan_id NOT IN (SELECT loan_id FROM _bad_schedule_loan)
ORDER BY loan_id LIMIT 1;

UPDATE inject.loan
SET status_code = NULL, status_label = NULL, is_problematic = NULL
WHERE loan_id IN (SELECT loan_id FROM _null_status_loan);

INSERT INTO inject.injected_defect VALUES (
    19, 'COMP_LOAN_STATUS_MISSING', 'completeness', 'loan',
    (SELECT loan_id::text FROM _null_status_loan),
    'Loan status removed, so the loan can be classified neither problematic nor healthy'
);

-- ---------------------------------------------------------------------------
-- 20. RECONCILIATION -- row counts no longer match the raw layer
-- (a consequence of defects 1, 2, 3 and 5 above, asserted explicitly)
-- ---------------------------------------------------------------------------
INSERT INTO inject.injected_defect VALUES (
    20, 'REC_ROWCOUNT_RAW_TO_STG', 'reconciliation', 'all', NULL,
    'Row counts diverge from raw because rows were added and deleted above'
);

ANALYZE inject.trans;
ANALYZE inject.account;
ANALYZE inject.client;
ANALYZE inject.disp;
ANALYZE inject.loan;
ANALYZE inject.card;
ANALYZE inject.district;
