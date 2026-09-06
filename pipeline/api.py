from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field, ValidationError
from starlette.responses import JSONResponse, StreamingResponse

from signals import get_predictor, signals_router

from . import build_info, db_adapter
from .collectors import whale_insider, whales
from .llm import providers as llm_providers
from .llm.client import ClientLLM, ModelConfig, QuotaState
from .rate_limit import build_rate_limiter_from_env
from .schemas import HealthResponse, HistoryMetaResponse, Report

# Optional Prometheus support for /metrics route; imported lazily below as well
try:  # pragma: no cover - import guard for environments without prometheus_client
    from prometheus_client import CONTENT_TYPE_LATEST as _PM_CONTENT_TYPE_LATEST
    from prometheus_client import generate_latest as _pm_generate
except Exception:  # pragma: no cover
    _PM_CONTENT_TYPE_LATEST = None  # type: ignore[assignment]
    _pm_generate = None  # type: ignore[assignment]

_docs_enabled = os.getenv("API_DOCS_ENABLED", "1").strip() != "0"
app = FastAPI(
    title="Crypto-AI Pipeline API",
    version="0.1.0",
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

app.include_router(signals_router)

# Optional CORS (disabled by default). Configure with env:
# API_CORS_ENABLED=1
# API_CORS_ORIGINS=comma-separated origins (e.g. https://app.example.com,https://studio.local)
if os.getenv("API_CORS_ENABLED", "0").strip() == "1":
    origins = [o.strip() for o in os.getenv("API_CORS_ORIGINS", "").split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

# Optional GZip compression
if os.getenv("API_GZIP_ENABLED", "0").strip() == "1":
    min_size = int(os.getenv("API_GZIP_MIN_SIZE", "500"))
    app.add_middleware(GZipMiddleware, minimum_size=min_size)


@app.middleware("http")
async def body_size_limit_middleware(request: Request, call_next):
    # Only apply to methods that can have significant bodies
    if request.method in {"POST", "PUT", "PATCH"}:
        # Evaluate per request to allow tests/env toggling without reload
        max_body_bytes = int(os.getenv("API_MAX_BODY_BYTES", "0") or 0)
        if max_body_bytes > 0:
            # Trust Content-Length if present; otherwise allow (streaming enforcement would be intrusive)
            try:
                cl = request.headers.get("content-length")
                if cl is not None and cl.isdigit() and int(cl) > max_body_bytes:
                    req_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
                    return JSONResponse(
                        {"detail": "Request entity too large"},
                        status_code=413,
                        headers={"X-Request-ID": req_id},
                    )
            except Exception:
                # Be permissive on parsing issues
                pass
    return await call_next(request)


class LLMGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    model: str | None = None  # hint/override
    temperature: float | None = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=256, ge=1, le=4096)


class LLMGenerateResponse(BaseModel):
    model: str
    output: str


class WhaleAddress(BaseModel):
    address: str
    balance_eth: float


class WhaleBalancesResponse(BaseModel):
    source: str
    generated_at: int | None
    total_eth: float
    addresses: list[WhaleAddress]


class WhaleInsiderRecord(BaseModel):
    timestamp: int | None = None
    asset: str | None = None
    symbol: str | None = None
    chain: str | None = None
    trader: str | None = None
    metric_name: str | None = None
    value: float | int | str | None = None
    source: str | None = None
    confidence_score: float | None = None
    metadata: dict[str, Any] | None = None
    addresses: list[dict[str, Any]] | None = None

    class Config:
        extra = "ignore"


class WhaleInsiderMeta(BaseModel):
    etherscan_watch_count: int | None = None
    hyperliquid_watch_count: int | None = None
    hyperliquid_records: int | None = None
    records_count: int | None = None

    class Config:
        extra = "ignore"


class WhaleInsiderResponse(BaseModel):
    timestamp: int
    records: list[WhaleInsiderRecord]
    meta: WhaleInsiderMeta

    class Config:
        extra = "ignore"


class RumourItem(BaseModel):
    topic: str
    sentiment: str
    intensity: float | None = Field(default=None)
    confidence: float | None = Field(default=None)
    timestamp: str | None = None
    source: str | None = None
    note: str | None = None


class RumourReportsResponse(BaseModel):
    page: int
    page_size: int
    total: int
    summary: str | None = None
    items: list[RumourItem]


class SignalHealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    model_loaded: bool
    backlog_size: int
    last_error: str | None = None
    model_path: str | None = None


def _build_signals_health() -> SignalHealthResponse:
    predictor = get_predictor()
    model_loaded = predictor.model_loaded
    backlog_size = predictor.backlog_size()
    last_error = predictor.last_error
    model_path = getattr(predictor, "_model_path", None)
    model_path_str = str(model_path) if model_path is not None else None
    status_value: Literal["ok", "degraded"] = "ok" if model_loaded else "degraded"
    return SignalHealthResponse(
        status=status_value,
        model_loaded=model_loaded,
        backlog_size=backlog_size,
        last_error=last_error,
        model_path=model_path_str,
    )


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-KEY")) -> str:
    """Dépendance FastAPI pour valider la clé API des routes d'écriture.

    Retourne la clé si valide (utile pour rate limit par clé), sinon 403.
    """
    required = os.getenv("API_WRITE_KEY", "").strip()
    # Interdit quand pas de clé configurée (safe-by-default) ou si clé absente/différente
    if not required or not x_api_key or not hmac.compare_digest(x_api_key, required):
        raise HTTPException(status_code=403, detail="Forbidden")
    return x_api_key


def _build_llm_client() -> ClientLLM:
    # Providers enabled based on env, otherwise fallback to mock
    models: list[ModelConfig] = []
    prio = 0
    only_provider = os.getenv("API_LLM_ONLY", "").strip().lower()

    # DeepSeek (prioritaire par défaut si disponible)
    if (only_provider in ("", "deepseek")) and os.getenv("DEEPSEEK_API_KEY"):
        models.append(
            ModelConfig(
                name=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                daily_calls_limit=int(os.getenv("DEEPSEEK_DAILY_LIMIT", "1000")),
                priority=prio,
                fn=llm_providers.deepseek_generate,
            )
        )
        prio += 1

    # OpenAI
    if (only_provider in ("", "openai")) and os.getenv("OPENAI_API_KEY"):
        models.append(
            ModelConfig(
                name=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                daily_calls_limit=int(os.getenv("OPENAI_DAILY_LIMIT", "500")),
                priority=prio,
                fn=llm_providers.openai_generate,
            )
        )
        prio += 1

    # OpenRouter
    if (only_provider in ("", "openrouter")) and os.getenv("OPENROUTER_API_KEY"):
        models.append(
            ModelConfig(
                name=os.getenv("OPENROUTER_MODEL", "openrouter/auto"),
                daily_calls_limit=int(os.getenv("OPENROUTER_DAILY_LIMIT", "500")),
                priority=prio,
                fn=llm_providers.openrouter_generate,
            )
        )
        prio += 1

    # Ollama local
    if (only_provider in ("", "ollama")) and (os.getenv("OLLAMA_HOST") or os.getenv("OLLAMA_MODEL")):
        models.append(
            ModelConfig(
                name=os.getenv("OLLAMA_MODEL", "llama3.1"),
                daily_calls_limit=int(os.getenv("OLLAMA_DAILY_LIMIT", "10000")),
                priority=prio,
                fn=llm_providers.ollama_generate,
            )
        )
        prio += 1

    # Always keep a mock last-resort to ensure API works without secrets
    models.append(
        ModelConfig(
            name="mock",
            daily_calls_limit=10_000,
            priority=prio,
            fn=llm_providers.mock_generate,
        )
    )

    return ClientLLM(models, QuotaState())


_LLM_CLIENT = _build_llm_client()
_RATE_LIMIT = build_rate_limiter_from_env(limit_per_minute=int(os.getenv("API_RATE_LIMIT_PER_MIN", "60")))


# Optional client-side caching for read endpoints
def _maybe_apply_cache_headers(request: Request, response: Response, payload_bytes: bytes) -> None:
    """Compute and set ETag + Cache-Control when enabled; respond 304 when match."""
    try:
        etag = '"' + hashlib.sha256(payload_bytes).hexdigest()[:32] + '"'
        inm = request.headers.get("if-none-match")
        if inm and inm.strip() == etag:
            # Signal to caller via header we would have returned same entity
            response.headers["ETag"] = etag
            # Mark handled by raising early return: in handlers we check separately
            response.status_code = 304
            # No body
            response.body = b""
            return
        response.headers["ETag"] = etag
        read_max_age = int(os.getenv("API_READ_MAX_AGE", "0") or 0)
        if read_max_age > 0:
            response.headers["Cache-Control"] = f"public, max-age={read_max_age}"
    except Exception:
        # Be permissive, never fail endpoint on cache headers
        pass


_RUMOUR_SNAPSHOT_PATH = Path(os.getenv("RUMOUR_SNAPSHOT_PATH", "exports/rumour_latest.json"))


def _load_rumour_records() -> list[dict[str, Any]]:
    path = _RUMOUR_SNAPSHOT_PATH
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    records = data.get("records") if isinstance(data, dict) else None
    if not isinstance(records, list):
        return []
    return [item for item in records if isinstance(item, dict)]


def _build_rumour_summary(records: list[dict[str, Any]]) -> str | None:
    if not records:
        return None
    lines = ["Analyse les rumeurs crypto suivantes et résume en trois bullet points actionnables :"]
    for rec in records:
        topic = rec.get("topic") or rec.get("symbol") or "narrative"
        sentiment = rec.get("sentiment") or "neutral"
        intensity = rec.get("value") or rec.get("intensity") or "?"
        confidence = rec.get("confidence") or rec.get("confidence_score") or "?"
        lines.append(f"- {topic}: sentiment {sentiment}, intensité {intensity}, confiance {confidence}")
    prompt = "\n".join(lines)
    try:
        return _LLM_CLIENT.generate(prompt, model=None, temperature=0.1, max_tokens=220)
    except Exception:
        return None


def _is_localhost_host(host_header: str) -> bool:
    host = (host_header or "").split(":")[0].lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def _is_metrics_allowed(request: Request) -> bool:
    """Restrict /metrics exposure to localhost by default or explicit allow-list.

    Env:
        - METRICS_ALLOWED_HOSTS: comma-separated hostnames/IPs allowed (default: 127.0.0.1,::1,localhost)
        - METRICS_TRUST_XFF: when true-ish (1/true/yes/y), trust first hop of X-Forwarded-For (default: 0)
    """
    try:
        raw = os.getenv("METRICS_ALLOWED_HOSTS", "127.0.0.1,::1,localhost")
        allowed_hosts = {h.strip().lower() for h in raw.split(",") if h.strip()}
    except Exception:
        allowed_hosts = {"127.0.0.1", "::1", "localhost"}

    # Prefer connection peer when available
    client_ip = (getattr(request.client, "host", None) or "").lower()

    # Only trust XFF if explicitly enabled
    trust_val = os.getenv("METRICS_TRUST_XFF", "0").strip().lower()
    trust_xff = trust_val in {"1", "true", "yes", "y"}
    if trust_xff:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            xff_ip = xff.split(",")[0].strip().lower()
            if xff_ip:
                client_ip = xff_ip

    if not client_ip:
        return False

    return ("*" in allowed_hosts) or (client_ip in allowed_hosts)


@app.middleware("http")
async def security_and_request_id_middleware(request: Request, call_next):
    # Generate or echo request id early so it's present even on errors
    req_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex

    # HTTPS enforcement (optional): allow localhost and forwarded https
    enforce_https = os.getenv("API_ENFORCE_HTTPS", "0").strip() == "1"
    forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
    is_secure = (request.url.scheme == "https") or (forwarded_proto == "https")
    is_local = _is_localhost_host(request.headers.get("host", ""))
    if enforce_https and (not is_secure) and (not is_local):
        return JSONResponse({"detail": "HTTPS required"}, status_code=400, headers={"X-Request-ID": req_id})

    response = await call_next(request)

    # Security headers (safe defaults for APIs)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    # HSTS only if secure and not localhost
    if is_secure and (not is_local):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    # Remove explicit server header if any (defense in depth)
    from contextlib import suppress

    with suppress(Exception):
        response.headers.pop("server", None)

    # Echo or generate X-Request-ID
    response.headers["X-Request-ID"] = req_id
    return response


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "service": "Crypto-AI Pipeline API",
        "version": "0.1.0",
        "status": "running",
        "endpoints": {
            "api_index": "/api",
            "health": "/api/health",
            "version": "/api/version",
            "report_latest": "/api/report/latest",
            "report_history": "/api/report/history?interval=1h",
            "report_history_meta": "/api/report/history_meta?interval=1h&page=1&page_size=50",
            "quant": "/api/quant",
            "onchain": "/api/onchain",
            "fundamental": "/api/fundamental",
            "llm_status": "/api/llm/status",
            "llm_generate": "/api/llm/generate",
            "llm_stream": "/api/llm/stream",
            "rumour_reports": "/api/rumour/reports",
            "signals_health": "/api/health/signals",
        },
    }


@app.get("/api")
def api_index() -> dict[str, Any]:
    return {
        "status": "ok",
        "routes": [
            "/api/health",
            "/api/version",
            "/api/report/latest",
            "/api/report/history",
            "/api/report/history_meta",
            "/api/quant",
            "/api/onchain",
            "/api/fundamental",
            "/api/llm/status",
            "/api/llm/generate",
            "/api/llm/stream",
            "/api/rumour/reports",
            "/api/health/signals",
        ],
    }


@app.get("/api/health", response_model=HealthResponse)
def api_health() -> dict[str, Any]:
    meta = build_info.build_metadata(include_uptime=True)
    # meta est un TypedDict compatible avec Dict[str, Any]
    merged: dict[str, Any] = {"status": "ok", **meta}
    return merged


@app.get("/api/health/signals", response_model=SignalHealthResponse)
def api_signals_health() -> SignalHealthResponse:
    return _build_signals_health()


@app.get("/api/version")
def api_version() -> dict[str, Any]:
    meta = build_info.build_metadata(include_uptime=False)
    return dict(meta)


# Root-level convenience aliases
@app.get("/health", response_model=HealthResponse)
def root_health() -> dict[str, Any]:
    return api_health()


@app.get("/health/signals", response_model=SignalHealthResponse)
def root_signals_health() -> SignalHealthResponse:
    return _build_signals_health()


@app.get("/version")
def root_version() -> dict[str, Any]:
    return api_version()


@app.get("/api/report/latest", response_model=Report)
def get_latest(request: Request, response: Response):
    r = db_adapter.get_latest_report()
    if not r:
        raise HTTPException(status_code=404, detail="No report available")
    # Apply optional ETag/Cache-Control
    try:
        payload = r.model_dump_json().encode("utf-8")
        _maybe_apply_cache_headers(request, response, payload)
        if response.status_code == 304:
            return Response(status_code=304)
    except Exception:
        pass
    return r


@app.get("/api/report/history", response_model=list[Report])
def get_history(
    request: Request,
    response: Response,
    interval: str = Query(default="1h", pattern=r"^(15m|1h|4h|1d|1w|1m|1y)$"),
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=200),
):
    items = db_adapter.get_report_history(interval)
    if page and page_size:
        start = (page - 1) * page_size
        end = start + page_size
        sliced = items[start:end]
        # En-têtes de pagination utiles pour les clients
        # Note: on ne peut pas ajouter des headers via return direct; cette route n'emploie pas Response param.
        # Pour exposer X-Total-Count et X-Has-Next, fournissons une JSONResponse quand pagination est utilisée.
        total = len(items)
        has_next = end < total
        # ETag/Cache-Control sur la payload paginée
        payload_obj = jsonable_encoder(sliced)
        payload_bytes = json.dumps(payload_obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        headers = {
            "X-Total-Count": str(total),
            "X-Has-Next": "true" if has_next else "false",
        }
        try:
            etag = '"' + hashlib.sha256(payload_bytes).hexdigest()[:32] + '"'
            inm = request.headers.get("if-none-match")
            if inm and inm.strip() == etag:
                return Response(status_code=304, headers={"ETag": etag})
            headers["ETag"] = etag
            read_max_age = int(os.getenv("API_READ_MAX_AGE", "0") or 0)
            if read_max_age > 0:
                headers["Cache-Control"] = f"public, max-age={read_max_age}"
        except Exception:
            pass
        return JSONResponse(payload_obj, headers=headers)
    # Non paginé: appliquer ETag/Cache-Control via Response
    try:
        payload_obj = jsonable_encoder(items)
        payload_bytes = json.dumps(payload_obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        _maybe_apply_cache_headers(request, response, payload_bytes)
        if response.status_code == 304:
            return Response(status_code=304)
    except Exception:
        pass
    return items


@app.get("/api/whales/balances", response_model=WhaleBalancesResponse)
def get_whale_balances() -> WhaleBalancesResponse:
    snapshot = whales.load_latest_snapshot()
    if not snapshot:
        raise HTTPException(status_code=404, detail="No whale balance snapshot available")
    addresses_raw = snapshot.get("addresses")
    addresses: list[WhaleAddress] = []
    if isinstance(addresses_raw, list):
        for entry in addresses_raw:
            if not isinstance(entry, dict):
                continue
            addr = entry.get("address")
            bal = entry.get("balance_eth")
            if not isinstance(addr, str) or not isinstance(bal, int | float):
                continue
            addresses.append(WhaleAddress(address=addr, balance_eth=float(bal)))
    total_eth = snapshot.get("total_eth")
    if not isinstance(total_eth, int | float):
        raise HTTPException(status_code=500, detail="Invalid whale snapshot payload")
    generated_at_raw = snapshot.get("generated_at")
    if isinstance(generated_at_raw, int | float):
        generated_at: int | None = int(generated_at_raw)
    elif isinstance(generated_at_raw, str) and generated_at_raw.isdigit():
        generated_at = int(generated_at_raw)
    else:
        generated_at = None
    source_raw = snapshot.get("source")
    source = source_raw if isinstance(source_raw, str) and source_raw else "etherscan"
    return WhaleBalancesResponse(
        source=source,
        generated_at=generated_at,
        total_eth=float(total_eth),
        addresses=addresses,
    )


@app.get("/api/whales/insider", response_model=WhaleInsiderResponse)
def get_whale_insider() -> WhaleInsiderResponse:
    snapshot = whale_insider.load_latest_snapshot()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No whale insider snapshot available")
    try:
        validator = getattr(WhaleInsiderResponse, "model_validate", None)
        if callable(validator):  # pydantic v2
            return cast(WhaleInsiderResponse, validator(snapshot))
        return cast(WhaleInsiderResponse, WhaleInsiderResponse.parse_obj(snapshot))
    except ValidationError as exc:
        raise HTTPException(status_code=500, detail="Invalid whale insider snapshot payload") from exc


@app.get("/api/report/history_meta", response_model=HistoryMetaResponse)
def get_history_meta(
    request: Request,
    response: Response,
    interval: str = Query(default="1h", pattern=r"^(15m|1h|4h|1d|1w|1m|1y)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    """Retourne l'historique paginé avec métadonnées.

    Réponse:
    {
      total: int,
      page: int,
      page_size: int,
      has_next: bool,
      items: List[Report]
    }
    """
    items = db_adapter.get_report_history(interval)
    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    sliced = items[start:end]
    has_next = end < total
    result = {
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_next": has_next,
        "items": sliced,
    }
    try:
        payload_obj = jsonable_encoder(result)
        payload_bytes = json.dumps(payload_obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        _maybe_apply_cache_headers(request, response, payload_bytes)
        if response.status_code == 304:
            return Response(status_code=304)
    except Exception:
        pass
    return result


@app.get("/api/quant")
def get_quant(request: Request, response: Response):
    r = db_adapter.get_latest_report()
    if not r or not r.quant:
        raise HTTPException(status_code=404, detail="No quant report available")
    try:
        payload_obj = jsonable_encoder(r.quant)
        payload_bytes = json.dumps(payload_obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        _maybe_apply_cache_headers(request, response, payload_bytes)
        if response.status_code == 304:
            return Response(status_code=304)
    except Exception:
        pass
    return r.quant


@app.get("/api/onchain")
def get_onchain(request: Request, response: Response):
    r = db_adapter.get_latest_report()
    # On-chain pourrait être dans technical ou une autre section dédiée selon implémentation finale
    if not r or not r.technical:
        raise HTTPException(status_code=404, detail="No on-chain/technical section available")
    try:
        payload_obj = jsonable_encoder(r.technical)
        payload_bytes = json.dumps(payload_obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        _maybe_apply_cache_headers(request, response, payload_bytes)
        if response.status_code == 304:
            return Response(status_code=304)
    except Exception:
        pass
    return r.technical


@app.get("/api/fundamental")
def get_fundamental(request: Request, response: Response):
    r = db_adapter.get_latest_report()
    if not r or not r.fundamental:
        raise HTTPException(status_code=404, detail="No fundamental report available")
    try:
        payload_obj = jsonable_encoder(r.fundamental)
        payload_bytes = json.dumps(payload_obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        _maybe_apply_cache_headers(request, response, payload_bytes)
        if response.status_code == 304:
            return Response(status_code=304)
    except Exception:
        pass
    return r.fundamental


@app.get("/api/rumour/reports", response_model=RumourReportsResponse)
def get_rumour_reports(
    request: Request,
    response: Response,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    keyword: str | None = Query(default=None, min_length=1),
    summarize: bool = Query(default=True),
):
    records = _load_rumour_records()
    if not records:
        raise HTTPException(status_code=404, detail="No rumour data available")
    filtered = records
    if keyword:
        kw = keyword.lower().strip()
        filtered = [
            rec
            for rec in records
            if kw in str(rec.get("topic", "")).lower() or kw in str(rec.get("symbol", "")).lower()
        ]
    if not filtered:
        raise HTTPException(status_code=404, detail="No rumour data matching filters")
    total = len(filtered)
    start = (page - 1) * page_size
    end = start + page_size
    items = filtered[start:end]
    if not items:
        raise HTTPException(status_code=404, detail="No rumour data for requested page")

    payload_items: list[RumourItem] = []
    for rec in items:
        topic = str(rec.get("topic") or rec.get("symbol") or "narrative")
        sentiment = str(rec.get("sentiment") or "neutral")
        try:
            intensity_val = float(rec.get("value") or rec.get("intensity") or 0.0)
        except Exception:
            intensity_val = 0.0
        try:
            confidence_val = float(rec.get("confidence") or rec.get("confidence_score") or 0.0)
        except Exception:
            confidence_val = 0.0
        timestamp = rec.get("timestamp") if isinstance(rec.get("timestamp"), str) else None
        source = str(rec.get("source") or "rumour.app")
        note = str(rec.get("note") or "NFA: Based on unverified narratives.")
        payload_items.append(
            RumourItem(
                topic=topic,
                sentiment=sentiment,
                intensity=round(intensity_val, 4),
                confidence=round(confidence_val, 3),
                timestamp=timestamp,
                source=source,
                note=note,
            )
        )

    summary = _build_rumour_summary(items) if summarize else None
    result = RumourReportsResponse(
        page=page,
        page_size=page_size,
        total=total,
        summary=summary,
        items=payload_items,
    )
    try:
        payload_bytes = result.model_dump_json().encode("utf-8")
        _maybe_apply_cache_headers(request, response, payload_bytes)
        if response.status_code == 304:
            return Response(status_code=304)
    except Exception:
        pass
    return result


@app.post("/api/report", response_model=Report, status_code=201)
def create_report(report: Report, response: Response, api_key: str = Depends(require_api_key)):
    # Rate limit per API key
    allowed, retry_after, remaining, reset_after = _RATE_LIMIT.check_allow_with_meta(f"report:{api_key}")
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(_RATE_LIMIT.limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(reset_after),
            },
        )
    db_adapter.write_report(report)
    # Expose basic quota headers on success
    response.headers["X-RateLimit-Limit"] = str(_RATE_LIMIT.limit)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Reset"] = str(reset_after)
    return Report(**report.model_dump())


@app.post("/api/llm/generate", response_model=LLMGenerateResponse)
def llm_generate(req: LLMGenerateRequest, response: Response, api_key: str = Depends(require_api_key)):
    allowed, retry_after, remaining, reset_after = _RATE_LIMIT.check_allow_with_meta(f"llm:{api_key}")
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(_RATE_LIMIT.limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(reset_after),
            },
        )
    # Build opts from request; ClientLLM will handle quotas/fallbacks and metrics
    opts = {
        "model": req.model,
        "temperature": req.temperature,
        "max_tokens": req.max_tokens,
    }
    try:
        out = _LLM_CLIENT.generate(req.prompt, **opts)
        used_model = _LLM_CLIENT.last_used_model or (req.model or "mock")
        # headers on success
        response.headers["X-RateLimit-Limit"] = str(_RATE_LIMIT.limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_after)
        return LLMGenerateResponse(model=used_model, output=out)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {type(e).__name__}: {e}") from e


@app.get("/api/llm/status")
def llm_status() -> dict[str, Any]:
    # Vue simple: liste des modèles avec leurs quotas restants
    models = [
        {
            "name": m.name,
            "priority": m.priority,
            "remaining": _LLM_CLIENT.quota.remaining(m),
        }
        for m in _LLM_CLIENT.models
    ]
    return {
        "models": models,
        "last_used_model": _LLM_CLIENT.last_used_model,
    }


class LLMStreamRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    model: str | None = None
    temperature: float | None = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=256, ge=1, le=4096)


def _stream_sse_from_text(text: str):
    # Génère des chunks SSE simples à partir d'un texte
    chunk_size = max(16, min(128, len(text) // 8 or 32))
    for i in range(0, len(text), chunk_size):
        chunk = text[i : i + chunk_size]
        yield f"data: {chunk}\n\n"
    yield "data: [DONE]\n\n"


@app.post("/api/llm/stream")
def llm_stream(req: LLMStreamRequest, response: Response, api_key: str = Depends(require_api_key)):
    # Limiteur spécifique au stream
    allowed, retry_after, remaining, reset_after = _RATE_LIMIT.check_allow_with_meta(f"llm_stream:{api_key}")
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(_RATE_LIMIT.limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(reset_after),
            },
        )

    opts = {
        "model": req.model,
        "temperature": req.temperature,
        "max_tokens": req.max_tokens,
    }
    try:
        out = _LLM_CLIENT.generate(req.prompt, **opts)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {type(e).__name__}: {e}") from e

    stream = StreamingResponse(_stream_sse_from_text(out), media_type="text/event-stream")
    # Friendly SSE headers to avoid buffering by proxies
    stream.headers["Cache-Control"] = "no-cache"
    stream.headers["Connection"] = "keep-alive"
    stream.headers["X-Accel-Buffering"] = "no"  # for nginx
    stream.headers["X-RateLimit-Limit"] = str(_RATE_LIMIT.limit)
    stream.headers["X-RateLimit-Remaining"] = str(remaining)
    stream.headers["X-RateLimit-Reset"] = str(reset_after)
    return stream


# Prometheus /metrics exposed by default, but restricted to localhost/allow-list.
if _pm_generate is not None:

    @app.get("/metrics")
    def metrics_route(request: Request):
        if not _is_metrics_allowed(request):
            raise HTTPException(status_code=403, detail="Forbidden")
        assert _pm_generate is not None
        data = _pm_generate()
        return Response(content=data, media_type=_PM_CONTENT_TYPE_LATEST)
