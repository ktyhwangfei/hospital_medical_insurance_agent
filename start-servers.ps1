# Start hospital medical insurance AI platform
$ErrorActionPreference = "Stop"
$PORT_BACKEND = 8000; $PORT_FRONTEND = 3000
$WORKDIR = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "[1/4] Port check..." -ForegroundColor Cyan
$killed = $false
foreach ($p in @($PORT_BACKEND, $PORT_FRONTEND, 3001, 3002)) {
    $lines = netstat -ano | Select-String ":$p.*LISTENING"
    if ($lines) {
        $lines | ForEach-Object { ($_ -replace '.*\s(\d+)$', '$1').Trim() } | Sort-Object -Unique | ForEach-Object {
            Write-Host "  Kill PID $_ (port $p)" -ForegroundColor Yellow
            taskkill /F /PID $_ 2>$null | Out-Null
            $killed = $true
        }
    }
}
if ($killed) { Start-Sleep -Seconds 3 }

Write-Host "[2/4] Verify ports..." -ForegroundColor Cyan
if (netstat -ano | Select-String ":${PORT_BACKEND}.*LISTENING|:${PORT_FRONTEND}.*LISTENING") {
    Write-Error "Ports still in use"; exit 1
}
Write-Host "  Ports free" -ForegroundColor Green

Write-Host "[3/4] Backend..." -ForegroundColor Cyan
$be = Start-Process uvicorn -ArgumentList "src.runtime.api.app:create_app","--host","127.0.0.1","--port","$PORT_BACKEND","--factory" -WorkingDirectory $WORKDIR -WindowStyle Hidden -PassThru
Start-Sleep -Seconds 2
try { Invoke-WebRequest "http://127.0.0.1:${PORT_BACKEND}/health" -UseBasicParsing -TimeoutSec 5 | Out-Null; Write-Host "  Backend PID $($be.Id) OK" -ForegroundColor Green } catch { Write-Error "Backend failed"; exit 1 }

Write-Host "[4/4] Frontend..." -ForegroundColor Cyan
$portalDir = "$WORKDIR\src\apps\portal"
$fe = Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$portalDir'; npm run dev" -WindowStyle Minimized -PassThru
Write-Host "  Compiling (PID $($fe.Id))..." -ForegroundColor Yellow
$elapsed = 0
do { Start-Sleep -Seconds 3; $elapsed += 3; try { if ((Invoke-WebRequest "http://127.0.0.1:${PORT_FRONTEND}/" -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200) { break } } catch {} } while ($elapsed -lt 90)
if ($elapsed -ge 90) { Write-Warning "Still compiling? Visit http://127.0.0.1:${PORT_FRONTEND}" } else { Write-Host "  Frontend ready" -ForegroundColor Green }

Write-Host "Backend: http://127.0.0.1:${PORT_BACKEND}" -ForegroundColor Green
Write-Host "Portal:  http://127.0.0.1:${PORT_FRONTEND}" -ForegroundColor Green