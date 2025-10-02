"""Génération d'un SBOM CycloneDX minimal sans dépendance externe.

Produit un fichier JSON (optionnellement XML basique) listant les paquets Python
installés dans l'environnement courant. Objectif: visibilité supply chain
(ci artefact, diff possible entre runs).

Limitations:
 - Pas de graphe de dépendances (toutes marquées comme composants de premier niveau).
 - Pas de hash cryptographique.
 - Suffisant pour audit initial et intégration CI basique.

Env:
  SBOM_OUTPUT_DIR (defaut: sbom)
  SBOM_FORMATS=JSON[,XML]

Usage:
  python -m pipeline.tools.generate_sbom
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

SPEC_VERSION = "1.5"


def _now_iso():
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def build_components() -> list[dict[str, Any]]:
    comps: list[dict[str, Any]] = []
    for dist in metadata.distributions():  # type: ignore[attr-defined]
        name = dist.metadata.get("Name") or dist.metadata.get("name")
        if not name:
            continue
        version = dist.version
        purl = f"pkg:pypi/{name}@{version}".replace(" ", "-")
        comp: dict[str, Any] = {
            "type": "library",
            "name": name,
            "version": version,
            "purl": purl,
        }
        # Hash heuristique (concat contenu .py)
        try:
            dist_path = Path(dist.locate_file(""))
            h_sha = hashlib.sha256()
            if dist_path.exists():
                for f in dist_path.rglob("*.py"):
                    from contextlib import suppress
                    with suppress(Exception):
                        h_sha.update(f.read_bytes())
                comp["hashes"] = [{"alg": "SHA-256", "content": h_sha.hexdigest()}]
        except Exception:  # pragma: no cover
            pass
        # Dépendances déclarées (Requires-Dist)
        requires = dist.metadata.get_all("Requires-Dist") or []
        deps: list[str] = []
        for r in requires:
            part = r.split(";")[0].strip()
            base = part.split()[0]
            if base:
                deps.append(base)
        if deps:
            comp["dependencies"] = deps
        comps.append(comp)
    comps.sort(key=lambda c: c["name"].lower())
    return comps


def build_bom() -> dict[str, Any]:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": SPEC_VERSION,
        "version": 1,
        "metadata": {
            "timestamp": _now_iso(),
            "tools": [{"vendor": "internal", "name": "generate_sbom", "version": "0.1"}],
        },
        "components": build_components(),
    }


def write_json(path: Path, data: dict[str, Any]):
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def maybe_write_xml(path: Path, data: dict[str, Any]):  # pragma: no cover - xml optionnel
    try:
        from xml.etree.ElementTree import Element, SubElement, tostring
    except Exception:
        return
    b = Element("bom", attrib={"xmlns": "https://cyclonedx.org/schema/bom/1.5", "version": "1"})
    components_el = SubElement(b, "components")
    for comp in data.get("components", []):
        c = SubElement(components_el, "component", attrib={"type": "library"})
        SubElement(c, "name").text = comp.get("name")
        SubElement(c, "version").text = comp.get("version")
        SubElement(c, "purl").text = comp.get("purl")
    xml_bytes = tostring(b)
    path.write_bytes(xml_bytes)


def main(argv: list[str]) -> int:
    out_dir = Path(os.getenv("SBOM_OUTPUT_DIR", "sbom"))
    out_dir.mkdir(parents=True, exist_ok=True)
    formats = os.getenv("SBOM_FORMATS", "JSON").upper().split(",")
    bom = build_bom()
    if "JSON" in formats:
        write_json(out_dir / "sbom.json", bom)
    if "XML" in formats:
        maybe_write_xml(out_dir / "sbom.xml", bom)
    print(f"SBOM generated in {out_dir}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
