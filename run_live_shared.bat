@echo off
cd /d "%~dp0"
echo ========================================
echo  Football EPA - Live Assistant (shared)
echo ========================================
echo.
echo Starting for booth laptop AND tablet on same Wi-Fi...
echo.

for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4 Address"') do (
  set IP=%%a
  goto :found
)
:found
set IP=%IP: =%

echo On THIS computer open:
echo   http://localhost:8501
echo.
echo On a TABLET / other device on the same Wi-Fi open:
echo   http://%IP%:8501
echo.
echo Booth PIN required (default in data\team_config.json).
echo Press Ctrl+C to stop.
echo.

set FOOTBALL_EPA_SHARED=1
if exist ".venv\Scripts\python.exe" (
  .venv\Scripts\python.exe -m streamlit run step4_dashboard.py --server.address 0.0.0.0 --server.port 8501
) else (
  python -m streamlit run step4_dashboard.py --server.address 0.0.0.0 --server.port 8501
)
pause
