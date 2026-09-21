"""Portfolio Risk Manager — Correlation limits, sector exposure, position sizing."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from app.core.config import Settings
from app.core.enums import Direction
from app.core.logging import get_logger
from app.database import crud
from app.database.session import async_session_factory

if TYPE_CHECKING:
    from app.indicators.bundle import IndicatorBundle
    from app.engine.signal_quality import SignalQualityResult

logger = get_logger(__name__)

SECTOR_MAP = {
    "BTCUSDT": "L1", "ETHUSDT": "L1", "BNBUSDT": "L1", "SOLUSDT": "L1",
    "ADAUSDT": "L1", "AVAXUSDT": "L1", "DOTUSDT": "L1", "NEARUSDT": "L1",
    "LINKUSDT": "ORACLE", "XRPUSDT": "PAYMENTS", "DOGEUSDT": "MEME",
    "SHIBUSDT": "MEME", "PEPEUSDT": "MEME", "FLOKIUSDT": "MEME",
    "UNIUSDT": "DEFI", "AAVEUSDT": "DEFI", "COMPUSDT": "DEFI", "MKRUSDT": "DEFI",
    "XAUUSDT": "COMMODITY", "SILVERUSDT": "COMMODITY",
    "USOILUSDT": "ENERGY", "UKOILUSDT": "ENERGY",
    "EURUSDT": "FOREX", "GBPUSDT": "FOREX", "JPYUSDT": "FOREX", "AUDUSDT": "FOREX",
}

DEFAULT_SECTOR_LIMITS = {
    "L1": 3,
    "DEFI": 2,
    "ORACLE": 1,
    "PAYMENTS": 1,
    "MEME": 1,
    "COMMODITY": 2,
    "ENERGY": 1,
    "FOREX": 3,
}

CORRELATION_LOOKBACK_DAYS = 30
CORRELATION_THRESHOLD = 0.7
MAX_CORRELATED_POSITIONS = 2


@dataclass
class PositionRisk:
    symbol: str
    direction: Direction
    size_pct: float
    entry_price: float
    current_price: float
    unrealized_pnl_pct: float
    risk_pct: float
    sector: str
    correlation_risk: float = 0.0


@dataclass
class PortfolioRiskResult:
    allowed: bool
    reason: str
    position_size_pct: float
    max_position_size_pct: float
    current_exposure_pct: float
    sector_exposure: dict[str, float]
    correlated_positions: list[str]
    risk_score: float
    details: list[str]


async def get_open_positions(session, user_id: int | None = None) -> list[dict]:
    """Get all open positions from paper trading or live."""
    try:
        from app.paper_trading.engine import PaperEngine
        from app.database import crud as db_crud

        if user_id:
            positions = await db_crud.get_user_open_positions(session, user_id)
        else:
            positions = await db_crud.get_all_open_positions(session)
        return positions
    except Exception:
        return []


async def calculate_correlation_matrix(
    symbols: list[str],
    lookback_days: int = CORRELATION_LOOKBACK_DAYS,
) -> pd.DataFrame:
    """Calculate correlation matrix for given symbols."""
    try:
        from app.market.candle_manager import CandleManager
        from app.core.config import Settings

        settings = Settings()
        cm = CandleManager(settings)
        await cm.start()

        returns_data = {}
        for symbol in symbols:
            df = await cm.get_candles(symbol, "1h", limit=lookback_days * 24)
            if df is not None and len(df) > 50:
                returns = df["close"].pct_change().dropna()
                returns_data[symbol] = returns

        if len(returns_data) < 2:
            return pd.DataFrame()

        returns_df = pd.DataFrame(returns_data).dropna()
        if len(returns_df) < 30:
            return pd.DataFrame()

        corr_matrix = returns_df.corr()
        await cm.stop()
        return corr_matrix

    except Exception as exc:
        logger.warning(f"Correlation calculation failed: {exc}")
        return pd.DataFrame()


def get_sector(symbol: str) -> str:
    """Get sector for symbol."""
    return SECTOR_MAP.get(symbol, "OTHER")


def check_sector_limits(
    open_positions: list[PositionRisk],
    new_symbol: str,
    new_direction: Direction,
    sector_limits: dict[str, int] | None = None,
) -> tuple[bool, str, dict[str, int]]:
    """Check if adding position would exceed sector limits."""
    limits = sector_limits or DEFAULT_SECTOR_LIMITS
    sector = get_sector(new_symbol)

    sector_counts = {}
    for pos in open_positions:
        sector_counts[pos.sector] = sector_counts.get(pos.sector, 0) + 1

    current = sector_counts.get(sector, 0)
    limit = limits.get(sector, 2)

    if current >= limit:
        return False, f"Sector limit reached: {sector} ({current}/{limit})", sector_counts

    return True, "OK", sector_counts


def find_correlated_positions(
    open_positions: list[PositionRisk],
    new_symbol: str,
    correlation_matrix: pd.DataFrame,
    threshold: float = CORRELATION_THRESHOLD,
) -> list[str]:
    """Find existing positions highly correlated with new symbol."""
    if correlation_matrix.empty or new_symbol not in correlation_matrix.columns:
        return []

    correlated = []
    for pos in open_positions:
        if pos.symbol in correlation_matrix.columns:
            corr = abs(correlation_matrix.loc[new_symbol, pos.symbol])
            if corr >= threshold:
                correlated.append(pos.symbol)

    return correlated


def calculate_position_size(
    signal_quality: "SignalQualityResult",
    account_balance: float,
    max_risk_pct: float = 2.0,
    base_risk_pct: float = 1.0,
    quality_multiplier: float = 1.5,
) -> tuple[float, float]:
    """
    Calculate position size based on signal quality.
    Returns: (position_size_pct, risk_amount)
    """
    quality_score = signal_quality.score
    stars = signal_quality.stars

    if stars >= 3:
        risk_mult = quality_multiplier
    elif stars >= 2:
        risk_mult = 1.0
    elif stars >= 1:
        risk_mult = 0.7
    else:
        risk_mult = 0.5

    risk_pct = min(max_risk_pct, base_risk_pct * risk_mult * (quality_score / 100))
    position_size_pct = risk_pct

    return round(position_size_pct, 2), round(account_balance * risk_pct / 100, 2)


def calculate_portfolio_heat(
    open_positions: list[PositionRisk],
    account_balance: float,
) -> tuple[float, float, float]:
    """Calculate portfolio heat metrics."""
    if not open_positions:
        return 0.0, 0.0, 0.0

    total_exposure = sum(p.size_pct for p in open_positions)
    total_risk = sum(p.risk_pct for p in open_positions)
    max_single = max(p.size_pct for p in open_positions)

    return total_exposure, total_risk, max_single


async def assess_portfolio_risk(
    symbol: str,
    direction: Direction,
    signal_quality: "SignalQualityResult",
    settings: Settings,
    account_balance: float = 10000.0,
    user_id: int | None = None,
    sector_limits: dict[str, int] | None = None,
) -> PortfolioRiskResult:
    """
    Main entry point: assess if new position is allowed and calculate size.
    """
    details = []

    async with async_session_factory() as session:
        open_pos_data = await get_open_positions(session, user_id)

    open_positions = []
    for pos in open_pos_data:
        try:
            open_positions.append(PositionRisk(
                symbol=pos.get("symbol", ""),
                direction=Direction(pos.get("direction", "BUY")),
                size_pct=pos.get("size_pct", 0),
                entry_price=pos.get("entry_price", 0),
                current_price=pos.get("current_price", 0),
                unrealized_pnl_pct=pos.get("unrealized_pnl_pct", 0),
                risk_pct=pos.get("risk_pct", 0),
                sector=get_sector(pos.get("symbol", "")),
            ))
        except Exception:
            continue

    total_exposure, total_risk, max_single = calculate_portfolio_heat(open_positions, account_balance)
    details.append(f"Portfolio exposure: {total_exposure:.1f}%, risk: {total_risk:.1f}%")

    max_portfolio_risk = getattr(settings, "max_portfolio_risk_pct", 10.0)
    if total_risk >= max_portfolio_risk:
        return PortfolioRiskResult(
            allowed=False,
            reason=f"Max portfolio risk reached ({total_risk:.1f}% >= {max_portfolio_risk}%)",
            position_size_pct=0,
            max_position_size_pct=0,
            current_exposure_pct=total_exposure,
            sector_exposure={},
            correlated_positions=[],
            risk_score=100,
            details=details,
        )

    max_single_position = getattr(settings, "max_single_position_pct", 5.0)
    if max_single >= max_single_position:
        return PortfolioRiskResult(
            allowed=False,
            reason=f"Max single position limit ({max_single:.1f}% >= {max_single_position}%)",
            position_size_pct=0,
            max_position_size_pct=0,
            current_exposure_pct=total_exposure,
            sector_exposure={},
            correlated_positions=[],
            risk_score=90,
            details=details,
        )

    sector_ok, sector_reason, sector_counts = check_sector_limits(
        open_positions, symbol, direction, sector_limits
    )
    if not sector_ok:
        return PortfolioRiskResult(
            allowed=False,
            reason=sector_reason,
            position_size_pct=0,
            max_position_size_pct=0,
            current_exposure_pct=total_exposure,
            sector_exposure={k: v * 100 for k, v in sector_counts.items()},
            correlated_positions=[],
            risk_score=80,
            details=details + [sector_reason],
        )

    all_symbols = [p.symbol for p in open_positions] + [symbol]
    corr_matrix = await calculate_correlation_matrix(all_symbols)

    correlated = find_correlated_positions(open_positions, symbol, corr_matrix)
    if len(correlated) >= MAX_CORRELATED_POSITIONS:
        return PortfolioRiskResult(
            allowed=False,
            reason=f"Too many correlated positions: {', '.join(correlated)}",
            position_size_pct=0,
            max_position_size_pct=0,
            current_exposure_pct=total_exposure,
            sector_exposure={k: v * 100 for k, v in sector_counts.items()},
            correlated_positions=correlated,
            risk_score=70,
            details=details + [f"Correlated: {correlated}"],
        )

    pos_size_pct, risk_amount = calculate_position_size(
        signal_quality, account_balance,
        max_risk_pct=getattr(settings, "max_position_risk_pct", 2.0),
    )

    if correlated:
        pos_size_pct *= 0.5
        details.append(f"Reduced size 50% due to correlation with: {correlated}")

    max_allowed = max_single_position - max_single
    if pos_size_pct > max_allowed:
        pos_size_pct = max(0, max_allowed)
        details.append(f"Capped at max single position limit")

    sector_exposure_pct = {k: v * 100 for k, v in sector_counts.items()}
    sector_exposure_pct[get_sector(symbol)] = sector_exposure_pct.get(get_sector(symbol), 0) + pos_size_pct

    risk_score = min(100, total_risk * 10 + len(correlated) * 10)

    return PortfolioRiskResult(
        allowed=True,
        reason="OK",
        position_size_pct=round(pos_size_pct, 2),
        max_position_size_pct=round(max_single_position, 2),
        current_exposure_pct=round(total_exposure, 2),
        sector_exposure=sector_exposure_pct,
        correlated_positions=correlated,
        risk_score=round(risk_score, 1),
        details=details,
    )


def get_risk_summary(portfolio_result: PortfolioRiskResult) -> list[str]:
    """Get human-readable risk summary."""
    lines = [
        f"📊 Portfolio Risk: {portfolio_result.risk_score:.0f}/100",
        f"💰 Exposure: {portfolio_result.current_exposure_pct:.1f}%",
        f"📏 Position Size: {portfolio_result.position_size_pct:.2f}%",
    ]
    if portfolio_result.sector_exposure:
        lines.append("🏭 Sectors: " + ", ".join(f"{k}={v:.1f}%" for k, v in portfolio_result.sector_exposure.items()))
    if portfolio_result.correlated_positions:
        lines.append(f"🔗 Correlated: {', '.join(portfolio_result.correlated_positions)}")
    return lines