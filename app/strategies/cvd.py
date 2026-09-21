"""Strategiya 12 — CVD (Cumulative Volume Delta): buyurtma oqimi divergensiyasi.

Narx yangi tepalik qilyaptimi-yu, lekin faol XARID hajmi (taker buy) pasayyaptimi —
harakat soxta (kuchsiz), reversal yaqin. Bu narx grafigida ko'rinmaydigan
"yashirin" sotuv/xarid bosimini ko'rsatadi.

Binance spot kline ma'lumotida taker_buy_volume allaqachon bor (qo'shimcha so'rovsiz).
MEXC/oltinda bu maydon bo'lmasa — strategiya neytral qaytaradi (tizimga xalaqit bermaydi).
"""
from __future__ import annotations

import pandas as pd

from app.core.config import Settings
from app.core.enums import Direction
from app.indicators import indicators as ind
from app.indicators.bundle import IndicatorBundle
from app.strategies.base import BaseStrategy, StrategyResult


class CvdDivergenceStrategy(BaseStrategy):
    key = "cvd"
    display_name = "CVD (Hajm oqimi)"

    LOOKBACK = 60

    def analyze(self, df: pd.DataFrame, b: IndicatorBundle,
                settings: Settings, timeframe: str) -> StrategyResult:
        # Taker buy hajm bo'lmasa (masalan, oltin/MEXC) — aniq CVD hisoblab bo'lmaydi
        if "taker_buy_volume" not in df.columns:
            return self._neutral(
                "NEUTRAL: taker buy hajm ma'lumoti yo'q (CVD)", [], {}
            )

        window = df.tail(self.LOOKBACK).reset_index(drop=True)
        vol = window["volume"].astype(float)
        buy_vol = window["taker_buy_volume"].astype(float)
        sell_vol = (vol - buy_vol).clip(lower=0.0)
        delta = buy_vol - sell_vol
        cvd = delta.cumsum()
        close = window["close"].astype(float)
        high = window["high"].astype(float)
        low = window["low"].astype(float)

        indicators = {
            "cvd_last": round(float(cvd.iloc[-1]), 2),
            "cvd_prev": round(float(cvd.iloc[-2]), 2),
        }

        # ---- Bearish divergence: narx yangi yuqori, CVD yangi yuqori EMAS ----
        # Oxirgi ~20 shamdagi narx tepalari vs CVD tepalari
        seg = 25
        price_now = float(close.iloc[-1])
        price_max_prev = float(high.iloc[-seg - 5:-5].max())
        cvd_now = float(cvd.iloc[-1])
        cvd_max_prev = float(cvd.iloc[-seg - 5:-5].max())
        price_min_prev = float(low.iloc[-seg - 5:-5].min())
        cvd_min_prev = float(cvd.iloc[-seg - 5:-5].min())

        bear_div = price_now >= price_max_prev * 0.999 and cvd_now < cvd_max_prev
        bull_div = price_now <= price_min_prev * 1.001 and cvd_now > cvd_min_prev

        rsi_v = float(b.rsi.iloc[-1]) if b.rsi is not None and len(b.rsi) else 50.0
        is_green = float(close.iloc[-1]) >= float(window["open"].iloc[-1])

        # So'nggi 5 shamdagi delta trendi (bosim kuchi)
        delta_recent = float(delta.iloc[-5:].sum())
        delta_prev = float(delta.iloc[-12:-5].sum())

        if bear_div and not is_green:
            core = [
                ("Narx yangi tepalikka chiqdi", True),
                ("CVD yangi tepalik qilmadi — xarid bosimi kuchsiz", True),
                ("Tasdiq sham: qizil yopilish", not is_green),
                ("So'nggi delta salbiy (sotuv bosimi)", delta_recent < 0),
            ]
            passed = sum(1 for _, p in core if p)
            if passed >= 3:
                extra = [
                    ("RSI yuqori zona (>60)", rsi_v > 60),
                    ("Delta oldingi davrdan kuchsizlandi", delta_recent < delta_prev),
                ]
                ex = sum(1 for _, p in extra if p)
                return self._result(
                    Direction.SELL, float(passed), 4.0, ex,
                    f"SELL: narx-CVD bearish divergensiyasi (soxta o'sish, {ex} qo'shimcha)",
                    core + extra, indicators,
                )
            return self._neutral(
                f"NEUTRAL: bearish CVD divergence bor, tasdiq {passed}/4",
                core, indicators, partial_score=passed / 4 * 4.0,
            )

        if bull_div and is_green:
            core = [
                ("Narx yangi pastlikka tushdi", True),
                ("CVD yangi pastlik qilmadi — yashirin xarid bosimi", True),
                ("Tasdiq sham: yashil yopilish", is_green),
                ("So'nggi delta musbat (xarid bosimi)", delta_recent > 0),
            ]
            passed = sum(1 for _, p in core if p)
            if passed >= 3:
                extra = [
                    ("RSI past zona (<40)", rsi_v < 40),
                    ("Delta oldingi davrdan kuchaydi", delta_recent > delta_prev),
                ]
                ex = sum(1 for _, p in extra if p)
                return self._result(
                    Direction.BUY, float(passed), 4.0, ex,
                    f"BUY: narx-CVD bullish divergensiyasi (yashirin to'planish, {ex} qo'shimcha)",
                    core + extra, indicators,
                )
            return self._neutral(
                f"NEUTRAL: bullish CVD divergence bor, tasdiq {passed}/4",
                core, indicators, partial_score=passed / 4 * 4.0,
            )

        return self._neutral(
            "NEUTRAL: CVD divergensiyasi yo'q",
            [("Bearish divergence kuzatilmoqda", bear_div),
             ("Bullish divergence kuzatilmoqda", bull_div)],
            indicators,
        )
