-- ============================================================================
-- 51_sec_auth.sql -- authentication (who you are) and access grants (what you
--                    may reach), as two separate, auditable things
--
-- THE TWO QUESTIONS, KEPT APART
-- Most access bugs come from answering one question when you meant the other.
-- This file answers them separately and joins them in exactly one place:
--
--   AUTHENTICATION  Are you who you say you are?
--                   Factor 1: the database role password, checked by
--                   PostgreSQL itself. This is what makes session_user
--                   unforgeable -- no statement can change it.
--                   Factor 2: a time-based one-time code (RFC 6238), checked
--                   by sec.verify_second_factor(), which opens a session bound
--                   to this backend.
--
--   AUTHORISATION   Given that you are you, what may you reach, and why?
--                   One view, sec.v_access_grant, holds every answer. Each row
--                   says which principal, which subject (a client or an
--                   account), which permission (view or operate), where the
--                   right comes from (ownership, disposition, portfolio,
--                   delegation), who granted it and for how long.
--
-- The join is sec.v_my_clients / sec.v_my_accounts: a grant counts only while
-- the caller holds a fully verified session. That is what makes the second
-- factor a CONTROL and not a formality -- with the password alone, every
-- entitlement query returns nothing, because the grant resolution finds no
-- live session to attach the grants to.
--
-- WHY THE SESSION IS BOUND TO A BACKEND PID
-- The session token is a bearer secret, and a bearer secret that can be
-- replayed is a password with extra steps. Each session records
-- pg_backend_pid() at the moment the second factor is verified, and the
-- resolution requires it to still match. A token copied to another connection
-- is therefore useless: that connection has a different pid. Combined with
-- session_user (which the holder of a stolen token still cannot forge), a
-- session is usable only on the one authenticated connection that created it.
--
-- WHAT THIS IS NOT
-- This is a demonstration of the control, not a production IAM. The
-- weaknesses are real and are listed in docs/ACCESS_AND_AUTH.md section 6:
-- the TOTP secrets are stored recoverable (they must be, to verify), there is
-- no rate limit on code attempts beyond the lockout below, and there is no
-- audit of reads.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ----------------------------------------------------------------------------
-- TOTP (RFC 6238) in SQL, so the check happens where the secret lives.
--
-- Implemented here rather than in Python because the verification must not
-- require the secret to leave the database. A Python verifier would have to
-- SELECT the shared secret over the wire on every login, which turns the most
-- sensitive column in the schema into routine network traffic.
--
-- tests/test_auth.py checks these two functions against an independent
-- Python implementation and against the published RFC 6238 test vectors, so
-- "it looks like TOTP" is not the standard being met.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION sec.base32_decode(p_input text)
RETURNS bytea
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    v_alphabet text := 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
    v_clean    text := upper(replace(p_input, '=', ''));
    v_bits     text := '';
    v_index    int;
    v_out      bytea := '\x'::bytea;
BEGIN
    FOR i IN 1..length(v_clean) LOOP
        v_index := position(substr(v_clean, i, 1) IN v_alphabet) - 1;
        IF v_index < 0 THEN
            RAISE EXCEPTION 'not base32: %', substr(v_clean, i, 1);
        END IF;
        -- Five bits per symbol, most significant first.
        v_bits := v_bits || lpad((v_index::bit(5))::text, 5, '0');
    END LOOP;
    -- Whole bytes only; RFC 4648 pads with zero bits that carry no data.
    FOR i IN 1..(length(v_bits) / 8) LOOP
        v_out := v_out || set_byte('\x00'::bytea, 0,
                                   (('B' || substr(v_bits, (i - 1) * 8 + 1, 8))::bit(8))::int);
    END LOOP;
    RETURN v_out;
END;
$$;

COMMENT ON FUNCTION sec.base32_decode(text) IS
    'RFC 4648 base32 decode, for the shared secret an authenticator app '
    'stores. Raises on a non-base32 character rather than skipping it.';

CREATE OR REPLACE FUNCTION sec.totp_code(p_secret text, p_step bigint,
                                         p_digits int DEFAULT 6)
RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    v_counter bytea := '\x0000000000000000'::bytea;
    v_step    bigint := p_step;
    v_hash    bytea;
    v_offset  int;
    v_binary  bigint;
BEGIN
    -- The counter is the step as an 8-byte big-endian integer.
    FOR i IN REVERSE 7..0 LOOP
        v_counter := set_byte(v_counter, i, (v_step % 256)::int);
        v_step := v_step / 256;
    END LOOP;
    v_hash := hmac(v_counter, sec.base32_decode(p_secret), 'sha1');
    -- Dynamic truncation: the low nibble of the last byte picks the offset.
    v_offset := get_byte(v_hash, 19) & 15;
    v_binary := ((get_byte(v_hash, v_offset)     & 127)::bigint << 24)
              | ((get_byte(v_hash, v_offset + 1) & 255)::bigint << 16)
              | ((get_byte(v_hash, v_offset + 2) & 255)::bigint <<  8)
              |  (get_byte(v_hash, v_offset + 3) & 255)::bigint;
    RETURN lpad((v_binary % (10 ^ p_digits)::bigint)::text, p_digits, '0');
END;
$$;

COMMENT ON FUNCTION sec.totp_code(text, bigint, int) IS
    'The RFC 6238 code for a shared secret at a given 30-second step. '
    'Verified against the RFC test vectors in tests/test_auth.py.';

REVOKE ALL ON FUNCTION sec.totp_code(text, bigint, int) FROM PUBLIC;
REVOKE ALL ON FUNCTION sec.base32_decode(text) FROM PUBLIC;

DROP VIEW  IF EXISTS sec.v_who_can_reach_client CASCADE;
DROP VIEW  IF EXISTS sec.v_my_session           CASCADE;
DROP TABLE IF EXISTS sec.auth_session           CASCADE;
DROP TABLE IF EXISTS sec.auth_factor            CASCADE;
DROP VIEW  IF EXISTS sec.v_access_grant         CASCADE;
DROP TABLE IF EXISTS sec.access_delegation      CASCADE;
DROP TABLE IF EXISTS sec.access_grant           CASCADE;

-- ----------------------------------------------------------------------------
-- AUTHENTICATION
-- ----------------------------------------------------------------------------

CREATE TABLE sec.auth_factor (
    factor_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    db_role      name        NOT NULL REFERENCES sec.app_user (db_role)
                                 ON DELETE CASCADE ON UPDATE CASCADE,
    factor_type  text        NOT NULL DEFAULT 'totp',
    -- Base32 shared secret. It has to be recoverable to verify a code, which
    -- is why this column is the most sensitive in the database and why a real
    -- deployment encrypts it with a key held outside the database entirely.
    secret       text        NOT NULL,
    enrolled_at  timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz,
    -- Replay defence: a code is valid for 30 seconds, so the same code must
    -- not be accepted twice even inside its own window.
    last_step    bigint,
    failed_count int         NOT NULL DEFAULT 0,
    locked_until timestamptz,
    UNIQUE (db_role, factor_type),
    CONSTRAINT auth_factor_type_known CHECK (factor_type IN ('totp'))
);

COMMENT ON TABLE sec.auth_factor IS
    'Second-factor enrolment, one row per principal per factor type. '
    'last_step stops a code being replayed inside its own validity window; '
    'failed_count and locked_until stop a code being guessed.';

CREATE TABLE sec.auth_session (
    session_id    uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    db_role       name        NOT NULL,
    -- The connection this session belongs to. A session is valid only on the
    -- backend that created it, so a leaked session id cannot be replayed.
    backend_pid   int         NOT NULL,
    -- Recorded for the audit trail and as the obvious next tightening of the
    -- binding (pids are reused after wraparound; see A45). NULLABLE on
    -- purpose: reading it means reading another role's pg_stat_activity row,
    -- which needs pg_read_all_stats, and a privilege that happens to differ
    -- between a Docker start and a native one must not decide whether anyone
    -- can log in. The pid is the part the security check uses.
    backend_start timestamptz,
    factor1_at    timestamptz NOT NULL,
    factor2_at    timestamptz,
    expires_at    timestamptz NOT NULL,
    ended_at      timestamptz,
    end_reason    text,
    CONSTRAINT auth_session_end_reason_known CHECK (
        end_reason IS NULL OR end_reason IN ('logout', 'expired', 'superseded')
    )
);

CREATE INDEX ix_sec_auth_session_live
    ON sec.auth_session (db_role, backend_pid)
    WHERE ended_at IS NULL;

COMMENT ON TABLE sec.auth_session IS
    'One row per login attempt that reached the second-factor stage. A session '
    'counts as fully authenticated only while factor2_at is set, ended_at is '
    'null and expires_at is in the future -- AND the querying backend is the '
    'one named in backend_pid.';

-- The single definition of "this caller is fully authenticated right now".
-- Everything else refers to this, so there is one place to read and one place
-- to get wrong.
CREATE OR REPLACE FUNCTION sec.has_verified_session()
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = sec, pg_catalog AS $$
    SELECT EXISTS (
        SELECT 1 FROM sec.auth_session s
        WHERE s.db_role     = session_user
          AND s.backend_pid = pg_backend_pid()
          AND s.factor2_at IS NOT NULL
          AND s.ended_at   IS NULL
          AND s.expires_at  > now()
    );
$$;

COMMENT ON FUNCTION sec.has_verified_session() IS
    'True only when the CALLING backend holds a live, two-factor-verified '
    'session. SECURITY DEFINER so a consumer can be asked the question '
    'without being granted sight of the session table.';

REVOKE ALL ON FUNCTION sec.has_verified_session() FROM PUBLIC;

-- ----------------------------------------------------------------------------
-- Step two of the login, callable by the consumer, verifiable by nobody else.
--
-- SECURITY DEFINER because it must write to a table the caller cannot read or
-- write. The caller supplies only a six-digit code; the function decides for
-- which principal it is checked, from session_user, which the caller cannot
-- influence. There is therefore no parameter that lets a caller verify a
-- second factor on somebody else's behalf.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION sec.verify_second_factor(p_code text)
RETURNS TABLE (ok boolean, detail text, session_id uuid, expires_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = sec, public, pg_catalog AS $$
DECLARE
    v_factor      sec.auth_factor%ROWTYPE;
    v_step        bigint;
    v_window      int := current_setting('berka.totp_window', true)::int;
    v_ttl         int := coalesce(current_setting('berka.session_ttl', true)::int, 30);
    v_match       boolean := false;
    v_session     uuid;
    v_expires     timestamptz;
    v_backend_start timestamptz;
BEGIN
    v_window := coalesce(v_window, 1);

    SELECT * INTO v_factor FROM sec.auth_factor
     WHERE db_role = session_user AND factor_type = 'totp';

    IF NOT FOUND THEN
        RETURN QUERY SELECT false, 'no second factor enrolled for this principal',
                            NULL::uuid, NULL::timestamptz;
        RETURN;
    END IF;

    IF v_factor.locked_until IS NOT NULL AND v_factor.locked_until > now() THEN
        RETURN QUERY SELECT false,
                            'locked until ' || to_char(v_factor.locked_until, 'HH24:MI:SS'),
                            NULL::uuid, NULL::timestamptz;
        RETURN;
    END IF;

    -- Check the code against the current step and the adjacent ones, so a
    -- slightly slow clock does not lock a legitimate user out.
    FOR v_step IN
        SELECT s FROM generate_series(
            floor(extract(epoch FROM now()) / 30)::bigint - v_window,
            floor(extract(epoch FROM now()) / 30)::bigint + v_window) AS s
    LOOP
        IF sec.totp_code(v_factor.secret, v_step) = p_code THEN
            -- Refuse a code already spent, even though it is still in date.
            IF v_factor.last_step IS NOT NULL AND v_factor.last_step >= v_step THEN
                UPDATE sec.auth_factor SET failed_count = failed_count + 1
                 WHERE factor_id = v_factor.factor_id;
                RETURN QUERY SELECT false, 'code already used', NULL::uuid,
                                    NULL::timestamptz;
                RETURN;
            END IF;
            v_match := true;
            EXIT;
        END IF;
    END LOOP;

    IF NOT v_match THEN
        UPDATE sec.auth_factor
           SET failed_count = failed_count + 1,
               locked_until = CASE WHEN failed_count + 1 >= 5
                                   THEN now() + interval '15 minutes' END
         WHERE factor_id = v_factor.factor_id;
        RETURN QUERY SELECT false, 'incorrect code', NULL::uuid, NULL::timestamptz;
        RETURN;
    END IF;

    UPDATE sec.auth_factor
       SET last_used_at = now(), last_step = v_step, failed_count = 0,
           locked_until = NULL
     WHERE factor_id = v_factor.factor_id;

    -- One live session per backend: logging in again supersedes the old one.
    UPDATE sec.auth_session
       SET ended_at = now(), end_reason = 'superseded'
     WHERE db_role = session_user AND backend_pid = pg_backend_pid()
       AND ended_at IS NULL;

    -- Best effort: hidden unless this role may read other backends' stats.
    BEGIN
        SELECT backend_start INTO v_backend_start
          FROM pg_stat_activity WHERE pid = pg_backend_pid();
    EXCEPTION WHEN insufficient_privilege THEN
        v_backend_start := NULL;
    END;
    v_expires := now() + make_interval(mins => v_ttl);

    INSERT INTO sec.auth_session (db_role, backend_pid, backend_start,
                                  factor1_at, factor2_at, expires_at)
    VALUES (session_user, pg_backend_pid(), v_backend_start,
            coalesce(v_backend_start, now()), now(), v_expires)
    RETURNING sec.auth_session.session_id INTO v_session;

    RETURN QUERY SELECT true, 'second factor accepted', v_session, v_expires;
END;
$$;

COMMENT ON FUNCTION sec.verify_second_factor(text) IS
    'Step two of the login. Checks a TOTP code for session_user -- never for a '
    'principal named by the caller -- and on success opens a session bound to '
    'this backend. Until it succeeds, every entitlement resolves to nothing.';

CREATE OR REPLACE FUNCTION sec.end_session()
RETURNS boolean
LANGUAGE sql SECURITY DEFINER SET search_path = sec, pg_catalog AS $$
    WITH closed AS (
        UPDATE sec.auth_session SET ended_at = now(), end_reason = 'logout'
         WHERE db_role = session_user AND backend_pid = pg_backend_pid()
           AND ended_at IS NULL
        RETURNING 1
    )
    SELECT count(*) > 0 FROM closed;
$$;

COMMENT ON FUNCTION sec.end_session() IS
    'Log out: ends this backend''s session. The next entitlement query returns '
    'nothing until the second factor is presented again.';

-- What the caller may know about their own session. Deliberately not the
-- session_id: there is no reason for a client to hold a copy of a secret the
-- server can look up from the connection it is already using.
CREATE VIEW sec.v_my_session AS
SELECT s.db_role,
       s.factor2_at IS NOT NULL                        AS second_factor_verified,
       s.factor2_at,
       s.expires_at,
       greatest(s.expires_at - now(), interval '0')    AS time_remaining
FROM sec.auth_session s
WHERE s.db_role = session_user
  AND s.backend_pid = pg_backend_pid()
  AND s.ended_at IS NULL
  AND s.expires_at > now();

COMMENT ON VIEW sec.v_my_session IS
    'The calling connection''s own session, if it has one. Empty means "not '
    'through step two", which is a different thing from "entitled to nothing".';

-- ----------------------------------------------------------------------------
-- AUTHORISATION: one table for every answer to "who may reach this?"
-- ----------------------------------------------------------------------------

-- WHY THIS IS A VIEW AND NOT A TABLE.
--
-- The first cut of this model materialised every grant into a table, rebuilt
-- on each pipeline run. It was wrong, and the test suite caught it: granting
-- a portfolio inserted a row in sec.user_portfolio but no matching grant, so
-- the new entitlement did nothing until the next rebuild. That silently broke
-- the claim this design exists to make -- that onboarding is data, effective
-- on the very next statement -- and it introduced the exact failure mode a
-- single access model is supposed to remove: two descriptions of who may see
-- what, drifting apart between runs.
--
-- So three of the four sources are DERIVED LIVE from the records that already
-- define them, and only delegation -- a genuine administrative act with no
-- other representation -- is stored.
--
--   ownership   the principal IS a client, and that client owns the account
--   disposition the bank authorised them to operate an account they do not own
--   portfolio   staff, through a book granted to them
--   delegation  an explicit act, e.g. a power of attorney (stored below)
--
-- Nothing can drift, because there is nothing to keep in step.
-- ----------------------------------------------------------------------------
CREATE TABLE sec.access_delegation (
    delegation_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    db_role       name        NOT NULL REFERENCES sec.app_user (db_role)
                                  ON DELETE CASCADE ON UPDATE CASCADE,
    subject_kind  text        NOT NULL,
    subject_id    bigint      NOT NULL,
    permission    text        NOT NULL,
    granted_by    text        NOT NULL,
    reason        text        NOT NULL,
    valid_from    timestamptz NOT NULL DEFAULT now(),
    valid_to      timestamptz,
    CONSTRAINT access_delegation_subject_known
        CHECK (subject_kind IN ('client', 'account')),
    CONSTRAINT access_delegation_permission_known
        CHECK (permission IN ('view', 'operate')),
    CONSTRAINT access_delegation_window_sane
        CHECK (valid_to IS NULL OR valid_to > valid_from),
    UNIQUE (db_role, subject_kind, subject_id, permission)
);

COMMENT ON TABLE sec.access_delegation IS
    'Rights granted by an explicit administrative act rather than derived '
    'from the banking records: power of attorney, a court order, an '
    'authorised third party. Every row needs a reason and a grantor, because '
    'this is the only grant source a human chooses, and so the only one that '
    'can be wrong in a way the data cannot reveal.';

-- ----------------------------------------------------------------------------
-- THE ACCESS GRANT SET: one answer to "who may reach what, and why".
--
-- Three sources derived live, one stored. Same columns from every source, so
-- a question about access never has to ask which kind of right it is looking
-- at first.
-- ----------------------------------------------------------------------------
CREATE VIEW sec.v_access_grant AS
-- 1. OWNERSHIP of the client record: the principal IS this client.
SELECT u.db_role, 'client'::text AS subject_kind, u.subject_client_id AS subject_id,
       p.permission, 'ownership'::text AS grant_source,
       'derived:self'::text AS granted_by,
       'The principal is this client'::text AS reason,
       u.created_at AS valid_from, NULL::timestamptz AS valid_to
FROM sec.app_user u
CROSS JOIN (VALUES ('view'), ('operate')) AS p(permission)
WHERE u.user_type = 'client' AND u.subject_client_id IS NOT NULL
UNION ALL
-- 2. OWNERSHIP of an account: this client is the account holder of record.
SELECT u.db_role, 'account', d.account_id, p.permission, 'ownership',
       'derived:disposition', 'Account holder of record',
       u.created_at, NULL
FROM sec.app_user u
JOIN core.bridge_disposition d ON d.client_id = u.subject_client_id
CROSS JOIN (VALUES ('view'), ('operate')) AS p(permission)
WHERE u.user_type = 'client' AND d.is_owner
UNION ALL
-- 3. DISPOSITION: authorised to operate an account they do NOT own.
--    Note the containment, which is the whole reason this is granted per
--    account and not per client: it reaches that one account and nothing
--    else. Not the owner's client record, not their other accounts.
SELECT u.db_role, 'account', d.account_id, p.permission, 'disposition',
       'derived:disposition',
       'Authorised to operate this account without owning it',
       u.created_at, NULL
FROM sec.app_user u
JOIN core.bridge_disposition d ON d.client_id = u.subject_client_id
CROSS JOIN (VALUES ('view'), ('operate')) AS p(permission)
WHERE u.user_type = 'client' AND NOT d.is_owner
UNION ALL
-- 4. PORTFOLIO: staff see the clients in the books granted to them. VIEW
--    only -- being accountable for a client is not authority to move their
--    money, and flattening those two together is how a reporting tool
--    quietly becomes a payment instrument.
SELECT u.db_role, 'client', pc.client_id, 'view', 'portfolio',
       'derived:portfolio', 'Client is in portfolio ' || p.portfolio_code,
       greatest(pc.added_at, up.granted_at), NULL
FROM sec.app_user u
JOIN sec.user_portfolio  up ON up.app_user_id = u.app_user_id
JOIN sec.portfolio        p ON p.portfolio_id = up.portfolio_id
JOIN sec.portfolio_client pc ON pc.portfolio_id = p.portfolio_id
WHERE u.user_type <> 'client'
UNION ALL
-- 5. DELEGATION: the stored, human-decided grants.
SELECT d.db_role, d.subject_kind, d.subject_id, d.permission, 'delegation',
       d.granted_by, d.reason, d.valid_from, d.valid_to
FROM sec.access_delegation d;

COMMENT ON VIEW sec.v_access_grant IS
    'Every right any principal holds over any client or account, with the '
    'source it comes from, who granted it and the window it is valid for. '
    'Derived live from the banking records and the portfolios, so a change to '
    'either takes effect on the next statement with nothing to rebuild.';

-- A grant is live when it is inside its validity window. Stated once.
CREATE OR REPLACE FUNCTION sec.grant_is_live(p_from timestamptz, p_to timestamptz)
RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
    SELECT p_from <= now() AND (p_to IS NULL OR p_to > now());
$$;

-- ----------------------------------------------------------------------------
-- The one place authentication and authorisation meet.
--
-- Note the shape: the session check is an AND over the whole resolution, not
-- a filter inside one branch. If it were per-branch, a future branch added
-- without it would quietly skip the second factor.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW sec.v_my_clients AS
SELECT DISTINCT g.subject_id AS client_id
FROM sec.v_access_grant g
JOIN sec.app_user u ON u.db_role = g.db_role
WHERE g.db_role = session_user
  AND u.is_active
  AND g.subject_kind = 'client'
  AND sec.grant_is_live(g.valid_from, g.valid_to)
  AND sec.has_verified_session();

COMMENT ON VIEW sec.v_my_clients IS
    'The clients the CALLING principal may see, resolved from sec.v_access_grant '
    'and gated on a verified two-factor session. Self-filtering on '
    'session_user: there is no parameter to tamper with.';

CREATE OR REPLACE VIEW sec.v_my_accounts AS
-- Accounts granted directly: ownership, disposition or delegation.
SELECT DISTINCT g.subject_id AS account_id
FROM sec.v_access_grant g
JOIN sec.app_user u ON u.db_role = g.db_role
WHERE g.db_role = session_user
  AND u.is_active
  AND g.subject_kind = 'account'
  AND sec.grant_is_live(g.valid_from, g.valid_to)
  AND sec.has_verified_session()
UNION
-- Accounts reached through an entitled client: the accounts that client owns.
-- This is how a staff portfolio resolves to accounts, and it is why a
-- relationship manager's reach follows their clients rather than being
-- maintained account by account.
SELECT DISTINCT d.account_id
FROM core.bridge_disposition d
JOIN sec.v_my_clients c ON c.client_id = d.client_id
WHERE d.is_owner;

COMMENT ON VIEW sec.v_my_accounts IS
    'The accounts the calling principal may reach: those granted to them '
    'directly (they own it, they are authorised to operate it, or it was '
    'delegated) plus those owned by a client they are entitled to.';

-- ----------------------------------------------------------------------------
-- The administrative answer to the question this model exists for.
-- ----------------------------------------------------------------------------
CREATE VIEW sec.v_who_can_reach_client AS
SELECT
    c.client_id,
    c.client_ref,
    g.db_role,
    u.display_name,
    u.user_type,
    g.permission,
    g.grant_source,
    g.granted_by,
    g.reason,
    g.valid_from,
    g.valid_to,
    sec.grant_is_live(g.valid_from, g.valid_to) AS is_live
FROM core.dim_client c
JOIN sec.v_access_grant g
  ON (g.subject_kind = 'client' AND g.subject_id = c.client_id)
JOIN sec.app_user u ON u.db_role = g.db_role
UNION ALL
-- Reached indirectly: a principal granted one of this client's accounts.
SELECT
    c.client_id,
    c.client_ref,
    g.db_role,
    u.display_name,
    u.user_type,
    g.permission,
    g.grant_source,
    g.granted_by,
    g.reason,
    g.valid_from,
    g.valid_to,
    sec.grant_is_live(g.valid_from, g.valid_to)
FROM core.dim_client c
JOIN core.bridge_disposition d ON d.client_id = c.client_id
JOIN sec.v_access_grant g
  ON (g.subject_kind = 'account' AND g.subject_id = d.account_id)
JOIN sec.app_user u ON u.db_role = g.db_role AND u.db_role <> ''
WHERE g.db_role <> (SELECT db_role FROM sec.app_user
                     WHERE subject_client_id = c.client_id LIMIT 1);

COMMENT ON VIEW sec.v_who_can_reach_client IS
    'For the data owner: every principal who can reach a given client, how, '
    'and why. This is the view a privacy question is answered from -- "who '
    'has seen this customer" starts here and ends in the read audit, which '
    'this build does not yet have.';

-- ----------------------------------------------------------------------------
-- Privileges on the auth surface.
--
-- A consumer may: present their second factor, log out, ask whether they are
-- verified, and see their own session. A consumer may NOT: read any secret,
-- read anyone's session, read the grant table, or generate a code.
--
-- sec.has_verified_session() is granted because the row level security
-- policies call it while evaluating as the querying user. It discloses one
-- boolean about the caller's own connection, which the caller already knows.
-- ----------------------------------------------------------------------------
GRANT EXECUTE ON FUNCTION sec.verify_second_factor(text)  TO ai_consumer;
GRANT EXECUTE ON FUNCTION sec.end_session()               TO ai_consumer;
GRANT EXECUTE ON FUNCTION sec.has_verified_session()      TO ai_consumer;
GRANT EXECUTE ON FUNCTION sec.grant_is_live(timestamptz, timestamptz) TO ai_consumer;
GRANT SELECT  ON sec.v_my_session                         TO ai_consumer;

-- The secrets, the sessions of other principals, and the grant table itself
-- are never readable by a consumer. Stated as explicit revokes because "we
-- did not grant it" is a weaker claim than "we took it away".
REVOKE ALL ON sec.auth_factor, sec.auth_session, sec.access_delegation,
              sec.v_access_grant,
              sec.v_who_can_reach_client FROM ai_consumer;
REVOKE ALL ON FUNCTION sec.totp_code(text, bigint, int)   FROM ai_consumer;
REVOKE ALL ON FUNCTION sec.base32_decode(text)            FROM ai_consumer;

-- The resolution views are read by the policies and may be read by the
-- consumer to see their own entitlement.
GRANT SELECT ON sec.v_my_clients, sec.v_my_accounts TO ai_consumer;
