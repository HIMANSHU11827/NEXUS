param(
    [ValidateSet("all", "server", "gui", "tui")]
    [string]$Mode = "all",
    [switch]$NoBuild,
    [switch]$Help
)

if ($Help) {
    Write-Host "NEXUS AI — Launch Script"
    Write-Host ""
    Write-Host "Usage: .\run.ps1 [-Mode <all|server|gui|tui>] [-NoBuild] [-Help]"
    Write-Host ""
    Write-Host "  -Mode all     Start backend + GUI (default)"
    Write-Host "  -Mode server  Start backend only"
    Write-Host "  -Mode gui     Start GUI dev server only"
    Write-Host "  -Mode tui     Start TUI only"
    Write-Host "  -NoBuild      Skip GUI production build check"
    exit 0
}

$Root = $PSScriptRoot
$LogDir = Join-Path $Root "logs"
$null = New-Item -ItemType Directory -Force -Path $LogDir

function Write-Status {
    param([string]$Label, [string]$Message)
    $ts = Get-Date -Format "HH:mm:ss"
    Write-Host "[$ts] [$Label] $Message"
}

function Wait-ForHealth {
    param([int]$Port = 8000, [int]$TimeoutSeconds = 30)
    $started = Get-Date
    while ((Get-Date) -lt $started.AddSeconds($TimeoutSeconds)) {
        try {
            $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -ErrorAction Stop
            if ($r.status -eq "ok") {
                Write-Status "OK" "Backend is healthy on port $Port"
                return $true
            }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    Write-Status "FAIL" "Backend did not become healthy within ${TimeoutSeconds}s"
    return $false
}

function Start-Server {
    Write-Status "SERVER" "Starting backend..."
    $log = Join-Path $LogDir "server_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
    $proc = Start-Process -NoNewWindow -FilePath "python" -ArgumentList "-m server" `
        -RedirectStandardOutput $log -RedirectStandardError $log -PassThru
    Write-Status "SERVER" "PID $($proc.Id), log: $log"
    return $proc
}

function Start-Gui {
    Write-Status "GUI" "Starting dev server..."
    Set-Location -LiteralPath (Join-Path $Root "gui")
    $proc = Start-Process -NoNewWindow -FilePath "npm" -ArgumentList "run dev" -PassThru
    Set-Location -LiteralPath $Root
    Write-Status "GUI" "PID $($proc.Id) on port 5173"
    return $proc
}

function Start-Tui {
    Write-Status "TUI" "Starting TUI..."
    $proc = Start-Process -NoNewWindow -FilePath "python" -ArgumentList "-m nexus" -PassThru
    Write-Status "TUI" "PID $($proc.Id)"
    return $proc
}

# Kill only processes holding our ports (not all Python processes)
function Stop-PortOwner {
    param([int]$Port)
    try {
        $owner = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique
        if ($owner) {
            Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue
        }
    } catch {}
}
Stop-PortOwner 8000
Stop-PortOwner 5173
Start-Sleep -Seconds 1

$procs = @()

if ($Mode -in "all", "server") {
    $proc = Start-Server
    $procs += $proc
    $ok = Wait-ForHealth
    if (-not $ok) {
        Write-Status "FAIL" "Server failed to start, exiting"
        $procs | ForEach-Object { $_.Kill() 2>$null }
        exit 1
    }
}

if ($Mode -in "all", "gui") {
    if (-not $NoBuild) {
        Write-Status "GUI" "Running production build check..."
        Set-Location -LiteralPath (Join-Path $Root "gui")
        npm run build 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Status "FAIL" "GUI build failed"
        } else {
            Write-Status "OK" "GUI build passes"
        }
        Set-Location -LiteralPath $Root
    }
    $procs += Start-Gui
}

if ($Mode -eq "tui") {
    $procs += Start-Tui
}

$urls = @{}
if ($Mode -in "all", "server") { $urls["Backend"] = "http://127.0.0.1:8000" }
if ($Mode -in "all", "gui") { $urls["GUI"] = "http://127.0.0.1:5173" }
if ($Mode -eq "tui") { $urls["TUI"] = "TUI (python -m nexus)" }

Write-Host ""
Write-Host "╔══════════════════════════════════════════╗"
Write-Host "║        NEXUS AI — Running                ║"
Write-Host "╠══════════════════════════════════════════╣"
$urls.GetEnumerator() | Sort-Object Key | ForEach-Object {
    Write-Host "║  $($_.Key): $($_.Value.PadRight(30))║"
}
Write-Host "╚══════════════════════════════════════════╝"
Write-Host "Press Ctrl+C to stop all processes"
Write-Host ""

try {
    $procs | ForEach-Object { $_.WaitForExit() }
} finally {
    Write-Status "STOP" "Shutting down..."
    $procs | ForEach-Object {
        if (-not $_.HasExited) { $_.Kill() 2>$null }
    }
}
