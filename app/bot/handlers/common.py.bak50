"""Asosiy menyu va /start."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, Filter
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards as kb
from app.bot.texts import ABOUT, MENU_READY, WELCOME

router = Router(name="common")

_SKIP_LOGIN = {
    "⬅️ Orqaga",
    "📡 Kanallar",
    "➕ Qo'shish",
    "➖ O'chirish",
    "🔎 Holat",
    "👤 Akkaunt",
    "🔥 Signallar",
    "📊 Bozor",
    "📚 Strategiyalar",
    "📈 Statistika",
    "💼 Hisob (paper)",
    "🗓 Hisobotlar",
    "💰 Balansni o'rnatish",
    "🤖 Avto-trade: yoqish/o'chirish",
    "⚙️ Sozlamalar",
    "ℹ️ Ma'lumot",
}


def _cancel_login(user_id: int | None) -> None:
    if not user_id:
        return
    try:
        from app.bot.handlers.channels import _login_tmp
        _login_tmp.pop(user_id, None)
    except Exception:  # noqa: BLE001
        pass


class _AccountFlow(Filter):
    """Faqat akkaunt wizard matni. /start, Orqaga, menyu tugmalari yutilmasin."""

    async def __call__(self, message: Message) -> bool:
        if message.from_user is None or not (message.text or "").strip():
            return False
        if getattr(message, "forward_origin", None) or getattr(message, "forward_from_chat", None):
            return False
        from app.core.access import is_admin
        if not is_admin(message.from_user.id):
            return False
        t = message.text.strip()
        low = t.lower()
        if t in _SKIP_LOGIN:
            return False
        if t.startswith("/") and not low.startswith("/akkaunt"):
            return False
        if "akkaunt" in low:
            return True
        try:
            from app.bot.handlers.channels import _login_tmp
            step = (_login_tmp.get(message.from_user.id) or {}).get("step")
        except Exception:  # noqa: BLE001
            step = None
        return bool(step)


@router.message(_AccountFlow())
async def account_flow_first(message: Message, state) -> None:
    from app.bot.handlers.channels import _login_tmp, account_start, account_wizard
    t = (message.text or "").strip()
    if "akkaunt" in t.lower():
        await account_start(message, state)
        return
    uid = message.from_user.id
    if not (_login_tmp.get(uid) or {}).get("step"):
        _login_tmp[uid] = {"step": "api_id"}
    await account_wizard(message, state)


@router.message(CommandStart())
async def cmd_start(message: Message, state) -> None:
    uid = message.from_user.id if message.from_user else None
    _cancel_login(uid)
    await state.clear()
    from app.core.access import claim_admin
    admin = await claim_admin(uid)
    if uid:
        try:
            from app.paper_trading.engine import PaperEngine
            from app.database.session import async_session_factory
            async with async_session_factory() as session:
                await PaperEngine().get_account(session, uid)
        except Exception:  # noqa: BLE001
            pass
    extra = ""
    if admin:
        extra = (
            "\n🔑 Siz <b>adminsiz</b>: 📡 Kanallar, akkaunt, holat.\n"
            "Oddiy user faqat signal/hisob/hisobotni ko'radi.\n"
        )
    await message.answer(
        MENU_READY + extra +
        "\n🤖 Avto-trade <b>yoqilgan</b> — yangi signallar virtual hisobda ochiladi.",
        parse_mode="HTML",
        reply_markup=kb.main_menu_reply(uid),
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message, state) -> None:
    """Klaviatura yig'ilib qolgan bo'lsa: /menu qayta ochadi."""
    _cancel_login(message.from_user.id if message.from_user else None)
    await state.clear()
    uid = message.from_user.id if message.from_user else None
    await message.answer(
        "🏠 Siz asosiy menyuga qaytdingiz.\nPastdan bo'limni tanlang 👇",
        parse_mode="HTML",
        reply_markup=kb.main_menu_reply(uid),
    )


@router.callback_query(F.data == "menu:reopen")
async def reopen_menu(callback: CallbackQuery) -> None:
    """Yig'ilgan klaviaturani qayta ochadi."""
    try:
        await callback.message.delete()
    except Exception:  # noqa: BLE001
        pass
    await callback.message.answer(
        "☰ Menyu ochildi. Bo'limni pastdan tanlang 👇",
        reply_markup=kb.main_menu_reply(callback.from_user.id if callback.from_user else None),
    )
    await callback.answer()


@router.message(F.text == "ℹ️ Ma'lumot")
async def about_message(message: Message) -> None:
    await message.answer(ABOUT, parse_mode="HTML")


@router.callback_query(F.data == "msg:delete")
async def delete_message(callback: CallbackQuery) -> None:
    try:
        await callback.message.delete()
    except Exception:  # noqa: BLE001
        pass
    await callback.answer()


@router.callback_query(F.data == "menu:main")
async def show_main(callback: CallbackQuery) -> None:
    await callback.message.edit_text(WELCOME, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "menu:about")
async def show_about(callback: CallbackQuery) -> None:
    await callback.message.edit_text(ABOUT, reply_markup=kb.back_to_menu(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "menu:back")
async def generic_back(callback: CallbackQuery) -> None:
    await callback.message.edit_text(WELCOME, parse_mode="HTML")
    await callback.answer()
