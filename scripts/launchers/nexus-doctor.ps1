# NEXUS AI - Environment doctor. Heavy checks; safe to run anywhere.
$Root = $PSScriptRoot
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
$py = if (Test-Path $venvPy) { $venvPy } else { "python" }

Write-Host "=== NEXUS AI Doctor ==="
Write-Host "root        : $Root"
Write-Host "python      : $py ($(& $py --version 2>&1))"
Write-Host "venv        : $(Test-Path $venvPy)"
Write-Host "config/.env : $(Test-Path (Join-Path $Root 'config\.env'))"
Write-Host "pyproject   : $(Test-Path (Join-Path $Root 'pyproject.toml'))"

# Write the probe to a temp file to avoid single-line `-c` mangling.
$tmpProbe = Join-Path $env:TEMP "nexus_doctor_probe.py"
@'
import importlib, sys
sys.path.insert(0, r"%REPO_ROOT%")
modules = ["server", "nexus", "fastapi", "uvicorn", "tools"]
for m in modules:
    try:
        importlib.import_module(m)
        print("  [OK] import", m)
    except Exception as e:
        print("  [FAIL] import", m + ":", type(e).__name__, e)
'@ -replace "%REPO_ROOT%", $Root | Set-Content -LiteralPath $tmpProbe -Encoding utf8

Write-Host "imports:"
& $py $tmpProbe 2>&1 | ForEach-Object { Write-Host "  $_" }
Remove-Item -LiteralPath $tmpProbe -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Next: .\setup.ps1 to repair, .\nexus.cmd to launch."