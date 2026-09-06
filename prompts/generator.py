"""Markdown prompt generator for analyses and roles.

Public API
- generate_template(kind, role, options) -> str
- list_templates() -> dict

Kinds: ta, onchain, sentiment, quant, fundamentals, news
Roles: analyst, summarizer, dev, auditor

Options:
- max_tokens: int
- detail: low|normal|high
- sections: list[str] to include
"""

from __future__ import annotations

from dataclasses import dataclass

KIND_ALIASES = {
    "ta": "Technical Analysis",
    "onchain": "On-chain Analysis",
    "sentiment": "Sentiment Analysis",
    "quant": "Quantitative Analysis",
    "fundamentals": "Fundamental Analysis",
    "news": "News Analysis",
}

ROLE_ALIASES = {
    "analyst": "Market Analyst",
    "summarizer": "Summarizer",
    "dev": "Developer",
    "auditor": "Auditor",
}


@dataclass
class TemplateOptions:
    max_tokens: int = 800
    detail: str = "normal"  # low|normal|high
    sections: list[str] | None = None


def _header(title: str) -> str:
    return f"# {title}\n\n"


def _common_sections(kind_label: str, role_label: str, opts: TemplateOptions) -> list[str]:
    sections = [
        "## TL;DR\n- 3 bullets clés\n\n",
        "## Observations\n- Données principales\n- Signaux\n\n",
        "## Analyse\n- Interprétation\n- Contexte\n\n",
        "## Recommandations\n- Actions proposées\n- Risques\n\n",
    ]
    if opts.detail == "high":
        sections.append("## Annexes\n- Méthodo\n- Liens\n\n")
    return sections


def generate_template(kind: str, role: str, options: dict | None = None) -> str:
    k = kind.lower().strip()
    r = role.lower().strip()
    if k not in KIND_ALIASES:
        raise ValueError(f"Unsupported kind: {kind}")
    if r not in ROLE_ALIASES:
        raise ValueError(f"Unsupported role: {role}")
    opts = TemplateOptions(**(options or {}))
    title = f"{KIND_ALIASES[k]} — {ROLE_ALIASES[r]}"
    parts: list[str] = [_header(title)]
    # Context block
    parts.append("""> Contexte: Remplir avec les données brutes (prix, volumes, news, métriques on-chain).\n\n""")
    # Role guidance
    guidance = {
        "analyst": "Focalise sur les signaux et le timing. Évite la spéculation non sourcée.",
        "summarizer": "Condense l'information en puces claires, sans jargon.",
        "dev": "Propose des scripts ou pseudo-code pour reproduire l'analyse.",
        "auditor": "Vérifie les hypothèses, la qualité des données, et les biais.",
    }[r]
    parts.append(f"> Consignes rôle: {guidance}\n\n")

    # Kind-specific preface
    prefaces = {
        "ta": "Utilise support/résistance, divergences, RSI/MA/MACD avec horizon court/moyen terme.",
        "onchain": "Considère MVRV, NUPL, realised cap, flux miniers, cohortes UTXO.",
        "sentiment": "Analyse indicateurs (Fear&Greed, Twitter/Reddit), attention aux bulles sociales.",
        "quant": "Décris features, target, validation, et risques de surapprentissage.",
        "fundamentals": "Évalue tokenomics, gouvernance, émissions, trésorerie, compétiteurs.",
        "news": "Résume les faits, sources fiables, impact potentiel sur prix et liquidité.",
    }[k]
    parts.append(f"> Consignes analyse: {prefaces}\n\n")

    # Sections
    if opts.sections:
        parts.extend([f"## {s}\n\n" for s in opts.sections])
    else:
        parts.extend(_common_sections(KIND_ALIASES[k], ROLE_ALIASES[r], opts))

    # Footer with constraints
    parts.append(f"---\nMax tokens suggérés: {opts.max_tokens}\n")
    return "".join(parts)


def list_templates() -> dict[str, list[str]]:
    return {
        "kinds": list(KIND_ALIASES.keys()),
        "roles": list(ROLE_ALIASES.keys()),
    }


__all__ = ["generate_template", "list_templates", "TemplateOptions"]
