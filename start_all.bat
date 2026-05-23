@echo off
cd /d %~dp0
echo.
echo === Voicebot: start API + UI ===
echo.
call stop_api.bat
echo.
echo Starting API in a NEW window...
start "Voicebot API :8000" cmd /k run_api.bat
timeout /t 4 /nobreak >nul
echo Starting UI in a NEW window...
start "Voicebot UI :8501" cmd /k run_ui.bat
echo.
echo Open http://localhost:8501 after both windows show "startup complete"
echo Test API:  http://127.0.0.1:8001/health
echo ngrok:     ngrok http 8001
pause
