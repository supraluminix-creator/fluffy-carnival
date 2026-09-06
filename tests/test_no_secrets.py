import re
from pathlib import Path

SENSITIVE_KEYS = [
    "DUNE_API_KEY",
    "COINMARKETCAP_API_KEY",
    "ETHERSCAN_API_KEY",
    "INFURA_API_KEY",
    "BINANCE_API_KEY",
    "BYBIT_API_KEY",
    "COINGECKO_API_KEY",
    "BITQUERY_API_KEY",
    "CRYPTOCOMPARE_API_KEY",
    "TOKEN_METRICS_API_KEY",
]


def test_env_file_placeholders():
    env_path = Path(".env")
    assert env_path.exists(), ".env doit exister (placeholder)"
    content = env_path.read_text(encoding="utf-8")
    for key in SENSITIVE_KEYS:
        pattern = re.compile(rf"^{key}=(.*)$", re.MULTILINE)
        m = pattern.search(content)
        assert m, f"Clé {key} absente"
        assert m.group(1).strip() == "REPLACE_ME", f"La clé {key} ne doit pas contenir une valeur réelle"

    # Heuristique: aucune longue chaîne hex > 48 char
    assert not re.search(r"[0-9a-fA-F]{48,}", content), "Hex longue potentielle trouvée dans .env"
