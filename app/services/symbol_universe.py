# -*- coding: utf-8 -*-
"""v101: matnda symbol YOZILMAGAN scalp signalni jonli narxlar bo'yicha
qaysi juftlikka tegishli ekanini topadi (zero-key: binance public ticker).

Kanal faqat narx yozadi ("69-73", "15-12 buy") — symbol nomini aytmaydi.
Bot barcha USDT juftliklarining jonli narxini olib, zona/kirish narxiga
eng yaqinini tanlaydi (<=3%); topilmasa XAUUSDT qoladi.
"""
from __future__ import annotations

import re
import time

_CACHE: dict = {"t": 0.0, "rows": []}
_TTL = 120.0
_rest = None

_SYM_WORDS = re.compile(
    r"(xau|gold|oltin|silver|kumush|xag|btc|bitcoin|eth|ethereum|sol|bnb|doge|"
    r"ltc|litecoin|xrp|ripple|ada|cardano|dot|polkadot|link|avax|matic|trx|"
    r"ton|pepe|shib|floki|bonk|not|usdt|usdc|\bpair\b)", re.I)


def has_symbol_word(text: str) -> bool:
    return bool(_SYM_WORDS.search(text or ""))


def _client():
    global _rest
    if _rest is None:
        from app.market.gold_rest import GoldRest
        _rest = GoldRest()
    return _rest


async def universe_prices() -> list:
    now = time.time()
    if _CACHE["rows"] and now - _CACHE["t"] < _TTL:
        return _CACHE["rows"]
    try:
        raw = await _client().get_all_tickers()
    except Exception:  # noqa: BLE001
        return _CACHE["rows"]
    out = []
    for r in raw or []:
        sym = str(r.get("symbol") or "").replace("_", "")
        if not sym.endswith("USDT"):
            continue
        try:
            px = float(r.get("lastPrice") or 0.0)
            qv = float(r.get("amount24") or r.get("quoteVolume") or 0.0)
        except (TypeError, ValueError):
            continue
        if px > 0:
            out.append({"symbol": sym, "price": px, "qvol": qv})
    if out:
        _CACHE["t"] = now
        _CACHE["rows"] = out
    return _CACHE["rows"]


async def guess_symbol(price: float, tol: float = 0.03) -> str | None:
    """Zona/kirish narxiga mos juftlik (eng yaqin, likvidroq ustun)."""
    try:
        px = float(price or 0.0)
    except (TypeError, ValueError):
        return None
    if px <= 0:
        return None
    rows = await universe_prices()
    cand = []
    for r in rows:
        d = abs(r["price"] - px) / px
        if d <= tol:
            cand.append((d, -r["qvol"], r["symbol"]))
    if not cand:
        return None
    cand.sort()
    return cand[0][2]
