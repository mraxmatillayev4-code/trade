"""Strategiya 2 — Supertrend + EMA (kuchaytirilgan)."""
from __future__ import annotations

import pandas as pd

from app.core.config import Settings
from app.core.enums import Direction
from app.indicators.bundle import IndicatorBundle
from app.strategies.base import BaseStrategy, StrategyResult


class SupertrendEmaStrategy(BaseStrategy):
    key = "supertrend"
    display_name = "Supertrend + EMA"

    def analyze(self, df: pd.DataFrame, b: IndicatorBundle,
                settings: Settings, timeframe: str) -> StrategyResult:
        c = b.last_close
        st = float(b.supertrend_line.iloc[-1])
        st_dir = int(b.supertrend_dir.iloc[-1])
        st_dir_prev = int(b.supertrend_dir.iloc[-3]) if len(b.supertrend_dir) >= 3 else st_dir
        ema50 = float(b.ema50.iloc[-1])
        ema200 = float(b.ema200.iloc[-1])
        adx_v = float(b.adx.iloc[-1])
        vol = float(b.volume.iloc[-1])
        vol_ma = float(b.vol_ma.iloc[-1]) or 0.0
        atr_v = b.last_atr
        is_green = float(b.open_.iloc[-1]) <= c
        overbought_ext = (c - ema50) > 3.0 * atr_v
        oversold_ext = (ema50 - c) > 3.0 * atr_v

        indicators = {
            "Supertrend": round(st, 6),
            "ST_dir": "bullish" if st_dir == 1 else "bearish",
            "EMA50": round(ema50, 6), "EMA200": round(ema200, 6),
            "ADX": round(adx_v, 2),
        }

        buy_core = [
            ("Supertrend bullish", st_dir == 1),
            ("Sham Supertrend ustida yopildi", c > st),
            ("Narx EMA200 dan yuqori", c > ema200),
            ("EMA50 > EMA200 (trend tasdig'i)", ema50 > ema200),
            ("Sham yopilgan tasdig'i", True),
        ]
        buy_extra = [
            ("Yangi Supertrend flipi (so'nggi 3 sham)", st_dir_prev == -1 and st_dir == 1),
            ("ADX > 20", adx_v > 20),
            ("EMA200 qiyaligi yuqori", b.ema200_slope > 0),
            ("Hajm o'rtachadan yuqori", vol > vol_ma),
            ("Narx EMA50 dan yuqori", c > ema50),
            ("Narx EMA50 ga oqilona masofada (kech emas)", not overbought_ext),
        ]

        sell_core = [
            ("Supertrend bearish", st_dir == -1),
            ("Sham Supertrend ostida yopildi", c < st),
            ("Narx EMA200 dan past", c < ema200),
            ("EMA50 < EMA200 (trend tasdig'i)", ema50 < ema200),
            ("Sham yopilgan tasdig'i", True),
        ]
        sell_extra = [
            ("Yangi Supertrend flipi (so'nggi 3 sham)", st_dir_prev == 1 and st_dir == -1),
            ("ADX > 20", adx_v > 20),
            ("EMA200 qiyaligi past", b.ema200_slope < 0),
            ("Hajm o'rtachadan yuqori", vol > vol_ma),
            ("Narx EMA50 dan past", c < ema50),
            ("Narx EMA50 ga oqilona masofada (kech emas)", not oversold_ext),
        ]

        buy_pass = sum(1 for _, p in buy_core if p)
        sell_pass = sum(1 for _, p in sell_core if p)

        if buy_pass == len(buy_core):
            extra = sum(1 for _, p in buy_extra if p)
            return self._result(
                Direction.BUY, float(buy_pass), float(len(buy_core)), extra,
                f"BUY: Supertrend bullish, narx EMA200 ustida ({extra} qo'shimcha tasdiq)",
                buy_core + buy_extra, indicators,
            )
        if sell_pass == len(sell_core):
            extra = sum(1 for _, p in sell_extra if p)
            return self._result(
                Direction.SELL, float(sell_pass), float(len(sell_core)), extra,
                f"SELL: Supertrend bearish, narx EMA200 ostida ({extra} qo'shimcha tasdiq)",
                sell_core + sell_extra, indicators,
            )

        best = max(buy_pass, sell_pass)
        partial = best / len(buy_core) * 4.0
        side = "BUY" if buy_pass >= sell_pass else "SELL"
        checks = (buy_core + buy_extra) if side == "BUY" else (sell_core + sell_extra)
        return self._neutral(
            f"NEUTRAL: Supertrend {side} shartlari {best}/{len(buy_core)} bajarildi",
            checks, indicators, partial_score=partial,
        )
