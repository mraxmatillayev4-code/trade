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
from app.notifications.telegram import (fmt_price, lot_money_text,
                                        lot_profit_text, lot_reason_text)
from app.paper_trading.engine import PaperEngine

router = Router(name="paper")

_pending_balance: set[int] = set()


class _AwaitingBalance(Filter):
    """Faqat 'Balansni o'rnatish' bosilgandan keyin raqamni ushlaydi.
    Aks holda api_id kabi raqamlar yutilib, javobsiz qolardi."""

    async def __call__(self, message: Message) -> bool:
        u = message.from_user
        return bool(u and u.id in _pending_balance)


_REASON_WORDS = {
    "SL": "STOP LOSS",
    "BE": "STOP (himoya)",
    "TP1": "TP1 (+1R)",
    "TP3": "TP3 (Lot1)",
    "TP4": "TP4 (Lot2)",
    "TP5": "TP5 (Lot2)",
    "VAQT TUGADI": "VAQT TUGADI",
    "BEKOR (yangi signal)": "BEKOR",
    "BEKOR": "BEKOR",
}


def _reason(p) -> str:
    raw = str(getattr(p, "close_reason", "") or "").strip()
    if raw:
        return _REASON_WORDS.get(raw.upper(), raw)
    return "yopilgan"


def _when(dt) -> str:
    from app.core.timeuz import format_tashkent
    return format_tashkent(dt) if dt else "—"


def _dur(p) -> str:
    from app.notifications.telegram import _duration_text
    return _duration_text(getattr(p, "opened_at", None), getattr(p, "closed_at", None))


def _lot_name(p) -> str:
    """Lot 2 — runner (stage 10+), Lot 1 — oddiy (stage 0..3)."""
    return "Lot 2 (+4R/+5R)" if int(getattr(p, "stage", 0) or 0) >= 10 else "Lot 1 (+3R)"


def _lot_short(p) -> str:
    return "Lot 2" if int(getattr(p, "stage", 0) or 0) >= 10 else "Lot 1"


def _group_rows(rows: list) -> list[list]:
    """Bitimni (signalni) bo'yicha guruhlaydi — LOTLAR BIRGA ko'rsatiladi."""
    groups: dict = {}
    order: list = []
    for p in rows:
        key = getattr(p, "signal_id", None)
        if key is None:
            key = ("x", id(p))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(p)
    return [groups[k] for k in order]


def _sort_lots(group: list) -> list:
    """Lot 1 doim birinchi."""
    return sorted(group, key=lambda p: int(getattr(p, "stage", 0) or 0))


def _grp_pnl(group: list) -> tuple[float, float]:
    """(jami $, o'rtacha R) — R = jami pul / jami risk (risk yo'q bo'lsa lotlar R i)."""
    cash = sum(float(getattr(p, "realized_pnl", 0) or 0) for p in group)
    risk = sum(float(getattr(p, "risk_amount", 0) or 0) for p in group)
    if risk > 0:
        return cash, cash / risk
    r_vals = [float(p.r_multiple) for p in group
              if getattr(p, "r_multiple", None) is not None]
    return cash, (sum(r_vals) / len(r_vals) if r_vals else 0.0)


def _closed_block(group: list, open_pos: list) -> list[str]:
    """Bitta bitim: IKKALA lot alohida + jami."""
    group = _sort_lots(group)
    head = group[0]
    cash, r_avg = _grp_pnl(group)
    ico = "🟢" if cash >= 0 else "🔴"
    out = [
        f"{ico} <b>{full_label(head.symbol)}</b> {head.direction} · "
        f"{str(head.timeframe or '').upper()} · {len(group)} lot"
    ]
    for p in group:
        rr = getattr(p, "r_multiple", None)
        rr_txt = f"{float(rr):+.2f}R" if rr is not None else "—"
        _money = lot_money_text(p)
        out.append(
            f"   📦 {_lot_name(p)}: <b>{rr_txt}</b> "
            f"({float(getattr(p, 'realized_pnl', 0) or 0):+,.2f}$) · "
            f"{_money + ' · ' if _money else ''}"
            f"📌 {lot_reason_text(getattr(p, 'close_reason', ''), rr)}"
        )
    # ikkinchi lot hali ochiq bo'lsa — aytib qo'yamiz
    if len(group) == 1:
        sid = getattr(head, "signal_id", None)
        still = [p for p in open_pos if getattr(p, "signal_id", None) == sid]
        if still:
            names = ", ".join(_lot_short(p) for p in still)
            out.append(f"   🕐 {names} hali ochiq — natijasi keyin qo'shiladi")
    r_txt = f"{r_avg:+.2f}R" + (" (2 lot o'rtachasi)" if len(group) > 1 else "")
    out.append(f"   💵 Jami: <b>{cash:+,.2f}$</b> · {r_txt}")
    out.append(f"   🏁 {_when(getattr(group[-1], 'closed_at', None))} · ⏳ {_dur(group[-1])}")
    return out


def _open_block(group: list) -> list[str]:
    """Ochiq bitim: ikkala lot ham alohida yoziladi."""
    group = _sort_lots(group)
    head = group[0]
    out = [
        f"🟢 <b>{full_label(head.symbol)}</b> {head.direction} · "
        f"{str(head.timeframe or '').upper()} · {len(group)} lot ochiq"
    ]
    goal = 0.0
    for p in group:
        _money = lot_money_text(p)
        _prof = lot_profit_text(p)          # v79: maqsad narxi + foyda ($)
        try:
            from app.engine.risk import money_for_move
            _t = float(getattr(p, "tp3", 0) or getattr(p, "tp2", 0) or 0)
            _rq = float(getattr(p, "qty_remaining", 0) or 0)
            if _t > 0 and _rq > 0:
                goal += money_for_move(str(getattr(p, "direction", "BUY")),
                                       float(getattr(p, "entry", 0) or 0), _t, _rq)
        except Exception:  # noqa: BLE001
            pass
        out.append(
            f"   📦 {_lot_name(p)}: <b>{_money}</b> · "
            f"kirish {fmt_price(p.entry)} | stop {fmt_price(p.sl)}"
            + (f" | {_prof}" if _prof else f" | maqsad {fmt_price(p.tp3)}")
        )
    if goal:
        out.append(f"   🎯 Maqsadga yetsa: <b>+{goal:,.2f}$</b> (ikkala lot)")
    return out


def _account_lines(acc, open_pos, closed, stats: dict | None = None) -> list[str]:
    pnl = acc.balance - acc.initial_balance
    pnl_pct = (pnl / acc.initial_balance * 100) if acc.initial_balance else 0.0
    icon = "🟢" if pnl >= 0 else "🔴"
    auto = "🟢 YOQILGAN" if acc.auto_trade_enabled else "🔴 O'CHIRILGAN"
    if acc.paused_by_circuit:
        auto = "⏸ PAUZA (3 ketma-ket zarar)"
    # v63: raqamlar DB dagi haqiqiy bitimlardan olinadi (hisoblagich xato bo'lsa ham to'g'ri)
    st = stats or {}
    trades = int(st.get("trades", acc.total_trades or 0))
    wins = int(st.get("wins", acc.total_wins or 0))
    losses = int(st.get("losses", max(0, trades - wins)))
    be = int(st.get("breakeven", 0))
    open_signals = int(st.get("open_signals", 0)) or (1 if open_pos else 0)
    wr = (wins / trades * 100.0) if trades else 0.0
    try:
        from app.core.config import get_settings
        _st = get_settings()
        lot_size = float(getattr(_st, "lot_size", 1.0) or 1.0)
        contract = float(getattr(_st, "contract_size", 100.0) or 100.0)
    except Exception:  # noqa: BLE001
        lot_size, contract = 1.0, 100.0
    lines = [
        "💼 <b>SIZNING VIRTUAL HISOBINGIZ</b>",
        "━━━━━━━━━━━━━━━━",
        f"💵 Boshlang'ich balans: ${acc.initial_balance:,.2f}",
        f"🏦 Joriy balans: <b>${acc.balance:,.2f}</b>",
        f"{icon} Jami natija: <b>{pnl:+,.2f}$ ({pnl_pct:+.2f}%)</b>",
        f"📊 Bitimlar: <b>{trades}</b> (🏆{wins} / 💥{losses}"
        + (f" / ⚖️{be}" if be else "") + f") | G'alaba: <b>{wr:.0f}%</b>",
        f"\u2696\uFE0F Hajm: <b>{lot_size / 2:,.2f} + {lot_size / 2:,.2f} lot</b> "
        f"(jami {lot_size:,.2f} lot \u00B7 1 lot = {contract:,.0f} oz)",
        f"🔴 Ketma-ket zarar: {acc.consecutive_losses}",
        f"🤖 Avto-trade: <b>{auto}</b>",
        f"📂 Ochiq: <b>{open_signals}</b> bitim ({len(open_pos)} lot)",
        "━━━━━━━━━━━━━━━━",
        "⚠️ Bu soxta (virtual) pul — haqiqiy pul ishlatilmaydi.",
    ]
    if open_pos:
        lines.append("\n<b>Sizning ochiq bitimlaringiz (lotlar bilan):</b>")
        for grp in _group_rows(open_pos)[:5]:
            lines.extend(_open_block(grp))
    if closed:
        lines.append("\n<b>So'nggi yopilgan bitimlaringiz (lotlar bilan):</b>")
        for grp in _group_rows(closed)[:5]:
            lines.extend(_closed_block(grp, open_pos))
    return lines


@router.message(F.text.startswith("/natija"))
async def last_results(message: Message) -> None:
    """Oxirgi yopilgan bitimlar: qachon, nima uchun, qancha foyda/zarar."""
    engine = PaperEngine()
    uid = message.from_user.id
    async with async_session_factory() as session:
        acc = await engine.get_account(session, uid)
        closed = await engine.recent_closed(session, uid, limit=10)
        summary = await engine.account_summary(session, uid)
    if not closed:
        await message.answer(
            "Hozircha yopilgan bitim yo'q.\n"
            "Signal kelganda avto-trade 2 lot ochadi; TP yoki SL urilganda natija shu yerga yoziladi.",
            parse_mode="HTML",
        )
        return
    icon = "🟢" if summary["pnl"] >= 0 else "🔴"
    out = [
        "📋 <b>OXIRGI NATIJALAR (WIN / LOSE)</b>",
        "━━━━━━━━━━━━━━━━",
    ]
    for grp in _group_rows(closed)[:10]:
        grp = _sort_lots(grp)
        cash, r_avg = _grp_pnl(grp)
        win = cash > 0.05
        head = grp[0]
        out.append(
            f"{'✅' if win else '❌'} <b>{full_label(head.symbol)}</b> {head.direction} "
            f"{str(head.timeframe or '').upper()} · <b>{len(grp)} lot</b>\n"
            f"   🕐 Ochilgan: {_when(getattr(head, 'opened_at', None))}\n"
            f"   🏁 Yopilgan: {_when(getattr(head, 'closed_at', None))}  (⏳ {_dur(head)})"
        )
        for p in grp:
            rr = getattr(p, "r_multiple", None)
            rr_txt = ("%+.2fR" % rr) if rr is not None else "—"
            out.append(
                f"   📦 {_lot_name(p)}: <b>{rr_txt}</b> "
                f"({float(getattr(p, 'realized_pnl', 0) or 0):+,.2f}$) · "
                f"📌 {lot_reason_text(getattr(p, 'close_reason', ''), rr)}\n"
                f"        📥 {fmt_price(p.entry)} → 🏁 {fmt_price(getattr(p, 'close_price', None))}"
            )
        r_txt = f"{r_avg:+.2f}R" + (" (2 lot o'rtachasi)" if len(grp) > 1 else "")
        out.append(f"   💵 Jami: <b>{cash:+,.2f}$</b> · {r_txt}")
    out += [
        "━━━━━━━━━━━━━━━━",
        f"🏦 Balans: <b>${summary['balance']:,.2f}</b>  {icon} "
        f"{summary['pnl']:+,.2f}$ ({summary['pnl_pct']:+.1f}%)",
        f"📊 Bitimlar: {summary['trades']} | G'alaba: {summary['winrate']:.0f}% | "
        f"Ochiq: {summary['open_count']}",
    ]
    await message.answer("\n".join(out), parse_mode="HTML")


@router.message(F.text.startswith("/hisob"))
async def paper_account_cmd(message: Message) -> None:
    """Buyruq ko'rinishida ham ishlaydi: /hisob"""
    await paper_account_message(message)


@router.message(F.text == "💼 Hisob (paper)")
async def paper_account_message(message: Message) -> None:
    engine = PaperEngine()
    uid = message.from_user.id
    async with async_session_factory() as session:
        acc = await engine.get_account(session, uid)
        open_pos = await engine.open_positions(session, user_id=uid)
        closed = await engine.recent_closed(session, uid, limit=5)
        stats = await engine.trade_stats(session, uid)
        text = "\n".join(_account_lines(acc, open_pos, closed, stats))
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
