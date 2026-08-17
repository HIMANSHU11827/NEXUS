@echo off
setlocal

REM Deprecated no-CLI-flag approach: delegate to the PowerShell doctor.
if exist "%~dp0nexus-doctor.ps1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0nexus-doctor.ps1" %*
) else (
    echo [nexus-doctor] nexus-doctor.ps1 not found.
)
exit /b 0