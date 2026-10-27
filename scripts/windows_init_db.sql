-- One-time database setup for native Windows (no Docker, no WSL).
--
-- The native-Linux branch of scripts/db_up.sh does the same thing with
-- `su postgres`, which Windows does not have. Run this as the PostgreSQL
-- superuser; scripts/windows.ps1 init-db does that for you:
--
--   psql -U postgres -h localhost -d postgres -v ON_ERROR_STOP=1 ^
--        -v owner=berka_owner -v owner_pw=berka_owner_pw -v dbname=berka ^
--        -f scripts/windows_init_db.sql
--
-- Idempotent: an existing role keeps its password, an existing database is
-- left alone. UTF8 is forced because a Windows cluster may default to WIN1252.

SELECT format('CREATE ROLE %I LOGIN CREATEROLE PASSWORD %L', :'owner', :'owner_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'owner') \gexec

-- build_security creates the consumer roles, so the owner needs CREATEROLE.
SELECT format('ALTER ROLE %I LOGIN CREATEROLE', :'owner') \gexec

SELECT format('CREATE DATABASE %I OWNER %I ENCODING ''UTF8'' TEMPLATE template0',
              :'dbname', :'owner')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'dbname') \gexec

-- Lets sec.verify_second_factor() read the caller's backend start time
-- (same grant as scripts/db_up.sh).
SELECT format('GRANT pg_read_all_stats TO %I', :'owner') \gexec

\connect :dbname
SELECT format('GRANT ALL ON SCHEMA public TO %I', :'owner') \gexec
