"""Ma'lumotlar bazasi bilan ishlash uchun yordamchi funksiyalar."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import SignalStatus
from app.database.models.candle import Candle
from app.database.models.signal import Signal, SignalConfirmation
from app.database.models.user import User, UserSettings


# ---------------- User ----------------
async def get_all_active_users(session: AsyncSession) -> list[int]:
    stmt = select(User.id).where(User.is_blocked.is_(False))
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---------------- Signal ----------------
async def get_or_create_user(session: AsyncSession, user_id: int,
                             username: str | None, full_name: str | None) -> User:
    user = await session.get(User, user_id)
    if user is None:
        user = User(id=user_id, username=username, full_name=full_name)
        session.add(user)
        await session.flush()
        session.add(UserSettings(user_id=user_id))
        await session.commit()
    else:
        changed = False
        if username and user.username != username:
            user.username = username
            changed = True
        if full_name and user.full_name != full_name:
            user.full_name = full_name
            changed = True
        if changed:
            await session.commit()
    return user


async def get_user_settings(session: AsyncSession, user_id: int) -> UserSettings | None:
    return await session.scalar(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )


# ---------------- Signal ----------------
async def get_open_signal(session: AsyncSession, symbol: str, timeframe: str,
                          direction: str | None = None) -> Signal | None:
    stmt = select(Signal).where(
        Signal.symbol == symbol,
        Signal.timeframe == timeframe,
        Signal.is_active.is_(True),
    )
    if direction:
        stmt = stmt.where(Signal.direction == direction)
    stmt = stmt.order_by(Signal.created_at.desc()).limit(1)
    return await session.scalar(stmt)


async def get_last_signal(session: AsyncSession, symbol: str, timeframe: str) -> Signal | None:
    stmt = (
        select(Signal)
        .where(Signal.symbol == symbol, Signal.timeframe == timeframe)
        .order_by(Signal.created_at.desc())
        .limit(1)
    )
    return await session.scalar(stmt)


async def get_active_signals(session: AsyncSession, symbol: str | None = None,
                             timeframe: str | None = None) -> list[Signal]:
    stmt = select(Signal).where(Signal.is_active.is_(True)).order_by(Signal.created_at.desc())
    if symbol:
        stmt = stmt.where(Signal.symbol == symbol)
    if timeframe:
        stmt = stmt.where(Signal.timeframe == timeframe)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_recent_signals(session: AsyncSession, limit: int = 10,
                             direction: str | None = None,
                             strong_only: bool = False) -> list[Signal]:
    stmt = select(Signal).order_by(Signal.created_at.desc()).limit(limit)
    if direction and direction in ("BUY", "SELL"):
        stmt = stmt.where(Signal.direction == direction)
    if strong_only:
        stmt = stmt.where(Signal.strength == "STRONG")
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_signal_by_id(session: AsyncSession, signal_id: int) -> Signal | None:
    return await session.get(Signal, signal_id)


async def get_confirmations(session: AsyncSession, signal_id: int) -> list[SignalConfirmation]:
    stmt = select(SignalConfirmation).where(SignalConfirmation.signal_id == signal_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def close_signal(session: AsyncSession, signal: Signal, status: SignalStatus,
                       result: str | None, r_multiple: float | None,
                       pnl_percent: float | None, close_price: float,
                       reason: str = "") -> None:
    signal.status = status.value
    signal.is_active = False
    signal.result = result
    signal.r_multiple = r_multiple
    signal.pnl_percent = pnl_percent
    signal.close_price = close_price
    signal.closed_at = datetime.now(timezone.utc)
    try:
        if reason:
            signal.close_reason = reason[:24]
    except Exception:  # noqa: BLE001
        pass
    await session.commit()


async def count_signals(session: AsyncSession) -> int:
    return await session.scalar(select(func.count(Signal.id))) or 0


async def count_signals_today(session: AsyncSession) -> int:
    """Bugun (Toshkent UTC+5) yaratilgan signallar soni — kunlik maksimum uchun."""
    from datetime import datetime, timedelta, timezone
    local = timezone(timedelta(hours=5))
    start_local = datetime.now(local).replace(hour=0, minute=0, second=0, microsecond=0)
    start = start_local.astimezone(timezone.utc)
    q = select(func.count(Signal.id)).where(Signal.created_at >= start)
    return await session.scalar(q) or 0


# ---------------- Candles ----------------
async def bulk_insert_candles(session: AsyncSession, rows: list[dict]) -> int:
    if not rows:
        return 0
    inserted = 0
    for row in rows:
        exists = await session.scalar(
            select(Candle.id).where(
                Candle.symbol == row["symbol"],
                Candle.timeframe == row["timeframe"],
                Candle.open_time == row["open_time"],
            )
        )
        if exists is None:
            session.add(Candle(**row))
            inserted += 1
    if inserted:
        await session.commit()
    return inserted
