"""Strategiyalar bo'yicha yig'ilgan statistika."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StrategyStat(Base):
    __tablename__ = "strategy_statistics"
    __table_args__ = (
        UniqueConstraint("strategy_name", name="uq_strategy_stat"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_name: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(80), default="")
    is_active: Mapped[bool] = mapped_column(default=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)

    total_signals: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    breakeven: Mapped[int] = mapped_column(Integer, default=0)
    sum_r: Mapped[float] = mapped_column(Float, default=0.0)
    gross_profit_r: Mapped[float] = mapped_column(Float, default=0.0)
    gross_loss_r: Mapped[float] = mapped_column(Float, default=0.0)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    @property
    def win_rate(self) -> float:
        decided = self.wins + self.losses
        return (self.wins / decided * 100) if decided else 0.0

    @property
    def profit_factor(self) -> float:
        return (self.gross_profit_r / abs(self.gross_loss_r)) if self.gross_loss_r < 0 else 0.0

    @property
    def avg_r(self) -> float:
        return (self.sum_r / self.total_signals) if self.total_signals else 0.0
