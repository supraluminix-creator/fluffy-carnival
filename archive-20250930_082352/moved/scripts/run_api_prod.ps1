param(
    [string]$BindHost = "0.0.0.0",
    [int]$Port = 8000,
    [int]$Workers = 4,
    [string]$App = "pipeline.api:app",
    [string]$LogLevel = "info",
    [string]$ApiWriteKey,
    [switch]$AutoPort,
    [int]$MaxPortAttempts = 5,
    [switch]$Detach,
    [string]$PidFile
)

$here = Resolve-Path "."
Write-Host "[run_api_prod] Using app=$App host=$BindHost port=$Port workers=$Workers" -ForegroundColor Yellow

$attempt = 0
while ($true) {
    if ($ApiWriteKey) {
        $env:API_WRITE_KEY = $ApiWriteKey
        Write-Host "[run_api_prod] API_WRITE_KEY provided (length=$($ApiWriteKey.Length))" -ForegroundColor DarkYellow
    }
    $params = @{ App = $App; BindHost = $BindHost; Port = $Port; Workers = $Workers; LogLevel = $LogLevel }
    if ($Detach) { $params.Detach = $true }
    if ($PidFile) { $params.PidFile = $PidFile }
    & "$here\scripts\run_uvicorn.ps1" @params

    if ($LASTEXITCODE -eq 0) {
        if ($Detach) {
            Write-Host "[run_api_prod] Launched in background on http://${BindHost}:${Port}" -ForegroundColor Green
            if ($PidFile) { Write-Host "[run_api_prod] PID file: $PidFile" -ForegroundColor DarkYellow }
            break
        } else {
            break
        }
    }

    if (-not $AutoPort -or $attempt -ge ($MaxPortAttempts - 1)) {
        exit $LASTEXITCODE
    }

    $attempt++
    $Port++
    Write-Warning "[run_api_prod] Launch failed (code=$LASTEXITCODE). Retrying on next port: $Port ($attempt/$MaxPortAttempts)"
}
