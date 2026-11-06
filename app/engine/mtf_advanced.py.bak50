"""Advanced Multi-Timeframe Analysis — Weighted votes, trend strength, session awareness."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pandas as pd

from app.core.config import Settings
from app.core.enums import Direction, HIGHER_TIMEFRAMES, MTFAlignment, Timeframe
from app.indicators.bundle import compute_bundle

if TYPE_CHECKING:
    from app.indicators.bundle import IndicatorBundle


@dataclass
class HTFVote:
    timeframe: str
    direction: Direction
    weight: float
    trend_strength: float
    adx: float
    ema_alignment: bool
    price_vs_ema: str
    confidence: float


@dataclass
class MTFAnalysisResult:
    votes: list[HTFVote]
    weighted_direction: Direction
    alignment: MTFAlignment
    total_weight: float
    agree_weight: float
    oppose_weight: float
    neutral_weight: float
    consensus_score: float
    trend_quality: str
    session_factor: float
    details: list[str]


HTF_WEIGHTS = {
    "5m": 1.0,
    "15m": 1.5,
    "30m": 2.0,
    "1h": 3.0,
    "4h": 5.0,
    "1d": 8.0,
}

HTF_MIN_ADX = {
    "5m": 15,
    "15m": 18,
    "30m": 20,
    "1h": 22,
    "4h": 25,
    "1d": 25,
}


def _session_factor(tf: str, utc_hour: int) -> float:
    """Session-based weight adjustment for HTF."""
    if tf in ("5m", "15m"):
        if (7 <= utc_hour <= 10) or (13 <= utc_hour <= 17):
            return 1.2
        return 0.8
    elif tf in ("1h", "4h"):
        if (7 <= utc_hour <= 10) or (13 <= utc_hour <= 17):
            return 1.1
        return 0.95
    return 1.0


def analyze_htf_trend(
    df: pd.DataFrame,
    timeframe: str,
    settings: Settings,
) -> HTFVote | None:
    """Analyze single higher timeframe for trend direction and strength."""
    if len(df) < settings.min_candles:
        return None

    try:
        b = compute_bundle(df, settings)
        close = float(b.close.iloc[-1])
        ema20 = float(b.ema20.iloc[-1])
        ema50 = float(b.ema50.iloc[-1])
        ema200 = float(b.ema200.iloc[-1])
        adx = float(b.adx.iloc[-1])

        ema_aligned = ema20 > ema50 > ema200 or ema20 < ema50 < ema200
        price_vs_ema = ""
        if close > ema20 > ema50:
            price_vs_ema = "ABOVE_ALL"
        elif close > ema20 > ema50 > ema200:
            price_vs_ema = "STRONG_BULLISH"
        elif close < ema20 < ema50:
            price_vs_ema = "BELOW_ALL"
        elif close < ema20 < ema50 < ema200:
            price_vs_ema = "STRONG_BEARISH"
        else:
            price_vs_ema = "MIXED"

        if ema50 > ema200 and close > ema50:
            direction = Direction.BUY
        elif ema50 < ema200 and close < ema50:
            direction = Direction.SELL
        else:
            direction = Direction.NEUTRAL

        trend_strength = 0.0
        if adx >= 25:
            trend_strength += 40
        elif adx >= 20:
            trend_strength += 25
        elif adx >= 15:
            trend_strength += 10

        if ema_aligned:
            trend_strength += 30

        if "STRONG" in price_vs_ema:
            trend_strength += 30
        elif price_vs_ema in ("ABOVE_ALL", "BELOW_ALL"):
            trend_strength += 15

        trend_strength = min(100.0, trend_strength)

        base_weight = HTF_WEIGHTS.get(timeframe, 1.0)
        min_adx = HTF_MIN_ADX.get(timeframe, 15)

        if adx < min_adx:
            base_weight *= 0.5

        now = datetime.now(timezone.utc)
        session_mult = _session_factor(timeframe, now.hour)
        weight = base_weight * session_mult

        confidence = min(100.0, trend_strength * weight / 5)

        return HTFVote(
            timeframe=timeframe,
            direction=direction,
            weight=round(weight, 2),
            trend_strength=round(trend_strength, 1),
            adx=round(adx, 1),
            ema_alignment=ema_aligned,
            price_vs_ema=price_vs_ema,
            confidence=round(confidence, 1),
        )

    except Exception:
        return None


def collect_advanced_mtf_votes(
    symbol: str,
    timeframe: str,
    get_df,
    settings: Settings,
) -> list[HTFVote]:
    """Collect weighted HTF votes with trend strength analysis."""
    votes = []
    for htf in HIGHER_TIMEFRAMES.get(timeframe, []):
        df = get_df(symbol, htf)
        if df is None or len(df) < settings.min_candles:
            continue
        vote = analyze_htf_trend(df, htf, settings)
        if vote:
            votes.append(vote)
    return votes


def compute_mtf_consensus(votes: list[HTFVote], signal_direction: Direction) -> MTFAnalysisResult:
    """Compute weighted MTF consensus with detailed analysis."""
    if not votes:
        return MTFAnalysisResult(
            votes=[],
            weighted_direction=Direction.NEUTRAL,
            alignment=MTFAlignment.NONE,
            total_weight=0.0,
            agree_weight=0.0,
            oppose_weight=0.0,
            neutral_weight=0.0,
            consensus_score=0.0,
            trend_quality="NO_DATA",
            session_factor=1.0,
            details=["No HTF data available"],
        )

    agree_weight = 0.0
    oppose_weight = 0.0
    neutral_weight = 0.0

    for v in votes:
        if v.direction == signal_direction:
            agree_weight += v.weight
        elif v.direction == Direction.NEUTRAL:
            neutral_weight += v.weight
        else:
            oppose_weight += v.weight

    total_weight = agree_weight + oppose_weight + neutral_weight

    if total_weight == 0:
        alignment = MTFAlignment.NONE
        weighted_direction = Direction.NEUTRAL
        consensus_score = 0.0
    elif agree_weight >= oppose_weight + neutral_weight:
        alignment = MTFAlignment.ALIGNED
        weighted_direction = signal_direction
        consensus_score = agree_weight / total_weight * 100
    elif oppose_weight > agree_weight:
        alignment = MTFAlignment.AGAINST
        weighted_direction = Direction.SELL if signal_direction == Direction.BUY else Direction.BUY
        consensus_score = -oppose_weight / total_weight * 100
    else:
        alignment = MTFAlignment.MIXED
        weighted_direction = signal_direction
        consensus_score = (agree_weight - oppose_weight) / total_weight * 100

    strong_votes = [v for v in votes if v.trend_strength >= 70 and v.adx >= 25]
    if len(strong_votes) >= 2 and all(v.direction == signal_direction for v in strong_votes):
        trend_quality = "STRONG_TREND"
    elif any(v.trend_strength >= 70 for v in votes):
        trend_quality = "MODERATE_TREND"
    else:
        trend_quality = "WEAK_TREND"

    details = []
    for v in votes:
        details.append(
            f"{v.timeframe}: {v.direction.value} | "
            f"W={v.weight} | ADX={v.adx} | "
            f"Trend={v.trend_strength:.0f}% | "
            f"EMA={'✅' if v.ema_alignment else '❌'} | "
            f"Price={v.price_vs_ema}"
        )

    session_factors = [_session_factor(v.timeframe, datetime.now(timezone.utc).hour) for v in votes]
    avg_session_factor = sum(session_factors) / len(session_factors) if session_factors else 1.0

    return MTFAnalysisResult(
        votes=votes,
        weighted_direction=weighted_direction,
        alignment=alignment,
        total_weight=round(total_weight, 2),
        agree_weight=round(agree_weight, 2),
        oppose_weight=round(oppose_weight, 2),
        neutral_weight=round(neutral_weight, 2),
        consensus_score=round(consensus_score, 1),
        trend_quality=trend_quality,
        session_factor=round(avg_session_factor, 2),
        details=details,
    )


def should_require_mtf_alignment(
    timeframe: str,
    mtf_result: MTFAnalysisResult,
    signal_quality_score: float,
    signal_voters: int,
) -> tuple[bool, str]:
    """
    Determine if MTF alignment should be REQUIRED for this signal.
    Strict mode for lower timeframes, weak setups, or counter-trend.
    """
    if timeframe in ("5m", "15m"):
        if signal_quality_score < 75 or signal_voters < 4:
            if mtf_result.alignment != MTFAlignment.ALIGNED:
                return True, f"{timeframe} requires MTF ALIGNED for weak setups (quality={signal_quality_score}, voters={signal_voters})"

    if timeframe in ("30m", "1h"):
        if signal_quality_score < 70 and mtf_result.alignment == MTFAlignment.AGAINST:
            return True, f"{timeframe} weak signal blocked by MTF AGAINST"

    if mtf_result.trend_quality == "STRONG_TREND" and mtf_result.alignment == MTFAlignment.AGAINST:
        return True, "Strong HTF trend opposes signal — blocked"

    return False, "OK"