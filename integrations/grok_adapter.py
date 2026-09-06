"""
Adapter Grok (XAI) — opt-in, minimal, robuste.

Contrat:
- Entrée: liste d'actifs (strings), fenêtre (ex: "1h", "24h"), limite (int)
- Sortie: dict JSON sérialisable { ts, window, assets, items: [ {asset, sentiment, trends, examples, source} ], meta }

Caractéristiques:
- Utilise la façade HTTP unifiée (pipeline.http.async_post_json)
- Flags/env: GROK_ENABLED, GROK_API_KEY, GROK_API_BASE, GROK_TIMEOUT, GROK_CACHE_TTL
- Cache local (fichier) pour limiter les appels si TTL non expiré
- Instrumentation: compteurs/latence via pipeline.metrics si disponible (sans crash si absent)

Nota bene: cet adapter ne dépend d'aucune lib externe et reste désactivé par défaut.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from httpx import AsyncClient
else:  # pragma: no cover - typing fallback
    AsyncClient = Any

try:
    # Facade HTTP unifiée
    from pipeline.http import async_post_json
except Exception:  # pragma: no cover - fallback import

    async def async_post_json(
        url: str,
        *,
        timeout: float | None = None,
        headers: Mapping[str, str] | None = None,
        json: Any | None = None,
        data: Any | None = None,
        retries: int | None = None,
        backoff_base: float | None = None,
        client: AsyncClient | None = None,
    ) -> Any:
        raise RuntimeError("pipeline.http.async_post_json indisponible")


DEFAULT_API_BASE = os.environ.get("GROK_API_BASE", "https://api.x.ai")
DEFAULT_ENDPOINT = "/v1/social/sentiment"


@dataclass
class GrokConfig:
    enabled: bool
    api_key: str | None
    api_base: str = DEFAULT_API_BASE
    endpoint: str = DEFAULT_ENDPOINT
    timeout: float = float(os.environ.get("GROK_TIMEOUT", "15"))
    cache_ttl: int = int(os.environ.get("GROK_CACHE_TTL", "1800"))  # 30 min


def _is_enabled() -> bool:
    return os.environ.get("GROK_ENABLED", "0") in {"1", "true", "yes", "on"}


def load_config() -> GrokConfig:
    return GrokConfig(
        enabled=_is_enabled(),
        api_key=os.environ.get("GROK_API_KEY"),
        api_base=os.environ.get("GROK_API_BASE", DEFAULT_API_BASE),
        endpoint=os.environ.get("GROK_API_ENDPOINT", DEFAULT_ENDPOINT),
        timeout=float(os.environ.get("GROK_TIMEOUT", "15")),
        cache_ttl=int(os.environ.get("GROK_CACHE_TTL", "1800")),
    )


def _cache_path(window: str, assets: list[str]) -> Path:
    key = f"{window}_" + "_".join(sorted(a.lower() for a in assets))
    safe = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in key)
    base = Path("exports") / "social"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"grok_{safe}.json"


def _cache_valid(p: Path, ttl: int) -> bool:
    try:
        return p.exists() and (time.time() - p.stat().st_mtime) < ttl
    except OSError:
        return False


async def get_social_signals(
    assets: list[str],
    window: str = "1h",
    limit: int = 50,
    *,
    force: bool = False,
) -> dict[str, Any]:
    cfg = load_config()
    cache_file = _cache_path(window, assets)

    if not force and _cache_valid(cache_file, cfg.cache_ttl):
        with cache_file.open("r", encoding="utf-8") as f:
            cached = json.load(f)
        if isinstance(cached, dict):
            return cached

    if not cfg.enabled:
        # Retourner un placeholder cohérent sans appeler l’API
        payload = {
            "ts": int(time.time()),
            "window": window,
            "assets": assets,
            "items": [],
            "meta": {"enabled": False, "reason": "GROK_ENABLED=0"},
        }
        _write(cache_file, payload)
        return payload

    if not cfg.api_key:
        payload = {
            "ts": int(time.time()),
            "window": window,
            "assets": assets,
            "items": [],
            "meta": {"enabled": True, "error": "missing_api_key"},
        }
        _write(cache_file, payload)
        return payload

    url = cfg.api_base.rstrip("/") + cfg.endpoint
    headers = {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"}
    body = {"assets": assets, "window": window, "limit": limit}

    try:
        data = await async_post_json(url, headers=headers, json=body, timeout=cfg.timeout)
        payload = _normalize_response(data, assets, window)
        _write(cache_file, payload)
        return payload
    except Exception as exc:  # noqa: BLE001
        # Dégradé: renvoyer un payload vide mais marqué en erreur
        payload = {
            "ts": int(time.time()),
            "window": window,
            "assets": assets,
            "items": [],
            "meta": {"enabled": True, "error": type(exc).__name__},
        }
        _write(cache_file, payload)
        return payload


def _normalize_response(data: Any, assets: list[str], window: str) -> dict[str, Any]:
    # Accepter plusieurs schémas: {items:[...]}, ou déjà normalisé
    items: list[dict[str, Any]] = []
    try:
        raw_items = data.get("items") if isinstance(data, dict) else None
        if isinstance(raw_items, list):
            items = [
                {
                    "asset": (it.get("asset") or it.get("symbol") or "unknown").upper(),
                    "sentiment": float(it.get("sentiment", 0.0)),
                    "trends": it.get("trends", []),
                    "examples": (it.get("examples", []) or [])[:5],
                    "source": it.get("source", "xai"),
                }
                for it in raw_items
                if isinstance(it, dict)
            ]
    except Exception:
        items = []

    return {
        "ts": int(time.time()),
        "window": window,
        "assets": assets,
        "items": items,
        "meta": {"enabled": True, "source": "grok"},
    }


def _write(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        tmp.replace(path)
    except Exception:
        # Ne pas faire échouer le pipeline pour un problème d’I/O d’export social
        pass


if __name__ == "__main__":  # petit test manuel

    async def _main():
        out = await get_social_signals(["BTC", "ETH"], window="1h", limit=20, force=True)
        print(json.dumps(out, ensure_ascii=False)[:400] + "...")

    asyncio.run(_main())
