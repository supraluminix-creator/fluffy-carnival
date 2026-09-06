from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict, cast

import structlog

from pipeline.http import async_fetch_text
from pipeline.instrumentation import instrument_collector

bs4_module: Any | None = None
_BS4_IMPORT_ERROR: Exception | None = None
try:  # pragma: no cover - import guard for optional dependency
    import bs4 as _bs4_module
except Exception as exc:  # pragma: no cover
    _BS4_IMPORT_ERROR = exc
else:
    bs4_module = _bs4_module

if TYPE_CHECKING:  # pragma: no cover - typing helper fallback
    from bs4 import BeautifulSoup as _BeautifulSoupType
else:  # pragma: no cover - runtime fallback
    _BeautifulSoupType = Any

BeautifulSoup: type[_BeautifulSoupType] | None
BeautifulSoup = cast("type[_BeautifulSoupType] | None", getattr(bs4_module, "BeautifulSoup", None))

log = structlog.get_logger(__name__)

_TRENDING_URL = "https://rumour.app/trending"
_CACHE_PATH = Path(".cache_rumour.json")
_DEFAULT_EXPORT_DIR = Path(os.getenv("EXPORT_DIR", "exports"))


class RumourRecord(TypedDict, total=False):
    timestamp: str
    asset: str
    symbol: str
    chain: str
    metric_name: str
    value: float
    source: str
    confidence_score: float
    topic: str
    sentiment: str
    confidence: float


@dataclass(slots=True)
class _CacheEnvelope:
    fetched_at: datetime
    records: list[RumourRecord]


def _truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _ensure_parser_available() -> None:
    if BeautifulSoup is None:  # pragma: no cover - defensive guard
        raise RuntimeError(
            "BeautifulSoup (beautifulsoup4) is required for rumour collector"
        ) from _BS4_IMPORT_ERROR


def _read_cache(key: tuple[str, ...], ttl_seconds: int) -> _CacheEnvelope | None:
    if not _CACHE_PATH.exists():
        return None
    try:
        payload = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    cached_key_raw = payload.get("cache_key")
    if not isinstance(cached_key_raw, list):
        return None
    cached_key = tuple(str(item) for item in cached_key_raw)
    if cached_key != key:
        return None
    fetched_at_raw = payload.get("fetched_at")
    try:
        fetched_at = datetime.fromisoformat(str(fetched_at_raw).replace("Z", "+00:00"))
    except Exception:
        return None
    if datetime.now(UTC) - fetched_at > timedelta(seconds=ttl_seconds):
        return None
    records = payload.get("records")
    if not isinstance(records, list):
        return None
    normalized: list[RumourRecord] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        normalized.append(item)  # type: ignore[arg-type]
    if not normalized:
        return None
    return _CacheEnvelope(fetched_at=fetched_at, records=normalized)


def _write_cache(key: tuple[str, ...], records: Iterable[RumourRecord]) -> None:
    snapshot = {
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "cache_key": list(key),
        "records": list(records),
    }
    try:
        _CACHE_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        log.debug("rumour_cache_write_failed", path=str(_CACHE_PATH))


def _persist_snapshot(records: list[RumourRecord], *, source: str) -> None:
    export_dir = _DEFAULT_EXPORT_DIR
    export_dir.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "records": records,
        "source": source,
        "disclaimer": "NFA: Based on unverified community narratives.",
    }
    latest = export_dir / "rumour_latest.json"
    history = export_dir / "rumour_history.jsonl"
    try:
        latest.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        log.warning("rumour_snapshot_write_failed", path=str(latest))
    try:
        with history.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    except Exception:
        log.debug("rumour_history_append_failed", path=str(history))


def _sanitize_sentiment(value: str | None) -> tuple[str, float]:
    if not value:
        return "neutral", 0.0
    label = value.strip().lower()
    if label in {"bullish", "positive"}:
        return label, 1.0
    if label in {"bearish", "negative"}:
        return label, -1.0
    return label, 0.0


def _parse_confidence(value: str | None) -> float:
    if not value:
        return 0.5
    try:
        conf = float(value)
    except Exception:
        try:
            conf = float(value.replace("%", ""))
        except Exception:
            return 0.5
    if conf > 1:
        conf = conf / 100 if conf <= 100 else 1.0
    return float(min(max(conf, 0.0), 1.0))


def _parse_mentions(value: str | None) -> int:
    if not value:
        return 1
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        return 1
    try:
        parsed = int(digits)
    except Exception:
        return 1
    return max(1, parsed)


def _extract_text(node: Any, selectors: Iterable[str]) -> str | None:
    for selector in selectors:
        found = getattr(node, "select_one", lambda s: None)(selector)
        if found is None:
            continue
        text = getattr(found, "get_text", lambda **_: "")(strip=True)
        if text:
            return str(text)
    return None


def _coerce_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="ignore")
        except Exception:
            return None
    if isinstance(value, bytearray):
        try:
            return bytes(value).decode("utf-8", errors="ignore")
        except Exception:
            return None
    return str(value)


def _parse_cards(html: str) -> list[RumourRecord]:
    _ensure_parser_available()
    assert BeautifulSoup is not None  # mypy narrowing: ensured via _ensure_parser_available
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".rumour-card") if hasattr(soup, "select") else []
    now = datetime.utcnow().isoformat() + "Z"
    records: list[RumourRecord] = []
    for card in cards:
        topic_raw = _coerce_text(card.get("data-topic"))
        topic = topic_raw or _extract_text(card, [".rumour-topic", ".topic", "h2", "h3"])
        sentiment_label_raw = _coerce_text(card.get("data-sentiment")) or _extract_text(
            card, [".sentiment", ".sentiment-label"]
        )
        sentiment_label, sentiment_score = _sanitize_sentiment(sentiment_label_raw)
        confidence_raw = _coerce_text(card.get("data-confidence")) or _extract_text(
            card, [".confidence", "[data-confidence]"]
        )
        confidence = _parse_confidence(confidence_raw)
        mentions_raw = _coerce_text(card.get("data-mentions")) or _extract_text(
            card, [".mentions", ".mention-count"]
        )
        mentions = _parse_mentions(mentions_raw)
        symbol_raw = _coerce_text(card.get("data-symbol"))
        symbol = symbol_raw or _extract_text(card, [".symbol", ".ticker", ".rumour-symbol"])
        symbol_candidate = symbol or topic or "NARRATIVE"
        symbol_clean = symbol_candidate.strip() if symbol_candidate else "NARRATIVE"
        topic_candidate = topic or symbol_clean or "NARRATIVE"
        topic_clean = topic_candidate.strip() if topic_candidate else "NARRATIVE"
        if not topic_clean:
            continue
        if not symbol_clean:
            symbol_clean = "NARRATIVE"
        record: RumourRecord = {
            "timestamp": now,
            "asset": symbol_clean.upper(),
            "symbol": symbol_clean.upper(),
            "chain": "-",
            "metric_name": "rumour_sentiment",
            "value": round(sentiment_score * confidence * mentions, 6),
            "source": "rumour.app",
            "confidence_score": confidence,
            "topic": topic_clean,
            "sentiment": sentiment_label,
            "confidence": confidence,
        }
        records.append(record)
    return records


_MOCK_TOPICS: list[dict[str, Any]] = [
    {"topic": "AI tokens", "symbol": "AIT", "sentiment": "positive", "confidence": 0.78},
    {"topic": "Restaking hype", "symbol": "ETH", "sentiment": "neutral", "confidence": 0.52},
    {"topic": "Bitcoin halving fatigue", "symbol": "BTC", "sentiment": "negative", "confidence": 0.63},
]


def _build_mock_records(limit: int) -> list[RumourRecord]:
    now = datetime.utcnow().isoformat() + "Z"
    records: list[RumourRecord] = []
    for item in _MOCK_TOPICS[:limit]:
        sentiment_label, sentiment_score = _sanitize_sentiment(item.get("sentiment"))
        confidence = float(item.get("confidence", 0.5))
        symbol = str(item.get("symbol") or item.get("topic") or "NARRATIVE").upper()
        records.append(
            {
                "timestamp": now,
                "asset": symbol,
                "symbol": symbol,
                "chain": "-",
                "metric_name": "rumour_sentiment",
                "value": round(sentiment_score * confidence, 6),
                "source": "rumour.app (mock)",
                "confidence_score": confidence,
                "topic": str(item.get("topic") or symbol),
                "sentiment": sentiment_label,
                "confidence": confidence,
            }
        )
    return records


def _filter_by_keywords(records: Iterable[RumourRecord], keywords: Iterable[str] | None) -> list[RumourRecord]:
    if not keywords:
        return list(records)
    lowered = [k.lower() for k in keywords if k]
    if not lowered:
        return list(records)
    filtered: list[RumourRecord] = []
    for rec in records:
        topic = str(rec.get("topic", "")).lower()
        symbol = str(rec.get("symbol", "")).lower()
        if any(k in topic or k in symbol for k in lowered):
            filtered.append(rec)
    return filtered


@instrument_collector("rumour")
async def fetch_rumour_trending(
    keywords: Iterable[str] | None = None,
    *,
    limit: int = 10,
    use_cache: bool = True,
) -> list[RumourRecord] | None:
    if not _truthy(os.getenv("ENABLE_RUMOUR_COLLECTOR", "1")):
        log.info("rumour_collector_disabled")
        return None

    kwargs_key = tuple(sorted(str(k).strip().lower() for k in (keywords or [])))
    limit = max(1, min(limit, 50))
    ttl_seconds = int(os.getenv("RUMOUR_CACHE_TTL", "900") or 900)

    if use_cache:
        cached = _read_cache(("keywords", *kwargs_key, f"limit={limit}"), ttl_seconds)
        if cached is not None:
            log.debug("rumour_cache_hit", fetched_at=cached.fetched_at.isoformat())
            return _filter_by_keywords(cached.records, keywords)[:limit]

    try:
        html = await async_fetch_text(_TRENDING_URL, timeout=10)
        records = _parse_cards(html)
    except Exception as exc:
        log.warning("rumour_scrape_failed", error=str(exc))
        if use_cache:
            cached = _read_cache(("keywords", *kwargs_key, f"limit={limit}"), ttl_seconds * 3)
            if cached is not None:
                log.info("rumour_cache_stale_usage")
                return _filter_by_keywords(cached.records, keywords)[:limit]
        if _truthy(os.getenv("ENABLE_RUMOUR_FALLBACKS", "0")):
            fallback = _build_mock_records(limit)
            _persist_snapshot(fallback, source="mock")
            _write_cache(("keywords", *kwargs_key, f"limit={limit}"), fallback)
            return _filter_by_keywords(fallback, keywords)[:limit]
        return None

    if not records:
        log.info("rumour_no_records")
        if _truthy(os.getenv("ENABLE_RUMOUR_FALLBACKS", "0")):
            fallback = _build_mock_records(limit)
            _persist_snapshot(fallback, source="mock_empty")
            _write_cache(("keywords", *kwargs_key, f"limit={limit}"), fallback)
            return _filter_by_keywords(fallback, keywords)[:limit]
        return None

    filtered = _filter_by_keywords(records, keywords)[:limit]
    if not filtered:
        log.info("rumour_filtered_empty", keywords=list(keywords or []))
        return None

    _persist_snapshot(filtered, source="primary")
    _write_cache(("keywords", *kwargs_key, f"limit={limit}"), filtered)
    return filtered


__all__ = [
    "RumourRecord",
    "fetch_rumour_trending",
]
