"""Strategiya 9 — Stochastic Oscillator (haddan ortiq sotilgan/sotib olingan burilishlar)."""
from __future__ import annotations

import pandas as pd

from app.core.config import Settings
from app.core.enums import Direction
from app.indicators.bundle import IndicatorBundle
from app.strategies.base import BaseStrategy, StrategyResult


class StochasticStrategy(BaseStrategy):
    key = "stochastic"
    display_name = "Stochastic (%K/%D)"

    def analyze(self, df: pd.DataFrame, b: IndicatorBundle,
                settings: Settings, timeframe: str) -> StrategyResult:
        c = b.last_close
        k = float(b.stoch_k.iloc[-1])
        k_prev = float(b.stoch_k.iloc[-2])
        d = float(b.stoch_d.iloc[-1])
        d_prev = float(b.stoch_d.iloc[-2])
        ema50 = float(b.ema50.iloc[-1])
        ema200 = float(b.ema200.iloc[-1])
        rsi_v = float(b.rsi.iloc[-1])
        adx_v = float(b.adx.iloc[-1])
        vol = float(b.volume.iloc[-1])
        vol_ma = float(b.vol_ma.iloc[-1]) or 0.0
        is_green = float(b.open_.iloc[-1]) <= c

        indicators = {
            "%K": round(k, 1), "%D": round(d, 1),
            "RSI": round(rsi_v, 1), "ADX": round(adx_v, 1),
        }

        # Bullish: %K oversold zonadan chiqib %D ni yuqoriga kesadi
        cross_up = k_prev <= d_prev and k > d
        cross_down = k_prev >= d_prev and k < d

        buy_core = [
            ("%K haddan ortiq sotuv zonasidan chiqdi (<35 dan ko'tarildi)", k > k_prev and k_prev < 35),
            ("%K %D ni yuqoriga kesdi (yoki kesishuv ustida)", cross_up or (k > d and k > 35)),
            ("Trend filtri: narx EMA200 dan yuqori", c > ema200),
            ("Sham yopilgan tasdig'i", True),
        ]
        buy_extra = [
            ("EMA50 > EMA200", ema50 > ema200),
            ("RSI > 50", rsi_v > 50),
            ("ADX > 20", adx_v > 20),
            ("Yashil sham", is_green),
            ("Hajm o'rtachadan yuqori", vol > vol_ma),
        ]

        sell_core = [
            ("%K haddan ortiq xarid zonasidan tushdi (>65 dan pastga)", k < k_prev and k_prev > 65),
            ("%K %D ni pastga kesdi (yoki kesishuv ostida)", cross_down or (k < d and k < 65)),
            ("Trend filtri: narx EMA200 dan past", c < ema200),
            ("Sham yopilgan tasdig'i", True),
        ]
        sell_extra = [
            ("EMA50 < EMA200", ema50 < ema200),
            ("RSI < 50", rsi_v < 50),
            ("ADX > 20", adx_v > 20),
            ("Qizil sham", not is_green),
            ("Hajm o'rtachadan yuqori", vol > vol_ma),
        ]

        buy_pass = sum(1 for _, ok in buy_core if ok)
        sell_pass = sum(1 for _, ok in sell_core if ok)

        if buy_pass == len(buy_core):
            extra = sum(1 for _, ok in buy_extra if ok)
            return self._result(
                Direction.BUY, float(buy_pass), float(len(buy_core)), extra,
                f"BUY: Stochastic oversold burilishini tasdiqladi ({extra} qo'shimcha)",
                buy_core + buy_extra, indicators,
            )
        if sell_pass == len(sell_core):
            extra = sum(1 for _, ok in sell_extra if ok)
            return self._result(
                Direction.SELL, float(sell_pass), float(len(sell_core)), extra,
                f"SELL: Stochastic overbought burilishini tasdiqladi ({extra} qo'shimcha)",
                sell_core + sell_extra, indicators,
            )

        best = max(buy_pass, sell_pass)
        partial = best / len(buy_core) * 4.0
        side = "BUY" if buy_pass >= sell_pass else "SELL"
        checks = (buy_core + buy_extra) if side == "BUY" else (sell_core + sell_extra)
        return self._neutral(
            f"NEUTRAL: stochastic {side} shartlari {best}/{len(buy_core)}",
            checks, indicators, partial_score=partial,
        )
