"""Signal deduplikatsiyasi — bir xil signal qayta-qayta yuborilmaydi."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import Direction
from app.database import crud


async def is_signal_allowed(session: AsyncSession, symbol: str, timeframe: str,
                           direction: Direction, settings: Settings) -> tuple[bool, str]:
    """
    Qoidalar:
    - Xuddi shu symbol+tf+yo'nalish bo'yacha OCHIQ signal bo'lsa → RAD.
    - Qarshi yo'nalishda ochiq signal bo'lsa → RUXSAT (flip, eskisi bekor qilinadi).
    - Xuddi shu yo'nalishdagi oxirgi signal cooldown ichida BEKOR/EXPIRED
      bo'lgan bo'lsa → RAD (chop bozorida spam bo'lmasin).
    - TP3/SL bilan yopilgan signaldan keyin yangi setup → RUXSAT.
    """
    open_same = await crud.get_open_signal(session, symbol, timeframe, direction.value)
    if open_same is not None:
        return False, "Xuddi shu yo'nalishda ochiq signal mavjud"

    last = await crud.get_last_signal(session, symbol, timeframe)
    if last is not None and last.direction == direction.value and not last.is_active:
        cooldown = timedelta(minutes=settings.signal_cooldown_minutes)
        age = datetime.now(timezone.utc) - last.created_at
        if age < cooldown and last.result in (None, "EXPIRED", "CANCELLED", "BREAKEVEN"):
            return False, f"Cooldown: {int((cooldown - age).total_seconds() // 60)} daqiqa qoldi"

    return True, ""
