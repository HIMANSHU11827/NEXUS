@echo off
set "NEXUS_ROOT=%~dp0"
cd /d "%NEXUS_ROOT%"
set "PYTHONPATH=%NEXUS_ROOT%"
python -m nexus --gui %*
