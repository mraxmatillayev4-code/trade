"""Foydalanuvchi va uning sozlamalari."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # telegram id
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    subscription: Mapped[str] = mapped_column(String(16), default="FREE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    settings: Mapped["UserSettings"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class UserSettings(Base):
    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    notify_buy: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_sell: Mapped[bool] = mapped_column(Boolean, default=True)
    strong_only: Mapped[bool] = mapped_column(Boolean, default=False)
    quality_mode: Mapped[str] = mapped_column(String(16), default="BALANCED")
    # Bo'sh ro'yxat = barchasi
    symbols_filter: Mapped[str] = mapped_column(String(500), default="")
    timeframes_filter: Mapped[str] = mapped_column(String(100), default="")

    user: Mapped["User"] = relationship(back_populates="settings")
