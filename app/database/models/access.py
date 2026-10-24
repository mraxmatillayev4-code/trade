"""AccessUser ORM modeli (v95 whitelist, v97 limit)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, String, select
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class AccessUser(Base):
    """Signal yuboriladigan foydalanuvchi ID lari (admin buyrug'i bilan)."""

    __tablename__ = "access_users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    added_by: Mapped[int] = mapped_column(BigInteger, default=0)
    # v97: LIMIT — YOKI signal soni YOKI kun soni (ikkalasi bir vaqtda EMAS).
    # 0 = cheksiz. Kun limiti FAQAT signal berilgan kunlarni hisoblaydi:
    # signal bo'lmagan kun days_used ga qo'shilmaydi.
    max_signals: Mapped[int] = mapped_column(default=0)   # nechta signal
    used_signals: Mapped[int] = mapped_column(default=0)  # nechtasi yuborildi
    max_days: Mapped[int] = mapped_column(default=0)      # nechta SIGNAL KUNI
    days_used: Mapped[int] = mapped_column(default=0)     # necha kun hisoblandi
    last_day: Mapped[str | None] = mapped_column(         # oxirgi hisoblangan kun
        String(10), nullable=True, default=None)
