"""Jonli holat (v61): narx manbasi va oxirgi tekshiruv vaqti.

Handlerlar (masalan `/kuzat`) bot yadrosidagi CandleManager/Birja klientlariga
to'g'ridan-to'g'ri yetib bormaydi — shuning uchun `main.Application` ishga
tushganda narx funksiyasini shu yerga "ulab" qo'yadi.
"""
from __future__ import annotations

from datetime import datetime, timezone

_price_provider = None
_last_check: dict[tuple[str, str], datetime] = {}
_last_error = ""


def set_price_provider(fn) -> None:
    """main.Application.price_for ni ulash."""
    global _price_provider
    _price_provider = fn


def has_price_provider() -> bool:
    return _price_provider is not None


async def get_price(symbol: str) -> float | None:
    """Oxirgi narx (1m sham yopilishi yoki birja tickeri)."""
    global _last_error
    if _price_provider is None:
        _last_error = "narx manbasi ulanmagan"
        return None
    try:
        px = await _price_provider(symbol)
    except Exception as exc:  # noqa: BLE001
        _last_error = f"{type(exc).__name__}: {exc}"
        return None
    try:
        px = float(px) if px is not None else None
    except (TypeError, ValueError):
        px = None
    if px and px > 0:
        _last_error = ""
        return px
    return None


def last_error() -> str:
    return _last_error


def note_check(symbol: str, timeframe: str, when: datetime | None = None) -> None:
    """Sham qayta ishlangan paytni yozib qo'yamiz (kuzatuv tirikligini ko'rsatadi)."""
    key = (str(symbol or "").upper(), str(timeframe or "").lower())
    _last_check[key] = when or datetime.now(timezone.utc)


def last_check(symbol: str, timeframe: str) -> datetime | None:
    return _last_check.get((str(symbol or "").upper(), str(timeframe or "").lower()))


def last_check_any() -> datetime | None:
    if not _last_check:
        return None
    return max(_last_check.values())


def snapshot() -> dict:
    return {
        "checks": {f"{k[0]} {k[1]}": v.isoformat() for k, v in _last_check.items()},
        "provider": _price_provider is not None,
        "error": _last_error,
    }
