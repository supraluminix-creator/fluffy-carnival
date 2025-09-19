param(
    [string]$MetricsPort = "9300",
    [string]$SchedulerConfig = "scheduler/jobs.yaml",
    [switch]$RunJobsAtStart,
    [int]$HeartbeatSecs = 60,
    [string]$RunId = "",
    [string]$HealthPort = "9310",
    [switch]$DisableHealth,
    [string]$AppVersion = "",
    [string]$GitSha = ""
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

Write-Host "Launching scheduler with metrics on port $MetricsPort and health on port $HealthPort..."
Write-Host "RUN_JOBS_AT_START=$($env:RUN_JOBS_AT_START) HEARTBEAT_SECS=$HeartbeatSecs"

# Prefer local venv python
$venvPython = Join-Path (Resolve-Path ".\").Path ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    & $venvPython .\main.py
} else {
    python .\main.py
}
