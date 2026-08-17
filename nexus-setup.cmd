@echo off
setlocal
set "NEXUS_ROOT=%~dp0"
cd /d "%NEXUS_ROOT%"

REM Run the one-command installer/repairer first (venv + deps + .env seed),
REM then open the interactive setup wizard.
if exist "%~dp0setup.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" -SkipNode
) else (
    echo [setup] setup.ps1 not found; continuing to wizard...
)

set "PYTHONPATH=%NEXUS_ROOT%"
set "NEXUS_PYTHON=%NEXUS_ROOT%.venv\Scripts\python.exe"
if not exist "%NEXUS_PYTHON%" set "NEXUS_PYTHON=python"
"%NEXUS_PYTHON%" -m nexus --setup %*
exit /b %errorlevel%
