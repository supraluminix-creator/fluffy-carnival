param(
    [string]$TargetHost = "127.0.0.1",
    [int]$Port = 8000,
    [string]$ApiKey
)

function Invoke-JsonGet {
    param([string]$Path)
    try {
    $base = "http://${TargetHost}:$Port"
    $url = "$base$Path"
        $resp = Invoke-WebRequest -Uri $url -Method GET -UseBasicParsing
        Write-Host "GET $Path -> $($resp.StatusCode)" -ForegroundColor Green
        if ($resp.Headers["X-Request-ID"]) {
            Write-Host "  X-Request-ID: $($resp.Headers["X-Request-ID"])" -ForegroundColor DarkGray
        }
        if ($resp.Content) {
            try { ($resp.Content | ConvertFrom-Json) | ConvertTo-Json -Depth 5 } catch { $resp.Content }
        }
    }
    catch {
        Write-Warning "GET $Path failed: $($_.Exception.Message)"
    }
}

function Invoke-JsonPost {
    param([string]$Path, [hashtable]$Body)
    $base = "http://${TargetHost}:$Port"
    $url = "$base$Path"
    $headers = @{"Content-Type"="application/json"}
    if ($ApiKey) { $headers["X-API-KEY"] = $ApiKey }
    try {
        $json = $Body | ConvertTo-Json -Depth 10
        $resp = Invoke-WebRequest -Uri $url -Method POST -Headers $headers -Body $json -UseBasicParsing
        Write-Host "POST $Path -> $($resp.StatusCode)" -ForegroundColor Green
        Write-Host "  X-RateLimit-Limit: $($resp.Headers["X-RateLimit-Limit"])" -ForegroundColor DarkGray
        Write-Host "  X-RateLimit-Remaining: $($resp.Headers["X-RateLimit-Remaining"])" -ForegroundColor DarkGray
        Write-Host "  X-RateLimit-Reset: $($resp.Headers["X-RateLimit-Reset"])" -ForegroundColor DarkGray
        if ($resp.Content) {
            try { ($resp.Content | ConvertFrom-Json) | ConvertTo-Json -Depth 5 } catch { $resp.Content }
        }
    }
    catch {
        if ($_.Exception.Response) {
            $code = $_.Exception.Response.StatusCode.value__
            Write-Warning "POST $Path failed: HTTP $code"
            $retry = $_.Exception.Response.Headers["Retry-After"]
            if ($retry) { Write-Host "  Retry-After: $retry" -ForegroundColor DarkGray }
        } else {
            Write-Warning "POST $Path failed: $($_.Exception.Message)"
        }
    }
}

Write-Host "[smoke] Target http://${TargetHost}:$Port" -ForegroundColor Yellow

# 1) Health & index
Invoke-JsonGet -Path "/api/health"
Invoke-JsonGet -Path "/api"

# 2) LLM status
Invoke-JsonGet -Path "/api/llm/status"

# 3) X-Request-ID echo test
try {
    $reqId = "abc123"
    $base = "http://${TargetHost}:$Port"
    $url = "$base/api/health"
    $resp = Invoke-WebRequest -Uri $url -Method GET -Headers @{"X-Request-ID"=$reqId} -UseBasicParsing
    Write-Host "GET /api/health (with X-Request-ID) -> $($resp.StatusCode)" -ForegroundColor Green
    Write-Host "  X-Request-ID (echo): $($resp.Headers['X-Request-ID'])" -ForegroundColor DarkGray
} catch { Write-Warning "Request-ID test failed: $($_.Exception.Message)" }

# 4) POST generate (if ApiKey provided)
if ($ApiKey) {
    Invoke-JsonPost -Path "/api/llm/generate" -Body @{ prompt = "hello from smoke" }
} else {
    Write-Host "[smoke] No ApiKey provided; skipping POST tests." -ForegroundColor DarkYellow
}

# 5) SSE stream via curl.exe if available and ApiKey
if ($ApiKey) {
    $curl = (Get-Command curl.exe -ErrorAction SilentlyContinue)
    if ($curl) {
        Write-Host "[smoke] SSE /api/llm/stream (first lines)" -ForegroundColor Yellow
        $base = "http://${TargetHost}:$Port"
        $tmp = Join-Path $env:TEMP "sse_body.json"
        Set-Content -Path $tmp -Value '{"prompt":"hello stream from smoke"}' -NoNewline
        $cmd = 'curl.exe -i -N -H "X-API-KEY: ' + $ApiKey + '" -H "Content-Type: application/json" --max-time 5 --data "@' + $tmp + '" ' + $base + '/api/llm/stream'
        cmd /c $cmd | Select-Object -First 15
    } else {
        Write-Host "[smoke] curl.exe not found; skipping SSE test." -ForegroundColor DarkYellow
    }
}

Write-Host "[smoke] Done." -ForegroundColor Green
