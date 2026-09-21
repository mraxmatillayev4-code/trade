"""Bozor ish vaqti (sessiya taqvimi).

Kripto (Bitcoin va boshqalar) — haftaning 7 kuni, 24/7 ochiq.
An'anaviy bozorlar (oltin, kumush, neft, gaz, forex) — real birja dam oladi:
  • Shanba kun bo'yi YOPIQ.
  • Yakshanba 22:00 UTC gacha yopiq (forex/oltin ~22:00 UTC = Toshkent dushanba 03:00 da ochiladi).
Yopiq vaqtda past likvidlik (sintetik narx sudraladi) — YANGI signal ochilmaydi;
ochiq bitimlar kuzatishda davom etadi (keyingi sessiyada TP/SL ishlaydi).

Vaqt UTC bilan hisoblanadi (MEXC/Binance sham vaqtlari UTC).
"""
from __future__ import annotations

from datetime import datetime, timezone

# An'anaviy (kripto emas) instrument asoslari — bular dam olish kunlari yopiladi.
_TRADITIONAL_BASES = frozenset({
    "XAU", "SILVER", "USOIL", "UKOIL", "NGAS", "COPPER",
    "EUR", "JPY", "GBP", "AUD", "CAD", "CHF", "NZD",
})

# Yakshanba kuni bozor shu UTC soatda ochiladi (forex/oltin standarti ~22:00 UTC).
_SUNDAY_OPEN_HOUR_UTC = 22


def _base(symbol: str) -> str:
    s = (symbol or "").upper()
    for q in ("USDT", "USDC", "BUSD", "FDUSD", "USD", "USD1"):
        if s.endswith(q) and len(s) > len(q):
            return s[: -len(q)]
    return s


def is_traditional(symbol: str) -> bool:
    """Bu instrument an'anaviy bozormi (oltin/neft/forex) — dam olish kuni yopiladimi."""
    return _base(symbol) in _TRADITIONAL_BASES


def is_market_open(symbol: str, when: datetime | None = None) -> bool:
    """Shu paytda bozor ochiqmi (yangi signal uchun).

    Kripto uchun har doim True. An'anaviy uchun:
    shanba (weekday=5) yoki yakshanba (weekday=6) 22:00 UTC dan oldin → False.
    """
    if not is_traditional(symbol):
        return True  # kripto — 24/7

    dt = when or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    wd = dt.weekday()  # 0=Dushanba ... 6=Yakshanba
    if wd == 5:  # shanba — yopiq
        return False
    if wd == 6 and dt.hour < _SUNDAY_OPEN_HOUR_UTC:  # yakshanba kechgacha yopiq
        return False
    return True


def market_status_label(symbol: str, when: datetime | None = None) -> str:
    """Inson o'qiy oladigan holat (xabarlar uchun)."""
    if not is_traditional(symbol):
        return "ochiq (24/7)"
    return "ochiq" if is_market_open(symbol, when) else "yopiq (dam olish kuni)"
