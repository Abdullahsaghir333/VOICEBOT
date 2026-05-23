@echo off
cd /d %~dp0

if not exist "venv\Scripts\python.exe" (
    echo Creating virtual environment in .\venv ...
    python -m venv venv
    if errorlevel 1 (
        echo Failed to create venv. Install Python 3.11+ and try again.
        exit /b 1
    )
)

echo Installing dependencies into venv ...
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r requirements.txt

echo.
echo Done. Activate with:  venv\Scripts\activate
echo Or run directly:      run_api.bat   and   run_ui.bat
exit /b 0
