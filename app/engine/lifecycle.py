"""
Signal lifecycle — sof mantiq (DB'siz). Live va backtest bir xil foydalanadi.
Bosqichlar: CREATED → ACTIVE → TP1 → TP2 → TP3 → (yaxshi ketsa) TP4 → TP5 / SL / EXPIRED.
Konservativ: bitta shamda avval SL, keyin TP.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.enums import Direction, SignalStatus


@dataclass
class CandleTick:
    high: float
    low: float
    close: float


@dataclass
class LifecycleEvent:
    event_type: str          # TP1 | TP2 | TP3 | TP4 | TP5 | SL | EXPIRED | NONE
    fill_price: float
    new_stage: int           # 0..5
    new_status: SignalStatus | None
    close_position: bool
    move_sl_to_be: bool = False
    move_sl_to_tp1: bool = False
    portion_closed: float = 0.0


def evaluate(direction: Direction, stage: int, entry: float, sl: float,
             tp1: float, tp2: float, tp3: float, tick: CandleTick,
             candles_since_open: int, expiry_candles: int,
             runner: bool = False, extend: bool = False,
             tp4: float | None = None, tp5: float | None = None) -> LifecycleEvent:
    none = LifecycleEvent("NONE", 0.0, stage, None, False)
    risk = abs(entry - sl)
    if risk < 1e-12:
        risk = abs(tp1 - entry)
    if risk <= 0:
        risk = 1e-9
    if tp4 is None:
        tp4 = entry + 4 * risk if direction == Direction.BUY else entry - 4 * risk
    if tp5 is None:
        tp5 = entry + 5 * risk if direction == Direction.BUY else entry - 5 * risk

    if candles_since_open > expiry_candles:
        return LifecycleEvent(
            "EXPIRED", tick.close, stage, SignalStatus.EXPIRED, True, False, False, 0.0
        )

    # 1R himoya, 2R foyda (50%), 3R, yaxshi ketsa 4R/5R
    if direction == Direction.BUY:
        if tick.low <= sl:
            return LifecycleEvent(
                "SL", sl, stage, SignalStatus.SL_HIT, True, False, False,
                _remaining_portion(stage),
            )
        if stage == 0 and tick.high >= tp1:
            return LifecycleEvent("TP1", tp1, 1, SignalStatus.TP1_HIT, False, True, False, 0.0)
        if stage == 1 and tick.high >= tp2:
            if runner:
                return LifecycleEvent("TP2", tp2, 2, SignalStatus.TP2_HIT, False, False, True, 0.5)
            return LifecycleEvent("TP2", tp2, 2, SignalStatus.TP2_HIT, True, False, False, 1.0)
        if stage == 2 and tick.high >= tp3:
            if extend:
                return LifecycleEvent("TP3", tp3, 3, SignalStatus.TP3_HIT, False, False, True, 0.0)
            return LifecycleEvent("TP3", tp3, 3, SignalStatus.TP3_HIT, True, False, False, 1.0)
        if stage == 3 and tick.high >= tp4:
            if extend:
                return LifecycleEvent("TP4", tp4, 4, SignalStatus.TP4_HIT, False, False, True, 0.0)
            return LifecycleEvent("TP4", tp4, 4, SignalStatus.TP4_HIT, True, False, False, 1.0)
        if stage >= 4 and tick.high >= tp5:
            return LifecycleEvent("TP5", tp5, 5, SignalStatus.TP5_HIT, True, False, False, 1.0)
        return none

    if direction == Direction.SELL:
        if tick.high >= sl:
            return LifecycleEvent(
                "SL", sl, stage, SignalStatus.SL_HIT, True, False, False,
                _remaining_portion(stage),
            )
        if stage == 0 and tick.low <= tp1:
            return LifecycleEvent("TP1", tp1, 1, SignalStatus.TP1_HIT, False, True, False, 0.0)
        if stage == 1 and tick.low <= tp2:
            if runner:
                return LifecycleEvent("TP2", tp2, 2, SignalStatus.TP2_HIT, False, False, True, 0.5)
            return LifecycleEvent("TP2", tp2, 2, SignalStatus.TP2_HIT, True, False, False, 1.0)
        if stage == 2 and tick.low <= tp3:
            if extend:
                return LifecycleEvent("TP3", tp3, 3, SignalStatus.TP3_HIT, False, False, True, 0.0)
            return LifecycleEvent("TP3", tp3, 3, SignalStatus.TP3_HIT, True, False, False, 1.0)
        if stage == 3 and tick.low <= tp4:
            if extend:
                return LifecycleEvent("TP4", tp4, 4, SignalStatus.TP4_HIT, False, False, True, 0.0)
            return LifecycleEvent("TP4", tp4, 4, SignalStatus.TP4_HIT, True, False, False, 1.0)
        if stage >= 4 and tick.low <= tp5:
            return LifecycleEvent("TP5", tp5, 5, SignalStatus.TP5_HIT, True, False, False, 1.0)
        return none

    return none


def _remaining_portion(stage: int) -> float:
    return {0: 1.0, 1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0, 5: 0.0}.get(stage, 1.0)


def final_r_multiple(direction: Direction, entry: float, sl: float,
                     final_stage: int, exit_price: float) -> float:
    """Yopilish narxi bo'yicha R (−1R … +5R)."""
    risk = abs(entry - sl)
    if risk == 0:
        return 0.0

    def r_at(price: float) -> float:
        return ((price - entry) if direction == Direction.BUY else (entry - price)) / risk

    r = r_at(exit_price)
    return round(max(-1.0, min(5.0, r)), 3)
