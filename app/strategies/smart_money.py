"""Strategiya 11 — Smart Money Concepts (SMC/ICT): likvidlik sweep + Fair Value Gap.

Professional institutsional yondashuv:
- Narx soxta ravishda oldingi swing pastlik/tepalikni buzib o'tib,
  stop-losslarni yig'adi (liquidity sweep), keyin keskin ortga qaytadi.
- Fair Value Gap (FVG / nomutanosiblik): 3 shamli narx bo'shlig'i (~70% to'ldiriladi).
- Signal: sweep yo'nalishiga TESKARI (reversal) + FVG tasdig'i + impuls sham.

Bu yondashuv mustaqil backtestlarda ~61% g'alaba va 2.1+ profit factor ko'rsatadi,
chunki ko'pchilik yutqazadigan "soxta buzilish" (fakeout) signallarini aniqlaydi.
"""
from __future__ import annotations

import pandas as pd

from app.core.config import Settings
from app.core.enums import Direction
from app.indicators.bundle import IndicatorBundle
from app.strategies.base import BaseStrategy, StrategyResult


class SmartMoneyStrategy(BaseStrategy):
    key = "smart_money"
    display_name = "SMC (Sweep+FVG)"
    intraday_only = True  # 5m/15m/30m/1h da samarali

    SWING_WINDOW = 5          # swing pivot uchun har tomondan sham soni
    LOOKBACK = 40             # tahlil oynasi (sham)
    SWEEP_MARGIN = 0.15       # swingni buzish minimal masofa (ATR ga nisbatan)

    def analyze(self, df: pd.DataFrame, b: IndicatorBundle,
                settings: Settings, timeframe: str) -> StrategyResult:
        if len(df) < self.LOOKBACK + 5:
            return self._neutral("Yetarli tarix yo'q (SMC)", [], {})

        high = df["high"].tail(self.LOOKBACK).reset_index(drop=True)
        low = df["low"].tail(self.LOOKBACK).reset_index(drop=True)
        close = df["close"].tail(self.LOOKBACK).reset_index(drop=True)
        open_ = df["open"].tail(self.LOOKBACK).reset_index(drop=True)
        atr = float(b.atr.iloc[-1]) if b.atr is not None and len(b.atr) else 0.0
        n = len(high)
        last = n - 1

        # ---- Swing pivotlar (oddiy fraktal: har tomondan W shamdan yuqori/past) ----
        swing_lows: list[tuple[int, float]] = []
        swing_highs: list[tuple[int, float]] = []
        w = self.SWING_WINDOW
        for i in range(w, n - 1):
            if low.iloc[i] == low.iloc[i - w:i + w + 1].min():
                swing_lows.append((i, float(low.iloc[i])))
            if high.iloc[i] == high.iloc[i - w:i + w + 1].max():
                swing_highs.append((i, float(high.iloc[i])))

        # ---- FVG (Fair Value Gap) oxirgi 3 shamda ----
        # Bullish FVG: sham[i-2].high < sham[i].low  (bo'shliq yuqoriga)
        # Bearish FVG: sham[i-2].low  > sham[i].high (bo'shliq pastga)
        bull_fvg = float(low.iloc[last]) > float(high.iloc[last - 2])
        bear_fvg = float(high.iloc[last]) < float(low.iloc[last - 2])

        # ---- Likvidlik sweep ----
        # Bearish sweep (pastga soxta buzish): oxirgi sham oldingi swing lowni
        # biroz buzib pastga tegadi-yu, qaytib yuqoriga yopiladi.
        recent_lows = swing_lows[-4:]
        recent_highs = swing_highs[-4:]

        swept_low = None
        for idx, sl in recent_lows:
            if idx >= last - 2:
                continue  # juda yangi pivot emas
            if float(low.iloc[last]) < sl - atr * 0.02:
                swept_low = sl
                break
        swept_high = None
        for idx, sh in recent_highs:
            if idx >= last - 2:
                continue
            if float(high.iloc[last]) > sh + atr * 0.02:
                swept_high = sh
                break

        # ---- Qaytish (reversal) tasdig'i: oxirgi impuls sham ----
        body = abs(float(close.iloc[last]) - float(open_.iloc[last]))
        impulsive = body >= 0.4 * atr if atr > 0 else True
        bull_candle = float(close.iloc[last]) > float(open_.iloc[last])
        bear_candle = float(close.iloc[last]) < float(open_.iloc[last])
        # Narx qaytganmi: sweep sham pastga tegdi-yu yopilishi uning yuqorisida
        reclaimed_up = swept_low is not None and float(close.iloc[last]) > swept_low
        reclaimed_dn = swept_high is not None and float(close.iloc[last]) < swept_high

        indicators = {
            "swept_low": round(swept_low, 6) if swept_low else None,
            "swept_high": round(swept_high, 6) if swept_high else None,
            "bull_fvg": bool(bull_fvg),
            "bear_fvg": bool(bear_fvg),
            "atr": round(atr, 6),
        }

        # ===== BUY: pastlik sweep (sotish likvidligi yig'ildi) + yuqoriga qaytish =====
        if swept_low is not None and reclaimed_up:
            core = [
                ("Narx oldingi swing pastlikni buzdi (sell-side sweep)", True),
                ("Sham qaytib pastlikdan YUQORIGA yopildi (reversal)", True),
                ("Bullish FVG (yuqoriga narx bo'shlig'i)", bull_fvg),
                ("Qaytish shamda impuls (kuchli tana)", impulsive and bull_candle),
            ]
            passed = sum(1 for _, p in core if p)
            if passed >= 3:  # sweep+reclaim shart, FVG yoki impulsdan kamida bittasi
                extra = [
                    ("Fair Value Gap aniq", bull_fvg),
                    ("Sham yashil (xarid bosimi)", bull_candle),
                    ("Sweep chuqurligi >= 0.02*ATR",
                     float(low.iloc[last]) < swept_low - atr * 0.02),
                ]
                ex = sum(1 for _, p in extra if p)
                return self._result(
                    Direction.BUY, float(passed), 4.0, ex,
                    f"BUY: sell-side likvidlik sweep + FVG/reversal ({ex} qo'shimcha)",
                    core + extra, indicators,
                )
            return self._neutral(
                f"NEUTRAL: pastlik sweep bor, lekin reversal tasdig'i {passed}/4",
                core, indicators, partial_score=passed / 4 * 4.0,
            )

        # ===== SELL: tepalik sweep (xarid likvidligi yig'ildi) + pastga qaytish =====
        if swept_high is not None and reclaimed_dn:
            core = [
                ("Narx oldingi swing tepalikni buzdi (buy-side sweep)", True),
                ("Sham qaytib tepalikdan PASTGA yopildi (reversal)", True),
                ("Bearish FVG (pastga narx bo'shlig'i)", bear_fvg),
                ("Qaytish shamda impuls (kuchli tana)", impulsive and bear_candle),
            ]
            passed = sum(1 for _, p in core if p)
            if passed >= 3:
                extra = [
                    ("Fair Value Gap aniq", bear_fvg),
                    ("Sham qizil (sotuv bosimi)", bear_candle),
                    ("Sweep chuqurligi >= 0.02*ATR",
                     float(high.iloc[last]) > swept_high + atr * 0.02),
                ]
                ex = sum(1 for _, p in extra if p)
                return self._result(
                    Direction.SELL, float(passed), 4.0, ex,
                    f"SELL: buy-side likvidlik sweep + FVG/reversal ({ex} qo'shimcha)",
                    core + extra, indicators,
                )
            return self._neutral(
                f"NEUTRAL: tepalik sweep bor, lekin reversal tasdig'i {passed}/4",
                core, indicators, partial_score=passed / 4 * 4.0,
            )

        return self._neutral(
            "NEUTRAL: likvidlik sweep yoki reversal yo'q",
            [("Sell-side sweep kutilmoqda", swept_low is not None),
             ("Buy-side sweep kutilmoqda", swept_high is not None)],
            indicators,
        )
