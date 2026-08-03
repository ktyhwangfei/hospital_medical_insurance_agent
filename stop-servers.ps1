# stop-servers.ps1 - Stop hospital medical insurance platform servers
# Improvements (based on --reload orphan worker issue):
#   1. Resolve listener PIDs from requested ports first
#   2. Verify each listener belongs to this workspace before stopping it
#   3. Walk ancestors so taskkill /F /T also removes worker process trees
#   4. Verify requested ports and matching workspace processes are gone
#
# Background: netstat LISTENING PID can be a stale entry (process dead, PID recycled,
#   TCP table not updated); killing it reports "process not found". The real port holder
#   is the orphan worker (command line spawn_main, no "uvicorn"), never caught by port PID.
# Usage:
#   .\stop-servers.ps1
#   .\stop-servers.ps1 -BackendPort 8100 -FrontendPort 3100
#   .\stop-servers.ps1 -Ports 8100,3100
# Multi-workspace example:
#   worktree A: .\stop-servers.ps1 -BackendPort 8000 -FrontendPort 3000
#   worktree B: .\stop-servers.ps1 -Ports 8100,3100
# NOTE: keep comments ASCII-only. Non-ASCII (CJK) bytes in UTF-8-no-BOM files get
#   mis-decoded by PowerShell 5.x (GBK), which can swallow newlines and break parsing.

[CmdletBinding(DefaultParameterSetName = "Named")]
param(
    [Parameter(ParameterSetName = "Named")]
    [ValidateRange(1, 65535)]
    [int]$BackendPort,

    [Parameter(ParameterSetName = "Named")]
    [ValidateRange(1, 65535)]
    [int]$FrontendPort,

    [Parameter(Mandatory = $true, ParameterSetName = "Ports")]
    [ValidateNotNullOrEmpty()]
    [ValidateRange(1, 65535)]
    [int[]]$Ports
)

$ErrorActionPreference = "SilentlyContinue"
$WORKDIR = [System.IO.Path]::GetFullPath((Split-Path -Parent $MyInvocation.MyCommand.Path))

if ($PSCmdlet.ParameterSetName -eq "Ports") {
    $watchPorts = @($Ports)
} else {
    $watchPorts = @()
    if ($PSBoundParameters.ContainsKey("BackendPort")) { $watchPorts += $BackendPort }
    if ($PSBoundParameters.ContainsKey("FrontendPort")) { $watchPorts += $FrontendPort }
    if ($watchPorts.Count -eq 0) { $watchPorts = @(8000, 3000) }
}
$watchPorts = @($watchPorts | Sort-Object -Unique)

function Get-ListeningProcessIds {
    param([int]$Port)

    $pattern = "^\s*TCP\s+\S+:${Port}\s+\S+\s+LISTENING\s+(\d+)\s*$"
    return @(netstat -ano -p TCP | ForEach-Object {
        if ($_ -match $pattern) { [int]$Matches[1] }
    } | Sort-Object -Unique)
}

function Test-WorkspaceCommandLine {
    param([string]$CommandLine)

    if (-not $CommandLine) { return $false }
    return ($CommandLine.IndexOf($WORKDIR, [System.StringComparison]::OrdinalIgnoreCase) -ge 0)
}

function Get-WorkspaceProcessRoot {
    param([int]$ProcessId)

    $currentId = $ProcessId
    $workspaceRoot = $null
    $visited = [System.Collections.Generic.HashSet[int]]::new()
    while ($currentId -gt 0 -and $visited.Add($currentId)) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$currentId"
        if (-not $process) { break }
        if (Test-WorkspaceCommandLine $process.CommandLine) { $workspaceRoot = $process }
        $currentId = [int]$process.ParentProcessId
    }
    return $workspaceRoot
}

function Test-CommandLineTargetsPort {
    param(
        [string]$CommandLine,
        [int[]]$TargetPorts
    )

    if (-not $CommandLine) { return $false }
    foreach ($port in $TargetPorts) {
        $backendPattern = '--port\s+["'']?{0}(?:\s|["'']|$)' -f $port
        $frontendPattern = '(?:^|\s)-p\s+["'']?{0}(?:\s|["'']|$)' -f $port
        if ($CommandLine -match $backendPattern -or $CommandLine -match $frontendPattern) {
            return $true
        }
    }
    return $false
}

# Resolve listeners first, then keep only process trees owned by this workspace.
$toKill = [System.Collections.Generic.HashSet[int]]::new()
$foundListeners = $false
foreach ($port in $watchPorts) {
    foreach ($listenerPid in (Get-ListeningProcessIds $port)) {
        $foundListeners = $true
        $workspaceRoot = Get-WorkspaceProcessRoot $listenerPid
        if ($workspaceRoot) {
            $null = $toKill.Add([int]$workspaceRoot.ProcessId)
        } else {
            Write-Warning "Port $port is owned by PID $listenerPid from another workspace; leaving it running."
        }
    }
}

if (-not $foundListeners) {
    Write-Host "No running server processes found" -ForegroundColor Gray
    exit 0
}

if ($toKill.Count -gt 0) {
    Write-Host "Stopping $($toKill.Count) process tree(s)..." -ForegroundColor Cyan
    foreach ($procId in $toKill) {
        $procName = try { (Get-Process -Id $procId -ErrorAction Stop).ProcessName } catch { "(dead/stale)" }
        Write-Host "  PID $procId ($procName)" -ForegroundColor Yellow
        # /T recursively removes frontend children and multiprocessing workers.
        taskkill /F /T /PID $procId 2>$null | Out-Null
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 3
}

# Verify only the requested ports and matching processes from this workspace.
$stillPort = 0
foreach ($port in $watchPorts) { $stillPort += @(Get-ListeningProcessIds $port).Count }
$stillWorkspace = @(Get-CimInstance Win32_Process | Where-Object {
    (Test-WorkspaceCommandLine $_.CommandLine) -and
    ($_.CommandLine -match 'create_app|src\.runtime\.api\.app|npm run dev|next(?:\.cmd)? dev|start-server\.js') -and
    (Test-CommandLineTargetsPort $_.CommandLine $watchPorts)
}).Count

if ($stillWorkspace -gt 0 -or $stillPort -gt 0) {
    Write-Warning "Residual: workspace_procs=$stillWorkspace port_listeners=$stillPort. A listener may belong to another workspace."
    exit 2
} else {
    Write-Host "Requested server processes stopped (incl. worker process trees)" -ForegroundColor Green
}
