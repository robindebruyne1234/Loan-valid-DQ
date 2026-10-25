-- ============================================================================
-- 40_ai_views.sql -- the only surface an AI consumer may query
--
-- Three jobs:
--   1. Business naming. Columns are named the way the questions are worded
--      ("region", "statement_frequency", "is_problematic"), so the LLM does
--      not have to translate Czech codes or guess at a join.
--   2. Narrowing. Lineage, audit and staging columns are not exposed; the
--      data quality flags are, as a readable text array, because a consumer
--      that cannot see the caveat cannot repeat it.
--   3. Entitlement enforcement. Every view is created
--      WITH (security_invoker = true), so the row level security policies on
--      the underlying core tables are evaluated as the USER RUNNING THE QUERY
--      and not as the view owner. Without that single setting these views
--      would quietly return everything: a view normally runs with its owner's
--      rights, and the owner is exempt from its own policies.
--
-- The guard in src/sql_guard.py additionally refuses any generated query that
-- references a schema other than `ai`. That is defence in depth, not the
-- control: the control is the policy on the base table, which holds even if a
-- consumer queries core directly.
-- ============================================================================

DROP VIEW IF EXISTS ai.account_month_end_balance CASCADE;
DROP VIEW IF EXISTS ai.transaction             CASCADE;
DROP VIEW IF EXISTS ai.loan                    CASCADE;
DROP VIEW IF EXISTS ai.card                    CASCADE;
DROP VIEW IF EXISTS ai.account_owner           CASCADE;
DROP VIEW IF EXISTS ai.account                 CASCADE;
DROP VIEW IF EXISTS ai.client                  CASCADE;
DROP VIEW IF EXISTS ai.district                CASCADE;
DROP VIEW IF EXISTS ai.calendar                CASCADE;
DROP VIEW IF EXISTS ai.code_reference          CASCADE;
DROP VIEW IF EXISTS ai.my_entitlement          CASCADE;

-- ----------------------------------------------------------------------------
-- ai.district -- reference data, deliberately NOT entitlement filtered (A22):
-- it holds no client information, and filtering it would break every
-- group-by for every user.
-- ----------------------------------------------------------------------------
CREATE VIEW ai.district WITH (security_invoker = true) AS
SELECT
    district_id,
    district_name,
    region,
    inhabitants,
    average_salary,
    unemployment_rate_1996,
    entrepreneurs_per_1000,
    crimes_1996
FROM core.dim_district;

COMMENT ON VIEW ai.district IS
    'One row per administrative district (77). Reference data, not entitlement '
    'filtered. "region" is the grouping Q1 asks for.';

-- ----------------------------------------------------------------------------
-- ai.client -- one row per client, filtered to the caller's entitled clients
-- ----------------------------------------------------------------------------
CREATE VIEW ai.client WITH (security_invoker = true) AS
SELECT
    c.client_id,
    c.client_ref,
    c.birth_date,
    c.gender,
    c.district_id,
    d.district_name,
    coalesce(d.region, 'unknown region')  AS region,
    EXISTS (SELECT 1 FROM core.bridge_disposition b
            WHERE b.client_id = c.client_id AND b.is_owner) AS is_account_owner,
    c._dq_flags                           AS data_quality_flags
FROM core.dim_client c
LEFT JOIN core.dim_district d ON d.district_id = c.district_id;

COMMENT ON VIEW ai.client IS
    'One row per client. "region" is the region of the CLIENT''S OWN district, '
    'which is what Q1 groups by (9.1 percent of owners live in a different '
    'district than their account is registered in).';

-- ----------------------------------------------------------------------------
-- ai.account -- one row per account
-- ----------------------------------------------------------------------------
CREATE VIEW ai.account WITH (security_invoker = true) AS
SELECT
    a.account_id,
    a.account_ref,
    a.open_date,
    a.statement_frequency,
    a.district_id,
    d.district_name,
    d.region,
    a._dq_flags                           AS data_quality_flags
FROM core.dim_account a
LEFT JOIN core.dim_district d ON d.district_id = a.district_id;

COMMENT ON VIEW ai.account IS
    'One row per account. open_date is the date the account was opened, which '
    'is what "new accounts" means in Q6. The district here is where the '
    'ACCOUNT is registered, which Q5 uses.';

-- ----------------------------------------------------------------------------
-- ai.account_owner -- one row per account, with its legal owner and their card
-- ----------------------------------------------------------------------------
CREATE VIEW ai.account_owner WITH (security_invoker = true) AS
SELECT
    account_id,
    account_ref,
    account_open_date,
    statement_frequency,
    account_district_id,
    account_district_name,
    account_region,
    owner_client_id,
    owner_client_ref,
    owner_birth_date,
    owner_gender,
    owner_district_name,
    owner_region,
    owner_card_id,
    owner_card_type,
    owner_card_issued_date,
    _dq_flags                             AS data_quality_flags
FROM core.v_account_owner;

COMMENT ON VIEW ai.account_owner IS
    'One row per account with its single legal owner, the owner''s own region '
    'and the owner''s card. Use this for anything phrased "of the account '
    'owner" (Q4, Q7, Q8): a card held by a disponent is deliberately not '
    'included here.';

-- ----------------------------------------------------------------------------
-- ai.card -- one row per issued card
-- ----------------------------------------------------------------------------
CREATE VIEW ai.card WITH (security_invoker = true) AS
SELECT
    k.card_id,
    k.card_type,
    k.issued_date,
    b.client_id                           AS holder_client_id,
    b.account_id,
    b.is_owner                            AS holder_is_account_owner
FROM core.dim_card k
JOIN core.bridge_disposition b ON b.disp_id = k.disp_id;

COMMENT ON VIEW ai.card IS
    'One row per issued card, with its holder. holder_is_account_owner = false '
    'means the card belongs to a disponent, not to the account owner.';

-- ----------------------------------------------------------------------------
-- ai.loan -- one row per loan, pre-joined to owner, card type and frequency
-- ----------------------------------------------------------------------------
CREATE VIEW ai.loan WITH (security_invoker = true) AS
SELECT
    loan_id,
    account_id,
    loan_date,
    loan_year,
    amount,
    duration_months,
    monthly_payment,
    status_code,
    loan_status,
    is_problematic,
    statement_frequency,
    owner_client_id,
    owner_gender,
    owner_birth_date,
    round(owner_age_at_loan_start, 2)     AS owner_age_at_loan_start,
    coalesce(owner_card_type, 'no card')  AS owner_card_type,
    account_district_name,
    account_region,
    owner_region,
    _dq_flags                             AS data_quality_flags
FROM core.v_loan_enriched;

COMMENT ON VIEW ai.loan IS
    'One row per loan (not per account). is_problematic is the certified '
    'definition: status B (finished, unpaid) or D (running, in debt). '
    'owner_card_type is already the account OWNER''s card type, with the '
    'explicit value "no card" where the owner holds none. '
    'owner_age_at_loan_start is the exact age in years at loan start.';

-- ----------------------------------------------------------------------------
-- ai.transaction -- one row per posting (1.06 m)
-- ----------------------------------------------------------------------------
CREATE VIEW ai.transaction WITH (security_invoker = true) AS
SELECT
    t.trans_id,
    t.account_id,
    t.trans_date,
    t.direction,
    t.transaction_type,
    t.amount,
    t.signed_amount,
    t.balance_after,
    t.operation,
    t.category,
    a.district_id                         AS account_district_id,
    d.district_name                       AS account_district_name,
    d.region                              AS account_region
FROM core.fact_transaction t
JOIN core.dim_account a       ON a.account_id = t.account_id
LEFT JOIN core.dim_district d ON d.district_id = a.district_id;

COMMENT ON VIEW ai.transaction IS
    'One row per posting. direction = ''credit'' is an incoming amount (the '
    'source type PRIJEM) and is what Q5 means by "incoming"; ''debit'' is '
    'outgoing. amount is always positive; signed_amount is negative for '
    'debits. balance_after is the account balance after the posting. '
    'operation is NULL for bank-generated interest postings, by design.';

-- ----------------------------------------------------------------------------
-- ai.account_month_end_balance -- the pre-computed answer surface for Q9
-- ----------------------------------------------------------------------------
CREATE VIEW ai.account_month_end_balance WITH (security_invoker = true) AS
SELECT
    b.account_id,
    b.month_end_date,
    b.closing_balance,
    b.is_carried_forward,
    b.balance_as_of_month_end,
    a._dq_flags                           AS account_data_quality_flags
FROM core.fact_account_month_end_balance b
JOIN core.dim_account a ON a.account_id = b.account_id;

COMMENT ON VIEW ai.account_month_end_balance IS
    'Account balance at each month end. Grain: one row per account per month '
    'end. This is the right source for "the balance at the end of <month>" '
    '(Q9): the intra-day tie-break and the carry-forward for months without '
    'postings are already applied. is_carried_forward = true means the account '
    'had no posting that month and the balance is inherited.';

-- ----------------------------------------------------------------------------
-- ai.calendar -- so "all twelve months" can be answered without inventing rows
-- ----------------------------------------------------------------------------
CREATE VIEW ai.calendar WITH (security_invoker = true) AS
SELECT date_key, year, quarter, month, month_name, year_month,
       month_start, month_end, is_month_end
FROM core.dim_date;

COMMENT ON VIEW ai.calendar IS
    'One row per calendar day, 1993-01-01 to 1998-12-31. Join to this when a '
    'question asks "per month" or "per year" so that periods with no activity '
    'are reported as zero instead of being silently omitted (Q6).';

-- ----------------------------------------------------------------------------
-- ai.code_reference -- the published code catalogue, for explanation
-- ----------------------------------------------------------------------------
CREATE VIEW ai.code_reference WITH (security_invoker = true) AS
SELECT code_set, code, label, code_set_note
FROM core.ref_codes;

COMMENT ON VIEW ai.code_reference IS
    'The published mapping from source codes to business labels. The ai views '
    'already expose the labels, so this is for explaining an answer rather '
    'than for joining.';

-- ----------------------------------------------------------------------------
-- ai.my_entitlement -- what the caller is allowed to see, in the caller's own
-- terms. Exposed on purpose: a user who can see the shape of their own
-- entitlement can tell "no rows" apart from "not entitled", and so can an LLM.
-- ----------------------------------------------------------------------------
CREATE VIEW ai.my_entitlement AS
SELECT
    session_user::text                                        AS database_role,
    -- Which KIND of principal is asking. An assistant that knows it is
    -- serving a customer rather than a relationship manager can word its
    -- answer accordingly, and a reader of a log can tell the two apart.
    coalesce((SELECT u.user_type FROM sec.app_user u
               WHERE u.db_role = session_user AND u.is_active),
             'unknown')                                       AS principal_type,
    (SELECT count(*) FROM sec.v_my_clients)                   AS entitled_clients,
    (SELECT count(*) FROM sec.v_my_accounts)                  AS entitled_accounts,
    -- For staff this is the list of books they hold. For a self-service
    -- customer there is no book, so it reports the subject instead -- which
    -- matters because "(none)" would otherwise be indistinguishable from a
    -- newly created user who has been granted nothing at all.
    coalesce(
        (SELECT string_agg(DISTINCT p.portfolio_code, ', ' ORDER BY p.portfolio_code)
           FROM sec.app_user u
           JOIN sec.user_portfolio up ON up.app_user_id = u.app_user_id
           JOIN sec.portfolio p       ON p.portfolio_id = up.portfolio_id
          WHERE u.db_role = session_user AND u.is_active),
        (SELECT 'SELF:' || u.subject_client_id
           FROM sec.app_user u
          WHERE u.db_role = session_user AND u.is_active
            AND u.subject_client_id IS NOT NULL)
    )                                                         AS portfolios;

COMMENT ON VIEW ai.my_entitlement IS
    'One row describing the calling principal''s own entitlement: what kind of '
    'principal they are, which portfolios they hold (or which single client '
    'they are), and how many clients and accounts that resolves to. Exposed '
    'on purpose so that "no rows" can be told apart from "not entitled".';
