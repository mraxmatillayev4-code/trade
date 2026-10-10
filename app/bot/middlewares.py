"""Middleware — har bir foydalanuvchini avtomatik ro'yxatga olish (bot ochiq)."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject, User

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

            # v95/v98: ADMIN MASYUSI faqat adminga. Ro'yxatdagi oddiy user
            # faqat: /start, «📊 Mening hisobim», «📞 Admin bilan bog'lanish».
            # Begona user faqat /start (kontakt tugma ko'rsatiladi).
            from app.core.access import is_admin as _is_adm
            if not _is_adm(user.id):
                txt = ""
                msg = event if isinstance(event, Message) else None
                if msg is not None:
                    txt = (msg.text or msg.caption or "").strip()
                _ok_txt = txt.startswith("/start")
                if not _ok_txt and msg is not None and txt in (
                        "\U0001F4CA Mening hisobim",
                        "\U0001F4DE Admin bilan bog'lanish"):
                    # v98: ro'yxatdagi user uchun shaxsiy tugmalar ochiq
                    try:
                        from app.services import access as _ACC98
                        async with async_session_factory() as _s98:
                            _ok_txt = await _ACC98.is_allowed(
                                _s98, get_settings(), user.id)
                    except Exception:  # noqa: BLE001
                        _ok_txt = False
                if not _ok_txt:
                    try:
                        from app.bot.keyboards import contact_admin_kb
                        bot = data.get("bot")
                        if bot is not None:
                            if msg is not None:
                                await bot.send_message(
                                    user.id,
                                    "\u26D4\uFE0F Buyruqlar yopiq. Signallar faqat "
                                    "ro\u2018yxatdagi ID larga yuboriladi.\n"
                                    "Savollar uchun adminga yozing:",
                                    reply_markup=contact_admin_kb())
                            else:
                                await bot.send_message(
                                    user.id,
                                    "\u26D4\uFE0F Buyruqlar yopiq. Adminga yozing:",
                                    reply_markup=contact_admin_kb())
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("[ACCESS] blok javobi: %s", exc)
                    return None

        return await handler(event, data)
