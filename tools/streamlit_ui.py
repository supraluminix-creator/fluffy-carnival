#!/usr/bin/env python3
"""
Streamlit UI (squelette) pour configurer le pipeline et générer un .env.

- Ne lance pas de collecte réseau. Sert uniquement d'assistant de configuration.
- Mappe les variables d'environnement documentées dans docs/PIPELINE_FEATURE_CATALOG.md.
- Exporte un bloc .env prêt à copier et peut écrire directement un fichier .env.

Lancer: streamlit run tools/streamlit_ui.py
"""
from __future__ import annotations

import json
import os
from contextlib import suppress
from typing import Any

import streamlit as st

# Valeurs par défaut pour toutes les variables exposées dans le catalogue
DEFAULTS: dict[str, str] = {
    # Global
    "CRYPTO_MONITOR_MODE": "scheduler",
    "ENABLE_SCHEDULER": "1",
    "SCHEDULER_CONFIG": "scheduler/jobs.yaml",
    "RUN_JOBS_AT_START": "1",
    "HEARTBEAT_SECS": "60",
    "SCHEDULER_JITTER_PERCENT": "10",
    "RUN_ID": "",
    "CB_THRESHOLD": "3",
    "CB_COOLDOWN_SECONDS": "30",
    # Observability
    "ENABLE_METRICS": "0",
    "METRICS_PORT": "9300",
    "ENABLE_HEALTH": "1",
    "HEALTH_PORT": "9310",
    "LOG_LEVEL": "INFO",
    "ENABLE_FILE_LOGS": "1",
    "LOGS_DIR": "logs",
    # HTTP/Breaker
    "RETRY_HTTP_ENABLED": "1",
    "RETRY_HTTP_MAX": "3",
    "RETRY_HTTP_BACKOFF_BASE": "0.3",
    "RETRY_MAX_CUMULATIVE_SLEEP_SEC": "0",
    "HTTP_BREAKER_WINDOW": "30",
    "HTTP_BREAKER_THRESHOLD": "5",
    "HTTP_BREAKER_COOLDOWN": "20",
    "RETRY_FORCE_THREAD": "0",
    "FORCE_HTTP_FACADE": "0",
    "DRY_RUN_FACADE": "0",
    # Collectors
    "ENABLE_BINANCE_SPOT_FALLBACK": "0",
    "ENABLE_BINANCE_MACRO_FALLBACK": "0",
    "ENABLE_BINANCE_OI_FALLBACK": "0",
    "BINANCE_HTTP_TIMEOUT": "5",
    "BINANCE_API_KEY": "",
    "MARKET_USE_FACADE": "0",
    "CMC_API_KEY": "",
    "ETHERSCAN_API_KEY": "",
    # Scheduler intervals
    "COLLECTOR_INTERVAL_MARKET": "300",
    "COLLECTOR_INTERVAL_DEFILLAMA": "900",
    "COLLECTOR_INTERVAL_ONCHAIN": "1800",
    "COLLECTOR_INTERVAL_DERIVATIVES": "300",
    "COLLECTOR_INTERVAL_SENTIMENT": "3600",
    # LLM
    "OPENAI_API_KEY": "",
    "OPENAI_MODEL": "gpt-4o-mini",
    "OPENAI_DAILY_LIMIT": "500",
    "OPENROUTER_API_KEY": "",
    "OPENROUTER_MODEL": "openrouter/auto",
    "OPENROUTER_DAILY_LIMIT": "500",
    "OLLAMA_HOST": "http://127.0.0.1:11434",
    "OLLAMA_MODEL": "llama3.1",
    "OLLAMA_DAILY_LIMIT": "10000",
    # API
    "API_DOCS_ENABLED": "1",
    "API_CORS_ENABLED": "0",
    "API_CORS_ORIGINS": "",
    "API_GZIP_ENABLED": "0",
    "API_GZIP_MIN_SIZE": "500",
    "API_MAX_BODY_BYTES": "0",
    "API_WRITE_KEY": "",
    "API_RATE_LIMIT_PER_MIN": "60",
    "API_RATE_LIMIT_BACKEND": "",
    "REDIS_URL": "",
    "API_REDIS_URL": "",
    "API_ENFORCE_HTTPS": "0",
    "API_READ_MAX_AGE": "0",
    # Export
    "EXPORT_DIR": "exports",
    # Maintenance / DB / Build
    "LIQ_RETENTION_DAYS": "30",
    "LIQ_PURGE_DRY_RUN": "0",
    "DB_FRAGMENTATION_VACUUM_THRESHOLD": "0.15",
    "FORCE_VACUUM": "0",
    "MAINT_INTERVAL_SECONDS": "86400",
    "SQLITE_JOURNAL_MODE": "WAL",
    "SQLITE_SYNCHRONOUS": "NORMAL",
    "SQLITE_CACHE_SIZE": "",
    "APP_VERSION": "dev",
    "GIT_SHA": "unknown",
    "STATE_DIR": "data",
    "TASK_ERROR_RATE_WARN": "0.2",
    "TASK_ERROR_RATE_MIN_COUNT": "5",
    "BREAKER_CRITICAL_LIST": "market,deriv_oi,onchain_txcount",
    "BREAKER_OPEN_GRACE_SECONDS": "120",
}

# Aide contextuelle pour chaque variable (info-bulles accessibles aux non-techs)
HELP: dict[str, str] = {
    # Global
    "CRYPTO_MONITOR_MODE": "Mode principal de l'application: 'scheduler' (tâches périodiques) ou 'cli' (commande ponctuelle).",
    "ENABLE_SCHEDULER": "Active le planificateur des collectes (tâches récurrentes).",
    "SCHEDULER_CONFIG": "Chemin vers le fichier des jobs (ex: scheduler/jobs.yaml).",
    "RUN_JOBS_AT_START": "Lance immédiatement les tâches au démarrage sans attendre le prochain créneau.",
    "HEARTBEAT_SECS": "Fréquence d'envoi du signal de vie (health beat), en secondes.",
    "SCHEDULER_JITTER_PERCENT": "Jitter (en %) appliqué aux délais pour éviter les bousculades synchronisées.",
    "RUN_ID": "Identifiant d'exécution pour tracer les logs/exports. Laisser vide pour auto.",
    "CB_THRESHOLD": "Seuil d'erreurs déclenchant l'ouverture du coupe-circuit (circuit breaker).",
    "CB_COOLDOWN_SECONDS": "Temps d'attente (s) avant une nouvelle tentative après ouverture du coupe-circuit.",
    # Observability
    "ENABLE_METRICS": "Expose des métriques Prometheus.",
    "METRICS_PORT": "Port d'écoute des métriques Prometheus.",
    "ENABLE_HEALTH": "Expose un endpoint de santé (readiness/liveness).",
    "HEALTH_PORT": "Port d'écoute du service de santé.",
    "LOG_LEVEL": "Niveau de logs (DEBUG, INFO, WARNING, ERROR).",
    "ENABLE_FILE_LOGS": "Écrit également les logs dans des fichiers (répertoire LOGS_DIR).",
    "LOGS_DIR": "Répertoire où les logs sont enregistrés si activé.",
    # HTTP/Breaker
    "RETRY_HTTP_ENABLED": "Réactive automatiquement certaines requêtes HTTP en cas d'échec temporaire.",
    "RETRY_HTTP_MAX": "Nombre maximum de tentatives par requête.",
    "RETRY_HTTP_BACKOFF_BASE": "Base du délai exponentiel entre tentatives (secondes).",
    "RETRY_MAX_CUMULATIVE_SLEEP_SEC": "Somme max des délais d'attente cumulés par requête (0 = illimité).",
    "HTTP_BREAKER_WINDOW": "Fenêtre de temps (s) utilisée pour observer les erreurs.",
    "HTTP_BREAKER_THRESHOLD": "Nombre d'erreurs dans la fenêtre pour ouvrir le coupe-circuit.",
    "HTTP_BREAKER_COOLDOWN": "Durée (s) pendant laquelle le coupe-circuit reste ouvert avant nouvel essai.",
    "RETRY_FORCE_THREAD": "Force l'exécution des retries dans un thread dédié (avancé).",
    "FORCE_HTTP_FACADE": "Force l'utilisation de la façade HTTP unifiée pour tous les appels.",
    "DRY_RUN_FACADE": "Mode simulation: ne fait pas d'appels réseau réels (pour tests).",
    # Collectors
    "ENABLE_BINANCE_SPOT_FALLBACK": "Active un plan B via Binance Spot si la source principale échoue.",
    "ENABLE_BINANCE_MACRO_FALLBACK": "Active un plan B pour indicateurs macro Binance.",
    "ENABLE_BINANCE_OI_FALLBACK": "Active un plan B pour l'Open Interest dérivés Binance.",
    "BINANCE_HTTP_TIMEOUT": "Délai d'attente max (s) par appel HTTP Binance.",
    "BINANCE_API_KEY": "Clé API Binance (si nécessaire pour certains endpoints).",
    "MARKET_USE_FACADE": "Utilise la façade HTTP pour le collecteur marché.",
    "CMC_API_KEY": "Clé API CoinMarketCap.",
    "ETHERSCAN_API_KEY": "Clé API Etherscan.",
    # Intervals
    "COLLECTOR_INTERVAL_MARKET": "Période en secondes entre deux exécutions du collecteur Marché.",
    "COLLECTOR_INTERVAL_DEFILLAMA": "Période (s) pour DeFiLlama.",
    "COLLECTOR_INTERVAL_ONCHAIN": "Période (s) pour données on-chain.",
    "COLLECTOR_INTERVAL_DERIVATIVES": "Période (s) pour dérivés (OI, funding...).",
    "COLLECTOR_INTERVAL_SENTIMENT": "Période (s) pour collectes de sentiment.",
    # LLM
    "OPENAI_API_KEY": "Clé API OpenAI.",
    "OPENAI_MODEL": "Nom du modèle OpenAI (ex: gpt-4o-mini).",
    "OPENAI_DAILY_LIMIT": "Budget quotidien maximum (unités internes).",
    "OPENROUTER_API_KEY": "Clé API OpenRouter.",
    "OPENROUTER_MODEL": "Modèle OpenRouter (ex: openrouter/auto).",
    "OPENROUTER_DAILY_LIMIT": "Budget quotidien maximum via OpenRouter.",
    "OLLAMA_HOST": "URL de l'instance Ollama locale (ex: http://127.0.0.1:11434).",
    "OLLAMA_MODEL": "Nom du modèle Ollama.",
    "OLLAMA_DAILY_LIMIT": "Budget quotidien maximum via Ollama.",
    # API
    "API_DOCS_ENABLED": "Active la documentation Swagger/Redoc.",
    "API_CORS_ENABLED": "Autorise des origines (navigateurs) externes à interagir avec l'API.",
    "API_CORS_ORIGINS": "Liste d'origines autorisées (séparées par virgules).",
    "API_GZIP_ENABLED": "Active la compression GZip des réponses.",
    "API_GZIP_MIN_SIZE": "Taille min (octets) d'une réponse pour activer GZip.",
    "API_MAX_BODY_BYTES": "Taille maximale (octets) d'un corps de requête accepté (0 = illimité).",
    "API_WRITE_KEY": "Clé d'écriture requise pour endpoints sensibles (laisser vide si non utilisé).",
    "API_RATE_LIMIT_PER_MIN": "Nombre maximum de requêtes par minute et par IP. 0 pour désactiver.",
    "API_RATE_LIMIT_BACKEND": "Backend de rate limiting (ex: redis).",
    "REDIS_URL": "URL Redis par défaut (si utilisée).",
    "API_REDIS_URL": "URL Redis spécifique à l'API (si différente).",
    "API_ENFORCE_HTTPS": "Force l'utilisation du HTTPS (recommandé en production).",
    "API_READ_MAX_AGE": "Cache max (s) côté client pour les endpoints GET.",
    # Export
    "EXPORT_DIR": "Répertoire de sortie des exports (CSV/Parquet...).",
    # Maintenance / DB / Build
    "LIQ_RETENTION_DAYS": "Nombre de jours de rétention des liquidations avant purge.",
    "LIQ_PURGE_DRY_RUN": "Purge à blanc: affiche ce qui serait supprimé sans toucher aux données.",
    "DB_FRAGMENTATION_VACUUM_THRESHOLD": "Fragmentation minimale (0-1) déclenchant un VACUUM.",
    "FORCE_VACUUM": "Force l'opération de VACUUM même si la fragmentation est faible.",
    "MAINT_INTERVAL_SECONDS": "Fréquence (s) des tâches de maintenance.",
    "SQLITE_JOURNAL_MODE": "Mode journal SQLite (ex: WAL).",
    "SQLITE_SYNCHRONOUS": "Niveau de synchronisation SQLite (FULL/NORMAL/OFF).",
    "SQLITE_CACHE_SIZE": "Taille du cache SQLite (laisser vide pour défaut).",
    "APP_VERSION": "Version applicative (pour traces et UI).",
    "GIT_SHA": "Hash Git court de la build (info).",
    "STATE_DIR": "Répertoire d'état/persistance (bases, caches...).",
    "TASK_ERROR_RATE_WARN": "Taux d'erreur (0-1) à partir duquel on déclenche un avertissement.",
    "TASK_ERROR_RATE_MIN_COUNT": "Taille minimale d'échantillon avant de calculer un taux d'erreur.",
    "BREAKER_CRITICAL_LIST": "Liste de tâches critiques (séparées par virgules) surveillées par le breaker.",
    "BREAKER_OPEN_GRACE_SECONDS": "Délai de grâce (s) après ouverture du breaker avant alerte forte.",
}

# Clés booléennes (affichées comme toggles)
BOOL_KEYS: set[str] = {
    "ENABLE_SCHEDULER",
    "RUN_JOBS_AT_START",
    "ENABLE_METRICS",
    "ENABLE_HEALTH",
    "ENABLE_FILE_LOGS",
    "RETRY_HTTP_ENABLED",
    "RETRY_FORCE_THREAD",
    "FORCE_HTTP_FACADE",
    "DRY_RUN_FACADE",
    "ENABLE_BINANCE_SPOT_FALLBACK",
    "ENABLE_BINANCE_MACRO_FALLBACK",
    "ENABLE_BINANCE_OI_FALLBACK",
    "API_DOCS_ENABLED",
    "API_CORS_ENABLED",
    "API_GZIP_ENABLED",
    "API_ENFORCE_HTTPS",
    "LIQ_PURGE_DRY_RUN",
    "FORCE_VACUUM",
}

# Import optionnel des schémas Pydantic pour validation à blanc
try:
    from pipeline.schemas import HealthResponse, HistoryMetaResponse, Report  # type: ignore
except Exception:  # pragma: no cover
    HealthResponse = HistoryMetaResponse = Report = None  # type: ignore


def _b(val: str) -> bool:
    return (val or "").strip().lower() in {"1", "true", "yes", "on"}


def _to_bool_str(v: bool) -> str:
    return "1" if v else "0"


def section_header(title: str) -> None:
    st.markdown(f"## {title}")


def env_input(key: str, label: str, help: str | None = None) -> None:
    default = os.getenv(key, DEFAULTS.get(key, ""))
    h = help if help is not None else HELP.get(key)
    if key in BOOL_KEYS:
        if key in st.session_state and isinstance(st.session_state.get(key), bool):
            # Utiliser la valeur existante (profil) sans passer 'value' pour éviter le warning Streamlit
            st.toggle(label, key=key, help=h)
        else:
            st.toggle(label, value=_b(default), key=key, help=h)
    else:
        if key in st.session_state:
            st.text_input(label, key=key, help=h)
        else:
            st.text_input(label, value=default, key=key, help=h)


def env_number(
    key: str,
    label: str,
    min_value: int | float | None = None,
    step: int | float | None = None,
    help: str | None = None,
) -> None:
    default = os.getenv(key, DEFAULTS.get(key, ""))
    # Décider du type numérique: float si une borne/step est float ou si la valeur par défaut contient un point
    use_float = isinstance(min_value, float) or isinstance(step, float) or ("." in str(default))
    try:
        if use_float:
            val = float(default)
        else:
            val = int(float(default))  # accepte "10" ou "10.0" en int
    except Exception:
        val = 0.0 if use_float else 0

    # Harmoniser les types de tous les arguments numériques
    if use_float:
        mv = float(min_value) if min_value is not None else None
        stp = float(step) if step is not None else None
        new_val = st.number_input(label, value=float(val), min_value=mv, step=stp, help=help or HELP.get(key))
    else:
        mv = int(min_value) if isinstance(min_value, (int, float)) and min_value is not None else None
        stp = int(step) if isinstance(step, (int, float)) and step is not None else None
        new_val = st.number_input(label, value=int(val), min_value=mv, step=stp, help=help or HELP.get(key))
    st.session_state[key] = str(new_val)


def collect_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for k, v in st.session_state.items():
        if k in DEFAULTS or k in BOOL_KEYS:
            if k in BOOL_KEYS and isinstance(v, bool):
                env[k] = _to_bool_str(v)
            else:
                env[k] = str(v)
    for k, v in DEFAULTS.items():
        env.setdefault(k, v)
    return env


def apply_profile(name: str) -> None:
    """Applique des presets simples pour local/dev/prod."""
    presets: dict[str, str] = {}
    if name == "local":
        presets = {
            "LOG_LEVEL": "DEBUG",
            "ENABLE_METRICS": "1",
            "ENABLE_HEALTH": "1",
            "API_DOCS_ENABLED": "1",
            "API_ENFORCE_HTTPS": "0",
            "RUN_JOBS_AT_START": "1",
        }
    elif name == "dev":
        presets = {
            "LOG_LEVEL": "DEBUG",
            "ENABLE_METRICS": "1",
            "ENABLE_HEALTH": "1",
            "API_DOCS_ENABLED": "1",
            "API_ENFORCE_HTTPS": "0",
            "API_READ_MAX_AGE": "60",
            "RUN_JOBS_AT_START": "1",
        }
    elif name == "prod":
        presets = {
            "LOG_LEVEL": "INFO",
            "ENABLE_METRICS": "1",
            "ENABLE_HEALTH": "1",
            "API_DOCS_ENABLED": "0",
            "API_ENFORCE_HTTPS": "1",
            "API_READ_MAX_AGE": "300",
            "RUN_JOBS_AT_START": "1",
        }
    for k, v in presets.items():
        if k in BOOL_KEYS:
            # Cast en booléen pour correspondre au widget toggle
            st.session_state[k] = _b(v) if isinstance(v, str) else bool(v)
        else:
            st.session_state[k] = v


def render_global() -> None:
    section_header("Global")
    env_input("CRYPTO_MONITOR_MODE", "Mode (scheduler/cli)")
    env_input("SCHEDULER_CONFIG", "Chemin jobs.yaml")
    env_input("RUN_ID", "RUN_ID (optionnel)")
    env_number("HEARTBEAT_SECS", "HEARTBEAT_SECS", min_value=1, step=1)
    env_number("SCHEDULER_JITTER_PERCENT", "SCHEDULER_JITTER_PERCENT", min_value=0, step=1)
    env_number("CB_THRESHOLD", "CB_THRESHOLD", min_value=1, step=1)
    env_number("CB_COOLDOWN_SECONDS", "CB_COOLDOWN_SECONDS", min_value=1, step=1)
    env_input("ENABLE_SCHEDULER", "ENABLE_SCHEDULER")
    env_input("RUN_JOBS_AT_START", "RUN_JOBS_AT_START")


def render_observability() -> None:
    section_header("Observabilité / Santé")
    env_input("ENABLE_METRICS", "ENABLE_METRICS")
    env_number("METRICS_PORT", "METRICS_PORT", min_value=1, step=1)
    env_input("ENABLE_HEALTH", "ENABLE_HEALTH")
    env_number("HEALTH_PORT", "HEALTH_PORT", min_value=1, step=1)
    env_input("LOG_LEVEL", "LOG_LEVEL")
    env_input("ENABLE_FILE_LOGS", "ENABLE_FILE_LOGS")
    env_input("LOGS_DIR", "LOGS_DIR")


def render_http() -> None:
    section_header("HTTP / Breaker")
    env_input("RETRY_HTTP_ENABLED", "RETRY_HTTP_ENABLED")
    env_number("RETRY_HTTP_MAX", "RETRY_HTTP_MAX", min_value=0, step=1)
    env_number("RETRY_HTTP_BACKOFF_BASE", "RETRY_HTTP_BACKOFF_BASE", min_value=0.0, step=0.1)
    env_number("RETRY_MAX_CUMULATIVE_SLEEP_SEC", "RETRY_MAX_CUMULATIVE_SLEEP_SEC", min_value=0.0, step=0.5)
    env_number("HTTP_BREAKER_WINDOW", "HTTP_BREAKER_WINDOW", min_value=1.0, step=1.0)
    env_number("HTTP_BREAKER_THRESHOLD", "HTTP_BREAKER_THRESHOLD", min_value=1, step=1)
    env_number("HTTP_BREAKER_COOLDOWN", "HTTP_BREAKER_COOLDOWN", min_value=1.0, step=1.0)
    env_input("RETRY_FORCE_THREAD", "RETRY_FORCE_THREAD")
    env_input("FORCE_HTTP_FACADE", "FORCE_HTTP_FACADE")
    env_input("DRY_RUN_FACADE", "DRY_RUN_FACADE")


def render_collectors() -> None:
    section_header("Collectors & Fallbacks")
    env_input("ENABLE_BINANCE_SPOT_FALLBACK", "ENABLE_BINANCE_SPOT_FALLBACK")
    env_input("ENABLE_BINANCE_MACRO_FALLBACK", "ENABLE_BINANCE_MACRO_FALLBACK")
    env_input("ENABLE_BINANCE_OI_FALLBACK", "ENABLE_BINANCE_OI_FALLBACK")
    env_number("BINANCE_HTTP_TIMEOUT", "BINANCE_HTTP_TIMEOUT", min_value=1.0, step=0.5)
    env_input("BINANCE_API_KEY", "BINANCE_API_KEY")
    env_input("MARKET_USE_FACADE", "MARKET_USE_FACADE")
    env_input("CMC_API_KEY", "CMC_API_KEY")
    env_input("ETHERSCAN_API_KEY", "ETHERSCAN_API_KEY")


def render_intervals() -> None:
    section_header("Intervalles du Scheduler (s)")
    env_number("COLLECTOR_INTERVAL_MARKET", "MARKET", min_value=30, step=30)
    env_number("COLLECTOR_INTERVAL_DEFILLAMA", "DEFILLAMA", min_value=60, step=60)
    env_number("COLLECTOR_INTERVAL_ONCHAIN", "ONCHAIN", min_value=300, step=60)
    env_number("COLLECTOR_INTERVAL_DERIVATIVES", "DERIVATIVES", min_value=60, step=30)
    env_number("COLLECTOR_INTERVAL_SENTIMENT", "SENTIMENT", min_value=300, step=60)


def render_llm() -> None:
    section_header("LLM Providers")
    env_input("OPENAI_API_KEY", "OPENAI_API_KEY")
    env_input("OPENAI_MODEL", "OPENAI_MODEL")
    env_number("OPENAI_DAILY_LIMIT", "OPENAI_DAILY_LIMIT", min_value=0, step=50)
    env_input("OPENROUTER_API_KEY", "OPENROUTER_API_KEY")
    env_input("OPENROUTER_MODEL", "OPENROUTER_MODEL")
    env_number("OPENROUTER_DAILY_LIMIT", "OPENROUTER_DAILY_LIMIT", min_value=0, step=50)
    env_input("OLLAMA_HOST", "OLLAMA_HOST")
    env_input("OLLAMA_MODEL", "OLLAMA_MODEL")
    env_number("OLLAMA_DAILY_LIMIT", "OLLAMA_DAILY_LIMIT", min_value=0, step=100)


def render_api() -> None:
    section_header("API FastAPI")
    env_input("API_DOCS_ENABLED", "API_DOCS_ENABLED")
    env_input("API_CORS_ENABLED", "API_CORS_ENABLED")
    env_input("API_CORS_ORIGINS", "API_CORS_ORIGINS")
    env_input("API_GZIP_ENABLED", "API_GZIP_ENABLED")
    env_number("API_GZIP_MIN_SIZE", "API_GZIP_MIN_SIZE", min_value=0, step=100)
    env_number("API_MAX_BODY_BYTES", "API_MAX_BODY_BYTES", min_value=0, step=1024)
    env_input("API_WRITE_KEY", "API_WRITE_KEY")
    env_number("API_RATE_LIMIT_PER_MIN", "API_RATE_LIMIT_PER_MIN", min_value=0, step=10)
    env_input("API_RATE_LIMIT_BACKEND", "API_RATE_LIMIT_BACKEND")
    env_input("REDIS_URL", "REDIS_URL")
    env_input("API_REDIS_URL", "API_REDIS_URL")
    env_input("API_ENFORCE_HTTPS", "API_ENFORCE_HTTPS")
    env_number("API_READ_MAX_AGE", "API_READ_MAX_AGE", min_value=0, step=60)


def render_export() -> None:
    section_header("Export / Reporting")
    env_input("EXPORT_DIR", "EXPORT_DIR")


def render_maintenance_db() -> None:
    section_header("Maintenance / DB / Build")
    env_number("LIQ_RETENTION_DAYS", "LIQ_RETENTION_DAYS", min_value=1, step=1)
    env_input("LIQ_PURGE_DRY_RUN", "LIQ_PURGE_DRY_RUN")
    env_number(
        "DB_FRAGMENTATION_VACUUM_THRESHOLD",
        "DB_FRAGMENTATION_VACUUM_THRESHOLD",
        min_value=0.0,
        step=0.05,
    )
    env_input("FORCE_VACUUM", "FORCE_VACUUM")
    env_number("MAINT_INTERVAL_SECONDS", "MAINT_INTERVAL_SECONDS", min_value=60, step=60)
    env_input("SQLITE_JOURNAL_MODE", "SQLITE_JOURNAL_MODE")
    env_input("SQLITE_SYNCHRONOUS", "SQLITE_SYNCHRONOUS")
    env_input("SQLITE_CACHE_SIZE", "SQLITE_CACHE_SIZE")
    env_input("APP_VERSION", "APP_VERSION")
    env_input("GIT_SHA", "GIT_SHA")
    env_input("STATE_DIR", "STATE_DIR")
    env_number("TASK_ERROR_RATE_WARN", "TASK_ERROR_RATE_WARN", min_value=0.0, step=0.05)
    env_number("TASK_ERROR_RATE_MIN_COUNT", "TASK_ERROR_RATE_MIN_COUNT", min_value=1, step=1)
    env_input("BREAKER_CRITICAL_LIST", "BREAKER_CRITICAL_LIST")
    env_number("BREAKER_OPEN_GRACE_SECONDS", "BREAKER_OPEN_GRACE_SECONDS", min_value=0.0, step=1.0)


def to_env_block(env: dict[str, str]) -> str:
    lines: list[str] = []
    for k in sorted(env.keys()):
        v = env[k]
        if any(ch in v for ch in [" ", ":", "="]):
            v = f'"{v}"'
        lines.append(f"{k}={v}")
    return "\n".join(lines)


def _render_validation_tab() -> None:
    st.subheader("Validation à blanc (Pydantic)")
    st.caption("Valide des payloads contre les modèles Pydantic sans appel réseau.")
    available: dict[str, Any] = {}
    if Report is not None:
        available["Report"] = Report
    if HealthResponse is not None:
        available["HealthResponse"] = HealthResponse
    if HistoryMetaResponse is not None:
        available["HistoryMetaResponse"] = HistoryMetaResponse
    if not available:
        st.info("Modèles indisponibles dans l'environnement.")
        return
    model_name = st.selectbox("Modèle", list(available.keys()))
    default_samples = {
        "HealthResponse": json.dumps({"status": "ok", "details": {}}, indent=2),
        "HistoryMetaResponse": json.dumps({"page": 1, "page_size": 10, "total": 0}, indent=2),
        "Report": json.dumps({"title": "Sample", "items": []}, indent=2),
    }
    sample = default_samples.get(model_name, "{}")
    raw = st.text_area("Payload JSON", value=sample, height=220)
    if st.button("Valider"):
        with suppress(Exception):
            parsed = json.loads(raw)
            model_cls = available[model_name]
            try:
                obj = model_cls(**parsed)  # type: ignore[call-arg]
                # pydantic v2
                output = obj.model_dump_json() if hasattr(obj, "model_dump_json") else json.dumps(parsed)
                st.success("Validation OK ✅")
                st.json(json.loads(output))
            except Exception as e:  # pydantic validation error
                st.error(f"Validation échouée: {e}")


def main() -> None:
    st.set_page_config(page_title="Crypto Pipeline Config", layout="wide")
    st.title("Assistant de configuration – Crypto Pipeline")
    st.caption("Générez un fichier .env proprement sans toucher au code.")

    with st.sidebar:
        st.header("Actions")
        if st.button("Réinitialiser valeurs par défaut", help="Remet toutes les valeurs aux paramètres conseillés."):
            st.session_state.clear()
        profile = st.selectbox("Profil", ["local", "dev", "prod"], index=0, help="Pré-réglages rapides: local (débogage), dev (intégration), prod (sécurisé).")
        if st.button("Appliquer profil", help="Applique le profil sélectionné aux champs ci-dessous."):
            apply_profile(profile)
        st.write("Aperçu rapide (lecture seule)")
        run_id_preview = st.session_state.get("RUN_ID", os.getenv("RUN_ID", DEFAULTS["RUN_ID"]))
        metrics_port_preview = st.session_state.get(
            "METRICS_PORT", os.getenv("METRICS_PORT", DEFAULTS["METRICS_PORT"])
        )
        health_port_preview = st.session_state.get(
            "HEALTH_PORT", os.getenv("HEALTH_PORT", DEFAULTS["HEALTH_PORT"])
        )
        st.text(f"RUN_ID: {run_id_preview}")
        st.text(f"METRICS_PORT: {metrics_port_preview}")
        st.text(f"HEALTH_PORT: {health_port_preview}")

    tabs = st.tabs(
        [
            "Global",
            "Observabilité",
            "HTTP/Breaker",
            "Collectors",
            "Intervalles",
            "LLM",
            "API",
            "Export",
            "Maintenance/DB/Build",
            "Validation",
        ]
    )
    with tabs[0]:
        render_global()
    with tabs[1]:
        render_observability()
    with tabs[2]:
        render_http()
    with tabs[3]:
        render_collectors()
    with tabs[4]:
        render_intervals()
    with tabs[5]:
        render_llm()
    with tabs[6]:
        render_api()
    with tabs[7]:
        render_export()
    with tabs[8]:
        render_maintenance_db()
    with tabs[9]:
        _render_validation_tab()

    st.divider()
    env = collect_env()
    env_block = to_env_block(env)
    st.subheader("Générer .env")
    st.code(env_block, language="dotenv")
    st.caption("Copiez-collez dans un fichier .env à la racine du projet.")
    if st.button("Exporter vers .env (écrire sur disque)", help="Crée/écrase le fichier .env à la racine avec la configuration affichée."):
        try:
            with open(".env", "w", encoding="utf-8") as f:
                f.write(env_block + "\n")
            st.success("Fichier .env écrit à la racine du projet.")
        except Exception as e:
            st.error(f"Échec d'écriture du .env: {e}")


if __name__ == "__main__":
    main()
