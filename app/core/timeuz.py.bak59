"""Toshkent vaqti (UTC+5) — kirish nuqtasi soniyagacha."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

TASHKENT = timezone(timedelta(hours=5))


def to_tashkent(dt: datetime | None = None) -> datetime:
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TASHKENT)


def format_tashkent(dt: datetime | None = None) -> str:
    """14.09.2026 21:25:43 (Toshkent)"""
    return to_tashkent(dt).strftime("%d.%m.%Y %H:%M:%S") + " (Toshkent)"
