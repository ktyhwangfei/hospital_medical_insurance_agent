# stop-servers.ps1 - Stop hospital medical insurance platform servers
# Improvements (based on --reload orphan worker issue):
#   1. Match backend by command line (create_app / src.runtime.api.app), not just port PID
#   2. Detect multiprocessing orphan workers: spawn_main with dead parent
#      (uvicorn --reload master killed -> worker orphaned, holds port + stale code)
#   3. taskkill /F /T kills process tree (incl. children)
#   4. Verify not just ports but backend process residue + orphans
#
# Background: netstat LISTENING PID can be a stale entry (process dead, PID recycled,
#   TCP table not updated); killing it reports "process not found". The real port holder
#   is the orphan worker (command line spawn_main, no "uvicorn"), never caught by port PID.
# Usage: .\stop-servers.ps1
# NOTE: keep comments ASCII-only. Non-ASCII (CJK) bytes in UTF-8-no-BOM files get
#   mis-decoded by PowerShell 5.x (GBK), which can swallow newlines and break parsing.

$ErrorActionPreference = "SilentlyContinue"

$BACKEND_PORT = 8000
$FRONTEND_PORT = 3000
$WATCH_PORTS = @(8000, 3000, 3001, 3002)

# All alive process IDs (to detect orphans: parent already dead)
$alivePids = [System.Collections.Generic.HashSet[int]]::new()
foreach ($p in (Get-Process)) { $null = $alivePids.Add([int]$p.Id) }

# 1) Backend master: python whose command line has create_app / src.runtime.api.app
$backendMain = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine -match 'create_app|src\.runtime\.api\.app' }
$backendMainIds = [System.Collections.Generic.HashSet[int]]::new()
foreach ($m in $backendMain) { $null = $backendMainIds.Add([int]$m.ProcessId) }

# 2) Backend multiprocessing workers (incl. orphans): command line has spawn_main
$backendWorkers = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine -match 'spawn_main' }

# 3) Frontend: node whose command line has this project path src/apps/portal
#    Covers next dev / start-server / postcss build children; avoids killing VSCode/MCP nodes
$frontend = Get-CimInstance Win32_Process -Filter "Name='node.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine -match 'src[/\\]apps[/\\]portal' }

# 4) Port LISTENING PIDs (fallback, incl. stale entries' real holders)
$portPids = @()
foreach ($p in $WATCH_PORTS) {
    $portPids += ((netstat -ano | Select-String ":$p\s.*LISTENING") |
        ForEach-Object { ($_ -replace '.*\s(\d+)\s*$', '$1').Trim() })
}
$portPids = $portPids | Sort-Object -Unique

# Collect PIDs to kill
$toKill = [System.Collections.Generic.HashSet[int]]::new()
foreach ($id in $backendMainIds) { $null = $toKill.Add([int]$id) }
foreach ($f in $frontend) { $null = $toKill.Add([int]$f.ProcessId) }
foreach ($id in $portPids) { $null = $toKill.Add([int]$id) }
foreach ($w in $backendWorkers) {
    # parse spawn_main(parent_pid=XXXX, ...)
    $m = [regex]::Match($w.CommandLine, 'parent_pid=(\d+)')
    $parentPid = if ($m.Success) { [int]$m.Groups[1].Value } else { 0 }
    # worker belongs to this backend: parent is backend master, or parent already dead (orphan)
    if ($backendMainIds.Contains($parentPid) -or -not $alivePids.Contains($parentPid)) {
        $null = $toKill.Add([int]$w.ProcessId)
    }
}

if ($toKill.Count -eq 0) {
    Write-Host "No running server processes found" -ForegroundColor Gray
    exit 0
}

Write-Host "Stopping $($toKill.Count) process(es)..." -ForegroundColor Cyan
foreach ($procId in $toKill) {
    $procName = try { (Get-Process -Id $procId -ErrorAction Stop).ProcessName } catch { "(dead/stale)" }
    Write-Host "  PID $procId ($procName)" -ForegroundColor Yellow
    # /T recursively kills child processes (multiprocessing worker tree)
    taskkill /F /T /PID $procId 2>$null | Out-Null
    # fallback
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
}

Start-Sleep -Seconds 3

# Verify: ports free + no backend residue
$stillBackend = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -and ($_.CommandLine -match 'create_app|src\.runtime\.api\.app') }).Count
$stillPort = (netstat -ano | Select-String ":$BACKEND_PORT\s.*LISTENING|:$FRONTEND_PORT\s.*LISTENING").Count

if ($stillBackend -gt 0 -or $stillPort -gt 0) {
    Write-Warning "Residual: backend_procs=$stillBackend port_listeners=$stillPort. Orphan workers may persist; reboot if needed."
    exit 2
} else {
    Write-Host "All server processes stopped (incl. orphan workers)" -ForegroundColor Green
}
