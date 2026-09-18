"""Faol strategiya 3 — Squeeze breakout (Bollinger Keltner ichida siqilish → chiqish).

- Avval narx past volatillik "sikvez"ida bo'ladi (BB Keltner kanalining ichida).
- Sikvez bo'shaganda (BB kanaldan chiqib) narx bir yo'nalishda IMPULS bilan yopiladi.
- Momentum (linreg slope) va hajm tasdig'i bilan — bu klassik yuqori-ehtimollik
  breakout kirishi (John Carter TTM Squeeze mantig'i).
"""
from __future__ import annotations

import pandas as pd

from app.core.config import Settings
from app.core.enums import Direction
from app.indicators.bundle import IndicatorBundle
from app.strategies.base import BaseStrategy, StrategyResult


class SqueezeBreakoutStrategy(BaseStrategy):
    key = "squeeze_breakout"
    display_name = "Squeeze Breakout"

    def analyze(self, df: pd.DataFrame, b: IndicatorBundle,
                settings: Settings, timeframe: str) -> StrategyResult:
        c = float(b.last_close)
        o = float(b.open_.iloc[-1])
        atr = b.last_atr or 1e-9

        # squeeze Series: oxirgi sham bo'shagan, lekin oldingi ~6 shamda siqilish bo'lgan
        sq = b.squeeze
        was_squeezed = bool(sq.iloc[-7:-1].any()) if len(sq) >= 8 else False
        released = not bool(sq.iloc[-1])
        bb_up = float(b.bb_upper.iloc[-1])
        bb_lo = float(b.bb_lower.iloc[-1])

        mom = float(b.momentum_slope.iloc[-1]) if b.momentum_slope is not None else 0.0
        vol = float(b.volume.iloc[-1])
        vol_ma = float(b.vol_ma.iloc[-1]) or 0.0
        body = abs(c - o)
        impulsive = body >= 0.5 * atr
        is_green = c >= o

        indicators = {
            "was_squeezed": was_squeezed, "released": released,
            "BB_upper": round(bb_up, 6), "BB_lower": round(bb_lo, 6),
            "momentum": round(mom, 6), "ATR": round(atr, 6),
        }

        base = [
            ("Oldingi 6 shamda sikvez (BB Keltner ichida)", was_squeezed),
            ("Sikvez bo'shadi (BB kanaldan chiqdi)", released),
            ("Impuls sham (tana >= 0.5*ATR)", impulsive),
            ("Hajm ortdi (o'rtachadan yuqori)", vol > vol_ma),
        ]

        # ---- BUY: yuqoriga chiqish ----
        buy_core = base + [
            ("Sham BB yuqori chegarasidan yuqori yopildi", c > bb_up),
            ("Momentum qiyaligi musbat", mom > 0),
            ("Yashil impuls sham", is_green),
        ]
        buy_extra = [
            ("Hajm > 1.3x o'rtacha", vol > vol_ma * 1.3),
            ("Narx EMA200 dan yuqori (trend bilan)", c > float(b.ema200.iloc[-1])),
        ]
        bp = sum(1 for _, p in buy_core if p)
        if bp == len(buy_core):
            ex = sum(1 for _, p in buy_extra if p)
            return self._result(
                Direction.BUY, float(bp), float(len(buy_core)), ex,
                f"BUY: sikvezdan yuqoriga chiqish + momentum/hajm tasdig'i ({ex})",
                buy_core + buy_extra, indicators,
            )

        # ---- SELL: pastga chiqish ----
        sell_core = base + [
            ("Sham BB pastki chegarasidan past yopildi", c < bb_lo),
            ("Momentum qiyaligi manfiy", mom < 0),
            ("Qizil impuls sham", not is_green),
        ]
        sell_extra = [
            ("Hajm > 1.3x o'rtacha", vol > vol_ma * 1.3),
            ("Narx EMA200 dan past (trend bilan)", c < float(b.ema200.iloc[-1])),
        ]
        sp = sum(1 for _, p in sell_core if p)
        if sp == len(sell_core):
            ex = sum(1 for _, p in sell_extra if p)
            return self._result(
                Direction.SELL, float(sp), float(len(sell_core)), ex,
                f"SELL: sikvezdan pastga chiqish + momentum/hajm tasdig'i ({ex})",
                sell_core + sell_extra, indicators,
            )

        best = max(bp, sp)
        partial = best / len(buy_core) * 4.0
        side = "BUY" if bp >= sp else "SELL"
        return self._neutral(
            f"NEUTRAL: squeeze {side} shartlari {best}/{len(buy_core)}",
            (buy_core + buy_extra) if side == "BUY" else (sell_core + sell_extra),
            indicators, partial_score=partial,
        )
