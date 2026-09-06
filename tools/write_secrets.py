#!/usr/bin/env python3
"""
Script interactif pour enregistrer des clés réelles dans .streamlit/secrets.toml
- Masque la saisie pour les champs sensibles
- Fusionne avec l'existant sans perdre les autres clés
- Conserve des valeurs si on appuie Entrée

Usage (PowerShell):
    .\\.venv\\Scripts\\python.exe tools\\write_secrets.py
"""

from __future__ import annotations

import getpass
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

try:
    import tomli_w  # type: ignore  # pour écrire TOML proprement
except Exception:  # pragma: no cover
    tomli_w = None

SECRETS_PATH = Path(".streamlit/secrets.toml")
SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)

# Champs sensibles probables (tu peux en ajouter si besoin)
SENSITIVE = {
    "BINANCE_API_KEY",
    "BYBIT_API_KEY",
    "CMC_API_KEY",
    "COINMARKETCAP_API_KEY",
    "COINGECKO_API_KEY",
    "CRYPTOCOMPARE_API_KEY",
    "DUNE_API_KEY",
    "ETHERSCAN_API_KEY",
    "INFURA_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "API_WRITE_KEY",
    "BITQUERY_API_KEY",
}

# Quelques champs non sensibles utiles à surcharger rapidement
NON_SENSITIVE_DEFAULTS: dict[str, str] = {
    "CRYPTO_MONITOR_MODE": "scheduler",
    "ENABLE_SCHEDULER": "1",
    "API_DOCS_ENABLED": "1",
    "ENABLE_HEALTH": "1",
    "ENABLE_METRICS": "0",
}


def load_existing() -> dict[str, str]:
    if SECRETS_PATH.exists():
        raw = SECRETS_PATH.read_bytes()
        data = tomllib.loads(raw.decode("utf-8"))
        # normaliser en str
        return {k: str(v) for k, v in data.items()}
    return {}


def prompt_var(name: str, current: str | None) -> str:
    label = f"{name}"
    if name in SENSITIVE:
        val = getpass.getpass(f"{label} [{'<set>' if current else ''}]: ")
    else:
        val = input(f"{label} [{current or ''}]: ")
    if not val:
        return current or ""
    return val


def save(data: dict[str, str]) -> None:
    # utiliser tomli_w si dispo, sinon écrire manuellement (clé = "val")
    if tomli_w:
        SECRETS_PATH.write_bytes(tomli_w.dumps(data).encode("utf-8"))
    else:
        lines = [f'{k} = "{v}"' for k, v in data.items()]
        SECRETS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    print(f"-- Écriture des secrets dans {SECRETS_PATH} --")
    data = load_existing()
    # Pré-remplir avec defaults non sensibles si absents
    for k, v in NON_SENSITIVE_DEFAULTS.items():
        data.setdefault(k, v)

    print("Entrez vos clés (laisser vide pour conserver la valeur actuelle):")
    # Proposer les plus communes d'abord
    order = [
        "API_WRITE_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "BINANCE_API_KEY",
        "BYBIT_API_KEY",
        "CMC_API_KEY",
        "COINMARKETCAP_API_KEY",
        "COINGECKO_API_KEY",
        "CRYPTOCOMPARE_API_KEY",
        "DUNE_API_KEY",
        "ETHERSCAN_API_KEY",
        "INFURA_API_KEY",
        "BITQUERY_API_KEY",
    ]
    for name in order:
        current = data.get(name)
        data[name] = prompt_var(name, current)

    # Optionnel: ajuste deux/trois options de confort
    for name in ["CRYPTO_MONITOR_MODE", "ENABLE_SCHEDULER", "ENABLE_METRICS"]:
        data[name] = prompt_var(name, data.get(name))

    save(data)
    print("✅ secrets.toml mis à jour. Tu peux lancer l'UI Streamlit.")


if __name__ == "__main__":
    main()
