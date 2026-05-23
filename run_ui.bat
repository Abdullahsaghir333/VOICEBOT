@echo off
cd /d %~dp0

if not exist "venv\Scripts\python.exe" (
    echo venv not found. Run setup.bat first.
    exit /b 1
)

venv\Scripts\python.exe -m streamlit run ui/streamlit_app.py
