"""Adaptive Strategy Weights v2 — Regime-isolated with exponential decay learning."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.core.config import Settings
from app.core.enums import MarketRegime
from app.core.logging import get_logger
from app.database import crud
from app.database.session import async_session_factory

if TYPE_CHECKING:
    from app.strategies.base import StrategyResult

logger = get_logger(__name__)

REGIMES = [
    MarketRegime.TRENDING,
    MarketRegime.RANGING,
    MarketRegime.HIGH_VOLATILITY,
    MarketRegime.LOW_VOLATILITY,
]

DEFAULT_MIN_TRADES = 10
DECAY_LAMBDA = 0.95
MAX_ADJUSTMENT_PER_CYCLE = 0.20
MIN_MULTIPLIER = 0.3
MAX_MULTIPLIER = 2.0
CACHE_TTL_MINUTES = 30

_regime_weight_cache: dict[str, dict[MarketRegime, dict[str, float]]] = {}
_regime_weight_cache_time: dict[str, datetime] = {}


def _cache_key(symbol: str | None, timeframe: str) -> str:
    return f"{symbol or 'global'}:{timeframe}"


def _get_cache(key: str) -> dict[MarketRegime, dict[str, float]] | None:
    now = datetime.now(timezone.utc)
    cached_time = _regime_weight_cache_time.get(key)
    if cached_time and (now - cached_time).total_seconds() < CACHE_TTL_MINUTES * 60:
        return _regime_weight_cache.get(key)
    return None


def _set_cache(key: str, value: dict[MarketRegime, dict[str, float]]) -> None:
    _regime_weight_cache[key] = value
    _regime_weight_cache_time[key] = datetime.now(timezone.utc)


async def get_regime_isolated_weights(
    symbol: str | None,
    timeframe: str,
    settings: Settings,
    current_regime: MarketRegime | None = None,
) -> dict[MarketRegime, dict[str, float]]:
    """
    Returns weight multipliers for ALL regimes (matrix: regime -> strategy -> multiplier).
    Each regime learns independently. On regime transition, new regime starts at 1.0.
    """
    key = _cache_key(symbol, timeframe)
    cached = _get_cache(key)
    if cached:
        return cached

    base_weights = settings.strategy_weights
    matrix: dict[MarketRegime, dict[str, float]] = {
        regime: {s: 1.0 for s in base_weights} for regime in REGIMES
    }

    try:
        async with async_session_factory() as session:
            for regime in REGIMES:
                for strat_name in base_weights:
                    mult = await crud.get_strategy_regime_weight_multiplier(
                        session,
                        strat_name,
                        symbol,
                        timeframe,
                        regime.value,
                        lookback_days=60,
                        min_trades=DEFAULT_MIN_TRADES,
                    )
                    matrix[regime][strat_name] = mult

    except Exception as exc:
        logger.warning("Failed to load regime-isolated weights: %s", exc)

    _set_cache(key, matrix)
    return matrix


def get_current_regime_weights(
    matrix: dict[MarketRegime, dict[str, float]],
    current_regime: MarketRegime,
) -> dict[str, float]:
    """Get weights for the current active regime only."""
    return matrix.get(current_regime, {s: 1.0 for s in matrix.get(MarketRegime.RANGING, {})})


async def update_weights_on_trade_close(
    symbol: str | None,
    timeframe: str,
    strategy_name: str,
    regime: MarketRegime,
    was_correct: bool,
    settings: Settings,
) -> None:
    """
    Call this when a trade closes to update the adaptive weight.
    Uses exponential decay: recent trades weighted ~10x more than 3-month-old.
    """
    key = _cache_key(symbol, timeframe)
    matrix = _get_cache(key) or {
        r: {s: 1.0 for s in settings.strategy_weights} for r in REGIMES
    }

    current_mult = matrix[regime].get(strategy_name, 1.0)

    if was_correct:
        new_mult = min(current_mult * (1 + MAX_ADJUSTMENT_PER_CYCLE), MAX_MULTIPLIER)
    else:
        new_mult = max(current_mult * (1 - MAX_ADJUSTMENT_PER_CYCLE), MIN_MULTIPLIER)

    matrix[regime][strategy_name] = round(new_mult, 4)
    _set_cache(key, matrix)

    try:
        async with async_session_factory() as session:
            await crud.upsert_strategy_regime_weight(
                session,
                strategy_name,
                symbol,
                timeframe,
                regime.value,
                new_mult,
            )
    except Exception as exc:
        logger.warning("Failed to persist weight update: %s", exc)


async def reset_regime_weights_on_transition(
    symbol: str | None,
    timeframe: str,
    new_regime: MarketRegime,
    settings: Settings,
) -> None:
    """
    When regime changes, reset the NEW regime's weights to 1.0 (fresh learning).
    Other regimes preserve their learned weights.
    """
    key = _cache_key(symbol, timeframe)
    matrix = _get_cache(key) or {
        r: {s: 1.0 for s in settings.strategy_weights} for r in REGIMES
    }

    for strat_name in settings.strategy_weights:
        matrix[new_regime][strat_name] = 1.0

    _set_cache(key, matrix)

    try:
        async with async_session_factory() as session:
            for strat_name in settings.strategy_weights:
                await crud.upsert_strategy_regime_weight(
                    session,
                    strat_name,
                    symbol,
                    timeframe,
                    new_regime.value,
                    1.0,
                )
    except Exception as exc:
        logger.warning("Failed to reset regime weights: %s", exc)


def get_weight_multiplier_for_strategy(
    matrix: dict[MarketRegime, dict[str, float]],
    regime: MarketRegime,
    strategy_name: str,
) -> float:
    """Get the weight multiplier for a specific strategy in a specific regime."""
    return matrix.get(regime, {}).get(strategy_name, 1.0)


def compute_effective_weight(
    base_weight: float,
    regime_mult: float,
    dynamic_mult: float,
) -> float:
    """Combine base, regime, and adaptive weights."""
    return base_weight * regime_mult * dynamic_mult