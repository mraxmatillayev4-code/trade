"""Signal Quality Scoring (0-100) — Professional grade signal assessment with star ratings."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

import pandas as pd

from app.core.config import Settings
from app.core.enums import Direction, MarketRegime, MTFAlignment
from app.core.logging import get_logger
from app.database import crud
from app.database.session import async_session_factory
from app.engine.adaptive_weights import get_current_regime_weights
from app.indicators.bundle import IndicatorBundle

if TYPE_CHECKING:
    from app.engine.scoring import EngineDecision

logger = get_logger(__name__)

SIGNAL_HISTORY_CACHE: dict[str, list[dict]] = {}
SIGNAL_HISTORY_MAX_AGE_MINUTES = 60
SIGNAL_DENSITY_WINDOW_MINUTES = 15
SIGNAL_DENSITY_MAX_SIGNALS = 3


@dataclass
class QualityComponents:
    volume_spike_strength: float = 0.0
    flow_conviction: float = 0.0
    trend_alignment: float = 0.0
    regime_strength: float = 0.0
    regime_freshness: float = 0.0
    squeeze_proximity: float = 0.0
    htf_alignment: float = 0.0
    smc_confluence: float = 0.0
    smc_structure: float = 0.0
    density_penalty: float = 0.0


@dataclass
class SignalQualityResult:
    score: float
    stars: int
    components: QualityComponents
    grade: str
    details: list[str]


def _star_rating(score: float) -> tuple[int, str]:
    if score >= 85:
        return 3, "⭐⭐⭐"
    if score >= 75:
        return 2, "⭐⭐"
    if score >= 65:
        return 1, "⭐"
    return 0, ""


def _grade(score: float) -> str:
    if score >= 90:
        return "A+"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B+"
    if score >= 60:
        return "B"
    if score >= 50:
        return "C"
    return "D"


async def _get_recent_signal_count(symbol: str, timeframe: str, minutes: int = 15) -> int:
    """Get count of recent signals for density penalty."""
    try:
        async with async_session_factory() as session:
            since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
            stmt = (
                f"SELECT COUNT(*) FROM signals "
                f"WHERE symbol = '{symbol}' AND timeframe = '{timeframe}' "
                f"AND created_at >= '{since.isoformat()}'"
            )
            result = await session.execute(stmt)
            return result.scalar() or 0
    except Exception:
        return 0


def _calc_volume_spike_strength(bundle: IndicatorBundle, settings: Settings) -> float:
    """Volume spike strength: 0-20 points."""
    try:
        vol = float(bundle.volume.iloc[-1])
        vol_ma = float(bundle.vol_ma.iloc[-1]) or 1.0
        ratio = vol / vol_ma if vol_ma > 0 else 1.0

        if ratio >= 3.0:
            return 20.0
        elif ratio >= 2.0:
            return 15.0
        elif ratio >= 1.5:
            return 10.0
        elif ratio >= 1.2:
            return 5.0
        return 0.0
    except Exception:
        return 0.0


def _calc_flow_conviction(bundle: IndicatorBundle, direction: Direction) -> float:
    """Flow direction conviction using CVD/OBV: 0-15 points."""
    try:
        cvd = bundle.cvd.iloc[-1] if hasattr(bundle, 'cvd') and len(bundle.cvd) > 0 else 0
        cvd_prev = bundle.cvd.iloc[-5] if hasattr(bundle, 'cvd') and len(bundle.cvd) > 5 else 0
        cvd_change = cvd - cvd_prev

        obv = bundle.obv.iloc[-1] if hasattr(bundle, 'obv') and len(bundle.obv) > 0 else 0
        obv_prev = bundle.obv.iloc[-5] if hasattr(bundle, 'obv') and len(bundle.obv) > 5 else 0
        obv_change = obv - obv_prev

        if direction == Direction.BUY:
            aligned = (cvd_change > 0) + (obv_change > 0)
        else:
            aligned = (cvd_change < 0) + (obv_change < 0)

        return min(15.0, aligned * 7.5)
    except Exception:
        return 7.5


def _calc_trend_alignment(bundle: IndicatorBundle, direction: Direction, regime: MarketRegime) -> float:
    """Trend alignment across EMAs, ADX, price position: 0-15 points."""
    try:
        score = 0.0
        close = float(bundle.close.iloc[-1])
        ema20 = float(bundle.ema20.iloc[-1])
        ema50 = float(bundle.ema50.iloc[-1])
        ema200 = float(bundle.ema200.iloc[-1])
        adx = float(bundle.adx.iloc[-1])

        if direction == Direction.BUY:
            if close > ema20 > ema50 > ema200:
                score += 6
            elif close > ema20 > ema50:
                score += 4
            elif close > ema20:
                score += 2
        else:
            if close < ema20 < ema50 < ema200:
                score += 6
            elif close < ema20 < ema50:
                score += 4
            elif close < ema20:
                score += 2

        if adx >= 25:
            score += 5
        elif adx >= 20:
            score += 3
        elif adx >= 15:
            score += 1

        if regime == MarketRegime.TRENDING:
            score += 4

        return min(15.0, score)
    except Exception:
        return 7.5


def _calc_regime_strength(bundle: IndicatorBundle, regime: MarketRegime) -> float:
    """Regime strength and conviction: 0-15 points."""
    try:
        score = 0.0
        atr_pct = (bundle.last_atr / bundle.last_close * 100) if bundle.last_close else 0
        adx = float(bundle.adx.iloc[-1])

        if regime == MarketRegime.TRENDING:
            score = 10.0 + min(5.0, adx / 5)
        elif regime == MarketRegime.HIGH_VOLATILITY:
            score = 8.0 + min(5.0, atr_pct)
        elif regime == MarketRegime.RANGING:
            score = 5.0 + min(5.0, 25 - adx)
        else:
            score = 3.0

        return min(15.0, score)
    except Exception:
        return 7.5


def _calc_regime_freshness(regime: MarketRegime, bundle: IndicatorBundle) -> float:
    """How fresh is the regime (recent transition = stronger signal): 0-10 points."""
    try:
        adx = float(bundle.adx.iloc[-1])
        adx_5_ago = float(bundle.adx.iloc[-6]) if len(bundle.adx) > 5 else adx
        adx_change = adx - adx_5_ago

        if regime == MarketRegime.TRENDING and adx_change > 2:
            return 10.0
        elif regime == MarketRegime.RANGING and abs(adx_change) < 1:
            return 8.0
        elif regime == MarketRegime.HIGH_VOLATILITY and adx_change > 3:
            return 10.0
        return 5.0
    except Exception:
        return 5.0


def _calc_squeeze_proximity(bundle: IndicatorBundle) -> float:
    """Distance to squeeze/breakout: 0-10 points."""
    try:
        if hasattr(bundle, 'squeeze_on') and bundle.squeeze_on is not None:
            squeeze_on = bundle.squeeze_on.iloc[-1] if len(bundle.squeeze_on) > 0 else False
            if squeeze_on:
                return 10.0

        bb_width = None
        if hasattr(bundle, 'bb_upper') and hasattr(bundle, 'bb_lower'):
            upper = bundle.bb_upper.iloc[-1]
            lower = bundle.bb_lower.iloc[-1]
            mid = bundle.bb_mid.iloc[-1] if hasattr(bundle, 'bb_mid') else (upper + lower) / 2
            bb_width = (upper - lower) / mid * 100

        if bb_width is not None:
            if bb_width < 5:
                return 10.0
            elif bb_width < 10:
                return 7.0
            elif bb_width < 15:
                return 4.0

        return 0.0
    except Exception:
        return 0.0


def _calc_htf_alignment(mtf_votes: list[tuple[str, Direction]], direction: Direction) -> float:
    """HTF alignment strength: 0-15 points."""
    if not mtf_votes:
        return 7.5

    real_votes = [v for _, v in mtf_votes if v != Direction.NEUTRAL]
    if not real_votes:
        return 7.5

    agree = sum(1 for v in real_votes if v == direction)
    total = len(real_votes)
    ratio = agree / total

    if ratio >= 0.75:
        return 15.0
    elif ratio >= 0.5:
        return 10.0
    elif ratio >= 0.33:
        return 5.0
    return 0.0


def _calc_density_penalty(symbol: str, timeframe: str) -> float:
    """Penalty for too many signals in short time: 0 to -20 points."""
    try:
        count = len(SIGNAL_HISTORY_CACHE.get(f"{symbol}:{timeframe}", []))
        if count >= SIGNAL_DENSITY_MAX_SIGNALS:
            return -20.0
        elif count >= 2:
            return -10.0
        elif count >= 1:
            return -5.0
        return 0.0
    except Exception:
        return 0.0


def _record_signal_emit(symbol: str, timeframe: str) -> None:
    """Record signal emission for density tracking."""
    key = f"{symbol}:{timeframe}"
    now = datetime.now(timezone.utc)
    if key not in SIGNAL_HISTORY_CACHE:
        SIGNAL_HISTORY_CACHE[key] = []
    SIGNAL_HISTORY_CACHE[key].append({"time": now})
    cutoff = now - timedelta(minutes=SIGNAL_HISTORY_MAX_AGE_MINUTES)
    SIGNAL_HISTORY_CACHE[key] = [s for s in SIGNAL_HISTORY_CACHE[key] if s["time"] > cutoff]


async def compute_signal_quality(
    bundle: IndicatorBundle,
    decision: "EngineDecision",
    settings: Settings,
    mtf_votes: list[tuple[str, Direction]] | None = None,
    smc_data: dict | None = None,
) -> SignalQualityResult:
    """
    Compute comprehensive signal quality score (0-100) with star rating.
    This is the main entry point for signal quality assessment.
    """
    mtf_votes = mtf_votes or []
    smc_data = smc_data or {}

    comp = QualityComponents()

    comp.volume_spike_strength = _calc_volume_spike_strength(bundle, settings)
    comp.flow_conviction = _calc_flow_conviction(bundle, decision.direction)
    comp.trend_alignment = _calc_trend_alignment(bundle, decision.direction, decision.regime)
    comp.regime_strength = _calc_regime_strength(bundle, decision.regime)
    comp.regime_freshness = _calc_regime_freshness(decision.regime, bundle)
    comp.squeeze_proximity = _calc_squeeze_proximity(bundle)
    comp.htf_alignment = _calc_htf_alignment(mtf_votes, decision.direction)
    comp.density_penalty = _calc_density_penalty(decision.symbol, decision.timeframe)

    comp.smc_confluence = smc_data.get("confluence_score", 0.0)
    comp.smc_structure = smc_data.get("structure_score", 0.0)

    raw_score = (
        comp.volume_spike_strength +
        comp.flow_conviction +
        comp.trend_alignment +
        comp.regime_strength +
        comp.regime_freshness +
        comp.squeeze_proximity +
        comp.htf_alignment +
        comp.smc_confluence +
        comp.smc_structure +
        comp.density_penalty
    )

    score = max(0.0, min(100.0, raw_score))
    stars, star_str = _star_rating(score)
    grade = _grade(score)

    details = [
        f"Volume Spike: {comp.volume_spike_strength:.0f}/20",
        f"Flow Conviction: {comp.flow_conviction:.0f}/15",
        f"Trend Align: {comp.trend_alignment:.0f}/15",
        f"Regime Strength: {comp.regime_strength:.0f}/15",
        f"Regime Freshness: {comp.regime_freshness:.0f}/10",
        f"Squeeze Proximity: {comp.squeeze_proximity:.0f}/10",
        f"HTF Align: {comp.htf_alignment:.0f}/15",
        f"SMC Confluence: {comp.smc_confluence:.0f}/15",
        f"SMC Structure: {comp.smc_structure:.0f}/15",
        f"Density Penalty: {comp.density_penalty:.0f}",
    ]

    _record_signal_emit(decision.symbol, decision.timeframe)

    return SignalQualityResult(
        score=round(score, 1),
        stars=stars,
        components=comp,
        grade=grade,
        details=details,
    )


def should_emit_signal(
    quality: SignalQualityResult,
    min_score: float = 65.0,
    min_stars: int = 1,
) -> tuple[bool, str]:
    """Decision function: should we emit this signal?"""
    if quality.score < min_score:
        return False, f"Quality score {quality.score:.1f} < {min_score}"
    if quality.stars < min_stars:
        return False, f"Stars {quality.stars} < {min_stars}"
    return True, "OK"


async def get_quality_thresholds_for_regime(
    regime: MarketRegime,
    settings: Settings,
) -> dict[str, float]:
    """Get adaptive quality thresholds per regime."""
    base_min_score = 55.0
    base_min_stars = 1

    if regime == MarketRegime.TRENDING:
        return {"min_score": base_min_score - 5, "min_stars": base_min_stars}
    elif regime == MarketRegime.HIGH_VOLATILITY:
        return {"min_score": base_min_score + 5, "min_stars": base_min_stars}
    elif regime == MarketRegime.RANGING:
        return {"min_score": base_min_score, "min_stars": base_min_stars}
    else:
        return {"min_score": base_min_score, "min_stars": base_min_stars}