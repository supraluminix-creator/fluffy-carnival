param(
    [Parameter(Mandatory=$true)][string]$App,
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$Reload,
    [int]$Workers = 1,
    [string]$LogLevel = "info",
    [switch]$Detach,
    [string]$PidFile
)

# Resolve python executable in local venv if present
$python = Join-Path -Path (Resolve-Path ".").Path -ChildPath ".venv\\Scripts\\python.exe"
if (-Not (Test-Path $python)) {
    $python = "python"
}

$uvArgs = @("-m", "uvicorn", $App, "--host", $BindHost, "--port", $Port, "--log-level", $LogLevel)
if ($Reload) { $uvArgs += "--reload" }

# Windows ne supporte pas --workers > 1 de manière fiable (SO_REUSEPORT non disponible)
$isWindowsOS = $env:OS -like "*Windows*"
if ($Workers -gt 1 -and -Not $Reload) {
    if ($isWindowsOS) {
        Write-Warning "Uvicorn multi-workers n'est pas supporté sur Windows. Fallback vers Workers=1."
        $Workers = 1
    }
}
if ($Workers -gt 1 -and -Not $Reload) { $uvArgs += @("--workers", $Workers) }

if ($Detach) {
    # Run in background and optionally write PID file
    $argList = $uvArgs
    Write-Host "Launching (detached): $python $($argList -join ' ')" -ForegroundColor Cyan
    $p = Start-Process -FilePath $python -ArgumentList $argList -PassThru -WindowStyle Hidden
    if ($PidFile) {
        try {
            $pidDir = Split-Path -Path $PidFile -Parent
            if ($pidDir -and -not (Test-Path $pidDir)) { New-Item -ItemType Directory -Path $pidDir | Out-Null }
            Set-Content -Path $PidFile -Value $p.Id
            Write-Host "[run_uvicorn] PID saved to $PidFile (PID=$($p.Id))" -ForegroundColor DarkYellow
        } catch {
            Write-Warning "Failed to write PID file: $($_.Exception.Message)"
        }
    } else {
        Write-Host "[run_uvicorn] Started background process PID=$($p.Id)" -ForegroundColor DarkYellow
    }
    # In detached mode we cannot capture exit code here; assume success.
    exit 0
} else {
    Write-Host "Launching: $python $($uvArgs -join ' ')" -ForegroundColor Cyan
    & $python $uvArgs

    if ($LASTEXITCODE -ne 0) {
        Write-Error "Uvicorn exited with code $LASTEXITCODE"
        exit $LASTEXITCODE
    }
}
