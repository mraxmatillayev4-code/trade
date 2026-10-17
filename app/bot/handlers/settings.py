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

# v86: LOT HAJMI — risk foizi OLIB TASHLANDI, foydalanuvchi o'zi tanlaydi.
# Tugma yozuvi "📦 X lot" ko'rinishida bo'ladi (qiymat = HAR BIR lot hajmi).
def _lot_buttons() -> dict:
    from app.services import lot_settings as _LS
    return {_LS.btn_label(c): c for c in _LS.LOT_CHOICES}


_LOTS = _lot_buttons()



class SettingsState(StatesGroup):
    menu = State()
    mode = State()
    lot = State()        # v86: lot hajmi (risk foizidan keyin)
    risk = State()       # eski nom saqlanadi (zaxira mosligi uchun)
    entry = State()      # v84: kirish nuqtasi sozlamalari


async def _get_us(session, uid: int):
    """UserSettings + tanlangan LOT hajmini birga oladi (v86)."""
    us = await crud.get_user_settings(session, uid)
    try:
        from app.services import lot_settings as _LS
        setattr(us, "lot_size", await _LS.get(session, uid))
    except Exception:  # noqa: BLE001
        pass
    return us


def _risk_pct(us) -> float:
    """v86: endi bu — foydalanuvchi tanlagan LOT hajmi (nomi eski qoldi)."""
    try:
        from app.services import lot_settings as _LS
        v = getattr(us, "lot_size", None) if us is not None else None
        return _LS.clean(v) if v else _LS.default_lot()
    except Exception:  # noqa: BLE001
        return 0.01


def _settings_text(us) -> str:
    mode = us.quality_mode if us else "BALANCED"
    try:
        threshold = QualityMode[mode].value
    except Exception:  # noqa: BLE001
        threshold = "?"
    import html as _h
    lot = _risk_pct(us)
    return (
        "⚙️ <b>SOZLAMALAR</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        f"🎚 Joriy rejim: <b>{mode}</b> (chegara {threshold}+ ball)\n"
        f"📦 Lot hajmi (siz tanlagan): <b>{lot:,.2f} lot</b> — "
        "har bir lot shunday, jami 2 lot\n\n"
        "Pastdagi tugmalar bilan o'zgartiring 👇\n"
        "• <b>📦 Lot</b> — necha lotdan ochilishini O'ZINGIZ belgilaysiz\n"
        "• <b>🎚 Rejim</b> — Aggressive / Balanced / Conservative\n"
        "• <b>Faqat kuchli signallar</b> — faqat yuqori sifatli signallar\n"
        "• <b>BUY / SELL xabarlari</b> — qaysi yo'nalishdagi signallar kelsin\n\n"
        "❗ Risk foizi OLIB TASHLANDI — endi hajm hisoblanmaydi, siz "
        "tanlagan lot ochiladi.\n"
        "Misol: <b>0.01</b> tanlansa → Lot 1 = 0.01, Lot 2 = 0.01 (jami 0.02 lot)."
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


@router.message(SettingsState.menu, F.text.startswith("\U0001F4E6 Lot"))
async def choose_lot(message: Message, state) -> None:
    """v86: lot hajmini tanlash (risk foizi o'rniga)."""
    async with async_session_factory() as session:
        us = await _get_us(session, message.from_user.id)
    cur = _risk_pct(us)
    await state.set_state(SettingsState.lot)
    await message.answer(
        "\U0001F4E6 <b>LOT HAJMINI TANLANG</b>\n"
        "Bu — <b>har bir lot</b> hajmi. Bot har signalda 2 lot ochadi:\n"
        "  \u2022 Lot 1 \u2192 TP1 da yopiladi\n"
        "  \u2022 Lot 2 \u2192 TP2 da yopiladi\n\n"
        "Masalan <b>0.01</b> tanlasangiz: Lot 1 = 0.01 va Lot 2 = 0.01 "
        "(jami 0.02 lot).\n"
        "1 lot = 100 untsiya \u2192 0.01 lotda 1$ narx harakati = <b>1$</b>.\n\n"
        f"Joriy: <b>{cur:,.2f} lot</b>",
        parse_mode="HTML",
        reply_markup=kb.risk_reply(cur),
    )


@router.message(SettingsState.lot, F.text.in_(tuple(_LOTS)))
async def set_lot_cb(message: Message, state) -> None:
    lot = _LOTS[message.text]
    async with async_session_factory() as session:
        from app.services import lot_settings as _LS
        saved = await _LS.set_lot(session, message.from_user.id, lot)
        us = await _get_us(session, message.from_user.id)
    await state.set_state(SettingsState.menu)
    _risk_money = "?"
    await message.answer(
        f"\u2705 Lot <b>{saved:,.2f}</b> qilib o'rnatildi.\n"
        f"<i>Endi har signalda Lot 1 = {saved:,.2f} va Lot 2 = {saved:,.2f} "
        f"(jami {saved * 2:,.2f} lot) ochiladi. Risk foizi ishlatilmaydi — "
        f"SL urilsa yo'qoladigan pul kartada $ da ko'rsatiladi.</i>",
        parse_mode="HTML",
        reply_markup=kb.settings_reply(us, risk=saved),
    )


@router.message(Command("lot"))
async def cmd_lot(message: Message, state) -> None:
    """v86: /lot — lot hajmini tez o'zgartirish (risk % o'rniga)."""
    async with async_session_factory() as session:
        us = await _get_us(session, message.from_user.id)
    cur = _risk_pct(us)
    await state.set_state(SettingsState.lot)
    await message.answer(
        f"\U0001F4E6 <b>LOT HAJMI</b> — joriy: <b>{cur:,.2f} lot</b>\n"
        "Har signalda 2 lot ochiladi (Lot 1 \u2192 TP1, Lot 2 \u2192 TP2).\n"
        "Risk foizi endi ishlatilmaydi — hajmni o'zingiz belgilaysiz.",
        parse_mode="HTML", reply_markup=kb.risk_reply(cur),
    )


# v86: eski /risk buyrug'i ham qoladi (lot oynasini ochadi — odamlar o'rganib qolgan)
@router.message(Command("risk"))
async def cmd_risk(message: Message, state) -> None:
    await cmd_lot(message, state)


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


# ================= v84: KIRISH NUQTASI (entry engine) =================
_ENTRY_WAIT = {f"\u23F1 Kutish {m} daqiqa": m for m in (15, 30, 60, 120)}
_ENTRY_COOL = {f"\U0001F6E1 Tanaffus {m} daqiqa": m for m in (0, 15, 30, 60)}


def _entry_text(vals: dict) -> str:
    on = bool(vals.get("entry_enabled", True))
    wait = int(vals.get("entry_wait_min", 30) or 30)
    cool = int(vals.get("entry_cool_min", 15) or 0)
    xato = "" if on else ""
    return (
        "\U0001F3AF <b>KIRISH NUQTASI</b> (entry engine)\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"Rejim: <b>{'YOQILGAN' if on else 'OCHIQ'}</b>\n"
        f"Kutish vaqti: <b>{wait} daqiqa</b>\n"
        f"Qarama-qarshi tomonga tanaffus: <b>{cool} daqiqa</b>\n"
        "\n<b>Nima qiladi:</b>\n"
        "\u2022 Signal kirish zonasini aytgan bo'lsa \u2014 bot hisoblamaydi, "
        "o'sha zona ishlatiladi.\n"
        "\u2022 Aytilmagan bo'lsa \u2014 bot bozor holatidan (5m/15m tayanch-"
        "qarshilik, EMA, diapazon) kirish nuqtasini o'zi hisoblaydi.\n"
        "\u2022 Narx o'sha zonaga KELGANDAGINA savdo ochiladi. Kelmasa \u2014 "
        "signal BEKOR, savdo ochilmaydi (0$ zarar, narx quvilmaydi).\n"
        "\u2022 Stop loss har doim qoladi (signal bersa o'sha, bermasa bot "
        "tuzilmadan hisoblaydi).\n"
        "\u2022 0.01 lot bilan ham risk balansning risk % idan oshsa \u2014 "
        "savdo ochilmaydi.\n"
        f"{xato}"
    )


@router.message(Command("kirish"))
async def cmd_entry(message: Message, state) -> None:
    """v84: /kirish — kirish nuqtasi rejimi va kutish muddati."""
    from app.services import entry_settings as ES
    async with async_session_factory() as session:
        vals = await ES.load(session)
    await state.set_state(SettingsState.entry)
    await message.answer(_entry_text(vals), parse_mode="HTML",
                         reply_markup=kb.entry_reply(vals))


@router.message(SettingsState.entry,
                F.text.startswith(("\U0001F535 Kirish rejimi", "\u26AA Kirish rejimi")))
async def toggle_entry_mode(message: Message, state) -> None:
    from app.services import entry_settings as ES
    async with async_session_factory() as session:
        vals = await ES.load(session)
        new = not bool(vals.get(ES.K_ENABLED, True))
        vals = await ES.save(session, **{ES.K_ENABLED: new})
    await state.set_state(SettingsState.entry)
    await message.answer(
        ("\U0001F3AF Kirish rejimi <b>YOQILGAN</b> \u2014 endi savdo faqat narx "
         "hisoblangan zonaga kelganda ochiladi."
         if new else
         "\u26A0\ufe0f Kirish rejimi <b>OCHIQ</b> \u2014 savdo signal kelishi "
         "bilan darhol bozordan ochiladi (eski xatti-harakat)."),
        parse_mode="HTML", reply_markup=kb.entry_reply(vals))


@router.message(SettingsState.entry, F.text.in_(tuple(_ENTRY_WAIT)))
async def set_entry_wait(message: Message, state) -> None:
    from app.services import entry_settings as ES
    m = _ENTRY_WAIT[message.text]
    async with async_session_factory() as session:
        vals = await ES.save(session, **{ES.K_WAIT: m})
    await message.answer(
        f"\u23F1 Kutish vaqti <b>{m} daqiqa</b>. Narx shu vaqt ichida kelmasa "
        "\u2014 signal bekor qilinadi (savdo ochilmaydi).",
        parse_mode="HTML", reply_markup=kb.entry_reply(vals))


@router.message(SettingsState.entry, F.text.in_(tuple(_ENTRY_COOL)))
async def set_entry_cool(message: Message, state) -> None:
    from app.services import entry_settings as ES
    m = _ENTRY_COOL[message.text]
    async with async_session_factory() as session:
        vals = await ES.save(session, **{ES.K_COOL: m})
    txt = (f"\U0001F6E1 Tanaffus <b>{m} daqiqa</b>: bir yo'nalishda STOP bo'lsa, "
           "shu vaqt ichida teskari yo'nalishdagi signal olinmaydi (flip-flop "
           "himoyasi)." if m else
           "\U0001F6E1 Flip-flop tanaffusi <b>o'chirildi</b> (0 daqiqa).")
    await message.answer(txt, parse_mode="HTML", reply_markup=kb.entry_reply(vals))


@router.message(SettingsState.entry, F.text == "\u2B05\uFE0F Orqaga")
async def entry_back(message: Message, state) -> None:
    async with async_session_factory() as session:
        us = await _get_us(session, message.from_user.id)
    await state.set_state(SettingsState.menu)
    await message.answer(_settings_text(us), parse_mode="HTML",
                         reply_markup=kb.settings_reply(us))
