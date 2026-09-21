"""Faol strategiya 4 — VWAP mean-reversion (intraday, trendga QARSHI emas).

Diqqat: bu strategiya KUCHLI TRENDDA ovoz bermaydi — faqat yonlama (range) bozorda.
- Narx VWAP dan ancha uzoqlashib ketdi (>= 1.5 ATR) — haddan oshdi.
- ADX past (<20) → trend yo'q, range.
- RSI haddan oshgan (30 past / 70 yuqori) — ortiqcha sotilgan/olingan.
- Oxirgi sham ortga qaytdi (mean tomon yopildi).
Kuchli trendda bu ovoz bermaydi, chunki trendda "arzon" yanada arzonlashaveradi.
"""
from __future__ import annotations

import pandas as pd

from app.core.config import Settings
from app.core.enums import Direction
from app.indicators.bundle import IndicatorBundle
from app.strategies.base import BaseStrategy, StrategyResult


class VwapReversionStrategy(BaseStrategy):
    key = "vwap_reversion"
    display_name = "VWAP Mean-Reversion"
    intraday_only = True   # faqat 5m/15m/30m

    DEV_ATR = 1.5          # VWAP dan uzoqlik (ATR) — haddan oshish chegarasi

    def analyze(self, df: pd.DataFrame, b: IndicatorBundle,
                settings: Settings, timeframe: str) -> StrategyResult:
        if not self._tf_allowed(timeframe):
            return self._neutral("NEUTRAL: mean-reversion faqat intraday TF", [], {})

        c = float(b.last_close)
        o = float(b.open_.iloc[-1])
        vwap = float(b.vwap.iloc[-1])
        if vwap != vwap:  # NaN
            return self._neutral("NEUTRAL: VWAP hali yo'q", [], {})
        rsi_v = float(b.rsi.iloc[-1])
        adx_v = float(b.adx.iloc[-1])
        atr = b.last_atr or 1e-9
        is_green = c >= o

        dev = c - vwap
        indicators = {
            "VWAP": round(vwap, 6), "RSI": round(rsi_v, 2),
            "ADX": round(adx_v, 2), "dev_ATR": round(dev / atr, 2),
        }

        ranging = adx_v < 20  # kuchli trend YO'Q

        # ---- BUY (arzon haddan oshdi → yuqoriga qaytish) ----
        oversold_stretch = dev <= -self.DEV_ATR * atr     # VWAP dan ancha pastda
        rsi_oversold = rsi_v < 32
        bounced = is_green and c > float(b.low.iloc[-1]) + 0.3 * (float(b.high.iloc[-1]) - float(b.low.iloc[-1]))
        buy_core = [
            ("Range bozor (ADX < 20, trend yo'q)", ranging),
            ("Narx VWAP dan >=1.5 ATR pastda (haddan oshdi)", oversold_stretch),
            ("RSI < 32 (ortiqcha sotilgan)", rsi_oversold),
            ("Sham pastdan yuqoriga qaytib yopildi", bounced),
        ]
        buy_extra = [
            ("Narx BB pastki chegarasiga tegdi/oshdi", c <= float(b.bb_lower.iloc[-1])),
        ]
        bp = sum(1 for _, p in buy_core if p)
        if bp == len(buy_core):
            ex = sum(1 for _, p in buy_extra if p)
            return self._result(
                Direction.BUY, float(bp), float(len(buy_core)), ex,
                f"BUY: range bozorda VWAP dan ortiqcha tushish + qaytish ({ex})",
                buy_core + buy_extra, indicators,
            )

        # ---- SELL (qimmat haddan oshdi → pastga qaytish) ----
        overbought_stretch = dev >= self.DEV_ATR * atr
        rsi_overbought = rsi_v > 68
        rejected = (not is_green) and c < float(b.high.iloc[-1]) - 0.3 * (float(b.high.iloc[-1]) - float(b.low.iloc[-1]))
        sell_core = [
            ("Range bozor (ADX < 20, trend yo'q)", ranging),
            ("Narx VWAP dan >=1.5 ATR yuqorida (haddan oshdi)", overbought_stretch),
            ("RSI > 68 (ortiqcha olingan)", rsi_overbought),
            ("Sham yuqoridan pastga qaytib yopildi", rejected),
        ]
        sell_extra = [
            ("Narx BB yuqori chegarasiga tegdi/oshdi", c >= float(b.bb_upper.iloc[-1])),
        ]
        sp = sum(1 for _, p in sell_core if p)
        if sp == len(sell_core):
            ex = sum(1 for _, p in sell_extra if p)
            return self._result(
                Direction.SELL, float(sp), float(len(sell_core)), ex,
                f"SELL: range bozorda VWAP dan ortiqcha ko'tarilish + qaytish ({ex})",
                sell_core + sell_extra, indicators,
            )

        best = max(bp, sp)
        partial = best / len(buy_core) * 4.0
        side = "BUY" if bp >= sp else "SELL"
        return self._neutral(
            f"NEUTRAL: mean-reversion {side} {best}/{len(buy_core)}",
            (buy_core + buy_extra) if side == "BUY" else (sell_core + sell_extra),
            indicators, partial_score=partial,
        )
