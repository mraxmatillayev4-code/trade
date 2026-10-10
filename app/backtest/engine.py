"""
Backtest engine — tarixiy ma'lumotlarda strategiyalarni sinash.
ANTI LOOK-AHEAD: har bir shamda faqat o'sha paytgacha mavjud ma'lumot ishlatiladi.
Live mantiq bilan BIR XIL: signal_engine.analyze + lifecycle.evaluate.
"""
from __future__ import annotations

import pandas as pd

from app.backtest.metrics import compute_metrics, per_strategy_metrics
from app.core.config import Settings
from app.core.enums import Direction, SignalStatus
from app.core.logging import get_logger
from app.engine.lifecycle import CandleTick, evaluate, final_r_multiple
from app.engine.risk import calculate_levels
from app.engine import signal_engine

logger = get_logger(__name__)


def _mtf_votes_for_window(symbol: str, timeframe: str,
                          higher_dfs: dict[str, pd.DataFrame],
                          window: pd.DataFrame, settings: Settings):
    """Yuqori timeframe'larning faqat shu paytgacha YOPILGAN shamlaridan foydalanadi."""
    from app.engine.mtf import higher_timeframe_trend
    from app.core.enums import HIGHER_TIMEFRAMES

    votes = []
    boundary = window.iloc[-1]["close_time"]
    for htf in HIGHER_TIMEFRAMES.get(timeframe, []):
        hdf = higher_dfs.get(htf)
        if hdf is None:
            continue
        sliced = hdf[hdf["open_time"] <= boundary]
        if len(sliced) < settings.min_candles:
            continue
        votes.append((htf, higher_timeframe_trend(sliced, settings)))
    return votes


def run_backtest(df: pd.DataFrame, timeframe: str, settings: Settings,
                 higher_dfs: dict[str, pd.DataFrame] | None = None,
                 strategy_filter: str = "ALL",
                 symbol: str = "?") -> dict:
    higher_dfs = higher_dfs or {}
    df = df.reset_index(drop=True)
    n = len(df)
    trades: list[dict] = []
    open_pos: dict | None = None
    start = settings.min_candles + 5

    for i in range(start, n):
        candle = df.iloc[i]
        tick = CandleTick(
            high=float(candle["high"]),
            low=float(candle["low"]),
            close=float(candle["close"]),
        )

        # --- 1) Ochiq pozitsiyani boshqarish ---
        if open_pos is not None:
            event = evaluate(
                Direction(open_pos["direction"]), open_pos["stage"],
                open_pos["entry"], open_pos["sl"],
                open_pos["tp1"], open_pos["tp2"], open_pos["tp3"],
                tick, i - open_pos["start_i"], settings.signal_expiry_candles,
            )
            if event.event_type == "TP1":
                # 1R ga yetdi: pozitsiya OCHIQ qoladi, SL breakeven (entry) ga ko'chadi.
                open_pos["stage"] = event.new_stage
                if event.move_sl_to_be:
                    open_pos["sl"] = open_pos["entry"]
            elif event.event_type in ("TP2", "TP3", "SL", "EXPIRED"):
                # TP2/TP3 = +2R g'alaba (to'liq yopiladi); SL/EXPIRED = yopilish.
                _close_position(open_pos, event, candle, trades, settings)
                open_pos = None

        # --- 2) Yangi signal qidirish ---
        # Bozor yopiq (dam olish kuni) bo'lsa yangi signal ochilmaydi (live bilan bir xil).
        try:
            from datetime import timedelta as _td
            from app.core.enums import Timeframe as _Tf
            from app.engine.market_hours import is_market_open
            _ot = pd.Timestamp(candle["open_time"])
            _ct = (_ot + _td(minutes=_Tf(timeframe).minutes)).to_pydatetime()
            if _ct.tzinfo is None:
                from datetime import timezone as _tz
                _ct = _ct.replace(tzinfo=_tz.utc)
            if not is_market_open(symbol, _ct):
                continue
        except Exception:  # noqa: BLE001
            pass

        window = df.iloc[: i + 1].copy()
        window.attrs["symbol"] = symbol
        votes = _mtf_votes_for_window(symbol, timeframe, higher_dfs, window, settings)
        decision, bundle = signal_engine.analyze(
            window, timeframe, settings, votes,
            strategy_filter=None if strategy_filter == "ALL" else strategy_filter,
        )

        if not decision.passes_threshold or decision.direction == Direction.NEUTRAL:
            continue

        entry = float(candle["close"])
        # Shovqinli asbob/TF uchun kengroq ATR stop (live bilan bir xil)
        from app.strategies.registry import atr_sl_mult_for
        atr_mult = atr_sl_mult_for(symbol, timeframe, settings.atr_sl_multiplier)
        levels = calculate_levels(decision.direction, entry, bundle.last_atr, settings,
                                  atr_mult=atr_mult)
        voters = [r.name for r in decision.results if r.signal == decision.direction]

        if open_pos is not None and open_pos["direction"] != decision.direction.value:
            # Flip: eski pozitsiya joriy narxda yopiladi
            open_pos["stage"] = open_pos["stage"]
            flip_event = type("E", (), {"event_type": "EXPIRED", "fill_price": entry,
                                        "new_stage": open_pos["stage"]})()
            _close_position(open_pos, flip_event, candle, trades, settings)
            open_pos = None

        if open_pos is None:
            open_pos = {
                "direction": decision.direction.value,
                "entry": entry,
                "sl": levels.sl,
                "orig_sl": levels.sl,   # asl SL — R hisobi uchun (o'zgarmaydi)
                "tp1": levels.tp1, "tp2": levels.tp2, "tp3": levels.tp3,
                "stage": 0,
                "start_i": i,
                "strategies": voters,
                "score": decision.score,
            }

    # --- Oxirida yopilmagan pozitsiya ---
    if open_pos is not None:
        last = df.iloc[-1]
        flip_event = type("E", (), {"event_type": "EXPIRED", "fill_price": float(last["close"]),
                                    "new_stage": open_pos["stage"]})()
        _close_position(open_pos, flip_event, last, trades, settings)

    metrics = compute_metrics(trades)
    metrics["per_strategy"] = per_strategy_metrics(trades)
    metrics["trades"] = trades
    logger.info(
        "[BACKTEST] %s %s: %d tranzaksiya, win_rate=%.1f%%, PF=%.2f, avgR=%.2f",
        symbol, timeframe, metrics["total_trades"],
        metrics["win_rate"], metrics["profit_factor"], metrics["avg_r"],
    )
    return metrics


def _close_position(pos: dict, event, candle, trades: list[dict],
                    settings: Settings) -> None:
    exit_price = float(event.fill_price)
    stage = pos["stage"]
    # Asl SL (risk masofasi) bo'yicha R hisoblanadi — breakeven ko'chishi R ni buzmaydi
    orig_sl = pos.get("orig_sl", pos["sl"])

    if event.event_type in ("TP2", "TP3"):
        # 1:2 model: TP2 (2R) da to'liq yopiladi → +2R g'alaba
        r = 2.0
        stage = 2
    elif event.event_type == "SL" and stage == 0:
        r = -1.0
    else:
        # SL breakeven'da (stage>=1) → 0R zararsiz; EXPIRED → joriy narx
        r = final_r_multiple(
            Direction(pos["direction"]), pos["entry"], orig_sl, stage, exit_price
        )

    risk_frac = abs(pos["entry"] - orig_sl) / pos["entry"]
    trades.append({
        "direction": pos["direction"],
        "entry": pos["entry"],
        "exit": exit_price,
        "r": r,
        "pnl_pct": round(r * risk_frac * 100, 3),
        "close_reason": event.event_type,
        "stage": stage,
        "strategies": pos["strategies"],
        "score": pos["score"],
        "index": pos["start_i"],
    })
