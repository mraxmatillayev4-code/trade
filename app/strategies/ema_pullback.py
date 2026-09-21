"""Faol strategiya 1 — Trend Pullback (EMA200 trend + EMA20/50 ga qaytish).

Nega bu kuchsiz "har shamda trend" yondashuvidan yaxshi:
- Faqat kuchli trendda (EMA200 qiyaligi, narx EMA200 ning to'g'ri tomonida) ishlaydi.
- Kirish narx SHOVQINDA emas, trend ICHIDAGI QAYTISH (pullback) da —
  EMA20/EMA50 ga tegib, yo'nalishda yana yopilgan shamda.
- RSI haddan oshmagan (50-70 oralig'i — momentum bor, lekin kech emas).
- Bu entry risk masofasini qisqartiradi va 1:2 maqsadga yetish ehtimolini oshiradi.
"""
from __future__ import annotations

import pandas as pd

from app.core.config import Settings
from app.core.enums import Direction
from app.indicators.bundle import IndicatorBundle
from app.strategies.base import BaseStrategy, StrategyResult


class EmaPullbackStrategy(BaseStrategy):
    key = "ema_pullback"
    display_name = "Trend Pullback (EMA)"

    PULLBACK_ATR = 1.2      # EMA ga shu masofadan yaqinlashsa — "tegdi" deb hisob
    MAX_EXTEND_ATR = 3.0    # trenddan bunchalik uzoq bo'lsa — kech, kiraverish yo'q

    def analyze(self, df: pd.DataFrame, b: IndicatorBundle,
                settings: Settings, timeframe: str) -> StrategyResult:
        c = float(b.last_close)
        o = float(b.open_.iloc[-1])
        ema20 = float(b.ema20.iloc[-1])
        ema50 = float(b.ema50.iloc[-1])
        ema200 = float(b.ema200.iloc[-1])
        rsi_v = float(b.rsi.iloc[-1])
        adx_v = float(b.adx.iloc[-1])
        atr = b.last_atr or 1e-9
        is_green = c >= o
        is_red = c < o

        indicators = {
            "EMA20": round(ema20, 6), "EMA50": round(ema50, 6),
            "EMA200": round(ema200, 6), "RSI": round(rsi_v, 2),
            "ADX": round(adx_v, 2), "ATR": round(atr, 6),
        }

        # ---------- BUY: yuqori trend + pastga qaytish + yashil tasdiq ----------
        uptrend = ema50 > ema200 and c > ema200 and b.ema200_slope > 0
        # so'nggi 3 sham ichida narx EMA20/50 ga tegdi (pastga qaytdi)
        lows = b.low.iloc[-3:].astype(float)
        touched_dip = float(lows.min()) <= ema20 + self.PULLBACK_ATR * atr or \
            float(lows.min()) <= ema50 + self.PULLBACK_ATR * atr
        bounced = is_green and c > ema20
        rsi_ok_buy = 50 <= rsi_v <= 72
        not_overextended = (c - ema50) < self.MAX_EXTEND_ATR * atr

        buy_core = [
            ("Yuqori trend (EMA50>EMA200, narx EMA200 ustida, qiyalik +)", uptrend),
            ("Narx EMA20/50 ga qaytdi (pullback)", touched_dip),
            ("Qaytishda yashil sham bilan yana yuqoriga yopildi", bounced),
            ("RSI 50-72 (momentum bor, kech emas)", rsi_ok_buy),
        ]
        buy_extra = [
            ("ADX > 18 (trend yetarli)", adx_v > 18),
            ("Narx trenddan juda uzoq emas (kech emas)", not_overextended),
            ("EMA200 qiyaligi sezilarli (>0)", b.ema200_slope > 0),
        ]
        bp = sum(1 for _, p in buy_core if p)
        if bp == len(buy_core):
            ex = sum(1 for _, p in buy_extra if p)
            return self._result(
                Direction.BUY, float(bp), float(len(buy_core)), ex,
                f"BUY: yuqori trendda EMA ga qaytish + yashil tasdiq ({ex} qo'shimcha)",
                buy_core + buy_extra, indicators,
            )

        # ---------- SELL: past trend + yuqoriga qaytish + qizil tasdiq ----------
        downtrend = ema50 < ema200 and c < ema200 and b.ema200_slope < 0
        highs = b.high.iloc[-3:].astype(float)
        touched_rally = float(highs.max()) >= ema20 - self.PULLBACK_ATR * atr or \
            float(highs.max()) >= ema50 - self.PULLBACK_ATR * atr
        rejected = is_red and c < ema20
        rsi_ok_sell = 28 <= rsi_v <= 50
        not_overextended_s = (ema50 - c) < self.MAX_EXTEND_ATR * atr

        sell_core = [
            ("Past trend (EMA50<EMA200, narx EMA200 ostida, qiyalik -)", downtrend),
            ("Narx EMA20/50 ga qaytdi (rally)", touched_rally),
            ("Qaytishda qizil sham bilan yana pastga yopildi", rejected),
            ("RSI 28-50 (momentum bor, kech emas)", rsi_ok_sell),
        ]
        sell_extra = [
            ("ADX > 18 (trend yetarli)", adx_v > 18),
            ("Narx trenddan juda uzoq emas (kech emas)", not_overextended_s),
            ("EMA200 qiyaligi sezilarli (<0)", b.ema200_slope < 0),
        ]
        sp = sum(1 for _, p in sell_core if p)
        if sp == len(sell_core):
            ex = sum(1 for _, p in sell_extra if p)
            return self._result(
                Direction.SELL, float(sp), float(len(sell_core)), ex,
                f"SELL: past trendda EMA ga qaytish + qizil tasdiq ({ex} qo'shimcha)",
                sell_core + sell_extra, indicators,
            )

        best = max(bp, sp)
        side = "BUY" if bp >= sp else "SELL"
        partial = best / len(buy_core) * 4.0
        return self._neutral(
            f"NEUTRAL: pullback {side} shartlari {best}/{len(buy_core)} — to'liq tasdiq yo'q",
            (buy_core + buy_extra) if side == "BUY" else (sell_core + sell_extra),
            indicators, partial_score=partial,
        )
