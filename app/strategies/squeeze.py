"""Strategiya 6 — Squeeze Breakout (Bollinger + Keltner, TT Squeeze uslubi)."""
from __future__ import annotations

import pandas as pd

from app.core.config import Settings
from app.core.enums import Direction
from app.indicators.bundle import IndicatorBundle
from app.strategies.base import BaseStrategy, StrategyResult


class SqueezeBreakoutStrategy(BaseStrategy):
    key = "squeeze"
    display_name = "Squeeze Breakout"

    def analyze(self, df: pd.DataFrame, b: IndicatorBundle,
                settings: Settings, timeframe: str) -> StrategyResult:
        c = b.last_close
        open_ = float(b.open_.iloc[-1])
        squeeze_now = bool(b.squeeze.iloc[-1])
        # So'nggi ~10 sham ichida sikvez bo'lganmi?
        recent_squeeze = bool(b.squeeze.tail(10).any())
        momentum = float(b.momentum_slope.iloc[-1])
        mom_prev = float(b.momentum_slope.iloc[-2]) if len(b.momentum_slope) >= 2 else 0.0
        kc_up = float(b.kc_upper.iloc[-1])
        kc_low = float(b.kc_lower.iloc[-1])
        bb_width_now = float(b.bb_width.iloc[-1])
        ema50 = float(b.ema50.iloc[-1])
        ema200 = float(b.ema200.iloc[-1])
        adx_v = float(b.adx.iloc[-1])
        rsi_v = float(b.rsi.iloc[-1])
        vol = float(b.volume.iloc[-1])
        vol_ma = float(b.vol_ma.iloc[-1]) or 0.0
        atr_v = b.last_atr
        is_green = open_ <= c

        indicators = {
            "Squeeze": "FAOL" if recent_squeeze else "yo'q",
            "Momentum slope": round(momentum, 6),
            "KC_upper": round(kc_up, 6), "KC_lower": round(kc_low, 6),
            "BB_width": round(bb_width_now, 5),
            "ADX": round(adx_v, 1), "RSI": round(rsi_v, 1),
        }

        # Squeeze chiqishi (fire): sikvez tugab, momentum narxni yuqoriga/pastga otadi
        squeeze_fired_up = recent_squeeze and (not squeeze_now) and momentum > 0
        squeeze_fired_down = recent_squeeze and (not squeeze_now) and momentum < 0

        buy_core = [
            ("Sikvez (BB Keltner ichida) yaqinda bo'lgan", recent_squeeze),
            ("Squeeze chiqishi: narx Keltner ustidan yopildi", c > kc_up),
            ("Momentum slope musbat va o'smoqda", momentum > 0 and momentum >= mom_prev),
            ("Trend filtri: narx EMA200 dan yuqori", c > ema200),
            ("Sham yopilgan tasdig'i", True),
        ]
        buy_extra = [
            ("EMA50 > EMA200", ema50 > ema200),
            ("ADX > 20 (harakat kuchi)", adx_v > 20),
            ("RSI 50–75 (sog'lom momentum)", 50 < rsi_v < 75),
            ("Hajm o'rtachadan yuqori", vol > vol_ma),
            ("Yashil sham", is_green),
            ("Squeeze narxni yuqoriga otdi", squeeze_fired_up),
        ]

        sell_core = [
            ("Sikvez yaqinda bo'lgan", recent_squeeze),
            ("Squeeze chiqishi: narx Keltner ostidan yopildi", c < kc_low),
            ("Momentum slope manfiy va pasaymoqda", momentum < 0 and momentum <= mom_prev),
            ("Trend filtri: narx EMA200 dan past", c < ema200),
            ("Sham yopilgan tasdig'i", True),
        ]
        sell_extra = [
            ("EMA50 < EMA200", ema50 < ema200),
            ("ADX > 20", adx_v > 20),
            ("RSI 25–50", 25 < rsi_v < 50),
            ("Hajm o'rtachadan yuqori", vol > vol_ma),
            ("Qizil sham", not is_green),
            ("Squeeze narxni pastga otdi", squeeze_fired_down),
        ]

        buy_pass = sum(1 for _, p in buy_core if p)
        sell_pass = sum(1 for _, p in sell_core if p)

        if buy_pass == len(buy_core):
            extra = sum(1 for _, p in buy_extra if p)
            return self._result(
                Direction.BUY, float(buy_pass), float(len(buy_core)), extra,
                f"BUY: volatillik sikvezdan yuqoriga chiqish tasdiqlandi ({extra} qo'shimcha)",
                buy_core + buy_extra, indicators,
            )
        if sell_pass == len(sell_core):
            extra = sum(1 for _, p in sell_extra if p)
            return self._result(
                Direction.SELL, float(sell_pass), float(len(sell_core)), extra,
                f"SELL: volatillik sikvezdan pastga chiqish tasdiqlandi ({extra} qo'shimcha)",
                sell_core + sell_extra, indicators,
            )

        best = max(buy_pass, sell_pass)
        partial = best / len(buy_core) * 4.0
        side = "BUY" if buy_pass >= sell_pass else "SELL"
        checks = (buy_core + buy_extra) if side == "BUY" else (sell_core + sell_extra)
        return self._neutral(
            f"NEUTRAL: squeeze {side} shartlari {best}/{len(buy_core)}",
            checks, indicators, partial_score=partial,
        )
