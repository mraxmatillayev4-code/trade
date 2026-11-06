"""Signal va uning strategiya tasdiqlari."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (
        # Database darajasidagi himoya: bitta symbol+tf+yo'nalish bo'yicha
        # bir vaqtda faqat BITTA ochiq signal bo'lishi mumkin (deduplication).
        Index(
            "uq_signal_open_direction",
            "symbol",
            "timeframe",
            "direction",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
        Index("ix_signal_symbol_tf", "symbol", "timeframe"),
        Index("ix_signal_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timeframe: Mapped[str] = mapped_column(String(8), index=True)
    direction: Mapped[str] = mapped_column(String(8))  # BUY | SELL

    status: Mapped[str] = mapped_column(String(16), default="CREATED", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    win_probability: Mapped[float] = mapped_column(Float, default=0.0)
    signal_no: Mapped[int] = mapped_column(Integer, default=0)
    strength: Mapped[str] = mapped_column(String(16), default="GOOD")
    regime: Mapped[str] = mapped_column(String(20), default="")
    mtf_alignment: Mapped[str] = mapped_column(String(16), default="NONE")
    quality_mode: Mapped[str] = mapped_column(String(16), default="BALANCED")

    entry: Mapped[float] = mapped_column(Float)
    entry_low: Mapped[float] = mapped_column(Float, default=0.0)
    entry_high: Mapped[float] = mapped_column(Float, default=0.0)
    sl: Mapped[float] = mapped_column(Float)
    tp1: Mapped[float] = mapped_column(Float)
    tp2: Mapped[float] = mapped_column(Float)
    tp3: Mapped[float] = mapped_column(Float)
    atr_value: Mapped[float] = mapped_column(Float, default=0.0)

    explanation: Mapped[str] = mapped_column(Text, default="")
    checks_json: Mapped[str] = mapped_column(Text, default="[]")

    # v81: MANBA — qaysi kanal, qaysi post, qachon tashlangan, asl matn va rasm matni.
    # (Baza eski bo'lsa ustunlar avtomatik qo'shiladi — _ensure_schema.)
    source_channel: Mapped[str] = mapped_column(String(160), default="")
    source_username: Mapped[str] = mapped_column(String(64), default="")
    source_msg_id: Mapped[int] = mapped_column(Integer, default=0)
    source_posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_text: Mapped[str] = mapped_column(Text, default="")
    source_ocr: Mapped[str] = mapped_column(Text, default="")

    # Natija
    result: Mapped[str | None] = mapped_column(String(16), nullable=True)
    r_multiple: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(24), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    candle_open_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    confirmations: Mapped[list["SignalConfirmation"]] = relationship(
        back_populates="signal", cascade="all, delete-orphan"
    )


class SignalConfirmation(Base):
    """Signalni tasdiqlagan (yoki rad etgan) har bir strategiya natijasi."""
    __tablename__ = "signal_confirmations"

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("signals.id", ondelete="CASCADE"), index=True
    )
    strategy_name: Mapped[str] = mapped_column(String(40), index=True)
    direction: Mapped[str] = mapped_column(String(8))  # BUY | SELL | NEUTRAL
    score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(Text, default="")
    indicators_json: Mapped[str] = mapped_column(Text, default="{}")

    signal: Mapped["Signal"] = relationship(back_populates="confirmations")
