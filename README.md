# new_crypto_prodsafe

[![CI](https://github.com/supraluminix-creator/fluffy-carnival/actions/workflows/ci.yml/badge.svg)](https://github.com/supraluminix-creator/fluffy-carnival/actions/workflows/ci.yml)

Prod-safe crypto monitor with:
- Central scheduler (APScheduler) with jitter
- Parallel orchestrator
- YAML-driven job configuration

Note: This repository is published as "fluffy-carnival" on GitHub.

## Quick start (Windows / PowerShell)

Prerequisites:
- Python 3.12
- Create and activate the venv, install deps (already in this repo)

### 1) Scheduler mode

```powershell
Set-Location "C:\\Users\\To the moon\\Downloads\\new_crypto_prodsafe"
$env:CRYPTO_MONITOR_MODE = "scheduler"
.\\.venv\\Scripts\\python.exe .\\main.py
```

There is no API server in this build; everything runs headless from the scheduler.

## YAML-driven jobs

Edit `scheduler/jobs.yaml` to enable/disable jobs and set intervals. We added args and kwargs support and allow `${ENV}` substitution for secrets.

Example entries:

```yaml
jobs:
  - id: macro
    every: 5m
    func: pipeline.collectors.market:fetch_macro
    enabled: true
    args: ["bitcoin"]
    kwargs:
      cmc_api_key: ${CMC_API_KEY}
```

Supported time units: ms, s, m, h, d.

## Windows caveats

- Stop background scripts that might lock resources you need.

## Dev and Tests

```powershell
Set-Location "C:\\Users\\To the moon\\Downloads\\new_crypto_prodsafe"
.\\.venv\\Scripts\\python.exe -m pytest -q
```


## Observability & Ops

Environment variables:

- ENABLE_SCHEDULER=1 — Enable the YAML-driven scheduler (default 1)
- SCHEDULER_CONFIG=scheduler/jobs.yaml — YAML config path
- RUN_JOBS_AT_START=1 — Run all jobs immediately at startup (default 1)
- HEARTBEAT_SECS=60 — Heartbeat interval in seconds
- RUN_ID — Correlation id for logs/CSV/metrics
- ENABLE_METRICS=1 — Start Prometheus metrics server
- METRICS_PORT=9300 — Metrics port
- ENABLE_HEALTH=1 — Start lightweight health HTTP server (default 1)
- HEALTH_PORT=9310 — Health server port
- APP_VERSION — App version (exposed in metrics)
- GIT_SHA — Git commit SHA (exposed in metrics)

Endpoints:

- Prometheus metrics: http://localhost:9300/metrics
  - crypto_ready, crypto_ready_timestamp, crypto_build_info, crypto_task_*

- Health JSON: http://localhost:9310/health (aliases: /ready, /live)
  - Payload includes run_id, jobs, started_at, ready, ready_ts, tasks ok/err, build {version, git_sha, run_id}, ports {metrics, health}, config_path

- Minimal readiness (text): http://localhost:9310/metrics/ready
  - Example body:
    ready 1
    ready_timestamp 1726640000

Helper script (PowerShell):

```powershell
./scripts/run_scheduler.ps1 -MetricsPort 9300 -HealthPort 9310 -RunJobsAtStart -HeartbeatSecs 60 -RunId RUN123 -AppVersion 1.2.3 -GitSha abcdef0
```

## Contributing and PR workflow

- See the action plan with sprint breakdown: `improvements/action_plan.md`
- Follow the PR template: `.github/pull_request_template.md`
- Prototype of a tiny PR (test-first): `improvements/prototype/README.md` and `improvements/prototype/test_stub.py`
