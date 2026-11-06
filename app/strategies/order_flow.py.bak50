"""Strategiya: Order Flow / Mikrostruktur tahlili (CVD, Volume Delta, Bid-Ask Imbalance).

Bu strategiya 5m/15m timeframelarda kirish nuqtasini aniqlash uchun mo'ljallangan.
Asosiy komponentlar:
1. CVD (Cumulative Volume Delta) - xarid/sotuv bosimi farqi
2. Volume Delta divergence - narx va hajim o'zgarishi farqi
3. Bid-Ask imbalance (proxy: close position in range + volume)
4. Large trade detection (whale alerts) - katta hajmdagi shamlar
5. Order flow imbalance at key levels (support/resistance)

Signal: CVD trend + volume delta confirmation + impulsive candle
"""
from __future__ import annotations

import pandas as pd
import numpy as np

from app.core.config import Settings
from app.core.enums import Direction
from app.indicators.bundle import IndicatorBundle
from app.strategies.base import BaseStrategy, StrategyResult


class OrderFlowStrategy(BaseStrategy):
    key = "order_flow"
    display_name = "Order Flow (CVD+Delta)"
    intraday_only = True  # Faqat 5m/15m/30m/1h

    LOOKBACK = 50
    CVD_LOOKBACK = 100
    MIN_DELTA_RATIO = 0.15  # Minimal delta/hajim nisbati
    WHALE_VOLUME_MULT = 3.0  # Kattasini aniqlash uchun o'rtachadan ko'paytiruvchi

    def analyze(self, df: pd.DataFrame, b: IndicatorBundle,
                settings: Settings, timeframe: str) -> StrategyResult:
        # Faqat past timeframelarda ishlaydi
        if timeframe not in ("5m", "15m", "30m", "1h"):
            return self._neutral("Order Flow: Faqat 5m/15m/30m/1h da ishlaydi", [], {})

        if len(df) < self.LOOKBACK + 10:
            return self._neutral("Yetarli tarix yo'q (Order Flow)", [], {})

        close = df["close"].tail(self.LOOKBACK).reset_index(drop=True)
        open_ = df["open"].tail(self.LOOKBACK).reset_index(drop=True)
        high = df["high"].tail(self.LOOKBACK).reset_index(drop=True)
        low = df["low"].tail(self.LOOKBACK).reset_index(drop=True)
        volume = df["volume"].tail(self.LOOKBACK).reset_index(drop=True)

        atr = float(b.atr.iloc[-1]) if b.atr is not None and len(b.atr) else 0.0
        n = len(close)
        last = n - 1

        # ===== 1. CVD (Cumulative Volume Delta) hisoblash =====
        # Delta = (close - open) / (high - low) * volume  (approximate buy/sell pressure)
        # Agar close > open: buying pressure, aks holda selling
        body = close - open_
        range_ = high - low
        range_[range_ == 0] = 1e-9  # division by zero oldini olish

        # Volume delta per candle
        delta = (body / range_) * volume
        cvd = delta.cumsum()

        # CVD slope (trend)
        cvd_recent = cvd.tail(20)
        cvd_slope = float(np.polyfit(range(len(cvd_recent)), cvd_recent, 1)[0]) if len(cvd_recent) == 20 else 0.0
        cvd_mean = cvd_recent.mean()
        cvd_std = cvd_recent.std() if cvd_recent.std() > 0 else 1.0
        cvd_zscore = (cvd.iloc[-1] - cvd_mean) / cvd_std

        # ===== 2. Volume Delta Divergence =====
        # Narx yangi high/low qilganda, delta emas - divergence
        price_higher_high = close.iloc[-1] > close.iloc[-5:-1].max()
        price_lower_low = close.iloc[-1] < close.iloc[-5:-1].min()
        delta_higher_high = delta.iloc[-1] > delta.iloc[-5:-1].max()
        delta_lower_low = delta.iloc[-1] < delta.iloc[-5:-1].min()

        bullish_div = price_lower_low and not delta_lower_low  # Narx pastroq, delta emas
        bearish_div = price_higher_high and not delta_higher_high  # Narx yuqoriroq, delta emas

        # ===== 3. Order Flow Imbalance (proxy) =====
        # Close position in range: 1 = high, 0 = low
        close_pos = (close.iloc[-1] - low.iloc[-1]) / (high.iloc[-1] - low.iloc[-1] + 1e-9)
        vol_ratio = volume.iloc[-1] / (volume.iloc[-10:-1].mean() + 1e-9)

        # Buying pressure: yuqori close position + yuqori volume
        buy_pressure = close_pos > 0.6 and vol_ratio > 1.2
        sell_pressure = close_pos < 0.4 and vol_ratio > 1.2

        # ===== 4. Whale / Large Trade Detection =====
        # O'rtacha hajmdan WHALE_VOLUME_MULT marta katta shamar
        avg_vol = volume.iloc[-20:-1].mean()
        whale_candle = volume.iloc[-1] > avg_vol * self.WHALE_VOLUME_MULT
        whale_direction = Direction.BUY if close.iloc[-1] > open_.iloc[-1] else Direction.SELL

        # ===== 5. CVD Trend Confirmation =====
        cvd_trending_up = cvd_slope > 0 and cvd_zscore > 0.5
        cvd_trending_down = cvd_slope < 0 and cvd_zscore < -0.5

        # ===== 6. Support/Resistance at Current Level (VWAP + Volume) =====
        vwap = float(b.vwap.iloc[-1]) if b.vwap is not None else close.iloc[-1]
        at_vwap = abs(close.iloc[-1] - vwap) / close.iloc[-1] < 0.002  # 0.2% yaqinlik

        indicators = {
            "cvd": round(cvd.iloc[-1], 2),
            "cvd_slope": round(cvd_slope, 4),
            "cvd_zscore": round(cvd_zscore, 2),
            "delta": round(delta.iloc[-1], 2),
            "bullish_divergence": bullish_div,
            "bearish_divergence": bearish_div,
            "close_position": round(close_pos, 2),
            "volume_ratio": round(vol_ratio, 2),
            "whale_candle": whale_candle,
            "whale_direction": whale_direction.value if whale_candle else None,
            "buy_pressure": buy_pressure,
            "sell_pressure": sell_pressure,
            "at_vwap": at_vwap,
        }

        # ===== BUY SIGNAL =====
        buy_core = [
            ("CVD trending up (xarid bosimi)", cvd_trending_up),
            ("Bullish volume delta divergence", bullish_div),
            ("Buy pressure (close yukori + volume)", buy_pressure),
            ("Impulsive green candle", close.iloc[-1] > open_.iloc[-1] and abs(close.iloc[-1] - open_.iloc[-1]) > 0.4 * atr),
        ]
        buy_extra = [
            ("Whale buying detected", whale_candle and whale_direction == Direction.BUY),
            ("At VWAP support", at_vwap and close.iloc[-1] >= vwap),
            ("CVD z-score > 1", cvd_zscore > 1.0),
        ]
        bp = sum(1 for _, p in buy_core if p)
        if bp >= 3:  # Kamida 3 ta core shart
            ex = sum(1 for _, p in buy_extra if p)
            return self._result(
                Direction.BUY, float(bp), 4.0, ex,
                f"BUY: Order Flow - CVD up + buy pressure + divergence ({ex} qo'shimcha)",
                buy_core + buy_extra, indicators,
            )

        # ===== SELL SIGNAL =====
        sell_core = [
            ("CVD trending down (sotuv bosimi)", cvd_trending_down),
            ("Bearish volume delta divergence", bearish_div),
            ("Sell pressure (close past + volume)", sell_pressure),
            ("Impulsive red candle", close.iloc[-1] < open_.iloc[-1] and abs(close.iloc[-1] - open_.iloc[-1]) > 0.4 * atr),
        ]
        sell_extra = [
            ("Whale selling detected", whale_candle and whale_direction == Direction.SELL),
            ("At VWAP resistance", at_vwap and close.iloc[-1] <= vwap),
            ("CVD z-score < -1", cvd_zscore < -1.0),
        ]
        sp = sum(1 for _, p in sell_core if p)
        if sp >= 3:
            ex = sum(1 for _, p in sell_extra if p)
            return self._result(
                Direction.SELL, float(sp), 4.0, ex,
                f"SELL: Order Flow - CVD down + sell pressure + divergence ({ex} qo'shimcha)",
                sell_core + sell_extra, indicators,
            )

        best = max(bp, sp)
        partial = best / len(buy_core) * 4.0
        side = "BUY" if bp >= sp else "SELL"
        return self._neutral(
            f"NEUTRAL: Order Flow {side} shartlari {best}/{len(buy_core)}",
            (buy_core + buy_extra) if side == "BUY" else (sell_core + sell_extra),
            indicators, partial_score=partial,
        )