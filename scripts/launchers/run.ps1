param(
    [ValidateSet("all", "server", "gui", "tui")]
    [string]$Mode = "all",
    [switch]$NoBuild,
    [switch]$NoWatchdog,
    [switch]$NoWorker,
    [switch]$Help
)

if ($Help) {
    Write-Host "NEXUS AI - Launch Script"
    Write-Host ""
    Write-Host "Usage: .\run.ps1 [-Mode <all|server|gui|tui>] [-NoBuild] [-NoWatchdog] [-NoWorker] [-Help]"
    Write-Host ""
    Write-Host "  -Mode all     Start backend + GUI (default)"
    Write-Host "  -Mode server  Start backend only"
    Write-Host "  -Mode gui     Start GUI dev server only"
    Write-Host "  -Mode tui     Start TUI only"
    Write-Host "  -NoBuild      Skip GUI production build check"
    Write-Host "  -NoWatchdog   Do not restart a crashed server or GUI process"
    Write-Host "  -NoWorker     Keep the API worker external (use python -m nexus --autonomous separately)"
    exit 0
}

$Root = $PSScriptRoot
$LogDir = Join-Path $Root "logs"
$null = New-Item -ItemType Directory -Force -Path $LogDir

# Prefer the project venv when present; fall back to PATH python.
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$Python = if (Test-Path -LiteralPath $VenvPython) { $VenvPython } else { "python" }

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

function Test-BackendHealthy {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 3 -ErrorAction Stop
        return ($r.status -eq "ok")
    } catch {
        return $false
    }
}

function Start-DetachedProcess {
    param(
        [string]$FilePath,
        [string]$Arguments,
        [string]$WorkingDirectory
    )
    # Use the Windows shell launcher because this machine exposes both Path
    # and PATH. PowerShell Start-Process rejects that duplicate environment.
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $FilePath
    $startInfo.Arguments = $Arguments
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $true
    $startInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    return [System.Diagnostics.Process]::Start($startInfo)
}

function Start-Server {
    Write-Status "SERVER" "Starting backend..."
    # Local desktop use is loopback-only; the API middleware still rejects
    # non-loopback clients when this opt-in is enabled.
    $env:NEXUS_ALLOW_LOCAL_ANON = "true"
    # A single launcher invocation must also consume the durable queue.  Set
    # this before spawning the API so cron and queued work cannot accumulate
    # silently when the operator only starts the server.
    $env:NEXUS_EMBED_QUEUE_DRIVER = if ($NoWorker) { "false" } else { "true" }
    $proc = Start-DetachedProcess -FilePath $Python -Arguments "-m server" -WorkingDirectory $Root
    Write-Status "SERVER" "PID $($proc.Id)"
    return $proc
}

function Start-Gui {
    Write-Status "GUI" "Starting dev server..."
    $guiRoot = Join-Path $Root "gui"
    $proc = Start-DetachedProcess -FilePath "npm.cmd" -Arguments "run dev" -WorkingDirectory $guiRoot
    Write-Status "GUI" "PID $($proc.Id) on port 5173"
    return $proc
}

function Start-Tui {
    Write-Status "TUI" "Starting TUI..."
    $proc = Start-DetachedProcess -FilePath $Python -Arguments "-m nexus" -WorkingDirectory $Root
    Write-Status "TUI" "PID $($proc.Id)"
    return $proc
}

# Kill only processes holding our ports (not all Python processes).
function Stop-PortOwner {
    param([int]$Port)
    try {
        # Get-NetTCPConnection may be blocked by the desktop sandbox; netstat
        # still gives us the exact listener PID without broad process scans.
        $owners = & netstat.exe -ano -p tcp | ForEach-Object {
            if ($_ -match ("^\s*TCP\s+\S+:" + $Port + "\s+\S+\s+LISTENING\s+(\d+)\s*$")) {
                [int]$Matches[1]
            }
        } | Select-Object -Unique
        if ($owners) {
            $owners | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
        }
    } catch {}
}

if ($Mode -in "all", "server") { Stop-PortOwner 8000 }
if ($Mode -in "all", "gui") { Stop-PortOwner 5173 }
Start-Sleep -Seconds 1

$procs = @()

if ($Mode -in "all", "server") {
    $serverProc = Start-Server
    $procs += $serverProc
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
        Push-Location -LiteralPath (Join-Path $Root "gui")
        npm.cmd run build 2>&1 | Out-Null
        $buildExit = $LASTEXITCODE
        Pop-Location
        if ($buildExit -ne 0) {
            Write-Status "FAIL" "GUI build failed"
        } else {
            Write-Status "OK" "GUI build passes"
        }
    }
    $guiProc = Start-Gui
    $procs += $guiProc
}

if ($Mode -eq "tui") {
    $tuiProc = Start-Tui
    $procs += $tuiProc
}

$urls = @{}
if ($Mode -in "all", "server") { $urls["Backend"] = "http://127.0.0.1:8000" }
if ($Mode -in "all", "gui") { $urls["GUI"] = "http://127.0.0.1:5173" }
if ($Mode -eq "tui") { $urls["TUI"] = "TUI (python -m nexus)" }

Write-Host ""
Write-Host "============================================================"
Write-Host "                 NEXUS AI - Running"
Write-Host "------------------------------------------------------------"
$urls.GetEnumerator() | Sort-Object Key | ForEach-Object {
    Write-Host ("  {0}: {1}" -f $_.Key, $_.Value)
}
Write-Host "============================================================"
Write-Host "Press Ctrl+C to stop all processes"
Write-Host ""

try {
    if ($NoWatchdog -or $Mode -eq "tui") {
        $procs | ForEach-Object { $_.WaitForExit() }
    } else {
        Write-Status "WATCHDOG" "Monitoring child processes; crashed services will be restarted"
        $serverHealthFailures = 0
        $serverRestartDelay = 1
        while ($true) {
            if ($serverProc -and $serverProc.HasExited) {
                Write-Status "WATCHDOG" "Backend exited; restarting"
                Start-Sleep -Seconds $serverRestartDelay
                $serverProc = Start-Server
                $procs += $serverProc
                if (Wait-ForHealth) {
                    $serverHealthFailures = 0
                    $serverRestartDelay = 1
                } else {
                    Write-Status "WATCHDOG" "Backend restart is not healthy yet"
                    $serverRestartDelay = [Math]::Min($serverRestartDelay * 2, 30)
                }
            } elseif ($serverProc -and -not (Test-BackendHealthy)) {
                $serverHealthFailures++
                if ($serverHealthFailures -ge 3) {
                    Write-Status "WATCHDOG" "Backend is alive but unhealthy; restarting"
                    $serverProc.Kill()
                    $serverHealthFailures = 0
                }
            } elseif ($serverProc) {
                $serverHealthFailures = 0
                $serverRestartDelay = 1
            }
            if ($guiProc -and $guiProc.HasExited) {
                Write-Status "WATCHDOG" "GUI exited; restarting"
                $guiProc = Start-Gui
                $procs += $guiProc
            }
            Start-Sleep -Seconds 2
        }
    }
} finally {
    Write-Status "STOP" "Shutting down..."
    $procs | ForEach-Object {
        if ($_ -and -not $_.HasExited) { $_.Kill() 2>$null }
    }
}
