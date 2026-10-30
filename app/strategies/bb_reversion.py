"""Faol strategiya — Bollinger Band Mean-Reversion (forex/range bozor uchun).

Ochiq manbali yondashuv (Bollinger Bands 20/2.0 + RSI + ADX rejim filtri):
- Faqat RANGE rejimida ishlaydi: ADX < 20 (trend yo'q). Trendda mean-reversion
  xavfli, shuning uchun kuchli trendda ovoz BERMAYDI.
- Narx tashqi Bollinger bandga tegib (yoki biroz buzib) ORQAGA qaytib yopilganida:
  bandga qarshi (mean tomon) pozitsiya.
- RSI haddan oshgan (32 past / 68 yuqori) — ekstremal tasdig'i.
- Maqsad: o'rta chiziq (mean) tomon snap-back. Tizim 1R da breakeven, 2R da g'alaba.

Bu strategiya trend strategiyalari yutqazadigan yonlama (chop/range) forex
juftliklarda (EUR, JPY) ishlash uchun mo'ljallangan.
"""
from __future__ import annotations

import pandas as pd

from app.core.config import Settings
from app.core.enums import Direction
from app.indicators.bundle import IndicatorBundle
from app.strategies.base import BaseStrategy, StrategyResult


class BollingerReversionStrategy(BaseStrategy):
    key = "bb_reversion"
    display_name = "Bollinger Mean-Reversion"

    ADX_MAX = 20.0      # bu qiymatdan past = range (trend emas)
    RSI_OS = 32.0
    RSI_OB = 68.0

    def analyze(self, df: pd.DataFrame, b: IndicatorBundle,
                settings: Settings, timeframe: str) -> StrategyResult:
        c = float(b.last_close)
        o = float(b.open_.iloc[-1])
        hi = float(b.high.iloc[-1])
        lo = float(b.low.iloc[-1])
        bb_up = float(b.bb_upper.iloc[-1])
        bb_lo = float(b.bb_lower.iloc[-1])
        bb_mid = float(b.bb_mid.iloc[-1])
        rsi_v = float(b.rsi.iloc[-1])
        adx_v = float(b.adx.iloc[-1])
        atr = b.last_atr or 1e-9

        ranging = adx_v < self.ADX_MAX
        rng = hi - lo
        close_pos = (c - lo) / rng if rng > 0 else 0.5   # 0 past, 1 yuqori

        indicators = {
            "BB_upper": round(bb_up, 6), "BB_lower": round(bb_lo, 6),
            "BB_mid": round(bb_mid, 6), "RSI": round(rsi_v, 2),
            "ADX": round(adx_v, 2), "ATR": round(atr, 6),
        }

        is_green = c >= o

        # ---- BUY: pastki bandga tegib, undan YUQORIGA qaytib yopildi ----
        touched_lower = lo <= bb_lo
        reclaimed_up = c > bb_lo and close_pos > 0.5     # pastki zonadan qaytdi
        buy_core = [
            ("Range rejimi (ADX < 20, trend yo'q)", ranging),
            ("Sham pastki Bollinger bandga tegdi/buzdi", touched_lower),
            ("Narx pastki banddan yuqoriga qaytib yopildi (rejection)", reclaimed_up),
            (f"RSI < {self.RSI_OS:.0f} (ortiqcha sotilgan)", rsi_v < self.RSI_OS),
        ]
        buy_extra = [
            ("Yashil qaytish shami", is_green),
            ("Stoxastik pastda yuqoriga burildi", float(b.stoch_k.iloc[-1]) < 30 and
             float(b.stoch_k.iloc[-1]) > float(b.stoch_d.iloc[-1])),
            ("Narx o'rta chiziqdan ancha pastda (mean-g'ildirak)", c < bb_mid - 0.5 * atr),
        ]
        bp = sum(1 for _, p in buy_core if p)
        if bp == len(buy_core):
            ex = sum(1 for _, p in buy_extra if p)
            return self._result(
                Direction.BUY, float(bp), float(len(buy_core)), ex,
                f"BUY (mean-reversion): pastki band rejection + RSI {rsi_v:.0f} ({ex} qo'shimcha)",
                buy_core + buy_extra, indicators,
            )

        # ---- SELL: yuqori bandga tegib, undan PASTGA qaytib yopildi ----
        touched_upper = hi >= bb_up
        reclaimed_dn = c < bb_up and close_pos < 0.5
        sell_core = [
            ("Range rejimi (ADX < 20, trend yo'q)", ranging),
            ("Sham yuqori Bollinger bandga tegdi/buzdi", touched_upper),
            ("Narx yuqori banddan pastga qaytib yopildi (rejection)", reclaimed_dn),
            (f"RSI > {self.RSI_OB:.0f} (ortiqcha olingan)", rsi_v > self.RSI_OB),
        ]
        sell_extra = [
            ("Qizil qaytish shami", not is_green),
            ("Stoxastik yuqorida pastga burildi", float(b.stoch_k.iloc[-1]) > 70 and
             float(b.stoch_k.iloc[-1]) < float(b.stoch_d.iloc[-1])),
            ("Narx o'rta chiziqdan ancha yuqorida (mean-g'ildirak)", c > bb_mid + 0.5 * atr),
        ]
        sp = sum(1 for _, p in sell_core if p)
        if sp == len(sell_core):
            ex = sum(1 for _, p in sell_extra if p)
            return self._result(
                Direction.SELL, float(sp), float(len(sell_core)), ex,
                f"SELL (mean-reversion): yuqori band rejection + RSI {rsi_v:.0f} ({ex} qo'shimcha)",
                sell_core + sell_extra, indicators,
            )

        best = max(bp, sp)
        side = "BUY" if bp >= sp else "SELL"
        partial = best / len(buy_core) * 4.0
        return self._neutral(
            f"NEUTRAL: mean-reversion {side} {best}/{len(buy_core)} (ADX={adx_v:.0f})",
            (buy_core + buy_extra) if side == "BUY" else (sell_core + sell_extra),
            indicators, partial_score=partial,
        )
