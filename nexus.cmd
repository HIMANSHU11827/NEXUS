@echo off
rem NEXUS AI launcher — placed at the repo root so that adding the repo
rem root to PATH (scripts\add-to-path.ps1) makes `nexus` work in any
rem terminal (PowerShell / cmd). Uses the uv-managed venv console script
rem (created by `uv sync`, which builds + installs the `nexus` package).
set "NEXUS_ROOT=%~dp0"
set "NEXUS_VENV=%NEXUS_ROOT%.venv\Scripts"
set "NEXUS_EXE=%NEXUS_VENV%\nexus.exe"
if exist "%NEXUS_EXE%" (
    "%NEXUS_EXE%" %*
) else (
    set "NEXUS_PYTHON=%NEXUS_VENV%\python.exe"
    if not exist "%NEXUS_PYTHON%" set "NEXUS_PYTHON=python"
    "%NEXUS_PYTHON%" -m nexus %*
)
