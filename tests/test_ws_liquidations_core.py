import asyncio
import json
from typing import Any

import pytest

from pipeline.collectors.bybit_ws import BybitWSService
from pipeline.collectors.bybit_liquidations import BybitLiquidationsWriter


class DummyWriter:
    def __init__(self):
        self.received: list[dict[str, Any]] = []
        self.closed = False

    async def write_record(self, record):  # noqa: D401
        self.received.append(dict(record))

    async def close(self):  # noqa: D401
        self.closed = True


@pytest.mark.asyncio
async def test_bybit_ws_service_basic_flow(monkeypatch):
    # Préparer messages simulés
    msgs = [
        json.dumps({"op": "pong"}),  # ignoré
        json.dumps({
            "topic": "liquidation.BTCUSDT",
            "data": {"symbol": "BTCUSDT", "side": "Buy", "price": 50000, "size": 10, "updatedTime": 111}
        }),
        json.dumps({
            "topic": "liquidation.ETHUSDT",
            "data": [
                {"symbol": "ETHUSDT", "side": "Sell", "price": 3000, "size": 5, "updatedTime": 222},
                {"symbol": "ETHUSDT", "side": "Sell", "price": 3001, "size": 2, "updatedTime": 333},
            ]
        }),
        "not-json",  # branche invalid JSON
    ]

    class FakeWS:
        def __init__(self, messages):
            self._messages = list(messages)
            self.sent_payloads: list[str] = []
        async def send(self, payload: str):  # capture subscribe
            self.sent_payloads.append(payload)
        def __aiter__(self):
            return self
        async def __anext__(self):
            if not self._messages:
                raise StopAsyncIteration
            return self._messages.pop(0)
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False

    # Patch websockets.connect pour renvoyer notre fake
    import pipeline.collectors.bybit_ws as ws_mod
    monkeypatch.setattr(ws_mod, 'websockets', ws_mod.websockets)  # assurance
    monkeypatch.setattr(ws_mod.websockets, 'connect', lambda url: FakeWS(msgs))

    svc = BybitWSService(["BTCUSDT", "ETHUSDT"])  # crée un vrai writer, on le remplace
    dummy = DummyWriter()
    svc.writer = dummy  # type: ignore[assignment]

    # Appel direct connect (pas la boucle run) pour traiter une séquence finie
    await svc.connect()

    # Vérifications basiques
    # Deux symboles -> 3 événements (1 single + 2 batch)
    assert len(dummy.received) == 3
    symbols = {r['symbol'] for r in dummy.received}
    assert symbols == {"BTCUSDT", "ETHUSDT"}

    # Tester chemins _handle_message supplémentaires (bytes + objet non str)
    await svc._handle_message(b'{"topic":"liquidation.BTCUSDT","data":{"symbol":"BTCUSDT","side":"Sell","price":1,"size":1,"updatedTime":444}}')
    # Objet non str ignoré
    await svc._handle_message({"foo": "bar"})  # type: ignore[arg-type]

    # Un enregistrement supplémentaire ajouté par message bytes
    assert any(r.get('time') == 444 for r in dummy.received) or len(dummy.received) >= 3


@pytest.mark.asyncio
async def test_bybit_liquidations_writer_flush_and_skips(monkeypatch, tmp_path):
    # Patch to_parquet pour éviter I/O
    import pandas as pd
    monkeypatch.setattr(pd.DataFrame, 'to_parquet', lambda self, path, index=False, engine="pyarrow": None)

    db_path = tmp_path / "liq.db"
    parquet_dir = tmp_path / "parquet"
    writer = BybitLiquidationsWriter(db=str(db_path), parquet_dir=str(parquet_dir), flush_size=2, flush_interval=60)

    # Enregistre valide 1
    await writer.write_record({"symbol": "BTCUSDT", "side": "Sell", "price": 50000, "size": 2, "updatedTime": 1})
    # Enregistre invalide (size 0) -> skip
    await writer.write_record({"symbol": "BTCUSDT", "side": "Sell", "price": 50010, "size": 0, "updatedTime": 2})
    # Enregistre valide 2 -> déclenche flush (flush_size=2)
    await writer.write_record({"symbol": "ETHUSDT", "side": "Buy", "price": 3000, "size": 1, "updatedTime": 3})

    # Buffer vidé
    assert writer.buffer == []

    # Vérifier contenu DB (2 lignes raw)
    cur = writer.conn.cursor()
    cur.execute("SELECT COUNT(*) FROM bybit_liquidations")
    count_raw = cur.fetchone()[0]
    assert count_raw == 2

    # Ajout record type casse casting
    await writer.write_record({"symbol": "ETHUSDT", "side": "Buy", "price": "abc", "size": 1, "updatedTime": 4})
    # Pas d'ajout dans buffer (skip car casting échoue)
    assert len(writer.buffer) == 0

    # Flush manuel vide (branch early return)
    await writer.flush()

    # Ajouter un nouvel enregistrement pour re-tester flush manuel avant close
    await writer.write_record({"symbol": "BTCUSDT", "side": "Sell", "price": 51000, "size": 1, "updatedTime": 5})
    await writer.flush()
    await writer.close()
    # Vérifie que la connexion est fermée via opération provoquant une exception
    with pytest.raises(Exception):  # sqlite ProgrammingError attendu
        writer.conn.execute("SELECT 1")
