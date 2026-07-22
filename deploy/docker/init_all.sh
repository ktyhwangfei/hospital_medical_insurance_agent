#!/usr/bin/env bash
# ==========================================================
# init_all.sh - One-click full database init (WSL Ubuntu)
# ==========================================================
# Usage:
#   chmod +x init_all.sh
#   ./init_all.sh              # init both
#   ./init_all.sh --skip-pg    # skip PostgreSQL
#   ./init_all.sh --skip-mssql # skip SQL Server
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SKIP_PG=false
SKIP_MSSQL=false
for arg in "$@"; do
    case "$arg" in
        --skip-pg)    SKIP_PG=true ;;
        --skip-mssql) SKIP_MSSQL=true ;;
    esac
done

# --- Colors ---
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'

# --- Logging ---
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="${SCRIPT_DIR}/init_all_${TIMESTAMP}.log"

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
        *)       echo "$msg" ;;
    esac
}

run_script() {
    local script="$1"
    local label="$2"
    local start end ec elapsed

    log INFO ">>> Starting [$label]: $script"
    start=$(date +%s)

    bash "$script" 2>&1 | while IFS= read -r line; do
        echo "$line"
        echo "$line" >> "$LOG_FILE"
    done
    ec=${PIPESTATUS[0]}

    end=$(date +%s)
    elapsed=$((end - start))
    log INFO "<<< [$label] done | exit: $ec | elapsed: ${elapsed}s"
    return $ec
}

# ==========================================================
# Start
# ==========================================================
log HEADER "========================================"
log HEADER "  Database Full Init (WSL Ubuntu)"
log HEADER "  Log: $LOG_FILE"
log HEADER "  Start: $(date '+%Y-%m-%d %H:%M:%S')"
log HEADER "  Skip PG: $SKIP_PG | Skip MSSQL: $SKIP_MSSQL"
log HEADER "========================================"

TOTAL_START=$(date +%s)
PG_RESULT="SKIPPED"
MSSQL_RESULT="SKIPPED"

# --- PostgreSQL ---
if [ "$SKIP_PG" != "true" ]; then
    PG_SCRIPT="${SCRIPT_DIR}/init_postgres.sh"
    if [ -x "$PG_SCRIPT" ] || [ -f "$PG_SCRIPT" ]; then
        log HEADER "--- Phase 1/2: PostgreSQL ---"
        if run_script "$PG_SCRIPT" "PostgreSQL"; then
            PG_RESULT="OK"
            log SUCCESS "PASS: PostgreSQL"
        else
            PG_RESULT="FAIL"
            log ERROR "FAIL: PostgreSQL"
        fi
    else
        PG_RESULT="MISSING"
        log ERROR "Script not found: $PG_SCRIPT"
    fi
else
    log INFO "Phase 1/2: PostgreSQL - SKIPPED"
fi

# --- SQL Server ---
if [ "$SKIP_MSSQL" != "true" ]; then
    MSSQL_SCRIPT="${SCRIPT_DIR}/init_sqlserver.sh"
    if [ -x "$MSSQL_SCRIPT" ] || [ -f "$MSSQL_SCRIPT" ]; then
        log HEADER "--- Phase 2/2: SQL Server ---"
        if run_script "$MSSQL_SCRIPT" "SQL Server"; then
            MSSQL_RESULT="OK"
            log SUCCESS "PASS: SQL Server"
        else
            MSSQL_RESULT="FAIL"
            log ERROR "FAIL: SQL Server"
        fi
    else
        MSSQL_RESULT="MISSING"
        log ERROR "Script not found: $MSSQL_SCRIPT"
    fi
else
    log INFO "Phase 2/2: SQL Server - SKIPPED"
fi

# --- Summary ---
TOTAL_END=$(date +%s)
TOTAL_ELAPSED=$((TOTAL_END - TOTAL_START))

log HEADER ""
log HEADER "========================================"
log HEADER "  RESULTS"
pg_icon="[FAIL]";  [ "$PG_RESULT" = "OK" ] && pg_icon="[PASS]"
ms_icon="[FAIL]";  [ "$MSSQL_RESULT" = "OK" ] && ms_icon="[PASS]"
log HEADER "  $pg_icon PostgreSQL : $PG_RESULT"
log HEADER "  $ms_icon SQL Server : $MSSQL_RESULT"
log HEADER "  Total time: ${TOTAL_ELAPSED}s"
log HEADER "  Log: $LOG_FILE"
log HEADER "  End: $(date '+%Y-%m-%d %H:%M:%S')"
log HEADER "========================================"

if [ "$PG_RESULT" = "OK" ] && [ "$MSSQL_RESULT" = "OK" ]; then
    log INFO "Connection info:"
    log INFO "  PostgreSQL:  localhost:5432 | User: postgres | DB: hospital_mcp"
    log INFO "  SQL Server:  localhost:1433 | User: sa | DBs: bjybdb, TransDB"
    log INFO "  Passwords in: deploy/docker/.env"
fi

if [ "$PG_RESULT" = "FAIL" ] || [ "$MSSQL_RESULT" = "FAIL" ] || \
   [ "$PG_RESULT" = "MISSING" ] || [ "$MSSQL_RESULT" = "MISSING" ]; then
    exit 1
fi
exit 0