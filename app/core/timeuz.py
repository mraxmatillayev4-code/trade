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


def now_tashkent() -> datetime:
    """Hozirgi Toshkent vaqti (tz-aware)."""
    return datetime.now(TASHKENT)


def hms_tashkent(dt: datetime | None = None) -> str:
    """16:38:18 — Toshkent (log/holat qatorlari uchun)."""
    return to_tashkent(dt).strftime("%H:%M:%S")


def stamp_tashkent(dt: datetime | None = None) -> str:
    """21.09.2026 16:38 — Toshkent (qisqa shtamp)."""
    return to_tashkent(dt).strftime("%d.%m.%Y %H:%M")


def format_short(dt: datetime | None = None) -> str:
    """21.09 16:38 (Toshkent) — ro'yxat qatorlari uchun."""
    return to_tashkent(dt).strftime("%d.%m %H:%M") + " (Toshkent)"
