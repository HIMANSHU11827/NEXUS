@echo off
setlocal

if exist "%~dp0nexus-status.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0nexus-status.ps1" %*
) else (
    echo [nexus-status] nexus-status.ps1 not found.
)
exit /b 0