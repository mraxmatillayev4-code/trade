"""v84: Bot/engine sozlamalari (kalit — qiymat) bazada saqlanadi.

Nima uchun kerak: `/kirish` buyrug'i bilan kutish muddati va qarama-qarshi
tomonga o'tish tanaffusini o'zgartirish mumkin. Render qayta ishga tushsa ham
sozlama yo'qolmasin (bazada turadi, zaxira fayliga ham tushadi).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(48), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
