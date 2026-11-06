"""Middleware — har bir foydalanuvchini avtomatik ro'yxatga olish (bot ochiq)."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from app.core.config import get_settings
from app.core.logging import get_logger
from app.database import crud
from app.database.session import async_session_factory

logger = get_logger(__name__)


class AccessMiddleware(BaseMiddleware):
    """Bot hamma uchun OCHIQ: start bosgan har bir foydalanuvchi ro'yxatga olinadi.
    Admin ID lar faqat tizim xatolari va hisobotlarni olish uchun ishlatiladi."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")

        if user is not None and not user.is_bot:
            try:
                async with async_session_factory() as session:
                    await crud.get_or_create_user(
                        session, user.id, user.username, user.full_name
                    )
            except Exception as exc:  # noqa: BLE001
                logger.error("Foydalanuvchi ro'yxatga olish xatosi: %s", exc)

        return await handler(event, data)
