from typing import Any

from pipeline.errors import SchemaError
from pipeline.http import fetch_json


def fetch_coingecko_price(symbol: str) -> dict[str, Any] | None:
    """
    Fetches price and market data for a given symbol from CoinGecko.

    Parameters
    ----------
    symbol : str
        Crypto symbol (e.g., 'bitcoin', 'ethereum').

    Returns
    -------
    Optional[Dict[str, Any]]
        Dictionary with price, volume, marketcap, dominance, etc.
    """
    url = f"https://api.coingecko.com/api/v3/coins/{symbol}"
    try:
        data = fetch_json(url, timeout=10)
        md = data.get("market_data", {}) if isinstance(data, dict) else {}
        if not isinstance(md, dict):
            raise SchemaError("invalid_market_data")
        return {
            "symbol": symbol,
            "price": md.get("current_price", {}).get("usd"),
            "volume_24h": md.get("total_volume", {}).get("usd"),
            "marketcap": md.get("market_cap", {}).get("usd"),
            "dominance": md.get("market_cap_rank", None),
        }
    except Exception:
        return None
