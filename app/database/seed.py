"""Boshlang'ich ma'lumotlarni yaratish (symbols, strategies, paper account)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.database.models.paper import PaperAccount
from app.database.models.stats import StrategyStat
from app.database.models.symbol import Symbol

logger = get_logger(__name__)

STRATEGY_META = {
    "ema_trend": ("EMA + RSI + MACD", "Trend strategiyasi"),
    "supertrend": ("Supertrend + EMA", "Trend yo'nalishi strategiyasi"),
    "vwap": ("VWAP + RSI", "Intraday strategiya"),
    "breakout": ("Breakout + Volume", "Buzilish strategiyasi"),
    "divergence": ("RSI Divergence", "Divergensiya strategiyasi"),
    "squeeze": ("Squeeze Breakout", "Bollinger/Keltner sikvez strategiyasi"),
    "ichimoku": ("Ichimoku Cloud", "Ichimoku bulut trendi strategiyasi"),
    "price_action": ("Price Action", "Sham shakllari (engulfing/hammer) strategiyasi"),
    "stochastic": ("Stochastic %K/%D", "Haddan ortiq sotuv/xarid burilish strategiyasi"),
    "obv": ("OBV hajm oqimi", "On-Balance Volume hajm oqimi strategiyasi"),
    "smart_money": ("SMC (Sweep+FVG)", "Likvidlik sweep + FVG"),
    "squeeze_breakout": ("Squeeze Breakout", "TTM squeeze chiqishi"),
    "ema_pullback": ("EMA Pullback", "Trend ichida qaytish"),
    "supertrend_pullback": ("Supertrend Pullback", "ST chizig'iga qayta tegish"),
    "trend_momentum": ("Trend Momentum", "Trend + momentum"),
    "wavetrend": ("WaveTrend (Cipher B)", "WT ekstremum + divergensiya"),
    "brain": ("SINO AI", "Mahalliy inson-fikr ovozi, xatolardan o'rganadi"),
}


async def seed_db(session: AsyncSession) -> None:
    settings = get_settings()

    # Symbols
    for name in settings.symbol_list:
        exists = await session.scalar(select(Symbol).where(Symbol.name == name))
        if not exists:
            session.add(Symbol(name=name, is_active=True))

    # Strategy stats
    weights = settings.strategy_weights
    for key, (display, _desc) in STRATEGY_META.items():
        exists = await session.scalar(
            select(StrategyStat).where(StrategyStat.strategy_name == key)
        )
        if not exists:
            session.add(
                StrategyStat(
                    strategy_name=key,
                    display_name=display,
                    is_active=True,
                    weight=weights.get(key, 1.0),
                )
            )

    # Paper hisoblar endi har FOYDALANUVCHI uchun alohida (per-user) —
    # seed'da umumiy hisob yaratilmaydi; u birinchi marta kerak bo'lganda ochiladi.

    await session.commit()
    logger.info("Seed ma'lumotlar tayyor")
