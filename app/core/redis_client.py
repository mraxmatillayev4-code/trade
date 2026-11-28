"""Redis cache klienti (ixtiyoriy — ishlamasa tizim barqaror ishlayveradi)."""
from __future__ import annotations

import json
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

try:
    import redis.asyncio as aioredis
except ImportError:  # pragma: no cover
    aioredis = None


class RedisCache:
    """Oddiy JSON cache. Redis yo'q bo'lsa xotira (dict) fallback ishlaydi."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._redis: Any = None
        self._memory: dict[str, str] = {}

    async def connect(self) -> None:
        if aioredis is None or not self._url:
            logger.warning("Redis kutubxonasi yo'q — xotira cache ishlatiladi")
            return
        try:
            self._redis = aioredis.from_url(self._url, decode_responses=True)
            await self._redis.ping()
            logger.info("Redis cache ulandi: %s", self._url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis ulanmadi (%s) — xotira cache ishlatiladi", exc)
            self._redis = None

    async def close(self) -> None:
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:  # noqa: BLE001
                pass

    async def set_json(self, key: str, value: Any, ttl: int = 60) -> None:
        raw = json.dumps(value, default=str, ensure_ascii=False)
        try:
            if self._redis is not None:
                await self._redis.set(key, raw, ex=ttl)
            else:
                self._memory[key] = raw
        except Exception as exc:  # noqa: BLE001
            logger.debug("Redis set xatosi: %s", exc)

    async def get_json(self, key: str) -> Any | None:
        try:
            if self._redis is not None:
                raw = await self._redis.get(key)
            else:
                raw = self._memory.get(key)
            return json.loads(raw) if raw else None
        except Exception as exc:  # noqa: BLE001
            logger.debug("Redis get xatosi: %s", exc)
            return None
