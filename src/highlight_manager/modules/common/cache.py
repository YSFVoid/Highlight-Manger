from __future__ import annotations

from cachetools import TTLCache


class SimpleTTLCache:
    def __init__(self, maxsize: int = 256, ttl: int = 60) -> None:
        self._cache: TTLCache[str, object] = TTLCache(maxsize=maxsize, ttl=ttl)

    def get(self, key: str):
        return self._cache.get(key)

    def set(self, key: str, value: object) -> object:
        self._cache[key] = value
        return value

    def invalidate(self, key: str) -> None:
        self._cache.pop(key, None)

    def clear(self) -> None:
        self._cache.clear()
