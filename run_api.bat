@echo off
cd /d %~dp0

if not exist "venv\Scripts\python.exe" (
    echo venv not found. Run setup.bat first.
    exit /b 1
)

REM Use 8001 if 8000 is stuck (Errno 10048). Set API_PORT in .env to change.
set API_PORT=8001
echo Starting API on http://127.0.0.1:%API_PORT%
venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port %API_PORT%
