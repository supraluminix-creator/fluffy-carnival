from scheduler.runner import build_scheduler


def test_build_scheduler_default_fallback(monkeypatch, tmp_path):
    # No YAML available -> defaults
    monkeypatch.delenv("SCHEDULER_CONFIG", raising=False)
    sched = build_scheduler()
    try:
        job_ids = {j.id for j in sched.get_jobs()}
        expected = {
            "macro",
            "onchain",
            "derivatives",
            "defi",
            "stablecoins",
            "sentiment",
            "tokenmetrics",
            "heavy_history",
        }
        assert expected.issubset(job_ids)
    finally:
        pass


def test_build_scheduler_from_yaml(monkeypatch, tmp_path):
    cfg = tmp_path / "jobs.yaml"
    cfg.write_text("jobs: []", encoding="utf-8")
    monkeypatch.setenv("SCHEDULER_CONFIG", str(cfg))
    sched = build_scheduler()
    try:
        # empty jobs -> fallback to defaults
        job_ids = {j.id for j in sched.get_jobs()}
        assert "macro" in job_ids and "heavy_history" in job_ids
    finally:
        pass
