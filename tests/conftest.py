"""Pytest sozlamalari va sintetik ma'lumot generatori."""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_bot.db")
os.environ.setdefault("BOT_TOKEN", "test:token")
os.environ.setdefault("ADMIN_IDS", "12345")

import numpy as np
import pandas as pd
import pytest

from app.core.config import Settings
from app.database.base import Base
from app.database.session import engine


@pytest.fixture(scope="session", autouse=True)
async def init_test_db():
    """Initialize test database with latest schema."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings()


def make_candles(n: int = 400, trend: float = 0.0, volatility: float = 0.01,
                 seed: int = 7, start_price: float = 100.0,
                 timeframe_minutes: int = 15) -> pd.DataFrame:
    """
    Sintetik shamlar:
    trend > 0 → barqaror ko'tarilish; trend < 0 → tushish; trend = 0 → yon tomonga.
    """
    rng = np.random.default_rng(seed)
    returns = rng.normal(loc=trend, scale=volatility, size=n)
    # So'nggi segmentda trend barqaror ("yetilgan trend") — kam shovqin
    if trend != 0:
        k = min(60, n)
        returns[-k:] = rng.normal(loc=trend * 1.2, scale=volatility * 0.25, size=k)
    close = start_price * np.exp(np.cumsum(returns))

    opens = np.empty(n)
    opens[0] = start_price
    opens[1:] = close[:-1]
    highs = np.maximum(opens, close) * (1 + np.abs(rng.normal(0, volatility * 0.5, n)))
    lows = np.minimum(opens, close) * (1 - np.abs(rng.normal(0, volatility * 0.5, n)))
    volume = rng.uniform(800, 1500, n)
    # Trend kunlari hajmni oshiramiz
    volume[-30:] *= 1.8

    start = pd.Timestamp("2024-01-01", tz="UTC")
    times = [start + pd.Timedelta(minutes=timeframe_minutes * i) for i in range(n)]

    df = pd.DataFrame({
        "open_time": times,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": close,
        "volume": volume,
        "close_time": [t + pd.Timedelta(minutes=timeframe_minutes) for t in times],
    })
    df.attrs["symbol"] = "TESTUSDT"
    df.attrs["timeframe"] = "15m"
    return df


@pytest.fixture
def uptrend_df(settings) -> pd.DataFrame:
    df = make_candles(n=400, trend=0.0018, volatility=0.009, seed=3)
    return df


@pytest.fixture
def downtrend_df(settings) -> pd.DataFrame:
    return make_candles(n=400, trend=-0.0018, volatility=0.009, seed=5)


@pytest.fixture
def flat_df(settings) -> pd.DataFrame:
    return make_candles(n=400, trend=0.0, volatility=0.006, seed=11)
