"""Hisobotlar — kunlik / haftalik / oylik / sana / TO'LIQ batafsil hisobot."""
from __future__ import annotations

import asyncio
from datetime import date as _date

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.state import State, StatesGroup, default_state
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards as kb
from app.core.logging import get_logger
from app.database.session import async_session_factory
from app.services.reports import (
    build_full_report,
    parse_date_input,
    report_on_demand,
)

router = Router(name="reports")
logger = get_logger(__name__)

_PERIOD_LABEL = {"daily": "📅 KUNLIK HISOBOT", "weekly": "🗓 HAFTALIK HISOBOT",
                 "monthly": "📆 OYLIK HISOBOT"}
_BTN_PERIOD = {
    "📅 Kunlik hisobot": "daily",
    "🗓 Haftalik hisobot": "weekly",
    "📆 Oylik hisobot": "monthly",
}


class ReportsState(StatesGroup):
    menu = State()
    awaiting_date = State()


def _parse_token(token: str) -> tuple[str, _date | None, str]:
    """'daily' | 'weekly' | 'monthly' | 'date:YYYY-MM-DD' -> (period, target_date, label)."""
    if token.startswith("date:"):
        d = parse_date_input(token.split(":", 1)[1])
        return "daily", d, (f"🔎 {d.strftime('%d.%m.%Y')} HISOBOTI" if d else "SANA")
    period = token if token in _PERIOD_LABEL else "daily"
    return period, None, _PERIOD_LABEL[period]


async def _answer_reports(text_builder, user_id: int, message: Message | None,
                          cq: CallbackQuery | None, markup) -> None:
    """Hisobot matnini qurib, yangi xabar yoki inline-tahrir orqali ko'rsatadi."""
    if cq is not None:
        try:
            await cq.answer()
        except Exception:  # noqa: BLE001
            pass
    try:
        async with async_session_factory() as session:
            text = await asyncio.wait_for(text_builder(session, user_id), timeout=12)
    except asyncio.TimeoutError:
        logger.error("Hisobot timeout")
        text = "⚠️ Hisobot uzoq davom etdi. Qayta bosing — kanal sonlari saqlanadi."
        if cq is not None:
            try:
                await cq.message.answer(text, reply_markup=kb.reports_reply())
            except Exception:  # noqa: BLE001
                pass
        elif message is not None:
            await message.answer(text, reply_markup=kb.reports_reply())
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("Hisobot tuzishda xato: %s", exc)
        if cq is not None:
            try:
                await cq.message.answer("⚠️ Hisobot tayyorlanmadi.", reply_markup=kb.reports_reply())
            except Exception:  # noqa: BLE001
                pass
        elif message is not None:
            await message.answer("⚠️ Hisobot hozircha tayyorlanmadi.", reply_markup=kb.reports_reply())
        return
    if cq is not None:
        try:
            await cq.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
        except Exception:  # noqa: BLE001 — matn bir xil bo'lsa
            try:
                await cq.message.answer(text, parse_mode="HTML", reply_markup=markup)
            except Exception:  # noqa: BLE001
                pass
    elif message is not None:
        await message.answer(text, parse_mode="HTML", reply_markup=markup)


@router.message(F.text == "🗓 Hisobotlar")
async def reports_menu_message(message: Message, state) -> None:
    await state.set_state(ReportsState.menu)
    await message.answer(
        "🗓 <b>HISOBOTLAR</b>\nQaysi davr hisobotini ko'rsatay? 👇\n\n"
        "🔎 <b>Sana bo'yicha</b> — aniq kunni <b>KK.OO.YYYY</b> da kiriting.\n"
        "📊 Hisobot ostidagi <b>To'liq hisobot</b> tugmasi — batafsil tahlil.",
        parse_mode="HTML", reply_markup=kb.reports_reply(),
    )


@router.message(F.text.in_(_BTN_PERIOD))
async def report_period(message: Message, state) -> None:
    await state.set_state(ReportsState.menu)
    period = _BTN_PERIOD[message.text]
    await _answer_reports(
        lambda sess, uid, p=period: report_on_demand(sess, p, user_id=uid),
        message.from_user.id, message, None, kb.report_summary_inline(period),
    )


@router.message(F.text == "🔎 Sana bo'yicha")
async def ask_for_date(message: Message, state) -> None:
    await state.set_state(ReportsState.awaiting_date)
    await message.answer(
        "🔎 Qaysi kunning natijasini ko'rasiz?\n\nSanani <b>KK.OO.YYYY</b> ko'rinishida yozing.\n"
        "Masalan: <code>08.09.2026</code>\n\nBekor: ⬅️ Orqaga.",
        parse_mode="HTML", reply_markup=kb.reports_reply(),
    )


@router.message(ReportsState.awaiting_date, F.text == "⬅️ Orqaga")
async def date_cancel(message: Message, state) -> None:
    await state.set_state(ReportsState.menu)
    await message.answer("🗓 Hisobotlar menyusi. Davrni tanlang 👇",
                         reply_markup=kb.reports_reply())


@router.message(ReportsState.awaiting_date, F.text)
async def report_for_date(message: Message, state) -> None:
    raw = (message.text or "").strip()
    if raw in _BTN_PERIOD:
        await state.set_state(ReportsState.menu)
        period = _BTN_PERIOD[raw]
        await _answer_reports(
            lambda sess, uid, p=period: report_on_demand(sess, p, user_id=uid),
            message.from_user.id, message, None, kb.report_summary_inline(period),
        )
        return
    target = parse_date_input(message.text)
    if target is None:
        await message.answer(
            "⚠️ Sana noto'g'ri. <b>KK.OO.YYYY</b> ko'rinishida kiriting (masalan: <code>08.09.2026</code>).",
            parse_mode="HTML", reply_markup=kb.reports_reply(),
        )
        return
    await state.set_state(ReportsState.menu)
    wait = await message.answer(f"🔎 {target.strftime('%d.%m.%Y')} hisoboti tayyorlanmoqda...")
    try:
        await wait.delete()
    except Exception:  # noqa: BLE001
        pass
    token = f"date:{target.isoformat()}"
    await _answer_reports(
        lambda sess, uid: report_on_demand(sess, "daily", user_id=uid, target_date=target),
        message.from_user.id, message, None, kb.report_summary_inline(token),
    )


@router.message(StateFilter(ReportsState.menu, default_state), F.text == "⬅️ Orqaga")
async def reports_back(message: Message, state) -> None:
    await state.clear()
    await message.answer(
        "🏠 <b>Asosiy menyuga qaytdingiz.</b>\nPastdan bo'limni tanlang 👇",
        parse_mode="HTML",
        reply_markup=kb.main_menu_reply(message.from_user.id if message.from_user else None),
    )


# ---------- INLINE: to'liq hisobot <-> qisqa hisobot ----------
@router.callback_query(F.data.startswith("rep:full:"))
async def show_full_report(cq: CallbackQuery) -> None:
    token = cq.data.split(":", 2)[2]
    period, target, _ = _parse_token(token)
    await _answer_reports(
        lambda sess, uid: build_full_report(sess, period, user_id=uid, target_date=target),
        cq.from_user.id, None, cq, kb.report_full_inline(token),
    )


@router.callback_query(F.data.startswith("rep:back:"))
async def back_to_summary(cq: CallbackQuery) -> None:
    token = cq.data.split(":", 2)[2]
    period, target, _ = _parse_token(token)
    await _answer_reports(
        lambda sess, uid: report_on_demand(sess, period, user_id=uid, target_date=target),
        cq.from_user.id, None, cq, kb.report_summary_inline(token),
    )
