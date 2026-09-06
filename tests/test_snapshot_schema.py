import json
from pathlib import Path

from jsonschema import validate

from scripts.snapshot_runtime import _serialize, build_snapshot  # type: ignore

SCHEMA_PATH = Path("schema/runtime_snapshot.schema.json")


def test_runtime_snapshot_schema_validation(monkeypatch):
    # Génère un snapshot réel (peut échouer si réseau down mais toléré via fallback assert minimal)
    data = build_snapshot()
    serialized = _serialize(data)  # type: ignore
    assert isinstance(serialized, list)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    # On valide seulement le premier élément si large; sinon tout
    try:
        validate(instance=serialized, schema=schema)
    except Exception as e:  # pragma: no cover - debug assist
        raise AssertionError(f"Schema validation failed: {e}") from e
