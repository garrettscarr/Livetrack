@echo off
setlocal
cd /d "%~dp0\.."
set OUT=packaging\out
set STAGE=%OUT%\football-epa
if exist "%STAGE%" rmdir /s /q "%STAGE%"
mkdir "%STAGE%"

robocopy . "%STAGE%" /E /XD .venv .git packaging\out __pycache__ /XF *.pyc >nul
if exist "%STAGE%\data\live_log.csv" del "%STAGE%\data\live_log.csv"
if exist "%STAGE%\data\football.db" del "%STAGE%\data\football.db"
if exist "%STAGE%\data\hudl_exports\*.xlsx" del /q "%STAGE%\data\hudl_exports\*.xlsx"

copy /Y "packaging\templates\Install and Run.command" "%STAGE%\" >nul
copy /Y "packaging\templates\Install and Run.bat" "%STAGE%\" >nul

where powershell >nul 2>&1
if %ERRORLEVEL%==0 (
  powershell -Command "Compress-Archive -Path '%STAGE%' -DestinationPath '%OUT%\football-epa-portable.zip' -Force"
  echo Wrote %OUT%\football-epa-portable.zip
) else (
  echo Stage ready at %STAGE% — zip manually if Compress-Archive unavailable.
)
endlocal
