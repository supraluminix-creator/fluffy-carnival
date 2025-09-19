import asyncio
import importlib
import json
import os
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from random import uniform
from typing import Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

try:
    import yaml  # type: ignore
except Exception:  # noqa: BLE001
    yaml = None  # type: ignore

log = structlog.get_logger(__name__)

# --- Prometheus metrics (optional) ---
_PROM_AVAILABLE = False
try:
    from prometheus_client import Counter, Gauge, Histogram  # type: ignore
    try:
        # Info is available in newer prometheus_client versions
        from prometheus_client import Info  # type: ignore

        _HAS_INFO = True
    except Exception:  # noqa: BLE001
        Info = None  # type: ignore
        _HAS_INFO = False

    CRYPTO_TASK_START = Counter(
        "crypto_task_start_total",
        "Number of task starts",
        labelnames=("task",),
    )
    CRYPTO_TASK_OK = Counter(
        "crypto_task_ok_total",
        "Number of task successes",
        labelnames=("task",),
    )
    CRYPTO_TASK_ERR = Counter(
        "crypto_task_error_total",
        "Number of task errors",
        labelnames=("task",),
    )
    CRYPTO_TASK_DURATION = Histogram(
        "crypto_task_duration_seconds",
        "Task duration in seconds",
        labelnames=("task",),
        buckets=(
            0.001,
            0.005,
            0.01,
            0.05,
            0.1,
            0.25,
            0.5,
            1,
            2.5,
            5,
            10,
            30,
            60,
            120,
            300,
        ),
    )
    CRYPTO_TASK_ERROR_RATE = Gauge(
        "crypto_task_error_rate",
        "Error rate per task (0..1)",
        labelnames=("task",),
    )
    CRYPTO_READY = Gauge(
        "crypto_ready",
        "Process readiness: 1 after first successful task",
    )
    CRYPTO_READY_TS = Gauge(
        "crypto_ready_timestamp",
        "Unix epoch seconds when process became ready",
    )
    # Build info (labels: version, git_sha, run_id)
    if _HAS_INFO and Info is not None:
        CRYPTO_BUILD_INFO = Info(
            "crypto_build_info",
            "Build and runtime info",
        )
    else:
        CRYPTO_BUILD_INFO = Gauge(
            "crypto_build_info",
            "Build and runtime info (value is always 1)",
            labelnames=("version", "git_sha", "run_id"),
        )
    _PROM_AVAILABLE = True
except Exception:  # noqa: BLE001
    # Metrics library not installed; metrics will be disabled gracefully
    CRYPTO_TASK_START = None  # type: ignore
    CRYPTO_TASK_OK = None  # type: ignore
    CRYPTO_TASK_ERR = None  # type: ignore
    CRYPTO_TASK_DURATION = None  # type: ignore
    CRYPTO_TASK_ERROR_RATE = None  # type: ignore
    CRYPTO_READY = None  # type: ignore
    CRYPTO_READY_TS = None  # type: ignore
    CRYPTO_BUILD_INFO = None  # type: ignore

# In-memory counters for simple error-rate alerting
_ok_counts: dict[str, int] = defaultdict(int)
_err_counts: dict[str, int] = defaultdict(int)
_ERR_RATE_WARN = float(os.getenv("TASK_ERROR_RATE_WARN", "0.2"))
_ERR_RATE_MIN_COUNT = int(os.getenv("TASK_ERROR_RATE_MIN_COUNT", "5"))

# Timestamps/state
_STARTED_AT = datetime.now(UTC)
_READY_TS: float | None = None

# Build/runtime info
_BUILD_INFO: dict[str, str] = {
    "version": os.getenv("APP_VERSION", os.getenv("VERSION", "dev")),
    "git_sha": os.getenv("GIT_SHA", "unknown"),
    "run_id": os.getenv("RUN_ID", ""),
}

# --- Persistence for counters ---
_STATE_DIR = Path(os.getenv("STATE_DIR", "data"))
_STATE_DIR.mkdir(parents=True, exist_ok=True)
_STATE_FILE = _STATE_DIR / "scheduler_counters.json"


def _load_state() -> None:
    try:
        if _STATE_FILE.exists():
            with _STATE_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
            ok = data.get("ok", {})
            err = data.get("err", {})
            for k, v in ok.items():
                _ok_counts[k] = int(v)
            for k, v in err.items():
                _err_counts[k] = int(v)
            log.info(
                "counters_state_loaded",
                path=str(_STATE_FILE),
                tasks=len(_ok_counts),
            )
    except Exception as e:  # noqa: BLE001
        log.warning("counters_state_load_failed", error=str(e))


def _save_state() -> None:
    try:
        tmp = {
            "ok": _ok_counts,
            "err": _err_counts,
        }
        with _STATE_FILE.open("w", encoding="utf-8") as f:
            json.dump(tmp, f)
    except Exception as e:  # noqa: BLE001
        log.warning("counters_state_save_failed", error=str(e))


# Load state at module import
_load_state()


def _with_jitter(seconds: float) -> float:
    return max(1.0, seconds + uniform(-seconds * 0.05, seconds * 0.05))


async def task_wrapper(
    name: str,
    fn: Callable[..., Any],
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
) -> None:
    start = datetime.now(UTC)
    log.info("task_start", task=name, ts=start.isoformat())
    # Prometheus: increment start
    if _PROM_AVAILABLE and CRYPTO_TASK_START is not None:
        try:
            CRYPTO_TASK_START.labels(task=name).inc()
        except Exception:  # noqa: BLE001
            pass
    try:
        kwargs = kwargs or {}
        res = fn(*args, **kwargs)
        if asyncio.iscoroutine(res):
            await res
        log.info("task_ok", task=name)
        if _PROM_AVAILABLE and CRYPTO_TASK_OK is not None:
            try:
                CRYPTO_TASK_OK.labels(task=name).inc()
            except Exception:  # noqa: BLE001
                pass
        _ok_counts[name] += 1
        # Mark readiness after first success
        if (CRYPTO_READY is not None) or (CRYPTO_READY_TS is not None):
            try:
                if CRYPTO_READY is not None:
                    CRYPTO_READY.set(1)
                global _READY_TS  # noqa: PLW0603
                if _READY_TS is None:
                    _READY_TS = datetime.now(UTC).timestamp()
                    try:
                        log.info("ready", ready_ts=_READY_TS)
                    except Exception:  # noqa: BLE001
                        pass
                    if CRYPTO_READY_TS is not None:
                        CRYPTO_READY_TS.set(_READY_TS)
            except Exception:  # noqa: BLE001
                pass
    except Exception as e:  # pragma: no cover - sanity log
        log.error("task_err", task=name, error=str(e))
        if _PROM_AVAILABLE and CRYPTO_TASK_ERR is not None:
            try:
                CRYPTO_TASK_ERR.labels(task=name).inc()
            except Exception:  # noqa: BLE001
                pass
        _err_counts[name] += 1
    finally:
        end = datetime.now(UTC)
        duration = (end - start).total_seconds()
        log.info("task_end", task=name, duration=duration)
        if _PROM_AVAILABLE and CRYPTO_TASK_DURATION is not None:
            try:
                CRYPTO_TASK_DURATION.labels(task=name).observe(duration)
            except Exception:  # noqa: BLE001
                pass
        total = _ok_counts[name] + _err_counts[name]
        if total > 0:
            err_rate = _err_counts[name] / total
            if _PROM_AVAILABLE and CRYPTO_TASK_ERROR_RATE is not None:
                try:
                    CRYPTO_TASK_ERROR_RATE.labels(task=name).set(err_rate)
                except Exception:  # noqa: BLE001
                    pass
            if total >= _ERR_RATE_MIN_COUNT and err_rate >= _ERR_RATE_WARN:
                log.warning(
                    "task_error_rate_high",
                    task=name,
                    error_rate=round(err_rate, 3),
                    total=total,
                    ok=_ok_counts[name],
                    err=_err_counts[name],
                    threshold=_ERR_RATE_WARN,
                )
        _save_state()


def set_build_info(
    run_id: str | None = None,
    version: str | None = None,
    git_sha: str | None = None,
) -> None:
    """Set build/runtime info labels for metrics and cache locally.

    Safe to call even if prometheus client isn't available.
    """
    try:
        if run_id:
            _BUILD_INFO["run_id"] = run_id
        if version:
            _BUILD_INFO["version"] = version
        if git_sha:
            _BUILD_INFO["git_sha"] = git_sha
        if _PROM_AVAILABLE and CRYPTO_BUILD_INFO is not None:
            try:
                if hasattr(CRYPTO_BUILD_INFO, "info"):
                    CRYPTO_BUILD_INFO.info(dict(_BUILD_INFO))  # type: ignore[attr-defined]
                else:
                    CRYPTO_BUILD_INFO.labels(
                        version=_BUILD_INFO["version"],
                        git_sha=_BUILD_INFO["git_sha"],
                        run_id=_BUILD_INFO["run_id"],
                    ).set(1)  # type: ignore[call-arg]
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass


def get_status_snapshot() -> dict[str, Any]:
    """Return current runtime status suitable for a /health endpoint."""
    try:
        started_iso = _STARTED_AT.isoformat() + "Z"
        total_tasks = {
            k: {"ok": _ok_counts.get(k, 0), "err": _err_counts.get(k, 0)}
            for k in set(list(_ok_counts.keys()) + list(_err_counts.keys()))
        }
        ready = _READY_TS is not None
        return {
            "started_at": started_iso,
            "ready": ready,
            "ready_ts": _READY_TS,
            "tasks": total_tasks,
            "build": dict(_BUILD_INFO),
        }
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def _import_callable(dotted: str) -> Callable[[], Any]:
    if ":" not in dotted:
        raise ValueError(f"Invalid func path (missing ':'): {dotted}")
    mod_name, func_name = dotted.split(":", 1)
    mod = importlib.import_module(mod_name)
    fn = getattr(mod, func_name)
    if not callable(fn):  # noqa: PLR1704
        raise TypeError(f"Imported object is not callable: {dotted}")
    return fn


def _load_jobs_from_yaml(path: str) -> list[dict[str, Any]] | None:
    if not path or not os.path.exists(path):
        log.warning("scheduler_config_missing", path=path)
        return None
    if yaml is None:
        log.warning("pyyaml_not_installed", hint="pip install pyyaml")
        return None
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    jobs = data.get("jobs", [])
    if not isinstance(jobs, list):
        log.warning("scheduler_config_invalid", reason="jobs is not a list")
        return None

    def _expand_env(val: Any) -> Any:
        if isinstance(val, str) and val.startswith("${") and val.endswith("}"):
            env_name = val[2:-1]
            return os.getenv(env_name, "")
        if isinstance(val, dict):
            return {k: _expand_env(v) for k, v in val.items()}
        if isinstance(val, list):
            return [_expand_env(v) for v in val]
        return val

    expanded: list[dict[str, Any]] = []
    for j in jobs:
        if isinstance(j, dict):
            j = {k: _expand_env(v) for k, v in j.items()}
        expanded.append(j)
    return expanded


def _to_seconds(every: Any) -> float:
    if isinstance(every, (int, float)):
        return float(every)
    if isinstance(every, str):
        s = every.strip().lower()
        if s.endswith("ms"):
            return max(0.001, float(s[:-2]) / 1000.0)
        if s.endswith("s"):
            return max(1.0, float(s[:-1]))
        if s.endswith("m"):
            return float(s[:-1]) * 60.0
        if s.endswith("h"):
            return float(s[:-1]) * 3600.0
        if s.endswith("d"):
            return float(s[:-1]) * 86400.0
        return float(s)
    raise ValueError(f"Unsupported 'every' value: {every}")


def build_scheduler() -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone="UTC")

    config_path = os.getenv("SCHEDULER_CONFIG", "")
    jobs = _load_jobs_from_yaml(config_path)

    run_at_start = os.getenv("RUN_JOBS_AT_START", "1") == "1"
    if jobs:
        for job in jobs:
            if not job.get("enabled", True):
                continue
            job_id = job.get("id")
            func_path = job.get("func")
            every = job.get("every", 300)
            if not job_id or not func_path:
                log.warning("job_skipped_invalid", job=job)
                continue
            try:
                seconds = _to_seconds(every)
                fn = _import_callable(func_path)
                args = job.get("args", [])
                if not isinstance(args, list):
                    raise TypeError("job.args must be a list")
                kwargs = job.get("kwargs", {})
                if kwargs is None:
                    kwargs = {}
                if not isinstance(kwargs, dict):
                    raise TypeError("job.kwargs must be a dict")
                sched.add_job(
                    task_wrapper,
                    IntervalTrigger(seconds=_with_jitter(seconds)),
                    id=str(job_id),
                    args=(job_id, fn, tuple(args), kwargs),
                    next_run_time=(datetime.now(UTC) if run_at_start else None),
                    replace_existing=True,
                    coalesce=True,
                    misfire_grace_time=60,
                    max_instances=1,
                )
                log.info(
                    "job_registered",
                    id=job_id,
                    every=seconds,
                    func=func_path,
                    args=args,
                    kwargs=list(kwargs.keys()),
                )
            except Exception as e:  # noqa: BLE001
                log.error(
                    "job_register_error", id=job_id, error=str(e), job=job
                )
    else:

        async def _noop():  # noqa: D401
            """No-op default coroutine when no scheduler file provided."""
            await asyncio.sleep(0.05)

        defaults = [
            ("macro", _noop, 300),
            ("onchain", _noop, 300),
            ("derivatives", _noop, 300),
            ("defi", _noop, 900),
            ("stablecoins", _noop, 1800),
            ("sentiment", _noop, 3600),
            ("tokenmetrics", _noop, 3600),
            ("heavy_history", _noop, 21600),
        ]
        for jid, fn, sec in defaults:
            sched.add_job(
                task_wrapper,
                IntervalTrigger(seconds=_with_jitter(sec)),
                id=jid,
                args=(jid, fn, tuple(), {}),
                next_run_time=(datetime.now(UTC) if run_at_start else None),
                replace_existing=True,
                coalesce=True,
                misfire_grace_time=60,
                max_instances=1,
            )
            log.info("job_registered_default", id=jid, every=sec)

    return sched


async def noop():
    """Fallback coroutine when an expected async function is missing."""
    log
