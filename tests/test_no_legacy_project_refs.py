import pathlib


def test_no_legacy_project_references_in_code():
    root = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    legacy_markers = (
        "crypto_pipeline_core",
        "crypto_pipeline_v15_2",
        "MONOLITH",
        "monolithV1",
        "monolithV2",
        "monolithV3",
    )

    for py in (root / "pipeline").rglob("*.py"):
        if "__pycache__" in str(py):
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        # Autoriser les mentions en commentaires/docstrings ? On interdit de manière stricte
        offenders.extend(
            [(str(py), marker) for marker in legacy_markers if marker in text]
        )

    assert not offenders, (
        "Legacy project name(s) detected in pipeline code. Clean up references to focus on new_crypto_prodsafe.\n"
        + "\n".join(f"{p}: {m}" for p, m in offenders)
    )
