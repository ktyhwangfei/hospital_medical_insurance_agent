#!/usr/bin/env bash
# ==========================================================
# init_postgres.sh - PostgreSQL database init (WSL Ubuntu)
# ==========================================================
# Usage:
#   chmod +x init_postgres.sh
#   ./init_postgres.sh
#   ./init_postgres.sh /mnt/d/project/hospital_medical_insurance_agent/deploy/docker
set -euo pipefail

# --- Config ---
DOCKER_DIR="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
SQL_BACKUP_DIR="${DOCKER_DIR}/backup/postgres"
SQL_FILE="postgres.sql"
COMPOSE_PROJECT="hospital-medical"
SERVICE_NAME="postgres"
CONTAINER_NAME="medical-postgres"
HEALTH_TIMEOUT=120

COMPOSE_FILE="${DOCKER_DIR}/docker-compose.yml"
ENV_FILE="${DOCKER_DIR}/.env"
SQL_PATH="${SQL_BACKUP_DIR}/${SQL_FILE}"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;90m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

# --- Logging ---
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="${DOCKER_DIR}/init_postgres_${TIMESTAMP}.log"

log() {
    local level="$1"; shift
    local msg="$*"
    local ts
    ts=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$ts] [$level] $msg" >> "$LOG_FILE"

    case "$level" in
        ERROR)   echo -e "${RED}${msg}${NC}" ;;
        WARN)    echo -e "${YELLOW}${msg}${NC}" ;;
        SUCCESS) echo -e "${GREEN}${msg}${NC}" ;;
        HEADER)  echo -e "${CYAN}${msg}${NC}" ;;
        CMD)     echo -e "${GRAY}${msg}${NC}" ;;
        RESULT)  echo -e "${WHITE}${msg}${NC}" ;;
        *)       echo "$msg" ;;
    esac
}

run_docker() {
    local desc="$1"; shift
    log CMD "$desc"
    {
        docker "$@" 2>&1
    } >> "$LOG_FILE" 2>&1
    local ec=$?
    log RESULT "ExitCode: $ec" >&2
    return $ec
}

# ==========================================================
# Start
# ==========================================================
log HEADER "========================================"
log HEADER "  PostgreSQL Init Script (WSL Ubuntu)"
log HEADER "  Log file: $LOG_FILE"
log HEADER "  SQL source: $SQL_PATH"
log HEADER "  Compose: $COMPOSE_FILE"
log HEADER "  Start: $(date '+%Y-%m-%d %H:%M:%S')"
log HEADER "========================================"

# 0. Pre-check
if [ ! -f "$COMPOSE_FILE" ]; then
    log ERROR "docker-compose.yml not found: $COMPOSE_FILE"
    exit 1
fi
if [ ! -f "$SQL_PATH" ]; then
    log ERROR "Backup file not found: $SQL_PATH"
    exit 1
fi
SQL_SIZE_MB=$(du -m "$SQL_PATH" 2>/dev/null | cut -f1 || echo "?")
log INFO "Backup file size: ${SQL_SIZE_MB} MB"

# 1. Stop and clean
log INFO "[1/5] Stopping old PostgreSQL container..."
run_docker "docker compose stop" compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT" stop "$SERVICE_NAME" || true
run_docker "docker compose rm" compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT" rm -f "$SERVICE_NAME" || true
VOLUME_NAME="${COMPOSE_PROJECT}_postgres_data"
run_docker "docker volume rm" volume rm "$VOLUME_NAME" || true
# 强制删除可能残留的孤儿容器（非 compose 管理的同名容器）
run_docker "docker rm -f" rm -f "$CONTAINER_NAME" || true
log SUCCESS "Old container and volume cleaned"

# 2. Start container
log INFO "[2/5] Starting PostgreSQL container..."
if ! run_docker "docker compose up -d" compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT" up -d "$SERVICE_NAME"; then
    log ERROR "Container start failed"
    exit 1
fi
log INFO "Container started, waiting for health check..."

# 3. Wait for ready
log INFO "[3/5] Waiting for PostgreSQL health check (max ${HEALTH_TIMEOUT}s)..."
elapsed=0
interval=3
ready=false
last_status=""

while [ $elapsed -lt $HEALTH_TIMEOUT ]; do
    status=$(docker inspect --format='{{.State.Health.Status}}' "$CONTAINER_NAME" 2>/dev/null || echo "unknown")
    if [ "$status" != "$last_status" ]; then
        log CMD "  ${elapsed}s: status = $status"
        last_status="$status"
    fi
    case "$status" in
        healthy)
            ready=true
            log SUCCESS "PostgreSQL healthy (${elapsed}s)"
            break
            ;;
        unhealthy)
            log WARN "PostgreSQL health check FAILED"
            run_docker "docker logs" logs --tail 30 "$CONTAINER_NAME" || true
            break
            ;;
    esac
    sleep $interval
    elapsed=$((elapsed + interval))
done

if [ "$ready" != "true" ]; then
    log WARN "PostgreSQL may not be ready (${elapsed}s), continuing..."
fi
sleep 5

# 4. Restore database
log INFO "[4/5] Converting and restoring database..."

# 4a. UTF-16LE -> UTF-8 conversion
log CMD "Converting: UTF-16LE -> UTF-8 (CRLF->LF)..."
UTF8_SQL_PATH=$(mktemp /tmp/postgres_utf8_XXXXXX.sql)

if command -v iconv &>/dev/null; then
    iconv -f UTF-16LE -t UTF-8 "$SQL_PATH" > "$UTF8_SQL_PATH"
    log CMD "Converted via iconv"
else
    python3 -c "
import sys
data = open('$SQL_PATH', 'rb').read()
text = data.decode('utf-16-le')
if text and ord(text[0]) == 0xFEFF:
    text = text[1:]
text = text.replace('\r\n', '\n')
open('$UTF8_SQL_PATH', 'w', encoding='utf-8').write(text)
" 2>/dev/null
    log CMD "Converted via python3"
fi

# Strip BOM if present and convert CRLF -> LF
if command -v sed &>/dev/null; then
    sed -i '1s/^\xEF\xBB\xBF//' "$UTF8_SQL_PATH" 2>/dev/null || true
    sed -i 's/\r$//' "$UTF8_SQL_PATH" 2>/dev/null || true
    # Remove \restrict / \unrestrict lines (pg_dumpall security markers)
    # These cause psql to lock down and reject all backslash commands
    sed -i '/^\\restrict /d' "$UTF8_SQL_PATH" 2>/dev/null || true
    sed -i '/^\\unrestrict /d' "$UTF8_SQL_PATH" 2>/dev/null || true
    log CMD "Stripped \\restrict / \\unrestrict lines"
fi

CONVERTED_SIZE=$(du -m "$UTF8_SQL_PATH" 2>/dev/null | cut -f1 || echo "?")
log SUCCESS "Conversion done: ${CONVERTED_SIZE} MB"

# 4b. Copy to container
log CMD "Copying SQL file to container..."
CONTAINER_SQL="/tmp/${SQL_FILE}"
if ! docker cp "$UTF8_SQL_PATH" "${CONTAINER_NAME}:${CONTAINER_SQL}"; then
    rm -f "$UTF8_SQL_PATH"
    log ERROR "Failed to copy SQL file to container"
    exit 1
fi
rm -f "$UTF8_SQL_PATH"

# 4c. Execute SQL restore
log CMD "Executing SQL restore (ON_ERROR_STOP=0)..."
docker exec "$CONTAINER_NAME" psql -U postgres -v ON_ERROR_STOP=0 -f "$CONTAINER_SQL" postgres 2>&1 | tee -a "$LOG_FILE" || true
RESTORE_EC=$?
docker exec "$CONTAINER_NAME" rm -f "$CONTAINER_SQL" 2>/dev/null || true

if [ $RESTORE_EC -ne 0 ]; then
    log WARN "SQL restore exit code: $RESTORE_EC (non-zero, may be pre-existing objects)"
else
    log SUCCESS "SQL file executed, exit code: 0"
fi

# 4d. Reset postgres password (dump overwrites it with old hash)
log CMD "Resetting postgres password..."
PG_PASSWORD="postgres"
if [ -f "$ENV_FILE" ]; then
    ENV_PW=$(grep -oP '^POSTGRES_PASSWORD=\K.*' "$ENV_FILE" 2>/dev/null | head -1 || echo "")
    if [ -n "$ENV_PW" ]; then
        PG_PASSWORD="$ENV_PW"
    fi
fi
# docker exec within container uses local trust, no password needed
docker exec "$CONTAINER_NAME" psql -U postgres -c "ALTER ROLE postgres WITH PASSWORD '${PG_PASSWORD}';" 2>&1 | tee -a "$LOG_FILE" || true
log SUCCESS "postgres password reset to .env value"

# 5. Verify
log INFO "[5/5] Verifying database..."
log RESULT "Database list:"
docker exec "$CONTAINER_NAME" psql -U postgres -t -A -c "SELECT datname FROM pg_database ORDER BY datname;" 2>&1 | tee -a "$LOG_FILE"

log CMD "Counting tables in hospital_mcp..."
TABLE_COUNT=$(docker exec "$CONTAINER_NAME" psql -U postgres -t -A -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';" hospital_mcp 2>/dev/null | tr -d '[:space:]')
if [[ "$TABLE_COUNT" =~ ^[0-9]+$ ]]; then
    log SUCCESS "hospital_mcp public tables: $TABLE_COUNT"
else
    log WARN "Cannot query hospital_mcp tables"
fi

log CMD "Tables in hospital_mcp:"
docker exec "$CONTAINER_NAME" psql -U postgres -t -A -c "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name;" hospital_mcp 2>&1 | tee -a "$LOG_FILE"

# Done
log HEADER "========================================"
log SUCCESS "  PostgreSQL init COMPLETE!"
log HEADER "  End: $(date '+%Y-%m-%d %H:%M:%S')"
log HEADER "  Connection: localhost:5432 | User: postgres | DB: hospital_mcp"
log HEADER "  Log: $LOG_FILE"
log HEADER "========================================"