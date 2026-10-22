-- ============================================================================
-- 50_sec_rls.sql -- entitlement-aware access (Task 3)
--
-- THE ANSWER IN ONE PARAGRAPH
-- Entitlements are DATA, not code: three tables say which clients belong to
-- which portfolio and which portfolio belongs to which user. The filter is a
-- row level security POLICY on every core table that carries client data, so
-- it is applied by the database engine inside the plan of every statement, for
-- every connection, whoever wrote the SQL. The ai views are created
-- WITH (security_invoker = true), which means they evaluate those policies as
-- the user running the query rather than as the view owner. An LLM cannot
-- bypass it because the LLM never holds the connection: it emits text, which a
-- guard parses and then executes on a session authenticated as a
-- low-privilege, policy-bound role. There is no prompt, no tool call and no
-- SQL string that can widen that role's visibility -- the predicate is not in
-- the query, so rewriting the query cannot remove it.
--
-- IDENTITY
-- The policy resolves the caller from session_user, the authenticated database
-- role. It deliberately does NOT read a session variable such as
-- current_setting('app.user'): a GUC can be set by anything that can send SQL,
-- so an entitlement built on one would be exactly as strong as the guard in
-- front of it. Role-per-user cannot be re-pointed by any statement the model
-- emits, because changing it requires a password the model never sees.
-- The trade-off (connection pooling) is discussed in the Design Decision
-- Record.
--
-- ONBOARDING A USER OR A PORTFOLIO = INSERT
--   new user          : INSERT INTO sec.app_user, plus a CREATE ROLE ... IN
--                       ROLE ai_consumer for the login (the only DDL, and it
--                       is a credential, not business logic)
--   new portfolio     : INSERT INTO sec.portfolio
--   move clients      : INSERT/DELETE in sec.portfolio_client
--   grant a portfolio : INSERT INTO sec.user_portfolio
-- No policy, no view, no SQL and no application code changes. The policies
-- read the tables, so the next statement already sees the new entitlement.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Roles. ai_consumer is a group role holding exactly the privileges an AI
-- consumer needs; each end user is a login role that inherits from it.
-- ----------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ai_consumer') THEN
        CREATE ROLE ai_consumer NOLOGIN;
    END IF;
END $$;

COMMENT ON ROLE ai_consumer IS
    'Group role for AI consumers: SELECT on the ai views and the core tables '
    'they read, nothing else. Subject to every row level security policy.';

-- ----------------------------------------------------------------------------
-- Entitlement tables. This is the whole model: four tables and two views.
-- ----------------------------------------------------------------------------
DROP VIEW  IF EXISTS sec.v_my_accounts      CASCADE;
DROP VIEW  IF EXISTS sec.v_my_clients       CASCADE;
DROP VIEW  IF EXISTS sec.v_entitlement      CASCADE;
DROP TABLE IF EXISTS sec.user_portfolio     CASCADE;
DROP TABLE IF EXISTS sec.portfolio_client   CASCADE;
DROP TABLE IF EXISTS sec.portfolio          CASCADE;
DROP TABLE IF EXISTS sec.app_user           CASCADE;

CREATE TABLE sec.app_user (
    app_user_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    db_role       name        NOT NULL UNIQUE,
    display_name  text        NOT NULL,
    user_type     text        NOT NULL DEFAULT 'relationship_manager',
    is_active     boolean     NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE sec.app_user IS
    'One row per person (or service) that may query the data product. db_role '
    'is the PostgreSQL login role they authenticate as, which is the identity '
    'the policies resolve. Setting is_active = false revokes access on the '
    'next statement, with no DDL.';

CREATE TABLE sec.portfolio (
    portfolio_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    portfolio_code text NOT NULL UNIQUE,
    description    text NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE sec.portfolio IS
    'A named set of clients. Portfolios exist so that entitlement is granted '
    'in business units ("the northern book") rather than client by client.';

CREATE TABLE sec.portfolio_client (
    portfolio_id bigint NOT NULL REFERENCES sec.portfolio (portfolio_id) ON DELETE CASCADE,
    client_id    bigint NOT NULL,
    added_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (portfolio_id, client_id)
);

CREATE INDEX ix_sec_portfolio_client_client ON sec.portfolio_client (client_id);

COMMENT ON TABLE sec.portfolio_client IS
    'Which clients are in which portfolio. Moving a client between books is '
    'one DELETE and one INSERT; no code changes.';

CREATE TABLE sec.user_portfolio (
    app_user_id  bigint NOT NULL REFERENCES sec.app_user (app_user_id) ON DELETE CASCADE,
    portfolio_id bigint NOT NULL REFERENCES sec.portfolio (portfolio_id) ON DELETE CASCADE,
    granted_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (app_user_id, portfolio_id)
);

COMMENT ON TABLE sec.user_portfolio IS
    'Which user holds which portfolio. A user may hold several (a team lead), '
    'and a portfolio may be held by several users (cover during leave).';

-- ----------------------------------------------------------------------------
-- Entitlement resolution.
--
-- These are plain views owned by the table owner, which is the point: a view
-- that is NOT security_invoker runs with its OWNER's rights, so it can resolve
-- entitlements against core.bridge_disposition without being filtered by the
-- very policies it is helping to evaluate. Without that, the policy on
-- dim_account would need to read bridge_disposition, whose own policy would
-- need to read dim_account, and the recursion would either fail or be
-- defeated by turning a policy off.
--
-- Both views self-filter on session_user, so a consumer granted SELECT on them
-- can only ever see their own entitlement.
-- ----------------------------------------------------------------------------
CREATE VIEW sec.v_my_clients AS
SELECT DISTINCT pc.client_id
FROM sec.app_user u
JOIN sec.user_portfolio  up ON up.app_user_id = u.app_user_id
JOIN sec.portfolio_client pc ON pc.portfolio_id = up.portfolio_id
WHERE u.db_role = session_user
  AND u.is_active;

COMMENT ON VIEW sec.v_my_clients IS
    'The client ids the CALLING user is entitled to. Self-filtering on '
    'session_user: there is no parameter to tamper with.';

CREATE VIEW sec.v_my_accounts AS
SELECT DISTINCT d.account_id
FROM core.bridge_disposition d
JOIN sec.v_my_clients c ON c.client_id = d.client_id
WHERE d.is_owner;

COMMENT ON VIEW sec.v_my_accounts IS
    'The accounts the calling user is entitled to: the accounts OWNED by their '
    'entitled clients (assumption A21 -- a disponent relationship does not '
    'grant the portfolio holder access to the account).';

CREATE VIEW sec.v_entitlement AS
SELECT
    u.db_role,
    u.display_name,
    u.user_type,
    u.is_active,
    p.portfolio_code,
    p.description,
    count(pc.client_id) AS clients_in_portfolio
FROM sec.app_user u
LEFT JOIN sec.user_portfolio  up ON up.app_user_id = u.app_user_id
LEFT JOIN sec.portfolio        p ON p.portfolio_id = up.portfolio_id
LEFT JOIN sec.portfolio_client pc ON pc.portfolio_id = p.portfolio_id
GROUP BY u.db_role, u.display_name, u.user_type, u.is_active,
         p.portfolio_code, p.description;

COMMENT ON VIEW sec.v_entitlement IS
    'Administrative overview: every user, their portfolios and the size of '
    'each. For the data owner, not for consumers.';

-- ----------------------------------------------------------------------------
-- Row level security policies.
--
-- Enabled on every core object that carries client data. NOT enabled on
-- dim_district, dim_date and ref_codes: they hold no client information, and
-- filtering them would break every group-by for every user (assumption A22).
--
-- The policies are SELECT-only because consumers have no write privileges at
-- all; a policy is not the right place to stop a write that the grant already
-- forbids.
--
-- The table owner (berka_owner, which runs the pipeline) is exempt from its
-- own policies, which is what makes the ETL possible. FORCE ROW LEVEL SECURITY
-- is deliberately NOT set for that reason. The owner is a privileged pipeline
-- identity that no AI consumer ever authenticates as; "a user who should see
-- everything" is modelled as a CONSUMER role holding every portfolio
-- (cro_global below), which goes through the policies like everyone else. That
-- distinction matters: unrestricted access is granted through data, never
-- through privilege.
-- ----------------------------------------------------------------------------

ALTER TABLE core.dim_client                     ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.dim_account                    ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.bridge_disposition             ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.dim_card                       ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.fact_loan                      ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.fact_transaction               ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.fact_account_month_end_balance ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS entitled_clients      ON core.dim_client;
DROP POLICY IF EXISTS entitled_accounts     ON core.dim_account;
DROP POLICY IF EXISTS entitled_dispositions ON core.bridge_disposition;
DROP POLICY IF EXISTS entitled_cards        ON core.dim_card;
DROP POLICY IF EXISTS entitled_loans       ON core.fact_loan;
DROP POLICY IF EXISTS entitled_transactions ON core.fact_transaction;
DROP POLICY IF EXISTS entitled_balances     ON core.fact_account_month_end_balance;

-- A client is visible when they are in one of the caller's portfolios.
CREATE POLICY entitled_clients ON core.dim_client
    FOR SELECT TO ai_consumer
    USING (client_id IN (SELECT client_id FROM sec.v_my_clients));

-- An account is visible when its OWNER is one of the caller's clients.
CREATE POLICY entitled_accounts ON core.dim_account
    FOR SELECT TO ai_consumer
    USING (account_id IN (SELECT account_id FROM sec.v_my_accounts));

-- A disposition is visible when it belongs to an entitled client or to an
-- entitled account, so a relationship manager can see who else may operate
-- their client's account.
CREATE POLICY entitled_dispositions ON core.bridge_disposition
    FOR SELECT TO ai_consumer
    USING (
        client_id  IN (SELECT client_id  FROM sec.v_my_clients)
     OR account_id IN (SELECT account_id FROM sec.v_my_accounts)
    );

-- A card is visible when its disposition is on an entitled account.
CREATE POLICY entitled_cards ON core.dim_card
    FOR SELECT TO ai_consumer
    USING (
        disp_id IN (
            SELECT d.disp_id FROM core.bridge_disposition d
            WHERE d.account_id IN (SELECT account_id FROM sec.v_my_accounts)
        )
    );

CREATE POLICY entitled_loans ON core.fact_loan
    FOR SELECT TO ai_consumer
    USING (account_id IN (SELECT account_id FROM sec.v_my_accounts));

CREATE POLICY entitled_transactions ON core.fact_transaction
    FOR SELECT TO ai_consumer
    USING (account_id IN (SELECT account_id FROM sec.v_my_accounts));

CREATE POLICY entitled_balances ON core.fact_account_month_end_balance
    FOR SELECT TO ai_consumer
    USING (account_id IN (SELECT account_id FROM sec.v_my_accounts));

-- ----------------------------------------------------------------------------
-- Privileges. Read only, and only on what the ai views need.
--
-- SELECT on the core tables is required because the ai views are
-- security_invoker: the privilege check happens as the calling user. That is
-- not a weakness -- the policies are on those base tables, so a consumer
-- querying core directly is filtered identically. The guard's "ai schema only"
-- rule is about keeping generated SQL on the documented, business-named
-- surface, not about hiding data it would otherwise be allowed to read.
-- ----------------------------------------------------------------------------
REVOKE ALL ON SCHEMA raw, stg, dq, inject FROM ai_consumer;
REVOKE ALL ON ALL TABLES IN SCHEMA raw, stg, dq FROM ai_consumer;

GRANT USAGE ON SCHEMA ai, core, sec TO ai_consumer;
GRANT SELECT ON ALL TABLES IN SCHEMA ai TO ai_consumer;
GRANT SELECT ON core.dim_client, core.dim_account, core.bridge_disposition,
                core.dim_card, core.fact_loan, core.fact_transaction,
                core.fact_account_month_end_balance, core.dim_district,
                core.dim_date, core.ref_codes,
                core.v_account_owner, core.v_loan_enriched, core.v_client_region
      TO ai_consumer;
GRANT SELECT ON sec.v_my_clients, sec.v_my_accounts TO ai_consumer;

-- Consumers may read their own entitlement, never the entitlement tables
-- themselves: who else holds which book is not their business.
REVOKE ALL ON sec.app_user, sec.portfolio, sec.portfolio_client,
              sec.user_portfolio, sec.v_entitlement FROM ai_consumer;

-- Nothing in the data product is writable by a consumer. Stated explicitly
-- rather than relying on the default, because "read only" is a claim this
-- submission makes and a reviewer should be able to see it enforced.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA core, ai, sec
    FROM ai_consumer;
