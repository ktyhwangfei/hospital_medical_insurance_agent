# stop-servers.ps1 - Stop THIS worktree's servers only.
# Scope discipline (per git worktree):
#   Only the ports persisted in .server-ports.json (backend_port / frontend_port) are
#   considered. The listening PID on each port is cross-checked against our process
#   signatures (backend: create_app/src.runtime.api.app; frontend: src/apps/portal)
#   before killing, so a port that has been taken over by an EXTERNAL process is
#   never touched. Ports owned by other worktrees or manual instances are left alone.
# Usage: .\stop-servers.ps1
# Exit codes: 0 = stopped (or nothing to do); 2 = residual listeners remain
# NOTE: keep comments ASCII-only. Non-ASCII (CJK) bytes in UTF-8-no-BOM files get
#   mis-decoded by PowerShell 5.x (GBK), which can swallow newlines and break parsing.

$ErrorActionPreference = "SilentlyContinue"

$WORKDIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$STATE_FILE = Join-Path $WORKDIR ".server-ports.json"

# Resolve ports: persisted pair only. Without state file there is nothing scoped to stop.
$backendPort = $null
$frontendPort = $null
if (Test-Path $STATE_FILE) {
    try {
        $state = Get-Content $STATE_FILE -Raw | ConvertFrom-Json
        if ($state.backend_port) { $backendPort = [int]$state.backend_port }
        if ($state.frontend_port) { $frontendPort = [int]$state.frontend_port }
    } catch {}
}
if (-not $backendPort -and -not $frontendPort) {
    Write-Host "No .server-ports.json found; nothing scoped to stop." -ForegroundColor Gray
    exit 0
}
Write-Host "Scoped ports: backend=$backendPort frontend=$frontendPort" -ForegroundColor DarkGray

function Get-ListeningPids([int]$port) {
    @((netstat -ano | Select-String ":$port\s.*LISTENING") |
        ForEach-Object { ($_ -replace '.*\s(\d+)\s*$', '$1').Trim() }) | Sort-Object -Unique
}

$toKill = [System.Collections.Generic.HashSet[int]]::new()
$note = @()

# Backend: listening PID on our backend port must match our uvicorn signature.
if ($backendPort) {
    foreach ($pidStr in (Get-ListeningPids $backendPort)) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$pidStr" -ErrorAction SilentlyContinue
        if ($proc -and $proc.CommandLine -match 'create_app|src\.runtime\.api\.app') {
            $null = $toKill.Add([int]$proc.ProcessId)
        } else {
            $note += "backend port $backendPort held by PID $pidStr (not ours, skipped)"
        }
    }
}

# Frontend: listening PID on our frontend port must be a node serving this portal.
if ($frontendPort) {
    foreach ($pidStr in (Get-ListeningPids $frontendPort)) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$pidStr" -ErrorAction SilentlyContinue
        if ($proc -and $proc.CommandLine -match 'src[/\\]apps[/\\]portal') {
            $null = $toKill.Add([int]$proc.ProcessId)
        } else {
            $note += "frontend port $frontendPort held by PID $pidStr (not ours, skipped)"
        }
    }
}

if ($toKill.Count -eq 0) {
    Write-Host "No matching processes on scoped ports." -ForegroundColor Gray
    foreach ($n in $note) { Write-Host "  $n" -ForegroundColor Yellow }
    exit 0
}

Write-Host "Stopping $($toKill.Count) process(es)..." -ForegroundColor Cyan
foreach ($procId in $toKill) {
    $procName = try { (Get-Process -Id $procId -ErrorAction Stop).ProcessName } catch { "(dead/stale)" }
    Write-Host "  PID $procId ($procName)" -ForegroundColor Yellow
    # /T recursively kills child processes (next dev worker tree)
    taskkill /F /T /PID $procId 2>$null | Out-Null
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
}

Start-Sleep -Seconds 3

# Verify: our scoped ports are free.
$still = 0
foreach ($p in @($backendPort, $frontendPort)) {
    if ($p) { $still += @(Get-ListeningPids $p).Count }
}
if ($still -gt 0) {
    Write-Warning "Residual listeners remain on scoped ports (count=$still). Check netstat -ano." 
    exit 2
} else {
    Write-Host "All this worktree's server processes stopped. Ports remain reserved in .server-ports.json." -ForegroundColor Green
    Write-Host "Restart: .\start-servers.ps1 (reuses the same ports)" -ForegroundColor DarkGray
}
