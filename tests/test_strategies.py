"""Strategiyalar testlari."""
from app.core.enums import Direction
from app.indicators.bundle import compute_bundle
from app.strategies.breakout import BreakoutVolumeStrategy
from app.strategies.divergence import RsiDivergenceStrategy
from app.strategies.ema_rsi_macd import EmaRsiMacdStrategy
from app.strategies.supertrend_strat import SupertrendEmaStrategy
from app.strategies.squeeze import SqueezeBreakoutStrategy
from app.strategies.ichimoku import IchimokuStrategy
from app.strategies.price_action import PriceActionStrategy
from app.strategies.stochastic import StochasticStrategy
from app.strategies.obv import ObvVolumeFlowStrategy
from app.strategies.vwap_rsi import VwapRsiStrategy


def test_ema_strategy_uptrend_buy(uptrend_df, settings):
    b = compute_bundle(uptrend_df, settings)
    res = EmaRsiMacdStrategy().analyze(uptrend_df, b, settings, "15m")
    assert res.signal == Direction.BUY
    assert res.score >= 7


def test_ema_strategy_downtrend_sell(downtrend_df, settings):
    b = compute_bundle(downtrend_df, settings)
    res = EmaRsiMacdStrategy().analyze(downtrend_df, b, settings, "15m")
    assert res.signal == Direction.SELL


def test_supertrend_uptrend(uptrend_df, settings):
    b = compute_bundle(uptrend_df, settings)
    res = SupertrendEmaStrategy().analyze(uptrend_df, b, settings, "15m")
    assert res.signal in (Direction.BUY, Direction.NEUTRAL)


def test_supertrend_downtrend(downtrend_df, settings):
    b = compute_bundle(downtrend_df, settings)
    res = SupertrendEmaStrategy().analyze(downtrend_df, b, settings, "15m")
    assert res.signal in (Direction.SELL, Direction.NEUTRAL)


def test_vwap_intraday_only(uptrend_df, settings):
    b = compute_bundle(uptrend_df, settings)
    res = VwapRsiStrategy().analyze(uptrend_df, b, settings, "4h")
    assert res.signal == Direction.NEUTRAL


def test_vwap_15m(uptrend_df, settings):
    b = compute_bundle(uptrend_df, settings)
    res = VwapRsiStrategy().analyze(uptrend_df, b, settings, "15m")
    assert res.signal in (Direction.BUY, Direction.NEUTRAL)


def test_breakout_returns_valid(uptrend_df, settings):
    b = compute_bundle(uptrend_df, settings)
    res = BreakoutVolumeStrategy().analyze(uptrend_df, b, settings, "15m")
    assert res.signal in (Direction.BUY, Direction.SELL, Direction.NEUTRAL)


def test_divergence_returns_valid(downtrend_df, settings):
    b = compute_bundle(downtrend_df, settings)
    res = RsiDivergenceStrategy().analyze(downtrend_df, b, settings, "15m")
    assert res.signal in (Direction.BUY, Direction.SELL, Direction.NEUTRAL)


def test_squeeze_valid(uptrend_df, settings):
    b = compute_bundle(uptrend_df, settings)
    res = SqueezeBreakoutStrategy().analyze(uptrend_df, b, settings, "15m")
    assert res.signal in (Direction.BUY, Direction.SELL, Direction.NEUTRAL)
    assert 0 <= res.score <= 10


def test_ichimoku_trend(uptrend_df, settings):
    b = compute_bundle(uptrend_df, settings)
    res = IchimokuStrategy().analyze(uptrend_df, b, settings, "15m")
    assert res.signal in (Direction.BUY, Direction.SELL, Direction.NEUTRAL)
    assert 0 <= res.score <= 10


def test_ichimoku_indicators_present(uptrend_df, settings):
    b = compute_bundle(uptrend_df, settings)
    res = IchimokuStrategy().analyze(uptrend_df, b, settings, "1h")
    assert "Tenkan" in res.indicators
    assert "Cloud" in res.indicators


def test_price_action_valid(uptrend_df, settings):
    b = compute_bundle(uptrend_df, settings)
    res = PriceActionStrategy().analyze(uptrend_df, b, settings, "15m")
    assert res.signal in (Direction.BUY, Direction.SELL, Direction.NEUTRAL)
    assert 0 <= res.score <= 10


def test_stochastic_valid(uptrend_df, settings):
    b = compute_bundle(uptrend_df, settings)
    res = StochasticStrategy().analyze(uptrend_df, b, settings, "15m")
    assert res.signal in (Direction.BUY, Direction.SELL, Direction.NEUTRAL)


def test_obv_valid(uptrend_df, settings):
    b = compute_bundle(uptrend_df, settings)
    res = ObvVolumeFlowStrategy().analyze(uptrend_df, b, settings, "15m")
    assert res.signal in (Direction.BUY, Direction.SELL, Direction.NEUTRAL)


def test_scores_in_range(uptrend_df, settings):
    b = compute_bundle(uptrend_df, settings)
    for strat in [EmaRsiMacdStrategy(), SupertrendEmaStrategy(),
                  VwapRsiStrategy(), BreakoutVolumeStrategy(),
                  RsiDivergenceStrategy(), SqueezeBreakoutStrategy(),
                  IchimokuStrategy(), PriceActionStrategy(),
                  StochasticStrategy(), ObvVolumeFlowStrategy()]:
        res = strat.analyze(uptrend_df, b, settings, "15m")
        assert 0 <= res.score <= 10
        assert 0 <= res.confidence <= 100
