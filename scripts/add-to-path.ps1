$nexusDir = "C:\Users\himan\Desktop\NEXUS AI"
$path = [Environment]::GetEnvironmentVariable("Path", "User")
if ($path -notlike "*$nexusDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$path;$nexusDir", "User")
    Write-Host "Added NEXUS AI to user PATH. Restart your terminal."
} else {
    Write-Host "NEXUS AI is already in PATH."
}
