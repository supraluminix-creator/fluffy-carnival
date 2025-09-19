from typing import Any

import requests  # type: ignore[import-untyped]


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
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return {
            "symbol": symbol,
            "price": data["market_data"]["current_price"]["usd"],
            "volume_24h": data["market_data"]["total_volume"]["usd"],
            "marketcap": data["market_data"]["market_cap"]["usd"],
            "dominance": data["market_data"].get("market_cap_rank", None)
        }
    except Exception:
        return None