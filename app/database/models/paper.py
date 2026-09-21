"""Paper trading (virtual savdo) — haqiqiy pul ishlatilmaydi."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PaperAccount(Base):
    """Har bir foydalanuvchi uchun alohida virtual hisob (user_id bo'yicha singleton)."""
    __tablename__ = "paper_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(32), default="main")
    initial_balance: Mapped[float] = mapped_column(Float)
    balance: Mapped[float] = mapped_column(Float)
    total_realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # --- Avto-trade (soxta pul) boshqaruvi (har foydalanuvchi uchun alohida) ---
    auto_trade_enabled: Mapped[bool] = mapped_column(default=True)
    consecutive_losses: Mapped[int] = mapped_column(Integer, default=0)
    paused_by_circuit: Mapped[bool] = mapped_column(default=False)
    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    total_wins: Mapped[int] = mapped_column(Integer, default=0)


class PaperPosition(Base):
    __tablename__ = "paper_positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    signal_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("signals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timeframe: Mapped[str] = mapped_column(String(8))
    direction: Mapped[str] = mapped_column(String(8))  # BUY | SELL

    status: Mapped[str] = mapped_column(String(8), default="OPEN", index=True)

    entry: Mapped[float] = mapped_column(Float)
    sl: Mapped[float] = mapped_column(Float)
    tp1: Mapped[float] = mapped_column(Float)
    tp2: Mapped[float] = mapped_column(Float)
    tp3: Mapped[float] = mapped_column(Float)

    qty_total: Mapped[float] = mapped_column(Float)
    qty_remaining: Mapped[float] = mapped_column(Float)
    risk_amount: Mapped[float] = mapped_column(Float)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    r_multiple: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    balance_before: Mapped[float] = mapped_column(Float)
    balance_after: Mapped[float | None] = mapped_column(Float, nullable=True)

    stage: Mapped[int] = mapped_column(Integer, default=0)  # 0 ochiq, 1 tp1, 2 tp2, 3 yopildi
    sl_moved_to_be: Mapped[bool] = mapped_column(default=False)

    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
