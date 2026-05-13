@echo off
setlocal

set "ROOT=%~dp0"

echo Starting backend: http://127.0.0.1:8000
start "medical-insurance-backend" cmd /k "cd /d "%ROOT%" && uvicorn src.runtime.api.app:create_app --host 127.0.0.1 --port 8000 --factory --reload"

echo Starting frontend portal: http://127.0.0.1:3000
start "medical-insurance-portal" cmd /k "cd /d "%ROOT%src\apps\portal" && npm run dev"

echo Starting frontend admin: http://127.0.0.1:3001
start "medical-insurance-admin" cmd /k "cd /d "%ROOT%src\apps\admin" && npm run dev --port 3001"

echo Starting frontend embed: http://127.0.0.1:3002
start "medical-insurance-embed" cmd /k "cd /d "%ROOT%src\apps\embed" && npm run dev --port 3002"

echo Backend and 3 frontend apps have been opened in separate windows.
endlocal
