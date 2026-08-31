# start-servers.ps1 - Start hospital medical insurance platform (backend + frontend)
# Port strategy (per git worktree):
#   Each worktree owns a persisted port pair in .server-ports.json (next to this file).
#   - First start: pick the first free port from 8000 (backend) / 3000 (frontend) upward.
#   - Later starts: reuse the persisted pair while both ports are still free.
#   - If a persisted port was taken over by an EXTERNAL process, re-scan and persist again.
#   - NEVER stops/kills any existing process. If the persisted pair is already listening
#     (this worktree running), report and exit without touching anything.
# Frontend multi-instance: each instance uses its own Next build dir (.next-<port>)
#   so several worktrees (or a user-run dev server on 3000) can coexist.
# Usage: .\start-servers.ps1   |   Stop: .\stop-servers.ps1
# NOTE: keep comments ASCII-only (see stop-servers.ps1 for encoding rationale).

$ErrorActionPreference = "Stop"
$invokedWorkdir = Split-Path -Parent $MyInvocation.MyCommand.Path
$workdirItem = Get-Item -LiteralPath $invokedWorkdir
$linkTarget = @($workdirItem.Target)[0]
$WORKDIR = if ($linkTarget) {
    if ([System.IO.Path]::IsPathRooted($linkTarget)) { $linkTarget } else { Join-Path $invokedWorkdir $linkTarget }
} else {
    $invokedWorkdir
}
$STATE_FILE = Join-Path $WORKDIR ".server-ports.json"
$BASE_BACKEND = 8000
$BASE_FRONTEND = 3000
$MAX_SCAN = 50

function Test-PortListening([int]$port) {
    return [bool](netstat -ano | Select-String ":$port\s.*LISTENING")
}

function Get-FreePort([int]$base) {
    for ($p = $base; $p -lt $base + $MAX_SCAN; $p++) {
        if (-not (Test-PortListening $p)) { return $p }
    }
    throw "No free port found starting from $base"
}

function Read-State {
    if (Test-Path $STATE_FILE) {
        try { return Get-Content $STATE_FILE -Raw | ConvertFrom-Json } catch { return $null }
    }
    return $null
}

function Write-State([int]$be, [int]$fe, $workerPid = $null) {
    $nextState = @{ backend_port = $be; frontend_port = $fe; updated_at = (Get-Date -Format o) }
    if ($workerPid) { $nextState.worker_pid = [int]$workerPid }
    $nextState | ConvertTo-Json | Set-Content $STATE_FILE -Encoding UTF8
}

# ---- [1] Resolve ports: reuse persisted pair if free, otherwise scan ----
$PORT_BACKEND = 0
$PORT_FRONTEND = 0
$state = Read-State
if ($state -and $state.backend_port -and $state.frontend_port) {
    $bBusy = Test-PortListening ([int]$state.backend_port)
    $fBusy = Test-PortListening ([int]$state.frontend_port)
    if (-not $bBusy -and -not $fBusy) {
        $PORT_BACKEND = [int]$state.backend_port
        $PORT_FRONTEND = [int]$state.frontend_port
        Write-Host "  Reusing persisted ports backend=$PORT_BACKEND frontend=$PORT_FRONTEND" -ForegroundColor DarkGray
    } elseif ($bBusy -and -not $fBusy) {
        Write-Host "  Persisted backend port $($state.backend_port) taken over by another process; re-scanning backend..." -ForegroundColor Yellow
    } else {
        Write-Host "  Persisted frontend port $($state.frontend_port) taken over by another process; re-scanning frontend..." -ForegroundColor Yellow
    }
}
if ($PORT_BACKEND -eq 0) { $PORT_BACKEND = Get-FreePort $BASE_BACKEND }
if ($PORT_FRONTEND -eq 0) { $PORT_FRONTEND = Get-FreePort $BASE_FRONTEND }

# Idempotent start: if our persisted pair is already listening, report and exit.
if ((Test-PortListening $PORT_BACKEND) -or (Test-PortListening $PORT_FRONTEND)) {
    Write-Host "Ports backend=$PORT_BACKEND frontend=$PORT_FRONTEND already listening. Nothing to start." -ForegroundColor Yellow
    Write-Host "Backend: http://127.0.0.1:${PORT_BACKEND}" -ForegroundColor Green
    Write-Host "Portal:  http://127.0.0.1:${PORT_FRONTEND}" -ForegroundColor Green
    Write-Host "Stop:    .\stop-servers.ps1" -ForegroundColor DarkGray
    exit 0
}

Write-State $PORT_BACKEND $PORT_FRONTEND
Write-Host "Using backend=$PORT_BACKEND frontend=$PORT_FRONTEND (persisted in .server-ports.json)" -ForegroundColor Cyan

# ---- [2] Start backend (single process, no --reload) ----
Write-Host "[2/5] Start backend on port $PORT_BACKEND..." -ForegroundColor Cyan
# Load .env if present (gitignored: holds secrets like MODEL_API_KEY). Pre-set env vars win.
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
if (-not $env:DATA_GOVERNANCE_MASTER_KEY) {
    throw "DATA_GOVERNANCE_MASTER_KEY is required. Run: .\.venv\Scripts\python.exe scripts\configure_data_governance_local.py"
}
# Provide a short-lived signed semantic-review session to the local Portal only.
if (-not $env:AUTH_JWT_SECRET) { $env:AUTH_JWT_SECRET = [Guid]::NewGuid().ToString("N") }
if (-not $env:NEXT_PUBLIC_SEMANTIC_REVIEW_TOKEN) {
    $jwtHeader = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('{"alg":"HS256","typ":"JWT"}')).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    $jwtPayloadJson = @{ sub = "portal-dev-reviewer"; roles = @("information_department"); permissions = @("semantic:review"); exp = [DateTimeOffset]::UtcNow.AddHours(8).ToUnixTimeSeconds() } | ConvertTo-Json -Compress
    $jwtPayload = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($jwtPayloadJson)).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    $jwtHmac = New-Object System.Security.Cryptography.HMACSHA256
    $jwtHmac.Key = [Text.Encoding]::UTF8.GetBytes($env:AUTH_JWT_SECRET)
    $jwtSignature = [Convert]::ToBase64String($jwtHmac.ComputeHash([Text.Encoding]::ASCII.GetBytes("$jwtHeader.$jwtPayload"))).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    $jwtHmac.Dispose()
    $env:NEXT_PUBLIC_SEMANTIC_REVIEW_TOKEN = "$jwtHeader.$jwtPayload.$jwtSignature"
}
if (-not $env:NEXT_PUBLIC_DATA_GOVERNANCE_TOKEN) {
    $jwtHeader = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('{"alg":"HS256","typ":"JWT"}')).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    $jwtPayloadJson = @{ sub = "portal-dev-data-governance"; roles = @("information_department"); permissions = @("data_governance:read", "data_governance:write"); exp = [DateTimeOffset]::UtcNow.AddHours(8).ToUnixTimeSeconds() } | ConvertTo-Json -Compress
    $jwtPayload = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($jwtPayloadJson)).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    $jwtHmac = New-Object System.Security.Cryptography.HMACSHA256
    $jwtHmac.Key = [Text.Encoding]::UTF8.GetBytes($env:AUTH_JWT_SECRET)
    $jwtSignature = [Convert]::ToBase64String($jwtHmac.ComputeHash([Text.Encoding]::ASCII.GetBytes("$jwtHeader.$jwtPayload"))).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    $jwtHmac.Dispose()
    $env:NEXT_PUBLIC_DATA_GOVERNANCE_TOKEN = "$jwtHeader.$jwtPayload.$jwtSignature"
}
# Inject MSSQL connection env vars for the backend process (SqlServerBusinessDataClient
# requires MSSQL_DATABASE/USER/PASSWORD). Pre-set env vars win; the password is NOT
# hardcoded here - it is read from the gitignored deploy/docker/.env (SA_PASSWORD).
# See deploy/docker/init_sqlserver.sh for the local docker SQL Server (bjybdb).
if (-not $env:MSSQL_HOST) { $env:MSSQL_HOST = "localhost" }
if (-not $env:MSSQL_PORT) { $env:MSSQL_PORT = "1433" }
if (-not $env:MSSQL_DATABASE) { $env:MSSQL_DATABASE = "bjybdb" }
if (-not $env:MSSQL_USER) { $env:MSSQL_USER = "sa" }
$dockerEnvCandidates = @((Join-Path $WORKDIR "deploy\docker\.env"))
try {
    Push-Location $WORKDIR
    $gitCommonDir = (& git rev-parse --path-format=absolute --git-common-dir 2>$null).Trim()
    Pop-Location
    if ($gitCommonDir) {
        $mainCheckout = Split-Path $gitCommonDir -Parent
        $dockerEnvCandidates += Join-Path $mainCheckout "deploy\docker\.env"
    }
} catch {
    Pop-Location -ErrorAction SilentlyContinue
}
$dockerEnv = $dockerEnvCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $env:MSSQL_PASSWORD) {
    if ($dockerEnv) {
        $saPass = (Get-Content -LiteralPath $dockerEnv | Where-Object { $_ -match '^SA_PASSWORD=' }) -replace '^SA_PASSWORD=', ''
        if ($saPass) { $env:MSSQL_PASSWORD = $saPass.Trim() }
    }
    if (-not $env:MSSQL_PASSWORD) {
        Write-Warning "MSSQL_PASSWORD not set; set env var or add SA_PASSWORD to deploy/docker/.env"
    }
}
if (-not $env:POSTGRES_PASSWORD -and $dockerEnv) {
    $postgresPass = (Get-Content -LiteralPath $dockerEnv | Where-Object { $_ -match '^POSTGRES_PASSWORD=' }) -replace '^POSTGRES_PASSWORD=', ''
    if ($postgresPass) { $env:POSTGRES_PASSWORD = $postgresPass.Trim() }
}
if (-not $env:MSSQL_DRIVER) { $env:MSSQL_DRIVER = "SQL Server" }
# Register and verify the current local outpatient source before API/worker startup.
$pythonExe = Join-Path $WORKDIR ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) { $pythonExe = (Get-Command python -ErrorAction Stop).Source }
& $pythonExe (Join-Path $WORKDIR "scripts\bootstrap_outpatient_governance.py")
if ($LASTEXITCODE -ne 0) { throw "Outpatient data governance bootstrap failed" }
# Enable real-DB data source so the skill path (settlement_data_provider) can query
# the SQL Server settlement context (REST + SSE skill execution require real_db mode).
if (-not $env:DATA_SOURCE_MODE) { $env:DATA_SOURCE_MODE = "real_db" }
# Local-only Skill release controls use the mock authenticator. Production remains disabled.
if (-not $env:SKILL_CONTROL_DEV_MODE) { $env:SKILL_CONTROL_DEV_MODE = "1" }
# Local-only model governance endpoints use the mock authenticator. Production remains disabled.
if (-not $env:MODEL_GOVERNANCE_DEV_MODE) { $env:MODEL_GOVERNANCE_DEV_MODE = "1" }
# NOTE: uvicorn --reload spawns multiprocessing workers; if the master dies the workers
#   become orphans holding the port + stale code (see stop-servers.ps1). Use single process
#   for daily dev; restart via .\stop-servers.ps1; .\start-servers.ps1 after backend edits.
$be = Start-Process uvicorn -ArgumentList "src.runtime.api.app:create_app","--host","127.0.0.1","--port","$PORT_BACKEND","--factory" -WorkingDirectory $WORKDIR -WindowStyle Hidden -PassThru

# Health check with generous window (startup may wait on PostgreSQL connect timeouts)
$beOk = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:${PORT_BACKEND}/health" -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) { $beOk = $true; break }
    } catch {}
}
if (-not $beOk) {
    Write-Error "Backend health check failed on port $PORT_BACKEND (PID $($be.Id))"
    exit 1
}
Write-Host "  Backend PID $($be.Id) healthy" -ForegroundColor Green

# ---- [3] Start outpatient synchronization worker ----
Write-Host "[3/5] Start outpatient synchronization worker..." -ForegroundColor Cyan
$workerScript = Join-Path $WORKDIR "scripts\run_outpatient_sync_worker.py"
$worker = Start-Process $pythonExe -ArgumentList $workerScript -WorkingDirectory $WORKDIR -WindowStyle Hidden -PassThru
Start-Sleep -Seconds 1
if ($worker.HasExited) { throw "Outpatient synchronization worker failed to start" }
Write-State $PORT_BACKEND $PORT_FRONTEND $worker.Id
Write-Host "  Worker PID $($worker.Id) running" -ForegroundColor Green

# ---- [4] Start frontend (portal) on port $PORT_FRONTEND ----
Write-Host "[4/5] Start frontend (portal) on port $PORT_FRONTEND..." -ForegroundColor Cyan
$portalDir = "$WORKDIR\src\apps\portal"
# Route portal API calls to OUR backend; use an isolated Next build dir so this
# worktree instance never collides with other dev servers on the same checkout.
$env:NEXT_PUBLIC_API_BASE_URL = "http://127.0.0.1:${PORT_BACKEND}"
$env:NEXT_DIST_DIR = ".next-${PORT_FRONTEND}"
$fe = Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$portalDir'; npm run dev -- -p $PORT_FRONTEND" -WindowStyle Minimized -PassThru
Write-Host "  Compiling (PID $($fe.Id))..." -ForegroundColor Yellow
$feOk = $false
$elapsed = 0
while ($elapsed -lt 120) {
    Start-Sleep -Seconds 3; $elapsed += 3
    try { if ((Invoke-WebRequest "http://127.0.0.1:${PORT_FRONTEND}/" -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200) { $feOk = $true; break } } catch {}
}
if (-not $feOk) {
    Write-Warning "Frontend not ready in 120s? Visit http://127.0.0.1:${PORT_FRONTEND}"
} else {
    Write-Host "  Frontend ready (${elapsed}s)" -ForegroundColor Green
}

# ---- [5] Done ----
Write-Host "[5/5] Done" -ForegroundColor Green
Write-Host "Backend: http://127.0.0.1:${PORT_BACKEND}  (PID $($be.Id))" -ForegroundColor Green
Write-Host "Portal:  http://127.0.0.1:${PORT_FRONTEND}  (PID $($fe.Id))" -ForegroundColor Green
Write-Host "Worker:  outpatient sync (PID $($worker.Id))" -ForegroundColor Green
Write-Host "Ports persisted in .server-ports.json (reused on next start)" -ForegroundColor DarkGray
Write-Host "Stop:    .\stop-servers.ps1" -ForegroundColor DarkGray
