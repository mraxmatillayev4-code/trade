"""IndikatorBundle — barcha indikatorlar bir marta hisoblanadi (performance)."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.core.config import Settings
from app.indicators import indicators as ind


@dataclass
class IndicatorBundle:
    close: pd.Series
    high: pd.Series
    low: pd.Series
    open_: pd.Series
    volume: pd.Series

    ema20: pd.Series
    ema50: pd.Series
    ema200: pd.Series
    rsi: pd.Series
    macd_line: pd.Series
    macd_signal: pd.Series
    macd_hist: pd.Series
    atr: pd.Series
    adx: pd.Series
    plus_di: pd.Series
    minus_di: pd.Series
    bb_upper: pd.Series
    bb_mid: pd.Series
    bb_lower: pd.Series
    kc_upper: pd.Series
    kc_lower: pd.Series
    bb_width: pd.Series
    squeeze: pd.Series  # True = Keltner ichidagi Bollinger (sikvez)
    momentum_slope: pd.Series
    supertrend_line: pd.Series
    supertrend_dir: pd.Series
    vwap: pd.Series
    vol_ma: pd.Series
    ichimoku: dict
    stoch_k: pd.Series
    stoch_d: pd.Series
    obv: pd.Series
    obv_ma: pd.Series
    candle_patterns: dict

    support: float | None
    resistance: float | None

    ema50_slope: float
    ema200_slope: float
    vwap_slope: float

    @property
    def last_close(self) -> float:
        return float(self.close.iloc[-1])

    @property
    def last_atr(self) -> float:
        v = float(self.atr.iloc[-1])
        return v if v == v else 0.0  # NaN tekshiruvi


def compute_bundle(df: pd.DataFrame, settings: Settings) -> IndicatorBundle:
    """Yopilgan shamlar DataFrame'idan barcha indikatorlarni hisoblaydi."""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    open_ = df["open"].astype(float)
    volume = df["volume"].astype(float)

    ema20 = ind.ema(close, settings.ema_mid)
    ema50 = ind.ema(close, settings.ema_fast)
    ema200 = ind.ema(close, settings.ema_slow)
    rsi_s = ind.rsi(close, settings.rsi_period)
    macd_line, macd_signal, macd_hist = ind.macd(
        close, settings.macd_fast, settings.macd_slow, settings.macd_signal
    )
    atr_s = ind.atr(high, low, close, settings.atr_period)
    adx_s, plus_di, minus_di = ind.adx(high, low, close, settings.adx_period)
    bb_upper, bb_mid, bb_lower = ind.bollinger(close, 20, 2.0)
    kc_upper, _, kc_lower = ind.keltner(high, low, close, 20, 1.5)
    # Squeeze: Bollinger diapazoni Keltner ichida (volatillik siqilgan)
    squeeze = (bb_lower > kc_lower) & (bb_upper < kc_upper)
    bb_width = (bb_upper - bb_lower) / bb_mid
    mom_slope = ind.linreg_slope(close, 20)
    ichi = ind.ichimoku(high, low)
    stoch_k, stoch_d = ind.stochastic(high, low, close, 14, 3)
    obv_s = ind.obv(close, volume)
    obv_ma = obv_s.rolling(window=20).mean()
    patterns = ind.detect_candle_pattern(open_, high, low, close)
    st_line, st_dir = ind.supertrend(
        high, low, close, settings.supertrend_period, settings.supertrend_multiplier
    )
    vwap_s = ind.rolling_vwap(df, settings.vwap_window)
    vol_ma = volume.rolling(window=20).mean()

    support, resistance = ind.support_resistance(high, low, lookback=80)

    return IndicatorBundle(
        close=close, high=high, low=low, open_=open_, volume=volume,
        ema20=ema20, ema50=ema50, ema200=ema200,
        rsi=rsi_s,
        macd_line=macd_line, macd_signal=macd_signal, macd_hist=macd_hist,
        atr=atr_s, adx=adx_s, plus_di=plus_di, minus_di=minus_di,
        bb_upper=bb_upper, bb_mid=bb_mid, bb_lower=bb_lower,
        kc_upper=kc_upper, kc_lower=kc_lower, bb_width=bb_width,
        squeeze=squeeze, momentum_slope=mom_slope,
        supertrend_line=st_line, supertrend_dir=st_dir,
        ichimoku=ichi, stoch_k=stoch_k, stoch_d=stoch_d,
        obv=obv_s, obv_ma=obv_ma, candle_patterns=patterns,
        vwap=vwap_s, vol_ma=vol_ma,
        support=support, resistance=resistance,
        ema50_slope=ind.slope_pct(ema50, 10),
        ema200_slope=ind.slope_pct(ema200, 20),
        vwap_slope=ind.slope_pct(vwap_s, 10),
    )
