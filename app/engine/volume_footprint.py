"""Volume Footprint Analysis — Momentum vs Absorption bars, CVD, Delta scoring."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from app.indicators.bundle import IndicatorBundle
from app.core.enums import Direction

if TYPE_CHECKING:
    from app.core.config import Settings


@dataclass
class VolumeBarClassification:
    """Classification of a single volume bar."""
    is_momentum: bool
    is_absorption: bool
    buy_volume: float
    sell_volume: float
    delta: float
    delta_pct: float
    body_size: float
    wick_size: float
    volume: float


@dataclass
class VolumeFootprintResult:
    """Complete volume footprint analysis result."""
    current_bar: VolumeBarClassification
    recent_bars: list[VolumeBarClassification]
    momentum_count: int
    absorption_count: int
    net_delta: float
    delta_trend: str
    volume_trend: str
    institutional_footprint: bool
    score: float
    details: list[str]


def classify_volume_bar(
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float,
    buy_volume: float | None = None,
    sell_volume: float | None = None,
) -> VolumeBarClassification:
    """
    Classify a single bar as Momentum or Absorption.
    Momentum: Large body, small wicks, high volume, delta aligned with direction.
    Absorption: Small body, large wicks, high volume, delta opposite or neutral.
    """
    body = abs(close - open_)
    total_range = high - low
    upper_wick = high - max(open_, close)
    lower_wick = min(open_, close) - low
    wick_size = upper_wick + lower_wick

    body_ratio = body / total_range if total_range > 0 else 0
    wick_ratio = wick_size / total_range if total_range > 0 else 0

    if buy_volume is not None and sell_volume is not None:
        delta = buy_volume - sell_volume
        delta_pct = delta / (buy_volume + sell_volume) if (buy_volume + sell_volume) > 0 else 0
    else:
        delta = volume if close > open_ else -volume
        delta_pct = 1.0 if close > open_ else -1.0

    is_momentum = (
        body_ratio > 0.6 and
        wick_ratio < 0.3 and
        volume > 0
    )

    is_absorption = (
        body_ratio < 0.3 and
        wick_ratio > 0.5 and
        volume > 0
    )

    return VolumeBarClassification(
        is_momentum=is_momentum,
        is_absorption=is_absorption,
        buy_volume=buy_volume or (volume if close > open_ else 0),
        sell_volume=sell_volume or (volume if close < open_ else 0),
        delta=delta,
        delta_pct=delta_pct,
        body_size=body_ratio,
        wick_size=wick_ratio,
        volume=volume,
    )


def analyze_volume_footprint(
    df: pd.DataFrame,
    lookback: int = 20,
    volume_ma_period: int = 20,
) -> VolumeFootprintResult:
    """
    Analyze volume footprint over recent bars.
    Returns classification, delta trends, and institutional footprint detection.
    """
    if len(df) < lookback:
        lookback = len(df)

    recent = df.tail(lookback).copy()

    if 'buy_volume' in recent.columns and 'sell_volume' in recent.columns:
        bars = [
            classify_volume_bar(
                row['open'], row['high'], row['low'], row['close'],
                row['volume'], row['buy_volume'], row['sell_volume']
            )
            for _, row in recent.iterrows()
        ]
    else:
        bars = [
            classify_volume_bar(
                row['open'], row['high'], row['low'], row['close'], row['volume']
            )
            for _, row in recent.iterrows()
        ]

    current_bar = bars[-1]
    momentum_count = sum(1 for b in bars if b.is_momentum)
    absorption_count = sum(1 for b in bars if b.is_absorption)

    deltas = [b.delta for b in bars]
    net_delta = sum(deltas)

    delta_sma_short = np.mean(deltas[-5:]) if len(deltas) >= 5 else deltas[-1]
    delta_sma_long = np.mean(deltas[-10:]) if len(deltas) >= 10 else delta_sma_short

    if delta_sma_short > delta_sma_long * 1.1:
        delta_trend = "INCREASING_BUY"
    elif delta_sma_short < delta_sma_long * 0.9:
        delta_trend = "INCREASING_SELL"
    else:
        delta_trend = "NEUTRAL"

    volumes = [b.volume for b in bars]
    vol_sma_short = np.mean(volumes[-5:]) if len(volumes) >= 5 else volumes[-1]
    vol_sma_long = np.mean(volumes[-10:]) if len(volumes) >= 10 else vol_sma_short

    if vol_sma_short > vol_sma_long * 1.2:
        volume_trend = "INCREASING"
    elif vol_sma_short < vol_sma_long * 0.8:
        volume_trend = "DECREASING"
    else:
        volume_trend = "STABLE"

    recent_momentum = sum(1 for b in bars[-5:] if b.is_momentum)
    recent_absorption = sum(1 for b in bars[-5:] if b.is_absorption)
    institutional_footprint = recent_momentum >= 3 or (recent_absorption >= 3 and abs(net_delta) > np.std(deltas) * 2)

    score = 0.0
    details = []

    if current_bar.is_momentum:
        score += 25
        details.append("✅ Current bar: MOMENTUM (strong directional conviction)")
    elif current_bar.is_absorption:
        score += 10
        details.append("⚠️ Current bar: ABSORPTION (supply/demand being absorbed)")
    else:
        details.append("➖ Current bar: NEUTRAL")

    if delta_trend == "INCREASING_BUY":
        score += 20
        details.append("📈 Delta trend: Increasing BUY pressure")
    elif delta_trend == "INCREASING_SELL":
        score += 20
        details.append("📉 Delta trend: Increasing SELL pressure")
    else:
        details.append("➖ Delta trend: Neutral")

    if volume_trend == "INCREASING":
        score += 15
        details.append("📊 Volume trend: Increasing")
    elif volume_trend == "DECREASING":
        score -= 10
        details.append("📉 Volume trend: Decreasing")
    else:
        details.append("➖ Volume trend: Stable")

    if institutional_footprint:
        score += 20
        details.append("🏦 Institutional footprint detected")

    if momentum_count >= lookback * 0.6:
        score += 15
        details.append(f"💪 {momentum_count}/{lookback} momentum bars (trend conviction)")
    elif absorption_count >= lookback * 0.5:
        score += 5
        details.append(f"🔄 {absorption_count}/{lookback} absorption bars (range consolidation)")

    score = max(0.0, min(100.0, score))

    return VolumeFootprintResult(
        current_bar=current_bar,
        recent_bars=bars,
        momentum_count=momentum_count,
        absorption_count=absorption_count,
        net_delta=net_delta,
        delta_trend=delta_trend,
        volume_trend=volume_trend,
        institutional_footprint=institutional_footprint,
        score=round(score, 1),
        details=details,
    )


def compute_cvd_score(
    bundle: IndicatorBundle,
    lookback: int = 50,
) -> tuple[float, str, list[str]]:
    """
    Compute CVD (Cumulative Volume Delta) based score.
    Returns: (score, trend_direction, details)
    """
    try:
        if not hasattr(bundle, 'cvd') or len(bundle.cvd) < lookback:
            return 50.0, "UNKNOWN", ["CVD data insufficient"]

        cvd = bundle.cvd.tail(lookback).dropna()
        if len(cvd) < 10:
            return 50.0, "UNKNOWN", ["CVD data insufficient"]

        cvd_current = float(cvd.iloc[-1])
        cvd_prev = float(cvd.iloc[-lookback // 2]) if len(cvd) > lookback // 2 else float(cvd.iloc[0])
        cvd_change = cvd_current - cvd_prev

        cvd_slope = np.polyfit(range(len(cvd)), cvd.values, 1)[0]
        cvd_accel = np.polyfit(range(len(cvd[-10:])), cvd.tail(10).values, 1)[0] if len(cvd) >= 10 else 0

        score = 50.0
        details = []

        if cvd_slope > 0:
            score += min(25, cvd_slope * 1000)
            trend = "BULLISH"
            details.append(f"CVD slope: POSITIVE ({cvd_slope:.4f})")
        else:
            score -= min(25, abs(cvd_slope) * 1000)
            trend = "BEARISH"
            details.append(f"CVD slope: NEGATIVE ({cvd_slope:.4f})")

        if cvd_accel > 0:
            score += 10
            details.append("CVD accelerating")
        elif cvd_accel < 0:
            score -= 10
            details.append("CVD decelerating")

        cvd_volatility = np.std(np.diff(cvd.values)) if len(cvd) > 1 else 0
        if cvd_volatility > 0:
            cvd_sharpe = cvd_slope / cvd_volatility if cvd_volatility > 0 else 0
            score += min(15, cvd_sharpe * 10)
            details.append(f"CVD consistency (Sharpe): {cvd_sharpe:.2f}")

        score = max(0.0, min(100.0, score))
        return round(score, 1), trend, details

    except Exception as exc:
        return 50.0, "ERROR", [f"CVD error: {exc}"]


def compute_delta_divergence(
    bundle: IndicatorBundle,
    price_lookback: int = 20,
    delta_lookback: int = 20,
) -> tuple[bool, str, float]:
    """
    Detect price vs delta divergence.
    Returns: (has_divergence, type, strength)
    """
    try:
        if not hasattr(bundle, 'cvd') or len(bundle.cvd) < max(price_lookback, delta_lookback):
            return False, "NONE", 0.0

        price = bundle.close.tail(price_lookback)
        cvd = bundle.cvd.tail(delta_lookback)

        price_high_idx = price.idxmax()
        price_low_idx = price.idxmin()
        cvd_high_idx = cvd.idxmax()
        cvd_low_idx = cvd.idxmin()

        bullish_div = price_low_idx > cvd_low_idx
        bearish_div = price_high_idx > cvd_high_idx

        if bullish_div:
            strength = abs(float(cvd.iloc[-1]) - float(cvd.loc[cvd_low_idx]))
            return True, "BULLISH", strength
        elif bearish_div:
            strength = abs(float(cvd.iloc[-1]) - float(cvd.loc[cvd_high_idx]))
            return True, "BEARISH", strength

        return False, "NONE", 0.0

    except Exception:
        return False, "ERROR", 0.0


def get_volume_profile_poc(
    df: pd.DataFrame,
    lookback: int = 100,
    bins: int = 20,
) -> tuple[float, float, list[tuple[float, float]]]:
    """
    Compute Volume Profile POC (Point of Control) and VAH/VAL.
    Returns: (poc_price, vah, val, profile_data)
    """
    if len(df) < lookback:
        lookback = len(df)

    recent = df.tail(lookback)

    price_min = recent['low'].min()
    price_max = recent['high'].max()

    if price_max == price_min:
        return float(price_min), float(price_max), float(price_min), []

    bin_edges = np.linspace(price_min, price_max, bins + 1)
    volume_profile = np.zeros(bins)

    for _, row in recent.iterrows():
        vol = row['volume']
        mid_price = (row['high'] + row['low']) / 2
        bin_idx = min(int((mid_price - price_min) / (price_max - price_min) * bins), bins - 1)
        volume_profile[bin_idx] += vol

    poc_idx = np.argmax(volume_profile)
    poc_price = (bin_edges[poc_idx] + bin_edges[poc_idx + 1]) / 2

    total_vol = volume_profile.sum()
    target_vol = total_vol * 0.7

    cumsum = np.cumsum(volume_profile[::-1])
    vah_idx = bins - 1 - np.searchsorted(cumsum, target_vol, side='left')
    vah_idx = max(poc_idx, min(vah_idx, bins - 1))

    cumsum = np.cumsum(volume_profile)
    val_idx = np.searchsorted(cumsum, target_vol, side='left')
    val_idx = min(poc_idx, max(val_idx, 0))

    vah = (bin_edges[vah_idx] + bin_edges[vah_idx + 1]) / 2
    val = (bin_edges[val_idx] + bin_edges[val_idx + 1]) / 2

    profile_data = [
        ((bin_edges[i] + bin_edges[i + 1]) / 2, float(volume_profile[i]))
        for i in range(bins)
    ]

    return float(poc_price), float(vah), float(val), profile_data