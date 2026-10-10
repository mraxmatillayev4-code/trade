"""Strategiya 10 — OBV (On-Balance Volume) hajm oqimi tahlili."""
from __future__ import annotations

import pandas as pd

from app.core.config import Settings
from app.core.enums import Direction
from app.indicators.bundle import IndicatorBundle
from app.indicators.indicators import slope_pct
from app.strategies.base import BaseStrategy, StrategyResult


class ObvVolumeFlowStrategy(BaseStrategy):
    key = "obv"
    display_name = "OBV (hajm oqimi)"

    def analyze(self, df: pd.DataFrame, b: IndicatorBundle,
                settings: Settings, timeframe: str) -> StrategyResult:
        c = b.last_close
        obv_slope = slope_pct(b.obv, 10)       # oxirgi 10 shamda OBV o'zgarishi %
        obv_above_ma = float(b.obv.iloc[-1]) > float(b.obv_ma.iloc[-1])
        obv_ma_slope = slope_pct(b.obv_ma, 10)
        ema50 = float(b.ema50.iloc[-1])
        ema200 = float(b.ema200.iloc[-1])
        rsi_v = float(b.rsi.iloc[-1])
        vol = float(b.volume.iloc[-1])
        vol_ma = float(b.vol_ma.iloc[-1]) or 0.0
        adx_v = float(b.adx.iloc[-1])
        is_green = float(b.open_.iloc[-1]) <= c

        indicators = {
            "OBV slope (10)": round(obv_slope, 2),
            "OBV > MA(20)": obv_above_ma,
            "OBV MA slope": round(obv_ma_slope, 2),
            "RSI": round(rsi_v, 1),
        }

        buy_core = [
            ("OBV o'smoqda (musbat qiyalik)", obv_slope > 0),
            ("OBV o'rtachasidan yuqori (akkumulyatsiya)", obv_above_ma),
            ("Narx EMA200 dan yuqori", c > ema200),
            ("Sham yopilgan tasdig'i", True),
        ]
        buy_extra = [
            ("OBV kuchli o'sish (> 0.3%)", obv_slope > 0.3),
            ("OBV o'rtacha chizig'i ham o'smoqda", obv_ma_slope > 0),
            ("EMA50 > EMA200", ema50 > ema200),
            ("RSI > 50", rsi_v > 50),
            ("ADX > 20", adx_v > 20),
            ("Hajm o'rtachadan yuqori", vol > vol_ma),
            ("Yashil sham", is_green),
        ]

        sell_core = [
            ("OBV pasaymoqda (manfiy qiyalik)", obv_slope < 0),
            ("OBV o'rtachasidan past (distribyutsiya)", not obv_above_ma),
            ("Narx EMA200 dan past", c < ema200),
            ("Sham yopilgan tasdig'i", True),
        ]
        sell_extra = [
            ("OBV kuchli pasayish (< -0.3%)", obv_slope < -0.3),
            ("OBV o'rtacha chizig'i ham pasaymoqda", obv_ma_slope < 0),
            ("EMA50 < EMA200", ema50 < ema200),
            ("RSI < 50", rsi_v < 50),
            ("ADX > 20", adx_v > 20),
            ("Hajm o'rtachadan yuqori", vol > vol_ma),
            ("Qizil sham", not is_green),
        ]

        buy_pass = sum(1 for _, ok in buy_core if ok)
        sell_pass = sum(1 for _, ok in sell_core if ok)

        if buy_pass == len(buy_core):
            extra = sum(1 for _, ok in buy_extra if ok)
            return self._result(
                Direction.BUY, float(buy_pass), float(len(buy_core)), extra,
                f"BUY: hajm oqimi (OBV) xaridorlar tomonida ({extra} qo'shimcha)",
                buy_core + buy_extra, indicators,
            )
        if sell_pass == len(sell_core):
            extra = sum(1 for _, ok in sell_extra if ok)
            return self._result(
                Direction.SELL, float(sell_pass), float(len(sell_core)), extra,
                f"SELL: hajm oqimi (OBV) sotuvchilar tomonida ({extra} qo'shimcha)",
                sell_core + sell_extra, indicators,
            )

        best = max(buy_pass, sell_pass)
        partial = best / len(buy_core) * 4.0
        side = "BUY" if buy_pass >= sell_pass else "SELL"
        checks = (buy_core + buy_extra) if side == "BUY" else (sell_core + sell_extra)
        return self._neutral(
            f"NEUTRAL: OBV {side} shartlari {best}/{len(buy_core)}",
            checks, indicators, partial_score=partial,
        )
