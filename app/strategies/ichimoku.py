"""Strategiya 7 — Ichimoku Cloud (Kumo) trendni aniqlash."""
from __future__ import annotations

import pandas as pd

from app.core.config import Settings
from app.core.enums import Direction
from app.indicators.bundle import IndicatorBundle
from app.strategies.base import BaseStrategy, StrategyResult


class IchimokuStrategy(BaseStrategy):
    key = "ichimoku"
    display_name = "Ichimoku Cloud"

    def analyze(self, df: pd.DataFrame, b: IndicatorBundle,
                settings: Settings, timeframe: str) -> StrategyResult:
        c = b.last_close
        open_ = float(b.open_.iloc[-1])
        ichi = b.ichimoku
        tenkan = float(ichi["tenkan"].iloc[-1])
        kijun = float(ichi["kijun"].iloc[-1])
        span_a = float(ichi["span_a"].iloc[-1])
        span_b = float(ichi["span_b"].iloc[-1])
        adx_v = float(b.adx.iloc[-1])
        rsi_v = float(b.rsi.iloc[-1])
        vol = float(b.volume.iloc[-1])
        vol_ma = float(b.vol_ma.iloc[-1]) or 0.0
        ema200 = float(b.ema200.iloc[-1])
        is_green = open_ <= c

        cloud_top = max(span_a, span_b)
        cloud_bottom = min(span_a, span_b)
        cloud_bullish = span_a > span_b
        cloud_bearish = span_a < span_b

        indicators = {
            "Tenkan": round(tenkan, 6), "Kijun": round(kijun, 6),
            "Span_A": round(span_a, 6), "Span_B": round(span_b, 6),
            "Cloud": "yashil (bullish)" if cloud_bullish else "qizil (bearish)",
            "RSI": round(rsi_v, 1), "ADX": round(adx_v, 1),
        }

        buy_core = [
            ("Narx bulut (Kumo) ustida yopildi", c > cloud_top),
            ("Bullish bulut: Span A > Span B", cloud_bullish),
            ("Tenkan > Kijun (tez/sekin chiziq kesishuvi)", tenkan > kijun),
            ("Narx Kijun dan yuqori", c > kijun),
            ("Sham yopilgan tasdig'i", True),
        ]
        buy_extra = [
            ("Narx EMA200 dan yuqori", c > ema200),
            ("ADX > 20", adx_v > 20),
            ("RSI > 50", rsi_v > 50),
            ("Hajm o'rtachadan yuqori", vol > vol_ma),
            ("Yashil sham", is_green),
            ("Bulut qalinligi 0 dan katta (tasdiq)", cloud_top - cloud_bottom > 0),
        ]

        sell_core = [
            ("Narx bulut (Kumo) ostida yopildi", c < cloud_bottom),
            ("Bearish bulut: Span A < Span B", cloud_bearish),
            ("Tenkan < Kijun", tenkan < kijun),
            ("Narx Kijun dan past", c < kijun),
            ("Sham yopilgan tasdig'i", True),
        ]
        sell_extra = [
            ("Narx EMA200 dan past", c < ema200),
            ("ADX > 20", adx_v > 20),
            ("RSI < 50", rsi_v < 50),
            ("Hajm o'rtachadan yuqori", vol > vol_ma),
            ("Qizil sham", not is_green),
            ("Bulut qalinligi 0 dan katta", cloud_top - cloud_bottom > 0),
        ]

        buy_pass = sum(1 for _, p in buy_core if p)
        sell_pass = sum(1 for _, p in sell_core if p)

        if buy_pass == len(buy_core):
            extra = sum(1 for _, p in buy_extra if p)
            return self._result(
                Direction.BUY, float(buy_pass), float(len(buy_core)), extra,
                f"BUY: narx bullish Ichimoku buluti ustida, Tenkan/Kijun tasdig'i ({extra} qo'shimcha)",
                buy_core + buy_extra, indicators,
            )
        if sell_pass == len(sell_core):
            extra = sum(1 for _, p in sell_extra if p)
            return self._result(
                Direction.SELL, float(sell_pass), float(len(sell_core)), extra,
                f"SELL: narx bearish Ichimoku buluti ostida ({extra} qo'shimcha)",
                sell_core + sell_extra, indicators,
            )

        best = max(buy_pass, sell_pass)
        partial = best / len(buy_core) * 4.0
        side = "BUY" if buy_pass >= sell_pass else "SELL"
        checks = (buy_core + buy_extra) if side == "BUY" else (sell_core + sell_extra)
        return self._neutral(
            f"NEUTRAL: Ichimoku {side} shartlari {best}/{len(buy_core)}",
            checks, indicators, partial_score=partial,
        )
