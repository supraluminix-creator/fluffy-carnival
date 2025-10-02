import json

from pipeline.tools import generate_sbom


def test_generate_sbom_json(tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setenv("SBOM_OUTPUT_DIR", out.as_posix())
    # Force JSON only
    monkeypatch.setenv("SBOM_FORMATS", "JSON")
    rc = generate_sbom.main([])
    assert rc == 0
    sbom_file = out / "sbom.json"
    assert sbom_file.exists()
    data = json.loads(sbom_file.read_text(encoding="utf-8"))
    assert data["bomFormat"] == "CycloneDX"
    assert data["specVersion"] == generate_sbom.SPEC_VERSION
    assert isinstance(data["components"], list)
    # Au moins 1 composant attendu (environnement tests possède dépendances)
    assert len(data["components"]) >= 1
    first = data["components"][0]
    assert {"name", "version", "purl"}.issubset(first.keys())
