-- ============================================================================
-- 10_stg.sql -- typed staging layer
--
-- Contract of this layer:
--   * every column gets its real type;
--   * every conversion is reversible: where a cast changed or dropped a value,
--     the original raw text is kept in a <column>_raw audit column and the
--     change is listed in _conversion_notes;
--   * every row keeps _source_file and _source_row, so any staged value can be
--     traced back to a line in a file whose SHA-256 is in raw.load_audit;
--   * nothing is filtered out here. Rejecting rows is the data quality layer's
--     job, and it needs to see the bad rows to report on them.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Conversion helpers. IMMUTABLE and STRICT where possible so the planner can
-- inline them; all of them return NULL rather than raising, because a staging
-- cast that throws would hide the very defect we are trying to measure.
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION stg.norm_text(p_value text)
RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    -- Trim, then map every known "missing" placeholder to a real NULL.
    SELECT CASE
        WHEN p_value IS NULL THEN NULL
        WHEN btrim(p_value) IN ('', '?', 'NA', 'N/A', 'NULL', '-', 'unknown') THEN NULL
        ELSE btrim(p_value)
    END;
$$;

COMMENT ON FUNCTION stg.norm_text(text) IS
    'Trim and normalise placeholder values to NULL. Placeholder list mirrors '
    'src.config.NULL_PLACEHOLDERS.';

CREATE OR REPLACE FUNCTION stg.parse_yymmdd(p_value text)
RETURNS date
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    v_clean text := btrim(coalesce(p_value, ''));
BEGIN
    -- Source dates are YYMMDD in the 1990s; a trailing clock time appears in
    -- card.issued ("931107 00:00:00") and is ignored.
    v_clean := split_part(v_clean, ' ', 1);
    IF v_clean !~ '^[0-9]{6}$' THEN
        RETURN NULL;
    END IF;
    RETURN to_date('19' || v_clean, 'YYYYMMDD');
EXCEPTION
    WHEN others THEN
        -- Syntactically six digits but not a real calendar date, e.g. 930231.
        RETURN NULL;
END;
$$;

COMMENT ON FUNCTION stg.parse_yymmdd(text) IS
    'Parse a YYMMDD source date into the 20th century. Returns NULL for '
    'anything that is not a real calendar date, so the validity rules can count it.';

CREATE OR REPLACE FUNCTION stg.parse_numeric(p_value text)
RETURNS numeric
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    RETURN stg.norm_text(p_value)::numeric;
EXCEPTION
    WHEN others THEN
        RETURN NULL;
END;
$$;

COMMENT ON FUNCTION stg.parse_numeric(text) IS
    'Cast to numeric, returning NULL instead of raising on malformed input.';

CREATE OR REPLACE FUNCTION stg.parse_int(p_value text)
RETURNS bigint
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    RETURN stg.norm_text(p_value)::bigint;
EXCEPTION
    WHEN others THEN
        RETURN NULL;
END;
$$;

COMMENT ON FUNCTION stg.parse_int(text) IS
    'Cast to bigint, returning NULL instead of raising on malformed input.';

-- birth_number is YYMMDD with the month increased by 50 for women.
CREATE OR REPLACE FUNCTION stg.birth_gender(p_birth_number text)
RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN btrim(coalesce(p_birth_number, '')) !~ '^[0-9]{6}$' THEN NULL
        WHEN substr(btrim(p_birth_number), 3, 2)::int BETWEEN 51 AND 62 THEN 'female'
        WHEN substr(btrim(p_birth_number), 3, 2)::int BETWEEN 1 AND 12 THEN 'male'
        ELSE NULL
    END;
$$;

COMMENT ON FUNCTION stg.birth_gender(text) IS
    'Decode gender from birth_number: women carry month + 50. NULL when the '
    'birth number is not decodable.';

CREATE OR REPLACE FUNCTION stg.birth_date(p_birth_number text)
RETURNS date
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    v_clean text := btrim(coalesce(p_birth_number, ''));
    v_year  int;
    v_month int;
    v_day   int;
BEGIN
    IF v_clean !~ '^[0-9]{6}$' THEN
        RETURN NULL;
    END IF;
    v_year  := substr(v_clean, 1, 2)::int;
    v_month := substr(v_clean, 3, 2)::int;
    v_day   := substr(v_clean, 5, 2)::int;
    IF v_month > 50 THEN
        v_month := v_month - 50;   -- female encoding
    END IF;
    IF v_month NOT BETWEEN 1 AND 12 THEN
        RETURN NULL;
    END IF;
    -- Clients of a 1990s bank: a two digit year is always 19xx here.
    RETURN make_date(1900 + v_year, v_month, v_day);
EXCEPTION
    WHEN others THEN
        -- e.g. 31 February: decodable digits, impossible calendar date.
        RETURN NULL;
END;
$$;

COMMENT ON FUNCTION stg.birth_date(text) IS
    'Decode birth_date from birth_number (YYMMDD, month + 50 for women). '
    'NULL when the digits do not form a real date.';

CREATE OR REPLACE FUNCTION stg.birth_number_valid(p_birth_number text)
RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
    -- Valid means: six digits, month in 1-12 or 51-62, and a day that exists
    -- in that month. The date decoder already enforces the last part.
    SELECT btrim(coalesce(p_birth_number, '')) ~ '^[0-9]{6}$'
       AND (
            substr(btrim(p_birth_number), 3, 2)::int BETWEEN 1 AND 12
         OR substr(btrim(p_birth_number), 3, 2)::int BETWEEN 51 AND 62
           )
       AND stg.birth_date(p_birth_number) IS NOT NULL;
$$;

COMMENT ON FUNCTION stg.birth_number_valid(text) IS
    'True when birth_number is six digits, has a month in 1-12 or 51-62 and '
    'decodes to a real calendar date.';

-- ----------------------------------------------------------------------------
-- stg.district
-- Grain: one row per administrative district. A12 (unemployment 1995) and
-- A15 (crimes 1995) carry '?' in the source for district 69 (Jesenik); the raw
-- text is retained in the _raw audit columns.
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS stg.district CASCADE;
CREATE TABLE stg.district AS
SELECT
    stg.parse_int(r."A1")                          AS district_id,
    stg.norm_text(r."A2")                          AS district_name,
    stg.norm_text(r."A3")                          AS region,
    stg.parse_int(r."A4")                          AS inhabitants,
    stg.parse_int(r."A5")                          AS municipalities_lt_499,
    stg.parse_int(r."A6")                          AS municipalities_500_1999,
    stg.parse_int(r."A7")                          AS municipalities_2000_9999,
    stg.parse_int(r."A8")                          AS municipalities_gt_10000,
    stg.parse_int(r."A9")                          AS cities,
    stg.parse_numeric(r."A10")                     AS urban_ratio_pct,
    stg.parse_numeric(r."A11")                     AS average_salary,
    stg.parse_numeric(r."A12")                     AS unemployment_rate_1995,
    stg.parse_numeric(r."A13")                     AS unemployment_rate_1996,
    stg.parse_numeric(r."A14")                     AS entrepreneurs_per_1000,
    stg.parse_int(r."A15")                         AS crimes_1995,
    stg.parse_int(r."A16")                         AS crimes_1996,
    CASE WHEN stg.parse_numeric(r."A12") IS NULL AND r."A12" IS NOT NULL
         THEN r."A12" END                          AS unemployment_rate_1995_raw,
    CASE WHEN stg.parse_int(r."A15") IS NULL AND r."A15" IS NOT NULL
         THEN r."A15" END                          AS crimes_1995_raw,
    array_remove(ARRAY[
        CASE WHEN stg.parse_numeric(r."A12") IS NULL AND r."A12" IS NOT NULL
             THEN 'unemployment_rate_1995: placeholder ' || r."A12" || ' -> NULL' END,
        CASE WHEN stg.parse_int(r."A15") IS NULL AND r."A15" IS NOT NULL
             THEN 'crimes_1995: placeholder ' || r."A15" || ' -> NULL' END
    ], NULL)                                       AS _conversion_notes,
    r._source_file,
    r._source_row
FROM raw.district r;

COMMENT ON TABLE stg.district IS
    'One row per district. Source columns A1..A16 renamed to business names '
    '(mapping lives in src.config.DISTRICT_COLUMN_MAP).';

-- ----------------------------------------------------------------------------
-- stg.client
-- Grain: one row per client. birth_number is decoded into birth_date + gender.
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS stg.client CASCADE;
CREATE TABLE stg.client AS
SELECT
    stg.parse_int(r.client_id)                     AS client_id,
    stg.norm_text(r.birth_number)                  AS birth_number,
    stg.birth_date(r.birth_number)                 AS birth_date,
    stg.birth_gender(r.birth_number)               AS gender,
    stg.birth_number_valid(r.birth_number)         AS birth_number_valid,
    stg.parse_int(r.district_id)                   AS district_id,
    CASE WHEN stg.birth_date(r.birth_number) IS NULL AND r.birth_number IS NOT NULL
         THEN r.birth_number END                   AS birth_number_raw,
    array_remove(ARRAY[
        CASE WHEN stg.birth_date(r.birth_number) IS NULL AND r.birth_number IS NOT NULL
             THEN 'birth_number: undecodable ' || r.birth_number END
    ], NULL)                                       AS _conversion_notes,
    r._source_file,
    r._source_row
FROM raw.client r;

COMMENT ON TABLE stg.client IS
    'One row per client, with birth_date and gender decoded from birth_number.';

-- ----------------------------------------------------------------------------
-- stg.account
-- Grain: one row per account. frequency is the statement frequency.
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS stg.account CASCADE;
CREATE TABLE stg.account AS
SELECT
    stg.parse_int(r.account_id)                    AS account_id,
    stg.parse_int(r.district_id)                   AS district_id,
    stg.norm_text(r.frequency)                     AS frequency_code,
    CASE stg.norm_text(r.frequency)
        WHEN 'POPLATEK MESICNE'    THEN 'monthly'
        WHEN 'POPLATEK TYDNE'      THEN 'weekly'
        WHEN 'POPLATEK PO OBRATU'  THEN 'after transaction'
    END                                            AS frequency_label,
    stg.parse_yymmdd(r."date")                     AS open_date,
    CASE WHEN stg.parse_yymmdd(r."date") IS NULL AND r."date" IS NOT NULL
         THEN r."date" END                         AS open_date_raw,
    array_remove(ARRAY[
        CASE WHEN stg.parse_yymmdd(r."date") IS NULL AND r."date" IS NOT NULL
             THEN 'open_date: unparsable ' || r."date" END,
        CASE WHEN stg.norm_text(r.frequency) IS NOT NULL
              AND stg.norm_text(r.frequency) NOT IN
                  ('POPLATEK MESICNE', 'POPLATEK TYDNE', 'POPLATEK PO OBRATU')
             THEN 'frequency_code: unknown value ' || r.frequency END
    ], NULL)                                       AS _conversion_notes,
    r._source_file,
    r._source_row
FROM raw.account r;

COMMENT ON TABLE stg.account IS
    'One row per account, with the statement frequency decoded to an English label.';

-- ----------------------------------------------------------------------------
-- stg.disp -- the client-to-account bridge (OWNER or DISPONENT)
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS stg.disp CASCADE;
CREATE TABLE stg.disp AS
SELECT
    stg.parse_int(r.disp_id)                       AS disp_id,
    stg.parse_int(r.client_id)                     AS client_id,
    stg.parse_int(r.account_id)                    AS account_id,
    upper(stg.norm_text(r."type"))                 AS disp_type_code,
    CASE upper(stg.norm_text(r."type"))
        WHEN 'OWNER'     THEN 'owner'
        WHEN 'DISPONENT' THEN 'disponent'
    END                                            AS disp_type_label,
    array_remove(ARRAY[
        CASE WHEN upper(stg.norm_text(r."type")) IS NOT NULL
              AND upper(stg.norm_text(r."type")) NOT IN ('OWNER', 'DISPONENT')
             THEN 'disp_type_code: unknown value ' || r."type" END
    ], NULL)                                       AS _conversion_notes,
    r._source_file,
    r._source_row
FROM raw.disp r;

COMMENT ON TABLE stg.disp IS
    'One row per disposition: which client may operate which account, and in '
    'which capacity. Exactly one OWNER per account is expected.';

-- ----------------------------------------------------------------------------
-- stg.card -- payment cards, attached to a disposition rather than a client
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS stg.card CASCADE;
CREATE TABLE stg.card AS
SELECT
    stg.parse_int(r.card_id)                       AS card_id,
    stg.parse_int(r.disp_id)                       AS disp_id,
    lower(stg.norm_text(r."type"))                 AS card_type,
    stg.parse_yymmdd(r.issued)                     AS issued_date,
    CASE WHEN stg.parse_yymmdd(r.issued) IS NULL AND r.issued IS NOT NULL
         THEN r.issued END                         AS issued_raw,
    array_remove(ARRAY[
        CASE WHEN stg.parse_yymmdd(r.issued) IS NULL AND r.issued IS NOT NULL
             THEN 'issued_date: unparsable ' || r.issued END,
        CASE WHEN lower(stg.norm_text(r."type")) IS NOT NULL
              AND lower(stg.norm_text(r."type")) NOT IN ('junior', 'classic', 'gold')
             THEN 'card_type: unknown value ' || r."type" END
    ], NULL)                                       AS _conversion_notes,
    r._source_file,
    r._source_row
FROM raw.card r;

COMMENT ON TABLE stg.card IS
    'One row per issued card. A card belongs to a disposition, so the holder '
    'is the client of that disposition, who is not always the account owner.';

-- ----------------------------------------------------------------------------
-- stg.loan -- one loan per account in this dataset
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS stg.loan CASCADE;
CREATE TABLE stg.loan AS
SELECT
    stg.parse_int(r.loan_id)                       AS loan_id,
    stg.parse_int(r.account_id)                    AS account_id,
    stg.parse_yymmdd(r."date")                     AS loan_date,
    stg.parse_numeric(r.amount)                    AS amount,
    stg.parse_int(r.duration)                      AS duration_months,
    stg.parse_numeric(r.payments)                  AS monthly_payment,
    upper(stg.norm_text(r.status))                 AS status_code,
    CASE upper(stg.norm_text(r.status))
        WHEN 'A' THEN 'finished, paid in full'
        WHEN 'B' THEN 'finished, unpaid (default)'
        WHEN 'C' THEN 'running, no problem'
        WHEN 'D' THEN 'running, client in debt'
    END                                            AS status_label,
    (upper(stg.norm_text(r.status)) IN ('B', 'D'))  AS is_problematic,
    CASE WHEN stg.parse_yymmdd(r."date") IS NULL AND r."date" IS NOT NULL
         THEN r."date" END                         AS loan_date_raw,
    CASE WHEN stg.parse_numeric(r.amount) IS NULL AND r.amount IS NOT NULL
         THEN r.amount END                         AS amount_raw,
    array_remove(ARRAY[
        CASE WHEN stg.parse_yymmdd(r."date") IS NULL AND r."date" IS NOT NULL
             THEN 'loan_date: unparsable ' || r."date" END,
        CASE WHEN stg.parse_numeric(r.amount) IS NULL AND r.amount IS NOT NULL
             THEN 'amount: unparsable ' || r.amount END,
        CASE WHEN stg.parse_numeric(r.payments) IS NULL AND r.payments IS NOT NULL
             THEN 'monthly_payment: unparsable ' || r.payments END,
        CASE WHEN upper(stg.norm_text(r.status)) IS NOT NULL
              AND upper(stg.norm_text(r.status)) NOT IN ('A', 'B', 'C', 'D')
             THEN 'status_code: unknown value ' || r.status END
    ], NULL)                                       AS _conversion_notes,
    r._source_file,
    r._source_row
FROM raw.loan r;

COMMENT ON TABLE stg.loan IS
    'One row per loan. is_problematic = status B (finished unpaid) or D '
    '(running, in debt), which is the definition used by Q3 and Q10.';

-- ----------------------------------------------------------------------------
-- stg.order -- standing orders. "order" is reserved, hence the quoting.
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS stg."order" CASCADE;
CREATE TABLE stg."order" AS
SELECT
    stg.parse_int(r.order_id)                      AS order_id,
    stg.parse_int(r.account_id)                    AS account_id,
    stg.norm_text(r.bank_to)                       AS bank_to,
    stg.norm_text(r.account_to)                    AS account_to,
    stg.parse_numeric(r.amount)                    AS amount,
    stg.norm_text(r.k_symbol)                      AS k_symbol_code,
    CASE stg.norm_text(r.k_symbol)
        WHEN 'POJISTNE'    THEN 'insurance payment'
        WHEN 'SLUZBY'      THEN 'payment for statement'
        WHEN 'UROK'        THEN 'interest credited'
        WHEN 'SANKC. UROK' THEN 'sanction interest for negative balance'
        WHEN 'SIPO'        THEN 'household payment'
        WHEN 'DUCHOD'      THEN 'old age pension'
        WHEN 'UVER'        THEN 'loan payment'
        WHEN 'LEASING'     THEN 'leasing payment'
    END                                            AS k_symbol_label,
    -- The source encodes "no category" three ways in this column: a quoted
    -- empty string, an unquoted empty field, and a single space.
    CASE WHEN stg.norm_text(r.k_symbol) IS NULL AND r.k_symbol IS NOT NULL
         THEN r.k_symbol END                       AS k_symbol_raw,
    array_remove(ARRAY[
        CASE WHEN stg.norm_text(r.k_symbol) IS NULL AND r.k_symbol IS NOT NULL
             THEN 'k_symbol_code: placeholder [' || r.k_symbol || '] -> NULL' END
    ], NULL)                                       AS _conversion_notes,
    r._source_file,
    r._source_row
FROM raw."order" r;

COMMENT ON TABLE stg."order" IS
    'One row per standing order. Not used by the 10 questions, but loaded, '
    'profiled and rule-checked like every other table.';

-- ----------------------------------------------------------------------------
-- stg.trans -- the fact table, 1.06 m rows
-- signed_amount makes the balance continuity check and every "incoming
-- amount" metric unambiguous: credits positive, debits negative.
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS stg.trans CASCADE;
CREATE TABLE stg.trans AS
SELECT
    stg.parse_int(r.trans_id)                      AS trans_id,
    stg.parse_int(r.account_id)                    AS account_id,
    stg.parse_yymmdd(r."date")                     AS trans_date,
    upper(stg.norm_text(r."type"))                 AS trans_type_code,
    CASE upper(stg.norm_text(r."type"))
        WHEN 'PRIJEM' THEN 'credit'
        WHEN 'VYDAJ'  THEN 'debit'
        WHEN 'VYBER'  THEN 'withdrawal (legacy debit)'
    END                                            AS trans_type_label,
    CASE
        WHEN upper(stg.norm_text(r."type")) = 'PRIJEM' THEN 'credit'
        WHEN upper(stg.norm_text(r."type")) IN ('VYDAJ', 'VYBER') THEN 'debit'
    END                                            AS direction,
    stg.norm_text(r.operation)                     AS operation_code,
    CASE stg.norm_text(r.operation)
        WHEN 'VKLAD'         THEN 'cash deposit'
        WHEN 'VYBER'         THEN 'cash withdrawal'
        WHEN 'VYBER KARTOU'  THEN 'credit card withdrawal'
        WHEN 'PREVOD Z UCTU' THEN 'collection from another bank'
        WHEN 'PREVOD NA UCET' THEN 'remittance to another bank'
    END                                            AS operation_label,
    stg.parse_numeric(r.amount)                    AS amount,
    CASE
        WHEN upper(stg.norm_text(r."type")) = 'PRIJEM'
            THEN stg.parse_numeric(r.amount)
        WHEN upper(stg.norm_text(r."type")) IN ('VYDAJ', 'VYBER')
            THEN -stg.parse_numeric(r.amount)
    END                                            AS signed_amount,
    stg.parse_numeric(r.balance)                   AS balance_after,
    stg.norm_text(r.k_symbol)                      AS k_symbol_code,
    CASE stg.norm_text(r.k_symbol)
        WHEN 'POJISTNE'    THEN 'insurance payment'
        WHEN 'SLUZBY'      THEN 'payment for statement'
        WHEN 'UROK'        THEN 'interest credited'
        WHEN 'SANKC. UROK' THEN 'sanction interest for negative balance'
        WHEN 'SIPO'        THEN 'household payment'
        WHEN 'DUCHOD'      THEN 'old age pension'
        WHEN 'UVER'        THEN 'loan payment'
        WHEN 'LEASING'     THEN 'leasing payment'
    END                                            AS k_symbol_label,
    stg.norm_text(r.bank)                          AS partner_bank,
    stg.norm_text(r.account)                       AS partner_account,
    CASE WHEN stg.parse_yymmdd(r."date") IS NULL AND r."date" IS NOT NULL
         THEN r."date" END                         AS trans_date_raw,
    CASE WHEN stg.parse_numeric(r.amount) IS NULL AND r.amount IS NOT NULL
         THEN r.amount END                         AS amount_raw,
    CASE WHEN stg.parse_numeric(r.balance) IS NULL AND r.balance IS NOT NULL
         THEN r.balance END                        AS balance_raw,
    array_remove(ARRAY[
        CASE WHEN stg.parse_yymmdd(r."date") IS NULL AND r."date" IS NOT NULL
             THEN 'trans_date: unparsable ' || r."date" END,
        CASE WHEN stg.parse_numeric(r.amount) IS NULL AND r.amount IS NOT NULL
             THEN 'amount: unparsable ' || r.amount END,
        CASE WHEN stg.parse_numeric(r.balance) IS NULL AND r.balance IS NOT NULL
             THEN 'balance_after: unparsable ' || r.balance END,
        CASE WHEN upper(stg.norm_text(r."type")) IS NOT NULL
              AND upper(stg.norm_text(r."type")) NOT IN ('PRIJEM', 'VYDAJ', 'VYBER')
             THEN 'trans_type_code: unknown value ' || r."type" END
    ], NULL)                                       AS _conversion_notes,
    r._source_file,
    r._source_row
FROM raw.trans r;

COMMENT ON TABLE stg.trans IS
    'One row per transaction (1.06 m). signed_amount is positive for credits '
    '(PRIJEM) and negative for debits (VYDAJ, VYBER); balance_after is the '
    'running account balance the source reports after this transaction.';

-- ----------------------------------------------------------------------------
-- Indexes the data quality rules and the core build rely on. Created here so
-- the expensive cross-table checks (balance continuity over 1.06 m rows)
-- do not table-scan.
-- ----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS ix_stg_trans_account_date
    ON stg.trans (account_id, trans_date, trans_id);
CREATE INDEX IF NOT EXISTS ix_stg_trans_id          ON stg.trans (trans_id);
CREATE INDEX IF NOT EXISTS ix_stg_disp_account      ON stg.disp (account_id);
CREATE INDEX IF NOT EXISTS ix_stg_disp_client       ON stg.disp (client_id);
CREATE INDEX IF NOT EXISTS ix_stg_loan_account      ON stg.loan (account_id);
CREATE INDEX IF NOT EXISTS ix_stg_card_disp         ON stg.card (disp_id);
CREATE INDEX IF NOT EXISTS ix_stg_account_district  ON stg.account (district_id);
CREATE INDEX IF NOT EXISTS ix_stg_client_district   ON stg.client (district_id);
CREATE INDEX IF NOT EXISTS ix_stg_order_account     ON stg."order" (account_id);

ANALYZE stg.trans;
ANALYZE stg.account;
ANALYZE stg.client;
ANALYZE stg.disp;
ANALYZE stg.card;
ANALYZE stg.loan;
ANALYZE stg."order";
ANALYZE stg.district;
