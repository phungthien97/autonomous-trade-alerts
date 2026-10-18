# Check OVH live/paper bot status from this PC.
# Double-click: Desktop\Check Bot Status.bat
# Or PowerShell:  .\deploy\ibgateway\check_bot.ps1

$ErrorActionPreference = "Stop"
$key = Join-Path $env:USERPROFILE ".ssh\ssh-key-2026-10-01.key"
$hostName = "ubuntu@15.235.62.2"
$remoteCmd = "bash /opt/autonomous-trade-alerts/deploy/ibgateway/status.sh"

Write-Host ""
Write-Host "Connecting to OVH bot host..." -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $key)) {
    Write-Host "ERROR: SSH key not found:" -ForegroundColor Red
    Write-Host "  $key"
    Write-Host ""
    Write-Host "Press Enter to close..."
    [void][Console]::ReadLine()
    exit 1
}

try {
    ssh -i $key -o BatchMode=yes -o ConnectTimeout=20 $hostName $remoteCmd
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "SSH/status exited with code $LASTEXITCODE" -ForegroundColor Yellow
    }
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""
Write-Host "Press Enter to close..."
[void][Console]::ReadLine()
