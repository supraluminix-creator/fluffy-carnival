param(
    [string]$PidFile = ".\\run\\api.pid"
)

try {
    if (-not (Test-Path $PidFile)) {
        Write-Host "[stop_api] No PID file found at $PidFile" -ForegroundColor DarkYellow
        exit 0
    }
    $targetPid = Get-Content -Path $PidFile | Select-Object -First 1
    if (-not $targetPid) {
        Write-Host "[stop_api] PID file empty: $PidFile" -ForegroundColor DarkYellow
        exit 0
    }
    $proc = Get-Process -Id $targetPid -ErrorAction SilentlyContinue
    if (-not $proc) {
        Write-Host "[stop_api] No process with PID=$targetPid" -ForegroundColor DarkYellow
        Remove-Item -Path $PidFile -ErrorAction SilentlyContinue
        exit 0
    }
    Write-Host "[stop_api] Stopping process PID=$targetPid..." -ForegroundColor Yellow
    Stop-Process -Id $targetPid -Force
    Start-Sleep -Seconds 1
    if (Get-Process -Id $targetPid -ErrorAction SilentlyContinue) {
        Write-Warning "[stop_api] Process still running (PID=$targetPid)." 
    } else {
        Write-Host "[stop_api] Stopped. Removing PID file." -ForegroundColor Green
        Remove-Item -Path $PidFile -Force -ErrorAction SilentlyContinue
    }
} catch {
    Write-Warning "[stop_api] Error: $($_.Exception.Message)"
}
