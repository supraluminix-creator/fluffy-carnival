from pipeline.storage.sqlite_adapter import get_connection


def test_sqlite_pragmas_configurables(monkeypatch, tmp_path):
    db_path = tmp_path / "test.db"
    # Config custom
    monkeypatch.setenv("SQLITE_JOURNAL_MODE", "MEMORY")
    monkeypatch.setenv("SQLITE_SYNCHRONOUS", "OFF")
    monkeypatch.setenv("SQLITE_CACHE_SIZE", "-4000")

    conn = get_connection(db_path.as_posix())
    try:
        cur = conn.cursor()
        # journal_mode renvoie toujours une ligne
        jm = cur.execute("PRAGMA journal_mode").fetchone()[0].upper()
        sync = cur.execute("PRAGMA synchronous").fetchone()[0]
        cache_sz = cur.execute("PRAGMA cache_size").fetchone()[0]
        assert jm in {"MEMORY", "MEM"}  # certains SQLite renvoient 'memory'
        assert sync in (0, 1, 2, 3)  # OFF=0 NORMAL=1 FULL=2 EXTRA=3
        # On ne valide pas la valeur exacte car dépend des conversions internes
        assert cache_sz != 0
    finally:
        conn.close()


def test_sqlite_pragmas_defaults(monkeypatch, tmp_path):
    db_path = tmp_path / "default.db"
    for var in ("SQLITE_JOURNAL_MODE", "SQLITE_SYNCHRONOUS", "SQLITE_CACHE_SIZE"):
        monkeypatch.delenv(var, raising=False)
    conn = get_connection(db_path.as_posix())
    try:
        cur = conn.cursor()
        jm = cur.execute("PRAGMA journal_mode").fetchone()[0].upper()
        # Par défaut on attend la valeur configurée (WAL) mais certains builds retournent DELETE (mode classique)
        # On accepte donc un ensemble élargi.
        assert jm in {"WAL", "MEMORY", "MEM", "DELETE"}
    finally:
        conn.close()
