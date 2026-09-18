"""Strategiya 1 — EMA + RSI + MACD (kuchaytirilgan filtrlar bilan)."""
from __future__ import annotations

import pandas as pd

from app.core.config import Settings
from app.core.enums import Direction
from app.indicators.bundle import IndicatorBundle
from app.strategies.base import BaseStrategy, StrategyResult


class EmaRsiMacdStrategy(BaseStrategy):
    key = "ema_trend"
    display_name = "EMA + RSI + MACD"

    def analyze(self, df: pd.DataFrame, b: IndicatorBundle,
                settings: Settings, timeframe: str) -> StrategyResult:
        c = b.last_close
        ema50 = float(b.ema50.iloc[-1])
        ema200 = float(b.ema200.iloc[-1])
        ema20 = float(b.ema20.iloc[-1])
        rsi_v = float(b.rsi.iloc[-1])
        macd_line = float(b.macd_line.iloc[-1])
        macd_sig = float(b.macd_signal.iloc[-1])
        macd_h = float(b.macd_hist.iloc[-1])
        macd_h_prev = float(b.macd_hist.iloc[-2])
        adx_v = float(b.adx.iloc[-1])
        atr_v = b.last_atr
        # Haddan oshib ketish filtri: narx EMA50 dan 2.5 ATR dan uzoq bo'lsa —
        # trend allaqachon kech, kirish xavfli.
        overbought_ext = (c - ema50) > 3.0 * atr_v
        oversold_ext = (ema50 - c) > 3.0 * atr_v
        vol = float(b.volume.iloc[-1])
        vol_ma = float(b.vol_ma.iloc[-1]) or 0.0
        is_green = float(b.open_.iloc[-1]) <= c

        indicators = {
            "EMA50": round(ema50, 6), "EMA200": round(ema200, 6),
            "RSI": round(rsi_v, 2), "MACD": round(macd_line, 6),
            "MACD_signal": round(macd_sig, 6), "MACD_hist": round(macd_h, 6),
            "ADX": round(adx_v, 2),
        }

        # ---- BUY shartlari ----
        buy_core = [
            ("EMA50 > EMA200 (uzoq trend yuqori)", ema50 > ema200),
            ("Narx EMA50 dan yuqori", c > ema50),
            ("RSI > 50 (momentum yuqori)", rsi_v > 50),
            ("MACD bullish (liniya signal ustida, gistogramma musbat)",
             macd_line > macd_sig and macd_h > 0),
            ("Sham yopilgan tasdig'i", True),  # pipeline faqat yopiq shamda ishlaydi
        ]
        buy_extra = [
            ("EMA200 qiyaligi yuqori", b.ema200_slope > 0),
            ("EMA50 qiyaligi yuqori", b.ema50_slope > 0),
            ("ADX > 20 (trend kuchi)", adx_v > 20),
            ("Hajm o'rtachadan yuqori", vol > vol_ma),
            ("Narx EMA20 dan yuqori", c > ema20),
            ("Yashil sham (xaridor bosimi)", is_green),
            ("Narx EMA50 ga oqilona masofada (kech emas)", not overbought_ext),
        ]

        # ---- SELL shartlari ----
        sell_core = [
            ("EMA50 < EMA200 (uzoq trend past)", ema50 < ema200),
            ("Narx EMA50 dan past", c < ema50),
            ("RSI < 50 (momentum past)", rsi_v < 50),
            ("MACD bearish (liniya signal ostida, gistogramma manfiy)",
             macd_line < macd_sig and macd_h < 0),
            ("Sham yopilgan tasdig'i", True),
        ]
        sell_extra = [
            ("EMA200 qiyaligi past", b.ema200_slope < 0),
            ("EMA50 qiyaligi past", b.ema50_slope < 0),
            ("ADX > 20 (trend kuchi)", adx_v > 20),
            ("Hajm o'rtachadan yuqori", vol > vol_ma),
            ("Narx EMA20 dan past", c < ema20),
            ("Qizil sham (sotuvchi bosimi)", not is_green),
            ("Narx EMA50 ga oqilona masofada (kech emas)", not oversold_ext),
        ]

        buy_pass = [p for _, p in buy_core if p]
        sell_pass = [p for _, p in sell_core if p]

        if len(buy_pass) == len(buy_core):
            extra = sum(1 for _, p in buy_extra if p)
            checks = buy_core + buy_extra
            return self._result(
                Direction.BUY, core_points=float(len(buy_core)),
                core_max=float(len(buy_core)), extra_count=extra,
                reason=f"BUY: barcha trend shartlari bajarildi ({extra} qo'shimcha tasdiq)",
                checks=checks, indicators=indicators,
            )

        if len(sell_pass) == len(sell_core):
            extra = sum(1 for _, p in sell_extra if p)
            checks = sell_core + sell_extra
            return self._result(
                Direction.SELL, core_points=float(len(sell_core)),
                core_max=float(len(sell_core)), extra_count=extra,
                reason=f"SELL: barcha trend shartlari bajarildi ({extra} qo'shimcha tasdiq)",
                checks=checks, indicators=indicators,
            )

        # Qisman moslik — neytral, lekin foiz ko'rsatib boriladi
        best = max(len(buy_pass), len(sell_pass))
        total = len(buy_core)
        partial = best / total * 4.0  # maksimal 4 (signal chegarasidan past)
        side = "BUY" if len(buy_pass) >= len(sell_pass) else "SELL"
        checks = (buy_core + buy_extra) if side == "BUY" else (sell_core + sell_extra)
        return self._neutral(
            f"NEUTRAL: {side} shartlari {best}/{total} bajarildi — to'liq tasdiq yo'q",
            checks, indicators, partial_score=partial,
        )
