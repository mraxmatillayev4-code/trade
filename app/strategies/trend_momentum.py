"""Faol strategiya 5 — Trend Momentum (MACD + RSI + ADX tasdig'i).

Pullback strategiyalari (EMA/Supertrend) qattiq "qaytib tegish" shartini kutadi;
bu strategiya esa trend YO'NALISHINI va momentumni tasdiqlaydi — pullback tiklanish
paytida 3 ta trend strategiyasi bir ovoz berishi uchun "konfluentlik" qatlami.

Qattiq qoidalar (kech kirishni kesadi):
- Trend aniq: EMA50 > EMA200 va narx EMA200 ning to'g'ri tomonida, ADX > 20.
- Momentum yo'nalishni tasdiqlaydi: MACD gistogramma musbat/manfiy va o'smoqda.
- RSI trend tomonida (50-70 BUY / 30-50 SELL) — haddan oshgan emas.
- Narx trenddan haddan tashqari uzoq emas (kech emas).
"""
from __future__ import annotations

import pandas as pd

from app.core.config import Settings
from app.core.enums import Direction
from app.indicators.bundle import IndicatorBundle
from app.strategies.base import BaseStrategy, StrategyResult


class TrendMomentumStrategy(BaseStrategy):
    key = "trend_momentum"
    display_name = "Trend Momentum (MACD)"

    MAX_EXTEND_ATR = 3.0

    def analyze(self, df: pd.DataFrame, b: IndicatorBundle,
                settings: Settings, timeframe: str) -> StrategyResult:
        c = float(b.last_close)
        ema50 = float(b.ema50.iloc[-1])
        ema200 = float(b.ema200.iloc[-1])
        rsi_v = float(b.rsi.iloc[-1])
        adx_v = float(b.adx.iloc[-1])
        macd_h = float(b.macd_hist.iloc[-1])
        macd_h_prev = float(b.macd_hist.iloc[-2]) if len(b.macd_hist) >= 2 else macd_h
        macd_line = float(b.macd_line.iloc[-1])
        macd_sig = float(b.macd_signal.iloc[-1])
        atr = b.last_atr or 1e-9

        indicators = {
            "EMA50": round(ema50, 6), "EMA200": round(ema200, 6),
            "RSI": round(rsi_v, 2), "ADX": round(adx_v, 2),
            "MACD_hist": round(macd_h, 6),
        }

        # ---- BUY ----
        up_trend = ema50 > ema200 and c > ema200
        mom_buy = macd_h > 0 and macd_h >= macd_h_prev and macd_line > macd_sig
        rsi_buy = 50 < rsi_v < 72
        not_late = (c - ema50) < self.MAX_EXTEND_ATR * atr
        buy_core = [
            ("Yuqori trend (EMA50>EMA200, narx EMA200 ustida)", up_trend),
            ("MACD momentum yuqori (hist musbat, o'smoqda)", mom_buy),
            ("RSI 50-72 (trend tomonida, kech emas)", rsi_buy),
            ("ADX > 20 (kuchli trend)", adx_v > 20),
        ]
        buy_extra = [
            ("EMA200 qiyaligi yuqori", b.ema200_slope > 0),
            ("Narx trenddan juda uzoq emas", not_late),
        ]
        bp = sum(1 for _, p in buy_core if p)
        if bp == len(buy_core):
            ex = sum(1 for _, p in buy_extra if p)
            return self._result(
                Direction.BUY, float(bp), float(len(buy_core)), ex,
                f"BUY: trend + MACD momentum tasdig'i ({ex} qo'shimcha)",
                buy_core + buy_extra, indicators,
            )

        # ---- SELL ----
        dn_trend = ema50 < ema200 and c < ema200
        mom_sell = macd_h < 0 and macd_h <= macd_h_prev and macd_line < macd_sig
        rsi_sell = 28 < rsi_v < 50
        not_late_s = (ema50 - c) < self.MAX_EXTEND_ATR * atr
        sell_core = [
            ("Past trend (EMA50<EMA200, narx EMA200 ostida)", dn_trend),
            ("MACD momentum past (hist manfiy, pasaymoqda)", mom_sell),
            ("RSI 28-50 (trend tomonida, kech emas)", rsi_sell),
            ("ADX > 20 (kuchli trend)", adx_v > 20),
        ]
        sell_extra = [
            ("EMA200 qiyaligi past", b.ema200_slope < 0),
            ("Narx trenddan juda uzoq emas", not_late_s),
        ]
        sp = sum(1 for _, p in sell_core if p)
        if sp == len(sell_core):
            ex = sum(1 for _, p in sell_extra if p)
            return self._result(
                Direction.SELL, float(sp), float(len(sell_core)), ex,
                f"SELL: trend + MACD momentum tasdig'i ({ex} qo'shimcha)",
                sell_core + sell_extra, indicators,
            )

        best = max(bp, sp)
        partial = best / len(buy_core) * 4.0
        side = "BUY" if bp >= sp else "SELL"
        return self._neutral(
            f"NEUTRAL: momentum {side} {best}/{len(buy_core)}",
            (buy_core + buy_extra) if side == "BUY" else (sell_core + sell_extra),
            indicators, partial_score=partial,
        )
