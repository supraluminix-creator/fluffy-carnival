from pipeline.maintenance import MaintenanceResult


def test_maintenance_skip_vacuum(monkeypatch, tmp_path):
    # ratio faible => pas de vacuum
    calls = {"vacuum": 0, "update": 0, "purge": 0}

    def fake_fragment(_):
        return (100, 5, 0.05)  # 5% < seuil 0.15

    def fake_vacuum(db_path):
        calls["vacuum"] += 1

    def fake_update(db_path):
        calls["update"] += 1

    def fake_purge(db_path):
        calls["purge"] += 1
        return {"bybit_liquidations": 1}

    monkeypatch.setenv("DB_FRAGMENTATION_VACUUM_THRESHOLD", "0.15")
    monkeypatch.setenv("MAINT_INTERVAL_SECONDS", "100")

    import pipeline.maintenance as maint
    import pipeline.purge_job as purge_job

    # Patch sur le module maintenance directement (les fonctions sont résolues à l'import)
    monkeypatch.setattr(maint, "vacuum_and_update_metrics", fake_vacuum, raising=True)
    monkeypatch.setattr(maint, "update_db_metrics", fake_update, raising=True)
    monkeypatch.setattr(purge_job, "purge_liquidations", fake_purge, raising=True)

    res: MaintenanceResult = maint.run_maintenance(db_path=str(tmp_path / "db.sqlite"), fragment_fn=fake_fragment)

    assert res.vacuum_performed is False
    assert calls["vacuum"] == 0
    # update_db_metrics appelé
    assert calls["update"] == 1
    assert res.fragmentation_ratio == 0.05
    assert res.next_run_ts > 0
    assert calls["purge"] == 1


def test_maintenance_with_vacuum(monkeypatch, tmp_path):
    calls = {"vacuum": 0, "update": 0}

    def high_fragment(_):
        return (100, 60, 0.6)  # 60% > seuil

    def fake_vacuum(db_path):
        calls["vacuum"] += 1

    def fake_update(db_path):
        calls["update"] += 1

    monkeypatch.setenv("DB_FRAGMENTATION_VACUUM_THRESHOLD", "0.15")
    monkeypatch.setenv("MAINT_INTERVAL_SECONDS", "50")

    import pipeline.maintenance as maint

    # Patch direct module maintenance
    monkeypatch.setattr(maint, "vacuum_and_update_metrics", fake_vacuum, raising=True)
    monkeypatch.setattr(maint, "update_db_metrics", fake_update, raising=True)

    res = maint.run_maintenance(db_path=str(tmp_path / "db.sqlite"), fragment_fn=high_fragment)

    assert res.vacuum_performed is True
    assert calls["vacuum"] == 1
    # update_db_metrics ne devrait pas être appelé lorsque vacuum exécuté (car vacuum wrapper le refait).
    assert calls["update"] == 0
    assert res.fragmentation_ratio == 0.6
    assert res.next_run_ts > 0
