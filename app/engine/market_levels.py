# -*- coding: utf-8 -*-
"""v100: kanal SL/TP aytmaganda darajalarni BOZORning o'zi beradi.

SL  — oxirgi 50 shamning swing nuqtasi ortida (support/resistance),
      agar swing juda yaqin (<1 pip) yoki juda uzoq (>300 pip) bo'lsa
      1.5 x ATR(14) ga o'tiladi;
TP  — riskning 2R / 3R / 4R karralari (2 lot sxemasiga mos),
      har biri <= 600 pip.
Bozor ma'lumoti bo'lmasa None qaytadi — chaqiruvchi eski 10/40/50 pip
qoidasini saqlab qoladi (user #60 zaxirasi).
"""
from __future__ import annotations


def _atr14(df) -> float:
    try:
        import pandas as pd
        h = df["high"].astype(float)
        lo = df["low"].astype(float)
        c = df["close"].astype(float)
        pc = c.shift(1)
        tr = pd.concat([(h - lo), (h - pc).abs(), (lo - pc).abs()],
                       axis=1).max(axis=1)
        v = float(tr.tail(14).mean())
        return v if v > 0 else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def market_levels(direction: str, entry: float, df, symbol: str,
                  lookback: int = 50) -> dict | None:
    """SL/TP ni bozordan hisoblaydi: {sl, tp1, tp2, tp3, risk, atr} | None."""
    from app.engine.sizing import pip_size
    e = float(entry or 0.0)
    if e <= 0 or df is None:
        return None
    try:
        if len(df) < 20:
            return None
        win = df.tail(lookback)
        swing_lo = float(win["low"].min())
        swing_hi = float(win["high"].max())
    except Exception:  # noqa: BLE001
        return None
    pip = pip_size(symbol)
    atr = _atr14(df)
    if atr <= 0:
        return None
    buy = str(direction or "").upper() == "BUY"
    risk_atr = min(max(1.5 * atr, 3.0 * pip), 300.0 * pip)
    if buy:
        sl = swing_lo - 0.5 * pip
        dist = e - sl
        if dist < 1.0 * pip or dist > 300.0 * pip:
            sl = e - risk_atr
    else:
        sl = swing_hi + 0.5 * pip
        dist = sl - e
        if dist < 1.0 * pip or dist > 300.0 * pip:
            sl = e + risk_atr
    risk = abs(e - sl)
    if risk < 1.0 * pip or risk > 300.0 * pip:
        return None
    sgn = 1.0 if buy else -1.0

    def _tp(k: float, floor_p: float) -> float:
        return max(min(k * risk, 600.0 * pip), floor_p)

    t1 = _tp(2.0, 10.0 * pip)
    t2 = max(_tp(3.0, 15.0 * pip), t1 + 5.0 * pip)
    t3 = max(_tp(4.0, 20.0 * pip), t2 + 5.0 * pip)
    return {"sl": sl, "tp1": e + sgn * t1, "tp2": e + sgn * t2,
            "tp3": e + sgn * t3, "risk": risk, "atr": atr}
