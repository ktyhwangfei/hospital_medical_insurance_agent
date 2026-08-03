# start-servers.ps1 - Start hospital medical insurance platform (backend + frontend)
# Improvements (based on --reload orphan worker issue):
#   1. Clean up leftovers first (calls stop-servers.ps1, handles orphan workers)
#   2. Verify ports truly free after cleanup (stale TCP entries count as occupied)
#   3. Single-process backend (no --reload): avoids multiprocessing orphan workers
#   4. Health check after start
# Usage:
#   .\start-servers.ps1
#   .\start-servers.ps1 -BackendPort 8100 -FrontendPort 3100
# Multi-workspace example:
#   worktree A: .\start-servers.ps1 -BackendPort 8000 -FrontendPort 3000
#   worktree B: .\start-servers.ps1 -BackendPort 8100 -FrontendPort 3100
# Stop matching workspace servers:
#   .\stop-servers.ps1 -BackendPort 8100 -FrontendPort 3100
# NOTE: keep comments ASCII-only (see stop-servers.ps1 for encoding rationale).

param(
    [ValidateRange(1, 65535)]
    [int]$BackendPort = 8000,

    [ValidateRange(1, 65535)]
    [int]$FrontendPort = 3000
)

$ErrorActionPreference = "Stop"
$PORT_BACKEND = $BackendPort
$PORT_FRONTEND = $FrontendPort
$WORKDIR = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "[1/5] Clean up any leftovers (incl. orphan workers)..." -ForegroundColor Cyan
& "$WORKDIR\stop-servers.ps1" -BackendPort $PORT_BACKEND -FrontendPort $PORT_FRONTEND
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
# NOTE: uvicorn --reload spawns multiprocessing workers; if the master dies the workers
#   become orphans holding the port + stale code (see stop-servers.ps1). Use single process
#   for daily dev; restart via .\stop-servers.ps1; .\start-servers.ps1 after backend edits.
$be = Start-Process uvicorn -ArgumentList "src.runtime.api.app:create_app","--host","127.0.0.1","--port","$PORT_BACKEND","--factory","--app-dir","$WORKDIR" -WorkingDirectory $WORKDIR -WindowStyle Hidden -PassThru
$backendElapsed = 0
$backendHealthy = $false
do {
    Start-Sleep -Seconds 1
    $backendElapsed += 1
    try {
        Invoke-WebRequest "http://127.0.0.1:${PORT_BACKEND}/health" -UseBasicParsing -TimeoutSec 5 | Out-Null
        $backendHealthy = $true
    } catch {}
} while (-not $backendHealthy -and $backendElapsed -lt 30 -and -not $be.HasExited)
if (-not $backendHealthy) {
    Write-Error "Backend health check failed after ${backendElapsed}s"; exit 1
}
Write-Host "  Backend PID $($be.Id) healthy (${backendElapsed}s)" -ForegroundColor Green

Write-Host "[4/5] Start frontend (portal)..." -ForegroundColor Cyan
$portalDir = "$WORKDIR\src\apps\portal"
$escapedPortalDir = $portalDir.Replace("'", "''")
$frontendCommand = "Set-Location -LiteralPath '$escapedPortalDir'; `$env:NEXT_PUBLIC_API_BASE_URL='http://127.0.0.1:${PORT_BACKEND}'; npm run dev -- -p ${PORT_FRONTEND}"
$fe = Start-Process powershell -ArgumentList "-NoProfile","-Command",$frontendCommand -WindowStyle Minimized -PassThru
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
Write-Host "Stop:    .\stop-servers.ps1 -BackendPort $PORT_BACKEND -FrontendPort $PORT_FRONTEND" -ForegroundColor DarkGray
