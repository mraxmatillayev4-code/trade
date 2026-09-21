"""Signallar menyusi."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards as kb
from datetime import datetime, timezone

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


# =========================================================================== #
#  v61: JONLI KUZATUV — bot bozorni hozir qanday kuzatayotganini ko'rsatadi
# =========================================================================== #
async def _live_block(sig, positions: list, price: float | None) -> list[str]:
    from app.engine.risk import money_for_move, r_multiple_for_price, r_price
    from app.core.enums import Direction
    head = positions[0]
    d = str(head.direction or "BUY").upper()
    entry = float(head.entry or 0.0)
    sl = float(head.sl or 0.0)
    lot1 = [q for q in positions if int(getattr(q, "stage", 0) or 0) < 10]
    lot2 = [q for q in positions if int(getattr(q, "stage", 0) or 0) >= 10]
    out = [
        f"🪙 <b>{full_label(head.symbol)}</b> {d} · ⏱ {str(head.timeframe or '').upper()}"
        f"{' · №' + str(sig.signal_no) if getattr(sig, 'signal_no', None) else ''}",
        f"   📦 Ochiq lot: <b>{len(positions)}</b> "
        f"(Lot1 {'✅' if lot1 else '—'} · Lot2 {'✅' if lot2 else '—'})",
        f"   📥 Kirish: <b>{fmt_price(entry)}</b> · 🛑 Stop: <b>{fmt_price(sl)}</b>",
    ]
    if price is None:
        out.append("   ⚠️ Joriy narx olinmadi (birja javob bermadi) — keyingi tsiklda qayta olinadi.")
        return out
    r_now = r_multiple_for_price(
        Direction.BUY if d == "BUY" else Direction.SELL, entry, sl, price
    )
    out.append(f"   💹 Joriy narx: <b>{fmt_price(price)}</b> · hozirgi R: <b>{r_now:+.2f}R</b>")
    # v68: pul — terminaldagi kabi (hajm x narx farqi). 1 lot = 100 oz.
    try:
        _qty = sum(float(getattr(q, "qty_total", 0) or 0) for q in positions)
        _money = money_for_move(d, entry, price, _qty)
        _lots = _qty / 100.0
        out.append(f"   💵 <b>Hozirgi P/L: {_money:+,.2f}$</b> · hajm {_lots:,.2f} lot "
                   f"(1 lot = 100 oz)")
    except Exception:  # noqa: BLE001
        pass
    # Darajalar: +1R/+2R/+3R — signalning o'z narxlari, +4R/+5R — R dan hisoblanadi
    levels: dict = {}
    for n in (1, 2, 3):
        v = float(getattr(sig, f"tp{n}", 0.0) or 0.0)
        if v > 0:
            levels[n] = v
    for n in (4, 5):
        v = 0.0
        for q in lot2:
            v = float(getattr(q, "tp2" if n == 4 else "tp3", 0.0) or 0.0) or v
        levels[n] = v or r_price(d, entry, sl, n)
    marks = []
    for n, label in ((-1, "STOP"), (0, "KIRISH"), (1, "himoya"), (2, "foyda"),
                     (3, "LOT 1"), (4, "LOT 2"), (5, "LOT 2 momentum")):
        lvl = levels.get(n) if n > 0 else r_price(d, entry, sl, n)
        if n < 0:
            hit = (price <= lvl) if d == "BUY" else (price >= lvl)
        else:
            hit = (price >= lvl) if d == "BUY" else (price <= lvl)
        marks.append(f"      {'✅' if hit else '➖'} {n:+d}R {label}: {fmt_price(lvl)}")
    nxt = None
    for n in (1, 2, 3, 4, 5):
        lvl = levels[n]
        if (price < lvl) if d == "BUY" else (price > lvl):
            nxt = (n, lvl)
            break
    out.append("   📐 <b>Darajalar</b> (narx qaysi darajada):")
    out.extend(marks)
    if nxt:
        far = abs(nxt[1] - price)
        out.append(f"   ⏭ Keyingi daraja: <b>+{nxt[0]}R</b> {fmt_price(nxt[1])} "
                   f"— narx {fmt_price(far)} uzoqda")
    else:
        out.append("   🏆 Barcha darajalar bosib o'tilgan")
    if lot2:
        out.append(f"   🔒 Lot 2 stopi: {fmt_price(float(lot2[0].sl or 0))}")
    return out


@router.message(Command("kuzat"))
@router.message(F.text == "\U0001F50E Jonli kuzatuv")
async def live_track_button(message: Message) -> None:
    """v74: «🔎 Jonli kuzatuv» — asosiy menyudagi tugma (kanallar ichida emas)."""
    await cmd_live_track(message)


async def _track_view(uid: int) -> tuple[str, list[tuple[str, str]]]:
    """Jonli kuzatuv matni + qo'lda yopish tugmalari (v74)."""
    from app.core.timeuz import format_tashkent
    from app.database import crud as _crud
    from app.database.session import async_session_factory
    from app.paper_trading.engine import PaperEngine
    from app.services import live_state

    engine = PaperEngine()
    async with async_session_factory() as session:
        opens = await engine.open_positions(session, user_id=uid)
        sigs = {}
        for sid in {int(p.signal_id) for p in opens if p.signal_id}:
            sig = await _crud.get_signal_by_id(session, sid)
            if sig is not None:
                sigs[sid] = sig

    if not opens:
        chk_any = live_state.last_check_any()
        alive = ""
        if chk_any is not None:
            age = max(0, int((datetime.now(timezone.utc) - chk_any).total_seconds()))
            alive = f"\n\u23F1 Oxirgi sham tekshiruvi: {format_tashkent(chk_any)} \u00B7 {age} s oldin"
        return ("\U0001F50E <b>JONLI KUZATUV</b>\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                "Hozir ochiq bitim yo'q \u2014 yopadigan lot ham yo'q.\n"
                "Yangi signal kelganda shu yerga darajalar bilan chiqadi va shu yerda "
                "\u00AB\u2705 Yopish\u00BB tugmasi paydo bo'ladi.\n"
                "Kuzatuv har 1m sham yopilganda avtomatik tekshiriladi, "
                "xohlasangiz \u00AB\U0001F504 Yangilash\u00BB bilan qo'lda ham.\n" + alive, [])

    by_sig: dict = {}
    for p in opens:
        by_sig.setdefault(p.signal_id, []).append(p)

    lines = ["\U0001F50E <b>JONLI KUZATUV</b>", "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"]
    buttons: list[tuple[str, str]] = []
    money_all = 0.0
    for sid, positions in by_sig.items():
        sig = sigs.get(sid)
        if sig is None:
            continue
        price = await live_state.get_price(sig.symbol)
        lines.extend(await _live_block(sig, positions, price))
        chk = live_state.last_check(sig.symbol, sig.timeframe)
        if chk is not None:
            age = max(0, int((datetime.now(timezone.utc) - chk).total_seconds()))
            lines.append(f"   \u23F1 Oxirgi tekshiruv: {format_tashkent(chk)} \u00B7 {age} s oldin")
        lines.append("\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501")
        no = getattr(sig, "signal_no", None) or sid
        side = str(sig.direction or "").upper()
        if price:
            try:
                from app.engine.risk import money_for_move
                qty = sum(float(getattr(q, "qty_total", 0) or 0) for q in positions)
                money_all += money_for_move(side, float(sig.entry or 0), float(price), qty)
            except Exception:  # noqa: BLE001
                pass
        buttons.append((f"\u2705 Yopish \u2014 foyda ol (\u2116{no} {side})", "kclose:%d" % int(sid)))
    if len(by_sig) > 1:
        buttons.append(("\U0001F6D1 Hammasini yopish (qo'lda)", "kclose:all"))
    buttons.append(("\U0001F504 Yangilash", "kreload"))
    lines.append(
        "<i>Qo'lda yopish: narx hozirgi holatda yopiladi va pul darhol hisobga "
        "o'tadi (inson omili). Avto-trade esa o'z qoidalarida davom etadi \u2014 "
        "kuzatuv har 1m sham yopilganda avtomatik yangilanadi.</i>"
    )
    return ("\n".join(lines), buttons)


async def cmd_live_track(message: Message) -> None:
    """🔎 Bot bozorni hozir qanday kuzatayotgani + QO'LDA YOPISH tugmalari (v74)."""
    uid = message.from_user.id if message.from_user else None
    text, buttons = await _track_view(uid)
    await message.answer(text, parse_mode="HTML",
                         reply_markup=kb.track_kb(buttons))


@router.callback_query(F.data == "kreload")
async def cb_track_reload(cb: CallbackQuery) -> None:
    """«🔄 Yangilash» — jonli kuzatuvni qayta hisoblaydi."""
    uid = cb.from_user.id if cb.from_user else None
    text, buttons = await _track_view(uid)
    try:
        await cb.message.edit_text(text, parse_mode="HTML",
                                   reply_markup=kb.track_kb(buttons))
    except Exception:  # noqa: BLE001
        try:
            await cb.message.answer(text, parse_mode="HTML",
                                    reply_markup=kb.track_kb(buttons))
        except Exception:  # noqa: BLE001
            pass
    await cb.answer("Yangilandi")


@router.callback_query(F.data.startswith("kclose:"))
async def cb_manual_close(cb: CallbackQuery) -> None:
    """«✅ Yopish — foyda ol» — lotlar JORIY narxda qo'lda yopiladi (inson omili)."""
    uid = cb.from_user.id if cb.from_user else 0
    raw = (cb.data or "").split(":", 1)[1]
    sid = None if raw == "all" else (int(raw) if raw.isdigit() else None)
    from app.core.timeuz import format_tashkent
    from app.database.session import async_session_factory
    from app.paper_trading.engine import PaperEngine

    engine = PaperEngine()
    async with async_session_factory() as session:
        res = await engine.manual_close(session, user_id=uid, signal_id=sid,
                                        reason="QO'LDA (foyda)")
    if not res.get("closed"):
        await cb.answer("Yopadigan ochiq lot yo'q.", show_alert=True)
        return
    money = float(res.get("money") or 0)
    icon = "\U0001F7E2" if money >= 0 else "\U0001F534"
    prices = res.get("prices") or {}
    px_txt = " \u00B7 ".join(f"{fmt_price(v)}" for v in prices.values()) or "\u2014"
    head = (f"\u2705 <b>QO'LDA YOPILDI</b> ({res['closed']} lot)\n"
            f"{icon} Natija: <b>{money:+,.2f}$</b> \u00B7 narx: {px_txt} \u00B7 "
            f"\u00F8 {float(res.get('r_avg') or 0):+.2f}R\n"
            f"\u23F1 {format_tashkent()}")
    if sid is None:
        head += "\n<i>Barcha ochiq bitimlar yopildi — foyda hisobga o'tdi.</i>"
    else:
        head += "\n<i>Shu signalning lotlari yopildi; boshqa signallar ochiq qoldi.</i>"
    try:
        await cb.message.answer(head, parse_mode="HTML")
    except Exception:  # noqa: BLE001
        pass
    await cb.answer(("Yopildi: %+.2f$" % money))
    # kuzatuvni yangilab qo'yamiz
    text, buttons = await _track_view(uid)
    try:
        await cb.message.edit_text(text, parse_mode="HTML",
                                   reply_markup=kb.track_kb(buttons))
    except Exception:  # noqa: BLE001
        try:
            await cb.message.answer(text, parse_mode="HTML",
                                    reply_markup=kb.track_kb(buttons))
        except Exception:  # noqa: BLE001
            pass


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
