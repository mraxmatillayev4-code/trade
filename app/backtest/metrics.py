"""Backtest metrikalari — win rate, profit factor, drawdown, expectancy."""
from __future__ import annotations


def max_drawdown_r(rs: list[float]) -> float:
    cum = peak = max_dd = 0.0
    for r in rs:
        cum += r
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    return round(max_dd, 2)


def compute_metrics(trades: list[dict]) -> dict:
    """
    trades: [{"r": float, "pnl_pct": float, "direction": str, "strategies": [...]}]
    """
    total = len(trades)
    if total == 0:
        return {
            "total_trades": 0, "wins": 0, "losses": 0, "breakeven": 0,
            "win_rate": 0.0, "profit_factor": 0.0, "avg_r": 0.0,
            "expectancy_r": 0.0, "max_drawdown_r": 0.0, "avg_return_pct": 0.0,
            "total_r": 0.0,
        }

    rs = [t["r"] for t in trades]
    wins = [r for r in rs if r > 0.05]
    losses = [r for r in rs if r < -0.05]
    be = total - len(wins) - len(losses)

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    total_r = sum(rs)
    pnls = [t.get("pnl_pct", 0.0) for t in trades]

    return {
        "total_trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": be,
        "win_rate": round(len(wins) / total * 100, 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0.0,
        "avg_r": round(total_r / total, 3),
        "expectancy_r": round(total_r / total, 3),
        "max_drawdown_r": max_drawdown_r(rs),
        "avg_return_pct": round(sum(pnls) / total, 3),
        "total_r": round(total_r, 2),
        "avg_win_r": round(sum(wins) / len(wins), 3) if wins else 0.0,
        "avg_loss_r": round(sum(losses) / len(losses), 3) if losses else 0.0,
    }


def per_strategy_metrics(trades: list[dict]) -> dict[str, dict]:
    by_strat: dict[str, list[float]] = {}
    for t in trades:
        for name in t.get("strategies", []):
            by_strat.setdefault(name, []).append(t["r"])
    out = {}
    for name, rs in by_strat.items():
        wins = [r for r in rs if r > 0.05]
        losses = [r for r in rs if r < -0.05]
        gp = sum(wins)
        gl = abs(sum(losses))
        out[name] = {
            "trades": len(rs),
            "win_rate": round(len(wins) / len(rs) * 100, 2) if rs else 0.0,
            "avg_r": round(sum(rs) / len(rs), 3) if rs else 0.0,
            "profit_factor": round(gp / gl, 2) if gl > 0 else 0.0,
        }
    return out
