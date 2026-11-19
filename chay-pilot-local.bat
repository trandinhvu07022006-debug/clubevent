@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PILOT_PY=python"
if exist ".venv\Scripts\python.exe" set "PILOT_PY=.venv\Scripts\python.exe"
"%PILOT_PY%" -m deployment.local_pilot %*
pause
