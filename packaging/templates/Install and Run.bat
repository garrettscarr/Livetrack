@echo off
cd /d "%~dp0"
echo Football EPA — install deps (first run) and launch
where python >nul 2>&1
if errorlevel 1 (
  echo Install Python 3.11+ from https://www.python.org/downloads/ then re-run.
  pause
  exit /b 1
)
if not exist .venv (
  python -m venv .venv
)
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\pip.exe install -r requirements.txt
echo.
echo Opening Football EPA on http://localhost:8501
.venv\Scripts\python.exe -m streamlit run step4_dashboard.py --server.port 8501
pause
