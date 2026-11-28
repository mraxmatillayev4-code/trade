"""Backtest va walk-forward natijalari."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Backtest(Base):
    __tablename__ = "backtests"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timeframe: Mapped[str] = mapped_column(String(8))
    period: Mapped[str] = mapped_column(String(16))  # 7d | 30d | 90d
    strategy: Mapped[str] = mapped_column(String(40), default="ALL")
    candles_count: Mapped[int] = mapped_column(Integer, default=0)
    quality_mode: Mapped[str] = mapped_column(String(16), default="BALANCED")
    walk_forward: Mapped[bool] = mapped_column(default=False)

    status: Mapped[str] = mapped_column(String(16), default="DONE")
    metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    trades_json: Mapped[str] = mapped_column(Text, default="[]")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
