"""Bozor rejimini aniqlash: TRENDING / RANGING / HIGH_VOLATILITY / LOW_VOLATILITY."""
from __future__ import annotations

from app.core.enums import MarketRegime
from app.indicators.bundle import IndicatorBundle


def detect_regime(b: IndicatorBundle) -> MarketRegime:
    adx_v = float(b.adx.iloc[-1])
    atr_v = b.last_atr
    close = b.last_close
    if close <= 0 or atr_v <= 0:
        return MarketRegime.RANGING

    atr_pct = atr_v / close * 100.0
    atr_avg = float(b.atr.rolling(100).mean().iloc[-1])
    atr_ratio = (atr_v / atr_avg) if atr_avg and atr_avg == atr_avg else 1.0

    ema_sep = abs(float(b.ema50.iloc[-1]) - float(b.ema200.iloc[-1])) / close * 100.0

    # 1) Juda yuqori volatillik
    if atr_ratio >= 1.5:
        return MarketRegime.HIGH_VOLATILITY

    # 2) Aniq trend
    if adx_v >= 23 and ema_sep >= 0.25:
        return MarketRegime.TRENDING

    # 3) Juda past volatillik (sokin bozor)
    if atr_ratio <= 0.7 and adx_v < 18:
        return MarketRegime.LOW_VOLATILITY

    # 4) Qolgan holat — range (yon tomonga)
    return MarketRegime.RANGING


REGIME_UZ = {
    MarketRegime.TRENDING: "TREND (yo'nalishli harakat)",
    MarketRegime.RANGING: "RANGE (yon tomonga)",
    MarketRegime.HIGH_VOLATILITY: "YUQORI VOLATILLIK",
    MarketRegime.LOW_VOLATILITY: "PAST VOLATILLIK",
}
