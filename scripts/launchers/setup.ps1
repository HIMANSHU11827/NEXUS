# ============================================================================
# NEXUS AI - Setup & Operations Tool
# setup / install / update / reinstall / restart / configure / doctor / status
# ============================================================================

param(
    [ValidateSet("setup","install","update","reinstall","fresh","restart",
                 "configure","doctor","status","check")]
    [string]$Action = "setup",
    [switch]$SkipNode,
    [switch]$SkipEnv,
    [switch]$SkipBackend,
    [switch]$Quiet,
    [switch]$Force,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false
$Root = $PSScriptRoot
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"

function Write-Step { process { if (-not $Quiet) { Write-Host "  $_" -ForegroundColor Cyan } } }
function Write-Ok   { process { if (-not $Quiet) { Write-Host "  [OK] $_" -ForegroundColor Green } } }
function Write-Warn { process { Write-Host "  [WARN] $_" -ForegroundColor Yellow } }
function Write-Err  { process { Write-Host "  [ERROR] $_" -ForegroundColor Red } }

function Confirm-Yes([string]$Msg) {
    if ($Force) { return $true }
    $r = Read-Host "$Msg [y/N]"
    return ($r -match '^[Yy]')
}

function Show-Help {
    $t = @(
        "NEXUS AI - Setup & Operations Tool",
        "  .\setup.ps1 [-Action <name>] [flags]",
        "",
        "Actions:",
        "  setup        Full idempotent install (venv + deps + node + .env)",
        "  install      Alias for setup",
        "  update       Refresh deps (no venv wipe)",
        "  reinstall    Wipe .venv and reinstall fresh",
        "  restart      Stop :8000/:5173 owners and restart API",
        "  configure    Open the interactive setup wizard",
        "  doctor       Run diagnostics (imports, env paths)",
        "  status       Quick environment overview",
        "  check        Inventory: what's installed vs missing + install choice",
        "",
        "Flags:",
        "  -SkipNode     Skip npm install (gui/, tui/)",
        "  -SkipEnv      Skip .env seeding",
        "  -SkipBackend  Skip backend import check",
        "  -Force        Skip confirmation prompts",
        "  -Quiet        Reduce output",
        "  -Help         Show this help"
    )
    $t | ForEach-Object { Write-Host $_ }
}
if ($Help) { Show-Help; exit 0 }

function Get-Python {
    foreach ($candidate in @($venvPy, "python")) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) { return $candidate }
    }
    Write-Err "No Python found. Install Python 3.11+ and retry."
    exit 1
}

function Install-Deps {
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        Write-Step "Using uv to sync deps"
        pushd $Root
        if (-not (Test-Path $venvPy)) { uv venv --quiet --python 3.11 }
        uv pip install -e ".[dev]"
        if ($LASTEXITCODE -eq 0) { Write-Ok "Deps installed via uv"; popd; return }
    }
    if (-not (Test-Path $venvPy)) {
        Write-Step "Creating .venv"
        python -m venv .venv 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { Write-Err "Failed to create venv"; exit 1 }
    }
    & $venvPy -m pip install --upgrade pip 2>&1 | Out-Null
    & $venvPy -m pip install -e ".[dev]" 2>&1 | Select-Object -Last 6 | ForEach-Object { if (-not $Quiet) { Write-Host "   $_" } }
    if ($LASTEXITCODE -ne 0) { Write-Err "pip install -e .[dev] failed"; exit 1 }
    Write-Ok "Deps installed via pip"
}

function Update-Deps {
    Write-Step "Updating dependencies (no venv wipe)"
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        pushd $Root
        if (-not (Test-Path $venvPy)) { uv venv --quiet --python 3.11 }
        uv pip install --upgrade -e ".[dev]"
        if ($LASTEXITCODE -eq 0) { Write-Ok "Deps updated via uv" } else { Write-Warn "uv update reported code $LASTEXITCODE" }
    } elseif (Test-Path $venvPy) {
        & $venvPy -m pip install --upgrade -e ".[dev]" 2>&1 | Select-Object -Last 6 | ForEach-Object { Write-Host "   $_" }
        Write-Ok "Deps updated via pip"
    } else {
        Write-Err "No venv to update; run setup/reinstall first."
    }
}




function Install-NodeDeps {
    if ($SkipNode) { Write-Warn "Skipping node deps"; return }
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Write-Warn "npm missing; skipped"; return }
    foreach ($proj in @("apps\web", "apps\tui")) {
        if (-not (Test-Path (Join-Path $Root "$proj\package.json"))) { continue }
        Write-Step "npm install ($proj)..."
        pushd (Join-Path $Root $proj)
        npm install 2>&1 | Select-Object -Last 4 | ForEach-Object { if (-not $Quiet) { Write-Host "   $_" } }
        if ($LASTEXITCODE -ne 0) { Write-Warn "npm install failed for $proj" } else { Write-Ok "$proj deps installed" }
        popd
    }
}

function Seed-Env {
    if ($SkipEnv) { Write-Warn "Skipping .env seed"; return }
    $t = Join-Path $Root ".env"
    $tpl = Join-Path $Root ".env.example"
    if (Test-Path $t) { Write-Ok ".env exists (left untouched)"; return }
    if (Test-Path $tpl) { Copy-Item $tpl $t; Write-Ok "Created .env from template" }
    else { Write-Warn ".env.example missing; nothing to seed" }
}

function Check-Backend {
    if ($SkipBackend) { Write-Warn "Skipping backend check"; return "" }
    $py = Get-Python
    $probe = (& $py -c "import server; print('server OK, routes=%d' % len(server.app.routes))" 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -eq 0) { Write-Ok $probe } else { Write-Warn "Backend import failed: $probe" }
    return $probe
}

function Show-Status {
    Write-Host "=== NEXUS AI Status ==="
    Write-Host "root        : $Root"
    Write-Host "python      : $([bool](Get-Command python -ErrorAction SilentlyContinue))"
    Write-Host "uv          : $([bool](Get-Command uv -ErrorAction SilentlyContinue))"
    Write-Host "node        : $([bool](Get-Command node -ErrorAction SilentlyContinue))"
    Write-Host "npm         : $([bool](Get-Command npm -ErrorAction SilentlyContinue))"
    Write-Host "venv        : $(Test-Path $venvPy)"
    Write-Host "config/.env : $(Test-Path (Join-Path $Root '.env'))"
}

function Show-Go-Summary([string]$probe) {
    Write-Host ""
    Write-Host "============================================================"
    Write-Host "                 NEXUS AI - Complete"
    Write-Host "------------------------------------------------------------"
    Write-Host "  action        : $Action"
    Write-Host "  venv          : $(if (Test-Path $venvPy) { 'OK' } else { 'MISSING' })"
    Write-Host "  config/.env   : $(if (Test-Path (Join-Path $Root '.env')) { 'present' } else { 'missing' })"
    Write-Host "  backend check : $(if ($probe -match 'server OK') { 'clean' } else { 'see above' })"
    Write-Host "============================================================"
    Write-Host ""
    Write-Host "  Next:"
    Write-Host "    .\nexus.cmd         launch (TUI default)"
    Write-Host "    .\run.ps1           launch server + GUI"
    Write-Host "    .\setup.ps1 -Action doctor | status | restart | update"
    Write-Host "    .\setup.ps1 -Action configure   (setup wizard)"
    Write-Host ""
}

function Show-Doctor {
    Write-Host "=== NEXUS AI Doctor ==="
    $py = Get-Python
    Write-Host "root        : $Root"
    Write-Host "python      : $py ($(& $py --version 2>&1))"
    Write-Host "venv        : $(Test-Path $venvPy)"
    Write-Host "config/.env : $(Test-Path (Join-Path $Root '.env'))"
    Write-Host "imports:"
    $escRoot = $Root.Replace("\", "\\")
    $tmp = Join-Path $env:TEMP "nexus_doctor_probe.py"
    [System.IO.File]::WriteAllText($tmp, "import importlib, sys" + [Environment]::NewLine +
        "sys.path.insert(0, r'" + $escRoot + "')" + [Environment]::NewLine +
        "for m in ['server','nexus','fastapi','uvicorn','tools']:" + [Environment]::NewLine +
        "    try:" + [Environment]::NewLine +
        "        importlib.import_module(m); print('  [OK]', m)" + [Environment]::NewLine +
        "    except Exception as e:" + [Environment]::NewLine +
        "        print('  [FAIL]', m, ':', type(e).__name__, e)" + [Environment]::NewLine)
    & $py $tmp 2>&1 | ForEach-Object { Write-Host "  $_" }
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
}

function Restart-Server {
    Write-Step "Stopping owners of :8000 and :5173..."
    foreach ($port in 8000, 5173) {
        $owners = & netstat.exe -ano -p tcp | ForEach-Object {
            if ($_ -match ("^\s*TCP\s+\S+:" + $port + "\s+.*LISTENING\s+(\d+)\s*$")) { [int]$Matches[1] }
        } | Select-Object -Unique
        $owners | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue; Write-Ok "Stopped PID $_ on :$port" }
    }
    Start-Sleep -Seconds 1
    $py = Get-Python
    Write-Step "Starting API server (python -m server) on :8000..."
    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $py
    $psi.Arguments = "-m server"
    $psi.WorkingDirectory = $Root
    $psi.UseShellExecute = $true
    try {
        $p = [System.Diagnostics.Process]::Start($psi)
        Write-Ok "API server started (PID $($p.Id))"
    } catch {
        Write-Err "Failed to start API server: $_"
    }
}

function Show-Go-Inventory {
    Write-Host "=== NEXUS AI - Inventory / Dependency Check ==="
    Write-Host ""
    Write-Host "System tools (what Hermes/OpenCode/OpenClaw reference installers use):"
    foreach ($t in @("python","uv","node","npm","pnpm","bun","docker","git","curl")) {
        $on = [bool](Get-Command $t -ErrorAction SilentlyContinue)
        $tag = if ($on) { "installed" } else { "MISSING  " }
        Write-Host ("  {0,-8} : {1}" -f $t, $tag)
    }
    Write-Host ""
    Write-Host "Project components:"
    $venvSt = if (Test-Path $venvPy) { "OK" } else { "MISSING" }
    Write-Host ("  {0,-12} : {1}" -f ".venv", $venvSt)
    $hasGui = Test-Path (Join-Path $Root "apps\web\node_modules")
    $guiSt = if ($hasGui) { "OK" } else { "MISSING" }
    Write-Host ("  {0,-12} : {1}" -f "gui deps", $guiSt)
    $hasTui = Test-Path (Join-Path $Root "apps\tui\node_modules")
    $tuiSt = if ($hasTui) { "OK" } else { "MISSING" }
    Write-Host ("  {0,-12} : {1}" -f "tui deps", $tuiSt)
    $hasEnv = Test-Path (Join-Path $Root ".env")
    $envSt = if ($hasEnv) { "present" } else { "missing" }
    Write-Host ("  {0,-12} : {1}" -f "config/.env", $envSt)
    Write-Host ""
}

function Do-Check {
    Show-Go-Inventory
    $missing = @()
    if (-not (Test-Path $venvPy)) { $missing += "1. Python venv + runtime deps" }
    if (-not (Test-Path (Join-Path $Root "apps\web\node_modules"))) { $missing += "2. GUI (react) node deps" }
    if (-not (Test-Path (Join-Path $Root "apps\tui\node_modules"))) { $missing += "3. TUI (ink) node deps" }
    if (-not (Test-Path (Join-Path $Root ".env"))) { $missing += "4. .env seed from template" }
    Write-Host "Missing items found: $($missing.Count)"
    if ($missing.Count -gt 0) {
        $missing | ForEach-Object { Write-Host ("    " + $_) }
        Write-Host ""
        Write-Host "Choose what to install:"
        Write-Host "  a) All missing (recommended)"
        Write-Host "  b) Only Python venv + deps"
        Write-Host "  c) Only GUI+TUI node deps"
        Write-Host "  d) Only .env seed"
        Write-Host "  s) Skip - do nothing now"
        $choice = "a"
        if (-not ($Force -or $Quiet)) { $choice = Read-Host "Choice [a/b/c/d/s]" }
        switch ($choice.ToLower()) {
            "a" { Install-Deps; Install-NodeDeps; Seed-Env }
            "b" { Install-Deps }
            "c" { Install-NodeDeps }
            "d" { Seed-Env }
            default { Write-Host "Skipping installs." }
        }
        $probe = Check-Backend
        Show-Go-Summary $probe
    } else {
        Write-Ok "Nothing missing - all components present."
    }
}

# ---------------------------------------------------------------------------
# Action dispatch
# ---------------------------------------------------------------------------
switch ($Action.ToLower()) {
    "setup"   { }
    "install" { }
    "update" {
        Update-Deps
        if (-not $SkipNode) { Install-NodeDeps }
        Write-Host "[update] Deps updated."
        exit 0
    }
    "restart" {
        Restart-Server
        Write-Host "[restart] Done."
        exit 0
    }
    "configure" {
        Write-Step "Opening interactive setup wizard..."
        & (Get-Python) -m nexus --setup
        Write-Host "[configure] Done. Run .\nexus.cmd to launch."
        exit 0
    }
    "doctor" { Show-Doctor; exit 0 }
    "status" { Show-Status; exit 0 }
    "check" { Do-Check; exit 0 }
}

# install / setup / reinstall / fresh flow
if ($Action -in "reinstall", "fresh") {
    Write-Host "[reinstall] Recreating venv + deps"
    if (-not (Confirm-Yes "This wipes .venv. Continue?")) { Write-Host "Aborted."; exit 1 }
    if (Test-Path $venvPy) {
        Write-Step "Removing old .venv..."
        Remove-Item (Split-Path $venvPy -Parent | Split-Path -Parent) -Recurse -Force
    }
    Install-Deps
    Install-NodeDeps
    Seed-Env
    $probe = Check-Backend
    Show-Go-Summary $probe
    exit 0
}

Write-Host "[1/5] Python/deps"
Install-Deps
Write-Host "[2/5] Node deps"
Install-NodeDeps
Write-Host "[3/5] .env"
Seed-Env
Write-Host "[4/5] Backend check"
$probe = Check-Backend
Write-Host "[5/5] Summary"
Show-Go-Summary $probe
