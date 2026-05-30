"""In-memory TTL cache."""
from __future__ import annotations
import asyncio, time, hashlib
from typing import Any

class TTLCache:
    def __init__(self, default_ttl: int = 3600, max_entries: int = 20000):
        self._store: dict[str, tuple[float, Any]] = {}
        self._ttl = default_ttl
        self._max = max_entries
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if time.monotonic() > expires_at:
                self._store.pop(key, None)
                return None
            return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        async with self._lock:
            now = time.monotonic()
            expired = [k for k, (exp, _) in self._store.items() if now > exp]
            for k in expired:
                self._store.pop(k, None)
            while len(self._store) >= self._max:
                oldest = min(self._store, key=lambda k: self._store[k][0])
                self._store.pop(oldest)
            self._store[key] = (time.monotonic() + (ttl if ttl is not None else self._ttl), value)

    @property
    def size(self) -> int:
        return len(self._store)

    @staticmethod
    def hash_key(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:24]

cache = TTLCache()
