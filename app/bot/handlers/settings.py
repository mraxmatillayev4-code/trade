"""Sozlamalar menyusi — oddiy pastki (reply) tugmalar bilan."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from app.bot import keyboards as kb
from app.core.enums import QualityMode
from app.database import crud
from app.database.session import async_session_factory

router = Router(name="settings")

_MODES = {"🟢 Aggressive": "AGGRESSIVE", "🟡 Balanced": "BALANCED", "🔴 Conservative": "CONSERVATIVE"}


class SettingsState(StatesGroup):
    menu = State()
    mode = State()


def _settings_text(us) -> str:
    mode = us.quality_mode if us else "BALANCED"
    try:
        threshold = QualityMode[mode].value
    except Exception:  # noqa: BLE001
        threshold = "?"
    return (
        "⚙️ <b>SOZLAMALAR</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        f"🎚 Joriy rejim: <b>{mode}</b> (chegara {threshold}+ ball)\n\n"
        "Pastdagi tugmalar bilan o'zgartiring 👇\n"
        "• <b>🎚 Rejim</b> — Aggressive / Balanced / Conservative\n"
        "• <b>Faqat kuchli signallar</b> — faqat yuqori sifatli signallar\n"
        "• <b>BUY / SELL xabarlari</b> — qaysi yo'nalishdagi signallar kelsin\n\n"
        "Avto-trade va balansni asosiy menyudagi\n"
        "🤖 Avto-trade va 💰 Balansni o'rnatish tugmalari boshqaradi."
    )


@router.message(F.text == "⚙️ Sozlamalar")
async def show_settings_message(message: Message, state) -> None:
    async with async_session_factory() as session:
        await crud.get_or_create_user(
            session, message.from_user.id, message.from_user.username, message.from_user.full_name
        )
        us = await crud.get_user_settings(session, message.from_user.id)
    await state.set_state(SettingsState.menu)
    await message.answer(
        _settings_text(us), parse_mode="HTML", reply_markup=kb.settings_reply(us)
    )


@router.message(SettingsState.menu, F.text.startswith("🎚 Rejim"))
async def choose_mode(message: Message, state) -> None:
    await state.set_state(SettingsState.mode)
    await message.answer(
        "🎚 Signal rejimini tanlang:\n"
        "• <b>Aggressive</b> — 6.0+ ball (ko'proq signal)\n"
        "• <b>Balanced</b> — 7.0+ ball (tavsiya etiladi)\n"
        "• <b>Conservative</b> — 8.5+ ball (kam, lekin kuchli)",
        parse_mode="HTML",
        reply_markup=kb.mode_reply(),
    )


@router.message(SettingsState.mode, F.text.in_(_MODES))
async def set_mode(message: Message, state) -> None:
    mode = _MODES[message.text]
    async with async_session_factory() as session:
        us = await crud.get_user_settings(session, message.from_user.id)
        if us:
            us.quality_mode = mode
            await session.commit()
        us = await crud.get_user_settings(session, message.from_user.id)
    await state.set_state(SettingsState.menu)
    await message.answer(
        f"✅ Rejim <b>{mode}</b> ga o'zgartirildi.",
        parse_mode="HTML",
        reply_markup=kb.settings_reply(us),
    )


@router.message(SettingsState.menu, F.text.startswith(("✅ Faqat kuchli", "⬜ Faqat kuchli")))
async def toggle_strong(message: Message, state) -> None:
    await _toggle_flag(message, state, "strong_only")


@router.message(SettingsState.menu, F.text.startswith(("✅ BUY xabarlari", "⬜ BUY xabarlari")))
async def toggle_buy(message: Message, state) -> None:
    await _toggle_flag(message, state, "notify_buy")


@router.message(SettingsState.menu, F.text.startswith(("✅ SELL xabarlari", "⬜ SELL xabarlari")))
async def toggle_sell(message: Message, state) -> None:
    await _toggle_flag(message, state, "notify_sell")


async def _toggle_flag(message: Message, state, field: str) -> None:
    async with async_session_factory() as session:
        us = await crud.get_user_settings(session, message.from_user.id)
        if us:
            setattr(us, field, not getattr(us, field))
            await session.commit()
        us = await crud.get_user_settings(session, message.from_user.id)
    await state.set_state(SettingsState.menu)
    await message.answer(_settings_text(us), parse_mode="HTML", reply_markup=kb.settings_reply(us))


@router.message(SettingsState.mode, F.text == "⬅️ Orqaga")
async def mode_back(message: Message, state) -> None:
    async with async_session_factory() as session:
        us = await crud.get_user_settings(session, message.from_user.id)
    await state.set_state(SettingsState.menu)
    await message.answer(_settings_text(us), parse_mode="HTML", reply_markup=kb.settings_reply(us))


@router.message(SettingsState.menu, F.text == "⬅️ Orqaga")
async def settings_back(message: Message, state) -> None:
    await state.clear()
    await message.answer(
        "🏠 <b>Siz asosiy menyuga qaytdingiz.</b>\nPastdan bo'limni tanlang 👇",
        parse_mode="HTML",
        reply_markup=kb.main_menu_reply(message.from_user.id if message.from_user else None),
    )
