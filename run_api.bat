@echo off
cd /d %~dp0

if not exist "venv\Scripts\python.exe" (
    echo venv not found. Run setup.bat first.
    exit /b 1
)

venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
