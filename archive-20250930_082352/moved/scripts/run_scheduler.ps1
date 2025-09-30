param(
    [string]$MetricsPort = "9300",
    [string]$SchedulerConfig = "scheduler/jobs.yaml",
    [switch]$RunJobsAtStart,
    [int]$HeartbeatSecs = 60,
    [string]$RunId = "",
    [string]$HealthPort = "9310",
    [switch]$DisableHealth,
    [string]$AppVersion = "",
    [string]$GitSha = "",
    # Bybit WS sidecar options
    [switch]$BybitWsAutostart,
    [string]$BybitWsPort = "8000",
    [string]$BybitWsHealthPort = "",
    [string]$BybitWsSymbols = "BTCUSDT,ETHUSDT",
    [string]$BybitWsDb = "",
    [string]$BybitWsParquetDir = ""
)

# Set working directory to script location
Set-Location -Path (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location ..

$env:ENABLE_METRICS = "1"
$env:METRICS_PORT = $MetricsPort
$env:ENABLE_HEALTH = $(if ($DisableHealth) { "0" } else { "1" })
$env:HEALTH_PORT = $HealthPort
$env:SCHEDULER_CONFIG = $SchedulerConfig
if ($RunJobsAtStart) { $env:RUN_JOBS_AT_START = "1" } else { $env:RUN_JOBS_AT_START = "0" }
$env:HEARTBEAT_SECS = "$HeartbeatSecs"
if ($RunId -ne "") { $env:RUN_ID = $RunId }
if ($AppVersion -ne "") { $env:APP_VERSION = $AppVersion }
if ($GitSha -ne "") { $env:GIT_SHA = $GitSha }

# Bybit WS sidecar env
if ($BybitWsAutostart) { $env:BYBIT_WS_AUTOSTART = "1" } else { $env:BYBIT_WS_AUTOSTART = "0" }
if ($BybitWsPort -ne "") { $env:BYBIT_WS_PORT = $BybitWsPort }
if ($BybitWsHealthPort -ne "") { $env:BYBIT_WS_HEALTH_PORT = $BybitWsHealthPort }
if ($BybitWsSymbols -ne "") { $env:BYBIT_WS_SYMBOLS = $BybitWsSymbols }
if ($BybitWsDb -ne "") { $env:BYBIT_WS_DB = $BybitWsDb }
if ($BybitWsParquetDir -ne "") { $env:BYBIT_WS_PARQUET_DIR = $BybitWsParquetDir }

Write-Host "Launching scheduler with metrics on port $MetricsPort and health on port $HealthPort..."
Write-Host "RUN_JOBS_AT_START=$($env:RUN_JOBS_AT_START) HEARTBEAT_SECS=$HeartbeatSecs"
if ($env:BYBIT_WS_AUTOSTART -eq "1") {
    $hp = if ($env:BYBIT_WS_HEALTH_PORT -and $env:BYBIT_WS_HEALTH_PORT -ne "") { $env:BYBIT_WS_HEALTH_PORT } else { $env:BYBIT_WS_PORT }
    Write-Host "BYBIT_WS_AUTOSTART=1 WS_PORT=$($env:BYBIT_WS_PORT) WS_HEALTH_PORT=$hp SYMBOLS=$($env:BYBIT_WS_SYMBOLS)"
}

# Prefer local venv python
$venvPython = Join-Path (Resolve-Path ".\").Path ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    & $venvPython .\main.py
} else {
    python .\main.py
}
