param(
    [string]$Symbols = "BTCUSDT,ETHUSDT",
    [int]$PrometheusPort = 8000,
    [int]$HealthPort = 8100,
    [string]$Db = "data/crypto.db",
    [string]$ParquetDir = "data/bybit_liquidations",
    [int]$FlushSize = 100,
    [int]$FlushInterval = 5,
    [string]$WsUrl = ""
)

# Set working directory to script location then repo root
Set-Location -Path (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location ..

Write-Host "Launching Bybit WS sidecar..."
Write-Host "SYMBOLS=$Symbols PROM_PORT=$PrometheusPort HEALTH_PORT=$HealthPort DB=$Db PARQUET=$ParquetDir"

$argsList = @(
    "-m", "pipeline.collectors.bybit_ws",
    "--symbols", $Symbols,
    "--prometheus-port", $PrometheusPort,
    "--health-port", $HealthPort,
    "--db", $Db,
    "--parquet-dir", $ParquetDir,
    "--flush-size", $FlushSize,
    "--flush-interval", $FlushInterval
)
if ($WsUrl -ne "") {
    $argsList += @("--ws-url", $WsUrl)
}

# Prefer local venv python
$venvPython = Join-Path (Resolve-Path ".\").Path ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    & $venvPython @argsList
} else {
    python @argsList
}
