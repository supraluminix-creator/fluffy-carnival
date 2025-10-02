"""Utilitaires d'export CSV centralisés."""
from __future__ import annotations

import csv
import hashlib
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import structlog

# Metrics import lazy-friendly: si prometheus indisponible ou non souhaité,
# les compteurs restent no-op (nous capturons exceptions d'importation).
try:  # pragma: no cover - chemin d'erreur improbable
    from pipeline.metrics import (
        EXPORT_ROW_REJECTIONS_TOTAL,
        EXPORT_ROWS_TOTAL,
        EXPORT_VALUE_NEGATIVE_TOTAL,
        EXPORTS_TOTAL,
    )
except Exception:  # pragma: no cover
    EXPORTS_TOTAL = None  # type: ignore
    EXPORT_ROWS_TOTAL = None  # type: ignore
    EXPORT_ROW_REJECTIONS_TOTAL = None  # type: ignore
    EXPORT_VALUE_NEGATIVE_TOTAL = None  # type: ignore

logger = structlog.get_logger(__name__)

EXPORT_FIELDS: Sequence[str] = (
    "timestamp",
    "asset",
    "symbol",
    "chain",
    "metric_name",
    "value",
    "source",
    "confidence_score",
)

try:
    from pydantic import BaseModel, Field, ValidationError
except Exception:  # pragma: no cover - pydantic absent (ne devrait pas arriver car dépendance)
    BaseModel = object  # type: ignore
    ValidationError = Exception  # type: ignore


class ExportRecord(BaseModel):  # type: ignore[misc]
    timestamp: str  # ISO8601 ou epoch str
    asset: str
    symbol: str
    chain: str | None = "-"
    metric_name: str
    value: float
    source: str
    confidence_score: float = Field(ge=0.0, le=1.0)

    # Normalisation légère possible ici (ex: upper asset) si besoin futur.

def _coerce_records(rows: Iterable[Mapping[str, Any]]) -> list[ExportRecord]:
    """Valide et normalise des enregistrements d'export.

    Stratégie de rétrocompat:
      - timestamp int/float accepté: converti en str
      - asset manquant: fallback symbol
      - symbol manquant: fallback asset
      - chain manquante: "-"
      - confidence_score manquant: 1.0 implicite pydantic
    Rejets:
      - value négative (compteurs dédiés)
      - schéma invalide malgré normalisation
    """
    validated: list[ExportRecord] = []
    def _coerce_value(metric_name: str, val: Any) -> float | None:
        # Déjà numérique
        if isinstance(val, int | float):
            try:
                return float(val)
            except Exception:
                return None
        # Chaîne convertible
        if isinstance(val, str):
            try:
                return float(val)
            except Exception:
                return None
        # Dictionnaire: choisir un champ principal selon metric
        if isinstance(val, dict):
            m = (metric_name or "").lower()
            # macro: prendre le prix USD si présent
            if ("macro" in m) or ("price_usd" in m):
                for k in ("price", "price_usd", "usd", "close"):
                    if k in val:
                        try:
                            return float(val[k])
                        except Exception:
                            pass
            # defi_tvl: prendre tvl
            if "defi" in m or "tvl" in m:
                for k in ("tvl", "total_value_locked"):
                    if k in val:
                        try:
                            return float(val[k])
                        except Exception:
                            pass
            # long_short_ratio: prendre buy_ratio
            if "long_short_ratio" in m or "lsr" in m:
                for k in ("buy_ratio", "buyRatio", "ratio", "longShortRatio"):
                    if k in val:
                        try:
                            return float(val[k])
                        except Exception:
                            pass
            # fear_greed: champ value (souvent string numérique)
            if "fear_greed" in m or "fear" in m:
                for k in ("value",):
                    if k in val:
                        try:
                            return float(val[k])
                        except Exception:
                            pass
            # Sinon: premier champ numérique trouvé
            for v in val.values():
                try:
                    return float(v)
                except Exception:
                    pass
        return None

    for r_in in rows:
        r = dict(r_in)  # copie modifiable
        # Normalisation légère avant validation
        ts = r.get("timestamp")
        if isinstance(ts, int | float):
            # convertir epoch numérique en str (non ISO pour ne pas changer logique aval)
            r["timestamp"] = str(ts)
        elif ts in (None, ""):
            # fallback ISO UTC si timestamp manquant
            r["timestamp"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        # Fallback asset<-symbol (legacy tests fournissent seulement symbol)
        if "asset" not in r and "symbol" in r:
            r["asset"] = r["symbol"]
        if "symbol" not in r and "asset" in r:
            r["symbol"] = r["asset"]
        # Si les deux manquent, tenter de déduire depuis chain, sinon fallback BTC
        if "asset" not in r and "symbol" not in r:
            chain_val = r.get("chain")
            mname = str(r.get("metric_name", "")).lower()
            if isinstance(chain_val, str) and chain_val and chain_val != "-":
                r["asset"] = chain_val
                r["symbol"] = chain_val
            elif ("fear" in mname) or ("greed" in mname):
                r["asset"] = "BTC"
                r["symbol"] = "BTC"
            else:
                r["asset"] = "BTC"
                r["symbol"] = "BTC"
        if "chain" not in r:
            r["chain"] = "-"
        if "source" not in r and "metric_name" in r:
            r["source"] = r["metric_name"]
        if "confidence_score" not in r:
            r["confidence_score"] = 1.0
        # Coercition de value (dict -> float principal)
        coerced = _coerce_value(str(r.get("metric_name", "")), r.get("value"))
        if coerced is not None:
            r["value"] = coerced
        try:
            rec = ExportRecord.model_validate(r)  # type: ignore[attr-defined]
            if rec.value < 0:
                logger.warning("export_record_negative_value", metric=rec.metric_name, value=rec.value)
                if EXPORT_VALUE_NEGATIVE_TOTAL is not None:
                    EXPORT_VALUE_NEGATIVE_TOTAL.labels(metric_name=rec.metric_name).inc()
                if EXPORT_ROW_REJECTIONS_TOTAL is not None:
                    EXPORT_ROW_REJECTIONS_TOTAL.labels(reason="negative_value").inc()
                continue
            validated.append(rec)
        except ValidationError as e:  # pragma: no cover
            logger.error("export_record_validation_error", errors=str(e), row=r_in)
            if EXPORT_ROW_REJECTIONS_TOTAL is not None:
                EXPORT_ROW_REJECTIONS_TOTAL.labels(reason="pydantic").inc()
    return validated


def export_csv_rows(rows: Iterable[Mapping[str, object]], filename: str) -> int:
    rows_list = list(rows)
    if not rows_list:
        logger.warning("No data to export", filename=filename)
        return 0
    validated = _coerce_records(rows_list)
    if not validated:
        logger.error("No valid rows after validation", filename=filename)
        return 0
    try:
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(EXPORT_FIELDS))
            writer.writeheader()
            for rec in validated:
                writer.writerow(rec.model_dump())  # type: ignore[attr-defined]
        logger.info("CSV export completed", filename=filename, rows=len(validated))
        if EXPORTS_TOTAL is not None:
            EXPORTS_TOTAL.labels(status="success").inc()
            EXPORT_ROWS_TOTAL.labels(status="success").inc(len(validated))  # type: ignore[union-attr]
        return len(validated)
    except Exception as e:  # pragma: no cover
        logger.error("CSV export failed", filename=filename, error=str(e))
        if EXPORTS_TOTAL is not None:
            EXPORTS_TOTAL.labels(status="error").inc()
            EXPORT_ROWS_TOTAL.labels(status="error").inc(0)  # type: ignore[union-attr]
        return 0


def export_latest_and_timestamped(
    rows: Iterable[Mapping[str, object]],
    export_dir: str = "exports",
    run_id: str | None = None,
) -> tuple[str | None, str | None]:
    rows = list(rows)
    if not rows:
        logger.info("No rows provided; skip export")
        return None, None
    validated = _coerce_records(rows)
    if not validated:
        logger.error("No valid rows after validation (latest/timestamped export)")
        return None, None
    os.makedirs(export_dir, exist_ok=True)
    latest_path = os.path.join(export_dir, "latest_export.csv")
    export_csv_rows(rows, latest_path)
    ts_name = f"pipeline_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if run_id:
        ts_name = f"{ts_name}_{run_id}"
    ts_path = os.path.join(export_dir, f"{ts_name}.csv")
    export_csv_rows(rows, ts_path)
    # Calcul hash SHA256 du fichier timestamped pour traçabilité
    try:
        sha256 = hashlib.sha256()
        with open(ts_path, "rb") as f:  # pragma: no cover - lecture simple
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        digest = sha256.hexdigest()
    except Exception as e:  # pragma: no cover - scénario I/O improbable
        logger.error("export_manifest_hash_error", error=str(e))
        digest = "error"

    # Manifeste append-only JSON Lines
    manifest_record = {
        "schema_version": 1,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "run_id": run_id,
        "row_count": len(validated),
        "latest_path": latest_path,
        "timestamped_path": ts_path,
        "sha256": digest,
        "columns": list(EXPORT_FIELDS),
    }
    manifest_path = os.path.join(export_dir, "export_manifest.jsonl")
    try:
        with open(manifest_path, "a", encoding="utf-8") as mf:
            mf.write(json.dumps(manifest_record, ensure_ascii=False) + "\n")
        logger.info("export_manifest_appended", manifest_path=manifest_path, row_count=len(rows))
    except Exception as e:  # pragma: no cover - ne doit pas bloquer export
        logger.error("export_manifest_write_error", error=str(e), manifest_path=manifest_path)
    return latest_path, ts_path


__all__ = ["export_latest_and_timestamped", "export_csv_rows", "EXPORT_FIELDS", "ExportRecord"]
