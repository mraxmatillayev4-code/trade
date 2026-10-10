"""Timeframe yozilmagan kanal signali: qaysi TF zonada yurayotganini tanlash.

Misol: 'Gold buy 4339-29' — TF yo'q. Bot XAU ning 5m/15m/1h/4h (va bor bo'lsa
1m/30m/1d) shamlarini ko'radi: narx shu zonada yursa VA zona kengligi o'sha TF
ATR iga mos kelsa — o'sha timeframe ga signal.
"""
from __future__ import annotations

import math

from app.core.logging import get_logger

logger = get_logger(__name__)

_ALL_TF = ("1m", "5m", "15m", "30m", "1h", "4h", "1d")


def _atr14(df) -> float:
    if df is None or len(df) < 5:
        return 0.0
    n = min(14, len(df) - 1)
    trs: list[float] = []
    for i in range(len(df) - n, len(df)):
        h = float(df.iloc[i]["high"])
        l = float(df.iloc[i]["low"])
        prev = float(df.iloc[i - 1]["close"]) if i > 0 else h
        trs.append(max(h - l, abs(h - prev), abs(l - prev)))
    return sum(trs) / len(trs) if trs else 0.0


def score_zone_tf(df, zone_low: float, zone_high: float) -> float:
    """Narx zonada yurayaptimi + zona shu TF uchun mantiqiymi."""
    if df is None or len(df) < 3:
        return -1.0
    if zone_low > zone_high:
        zone_low, zone_high = zone_high, zone_low
    mid = (zone_low + zone_high) / 2.0
    zw = max(zone_high - zone_low, 1e-9)
    rec = df.iloc[-8:] if len(df) >= 8 else df
    close = float(df.iloc[-1]["close"])
    hi = float(rec["high"].max())
    lo = float(rec["low"].min())
    score = 0.0
    if zone_low <= close <= zone_high:
        score += 5.0
    else:
        dist = min(abs(close - zone_low), abs(close - zone_high), abs(close - mid))
        near = dist / max(abs(mid), 1.0)
        if near <= 0.002:
            score += 3.5
        elif near <= 0.006:
            score += 1.5
        else:
            return -1.0
    overlap = max(0.0, min(hi, zone_high) - max(lo, zone_low))
    if overlap > 0:
        score += 2.0 * min(1.0, overlap / zw)
    inside = 0
    for i in range(len(rec)):
        ch = float(rec.iloc[i]["high"])
        cl = float(rec.iloc[i]["low"])
        if min(ch, zone_high) > max(cl, zone_low):
            inside += 1
    score += 1.5 * (inside / max(len(rec), 1))
    atr = _atr14(df)
    if atr > 0 and zw > 0:
        ratio = zw / atr
        # zona ~ 0.3..3 ATR — shu TF da 'yurish' zonasi
        if 0.2 <= ratio <= 3.5:
            score += 3.0 * math.exp(-abs(math.log(max(ratio, 0.05))) ** 2)
        elif ratio < 0.2:
            score -= 0.5
        else:
            score -= 1.0
    return score


def infer_timeframe(
    symbol: str,
    *,
    zone_low: float | None,
    zone_high: float | None,
    entry: float | None,
    candles,
    tfs: list[str] | None = None,
) -> str | None:
    """Eng mos TF yoki None (ma'lumot yo'q)."""
    if candles is None:
        return None
    if zone_low is None or zone_high is None:
        if not entry:
            return None
        pad = max(abs(float(entry)) * 0.0008, 0.5)
        zone_low, zone_high = float(entry) - pad, float(entry) + pad
    zlo, zhi = float(zone_low), float(zone_high)
    order: list[str] = []
    for t in list(tfs or []) + list(_ALL_TF):
        tl = str(t).lower()
        if tl not in order:
            order.append(tl)
    best_tf = None
    best_sc = 0.0
    for tf in order:
        try:
            df = candles.get_df(symbol, tf, include_open=True)
        except Exception:  # noqa: BLE001
            df = None
        if df is None or getattr(df, "empty", False):
            continue
        sc = score_zone_tf(df, zlo, zhi)
        logger.info("[TF-MATCH] %s %s zona=%.2f-%.2f score=%.2f", symbol, tf, zlo, zhi, sc)
        if sc > best_sc:
            best_sc = sc
            best_tf = tf
    if best_tf:
        logger.info("[TF-MATCH] tanlandi %s %s (%.2f)", symbol, best_tf, best_sc)
    return best_tf
