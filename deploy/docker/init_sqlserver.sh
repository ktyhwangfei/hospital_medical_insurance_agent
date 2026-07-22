#!/usr/bin/env bash
# ==========================================================
# init_sqlserver.sh - SQL Server database init (WSL Ubuntu)
# ==========================================================
# Usage:
#   chmod +x init_sqlserver.sh
#   ./init_sqlserver.sh
#   ./init_sqlserver.sh /mnt/d/project/hospital_medical_insurance_agent/deploy/docker
set -euo pipefail

# --- Config ---
DOCKER_DIR="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
SQL_BACKUP_DIR="${DOCKER_DIR}/backup/sqlserver"
COMPOSE_PROJECT="hospital-medical"
SERVICE_NAME="sqlserver"
CONTAINER_NAME="sql2022"
HEALTH_TIMEOUT=180

COMPOSE_FILE="${DOCKER_DIR}/docker-compose.yml"
ENV_FILE="${DOCKER_DIR}/.env"

# --- Colors ---
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; GRAY='\033[0;90m'; WHITE='\033[1;37m'; NC='\033[0m'

# --- Logging ---
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="${DOCKER_DIR}/init_sqlserver_${TIMESTAMP}.log"

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
    { docker "$@" 2>&1; } >> "$LOG_FILE" 2>&1
    local ec=$?
    log RESULT "ExitCode: $ec"
    return $ec
}

# ==========================================================
# 0. Pre-check & read SA password
# ==========================================================
log HEADER "========================================"
log HEADER "  SQL Server Init Script (WSL Ubuntu)"
log HEADER "  Log file: $LOG_FILE"
log HEADER "  Backup dir: $SQL_BACKUP_DIR"
log HEADER "  Start: $(date '+%Y-%m-%d %H:%M:%S')"
log HEADER "========================================"

if [ ! -f "$COMPOSE_FILE" ]; then
    log ERROR "docker-compose.yml not found: $COMPOSE_FILE"
    exit 1
fi
if [ ! -d "$SQL_BACKUP_DIR" ]; then
    log ERROR "Backup dir not found: $SQL_BACKUP_DIR"
    exit 1
fi

# Read SA password
SA_PASSWORD=""
if [ -f "$ENV_FILE" ]; then
    SA_PASSWORD=$(grep -oP '^SA_PASSWORD=\K.*' "$ENV_FILE" 2>/dev/null | head -1 || echo "")
fi
if [ -z "$SA_PASSWORD" ]; then
    SA_PASSWORD="REDACTED"
    log WARN "SA_PASSWORD not found in .env, using default"
fi
log INFO "SA password loaded (length: ${#SA_PASSWORD})"

# Database list
declare -A DB_DATA=(
    [bjybdb]="bjybdb_Data.MDF"
    [TransDB]="TransDB_Data.MDF"
)
declare -A DB_LOG=(
    [bjybdb]="bjybdb_log.LDF"
    [TransDB]="TransDB_Log.LDF"
)
DB_NAMES="bjybdb TransDB"
log INFO "Target databases: $DB_NAMES"

# Check backup files
for db in $DB_NAMES; do
    data_file="${SQL_BACKUP_DIR}/${DB_DATA[$db]}"
    log_file_path="${SQL_BACKUP_DIR}/${DB_LOG[$db]}"
    if [ ! -f "$data_file" ]; then
        log ERROR "Data file not found: $data_file"
        exit 1
    fi
    if [ ! -f "$log_file_path" ]; then
        log ERROR "Log file not found: $log_file_path"
        exit 1
    fi
    data_mb=$(du -m "$data_file" 2>/dev/null | cut -f1 || echo "?")
    log_mb=$(du -m "$log_file_path" 2>/dev/null | cut -f1 || echo "?")
    log INFO "[$db] data: ${data_mb} MB | log: ${log_mb} MB"
done

# 1. Stop and clean
log INFO "[1/5] Stopping old SQL Server container..."
run_docker "docker compose stop" compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT" stop "$SERVICE_NAME" || true
run_docker "docker compose rm" compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT" rm -f "$SERVICE_NAME" || true
VOLUME_NAME="${COMPOSE_PROJECT}_sqlserver_data"
run_docker "docker volume rm" volume rm "$VOLUME_NAME" || true
# Force remove lingering orphan container
run_docker "docker rm -f" rm -f "$CONTAINER_NAME" || true
log SUCCESS "Old container and volume cleaned"

# 2. Start container
log INFO "[2/5] Starting SQL Server container..."
if ! run_docker "docker compose up -d" compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT" up -d "$SERVICE_NAME"; then
    log ERROR "Container start failed"
    exit 1
fi
log INFO "Container started, waiting (first start ~30-60s)..."

# 3. Wait for ready
log INFO "[3/5] Waiting for health check (max ${HEALTH_TIMEOUT}s)..."
elapsed=0
interval=5
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
            log SUCCESS "SQL Server healthy (${elapsed}s)"
            break
            ;;
        unhealthy)
            log WARN "SQL Server health check FAILED"
            run_docker "docker logs" logs --tail 20 "$CONTAINER_NAME" || true
            break
            ;;
    esac
    sleep $interval
    elapsed=$((elapsed + interval))
done

if [ "$ready" != "true" ]; then
    log WARN "SQL Server may not be ready (${elapsed}s), continuing..."
fi
sleep 10

# 4. Copy and attach databases
log INFO "[4/5] Copy files and attach databases..."
CONTAINER_DATA_DIR="/var/opt/mssql/data"

for db in $DB_NAMES; do
    data_file="${DB_DATA[$db]}"
    log_file_name="${DB_LOG[$db]}"
    src_data="${SQL_BACKUP_DIR}/${data_file}"
    src_log="${SQL_BACKUP_DIR}/${log_file_name}"

    log INFO "--- Processing [$db] ---"

    # 4a. Copy files to container
    log CMD "Copying $data_file ($(du -m "$src_data" | cut -f1) MB)..."
    if ! run_docker "docker cp $data_file" cp "$src_data" "${CONTAINER_NAME}:${CONTAINER_DATA_DIR}/${data_file}"; then
        log ERROR "Failed to copy $data_file"
        exit 1
    fi

    log CMD "Copying $log_file_name..."
    if ! run_docker "docker cp $log_file_name" cp "$src_log" "${CONTAINER_NAME}:${CONTAINER_DATA_DIR}/${log_file_name}"; then
        log ERROR "Failed to copy $log_file_name"
        exit 1
    fi

    # 4b. Fix permissions
    log CMD "Fixing permissions (chown mssql)..."
    run_docker "chown" exec "$CONTAINER_NAME" chown mssql:mssql "${CONTAINER_DATA_DIR}/${data_file}" "${CONTAINER_DATA_DIR}/${log_file_name}" || true
    log SUCCESS "Permissions fixed"

    # 4c. Drop existing database
    log CMD "Checking and dropping existing [$db]..."
    DROP_SQL="IF EXISTS (SELECT 1 FROM sys.databases WHERE name = N'${db}') BEGIN ALTER DATABASE [${db}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [${db}]; END"
    docker exec "$CONTAINER_NAME" /opt/mssql-tools18/bin/sqlcmd \
        -S localhost -U sa -P "$SA_PASSWORD" -C \
        -Q "$DROP_SQL" 2>&1 | tee -a "$LOG_FILE" || true

    # 4d. Attach database
    log CMD "Attaching [$db]..."
    ATTACH_SQL="CREATE DATABASE [${db}] ON (FILENAME = N'${CONTAINER_DATA_DIR}/${data_file}'), (FILENAME = N'${CONTAINER_DATA_DIR}/${log_file_name}') FOR ATTACH;"
    ATTACH_OUT=$(docker exec "$CONTAINER_NAME" /opt/mssql-tools18/bin/sqlcmd \
        -S localhost -U sa -P "$SA_PASSWORD" -C \
        -Q "$ATTACH_SQL" 2>&1) || true
    echo "$ATTACH_OUT" | tee -a "$LOG_FILE"

    if echo "$ATTACH_OUT" | grep -qE 'Msg [0-9]+, Level'; then
        log WARN "Attach [$db] may have failed, continuing..."
    else
        log SUCCESS "[$db] attached successfully!"
    fi
done

# 5. Verify
log INFO "[5/5] Verifying attached databases..."

VERIFY_SQL="SELECT name AS DatabaseName, state_desc AS State, create_date AS CreateDate, CAST(ROUND(size * 8.0 / 1024, 2) AS DECIMAL(10,2)) AS SizeMB FROM sys.master_files WHERE database_id > 4 ORDER BY name;"
log RESULT "Attached database status:"
docker exec "$CONTAINER_NAME" /opt/mssql-tools18/bin/sqlcmd \
    -S localhost -U sa -P "$SA_PASSWORD" -C \
    -Q "$VERIFY_SQL" 2>&1 | tee -a "$LOG_FILE" || true

# Count tables per database
for db in $DB_NAMES; do
    COUNT_SQL="USE [${db}]; SELECT COUNT(*) AS TableCount FROM sys.tables;"
    COUNT_OUT=$(docker exec "$CONTAINER_NAME" /opt/mssql-tools18/bin/sqlcmd \
        -S localhost -U sa -P "$SA_PASSWORD" -C \
        -Q "$COUNT_SQL" 2>&1) || true
    COUNT_VAL=$(echo "$COUNT_OUT" | grep -oP '\d+' | head -1 || echo "?")
    if [ -n "$COUNT_VAL" ] && [ "$COUNT_VAL" != "?" ]; then
        log SUCCESS "[$db] table count: $COUNT_VAL"
    fi
done

# Done
log HEADER "========================================"
log SUCCESS "  SQL Server init COMPLETE!"
log HEADER "  End: $(date '+%Y-%m-%d %H:%M:%S')"
log HEADER "  Connection: localhost:1433 | User: sa | DBs: $DB_NAMES"
log HEADER "  Log: $LOG_FILE"
log HEADER "========================================"