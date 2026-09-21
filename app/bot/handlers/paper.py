"""Paper trading (virtual hisob) — har foydalanuvchining O'Z balansi/bitimlari/avto-trade'i.

Tugmalar pastki (reply) klaviaturada; xabar osti inline yo'q.
Balansni o'rnatish: tugma bosilgach foydalanuvchi raqam yuboradi.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Filter
from aiogram.types import Message

from app.core.symbols import full_label
from app.database.session import async_session_factory
from app.notifications.telegram import fmt_price
from app.paper_trading.engine import PaperEngine

router = Router(name="paper")

_pending_balance: set[int] = set()


class _AwaitingBalance(Filter):
    """Faqat 'Balansni o'rnatish' bosilgandan keyin raqamni ushlaydi.
    Aks holda api_id kabi raqamlar yutilib, javobsiz qolardi."""

    async def __call__(self, message: Message) -> bool:
        u = message.from_user
        return bool(u and u.id in _pending_balance)


def _account_lines(acc, open_pos, closed) -> list[str]:
    pnl = acc.balance - acc.initial_balance
    pnl_pct = (pnl / acc.initial_balance * 100) if acc.initial_balance else 0.0
    icon = "🟢" if pnl >= 0 else "🔴"
    auto = "🟢 YOQILGAN" if acc.auto_trade_enabled else "🔴 O'CHIRILGAN"
    if acc.paused_by_circuit:
        auto = "⏸ PAUZA (3 ketma-ket zarar)"
    wr = (acc.total_wins / acc.total_trades * 100) if acc.total_trades else 0.0
    lines = [
        "💼 <b>SIZNING VIRTUAL HISOBINGIZ</b>",
        "━━━━━━━━━━━━━━━━",
        f"💵 Boshlang'ich balans: ${acc.initial_balance:,.2f}",
        f"🏦 Joriy balans: <b>${acc.balance:,.2f}</b>",
        f"{icon} Jami natija: <b>{pnl:+,.2f}$ ({pnl_pct:+.2f}%)</b>",
        f"📊 Bitimlar: {acc.total_trades} | G'alaba: {wr:.0f}%",
        f"🔴 Ketma-ket zarar: {acc.consecutive_losses}",
        f"🤖 Avto-trade: <b>{auto}</b>",
        f"📂 Ochiq bitimlar: {len(open_pos)}",
        "━━━━━━━━━━━━━━━━",
        "⚠️ Bu soxta (virtual) pul — haqiqiy pul ishlatilmaydi.",
    ]
    if open_pos:
        lines.append("\n<b>Sizning ochiq bitimlaringiz:</b>")
        for p in open_pos[:10]:
            ico = "🟢" if p.direction == "BUY" else "🔴"
            lot = "Lot2 +4R/+5R" if int(getattr(p, "stage", 0) or 0) >= 10 else "Lot1 +3R"
            lines.append(
                f"{ico} {full_label(p.symbol)} {p.timeframe.upper()} {p.direction} · {lot}\n"
                f"   Kirish: {fmt_price(p.entry)} | Stop: {fmt_price(p.sl)} | Maqsad: {fmt_price(p.tp3)}"
            )
    if closed:
        lines.append("\n<b>So'nggi yopilgan bitimlaringiz:</b>")
        for p in closed[:5]:
            r = f" ({p.r_multiple:+.2f}R)" if p.r_multiple is not None else ""
            ico = "🟢" if (p.realized_pnl or 0) >= 0 else "🔴"
            lines.append(f"{ico} {full_label(p.symbol)} {p.direction}: {p.realized_pnl:+.2f}${r}")
    return lines


@router.message(F.text == "💼 Hisob (paper)")
async def paper_account_message(message: Message) -> None:
    engine = PaperEngine()
    uid = message.from_user.id
    async with async_session_factory() as session:
        acc = await engine.get_account(session, uid)
        open_pos = await engine.open_positions(session, user_id=uid)
        closed = await engine.recent_closed(session, uid, limit=5)
        text = "\n".join(_account_lines(acc, open_pos, closed))
    await message.answer(text, parse_mode="HTML")


@router.message(F.text == "🤖 Avto-trade: yoqish/o'chirish")
async def toggle_auto_trade(message: Message) -> None:
    engine = PaperEngine()
    uid = message.from_user.id
    async with async_session_factory() as session:
        enabled, acc = await engine.toggle_auto_trade(session, uid)
    if enabled:
        await message.answer(
            "🤖 <b>Avto-trade YOQILDI</b> (sizning hisobingizda).\n"
            "Yangi signallar avtomatik virtual bitimga ochiladi.\n"
            "3 ketma-ket zarardan keyin faqat sizning avto-trade'ingiz pauzaga tushadi;\n"
            "signallar va hisobotlar baribir kelib turadi. Davom ettirish — shu tugmani qayta bosish.",
            parse_mode="HTML",
        )
    else:
        await message.answer(
            "🤖 <b>Avto-trade O'CHIRILDI</b> (sizning hisobingizda).\n"
            "Signallar baribir keladi, lekin sizga virtual bitim ochilmaydi.",
            parse_mode="HTML",
        )


@router.message(F.text == "💰 Balansni o'rnatish")
async def ask_balance(message: Message) -> None:
    _pending_balance.add(message.from_user.id)
    await message.answer(
        "💰 Yangi virtual balansni <b>raqam</b> bilan yuboring.\n"
        "Masalan: <code>10000</code> yoki <code>500</code>",
        parse_mode="HTML",
    )


@router.message(_AwaitingBalance(), F.text.regexp(r"^\d+(\.\d+)?$"))
async def set_balance(message: Message) -> None:
    try:
        amount = float(message.text)
    except ValueError:
        await message.answer("Iltimos, to'g'ri raqam yuboring (masalan: 10000).")
        return
    if amount <= 0:
        await message.answer("Balans 0 dan katta bo'lishi kerak.")
        return
    _pending_balance.discard(message.from_user.id)
    engine = PaperEngine()
    async with async_session_factory() as session:
        acc = await engine.set_balance(session, message.from_user.id, amount)
    await message.answer(
        f"✅ Sizning virtual balansingiz <b>${acc.balance:,.2f}</b> qilib o'rnatildi.\n"
        f"Zarar hisoblagichi va pauza nolga tushirildi.",
        parse_mode="HTML",
    )
