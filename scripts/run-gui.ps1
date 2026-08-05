param(
  [int]$ApiPort = 8000,
  [int]$WebPort = 5173
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$Gui = Join-Path $Root "gui"
$Logs = Join-Path $Root "logs"
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
  $VenvPython = "python.exe"
}
New-Item -ItemType Directory -Force -Path $Logs | Out-Null
$RunStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$ApiOutLog = Join-Path $Logs "gui-api-$RunStamp.out.log"
$ApiErrLog = Join-Path $Logs "gui-api-$RunStamp.err.log"
$ViteOutLog = Join-Path $Logs "gui-vite-$RunStamp.out.log"
$ViteErrLog = Join-Path $Logs "gui-vite-$RunStamp.err.log"

# Detached processes do not reliably receive newly-created user environment
# variables through WMI. Import provider secrets from the current user's
# environment before spawning the API so ${DEEPSEEK_API_KEY}, OPENROUTER_API_KEY,
# and other configured provider references reach the actual server process.
foreach ($secretName in @(
  "DEEPSEEK_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY",
  "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "XAI_API_KEY"
)) {
  if (-not [Environment]::GetEnvironmentVariable($secretName, "Process")) {
    $userSecret = [Environment]::GetEnvironmentVariable($secretName, "User")
    if ($userSecret) { Set-Item -Path "Env:$secretName" -Value $userSecret }
  }
}

function Stop-PortOwner {
  param([int]$Port)
  $owners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
  foreach ($owner in $owners) {
    if ($owner) {
      Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue
    }
  }
}

function Wait-HttpOk {
  param(
    [string]$Url,
    [int]$Seconds = 30
  )
  $deadline = (Get-Date).AddSeconds($Seconds)
  do {
    try {
      $status = & curl.exe --silent --output NUL --max-time 20 --write-out "%{http_code}" $Url
      $statusCode = [int]$status
      if ($statusCode -ge 200 -and $statusCode -lt 500) {
        return $true
      }
    } catch {
      Start-Sleep -Milliseconds 700
    }
  } while ((Get-Date) -lt $deadline)
  return $false
}

Write-Host "Stopping stale gui processes..." -ForegroundColor Yellow
Stop-PortOwner -Port $ApiPort
Stop-PortOwner -Port $WebPort
Start-Sleep -Seconds 1

Write-Host "Starting NEXUS API on http://127.0.0.1:$ApiPort ..." -ForegroundColor Cyan
$OldPythonHome = $env:PYTHONHOME
$OldPythonPath = $env:PYTHONPATH
try {
  Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
  Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
  $apiArgs = @('-m', 'uvicorn', 'server:app', '--host', '127.0.0.1', '--port', [string]$ApiPort)
  Start-Process -FilePath $VenvPython -ArgumentList $apiArgs -WorkingDirectory $Root -RedirectStandardOutput $ApiOutLog -RedirectStandardError $ApiErrLog -WindowStyle Hidden | Out-Null
} finally {
  if ($null -ne $OldPythonHome) { $env:PYTHONHOME = $OldPythonHome } else { Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue }
  if ($null -ne $OldPythonPath) { $env:PYTHONPATH = $OldPythonPath } else { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
}

if (-not (Wait-HttpOk -Url "http://127.0.0.1:$ApiPort/api/health" -Seconds 20)) {
  Write-Host "API health check failed. Last backend errors:" -ForegroundColor Red
  Get-Content $ApiErrLog -Tail 40 -ErrorAction SilentlyContinue
  exit 1
}

if (-not (Wait-HttpOk -Url "http://127.0.0.1:$ApiPort/api/state" -Seconds 90)) {
  Write-Host "API did not become healthy. Last backend errors:" -ForegroundColor Red
  Get-Content $ApiErrLog -Tail 40 -ErrorAction SilentlyContinue
  exit 1
}

Write-Host "Starting GUI on http://127.0.0.1:$WebPort ..." -ForegroundColor Cyan
$viteArgs = @('run', 'dev', '--', '--host', '127.0.0.1', '--port', [string]$WebPort)
Start-Process -FilePath 'npm.cmd' -ArgumentList $viteArgs -WorkingDirectory $Gui -RedirectStandardOutput $ViteOutLog -RedirectStandardError $ViteErrLog -WindowStyle Hidden | Out-Null

if (-not (Wait-HttpOk -Url "http://127.0.0.1:$WebPort" -Seconds 60)) {
  Write-Host "Frontend did not become healthy." -ForegroundColor Red
  Get-Content $ViteErrLog -Tail 40 -ErrorAction SilentlyContinue
  exit 1
}

Write-Host "NEXUS GUI is ready: http://127.0.0.1:$WebPort" -ForegroundColor Green
Write-Host "Logs: $ApiErrLog / $ViteErrLog" -ForegroundColor DarkGray
