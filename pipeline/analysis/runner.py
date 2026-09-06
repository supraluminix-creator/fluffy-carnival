"""Exécution d'analyses automatiques post-collecte.

Contrat minimal:
- Input: DataFrame consolidé (exports/latest_export.csv chargé)
- Output: dict avec 'signals' et 'insights' (texte LLM ou mock)
- Robustesse: best-effort, pas de crash pipeline
"""

from __future__ import annotations

# ruff: noqa: I001

import asyncio
import json
from collections import defaultdict
from contextlib import suppress
from pathlib import Path
from typing import Any

from integrations.ai_provider import AIClient
import structlog
from .dataset import load_latest_export
from .llm_exec import run_llm_analysis
from .signals import detect_signals


log = structlog.get_logger(__name__)


def _run_async(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        with suppress(Exception):
            asyncio.set_event_loop(None)


def _load_rumour_snapshot(path: str = "exports/rumour_latest.json") -> list[dict[str, Any]]:
    snapshot_path = Path(path)
    if not snapshot_path.exists():
        return []
    try:
        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    records = data.get("records") if isinstance(data, dict) else None
    if not isinstance(records, list):
        return []
    return [item for item in records if isinstance(item, dict)]


def _aggregate_rumour_signals(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not records:
        return []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in records:
        topic = str(rec.get("topic") or rec.get("symbol") or "narrative")
        grouped[topic].append(rec)
    aggregated: list[dict[str, Any]] = []
    for topic, items in grouped.items():
        try:
            confidences = [float(i.get("confidence") or i.get("confidence_score") or 0.0) for i in items]
            intensities = [float(i.get("value") or 0.0) for i in items]
        except Exception:
            continue
        if not confidences:
            continue
        avg_conf = sum(confidences) / max(1, len(confidences))
        avg_intensity = sum(intensities) / max(1, len(intensities))
        sentiment = next((str(i.get("sentiment")) for i in reversed(items) if i.get("sentiment")), "neutral")
        signal_type: str | None = None
        if avg_intensity >= 0.6:
            signal_type = "buy_rumour"
        elif avg_intensity <= -0.6:
            signal_type = "sell_news"
        if signal_type is None:
            continue
        type_name = "narrative_buy_signal" if signal_type == "buy_rumour" else "narrative_sell_signal"
        aggregated.append(
            {
                "type": type_name,
                "signal": signal_type,
                "topic": topic,
                "confidence": round(avg_conf, 3),
                "intensity": round(avg_intensity, 4),
                "sentiment": sentiment,
                "note": "NFA: Based on unverified narratives.",
                "source": "rumour.app",
            }
        )
    return aggregated


def _parse_json_payload(raw: str) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return None


async def _async_generate_text(client: AIClient, prompt: str, task: str, metadata: dict[str, Any] | None = None) -> str:
    metadata = metadata or {}
    result = await client.generate(prompt, max_tokens=512, metadata=metadata, task_type=task)
    output = result.get("content") or ""
    return output.strip()


async def _async_collect_legal_signals(client: AIClient) -> list[dict[str, Any]]:
    prompt_monitor = (
        "Liste les mises à jour récentes du droit crypto (France + UE) au format JSON. "
        "Réponds avec un tableau d'objets {topic, summary, risk_level}."
    )
    monitor_raw = await _async_generate_text(
        client,
        prompt_monitor,
        task="legal_monitor",
        metadata={"origin": "analysis_runner"},
    )
    monitor_payload = _parse_json_payload(monitor_raw) or []
    topics = [item.get("topic") for item in monitor_payload if isinstance(item, dict)]
    verify_prompt = (
        "Vérifie ces éléments et renvoie un objet JSON {topic: {verified: bool, note: string}} : "
        + json.dumps(topics, ensure_ascii=False)
    )
    verify_raw = await _async_generate_text(
        client,
        verify_prompt,
        task="legal_verify",
        metadata={"origin": "analysis_runner"},
    )
    verify_payload = _parse_json_payload(verify_raw) or {}
    signals: list[dict[str, Any]] = []
    for item in monitor_payload:
        if not isinstance(item, dict):
            continue
        topic = str(item.get("topic") or "")
        summary = str(item.get("summary") or item.get("note") or "")
        risk = item.get("risk_level")
        verification = verify_payload.get(topic) if isinstance(verify_payload, dict) else None
        verified = bool(verification.get("verified")) if isinstance(verification, dict) else False
        note = verification.get("note") if isinstance(verification, dict) else None
        signals.append(
            {
                "type": "legal_alert",
                "signal": "legal_alert",
                "topic": topic or "unspecified",
                "summary": summary,
                "risk_level": risk,
                "source": "perplexity",
                "verified": verified,
                "verified_by": "mistral" if verified else None,
                "verification_note": note,
                "disclaimer": "NFA: consultez un professionnel du droit.",
            }
        )
    return signals


async def _async_confirm_rumour_signals(client: AIClient, signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for signal in signals:
        topic = signal.get("topic") or signal.get("type") or "signal"
        prompt = (
            "Confirme l'analyse de sentiment suivante en JSON {agree: bool, sentiment: string, note: string}: "
            f"{json.dumps(signal, ensure_ascii=False)}"
        )
        try:
            response = await client.generate(
                prompt,
                max_tokens=256,
                metadata={"origin": "analysis_runner", "topic": topic},
                task_type="sentiment",
            )
            provider = response.get("provider") or ""
            content = response.get("content") or ""
            parsed = _parse_json_payload(content) or {}
            agree = parsed.get("agree") if isinstance(parsed, dict) else None
            sentiment = parsed.get("sentiment") if isinstance(parsed, dict) else None
            note = parsed.get("note") if isinstance(parsed, dict) else content
            updated = dict(signal)
            updated["llm_provider"] = provider
            if agree is not None:
                updated["llm_agree"] = bool(agree)
            if sentiment:
                updated["llm_sentiment"] = sentiment
            if note:
                updated["llm_note"] = note
            enriched.append(updated)
        except Exception as exc:  # pragma: no cover - network failure path
            log.warning("rumour_sentiment_confirmation_failed", error=str(exc), topic=topic)
            enriched.append(signal)
    return enriched


def build_prompt_from_signals(signals: list[dict[str, Any]]) -> str:
    if not signals:
        return (
            "Aucune alerte majeure détectée. Résume brièvement l'état du marché crypto "
            "en t'appuyant sur des indicateurs génériques (macro, on-chain, sentiment)."
        )
    lines = ["Synthétise les signaux suivants en un bref insight actionnable:"]
    for s in signals:
        t = s.get("type", "signal")
        msg = s.get("msg") or str(s)
        lines.append(f"- {t}: {msg}")
    return "\n".join(lines)


def run_automatic_analyses(path: str = "exports/latest_export.csv") -> dict[str, Any]:
    try:
        df = load_latest_export(path)
    except Exception as e:
        return {"status": "no_data", "error": str(e)}

    try:
        signals = detect_signals(df)
    except Exception:
        signals = []

    rumour_records = _load_rumour_snapshot()
    rumour_signals = _aggregate_rumour_signals(rumour_records)
    if rumour_signals:
        signals.extend(rumour_signals)

    client: AIClient | None = None
    try:
        client = AIClient()
    except Exception as exc:  # pragma: no cover
        log.warning("llm_client_init_failed", error=str(exc))
        client = None

    if client and rumour_signals:
        try:
            enriched = _run_async(_async_confirm_rumour_signals(client, rumour_signals))
            signals = [s for s in signals if s not in rumour_signals]
            signals.extend(enriched)
        except Exception as exc:  # pragma: no cover
            log.warning("llm_rumour_confirmation_error", error=str(exc))

    if client:
        try:
            legal_signals = _run_async(_async_collect_legal_signals(client))
            if legal_signals:
                signals.extend(legal_signals)
        except Exception as exc:  # pragma: no cover
            log.warning("legal_signal_collection_failed", error=str(exc))

    try:
        prompt = build_prompt_from_signals(signals)
        if client:
            insight = _run_async(
                _async_generate_text(
                    client,
                    prompt,
                    task="strategy",
                    metadata={"origin": "analysis_runner", "signals_count": len(signals)},
                )
            )
        else:
            insight = run_llm_analysis(prompt)
    except Exception as e:  # pragma: no cover
        insight = f"[analysis_error] {e}"

    return {
        "status": "ok",
        "signals": signals,
        "insight": insight,
    }
