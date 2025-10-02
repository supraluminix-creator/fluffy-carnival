from prompts.generator import generate_template, list_templates


def test_generate_template_basic():
    md = generate_template("ta", "analyst", {"max_tokens": 600})
    assert md.startswith("# Technical Analysis — Market Analyst")
    assert "## TL;DR" in md
    assert "Max tokens suggérés: 600" in md


def test_list_templates_keys():
    info = list_templates()
    assert "ta" in info["kinds"]
    assert "analyst" in info["roles"]
