"""Audit des usages HTTP legacy en dehors de la façade unifiée.

Objectif:
  - Lister les occurrences residuelles d'appels httpx.get / AsyncClient.get
    dans le code du dossier `pipeline/` qui ne passent pas par fetch_json / async_fetch_json.
  - Produire un rapport simple (stdout + option JSON) pour suivre la dette
    de migration vers la façade HTTP.

Usage:
  python -m pipeline.dev.audit_http [--json]

Stratégie:
  - Parcours récursif des fichiers .py sous pipeline/
  - Analyse lexicale simple (regex) pour détecter:
      httpx.get( ... )
      client.get( ... ) dans un contexte httpx.AsyncClient as client
  - Ignore:
      - fichiers sous pipeline/http.py, pipeline/http_wrappers.py (sources historiques)
      - lignes commentées (#) et chaînes multi-lignes triviales
      - occurrences déjà migrées basées sur fetch_json/async_fetch_json

Limites:
  - Heuristique légère (pas d'AST complet) mais suffisante pour repérage.
  - Peut produire des faux positifs si variable 'client' n'est pas un AsyncClient.

Sortie:
  - Tableau texte avec: fichier:ligne | extrait
  - Résumé final: total occurrences restantes.
  - Option --json: JSON list [{file, line, code}]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent  # pipeline/

# Patterns simples
PAT_HTTPX_GET = re.compile(r"(^|[^\w])httpx\.get\s*\(")
PAT_CLIENT_GET = re.compile(r"client\.get\s*\(")
# Utilisations façade (à ignorer)
PAT_FACADE = re.compile(r"(fetch_json|async_fetch_json)\s*\(")

IGNORE_SUBPATHS = {
    "http.py",
    "http_wrappers.py",
}


def scan_file(path: Path):
    findings: list[tuple[int, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return findings
    # Ignorer immédiatement si pas de 'get(' pour perf
    if "get(" not in text and "httpx.get" not in text:
        return findings
    for idx, line in enumerate(text.splitlines(), start=1):
        lstr = line.strip()
        if not lstr or lstr.startswith("#"):
            continue
        if "httpx.get" in lstr and PAT_HTTPX_GET.search(lstr):
            if PAT_FACADE.search(lstr):  # ligne mélange façade -> ignorer
                continue
            findings.append((idx, line.rstrip()))
            continue
        # Heuristique client.get
        if "client.get" in lstr and PAT_CLIENT_GET.search(lstr):
            if PAT_FACADE.search(lstr):
                continue
            findings.append((idx, line.rstrip()))
    return findings


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="Sortie JSON")
    args = ap.parse_args(argv)

    results: list[dict[str, Any]] = []
    for py in ROOT.rglob("*.py"):
        if any(py.name == ign for ign in IGNORE_SUBPATHS):
            continue
        rel = py.relative_to(ROOT.parent)  # remonter pour inclure 'pipeline/...'
        findings = scan_file(py)
        for line_no, code in findings:
            results.append({"file": str(rel), "line": line_no, "code": code})

    # Tri stable
    results.sort(key=lambda x: (x["file"], x["line"]))

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        if not results:
            print("[OK] Aucun usage HTTP legacy détecté (httpx.get / client.get)")
        else:
            width = max(len(r["file"]) for r in results)
            for r in results:
                print(f"{r['file']:<{width}}:{r['line']:>4} | {r['code']}")
            print(f"\nTotal occurrences legacy potentiellement non migrées: {len(results)}")
            print("(Vérifier les faux positifs éventuels — heuristique client.get)")
    return 0


if __name__ == "__main__":  # pragma: no cover - exécution manuelle
    raise SystemExit(main(sys.argv[1:]))
