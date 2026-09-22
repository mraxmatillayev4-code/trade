"""Sozlamalar menyusi — oddiy pastki (reply) tugmalar bilan."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from app.bot import keyboards as kb
from app.core.enums import QualityMode
from app.database import crud
from app.database.session import async_session_factory

router = Router(name="settings")

_MODES = {"🟢 Aggressive": "AGGRESSIVE", "🟡 Balanced": "BALANCED", "🔴 Conservative": "CONSERVATIVE"}

# v82: risk/money management — hajm balansning shu foizidan hisoblanadi
_RISKS = {
    "⚖️ Risk 0.5%": 0.5,
    "⚖️ Risk 1%": 1.0,
    "⚖️ Risk 2%": 2.0,
}



class SettingsState(StatesGroup):
    menu = State()
    mode = State()
    risk = State()


async def _get_us(session, uid: int):
    """UserSettings + hisobdagi risk foizini birga oladi (v82)."""
    us = await crud.get_user_settings(session, uid)
    try:
        from sqlalchemy import select as _sel
        from app.database.models.paper import PaperAccount
        acc = (await session.execute(_sel(PaperAccount).where(
            PaperAccount.user_id == uid))).scalars().first()
        if acc is not None and acc.risk_percent:
            setattr(us, "risk_percent", float(acc.risk_percent))
    except Exception:  # noqa: BLE001
        pass
    return us


def _risk_pct(us) -> float:
    """v82: foydalanuvchining risk foizi (yoki umumiy standart)."""
    try:
        from app.core.config import get_settings
        d = float(getattr(get_settings(), "risk_percent", 0.5) or 0.5)
    except Exception:  # noqa: BLE001
        d = 0.5
    v = getattr(us, "risk_percent", None) if us is not None else None
    try:
        return float(v) if v else d
    except (TypeError, ValueError):
        return d


def _settings_text(us) -> str:
    mode = us.quality_mode if us else "BALANCED"
    try:
        threshold = QualityMode[mode].value
    except Exception:  # noqa: BLE001
        threshold = "?"
    import html as _h
    risk = _risk_pct(us)
    risks = {0.5: "0.5%", 1.0: "1%", 2.0: "2%"}
    return (
        "⚙️ <b>SOZLAMALAR</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        f"🎚 Joriy rejim: <b>{mode}</b> (chegara {threshold}+ ball)\n"
        f"⚖️ Risk (money management): <b>{risks.get(risk, f'{risk:g}%')}</b> — "
        "hajm shu foizdan hisoblanadi\n\n"
        "Pastdagi tugmalar bilan o'zgartiring 👇\n"
        "• <b>⚖️ Risk</b> — 0.5% / 1% / 2% (balansning qanchasi riskda)\n"
        "• <b>🎚 Rejim</b> — Aggressive / Balanced / Conservative\n"
        "• <b>Faqat kuchli signallar</b> — faqat yuqori sifatli signallar\n"
        "• <b>BUY / SELL xabarlari</b> — qaysi yo'nalishdagi signallar kelsin\n\n"
        "Misol: balans 1000$ · risk 0.5% = <b>5$</b> — stop urilsa shu pul ketadi,"
        "\nhajm esa stop masofasiga qarab o'zi hisoblanadi."
    )


@router.message(F.text == "⚙️ Sozlamalar")
async def show_settings_message(message: Message, state) -> None:
    async with async_session_factory() as session:
        await crud.get_or_create_user(
            session, message.from_user.id, message.from_user.username, message.from_user.full_name
        )
        us = await _get_us(session, message.from_user.id)
    await state.set_state(SettingsState.menu)
    await message.answer(
        _settings_text(us), parse_mode="HTML", reply_markup=kb.settings_reply(us)
    )


@router.message(SettingsState.menu, F.text.startswith("⚖️ Risk"))
async def choose_risk(message: Message, state) -> None:
    async with async_session_factory() as session:
        us = await _get_us(session, message.from_user.id)
    cur = _risk_pct(us)
    await state.set_state(SettingsState.risk)
    await message.answer(
        "⚖️ <b>Risk foizini tanlang</b>\n"
        "Bu — balansning qanchasi riskda bo'lishi (lot hajmi shundan hisoblanadi):\n"
        "• <b>0.5%</b> — ehtiyotkor (tavsiya)\n"
        "• <b>1%</b> — o'rtacha\n"
        "• <b>2%</b> — agressiv\n\n"
        f"Joriy: <b>{cur:g}%</b>",
        parse_mode="HTML",
        reply_markup=kb.risk_reply(),
    )


@router.message(SettingsState.risk, F.text.in_(tuple(_RISKS)))
async def set_risk(message: Message, state) -> None:
    pct = _RISKS[message.text]
    async with async_session_factory() as session:
        us = await _get_us(session, message.from_user.id)
        if us:
            # UserSettings da risk ustuni yo'q — hisob (PaperAccount)ga yozamiz
            try:
                from app.database.models.paper import PaperAccount
                from sqlalchemy import select as _sel
                acc = (await session.execute(_sel(PaperAccount).where(
                    PaperAccount.user_id == message.from_user.id))).scalars().first()
                if acc is None:
                    acc = PaperAccount(user_id=message.from_user.id,
                                       initial_balance=1000.0, balance=1000.0)
                    session.add(acc)
                acc.risk_percent = float(pct)
                await session.commit()
            except Exception as exc:  # noqa: BLE001
                from app.core.logging import get_logger
                get_logger(__name__).warning("[SET] risk: %s", exc)
    async with async_session_factory() as session:
        us = await _get_us(session, message.from_user.id)
    await state.set_state(SettingsState.menu)
    await message.answer(
        f"✅ Risk <b>{pct:g}%</b> qilib o'rnatildi.\n"
        "<i>Endi har yangi signalda hajm shu foizdan hisoblanadi.</i>",
        parse_mode="HTML",
        reply_markup=kb.settings_reply(us),
    )


@router.message(Command("risk"))
async def cmd_risk(message: Message, state) -> None:
    """v82: /risk — risk foizini tez o'zgartirish."""
    async with async_session_factory() as session:
        us = await _get_us(session, message.from_user.id)
    cur = _risk_pct(us)
    await state.set_state(SettingsState.risk)
    await message.answer(
        f"⚖️ <b>Risk (money management)</b> — joriy: <b>{cur:g}%</b>\n"
        "Hajm har signalda balans va stop masofasidan hisoblanadi.",
        parse_mode="HTML", reply_markup=kb.risk_reply(),
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
        us = await _get_us(session, message.from_user.id)
        if us:
            us.quality_mode = mode
            await session.commit()
        us = await _get_us(session, message.from_user.id)
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
        us = await _get_us(session, message.from_user.id)
        if us:
            setattr(us, field, not getattr(us, field))
            await session.commit()
        us = await _get_us(session, message.from_user.id)
    await state.set_state(SettingsState.menu)
    await message.answer(_settings_text(us), parse_mode="HTML", reply_markup=kb.settings_reply(us))


@router.message(SettingsState.risk, F.text == "⬅️ Orqaga")
async def risk_back(message: Message, state) -> None:
    async with async_session_factory() as session:
        us = await _get_us(session, message.from_user.id)
    await state.set_state(SettingsState.menu)
    await message.answer(_settings_text(us), parse_mode="HTML",
                         reply_markup=kb.settings_reply(us))


@router.message(SettingsState.mode, F.text == "⬅️ Orqaga")
async def mode_back(message: Message, state) -> None:
    async with async_session_factory() as session:
        us = await _get_us(session, message.from_user.id)
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
