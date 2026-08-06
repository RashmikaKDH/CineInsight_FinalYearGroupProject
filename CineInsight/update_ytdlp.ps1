# CineInsight - Daily yt-dlp Auto-Updater
# This script updates yt-dlp inside the project's .venv automatically.

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPip = Join-Path $projectRoot ".venv\Scripts\pip.exe"
$logFile = Join-Path $projectRoot "ytdlp_update.log"

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

if (-Not (Test-Path $venvPip)) {
    Add-Content -Path $logFile -Value "[$timestamp] ERROR: pip not found at $venvPip"
    exit 1
}

$output = & $venvPip install -U yt-dlp 2>&1
Add-Content -Path $logFile -Value "[$timestamp] $output"
Write-Host "yt-dlp updated. See ytdlp_update.log for details."
