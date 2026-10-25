#!/usr/bin/env bash
# Bring up PostgreSQL 16 for this project.
#
# Preference order:
#   1. docker compose (portable, matches docker-compose.yml)
#   2. a natively installed PostgreSQL 16 cluster (pg_ctlcluster)
# Either way the pipeline sees the same server on localhost:5432 with the
# credentials from src/config.py, so `make all` does not care which path ran.
#
# Deliberately NOT required: the psql client. Someone running this with Docker
# Desktop has a database but usually no local postgres-client, and an earlier
# version of this script failed for them after an 80-second timeout with a
# misleading message. The readiness probe therefore uses psycopg, which is
# already a project dependency, and falls back to psql only if it is there.
set -euo pipefail

cd "$(dirname "$0")/.."

DB_NAME="${PGDATABASE:-berka}"
DB_USER="${PGUSER:-berka_owner}"
DB_PASS="${PGPASSWORD:-berka_owner_pw}"
PY="${PY:-python3}"

log() { echo "db_up | $*"; }

# One connection attempt. Returns 0 when the server answers.
probe() {
  if PGPASSWORD="$DB_PASS" "$PY" - "$DB_NAME" "$DB_USER" "$DB_PASS" <<'PYEOF' >/dev/null 2>&1
import sys
import psycopg
database, user, password = sys.argv[1], sys.argv[2], sys.argv[3]
with psycopg.connect(
    f"host=localhost port=5432 dbname={database} user={user} password={password}",
    connect_timeout=3,
) as conn:
    conn.execute("SELECT 1")
PYEOF
  then
    return 0
  fi
  # Fall back to psql where psycopg is not installed yet (e.g. `make up`
  # before `make deps`), so the script still works in either order.
  if command -v psql >/dev/null 2>&1; then
    PGPASSWORD="$DB_PASS" psql -h localhost -U "$DB_USER" -d "$DB_NAME" \
      -tAc 'select 1' >/dev/null 2>&1
    return $?
  fi
  return 1
}

wait_ready() {
  for _ in $(seq 1 40); do
    if probe; then
      log "database ready -> localhost:5432/$DB_NAME as $DB_USER"
      return 0
    fi
    sleep 2
  done
  log "ERROR: database did not become ready in time."
  log "       Check 'docker compose ps' and 'docker compose logs db'."
  log "       If neither psycopg nor psql is installed, run 'make deps' first."
  return 1
}

# pg_read_all_stats lets sec.verify_second_factor() read the CALLING backend's
# start time while running as the owner, which is how a session is bound to
# the connection that created it. Needed on BOTH paths: the native cluster
# creates berka_owner as an ordinary role, and while the docker image makes it
# a superuser, relying on that would couple a security feature to which of the
# two startup paths happened to run.
grant_stats() {
  "$PY" - "$DB_NAME" "$DB_USER" "$DB_PASS" <<'PYEOF' 2>/dev/null || true
import sys
import psycopg
database, user, password = sys.argv[1], sys.argv[2], sys.argv[3]
with psycopg.connect(
    f"host=localhost port=5432 dbname={database} user={user} password={password}",
    autocommit=True,
) as conn:
    row = conn.execute("SELECT rolsuper FROM pg_roles WHERE rolname = %s", (user,)).fetchone()
    if row and row[0]:
        print(f"db_up | {user} is a superuser, pg_read_all_stats not needed")
    else:
        conn.execute(f'GRANT pg_read_all_stats TO "{user}"')
        print(f"db_up | granted pg_read_all_stats to {user}")
PYEOF
}

if docker info >/dev/null 2>&1; then
  log "docker daemon available -> using docker compose"
  docker compose up -d
  wait_ready
  grant_stats
  exit 0
fi

log "docker daemon not available -> falling back to a native PostgreSQL 16 cluster"
if ! command -v pg_ctlcluster >/dev/null 2>&1; then
  log "ERROR: neither a docker daemon nor a native PostgreSQL 16 cluster is available."
  log "       Start Docker Desktop (and enable WSL integration), or install"
  log "       PostgreSQL 16, then re-run 'make up'."
  exit 1
fi

if ! pg_lsclusters -h 2>/dev/null | grep -q '^16 *main .*online'; then
  log "starting cluster 16/main"
  pg_ctlcluster 16 main start || true
fi

log "ensuring role and database exist"
su postgres -c "psql -v ON_ERROR_STOP=1 -tAc \"SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'\"" \
  | grep -q 1 \
  || su postgres -c "psql -v ON_ERROR_STOP=1 -c \"CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASS}' CREATEROLE\""

su postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'\"" \
  | grep -q 1 \
  || su postgres -c "createdb -O ${DB_USER} ${DB_NAME}"

su postgres -c "psql -v ON_ERROR_STOP=1 -d ${DB_NAME} -c 'GRANT ALL ON DATABASE ${DB_NAME} TO ${DB_USER}; GRANT ALL ON SCHEMA public TO ${DB_USER};'" >/dev/null
su postgres -c "psql -v ON_ERROR_STOP=1 -d ${DB_NAME} -c 'GRANT pg_read_all_stats TO ${DB_USER};'" >/dev/null

wait_ready
