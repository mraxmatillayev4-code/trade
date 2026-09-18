"""Faol strategiya — RSI Extreme Reversal (range bozorda haddan oshishdan qaytish).

Bollinger strategiyasini to'ldiradi: narx RSI ekstremumga yetganda (ortiqcha
sotilgan/olingan) + stoxastik burilishi + range rejimi (ADX past) → mean tomon
qaytish. Stoxastik burilish "ortga qaytish boshlandi" tasdig'ini beradi.
Trendda (ADX yuqori) ovoz bermaydi — trendda haddan oshish davom etaveradi.
"""
from __future__ import annotations

import pandas as pd

from app.core.config import Settings
from app.core.enums import Direction
from app.indicators.bundle import IndicatorBundle
from app.strategies.base import BaseStrategy, StrategyResult


class RsiReversionStrategy(BaseStrategy):
    key = "rsi_reversion"
    display_name = "RSI Extreme Reversal"

    ADX_MAX = 22.0
    RSI_LO = 30.0
    RSI_HI = 70.0

    def analyze(self, df: pd.DataFrame, b: IndicatorBundle,
                settings: Settings, timeframe: str) -> StrategyResult:
        c = float(b.last_close)
        rsi_v = float(b.rsi.iloc[-1])
        rsi_prev = float(b.rsi.iloc[-2]) if len(b.rsi) >= 2 else rsi_v
        adx_v = float(b.adx.iloc[-1])
        sk = float(b.stoch_k.iloc[-1])
        sd = float(b.stoch_d.iloc[-1])
        sk_prev = float(b.stoch_k.iloc[-2]) if len(b.stoch_k) >= 2 else sk

        ranging = adx_v < self.ADX_MAX

        indicators = {
            "RSI": round(rsi_v, 2), "ADX": round(adx_v, 2),
            "StochK": round(sk, 2), "StochD": round(sd, 2),
        }

        # ---- BUY: ortiqcha sotilgan + stoxastik pastda yuqoriga burildi ----
        oversold = rsi_v < self.RSI_LO
        stoch_turn_up = sk > sd and sk > sk_prev and sk < 35
        buy_core = [
            ("Range rejimi (ADX < 22)", ranging),
            (f"RSI < {self.RSI_LO:.0f} (ortiqcha sotilgan)", oversold),
            ("Stoxastik pastda yuqoriga burildi", stoch_turn_up),
        ]
        buy_extra = [
            ("RSI pastdan burildi (momentum susaydi)", rsi_v > rsi_prev),
            ("Narx pastki BB banddan past/tegdi", c <= float(b.bb_lower.iloc[-1]) * 1.0005),
        ]
        bp = sum(1 for _, p in buy_core if p)
        if bp == len(buy_core):
            ex = sum(1 for _, p in buy_extra if p)
            return self._result(
                Direction.BUY, float(bp), float(len(buy_core)), ex,
                f"BUY (RSI reversal): RSI {rsi_v:.0f} + stoxastik burilish ({ex} qo'shimcha)",
                buy_core + buy_extra, indicators,
            )

        # ---- SELL: ortiqcha olingan + stoxastik yuqorida pastga burildi ----
        overbought = rsi_v > self.RSI_HI
        stoch_turn_dn = sk < sd and sk < sk_prev and sk > 65
        sell_core = [
            ("Range rejimi (ADX < 22)", ranging),
            (f"RSI > {self.RSI_HI:.0f} (ortiqcha olingan)", overbought),
            ("Stoxastik yuqorida pastga burildi", stoch_turn_dn),
        ]
        sell_extra = [
            ("RSI yuqoridan burildi", rsi_v < rsi_prev),
            ("Narx yuqori BB banddan yuqori/tegdi", c >= float(b.bb_upper.iloc[-1]) * 0.9995),
        ]
        sp = sum(1 for _, p in sell_core if p)
        if sp == len(sell_core):
            ex = sum(1 for _, p in sell_extra if p)
            return self._result(
                Direction.SELL, float(sp), float(len(sell_core)), ex,
                f"SELL (RSI reversal): RSI {rsi_v:.0f} + stoxastik burilish ({ex} qo'shimcha)",
                sell_core + sell_extra, indicators,
            )

        best = max(bp, sp)
        side = "BUY" if bp >= sp else "SELL"
        partial = best / len(buy_core) * 4.0
        return self._neutral(
            f"NEUTRAL: RSI reversal {side} {best}/{len(buy_core)} (ADX={adx_v:.0f})",
            (buy_core + buy_extra) if side == "BUY" else (sell_core + sell_extra),
            indicators, partial_score=partial,
        )
