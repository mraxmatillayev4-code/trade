"""Strategiya 4 — Breakout + Volume (fake breakout filtrlari bilan)."""
from __future__ import annotations

import pandas as pd

from app.core.config import Settings
from app.core.enums import Direction
from app.indicators.bundle import IndicatorBundle
from app.strategies.base import BaseStrategy, StrategyResult


class BreakoutVolumeStrategy(BaseStrategy):
    key = "breakout"
    display_name = "Breakout + Volume"

    def analyze(self, df: pd.DataFrame, b: IndicatorBundle,
                settings: Settings, timeframe: str) -> StrategyResult:
        c = b.last_close
        high = float(b.high.iloc[-1])
        low = float(b.low.iloc[-1])
        open_ = float(b.open_.iloc[-1])
        atr_v = b.last_atr
        vol = float(b.volume.iloc[-1])
        vol_ma = float(b.vol_ma.iloc[-1]) or 0.0
        ema200 = float(b.ema200.iloc[-1])
        ema50 = float(b.ema50.iloc[-1])
        adx_v = float(b.adx.iloc[-1])

        support = b.support
        resistance = b.resistance

        indicators = {
            "Support": round(support, 6) if support else None,
            "Resistance": round(resistance, 6) if resistance else None,
            "ATR": round(atr_v, 6),
            "Volume_ratio": round(vol / vol_ma, 2) if vol_ma else None,
            "EMA200": round(ema200, 6),
        }

        if support is None or resistance is None or atr_v <= 0:
            return self._neutral("NEUTRAL: support/resistance darajalari aniqlanmadi",
                                 [], indicators)

        candle_range = max(high - low, 1e-12)
        close_position = (c - low) / candle_range  # 0..1, shamning yuqoriga yaqinligi

        buy_core = [
            (f"Sham Resistance ({resistance:.6g}) dan yuqori yopildi", c > resistance),
            ("Sham tanasi yuqori zonada yopildi (close > 60% range)", close_position > 0.6),
            (f"Hajm tasdig'i (>{settings.volume_multiplier}x o'rtacha)",
             vol > vol_ma * settings.volume_multiplier),
            ("ATR filtri: sham kengligi >= 0.6*ATR", candle_range >= 0.6 * atr_v),
            ("Over-extension yo'q: narx resistance + 2*ATR dan past",
             c <= resistance + 2 * atr_v),
            ("Trend filtri: narx EMA200 dan yuqori", c > ema200),
            ("Sham yopilgan tasdig'i", True),
        ]
        buy_extra = [
            ("EMA50 > EMA200", ema50 > ema200),
            ("ADX > 20", adx_v > 20),
            ("Hajm > 2x o'rtacha (kuchli kirish)", vol > vol_ma * 2.0),
            ("Yashil sham", open_ <= c),
        ]

        sell_core = [
            (f"Sham Support ({support:.6g}) dan past yopildi", c < support),
            ("Sham tanasi pastki zonada yopildi (close < 40% range)", close_position < 0.4),
            (f"Hajm tasdig'i (>{settings.volume_multiplier}x o'rtacha)",
             vol > vol_ma * settings.volume_multiplier),
            ("ATR filtri: sham kengligi >= 0.6*ATR", candle_range >= 0.6 * atr_v),
            ("Over-extension yo'q: narx support - 2*ATR dan yuqori",
             c >= support - 2 * atr_v),
            ("Trend filtri: narx EMA200 dan past", c < ema200),
            ("Sham yopilgan tasdig'i", True),
        ]
        sell_extra = [
            ("EMA50 < EMA200", ema50 < ema200),
            ("ADX > 20", adx_v > 20),
            ("Hajm > 2x o'rtacha (kuchli kirish)", vol > vol_ma * 2.0),
            ("Qizil sham", open_ > c),
        ]

        buy_pass = sum(1 for _, p in buy_core if p)
        sell_pass = sum(1 for _, p in sell_core if p)

        if buy_pass == len(buy_core):
            extra = sum(1 for _, p in buy_extra if p)
            return self._result(
                Direction.BUY, float(buy_pass), float(len(buy_core)), extra,
                f"BUY: resistance buzilishi hajm bilan tasdiqlandi ({extra} qo'shimcha)",
                buy_core + buy_extra, indicators,
            )
        if sell_pass == len(sell_core):
            extra = sum(1 for _, p in sell_extra if p)
            return self._result(
                Direction.SELL, float(sell_pass), float(len(sell_core)), extra,
                f"SELL: support buzilishi hajm bilan tasdiqlandi ({extra} qo'shimcha)",
                sell_core + sell_extra, indicators,
            )

        best = max(buy_pass, sell_pass)
        partial = best / len(buy_core) * 4.0
        side = "BUY" if buy_pass >= sell_pass else "SELL"
        checks = (buy_core + buy_extra) if side == "BUY" else (sell_core + sell_extra)
        return self._neutral(
            f"NEUTRAL: breakout {side} shartlari {best}/{len(buy_core)} (hajm yoki close tasdig'i kutilmoqda)",
            checks, indicators, partial_score=partial,
        )
