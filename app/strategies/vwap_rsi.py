"""Strategiya 3 — VWAP + RSI (intraday, trend filter bilan)."""
from __future__ import annotations

import pandas as pd

from app.core.config import Settings
from app.core.enums import Direction
from app.indicators.bundle import IndicatorBundle
from app.strategies.base import BaseStrategy, StrategyResult


class VwapRsiStrategy(BaseStrategy):
    key = "vwap"
    display_name = "VWAP + RSI"
    intraday_only = True  # faqat 5m / 15m / 30m

    def analyze(self, df: pd.DataFrame, b: IndicatorBundle,
                settings: Settings, timeframe: str) -> StrategyResult:
        if not self._tf_allowed(timeframe):
            return self._neutral(
                "NEUTRAL: VWAP strategiyasi faqat intraday (5m/15m/30m) timeframe'da ishlaydi",
                [], {}, partial_score=0.0,
            )

        c = b.last_close
        vwap = float(b.vwap.iloc[-1])
        vwap_prev = float(b.vwap.iloc[-2]) if len(b.vwap) >= 2 else vwap
        rsi_v = float(b.rsi.iloc[-1])
        rsi_prev = float(b.rsi.iloc[-2])
        ema50 = float(b.ema50.iloc[-1])
        ema200 = float(b.ema200.iloc[-1])
        macd_h = float(b.macd_hist.iloc[-1])
        vol = float(b.volume.iloc[-1])
        vol_ma = float(b.vol_ma.iloc[-1]) or 0.0
        is_green = float(b.open_.iloc[-1]) <= c

        if vwap != vwap:  # NaN
            return self._neutral("NEUTRAL: VWAP hali hisoblanmadi", [], {})

        indicators = {
            "VWAP": round(vwap, 6), "RSI": round(rsi_v, 2),
            "EMA50": round(ema50, 6), "EMA200": round(ema200, 6),
        }

        buy_core = [
            ("Narx VWAP dan yuqori", c > vwap),
            ("RSI > 50 (momentum yuqori)", rsi_v > 50),
            ("Bullish tasdiq: yashil sham yoki MACD gist. > 0", is_green or macd_h > 0),
            ("Trend filter: narx EMA200 dan yuqori", c > ema200),
            ("Sham yopilgan tasdig'i", True),
        ]
        buy_extra = [
            ("Hajm o'rtachadan yuqori", vol > vol_ma),
            ("RSI o'smoqda", rsi_v > rsi_prev),
            ("VWAP qiyaligi yuqori", vwap > vwap_prev),
            ("EMA50 > EMA200", ema50 > ema200),
        ]

        sell_core = [
            ("Narx VWAP dan past", c < vwap),
            ("RSI < 50 (momentum past)", rsi_v < 50),
            ("Bearish tasdiq: qizil sham yoki MACD gist. < 0", (not is_green) or macd_h < 0),
            ("Trend filter: narx EMA200 dan past", c < ema200),
            ("Sham yopilgan tasdig'i", True),
        ]
        sell_extra = [
            ("Hajm o'rtachadan yuqori", vol > vol_ma),
            ("RSI pasaymoqda", rsi_v < rsi_prev),
            ("VWAP qiyaligi past", vwap < vwap_prev),
            ("EMA50 < EMA200", ema50 < ema200),
        ]

        buy_pass = sum(1 for _, p in buy_core if p)
        sell_pass = sum(1 for _, p in sell_core if p)

        if buy_pass == len(buy_core):
            extra = sum(1 for _, p in buy_extra if p)
            return self._result(
                Direction.BUY, float(buy_pass), float(len(buy_core)), extra,
                f"BUY: narx VWAP ustida, RSI tasdig'i bilan ({extra} qo'shimcha)",
                buy_core + buy_extra, indicators,
            )
        if sell_pass == len(sell_core):
            extra = sum(1 for _, p in sell_extra if p)
            return self._result(
                Direction.SELL, float(sell_pass), float(len(sell_core)), extra,
                f"SELL: narx VWAP ostida, RSI tasdig'i bilan ({extra} qo'shimcha)",
                sell_core + sell_extra, indicators,
            )

        best = max(buy_pass, sell_pass)
        partial = best / len(buy_core) * 4.0
        side = "BUY" if buy_pass >= sell_pass else "SELL"
        checks = (buy_core + buy_extra) if side == "BUY" else (sell_core + sell_extra)
        return self._neutral(
            f"NEUTRAL: VWAP {side} shartlari {best}/{len(buy_core)} bajarildi",
            checks, indicators, partial_score=partial,
        )
