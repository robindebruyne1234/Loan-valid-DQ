-- ============================================================================
-- 30_core.sql -- the cleaned, modelled data product
--
-- Grain and keys are stated on every table, because the semantic layer
-- publishes them to the LLM and a wrong grain is how an AI assistant produces
-- a confidently wrong number.
--
-- Built from stg MINUS dq.v_blocked (the rows block rules rejected), with warn
-- flags joined in from dq.v_row_flags into _dq_flags. Lineage: _stg_key is the
-- natural key in staging, and staging carries _source_file / _source_row, so
-- any value in core traces to a line in a file whose SHA-256 is in
-- raw.load_audit.
--
-- Natural keys are used as primary keys rather than surrogates: the source keys
-- are stable integers, and at 1.06 m rows a surrogate layer would add a join
-- for no benefit. See DECISIONS.md D007 for what changes at 100,000x.
-- ============================================================================

DROP VIEW IF EXISTS core.v_loan_enriched    CASCADE;
DROP VIEW IF EXISTS core.v_account_owner    CASCADE;
DROP VIEW IF EXISTS core.v_client_region    CASCADE;
DROP TABLE IF EXISTS core.fact_account_month_end_balance CASCADE;
DROP TABLE IF EXISTS core.fact_transaction  CASCADE;
DROP TABLE IF EXISTS core.fact_loan         CASCADE;
DROP TABLE IF EXISTS core.dim_card          CASCADE;
DROP TABLE IF EXISTS core.bridge_disposition CASCADE;
DROP TABLE IF EXISTS core.dim_account       CASCADE;
DROP TABLE IF EXISTS core.dim_client        CASCADE;
DROP TABLE IF EXISTS core.dim_district      CASCADE;
DROP TABLE IF EXISTS core.dim_date          CASCADE;

-- ----------------------------------------------------------------------------
-- core.dim_date
-- Grain: one row per calendar day in the dataset window (1993-01-01..1998-12-31).
-- Exists so that "per month in 1996" (Q6) can report all twelve months,
-- including months with no activity, without the query having to invent them.
-- ----------------------------------------------------------------------------
CREATE TABLE core.dim_date AS
SELECT
    d::date                                                   AS date_key,
    extract(year  FROM d)::int                                AS year,
    extract(quarter FROM d)::int                              AS quarter,
    extract(month FROM d)::int                                AS month,
    to_char(d, 'FMMonth')                                     AS month_name,
    to_char(d, 'YYYY-MM')                                     AS year_month,
    extract(day FROM d)::int                                  AS day_of_month,
    extract(isodow FROM d)::int                               AS iso_day_of_week,
    to_char(d, 'FMDay')                                       AS day_name,
    date_trunc('month', d)::date                              AS month_start,
    (date_trunc('month', d) + INTERVAL '1 month - 1 day')::date AS month_end,
    (d = (date_trunc('month', d) + INTERVAL '1 month - 1 day')::date) AS is_month_end
FROM generate_series(DATE '1993-01-01', DATE '1998-12-31', INTERVAL '1 day') AS g(d);

ALTER TABLE core.dim_date ADD PRIMARY KEY (date_key);
CREATE INDEX ix_core_dim_date_month ON core.dim_date (year, month);

COMMENT ON TABLE core.dim_date IS
    'Calendar dimension, one row per day 1993-01-01..1998-12-31. Grain: day.';

-- ----------------------------------------------------------------------------
-- core.dim_district
-- Grain: one row per administrative district (77). Reference data: joined by
-- both clients and accounts, and the source of the "region" Q1 groups by.
-- ----------------------------------------------------------------------------
CREATE TABLE core.dim_district AS
SELECT
    s.district_id,
    s.district_name,
    s.region,
    s.inhabitants,
    s.municipalities_lt_499,
    s.municipalities_500_1999,
    s.municipalities_2000_9999,
    s.municipalities_gt_10000,
    s.cities,
    s.urban_ratio_pct,
    s.average_salary,
    s.unemployment_rate_1995,
    s.unemployment_rate_1996,
    s.entrepreneurs_per_1000,
    s.crimes_1995,
    s.crimes_1996,
    s.district_id                               AS _stg_key,
    coalesce(f.flags, ARRAY[]::text[])          AS _dq_flags
FROM stg.district s
LEFT JOIN dq.v_row_flags f
       ON f.target_table = 'district' AND f.business_key = s.district_id::text
WHERE s.district_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM dq.v_blocked b
      WHERE b.target_table = 'district' AND b.business_key = s.district_id::text
  );

ALTER TABLE core.dim_district ADD PRIMARY KEY (district_id);

COMMENT ON TABLE core.dim_district IS
    'District reference data. Grain: one row per district. 1995 unemployment '
    'and crime figures are NULL for district 69 (source carries ?).';

-- ----------------------------------------------------------------------------
-- core.dim_client
-- Grain: one row per client. The entitlement key: sec grants access per client.
-- ----------------------------------------------------------------------------
CREATE TABLE core.dim_client AS
SELECT
    s.client_id,
    s.birth_date,
    s.gender,
    s.birth_number_valid,
    s.district_id,
    s.client_id                                 AS _stg_key,
    coalesce(f.flags, ARRAY[]::text[])          AS _dq_flags
FROM stg.client s
LEFT JOIN dq.v_row_flags f
       ON f.target_table = 'client' AND f.business_key = s.client_id::text
WHERE s.client_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM dq.v_blocked b
      WHERE b.target_table = 'client' AND b.business_key = s.client_id::text
  );

ALTER TABLE core.dim_client ADD PRIMARY KEY (client_id);
CREATE INDEX ix_core_dim_client_district ON core.dim_client (district_id);

COMMENT ON TABLE core.dim_client IS
    'Client dimension. Grain: one row per client. birth_date and gender are '
    'decoded from the source birth_number; birth_number_valid says whether '
    'that decode succeeded.';

-- ----------------------------------------------------------------------------
-- core.dim_account
-- Grain: one row per account. statement_frequency is the English label; the
-- original Czech code is kept beside it so the two can never disagree.
-- ----------------------------------------------------------------------------
CREATE TABLE core.dim_account AS
SELECT
    s.account_id,
    s.open_date,
    s.frequency_code                            AS statement_frequency_code,
    coalesce(r.label, 'unknown')                AS statement_frequency,
    s.district_id,
    s.account_id                                AS _stg_key,
    coalesce(f.flags, ARRAY[]::text[])          AS _dq_flags
FROM stg.account s
LEFT JOIN core.ref_codes r
       ON r.code_set = 'statement_frequency' AND r.code = s.frequency_code
LEFT JOIN dq.v_row_flags f
       ON f.target_table = 'account' AND f.business_key = s.account_id::text
WHERE s.account_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM dq.v_blocked b
      WHERE b.target_table = 'account' AND b.business_key = s.account_id::text
  );

ALTER TABLE core.dim_account ADD PRIMARY KEY (account_id);
CREATE INDEX ix_core_dim_account_district ON core.dim_account (district_id);
CREATE INDEX ix_core_dim_account_open     ON core.dim_account (open_date);

COMMENT ON TABLE core.dim_account IS
    'Account dimension. Grain: one row per account. The district is where the '
    'account is registered, which is not always where its owner lives '
    '(9.1 percent differ -- see dq rule CON_CLIENT_ACCOUNT_DISTRICT_MISMATCH).';

-- ----------------------------------------------------------------------------
-- core.bridge_disposition
-- Grain: one row per disposition = one (client, account, capacity) triple.
-- This is a bridge and not a dimension on purpose: it is many-to-many, and
-- collapsing it into either side is what makes "the account owner" ambiguous.
-- ----------------------------------------------------------------------------
CREATE TABLE core.bridge_disposition AS
SELECT
    s.disp_id,
    s.client_id,
    s.account_id,
    s.disp_type_code,
    coalesce(r.label, 'unknown')                AS disposition_type,
    (s.disp_type_code = 'OWNER')                AS is_owner,
    s.disp_id                                   AS _stg_key,
    coalesce(f.flags, ARRAY[]::text[])          AS _dq_flags
FROM stg.disp s
LEFT JOIN core.ref_codes r
       ON r.code_set = 'disposition_type' AND r.code = s.disp_type_code
LEFT JOIN dq.v_row_flags f
       ON f.target_table = 'disp' AND f.business_key = s.disp_id::text
WHERE s.disp_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM dq.v_blocked b
      WHERE b.target_table = 'disp' AND b.business_key = s.disp_id::text
  );

ALTER TABLE core.bridge_disposition ADD PRIMARY KEY (disp_id);
CREATE INDEX ix_core_bridge_account ON core.bridge_disposition (account_id, is_owner);
CREATE INDEX ix_core_bridge_client  ON core.bridge_disposition (client_id);

COMMENT ON TABLE core.bridge_disposition IS
    'Client-to-account bridge. Grain: one disposition. is_owner marks the '
    'single legal account holder; a DISPONENT may operate the account but is '
    'not its owner, which is the distinction Q4, Q7, Q8 and Q9 depend on.';

-- ----------------------------------------------------------------------------
-- core.dim_card
-- Grain: one row per issued card. A card belongs to a DISPOSITION, so its
-- holder is not necessarily the account owner.
-- ----------------------------------------------------------------------------
CREATE TABLE core.dim_card AS
SELECT
    s.card_id,
    s.disp_id,
    s.card_type                                 AS card_type_code,
    coalesce(r.label, 'unknown card type')      AS card_type,
    s.issued_date,
    s.card_id                                   AS _stg_key,
    coalesce(f.flags, ARRAY[]::text[])          AS _dq_flags
FROM stg.card s
LEFT JOIN core.ref_codes r
       ON r.code_set = 'card_type' AND r.code = s.card_type
LEFT JOIN dq.v_row_flags f
       ON f.target_table = 'card' AND f.business_key = s.card_id::text
WHERE s.card_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM dq.v_blocked b
      WHERE b.target_table = 'card' AND b.business_key = s.card_id::text
  );

ALTER TABLE core.dim_card ADD PRIMARY KEY (card_id);
CREATE INDEX ix_core_dim_card_disp ON core.dim_card (disp_id);

COMMENT ON TABLE core.dim_card IS
    'Card dimension. Grain: one row per card. Joined to a client through '
    'bridge_disposition, never directly.';

-- ----------------------------------------------------------------------------
-- core.fact_loan
-- Grain: one row per loan (682). is_problematic is the certified definition of
-- "problematic" used by Q3 and Q10: status B (finished, unpaid) or D (running,
-- in debt). Defining it once here is what stops an LLM inventing its own.
-- ----------------------------------------------------------------------------
CREATE TABLE core.fact_loan AS
SELECT
    s.loan_id,
    s.account_id,
    s.loan_date,
    extract(year FROM s.loan_date)::int          AS loan_year,
    s.amount,
    s.duration_months,
    s.monthly_payment,
    s.status_code,
    coalesce(r.label, 'unknown')                 AS loan_status,
    (s.status_code IN ('B', 'D'))                AS is_problematic,
    s.loan_id                                    AS _stg_key,
    coalesce(f.flags, ARRAY[]::text[])           AS _dq_flags
FROM stg.loan s
LEFT JOIN core.ref_codes r
       ON r.code_set = 'loan_status' AND r.code = s.status_code
LEFT JOIN dq.v_row_flags f
       ON f.target_table = 'loan' AND f.business_key = s.loan_id::text
WHERE s.loan_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM dq.v_blocked b
      WHERE b.target_table = 'loan' AND b.business_key = s.loan_id::text
  );

ALTER TABLE core.fact_loan ADD PRIMARY KEY (loan_id);
CREATE INDEX ix_core_fact_loan_account ON core.fact_loan (account_id);
CREATE INDEX ix_core_fact_loan_date    ON core.fact_loan (loan_date);

COMMENT ON TABLE core.fact_loan IS
    'Loan fact. Grain: one row per loan. is_problematic = status B or D, which '
    'is the single certified definition of a problematic loan in this product.';

-- ----------------------------------------------------------------------------
-- core.fact_transaction
-- Grain: one row per posting (1.06 m).
-- signed_amount (credits positive, debits negative) is pre-computed so that no
-- consumer has to re-derive the sign from the Czech type code -- the single
-- most likely place for an LLM-written query to go wrong.
-- ----------------------------------------------------------------------------
CREATE TABLE core.fact_transaction AS
SELECT
    s.trans_id,
    s.account_id,
    s.trans_date,
    s.trans_type_code,
    coalesce(rt.label, 'unknown')                AS transaction_type,
    s.direction,
    s.amount,
    s.signed_amount,
    s.balance_after,
    s.operation_code,
    ro.label                                     AS operation,
    s.k_symbol_code                              AS category_code,
    rk.label                                     AS category,
    s.partner_bank,
    s.partner_account,
    s.trans_id                                   AS _stg_key,
    coalesce(f.flags, ARRAY[]::text[])           AS _dq_flags
FROM stg.trans s
LEFT JOIN core.ref_codes rt
       ON rt.code_set = 'transaction_type' AND rt.code = s.trans_type_code
LEFT JOIN core.ref_codes ro
       ON ro.code_set = 'transaction_operation' AND ro.code = s.operation_code
LEFT JOIN core.ref_codes rk
       ON rk.code_set = 'transaction_category' AND rk.code = s.k_symbol_code
LEFT JOIN dq.v_row_flags f
       ON f.target_table = 'trans' AND f.business_key = s.trans_id::text
WHERE s.trans_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM dq.v_blocked b
      WHERE b.target_table = 'trans' AND b.business_key = s.trans_id::text
  );

ALTER TABLE core.fact_transaction ADD PRIMARY KEY (trans_id);
CREATE INDEX ix_core_fact_trans_account_date
    ON core.fact_transaction (account_id, trans_date, trans_id);
CREATE INDEX ix_core_fact_trans_date ON core.fact_transaction (trans_date);

COMMENT ON TABLE core.fact_transaction IS
    'Transaction fact. Grain: one row per posting. signed_amount is positive '
    'for credits (PRIJEM) and negative for debits (VYDAJ, VYBER); '
    'balance_after is the balance the source reports after the posting. '
    'operation is NULL for bank-generated interest postings, by design.';

-- ----------------------------------------------------------------------------
-- core.fact_account_month_end_balance
-- Grain: one row per account per month end, from the account's first posting
-- month to the end of the dataset.
--
-- Built in three steps, because "the balance at the end of a month" is a
-- modelling decision and not a column that exists:
--   1. per account and month, take the posting that closes the month --
--      the latest trans_date in that month, ties broken by the highest
--      trans_id (the documented tie-break; trans_id is not chronological
--      within a day, which dq rule CON_INTRADAY_ORDER_AMBIGUOUS reports);
--   2. build the full account x month grid so months with no activity exist;
--   3. carry the last known balance forward into those months and mark them
--      with is_carried_forward, so a consumer can tell a real month-end
--      balance from an inherited one.
-- ----------------------------------------------------------------------------
CREATE TABLE core.fact_account_month_end_balance AS
WITH month_ends AS (
    SELECT DISTINCT month_end FROM core.dim_date
),
closing AS (
    -- step 1: the posting that closes each month the account was active in
    SELECT DISTINCT ON (t.account_id, date_trunc('month', t.trans_date))
           t.account_id,
           (date_trunc('month', t.trans_date) + INTERVAL '1 month - 1 day')::date AS month_end,
           t.balance_after,
           t.trans_id
    FROM core.fact_transaction t
    ORDER BY t.account_id,
             date_trunc('month', t.trans_date),
             t.trans_date DESC,
             t.trans_id DESC
),
first_month AS (
    SELECT account_id,
           (date_trunc('month', min(trans_date)) + INTERVAL '1 month - 1 day')::date AS first_month_end
    FROM core.fact_transaction
    GROUP BY account_id
),
grid AS (
    -- step 2: every month end from the first posting month onwards
    SELECT fm.account_id, m.month_end
    FROM first_month fm
    JOIN month_ends m ON m.month_end >= fm.first_month_end
),
joined AS (
    SELECT g.account_id,
           g.month_end,
           c.balance_after,
           c.trans_id,
           count(c.balance_after) OVER (PARTITION BY g.account_id ORDER BY g.month_end) AS carry_group
    FROM grid g
    LEFT JOIN closing c ON c.account_id = g.account_id AND c.month_end = g.month_end
)
-- step 3: carry forward within each group of months that share a last posting
SELECT
    j.account_id,
    j.month_end                                                    AS month_end_date,
    first_value(j.balance_after) OVER w                            AS closing_balance,
    first_value(j.trans_id) OVER w                                 AS last_trans_id,
    (j.balance_after IS NULL)                                      AS is_carried_forward,
    first_value(j.month_end) OVER w                                AS balance_as_of_month_end
FROM joined j
WINDOW w AS (PARTITION BY j.account_id, j.carry_group ORDER BY j.month_end);

ALTER TABLE core.fact_account_month_end_balance
    ADD PRIMARY KEY (account_id, month_end_date);
CREATE INDEX ix_core_meb_month ON core.fact_account_month_end_balance (month_end_date);

COMMENT ON TABLE core.fact_account_month_end_balance IS
    'Month-end balance per account. Grain: account x month end. '
    'is_carried_forward = true means the account had no posting in that month '
    'and the balance is inherited from balance_as_of_month_end. Built with the '
    'documented tie-break (latest date in the month, then highest trans_id).';

-- ----------------------------------------------------------------------------
-- Curated views: the join paths a business question needs, written once.
-- These are what the ai schema exposes, so that an LLM never has to rediscover
-- that "the account owner" means a disposition of type OWNER.
--
-- WITH (security_invoker = true) is not optional here, and it is the subtlest
-- thing in this submission. A PostgreSQL view normally reads its base tables
-- with its OWNER's rights, and the owner is exempt from its own row level
-- security policies. So a security_invoker view in the ai schema reading a
-- NON-invoker view in core evaluates the policies as the view owner -- and
-- returns everything. That is exactly what happened the first time these views
-- were built: ai.loan returned all 682 loans to a user entitled to none,
-- while the base table core.fact_loan correctly returned 0 for the same user.
-- The chain is only as strong as its weakest view, so every view between the
-- consumer and the policy carries the setting. tests/test_rls.py pins it.
-- ----------------------------------------------------------------------------

CREATE VIEW core.v_account_owner WITH (security_invoker = true) AS
SELECT
    a.account_id,
    a.open_date                         AS account_open_date,
    a.statement_frequency,
    a.statement_frequency_code,
    a.district_id                       AS account_district_id,
    ad.district_name                    AS account_district_name,
    ad.region                           AS account_region,
    d.disp_id                           AS owner_disp_id,
    c.client_id                         AS owner_client_id,
    c.birth_date                        AS owner_birth_date,
    c.gender                            AS owner_gender,
    c.birth_number_valid                AS owner_birth_number_valid,
    c.district_id                       AS owner_district_id,
    cd.district_name                    AS owner_district_name,
    cd.region                           AS owner_region,
    k.card_id                           AS owner_card_id,
    k.card_type                         AS owner_card_type,
    k.issued_date                       AS owner_card_issued_date,
    (a._dq_flags || c._dq_flags || d._dq_flags) AS _dq_flags
FROM core.dim_account a
JOIN core.bridge_disposition d ON d.account_id = a.account_id AND d.is_owner
JOIN core.dim_client c         ON c.client_id = d.client_id
LEFT JOIN core.dim_district ad ON ad.district_id = a.district_id
LEFT JOIN core.dim_district cd ON cd.district_id = c.district_id
-- The owner's card, if any. A disponent's card is deliberately NOT joined
-- here: Q4 and Q8 both say "of the account owner".
LEFT JOIN core.dim_card k      ON k.disp_id = d.disp_id;

COMMENT ON VIEW core.v_account_owner IS
    'One row per account with its legal owner, the owner''s own district and '
    'the owner''s card. Grain: one row per account (guaranteed by the '
    'one-OWNER-per-account block rule). Use this instead of joining disp by '
    'hand -- it is the only place that decides what "the account owner" means.';

CREATE VIEW core.v_loan_enriched WITH (security_invoker = true) AS
SELECT
    l.loan_id,
    l.account_id,
    l.loan_date,
    l.loan_year,
    l.amount,
    l.duration_months,
    l.monthly_payment,
    l.status_code,
    l.loan_status,
    l.is_problematic,
    o.statement_frequency,
    o.owner_client_id,
    o.owner_birth_date,
    o.owner_gender,
    o.owner_card_type,
    o.account_district_name,
    o.account_region,
    o.owner_district_name,
    o.owner_region,
    -- Exact age in years at loan start, from the owner's date of birth.
    CASE
        WHEN o.owner_birth_date IS NOT NULL AND l.loan_date IS NOT NULL
        THEN extract(year FROM age(l.loan_date, o.owner_birth_date))
             + extract(month FROM age(l.loan_date, o.owner_birth_date)) / 12.0
             + extract(day FROM age(l.loan_date, o.owner_birth_date)) / 365.25
    END                                              AS owner_age_at_loan_start,
    (l._dq_flags || o._dq_flags)                     AS _dq_flags
FROM core.fact_loan l
LEFT JOIN core.v_account_owner o ON o.account_id = l.account_id;

COMMENT ON VIEW core.v_loan_enriched IS
    'One row per loan with its account owner, the owner''s card type, the '
    'statement frequency and the owner''s exact age at loan start. Grain: one '
    'row per loan. Covers Q2, Q3, Q4, Q7 and Q10 without any further joins.';

CREATE VIEW core.v_client_region WITH (security_invoker = true) AS
SELECT
    c.client_id,
    c.birth_date,
    c.gender,
    c.district_id,
    d.district_name,
    coalesce(d.region, 'unknown region')             AS region,
    EXISTS (SELECT 1 FROM core.bridge_disposition b WHERE b.client_id = c.client_id)
                                                     AS has_account,
    EXISTS (SELECT 1 FROM core.bridge_disposition b
            WHERE b.client_id = c.client_id AND b.is_owner)
                                                     AS is_account_owner,
    c._dq_flags
FROM core.dim_client c
LEFT JOIN core.dim_district d ON d.district_id = c.district_id;

COMMENT ON VIEW core.v_client_region IS
    'One row per client with the region of the client''s OWN district (not of '
    'their account''s district -- the two differ for 9.1 percent of owners). '
    'Grain: one row per client. This is the view Q1 is answered from.';

ANALYZE core.dim_date;
ANALYZE core.dim_district;
ANALYZE core.dim_client;
ANALYZE core.dim_account;
ANALYZE core.bridge_disposition;
ANALYZE core.dim_card;
ANALYZE core.fact_loan;
ANALYZE core.fact_transaction;
ANALYZE core.fact_account_month_end_balance;
