# pipeline/redis_cache.py
"""Redis cache with disk fallback for ML predictions."""

from __future__ import annotations

import json
import os
from typing import Any

import redis
from diskcache import Cache

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

class RedisCache:
    def __init__(self, fallback: Cache):
        self.redis = redis.from_url(REDIS_URL)
        self.fallback = fallback

    def set(self, key: str, value: Any, expire: int = 3600):
        try:
            self.redis.setex(key, expire, json.dumps(value))
        except Exception:
            self.fallback.set(key, value, expire=expire)

    def get(self, key: str) -> Any | None:
        try:
            data = self.redis.get(key)
            return json.loads(data) if data else None
        except Exception:
            return self.fallback.get(key)

    def close(self):
        self.redis.close()


__all__ = ["RedisCache"]
