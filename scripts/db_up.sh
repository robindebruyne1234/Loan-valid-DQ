#!/usr/bin/env bash
# Bring up PostgreSQL 16 for this project.
#
# Preference order:
#   1. docker compose (portable, matches docker-compose.yml)
#   2. a natively installed PostgreSQL 16 cluster (pg_ctlcluster)
# Either way the pipeline sees the same server on localhost:5432 with the
# credentials from src/config.py, so `make all` does not care which path ran.
set -euo pipefail

DB_NAME="${PGDATABASE:-berka}"
DB_USER="${PGUSER:-berka_owner}"
DB_PASS="${PGPASSWORD:-berka_owner_pw}"

log() { echo "db_up | $*"; }

wait_ready() {
  for _ in $(seq 1 40); do
    if PGPASSWORD="$DB_PASS" psql -h localhost -U "$DB_USER" -d "$DB_NAME" -tAc 'select 1' >/dev/null 2>&1; then
      log "database ready -> localhost:5432/$DB_NAME as $DB_USER"
      return 0
    fi
    sleep 2
  done
  log "ERROR: database did not become ready in time"
  return 1
}

if docker info >/dev/null 2>&1; then
  log "docker daemon available -> using docker compose"
  docker compose up -d
  wait_ready
  exit 0
fi

log "docker daemon not available -> falling back to a native PostgreSQL 16 cluster"
if ! command -v pg_ctlcluster >/dev/null 2>&1; then
  log "ERROR: neither a docker daemon nor a native PostgreSQL 16 cluster is available."
  log "       Install PostgreSQL 16 or start Docker, then re-run 'make up'."
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

# pg_read_all_stats lets sec.verify_second_factor() read the CALLING backend's
# start time while running as the owner. Without it, pg_stat_activity hides
# another role's backend details and the session cannot be bound to the
# connection that created it. Read-only on statistics; no data access.
su postgres -c "psql -v ON_ERROR_STOP=1 -d ${DB_NAME} -c 'GRANT pg_read_all_stats TO ${DB_USER};'" >/dev/null

wait_ready
