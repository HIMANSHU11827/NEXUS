param(
    [switch]$Warmup,
    [switch]$Text,
    [switch]$Manual,
    [switch]$Once,
    [switch]$NoSpeak
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$env:PYTHONIOENCODING = "utf-8"

$argsList = @("voice_chat.py")
if ($Warmup) { $argsList += "--warmup" }
if ($Text) { $argsList += "--text" }
if ($Manual) { $argsList += "--manual" }
if ($Once) { $argsList += "--once" }
if ($NoSpeak) { $argsList += "--no-speak" }

python @argsList
