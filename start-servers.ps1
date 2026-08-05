# start-servers.ps1 - Start hospital medical insurance platform (backend + frontend)
# Improvements (based on --reload orphan worker issue):
#   1. Clean up leftovers first (calls stop-servers.ps1, handles orphan workers)
#   2. Verify ports truly free after cleanup (stale TCP entries count as occupied)
#   3. Single-process backend (no --reload): avoids multiprocessing orphan workers
#   4. Health check after start
# Usage: .\start-servers.ps1   |   Stop: .\stop-servers.ps1
# NOTE: keep comments ASCII-only (see stop-servers.ps1 for encoding rationale).

$ErrorActionPreference = "Stop"
$PORT_BACKEND = 8000
$PORT_FRONTEND = 3000
$WORKDIR = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "[1/5] Clean up any leftovers (incl. orphan workers)..." -ForegroundColor Cyan
& "$WORKDIR\stop-servers.ps1"
# stop exits 2 if residual processes remain (orphan etc.); starting would fail to bind
if ($LASTEXITCODE -eq 2) {
    Write-Error "Cleanup left residual processes. Aborting start; kill manually or reboot."
    exit 1
}
Start-Sleep -Seconds 1

Write-Host "[2/5] Verify ports free..." -ForegroundColor Cyan
if (netstat -ano | Select-String ":${PORT_BACKEND}\s.*LISTENING|:${PORT_FRONTEND}\s.*LISTENING") {
    Write-Error "Ports still in use after cleanup. Orphan workers may persist; reboot or kill manually."
    exit 1
}
Write-Host "  Ports free" -ForegroundColor Green

Write-Host "[3/5] Start backend (single process, no --reload)..." -ForegroundColor Cyan
# NOTE: keep comments ASCII-only (see stop-servers.ps1 for encoding rationale).
# Load .env if present (gitignored: holds secrets like MODEL_API_KEY). Pre-set env vars win,
# so system-level env or interactive overrides are respected.
$envFile = Join-Path $WORKDIR ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $idx = $line.IndexOf("=")
            $k = $line.Substring(0, $idx).Trim()
            $v = $line.Substring($idx + 1).Trim().Trim('"').Trim("'")
            if (-not (Get-Item -Path "Env:$k" -ErrorAction SilentlyContinue)) {
                Set-Item -Path "Env:$k" -Value $v
            }
        }
    }
    Write-Host "  Loaded .env" -ForegroundColor DarkGray
}
# Inject MSSQL connection env vars for the backend process (SqlServerBusinessDataClient
# requires MSSQL_DATABASE/USER/PASSWORD). Pre-set env vars win; defaults match the local
# docker SQL Server (bjybdb, see deploy/docker/init_sqlserver.sh).
if (-not $env:MSSQL_HOST) { $env:MSSQL_HOST = "localhost" }
if (-not $env:MSSQL_PORT) { $env:MSSQL_PORT = "1433" }
if (-not $env:MSSQL_DATABASE) { $env:MSSQL_DATABASE = "bjybdb" }
if (-not $env:MSSQL_USER) { $env:MSSQL_USER = "sa" }
if (-not $env:MSSQL_PASSWORD) { $env:MSSQL_PASSWORD = "REDACTED" }
if (-not $env:MSSQL_DRIVER) { $env:MSSQL_DRIVER = "SQL Server" }
# Enable real-DB data source so the skill path (settlement_data_provider) can query
# the SQL Server settlement context (REST + SSE skill execution require real_db mode).
if (-not $env:DATA_SOURCE_MODE) { $env:DATA_SOURCE_MODE = "real_db" }
# Local-only Skill release controls use the mock authenticator. Production remains disabled.
if (-not $env:SKILL_CONTROL_DEV_MODE) { $env:SKILL_CONTROL_DEV_MODE = "1" }
# NOTE: uvicorn --reload spawns multiprocessing workers; if the master dies the workers
#   become orphans holding the port + stale code (see stop-servers.ps1). Use single process
#   for daily dev; restart via .\stop-servers.ps1; .\start-servers.ps1 after backend edits.
$be = Start-Process uvicorn -ArgumentList "src.runtime.api.app:create_app","--host","127.0.0.1","--port","$PORT_BACKEND","--factory" -WorkingDirectory $WORKDIR -WindowStyle Hidden -PassThru
Start-Sleep -Seconds 3
try {
    Invoke-WebRequest "http://127.0.0.1:${PORT_BACKEND}/health" -UseBasicParsing -TimeoutSec 5 | Out-Null
    Write-Host "  Backend PID $($be.Id) healthy" -ForegroundColor Green
} catch {
    Write-Error "Backend health check failed"; exit 1
}

Write-Host "[4/5] Start frontend (portal)..." -ForegroundColor Cyan
$portalDir = "$WORKDIR\src\apps\portal"
$fe = Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$portalDir'; npm run dev" -WindowStyle Minimized -PassThru
Write-Host "  Compiling (PID $($fe.Id))..." -ForegroundColor Yellow
$elapsed = 0
do {
    Start-Sleep -Seconds 3; $elapsed += 3
    try { if ((Invoke-WebRequest "http://127.0.0.1:${PORT_FRONTEND}/" -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200) { break } } catch {}
} while ($elapsed -lt 120)
if ($elapsed -ge 120) {
    Write-Warning "Frontend still compiling? Visit http://127.0.0.1:${PORT_FRONTEND}"
} else {
    Write-Host "  Frontend ready (${elapsed}s)" -ForegroundColor Green
}

Write-Host "[5/5] Done" -ForegroundColor Green
Write-Host "Backend: http://127.0.0.1:${PORT_BACKEND}  (PID $($be.Id))" -ForegroundColor Green
Write-Host "Portal:  http://127.0.0.1:${PORT_FRONTEND}  (PID $($fe.Id))" -ForegroundColor Green
Write-Host "Stop:    .\stop-servers.ps1" -ForegroundColor DarkGray
