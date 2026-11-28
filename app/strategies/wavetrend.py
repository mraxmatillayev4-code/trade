"""WaveTrend / VuManChu Cipher B uslubidagi ovoz.

FxDailyReport Cipher B g'oyasi (yashil/qizil nuqta + divergensiya + money flow),
lekin yolg'iz har qanday nuqta ovoz bermaydi — kamida 2 tasdiq va ekstremum.

Formula (LazyBear/Cipher B):
  hlc3 = (H+L+C)/3
  esa  = EMA(hlc3, 9)
  de   = EMA(|hlc3-esa|, 9)
  ci   = (hlc3-esa) / (0.015 * de)
  wt1  = EMA(ci, 12)
  wt2  = SMA(wt1, 4)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.core.config import Settings
from app.core.enums import Direction
from app.indicators import indicators as ind
from app.indicators.bundle import IndicatorBundle
from app.strategies.base import BaseStrategy, StrategyResult

# Cipher B default darajalari
_N1 = 9
_N2 = 12
_OS = -53.0   # oversold (nuqta zonasi); -60 juda qattiq, -53 sifat+son muvozanati
_OB = 53.0
_MF_PERIOD = 60


def _wavetrend(high: pd.Series, low: pd.Series, close: pd.Series
               ) -> tuple[pd.Series, pd.Series]:
    hlc3 = (high.astype(float) + low.astype(float) + close.astype(float)) / 3.0
    esa = ind.ema(hlc3, _N1)
    de = ind.ema((hlc3 - esa).abs(), _N1).replace(0.0, np.nan)
    ci = (hlc3 - esa) / (0.015 * de)
    wt1 = ind.ema(ci, _N2)
    wt2 = ind.sma(wt1, 4)
    return wt1, wt2


def _money_flow(high: pd.Series, low: pd.Series, close: pd.Series,
                volume: pd.Series) -> pd.Series:
    """Cipher B dagi MFI-area o'rniga barqaror imzo: EMA(signed volume).

    Volume 0 bo'lsa (ba'zi CFD) |H-L| proxy. >0 = pul kiryapti (yashil).
    """
    hlc3 = (high.astype(float) + low.astype(float) + close.astype(float)) / 3.0
    vol = volume.astype(float)
    proxy = (high.astype(float) - low.astype(float)).abs().clip(lower=1e-12)
    vol = vol.where(vol > 0, proxy)
    signed = np.sign(hlc3.diff().fillna(0.0)) * vol
    return ind.ema(signed, _MF_PERIOD)


def _wt_divergence(high: pd.Series, low: pd.Series, wt1: pd.Series
                   ) -> str:
    """Regular divergensiya: narx vs WaveTrend. Repaint yo'q (tasdiqlangan pivot)."""
    if wt1.isna().all() or len(wt1) < 30:
        return "NEUTRAL"
    n = len(wt1)
    pivot_highs, pivot_lows = ind.find_pivots(high, low, left=2, right=2)
    w = wt1.to_numpy(dtype=float)
    lookback = min(90, n)

    lows = [(i, p) for i, p in pivot_lows if i >= n - lookback]
    highs = [(i, p) for i, p in pivot_highs if i >= n - lookback]

    if len(lows) >= 2:
        (i1, p1), (i2, p2) = lows[-2], lows[-1]
        if p2 < p1 and w[i2] > w[i1] and np.isfinite(w[i1]) and np.isfinite(w[i2]):
            return "BUY"
    if len(highs) >= 2:
        (i1, p1), (i2, p2) = highs[-2], highs[-1]
        if p2 > p1 and w[i2] < w[i1] and np.isfinite(w[i1]) and np.isfinite(w[i2]):
            return "SELL"
    return "NEUTRAL"


class WaveTrendStrategy(BaseStrategy):
    key = "wavetrend"
    display_name = "WaveTrend (Cipher B)"

    def analyze(self, df: pd.DataFrame, b: IndicatorBundle,
                settings: Settings, timeframe: str) -> StrategyResult:
        if len(df) < 80:
            return self._neutral("Yetarli tarix yo'q (WaveTrend)", [], {})

        high, low, close = b.high, b.low, b.close
        wt1, wt2 = _wavetrend(high, low, close)
        mf = _money_flow(high, low, close, b.volume)

        w1 = float(wt1.iloc[-1]) if np.isfinite(wt1.iloc[-1]) else 0.0
        w2 = float(wt2.iloc[-1]) if np.isfinite(wt2.iloc[-1]) else 0.0
        w1p = float(wt1.iloc[-2]) if len(wt1) >= 2 and np.isfinite(wt1.iloc[-2]) else w1
        w2p = float(wt2.iloc[-2]) if len(wt2) >= 2 and np.isfinite(wt2.iloc[-2]) else w2
        mf_now = float(mf.iloc[-1]) if np.isfinite(mf.iloc[-1]) else 0.0
        ema200 = float(b.ema200.iloc[-1]) if np.isfinite(b.ema200.iloc[-1]) else 0.0
        c = float(b.last_close)
        bb_w = float(b.bb_width.iloc[-1]) if np.isfinite(b.bb_width.iloc[-1]) else 0.0

        cross_up = w1p <= w2p and w1 > w2
        cross_dn = w1p >= w2p and w1 < w2
        oversold = w1 <= _OS
        overbought = w1 >= _OB
        mid_band = (not oversold) and (not overbought) and abs(w1) < 40

        buy_cross = cross_up and oversold
        sell_cross = cross_dn and overbought
        div = _wt_divergence(high, low, wt1)
        mf_green = mf_now > 0
        wt_zero_up = w1p <= 0 <= w1
        wt_zero_dn = w1p >= 0 >= w1

        indicators = {
            "WT1": round(w1, 2),
            "WT2": round(w2, 2),
            "money_flow": "yashil" if mf_green else "qizil",
            "divergensiya": div if div != "NEUTRAL" else "yo'q",
            "BB_width": round(bb_w, 5),
        }

        # O'lik bozor — ovoz yo'q
        atr_v = b.last_atr or 0.0
        if c > 0 and atr_v / c < 0.00015:
            return self._neutral("NEUTRAL: ATR juda kichik (o'lik bozor)", [], indicators)

        # O'rta panel kesishishlari — Cipher B ning asosiy tuzog'i
        if mid_band and div == "NEUTRAL":
            return self._neutral(
                "NEUTRAL: WaveTrend o'rta zonada (ekstremum/divergensiya yo'q)",
                [], indicators,
            )

        buy_a = buy_cross
        buy_b = div == "BUY"
        buy_c = mf_green or wt_zero_up
        buy_n = int(buy_a) + int(buy_b) + int(buy_c)

        sell_a = sell_cross
        sell_b = div == "SELL"
        sell_c = (not mf_green) or wt_zero_dn
        sell_n = int(sell_a) + int(sell_b) + int(sell_c)

        buy_core = [
            ("WT oversold kesish (yashil nuqta)", buy_a),
            ("Bullish divergensiya (narx LL, WT HL)", buy_b),
            ("Money flow yashil yoki WT nolni tesdi", buy_c),
            ("Kamida 2 tasdiq", buy_n >= 2),
        ]
        buy_extra = [
            ("Narx EMA200 ustida (trend filtri)", c > ema200),
            ("WT chuqur oversold (<= -60)", w1 <= -60),
        ]
        sell_core = [
            ("WT overbought kesish (qizil nuqta)", sell_a),
            ("Bearish divergensiya (narx HH, WT LH)", sell_b),
            ("Money flow qizil yoki WT nolni tesdi", sell_c),
            ("Kamida 2 tasdiq", sell_n >= 2),
        ]
        sell_extra = [
            ("Narx EMA200 ostida (trend filtri)", c < ema200),
            ("WT chuqur overbought (>= 60)", w1 >= 60),
        ]

        # Signal: kamida 2 tasdiq (4-core shartning oxirgisi True) + A yoki B
        if buy_n >= 2 and (buy_a or buy_b):
            extra = sum(1 for _, p in buy_extra if p)
            return self._result(
                Direction.BUY, float(buy_n), 3.0, extra,
                f"BUY: WaveTrend Cipher B ({buy_n}/3 tasdiq, {extra} qo'shimcha)",
                buy_core + buy_extra, indicators,
            )
        if sell_n >= 2 and (sell_a or sell_b):
            extra = sum(1 for _, p in sell_extra if p)
            return self._result(
                Direction.SELL, float(sell_n), 3.0, extra,
                f"SELL: WaveTrend Cipher B ({sell_n}/3 tasdiq, {extra} qo'shimcha)",
                sell_core + sell_extra, indicators,
            )

        best = max(buy_n, sell_n)
        side = "BUY" if buy_n >= sell_n else "SELL"
        checks = (buy_core + buy_extra) if side == "BUY" else (sell_core + sell_extra)
        return self._neutral(
            f"NEUTRAL: WaveTrend {side} tasdiq {best}/3",
            checks, indicators, partial_score=best / 3.0 * 4.0,
        )
