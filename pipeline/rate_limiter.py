"""
Global rate limiter for crypto APIs.

Provides token bucket rate limiters for different API tiers to prevent 429 errors.
Configured via scheduler/config.yaml with sensible defaults for major exchanges.
"""

from __future__ import annotations

from typing import Any

from aiolimiter import AsyncLimiter

# Default rate limits (requests per minute)
DEFAULT_RATE_LIMITS = {
    "binance": 1200,      # Binance: 1200 req/min
    "bybit": 600,         # Bybit: 600 req/min
    "coingecko": 50,      # CoinGecko: 50 req/min
    "coinmarketcap": 30,  # CMC: 30 req/min
    "etherscan": 5,       # Etherscan: 5 req/min
    "defillama": 100,     # DefiLlama: 100 req/min
    "bgeometrics": 300,   # BGeometrics: 300 req/min
    "default": 10,        # Conservative default
}

# Global limiter instances
_RATE_LIMITERS: dict[str, AsyncLimiter] = {}


def get_rate_limiter(api_name: str) -> AsyncLimiter:
    """
    Get or create a rate limiter for the specified API.

    Args:
        api_name: Name of the API (e.g., 'binance', 'coingecko')

    Returns:
        AsyncLimiter instance for the API
    """
    if api_name not in _RATE_LIMITERS:
        # Get rate limit from config or use default
        rate_limit = DEFAULT_RATE_LIMITS.get(api_name, DEFAULT_RATE_LIMITS["default"])
        _RATE_LIMITERS[api_name] = AsyncLimiter(rate_limit, 60)  # per minute

    return _RATE_LIMITERS[api_name]


async def acquire_rate_limit(api_name: str, amount: int = 1) -> None:
    """
    Acquire rate limit tokens for an API call.

    Args:
        api_name: Name of the API
        amount: Number of tokens to acquire (default: 1)

    Raises:
        Exception: If rate limit is exceeded (shouldn't happen with proper usage)
    """
    limiter = get_rate_limiter(api_name)
    await limiter.acquire(amount)


def get_rate_limiter_status() -> dict[str, dict[str, Any]]:
    """
    Get status of all rate limiters for monitoring.

    Returns:
        Dict mapping API names to their limiter status
    """
    status = {}
    for api_name in _RATE_LIMITERS:
        # Note: aiolimiter doesn't expose internal state easily
        # This is a basic status - could be enhanced
        status[api_name] = {
            "rate_limit": DEFAULT_RATE_LIMITS.get(api_name, DEFAULT_RATE_LIMITS["default"]),
            "active": True,  # Assume active if created
        }
    return status


def update_rate_limits(new_limits: dict[str, int]) -> None:
    """
    Update rate limits dynamically (for runtime configuration).

    Args:
        new_limits: Dict mapping API names to new rate limits (req/min)
    """
    global DEFAULT_RATE_LIMITS
    DEFAULT_RATE_LIMITS.update(new_limits)

    # Recreate limiters with new limits
    for api_name in list(_RATE_LIMITERS.keys()):
        if api_name in new_limits:
            new_limit = new_limits[api_name]
            _RATE_LIMITERS[api_name] = AsyncLimiter(new_limit, 60)
