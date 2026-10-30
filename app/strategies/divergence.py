"""Strategiya 5 — RSI Divergence (tasdiqlangan pivotlar, repaint yo'q)."""
from __future__ import annotations

import pandas as pd

from app.core.config import Settings
from app.core.enums import Direction
from app.indicators import indicators as ind
from app.indicators.bundle import IndicatorBundle
from app.strategies.base import BaseStrategy, StrategyResult


class RsiDivergenceStrategy(BaseStrategy):
    key = "divergence"
    display_name = "RSI Divergence"

    def analyze(self, df: pd.DataFrame, b: IndicatorBundle,
                settings: Settings, timeframe: str) -> StrategyResult:
        c = b.last_close
        open_ = float(b.open_.iloc[-1])
        rsi_v = float(b.rsi.iloc[-1])
        rsi_prev = float(b.rsi.iloc[-2])
        macd_h = float(b.macd_hist.iloc[-1])
        macd_h_prev = float(b.macd_hist.iloc[-2])
        vol = float(b.volume.iloc[-1])
        vol_ma = float(b.vol_ma.iloc[-1]) or 0.0
        atr_v = b.last_atr

        direction, div = ind.detect_divergence(
            b.high, b.low, b.close, b.rsi,
            lookback=90, oversold=45.0, overbought=55.0,
        )

        indicators = {
            "RSI": round(rsi_v, 2),
            "divergence": div.get("type") if div else None,
            "pivot_rsi_old": round(div.get("pivot1_rsi", 0), 2) if div else None,
            "pivot_rsi_new": round(div.get("pivot2_rsi", 0), 2) if div else None,
        }
        is_green = open_ <= c

        if direction == "BUY":
            core = [
                ("Bullish divergence: narx Lower Low, RSI Higher Low", True),
                ("RSI pivot zonasi < 45 (oversold hudud)", True),
                ("Tasdiq sham: yashil yopilish", is_green),
                ("Momentum burilishi: MACD gist. o'smoqda", macd_h > macd_h_prev),
                ("RSI ko'tarilmoqda", rsi_v > rsi_prev),
                ("Sham yopilgan tasdig'i", True),
            ]
            extra = [
                ("Tasdiq shamida hajm o'rtachadan yuqori", vol > vol_ma),
                ("RSI 40 darajadan yuqoriga chiqdi", rsi_v > 40),
                ("MACD gist. musbat", macd_h > 0),
                ("Sham kengligi >= 0.5*ATR", (float(b.high.iloc[-1]) - float(b.low.iloc[-1])) >= 0.5 * atr_v),
            ]
            passed = sum(1 for _, p in core if p)
            if passed == len(core):
                ex = sum(1 for _, p in extra if p)
                return self._result(
                    Direction.BUY, float(passed), float(len(core)), ex,
                    f"BUY: bullish RSI divergensiyasi tasdiqlandi ({ex} qo'shimcha)",
                    core + extra, indicators,
                )
            return self._neutral(
                f"NEUTRAL: bullish divergence bor, lekin tasdiq {passed}/{len(core)}",
                core + extra, indicators, partial_score=passed / len(core) * 4.0,
            )

        if direction == "SELL":
            core = [
                ("Bearish divergence: narx Higher High, RSI Lower High", True),
                ("RSI pivot zonasi > 55 (overbought hudud)", True),
                ("Tasdiq sham: qizil yopilish", not is_green),
                ("Momentum burilishi: MACD gist. pasaymoqda", macd_h < macd_h_prev),
                ("RSI pasaymoqda", rsi_v < rsi_prev),
                ("Sham yopilgan tasdig'i", True),
            ]
            extra = [
                ("Tasdiq shamida hajm o'rtachadan yuqori", vol > vol_ma),
                ("RSI 60 darajadan pastga tushdi", rsi_v < 60),
                ("MACD gist. manfiy", macd_h < 0),
                ("Sham kengligi >= 0.5*ATR", (float(b.high.iloc[-1]) - float(b.low.iloc[-1])) >= 0.5 * atr_v),
            ]
            passed = sum(1 for _, p in core if p)
            if passed == len(core):
                ex = sum(1 for _, p in extra if p)
                return self._result(
                    Direction.SELL, float(passed), float(len(core)), ex,
                    f"SELL: bearish RSI divergensiyasi tasdiqlandi ({ex} qo'shimcha)",
                    core + extra, indicators,
                )
            return self._neutral(
                f"NEUTRAL: bearish divergence bor, lekin tasdiq {passed}/{len(core)}",
                core + extra, indicators, partial_score=passed / len(core) * 4.0,
            )

        return self._neutral("NEUTRAL: tasdiqlangan divergensiya yo'q", [], indicators)
