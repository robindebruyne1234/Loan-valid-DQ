-- ============================================================================
-- 00_schemas.sql -- schemas and the audit / control tables
--
-- Layer contract:
--   raw    verbatim text landing zone, one table per source file. Nothing is
--          cast, nothing is cleaned, nothing is rejected. Reloadable.
--   stg    typed and lineage-carrying. Casts happen here and every conversion
--          that changed a value keeps the original raw text alongside it.
--   dq     rule results, quarantine and reconciliation. The control plane.
--   core   the cleaned, modelled data product (star schema + curated views).
--   ai     the only surface an AI consumer may touch. Views over core, created
--          WITH (security_invoker = true) so core's row level security applies
--          as the querying user.
--   sec    entitlements: who may see which clients. Data, not code.
--   inject a deliberately corrupted copy of stg, used only to prove that the
--          data quality rules actually fire. Never feeds core.
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS stg;
CREATE SCHEMA IF NOT EXISTS dq;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS ai;
CREATE SCHEMA IF NOT EXISTS sec;
CREATE SCHEMA IF NOT EXISTS inject;

COMMENT ON SCHEMA raw IS 'Verbatim text landing zone, one table per source file.';
COMMENT ON SCHEMA stg IS 'Typed staging with lineage and conversion audit columns.';
COMMENT ON SCHEMA dq IS 'Data quality control plane: rule results and quarantine.';
COMMENT ON SCHEMA core IS 'Cleaned, modelled data product (star schema).';
COMMENT ON SCHEMA ai IS 'The only surface AI consumers may query. Entitlement filtered.';
COMMENT ON SCHEMA sec IS 'Entitlement data: users, portfolios and client membership.';
COMMENT ON SCHEMA inject IS 'Deliberately corrupted copy of stg, for rule self-tests only.';

-- ----------------------------------------------------------------------------
-- raw.load_audit -- provenance of every ingest
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.load_audit (
    load_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id          uuid        NOT NULL,
    source_name     text        NOT NULL,
    source_file     text        NOT NULL,
    file_bytes      bigint      NOT NULL,
    file_sha256     text        NOT NULL,
    rows_loaded     bigint      NOT NULL,
    rows_expected   bigint,
    counts_match    boolean,
    copy_options    text        NOT NULL,
    loaded_at       timestamptz NOT NULL DEFAULT now(),
    duration_sec    numeric(10, 3)
);

COMMENT ON TABLE raw.load_audit IS
    'One row per file per ingest run. file_sha256 is taken on the decompressed '
    'byte stream, so the hash identifies the data and not the compression.';

-- ----------------------------------------------------------------------------
-- dq control tables
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dq.run (
    run_id        uuid        PRIMARY KEY,
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    dataset       text        NOT NULL,
    git_commit    text,
    rules_total   integer,
    rules_failed  integer,
    command       text
);

COMMENT ON TABLE dq.run IS 'One row per data quality run, for provenance of every reported number.';

CREATE TABLE IF NOT EXISTS dq.results (
    result_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id            uuid        NOT NULL REFERENCES dq.run (run_id) ON DELETE CASCADE,
    rule_id           text        NOT NULL,
    dimension         text        NOT NULL,
    target_schema     text        NOT NULL,
    target_table      text        NOT NULL,
    severity          text        NOT NULL,
    violation_count   bigint      NOT NULL,
    total_count       bigint,
    violation_rate    numeric(12, 8),
    sample_keys       jsonb       NOT NULL DEFAULT '[]'::jsonb,
    executed_at       timestamptz NOT NULL DEFAULT now(),
    duration_sec      numeric(10, 3),
    error_message     text
);

CREATE INDEX IF NOT EXISTS ix_dq_results_run ON dq.results (run_id, rule_id);

COMMENT ON TABLE dq.results IS
    'Per-rule outcome of one run: how many rows violated, out of how many, '
    'with up to ten sample keys so a reviewer can go and look at them.';

CREATE TABLE IF NOT EXISTS dq.quarantine (
    quarantine_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id          uuid        NOT NULL,
    rule_id         text        NOT NULL,
    severity        text        NOT NULL,
    target_schema   text        NOT NULL,
    target_table    text        NOT NULL,
    business_key    text        NOT NULL,
    reason          text        NOT NULL,
    row_snapshot    jsonb,
    quarantined_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_dq_quarantine_target
    ON dq.quarantine (target_table, business_key);

COMMENT ON TABLE dq.quarantine IS
    'Rows excluded from core by a block-severity rule, with the rule that '
    'excluded them, the reason and a JSON snapshot of the row as it arrived.';

CREATE TABLE IF NOT EXISTS dq.reconciliation (
    recon_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id        uuid        NOT NULL,
    metric        text        NOT NULL,
    entity        text        NOT NULL,
    raw_value     numeric,
    stg_value     numeric,
    quarantined   numeric,
    core_value    numeric,
    delta         numeric,
    is_balanced   boolean,
    note          text,
    checked_at    timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE dq.reconciliation IS
    'raw -> stg -> core row count and amount sum reconciliation. is_balanced '
    'is true when core = stg - quarantined, which is the only acceptable gap.';
