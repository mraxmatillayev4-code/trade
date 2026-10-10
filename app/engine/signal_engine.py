"""Signal engine — FAQAT SINO AI qaror qiladi.

Strategiyalar kodi saqlanadi, lekin ovoz bermaydi / tahlilga qatnashmaydi.
Darvoza, min_voters, whitelist, killzone — YO'Q.
"""
from __future__ import annotations

import pandas as pd

from app.core.config import Settings
from app.core.enums import Direction, MTFAlignment
from app.core.logging import get_logger
from app.engine.market_regime import detect_regime
from app.engine.mtf import alignment
from app.engine.scoring import EngineDecision
from app.indicators.bundle import IndicatorBundle, compute_bundle
from app.strategies.base import StrategyResult

logger = get_logger(__name__)


def run_strategies(df: pd.DataFrame, bundle: IndicatorBundle,
                   settings: Settings, timeframe: str,
                   strategy_filter: str | None = None,
                   symbol: str | None = None) -> list[StrategyResult]:
    """Eski API saqlanadi, lekin JONLI signalda chaqirilMAYDI."""
    return []


def _symbol_placeholder(df: pd.DataFrame) -> str:
    return str(df.attrs.get("symbol", "?"))


def analyze(df: pd.DataFrame, timeframe: str, settings: Settings,
            mtf_votes: list[tuple[str, Direction]] | None = None,
            strategy_filter: str | None = None,
            symbol: str | None = None,
            ) -> tuple[EngineDecision, IndicatorBundle]:
    """Indikatorlar → rejim → SINO AI. Strategiya ovozi yo'q."""
    mtf_votes = mtf_votes or []
    sym = symbol or str(df.attrs.get("symbol", "")) or None
    bundle = compute_bundle(df, settings)
    regime = detect_regime(bundle)

    from app.engine.ai_trader import decide
    mtf = MTFAlignment.NONE
    decision = decide(df, bundle, timeframe, sym, regime, MTFAlignment.NONE)
    if decision.direction != Direction.NEUTRAL:
        mtf = alignment(mtf_votes, decision.direction)
        decision.mtf = mtf
        decision.mtf_votes = [(tf, d.value) for tf, d in mtf_votes]
        if mtf == MTFAlignment.ALIGNED:
            decision.score = round(min(9.8, decision.score + 0.3), 2)
            decision.checks.append(("Yuqori TF tasdiqlaydi", True))

    logger.info(
        "[%s %s] AI-ONLY rejim=%s mtf=%s → %s score=%.2f pass=%s",
        _symbol_placeholder(df), timeframe, regime.value, mtf.value,
        decision.direction.value, decision.score, decision.passes_threshold,
    )
    return decision, bundle
