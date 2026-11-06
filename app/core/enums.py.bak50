"""Tizim bo'ylab ishlatiladigan enum'lar."""
from __future__ import annotations

import enum


class Direction(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"
    NEUTRAL = "NEUTRAL"


class Timeframe(str, enum.Enum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"

    @property
    def minutes(self) -> int:
        return {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}[self.value]

    @property
    def seconds(self) -> int:
        return self.minutes * 60


# Signal timeframe'iga qarab yuqori (tasdiqlovchi) timeframe'lar
HIGHER_TIMEFRAMES: dict[str, list[str]] = {
    "1m": ["5m", "15m"],
    "5m": ["15m", "1h"],
    "15m": ["1h", "4h"],
    "30m": ["1h", "4h"],
    "1h": ["4h"],
    "4h": [],
}


class SignalStatus(str, enum.Enum):
    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    TP1_HIT = "TP1_HIT"
    TP2_HIT = "TP2_HIT"
    TP3_HIT = "TP3_HIT"
    TP4_HIT = "TP4_HIT"
    TP5_HIT = "TP5_HIT"
    SL_HIT = "SL_HIT"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"

    @property
    def is_final(self) -> bool:
        return self in (
            SignalStatus.TP5_HIT, SignalStatus.SL_HIT,
            SignalStatus.EXPIRED, SignalStatus.CANCELLED,
        )

    @property
    def is_open(self) -> bool:
        return self in (
            SignalStatus.CREATED, SignalStatus.ACTIVE,
            SignalStatus.TP1_HIT, SignalStatus.TP2_HIT,
            SignalStatus.TP3_HIT, SignalStatus.TP4_HIT,
        )


class SignalStrength(str, enum.Enum):
    NO_TRADE = "NO_TRADE"
    WEAK = "WEAK"
    GOOD = "GOOD"
    STRONG = "STRONG"


class MarketRegime(str, enum.Enum):
    TRENDING = "TRENDING"
    RANGING = "RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"


class QualityMode(str, enum.Enum):
    AGGRESSIVE = "AGGRESSIVE"
    BALANCED = "BALANCED"
    CONSERVATIVE = "CONSERVATIVE"


class MTFAlignment(str, enum.Enum):
    ALIGNED = "ALIGNED"        # yuqori timeframe'lar signalni tasdiqlaydi
    MIXED = "MIXED"            # qismi tasdiq, qarsi neytral
    AGAINST = "AGAINST"        # yuqori trend signalga qarshi
    NONE = "NONE"              # yuqori timeframe ma'lumoti yo'q


class PaperStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class TradeResult(str, enum.Enum):
    WIN = "WIN"
    LOSS = "LOSS"
    BREAKEVEN = "BREAKEVEN"
    EXPIRED = "EXPIRED"


# Strategiya kalitlari (weight va regime sozlamalari shu nomlar bilan ishlaydi)
STRATEGY_EMA = "ema_trend"
STRATEGY_SUPERTREND = "supertrend"
STRATEGY_VWAP = "vwap"
STRATEGY_BREAKOUT = "breakout"
STRATEGY_DIVERGENCE = "divergence"
STRATEGY_SQUEEZE = "squeeze"
STRATEGY_ICHIMOKU = "ichimoku"
STRATEGY_PRICE_ACTION = "price_action"
STRATEGY_STOCHASTIC = "stochastic"
STRATEGY_OBV = "obv"
STRATEGY_SMART_MONEY = "smart_money"
STRATEGY_CVD = "cvd"
STRATEGY_WAVETREND = "wavetrend"
STRATEGY_BRAIN = "brain"

ALL_STRATEGY_KEYS = [
    STRATEGY_EMA,
    STRATEGY_SUPERTREND,
    STRATEGY_VWAP,
    STRATEGY_BREAKOUT,
    STRATEGY_DIVERGENCE,
    STRATEGY_SQUEEZE,
    STRATEGY_ICHIMOKU,
    STRATEGY_PRICE_ACTION,
    STRATEGY_STOCHASTIC,
    STRATEGY_OBV,
    STRATEGY_SMART_MONEY,
    STRATEGY_CVD,
    STRATEGY_WAVETREND,
    STRATEGY_BRAIN,
]
