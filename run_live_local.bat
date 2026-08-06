@echo off
cd /d "%~dp0"
echo Football EPA - Local only (this computer)
if exist ".venv\Scripts\python.exe" (
  .venv\Scripts\python.exe -m streamlit run step4_dashboard.py --server.port 8501
) else (
  python -m streamlit run step4_dashboard.py --server.port 8501
)
pause
