"""Signallar menyusi."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards as kb
from app.core.symbols import full_label
from app.core.timeuz import format_short
from app.database import crud
from app.database.session import async_session_factory
from app.notifications.telegram import fmt_price, format_signal_full, format_signal_short

router = Router(name="signals")

STATUS_UZ = {
    "ACTIVE": "✅ Faol", "CREATED": "✅ Faol",
    "TP1_HIT": "🎯 TP1", "TP2_HIT": "🎯 TP2",
    "TP3_HIT": "🏁 TP3 (yutuq)", "SL_HIT": "🛑 SL",
    "EXPIRED": "⏳ Tugagan", "CANCELLED": "❌ Bekor",
}


async def _render_signals(filter_key: str) -> str:
    async with async_session_factory() as session:
        signals = await crud.get_recent_signals(
            session, limit=10,
            direction=filter_key if filter_key in ("BUY", "SELL") else None,
            strong_only=(filter_key == "STRONG"),
        )
    if not signals:
        return "🔥 <b>Signallar</b>\n━━━━━━━━━━━━━━━━\nHozircha signallar yo'q."
    lines = ["🔥 <b>So'nggi signallar</b>", "━━━━━━━━━━━━━━━━"]
    for s in signals:
        icon = "🟢" if s.direction == "BUY" else "🔴"
        pair = full_label(s.symbol)
        r = (f" ({s.r_multiple:+.2f}R \u00B7 2 lot o'rtachasi)"
             if s.r_multiple is not None else "")
        lines.append(
            f"{icon} <b>{pair}</b> {s.timeframe.upper()} • "
            f"{s.score:.1f}/10 • {STATUS_UZ.get(s.status, s.status)}{r}\n"
            f"   Kirish: {fmt_price(s.entry)} | "
            f"{format_short(s.created_at)}"
        )
    return "\n".join(lines)


@router.callback_query(F.data == "menu:signals")
async def show_signals(callback: CallbackQuery) -> None:
    text = await _render_signals("all")
    await callback.message.edit_text(
        text, reply_markup=kb.signals_menu(), parse_mode="HTML"
    )
    await callback.answer()


@router.message(F.text == "🔥 Signallar")
async def show_signals_message(message: Message) -> None:
    text = await _render_signals("all")
    await message.answer(text, parse_mode="HTML")


@router.callback_query(F.data.startswith("sig:filter:"))
async def filter_signals(callback: CallbackQuery) -> None:
    key = callback.data.split(":")[-1]
    text = await _render_signals(key)
    await callback.message.edit_text(
        text, reply_markup=kb.signals_menu(), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sig:why:"))
async def explain(callback: CallbackQuery) -> None:
    signal_id = int(callback.data.split(":")[-1])
    async with async_session_factory() as session:
        signal = await crud.get_signal_by_id(session, signal_id)
        if signal is None:
            await callback.answer("Signal topilmadi", show_alert=True)
            return
    # To'liq tafsilot sahifasi; "Signalga qaytish" tugmasi qisqa kartaga qaytaradi
    await callback.message.edit_text(
        format_signal_full(signal),
        reply_markup=kb.signal_detail_kb(signal_id),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sig:card:"))
async def back_to_card(callback: CallbackQuery) -> None:
    signal_id = int(callback.data.split(":")[-1])
    async with async_session_factory() as session:
        signal = await crud.get_signal_by_id(session, signal_id)
        if signal is None:
            await callback.answer("Signal topilmadi", show_alert=True)
            return
    # To'liq sahifadan qisqa signal kartasiga qaytamiz
    await callback.message.edit_text(
        format_signal_short(signal),
        reply_markup=kb.signal_card_kb(signal_id),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer()
