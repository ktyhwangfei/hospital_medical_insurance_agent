# Stop all hospital medical insurance platform servers
# Usage: .\stop-servers.ps1

$ports = netstat -ano | Select-String ":8000.*LISTENING|:3000.*LISTENING|:3001.*LISTENING|:3002.*LISTENING"
if ($ports) {
    $pids = $ports | ForEach-Object { ($_ -replace '.*\s(\d+)$', '$1').Trim() } | Sort-Object -Unique
    foreach ($p in $pids) {
        Write-Host "Stopping PID $p ..." -ForegroundColor Yellow
        taskkill /F /PID $p 2>$null | Out-Null
    }
    # Also kill any leftover uvicorn/node processes on known ports
    Get-Process -Name "uvicorn","node","python" -ErrorAction SilentlyContinue | Where-Object { $_.Id -in $pids } | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host "All server processes stopped" -ForegroundColor Green
} else {
    Write-Host "No running server processes found" -ForegroundColor Gray
}