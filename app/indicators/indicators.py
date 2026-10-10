"""
Indikatorlar — barchasi pandas/numpy bilan qo'lda implement qilingan.
MUHIM: barcha hisob-kitoblar faqat yopilgan shamlar asosida.
Har bir funksiya butun seriyani qaytaradi (backtest va live bir xil mantiq).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------- Moving averages ----------------
def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


# ---------------- RSI (Wilder) ----------------
def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    # avg_loss 0 bo'lsa (ketma-ket o'sish) → RSI 100
    out = out.fillna(100.0).clip(0.0, 100.0)
    return out


# ---------------- MACD ----------------
def macd(close: pd.Series, fast: int = 12, slow: int = 26,
         signal_period: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


# ---------------- ATR (Wilder) ----------------
def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = true_range(high, low, close)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


# ---------------- ADX / DI (Wilder) ----------------
def adx(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_dm = pd.Series(plus_dm, index=high.index)
    minus_dm = pd.Series(minus_dm, index=high.index)

    tr = true_range(high, low, close)
    atr_s = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()

    plus_di = 100.0 * plus_dm.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean() / atr_s
    minus_di = 100.0 * minus_dm.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean() / atr_s

    di_sum = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum
    adx_s = dx.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    return adx_s.fillna(0.0), plus_di.fillna(0.0), minus_di.fillna(0.0)


# ---------------- Bollinger Bands ----------------
def bollinger(close: pd.Series, period: int = 20, std_mult: float = 2.0
              ) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = sma(close, period)
    std = close.rolling(window=period).std(ddof=0)
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    return upper, mid, lower


# ---------------- Supertrend ----------------
def supertrend(high: pd.Series, low: pd.Series, close: pd.Series,
               period: int = 10, multiplier: float = 3.0
               ) -> tuple[pd.Series, pd.Series]:
    """
    Qaytaradi: (supertrend_line, direction)
    direction: 1 = bullish (ko'tarilish), -1 = bearish (tushish).
    """
    _atr = atr(high, low, close, period)
    hl2 = (high + low) / 2.0

    upper_basic = hl2 + multiplier * _atr
    lower_basic = hl2 - multiplier * _atr

    n = len(close)
    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    st_line = np.full(n, np.nan)
    direction = np.full(n, np.nan)

    c = close.to_numpy()
    ub = upper_basic.to_numpy()
    lb = lower_basic.to_numpy()

    prev_upper = np.nan
    prev_lower = np.nan
    prev_dir = 1  # 1 = bullish, -1 = bearish

    for i in range(n):
        # ATR hali hisoblanmagan (warmup) satrlar — neytral, o'tkazib yuboriladi
        if np.isnan(_atr.iloc[i]) or np.isnan(ub[i]) or np.isnan(lb[i]):
            continue

        if np.isnan(prev_upper):
            # birinchi yaroqli satr
            final_upper[i] = ub[i]
            final_lower[i] = lb[i]
            direction[i] = 1 if c[i] >= hl2.iloc[i] else -1
        else:
            # final band rekursiyasi (standart Supertrend)
            final_upper[i] = (
                ub[i] if (ub[i] < prev_upper or c[i - 1] > prev_upper)
                else prev_upper
            )
            final_lower[i] = (
                lb[i] if (lb[i] > prev_lower or c[i - 1] < prev_lower)
                else prev_lower
            )
            # yo'nalish almashinuvi
            if prev_dir == -1:
                direction[i] = 1 if c[i] > final_upper[i] else -1
            else:
                direction[i] = 1 if c[i] >= final_lower[i] else -1

        st_line[i] = final_lower[i] if direction[i] == 1 else final_upper[i]
        prev_upper = final_upper[i]
        prev_lower = final_lower[i]
        prev_dir = direction[i]

    return (
        pd.Series(st_line, index=close.index),
        pd.Series(direction, index=close.index),
    )


# ---------------- VWAP (rolling, crypto 24/7) ----------------
def rolling_vwap(df: pd.DataFrame, window: int = 20) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = typical * df["volume"]
    return pv.rolling(window=window).sum() / df["volume"].rolling(window=window).sum()


# ---------------- Pivotlar (tasdiqlangan, repaint qilmaydi) ----------------
def find_pivots(high: pd.Series, low: pd.Series, left: int = 2, right: int = 2
                ) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """
    Fractal pivotlar. Pivot faqat `right` ta sham o'ng tomonda yopilgandan keyin
    tasdiqlangan hisoblanadi — shu sababli repaint bo'lmaydi.
    Qaytaradi: (pivot_highs[(index, price)], pivot_lows[(index, price)])
    """
    n = len(high)
    pivot_highs: list[tuple[int, float]] = []
    pivot_lows: list[tuple[int, float]] = []
    h = high.to_numpy()
    lo = low.to_numpy()

    for i in range(left, n - right):
        if all(h[i] > h[i - j] for j in range(1, left + 1)) and \
           all(h[i] > h[i + j] for j in range(1, right + 1)):
            pivot_highs.append((i, float(h[i])))
        if all(lo[i] < lo[i - j] for j in range(1, left + 1)) and \
           all(lo[i] < lo[i + j] for j in range(1, right + 1)):
            pivot_lows.append((i, float(lo[i])))

    return pivot_highs, pivot_lows


def support_resistance(high: pd.Series, low: pd.Series, lookback: int = 80,
                       left: int = 2, right: int = 2
                       ) -> tuple[float | None, float | None]:
    """So'nggi tasdiqlangan pivotlardan eng yaqin support / resistance."""
    n = len(high)
    start = max(left, n - lookback)
    pivot_highs, pivot_lows = find_pivots(high, low, left, right)

    recent_highs = [p for idx, p in pivot_highs if idx >= start]
    recent_lows = [p for idx, p in pivot_lows if idx >= start]

    resistance = max(recent_highs) if recent_highs else None
    support = min(recent_lows) if recent_lows else None
    return support, resistance


# ---------------- RSI divergensiya ----------------
def detect_divergence(high: pd.Series, low: pd.Series, close: pd.Series,
                      rsi_s: pd.Series, lookback: int = 90,
                      left: int = 2, right: int = 2,
                      oversold: float = 45.0, overbought: float = 55.0
                      ) -> tuple[str, dict]:
    """
    Bullish: narx Lower Low, RSI Higher Low (RSI past zonada).
    Bearish: narx Higher High, RSI Lower High (RSI yuqori zonada).
    Faqat tasdiqlangan pivotlardan foydalaniladi → repaint yo'q.
    Pivotlar high/low ekstremumlari bo'yicha aniqlanadi.
    """
    n = len(close)
    pivot_highs, pivot_lows = find_pivots(high, low, left, right)

    r = rsi_s.to_numpy()

    lows = [(i, p) for i, p in pivot_lows if i >= n - lookback]
    highs = [(i, p) for i, p in pivot_highs if i >= n - lookback]

    # Bullish divergence
    if len(lows) >= 2:
        (i1, p1), (i2, p2) = lows[-2], lows[-1]
        if p2 < p1 and r[i2] > r[i1] and r[i2] < oversold:
            result = {
                "type": "bullish",
                "pivot1_index": i1, "pivot1_price": p1, "pivot1_rsi": float(r[i1]),
                "pivot2_index": i2, "pivot2_price": p2, "pivot2_rsi": float(r[i2]),
            }
            return "BUY", result

    # Bearish divergence
    if len(highs) >= 2:
        (i1, p1), (i2, p2) = highs[-2], highs[-1]
        if p2 > p1 and r[i2] < r[i1] and r[i2] > overbought:
            result = {
                "type": "bearish",
                "pivot1_index": i1, "pivot1_price": p1, "pivot1_rsi": float(r[i1]),
                "pivot2_index": i2, "pivot2_price": p2, "pivot2_rsi": float(r[i2]),
            }
            return "SELL", result

    return "NEUTRAL", {}


# ---------------- Slope (foiz ko'rinishida) ----------------
def slope_pct(series: pd.Series, lookback: int = 10) -> float:
    if len(series) < lookback + 1:
        return 0.0
    old = float(series.iloc[-lookback - 1])
    new = float(series.iloc[-1])
    if old == 0:
        return 0.0
    return (new - old) / old * 100.0


# ---------------- Keltner Channel ----------------
def keltner(high: pd.Series, low: pd.Series, close: pd.Series,
            period: int = 20, mult: float = 1.5
            ) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Keltner kanali: EMA(20) ± mult * ATR."""
    mid = ema(close, period)
    _atr = atr(high, low, close, period)
    upper = mid + mult * _atr
    lower = mid - mult * _atr
    return upper, mid, lower


# ---------------- Linear regression slope ----------------
def linreg_slope(series: pd.Series, lookback: int = 20) -> pd.Series:
    """
    Har nuqtada oxirgi `lookback` qiymat bo'yicha linear regression
    qiyaligini (narx birligida) qaytaradi.
    """
    x = np.arange(lookback)
    x_mean = x.mean()
    denom = ((x - x_mean) ** 2).sum()
    out = pd.Series(np.nan, index=series.index, dtype=float)
    vals = series.to_numpy(dtype=float)
    for i in range(lookback - 1, len(series)):
        y = vals[i - lookback + 1: i + 1]
        if np.isnan(y).any():
            continue
        y_mean = y.mean()
        slope = ((x - x_mean) * (y - y_mean)).sum() / denom
        out.iloc[i] = slope
    return out


# ---------------- Ichimoku Cloud ----------------
def ichimoku(high: pd.Series, low: pd.Series,
             conv_period: int = 9, base_period: int = 26,
             span_b_period: int = 52, displacement: int = 26
             ) -> dict[str, pd.Series]:
    """
    Qaytaradi:
      tenkan  (Conversion line)
      kijun   (Base line)
      span_a  (Senkou Span A — oldinga siljigan)
      span_b  (Senkou Span B — oldinga siljigan)
    Anti-repaint: span'lar `displacement` sham oldinga siljitiladi.
    """
    def mid(period: int) -> pd.Series:
        hh = high.rolling(period).max()
        ll = low.rolling(period).min()
        return (hh + ll) / 2.0

    tenkan = mid(conv_period)
    kijun = mid(base_period)
    span_a = ((tenkan + kijun) / 2.0).shift(displacement)
    span_b = mid(span_b_period).shift(displacement)
    return {
        "tenkan": tenkan,
        "kijun": kijun,
        "span_a": span_a,
        "span_b": span_b,
    }


# ---------------- Stochastic Oscillator ----------------
def stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
               k_period: int = 14, d_period: int = 3
               ) -> tuple[pd.Series, pd.Series]:
    """%K va %D. 0–100 oraliqda. >80 overbought, <20 oversold."""
    lowest = low.rolling(k_period).min()
    highest = high.rolling(k_period).max()
    rng = (highest - lowest).replace(0.0, np.nan)
    k = 100.0 * (close - lowest) / rng
    k = k.fillna(50.0).clip(0.0, 100.0)
    d = k.rolling(d_period).mean().fillna(50.0)
    return k, d


# ---------------- On-Balance Volume (OBV) ----------------
def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff()).fillna(0.0)
    return (direction * volume).cumsum()


# ---------------- Candle (narx) shakllari ----------------
def detect_candle_pattern(open_: pd.Series, high: pd.Series, low: pd.Series,
                          close: pd.Series) -> dict:
    """
    Yopilgan oxirgi sham asosida taniqli shakllarni aniqlaydi.
    Faqat yopiq shamlarda chaqiriladi → repaint yo'q.
    Qaytaradi: {
        bullish_engulfing, bearish_engulfing,
        hammer, shooting_star, bullish_pin, bearish_pin
    }
    """
    if len(close) < 2:
        return {}
    o1, o0 = float(open_.iloc[-2]), float(open_.iloc[-1])
    c1, c0 = float(close.iloc[-2]), float(close.iloc[-1])
    h0, l0 = float(high.iloc[-1]), float(low.iloc[-1])
    rng = h0 - l0
    rng = rng if rng > 0 else 1e-9

    body = abs(c0 - o0)
    upper_wick = h0 - max(o0, c0)
    lower_wick = min(o0, c0) - l0
    body_pct = body / rng

    prev_green = c1 >= o1
    prev_red = c1 < o1
    cur_green = c0 >= o0
    cur_red = c0 < o0

    bullish_engulfing = (
        prev_red and cur_green
        and o0 <= c1 * 0.999 and c0 >= o1 * 1.001
        and body_pct > 0.55
    )
    bearish_engulfing = (
        prev_green and cur_red
        and o0 >= c1 * 1.001 and c0 <= o1 * 0.999
        and body_pct > 0.55
    )
    # Hammer (pastdagi uzun soya, kichik tana) — pastdagi bukilish
    hammer = lower_wick > body * 2.0 and upper_wick < body * 0.9 and body_pct < 0.45
    shooting_star = upper_wick > body * 2.0 and lower_wick < body * 0.9 and body_pct < 0.45

    return {
        "bullish_engulfing": bool(bullish_engulfing),
        "bearish_engulfing": bool(bearish_engulfing),
        "hammer": bool(hammer),
        "shooting_star": bool(shooting_star),
        "bullish_pin": bool(hammer),
        "bearish_pin": bool(shooting_star),
    }
