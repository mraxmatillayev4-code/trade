"""Faol strategiya 2 — Supertrend trend + retest (qayta tegish) kirishi.

- Trend yo'nalishi Supertrend + EMA200 bilan aniqlanadi.
- Kirish narx shunchaki trend tomonida bo'lganida EMAS, balki narx Supertrend
  chizig'iga QAYTA TEGIB (pullback/retest) yana trend yo'nalishida yopilganda.
- Bu stop-loss ni struktura yonida qisqa qo'yish va 1:2 ni osonroq olish imkonini beradi.
"""
from __future__ import annotations

import pandas as pd

from app.core.config import Settings
from app.core.enums import Direction
from app.indicators.bundle import IndicatorBundle
from app.strategies.base import BaseStrategy, StrategyResult


class SupertrendPullbackStrategy(BaseStrategy):
    key = "supertrend_pullback"
    display_name = "Supertrend Retest"

    TOUCH_ATR = 1.1        # Supertrend/EMA chizig'iga shuncha ATR masofada — "tegdi"
    MAX_EXTEND_ATR = 4.0

    def analyze(self, df: pd.DataFrame, b: IndicatorBundle,
                settings: Settings, timeframe: str) -> StrategyResult:
        c = float(b.last_close)
        o = float(b.open_.iloc[-1])
        st = float(b.supertrend_line.iloc[-1])
        st_dir = int(b.supertrend_dir.iloc[-1])
        ema200 = float(b.ema200.iloc[-1])
        ema50 = float(b.ema50.iloc[-1])
        adx_v = float(b.adx.iloc[-1])
        atr = b.last_atr or 1e-9
        is_green = c >= o
        is_red = c < o

        indicators = {
            "Supertrend": round(st, 6),
            "ST_dir": "bullish" if st_dir == 1 else "bearish",
            "EMA200": round(ema200, 6), "ADX": round(adx_v, 2), "ATR": round(atr, 6),
        }

        band = self.TOUCH_ATR * atr

        # ---- BUY ----
        up_trend = st_dir == 1 and c > ema200 and ema50 > ema200
        # so'nggi 4 shamda narx Supertrend yoki EMA50 ga qaytdi (kengroq band)
        lows = b.low.iloc[-4:].astype(float)
        closes = b.close.iloc[-4:].astype(float)
        touched_st = float(lows.min()) <= st + band or float(lows.min()) <= ema50 + band
        # narx retestdan so'ng Supertrend ustida barqaror (so'nggi yopilish ST dan yuqori)
        held = c > st
        buy_core = [
            ("Supertrend bullish + narx EMA200 ustida", up_trend),
            ("Narx Supertrend chizig'iga qaytdi (retest)", touched_st),
            ("Narx qaytib Supertrend ustida yopildi (davom)", held),
            ("Trend kuchi: ADX > 18", adx_v > 18),
        ]
        buy_extra = [
            ("EMA200 qiyaligi yuqori", b.ema200_slope > 0),
            ("Yashil tasdiq shami", is_green),
            ("Narx trenddan juda uzoq emas", (c - ema50) < self.MAX_EXTEND_ATR * atr),
        ]
        bp = sum(1 for _, p in buy_core if p)
        if bp == len(buy_core):
            ex = sum(1 for _, p in buy_extra if p)
            return self._result(
                Direction.BUY, float(bp), float(len(buy_core)), ex,
                f"BUY: Supertrend trendida retest + yashil tasdiq ({ex} qo'shimcha)",
                buy_core + buy_extra, indicators,
            )

        # ---- SELL ----
        dn_trend = st_dir == -1 and c < ema200 and ema50 < ema200
        highs = b.high.iloc[-4:].astype(float)
        touched_st_dn = float(highs.max()) >= st - band or float(highs.max()) >= ema50 - band
        held_dn = c < st
        sell_core = [
            ("Supertrend bearish + narx EMA200 ostida", dn_trend),
            ("Narx Supertrend chizig'iga qaytdi (retest)", touched_st_dn),
            ("Narx qaytib Supertrend ostida yopildi (davom)", held_dn),
            ("Trend kuchi: ADX > 18", adx_v > 18),
        ]
        sell_extra = [
            ("EMA200 qiyaligi past", b.ema200_slope < 0),
            ("Qizil tasdiq shami", is_red),
            ("Narx trenddan juda uzoq emas", (ema50 - c) < self.MAX_EXTEND_ATR * atr),
        ]
        sp = sum(1 for _, p in sell_core if p)
        if sp == len(sell_core):
            ex = sum(1 for _, p in sell_extra if p)
            return self._result(
                Direction.SELL, float(sp), float(len(sell_core)), ex,
                f"SELL: Supertrend trendida retest + qizil tasdiq ({ex} qo'shimcha)",
                sell_core + sell_extra, indicators,
            )

        best = max(bp, sp)
        side = "BUY" if bp >= sp else "SELL"
        partial = best / len(buy_core) * 4.0
        return self._neutral(
            f"NEUTRAL: Supertrend retest {side} {best}/{len(buy_core)}",
            (buy_core + buy_extra) if side == "BUY" else (sell_core + sell_extra),
            indicators, partial_score=partial,
        )
