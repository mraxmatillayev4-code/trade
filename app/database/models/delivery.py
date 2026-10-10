"""UserDelivery — v98: kimga qaysi signal kartasi yuborilganini yuritadi.

Maqsadlar:
  * TRIAL: har /start bosgan user (bazaga BIR marta yozilgan) har 2 kunda
    1 bepul signal oladi — oxirgi yuborilish vaqti shu jadvalda;
  * signal natijasi ham shu userlarga boradi (signal_id bo'yicha topiladi);
  * «📊 Mening hisobim»: nechta signal olgan, nechtasi g'alaba, jami foyda (pip).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class UserDelivery(Base):
    __tablename__ = "user_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    signal_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(8), default="FULL")  # FULL | TRIAL
    delivered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        index=True)
    result_pips: Mapped[float | None] = mapped_column(
        Float, nullable=True, default=None)
    win: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
