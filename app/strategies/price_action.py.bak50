"""Strategiya 8 — Price Action (sham shakllari: engulfing, hammer, pin bar)."""
from __future__ import annotations

import pandas as pd

from app.core.config import Settings
from app.core.enums import Direction
from app.indicators.bundle import IndicatorBundle
from app.strategies.base import BaseStrategy, StrategyResult


class PriceActionStrategy(BaseStrategy):
    key = "price_action"
    display_name = "Price Action (sham shakllari)"

    def analyze(self, df: pd.DataFrame, b: IndicatorBundle,
                settings: Settings, timeframe: str) -> StrategyResult:
        c = b.last_close
        o0 = float(b.open_.iloc[-1])
        ema50 = float(b.ema50.iloc[-1])
        ema200 = float(b.ema200.iloc[-1])
        adx_v = float(b.adx.iloc[-1])
        atr_v = b.last_atr
        rsi_v = float(b.rsi.iloc[-1])
        vol = float(b.volume.iloc[-1])
        vol_ma = float(b.vol_ma.iloc[-1]) or 0.0
        rng = float(b.high.iloc[-1] - b.low.iloc[-1]) or 1e-9
        p = b.candle_patterns

        indicators = {
            "Shakl": (
                "bullish engulfing/hammer" if (p.get("bullish_engulfing") or p.get("hammer"))
                else "bearish engulfing/shooting star" if (p.get("bearish_engulfing") or p.get("shooting_star"))
                else "aniq shakl yo'q"
            ),
            "Tana kengligi %": round(abs(c - o0) / rng * 100, 1),
            "RSI": round(rsi_v, 1), "ADX": round(adx_v, 1),
        }

        bullish_shape = bool(p.get("bullish_engulfing") or p.get("hammer"))
        bearish_shape = bool(p.get("bearish_engulfing") or p.get("shooting_star"))

        buy_core = [
            ("Bullish sham shakli (engulfing yoki hammer)", bullish_shape),
            ("Sham tanasi sezilarli (>= 45% diapazon)", abs(c - o0) / rng >= 0.45 or p.get("hammer")),
            ("Sham kengligi >= 0.5 ATR (kuchli harakat)", rng >= 0.5 * atr_v),
            ("Trend filtri: narx EMA200 dan yuqori", c > ema200),
            ("Sham yopilgan tasdig'i", True),
        ]
        buy_extra = [
            ("Bullish engulfing (kuchli shakl)", p.get("bullish_engulfing", False)),
            ("EMA50 > EMA200", ema50 > ema200),
            ("Hajm o'rtachadan yuqori", vol > vol_ma),
            ("RSI > 50", rsi_v > 50),
            ("ADX > 20", adx_v > 20),
        ]

        sell_core = [
            ("Bearish sham shakli (engulfing yoki shooting star)", bearish_shape),
            ("Sham tanasi sezilarli (>= 45% diapazon)", abs(c - o0) / rng >= 0.45 or p.get("shooting_star")),
            ("Sham kengligi >= 0.5 ATR", rng >= 0.5 * atr_v),
            ("Trend filtri: narx EMA200 dan past", c < ema200),
            ("Sham yopilgan tasdig'i", True),
        ]
        sell_extra = [
            ("Bearish engulfing (kuchli shakl)", p.get("bearish_engulfing", False)),
            ("EMA50 < EMA200", ema50 < ema200),
            ("Hajm o'rtachadan yuqori", vol > vol_ma),
            ("RSI < 50", rsi_v < 50),
            ("ADX > 20", adx_v > 20),
        ]

        buy_pass = sum(1 for _, ok in buy_core if ok)
        sell_pass = sum(1 for _, ok in sell_core if ok)

        if buy_pass == len(buy_core):
            extra = sum(1 for _, ok in buy_extra if ok)
            return self._result(
                Direction.BUY, float(buy_pass), float(len(buy_core)), extra,
                f"BUY: bullish price action shakli tasdiqlandi ({extra} qo'shimcha)",
                buy_core + buy_extra, indicators,
            )
        if sell_pass == len(sell_core):
            extra = sum(1 for _, ok in sell_extra if ok)
            return self._result(
                Direction.SELL, float(sell_pass), float(len(sell_core)), extra,
                f"SELL: bearish price action shakli tasdiqlandi ({extra} qo'shimcha)",
                sell_core + sell_extra, indicators,
            )

        best = max(buy_pass, sell_pass)
        partial = best / len(buy_core) * 4.0
        side = "BUY" if buy_pass >= sell_pass else "SELL"
        checks = (buy_core + buy_extra) if side == "BUY" else (sell_core + sell_extra)
        return self._neutral(
            f"NEUTRAL: price action {side} shartlari {best}/{len(buy_core)}",
            checks, indicators, partial_score=partial,
        )
