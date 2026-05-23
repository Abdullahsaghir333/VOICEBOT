@echo off
cd /d %~dp0
echo Stopping processes on ports 8000 and 8001...

for %%P in (8000 8001) do (
    powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort %%P -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%P" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1
)

echo Done. Run run_api.bat ^(uses port 8001^)

pause
