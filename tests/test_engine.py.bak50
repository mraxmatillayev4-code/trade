"""Scoring, regime, risk va lifecycle testlari."""
import asyncio
import math

from app.core.enums import Direction, MarketRegime, MTFAlignment, SignalStatus
from app.engine.lifecycle import CandleTick, evaluate, final_r_multiple
from app.engine.market_regime import detect_regime
from app.engine.risk import calculate_levels, position_size
from app.engine.scoring import aggregate
from app.indicators.bundle import compute_bundle
from app.strategies.base import StrategyResult


def _res(name: str, signal: Direction, score: float) -> StrategyResult:
    return StrategyResult(
        name=name, display_name=name, signal=signal,
        score=score, confidence=score * 10, reason="test",
    )


def run_async(coro):
    """Helper to run async function in sync tests."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def test_aggregate_all_buy(uptrend_df, settings):
    b = compute_bundle(uptrend_df, settings)
    results = [
        _res("ema_trend", Direction.BUY, 8),
        _res("supertrend", Direction.BUY, 9),
        _res("vwap", Direction.BUY, 7),
        _res("breakout", Direction.BUY, 9),
        _res("divergence", Direction.NEUTRAL, 0),
    ]
    d = run_async(aggregate(results, MarketRegime.TRENDING, MTFAlignment.ALIGNED,
                  [("1h", Direction.BUY)], settings, "15m"))
    assert d.direction == Direction.BUY
    assert d.score >= 7
    assert d.passes_threshold is True


def test_aggregate_equal_no_signal(settings):
    results = [
        _res("ema_trend", Direction.BUY, 8),
        _res("supertrend", Direction.BUY, 8),
        _res("vwap", Direction.SELL, 8),
        _res("breakout", Direction.SELL, 8),
        _res("divergence", Direction.NEUTRAL, 0),
    ]
    d = run_async(aggregate(results, MarketRegime.RANGING, MTFAlignment.NONE, [], settings, "15m"))
    assert d.direction == Direction.NEUTRAL


def test_aggregate_mtf_against_blocks_conservative(uptrend_df, settings):
    settings.quality_mode = settings.quality_mode.__class__.CONSERVATIVE
    results = [
        _res("ema_trend", Direction.BUY, 9),
        _res("supertrend", Direction.BUY, 9),
        _res("breakout", Direction.BUY, 9),
        _res("trend_momentum", Direction.BUY, 9),
        _res("vwap", Direction.NEUTRAL, 0),
        _res("divergence", Direction.NEUTRAL, 0),
    ]
    d = run_async(aggregate(results, MarketRegime.TRENDING, MTFAlignment.AGAINST,
                  [("1h", Direction.SELL)], settings, "15m"))
    assert d.passes_threshold is False
    assert "bloklandi" in d.block_reason or "qarshi" in d.block_reason.lower()


def test_regime_trending(uptrend_df, settings):
    b = compute_bundle(uptrend_df, settings)
    regime = detect_regime(b)
    assert regime in (MarketRegime.TRENDING, MarketRegime.HIGH_VOLATILITY)


def test_risk_levels_buy(settings):
    lv = calculate_levels(Direction.BUY, entry=100.0, atr_value=2.0, settings=settings)
    assert lv.sl < lv.entry < lv.tp1 < lv.tp2 < lv.tp3
    assert math.isclose(lv.tp1 - lv.entry, lv.entry - lv.sl)  # 1R
    assert math.isclose(lv.tp3 - lv.entry, 3 * (lv.entry - lv.sl))


def test_risk_levels_sell(settings):
    lv = calculate_levels(Direction.SELL, entry=100.0, atr_value=2.0, settings=settings)
    assert lv.tp3 < lv.tp2 < lv.tp1 < lv.entry < lv.sl


def test_position_size(settings):
    qty, risk = position_size(10_000, 1.0, risk_distance=2.0, entry=100.0)
    assert math.isclose(risk, 100.0)       # 1% of 10k
    assert math.isclose(qty, 50.0)         # 100 / 2


def test_lifecycle_tp_sequence(settings):
    entry, sl = 100.0, 97.0  # risk = 3
    tp1, tp2, tp3 = 103.0, 106.0, 109.0

    # 1-sham: TP1 (1R)
    e = evaluate(Direction.BUY, 0, entry, sl, tp1, tp2, tp3,
                 CandleTick(high=103.5, low=99.0, close=103.2), 1, 100)
    assert e.event_type == "TP1"
    assert e.move_sl_to_be is True

    # 2-sham: TP2 (2R) - pozitsiya to'liq yopiladi
    e2 = evaluate(Direction.BUY, 1, entry, entry, tp1, tp2, tp3,
                  CandleTick(high=106.2, low=101.0, close=106.0), 2, 100)
    assert e2.event_type == "TP2"
    assert e2.close_position is True


def test_lifecycle_sl_first(settings):
    # Bir shamda ham TP1 ham SL darajasi ko'rinsa → SL ustun (konservativ)
    e = evaluate(Direction.BUY, 0, 100.0, 97.0, 103.0, 106.0, 109.0,
                 CandleTick(high=103.5, low=96.5, close=98.0), 1, 100)
    assert e.event_type == "SL"


def test_lifecycle_expiry(settings):
    e = evaluate(Direction.BUY, 0, 100.0, 97.0, 103.0, 106.0, 109.0,
                 CandleTick(high=101.0, low=99.0, close=100.5), 150, 100)
    assert e.event_type == "EXPIRED"


def test_final_r_tp3():
    r = final_r_multiple(Direction.BUY, 100.0, 97.0, 3, 109.0)
    assert math.isclose(r, 2.0, abs_tol=0.01)  # (1+2+3)/3 = 2R


def test_final_r_sl_stage0():
    r = final_r_multiple(Direction.BUY, 100.0, 97.0, 0, 97.0)
    assert math.isclose(r, -1.0)


def test_final_r_be_after_tp1():
    # TP1 olingan (1R), keyin SL breakeven da (entry) → 0R zararsiz
    r = final_r_multiple(Direction.BUY, 100.0, 97.0, 1, 100.0)
    assert math.isclose(r, 0.0, abs_tol=0.01)
