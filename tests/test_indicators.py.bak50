"""Indikatorlar testlari."""
import numpy as np
import pandas as pd

from app.indicators import indicators as ind


def test_ema_constant_series():
    s = pd.Series([50.0] * 100)
    e = ind.ema(s, 20)
    assert abs(e.iloc[-1] - 50.0) < 1e-9


def test_rsi_bounds_and_overbought():
    # Kuchli monoton o'sish → RSI 100 ga yaqin
    up = pd.Series(np.linspace(100, 200, 100))
    r = ind.rsi(up, 14)
    assert 0 <= r.iloc[-1] <= 100
    assert r.iloc[-1] > 90

    down = pd.Series(np.linspace(200, 100, 100))
    r2 = ind.rsi(down, 14)
    assert r2.iloc[-1] < 10


def test_macd_sign():
    up = pd.Series(np.linspace(100, 200, 100))
    line, signal, hist = ind.macd(up)
    assert line.iloc[-1] > signal.iloc[-1]
    assert hist.iloc[-1] > 0


def test_atr_positive():
    rng = np.random.default_rng(1)
    high = pd.Series(100 + rng.uniform(0, 2, 100))
    low = pd.Series(99 - rng.uniform(0, 2, 100))
    close = pd.Series(99.5 + rng.normal(0, 0.5, 100))
    a = ind.atr(high, low, close, 14)
    assert a.iloc[-1] > 0


def test_supertrend_direction_values():
    rng = np.random.default_rng(2)
    close = pd.Series(100 + np.cumsum(rng.normal(0.2, 1, 100)))
    high = close + rng.uniform(0.1, 1, 100)
    low = close - rng.uniform(0.1, 1, 100)
    line, direction = ind.supertrend(high, low, close)
    assert set(direction.dropna().unique()).issubset({1, -1})


def test_pivots_no_repaint():
    # Pivot faqat right tasdiqdan keyin paydo bo'ladi
    n = 50
    high = pd.Series(np.full(n, 100.0))
    low = pd.Series(np.full(n, 99.0))
    high.iloc[20] = 105  # aniq tepalik
    low.iloc[20] = 99
    ph, pl = ind.find_pivots(high, low, left=2, right=2)
    assert any(idx == 20 for idx, _ in ph)
    # Oxirgi 2 sham pivot bo'la olmaydi (hali tasdiqlanmagan)
    assert all(idx <= n - 3 for idx, _ in ph)


def test_vwap_between_high_low(uptrend_df):
    vwap = ind.rolling_vwap(uptrend_df, 20)
    assert vwap.iloc[-1] > 0
    assert uptrend_df["low"].iloc[-20:].min() <= vwap.iloc[-1] <= uptrend_df["high"].iloc[-20:].max()
