@echo off
set "NEXUS_ROOT=%~dp0"
cd /d "%NEXUS_ROOT%"
set "PYTHONPATH=%NEXUS_ROOT%"
set "NEXUS_PYTHON=%NEXUS_ROOT%.venv\Scripts\python.exe"
if not exist "%NEXUS_PYTHON%" set "NEXUS_PYTHON=python"
"%NEXUS_PYTHON%" -m nexus %*
