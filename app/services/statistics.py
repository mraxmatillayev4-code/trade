"""Statistika hisob-kitoblari (signallar asosida)."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.signal import Signal, SignalConfirmation
from app.database.models.stats import StrategyStat


def _max_drawdown(rs: list[float]) -> float:
    """Cumulative R egri chizig'i bo'yicha maksimal drawdown (R birligida)."""
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in rs:
        cum += r
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    return round(max_dd, 2)


async def overall_statistics(session: AsyncSession) -> dict:
    stmt = select(Signal).where(Signal.is_active.is_(False))
    closed = list((await session.execute(stmt)).scalars().all())

    decided = [s for s in closed if s.r_multiple is not None]
    wins = [s for s in decided if (s.r_multiple or 0) > 0.05]
    losses = [s for s in decided if (s.r_multiple or 0) < -0.05]
    rs = [s.r_multiple or 0.0 for s in decided]
    pnls = [s.pnl_percent or 0.0 for s in decided]

    gross_profit = sum(r for r in rs if r > 0)
    gross_loss = abs(sum(r for r in rs if r < 0))
    total_signals = await session.scalar(select(func.count(Signal.id))) or 0

    # Eng yaxshi strategiya / timeframe / symbol
    best_strategy = await _best_group(session, SignalConfirmation.strategy_name)
    best_tf = await _best_signal_group(session, Signal.timeframe)
    best_symbol = await _best_signal_group(session, Signal.symbol)

    return {
        "total_signals": total_signals,
        "closed": len(decided),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(decided) - len(wins) - len(losses),
        "win_rate": round(len(wins) / len(decided) * 100, 2) if decided else 0.0,
        "avg_r": round(sum(rs) / len(rs), 3) if rs else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0.0,
        "max_drawdown_r": _max_drawdown(rs),
        "avg_return_pct": round(sum(pnls) / len(pnls), 3) if pnls else 0.0,
        "total_r": round(sum(rs), 2),
        "best_strategy": best_strategy,
        "best_timeframe": best_tf,
        "best_symbol": best_symbol,
    }


async def _best_group(session: AsyncSession, column) -> str:
    stmt = (
        select(column, func.avg(Signal.r_multiple), func.count(Signal.id))
        .join(Signal, SignalConfirmation.signal_id == Signal.id)
        .where(Signal.r_multiple.is_not(None))
        .group_by(column)
        .having(func.count(Signal.id) >= 3)
        .order_by(func.avg(Signal.r_multiple).desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    return row[0] if row else "—"


async def _best_signal_group(session: AsyncSession, column) -> str:
    stmt = (
        select(column, func.avg(Signal.r_multiple), func.count(Signal.id))
        .where(Signal.r_multiple.is_not(None))
        .group_by(column)
        .having(func.count(Signal.id) >= 3)
        .order_by(func.avg(Signal.r_multiple).desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    return row[0] if row else "—"


async def strategy_statistics(session: AsyncSession) -> list[dict]:
    stmt = select(StrategyStat).order_by(StrategyStat.strategy_name)
    stats = list((await session.execute(stmt)).scalars().all())
    return [
        {
            "name": s.strategy_name,
            "display_name": s.display_name,
            "is_active": s.is_active,
            "weight": s.weight,
            "total": s.total_signals,
            "wins": s.wins,
            "losses": s.losses,
            "breakeven": s.breakeven,
            "win_rate": round(s.win_rate, 2),
            "avg_r": round(s.avg_r, 3),
            "profit_factor": round(s.profit_factor, 2),
        }
        for s in stats
    ]
