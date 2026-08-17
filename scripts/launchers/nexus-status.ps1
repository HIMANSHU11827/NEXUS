# NEXUS AI - Quick environment status. Stdlib-only, no imports required.
$Root = $PSScriptRoot
function Test-Cmd([string]$name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}
Write-Host "=== NEXUS AI Status ==="
Write-Host "root        : $Root"
Write-Host "python      : $(Test-Cmd python)"
Write-Host "uv          : $(Test-Cmd uv)"
Write-Host "node        : $(Test-Cmd node)"
Write-Host "npm         : $(Test-Cmd npm)"
Write-Host "venv        : $(Test-Path (Join-Path $Root '.venv\Scripts\python.exe'))"
Write-Host "config/.env : $(Test-Path (Join-Path $Root 'config\.env'))"
Write-Host ""
Write-Host "Missing something? Run .\setup.ps1 (or .\nexus-setup.cmd) to install."