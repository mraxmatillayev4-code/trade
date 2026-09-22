"""Telegram xabarlar: signallar, grafik, natija (YUTDI/YUTQAZDI), hisobotlar."""
from __future__ import annotations

import json
from datetime import timezone

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.symbols import full_label, pair_display
from app.core.timeuz import format_tashkent
from app.database import crud
from app.database.models.signal import Signal
from app.engine.risk import format_r_map
from app.notifications.charts import render_signal_chart

logger = get_logger(__name__)


def fmt_price(p: float | None) -> str:
    if p is None:
        return "—"
    if p >= 1000:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:,.4f}"
    return f"{p:.6f}"


def risk_label(score: float) -> str:
    if score >= 8.5:
        return "Past (juda kuchli tasdiq)"
    if score >= 7:
        return "Past-o'rta"
    if score >= 6:
        return "O'rtacha"
    return "Yuqori"


def strategy_vote_line(signal: Signal) -> list[str]:
    """Strategiyalarning ovozini chiroyli chiqaradi."""
    try:
        checks = json.loads(signal.checks_json or "[]")
    except json.JSONDecodeError:
        checks = []
    lines = []
    for item in checks:
        label = item.get("label", "")
        if any(mark in label for mark in ("✅", "❌", "➖")):
            lines.append(label)
        elif item.get("source") in ("ai", "channel"):
            mark = "✅" if item.get("passed") else "➖"
            lines.append(f"{mark} {label}")
    return lines


def _source_line(signal: Signal) -> str:
    """Manba: SINO AI yoki Telegram kanal (nomi bilan)."""
    mode = (signal.quality_mode or "").upper()
    channel = ""
    try:
        checks = json.loads(signal.checks_json or "[]")
        for item in checks:
            if not isinstance(item, dict):
                continue
            if item.get("source") == "channel" or item.get("channel"):
                channel = str(item.get("channel") or item.get("label") or "")
                break
            lab = str(item.get("label") or "")
            if lab.upper().startswith("KANAL:"):
                channel = lab.split(":", 1)[-1].strip()
                break
    except json.JSONDecodeError:
        channel = ""
    if mode == "CHANNEL" or channel:
        name = channel if channel else "ulangan kanal"
        if name.upper().startswith("KANAL"):
            name = name.split(":", 1)[-1].strip() or name
        return f"📡 <b>Kanal:</b> {name}"
    return "📡 <b>Manba:</b> signal kanali"


def _esc81(v) -> str:
    """HTML uchun xavfsiz matn (kanal matni foydalanuvchi tomonidan yozilgan)."""
    import html as _html
    return _html.escape(str(v or ""), quote=False)


def source_block(signal: Signal, *, full: bool = True, text_limit: int = 700) -> list[str]:
    """v81: SIGNAL QAYSI KANALNING QAYSI XABARIDAN — post, vaqt, asl matn, rasm matni.

    full=True  -> «Nega bu signal?» uchun to'liq matn
    full=False -> qisqa karta uchun (matn qisqartiriladi)
    """
    ch = str(getattr(signal, "source_channel", "") or "").strip()
    un = str(getattr(signal, "source_username", "") or "").strip().lstrip("@")
    mid = int(getattr(signal, "source_msg_id", 0) or 0)
    posted = getattr(signal, "source_posted_at", None)
    body = str(getattr(signal, "source_text", "") or "").strip()
    ocr = str(getattr(signal, "source_ocr", "") or "").strip()
    if not (ch or un or mid or body or ocr):
        return []
    lim = text_limit if full else 240
    out = ["━━━━━━━━━━━━━━━━", "📡 <b>MANBA — qaysi xabardan olingan</b>"]
    name = ch or (("@" + un) if un else "noma'lum kanal")
    if un and un.lower() not in name.lower():
        name = f"{name} (@{un})"
    out.append(f"   📣 Kanal: <b>{_esc81(name)}</b>")
    if mid:
        out.append(f"   🆔 Post: <b>#{mid}</b>")
        if un:
            out.append(f"   🔗 <a href=\"https://t.me/{un}/{mid}\">"
                       f"Bu signalga ko'chir</a>")
    if posted is not None:
        out.append(f"   🕐 Post vaqti: <b>{format_tashkent(posted)}</b>")
    err = _age_text(getattr(signal, "created_at", None), posted)
    if err:
        out.append(f"   ⚡ Bot o'qigan: {format_tashkent(signal.created_at)} ({err} keyin)")
    if body:
        cut = "" if len(body) <= lim else " …"
        out.append("   📝 <b>Kanal xabari (asl holda):</b>")
        out.append(f"   <blockquote>{_esc81(body[:lim])}{cut}</blockquote>")
    if ocr:
        cut = "" if len(ocr) <= lim else " …"
        out.append("   🖼 <b>Rasmda yozilgan (OCR):</b>")
        out.append(f"   <blockquote>{_esc81(ocr[:lim])}{cut}</blockquote>")
    else:
        out.append("   🖼 Rasm: <i>rasm matni yo'q (yoki rasm yo'q)</i>")
    return out


def _age_text(created, posted) -> str:
    """Post tashlangandan keyin bot qancha vaqt o'tib o'qigan."""
    try:
        from datetime import timezone as _tz
        if created is None or posted is None:
            return ""
        a = created if created.tzinfo else created.replace(tzinfo=_tz.utc)
        b = posted if posted.tzinfo else posted.replace(tzinfo=_tz.utc)
        d = abs((a - b).total_seconds())
        if d < 90:
            return f"{int(d)} soniya"
        if d < 5400:
            return f"{int(d // 60)} daqiqa"
        return f"{d / 3600:.1f} soat"
    except Exception:  # noqa: BLE001
        return ""


def _expiry_text(signal: Signal) -> str:
    """'4 soat' / '36 daqiqa' — signal qancha vaqt amal qiladi."""
    try:
        from app.core.config import get_settings
        mins = int(get_settings().expiry_minutes_for(
            str(signal.timeframe or "1m"),
            str(getattr(signal, "quality_mode", "") or ""),
        ))
    except Exception:  # noqa: BLE001
        mins = 240
    if mins % 60 == 0 and mins >= 60:
        return f"{mins // 60} soat"
    return f"{mins} daqiqa"


def _duration_text(start, end) -> str:
    try:
        if start is None or end is None:
            return "—"
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        sec = max(0, int((end - start).total_seconds()))
    except Exception:  # noqa: BLE001
        return "—"
    if sec < 3600:
        return f"{sec // 60} daqiqa"
    h, m = divmod(sec // 60, 60)
    return f"{h} soat {m} daqiqa" if m else f"{h} soat"


_REASON_WORDS = {
    "SL": "STOP LOSS (−1R)",
    "BE": "STOP (himoya — kirishda)",
    "TP1": "TP1 (+1R himoya)",
    "TP2": "TP2",
    "TP3": "TP3 (Lot 1 yopildi)",
    "TP4": "TP4 (Lot 2 yopildi)",
    "TP5": "TP5 (Lot 2 momentum)",
    "VAQT TUGADI": "VAQT TUGADI (muddat tugadi)",
    "BEKOR": "BEKOR QILINDI",
    "BREAKEVEN": "ZARARSIZ (breakeven)",
}


_LOT_REASON = {
    "TP1": "TP1 (+1R himoya)", "TP2": "TP2 (+2R)", "TP3": "TP3 (Lot 1 +3R)",
    "TP4": "TP4 (Lot 2 +4R)", "TP5": "TP5 (Lot 2 +5R)",
    "SL": "STOP (−1R)", "BE": "STOP (himoya)", "VAQT TUGADI": "VAQT TUGADI",
    "BEKOR": "BEKOR QILINDI", "BREAKEVEN": "ZARARSIZ",
}


def lot_money_line(balance: float = 0.0, risk_percent: float = 1.0, *,
                   lot: float = 1.0, risk_distance: float = 0.0) -> str:
    """v68: hajm va shu hajmdagi pul — terminaldagi formulada (1 lot = 100 oz).

    «💵 Hajm: 0.50 + 0.50 lot (jami 1.00 lot · 1 lot = 100 oz) · SL gacha ~331.00$»
    """
    total = float(lot or 1.0)
    half = total / 2.0
    d = abs(float(risk_distance or 0.0))
    risk_total = d * 100.0 * total
    txt = (f"\U0001F4B5 <b>Hajm: {half:,.2f} + {half:,.2f} lot</b> "
           f"(jami {total:,.2f} lot \u00B7 1 lot = 100 oz)")
    if risk_total > 0:
        txt += f" \u00B7 SL gacha ~{risk_total:,.2f}$"
    if balance:
        txt += f" \u00B7 hisob {float(balance):,.2f}$"
    return txt


def lots_entry_lines(signal, *, lot: float = 1.0, contract: float = 100.0) -> list[str]:
    """v77/v79: HAR BIR LOT - qanchadan ochilgani va maqsadga yetsa qancha foyda.

    «📥 Lot 1: 0.50 lot · ochilish 4,348.68 · stop 4,351.08 · maqsad 4,345.00 (+3R)
      · risk 119.85$ · foyda +359.55$»
    Foyda ham, risk ham bitta formulada: hajm(oz) x narx farqi.
    """
    from app.engine.risk import lot_position_size, money_for_move, r_price
    d = str(getattr(signal, "direction", "") or "").upper()
    entry = float(getattr(signal, "entry", 0) or 0)
    sl = float(getattr(signal, "sl", 0) or 0)
    if entry <= 0 or sl <= 0 or d not in ("BUY", "SELL"):
        return []
    qty, risk_all = lot_position_size(abs(entry - sl), lot, contract)
    if qty <= 0:
        return []
    half_q = qty / 2.0
    half_lot = half_q / (contract or 100.0)
    half_risk = risk_all / 2.0
    risk_dist = abs(entry - sl)
    tp1 = float(getattr(signal, "tp1", 0) or 0)
    tp2 = float(getattr(signal, "tp2", 0) or 0)
    tp3 = float(getattr(signal, "tp3", 0) or 0)
    t1 = tp3 or tp2 or tp1
    t2 = r_price(d, entry, sl, 4)      # Lot 2 asosiy maqsadi (+4R)
    t2m = r_price(d, entry, sl, 5)     # Lot 2 momentum maqsadi (+5R)
    p1 = money_for_move(d, entry, t1, half_q) if t1 > 0 else risk_dist * half_q * 3.0
    p2 = money_for_move(d, entry, t2, half_q)
    p2m = money_for_move(d, entry, t2m, half_q)
    out = [
        f"\U0001F4E5 <b>Lot 1</b>: {half_lot:,.2f} lot \u00B7 ochilish <b>{fmt_price(entry)}</b> "
        f"\u00B7 stop {fmt_price(sl)} \u00B7 maqsad {fmt_price(t1)} (+3R)",
        f"      \u26A0\uFE0F risk {half_risk:,.2f}$ \u00B7 \U0001F7E2 foyda +{p1:,.2f}$ (+3R)",
        f"\U0001F4E5 <b>Lot 2</b>: {half_lot:,.2f} lot \u00B7 ochilish <b>{fmt_price(entry)}</b> "
        f"\u00B7 stop {fmt_price(sl)} (keyin +1R da {fmt_price(entry)}) "
        f"\u00B7 maqsad {fmt_price(t2)} (+4R) \u00B7 momentum {fmt_price(t2m)} (+5R)",
        f"      \u26A0\uFE0F risk {half_risk:,.2f}$ \u00B7 \U0001F7E2 foyda +{p2:,.2f}$ (+4R) "
        f"\u00B7 momentumda +{p2m:,.2f}$ (+5R)",
    ]
    out.append(lots_profit_line(signal, lot=lot, contract=contract))
    out.append(
        "\U0001F512 <b>Lot 2 qoidasi</b>: +4R da stop +4R ga qulflanadi \u2014 momentum "
        "kuchli bo'lsa +5R gacha boradi, so'nsa +4R da yopiladi "
        "(foyda 4R dan pastga tushmaydi)."
    )
    return out


def lots_profit_line(signal, *, lot: float = 1.0, contract: float = 100.0) -> str:
    """v79: «🎯 Maqsadga yetsa: +838.95$ (Lot 1 +359.55$ · Lot 2 +479.40$)»."""
    from app.engine.risk import lot_position_size, money_for_move, r_price
    d = str(getattr(signal, "direction", "") or "").upper()
    entry = float(getattr(signal, "entry", 0) or 0)
    sl = float(getattr(signal, "sl", 0) or 0)
    if entry <= 0 or sl <= 0 or d not in ("BUY", "SELL"):
        return ""
    qty, risk_all = lot_position_size(abs(entry - sl), lot, contract)
    if qty <= 0:
        return ""
    half_q, half_risk = qty / 2.0, risk_all / 2.0
    dist = abs(entry - sl)
    tp3 = float(getattr(signal, "tp3", 0) or 0) or float(getattr(signal, "tp2", 0) or 0) \
        or float(getattr(signal, "tp1", 0) or 0)
    t1 = tp3 or r_price(d, entry, sl, 3)
    t2 = r_price(d, entry, sl, 4)
    p1 = money_for_move(d, entry, t1, half_q) if t1 > 0 else dist * half_q * 3.0
    p2 = money_for_move(d, entry, t2, half_q)
    p2m = money_for_move(d, entry, r_price(d, entry, sl, 5), half_q)
    total = p1 + p2
    if total <= 0:
        return ""
    r_avg = (total / risk_all) if risk_all > 0 else 0.0
    tot_m = total + (p2m - p2)
    return (f"\U0001F3AF <b>Maqsadga yetsa: +{total:,.2f}$</b> "
            f"(Lot 1 +{p1:,.2f}$ \u00B7 Lot 2 +{p2:,.2f}$ \u00B7 "
            f"risk {half_risk * 2:,.2f}$ \u00B7 o'rtacha +{r_avg:,.2f}R)\n"
            f"\U0001F680 Momentum bo'lsa (Lot 2 +5R): <b>+{tot_m:,.2f}$</b>")


def lot_profit_text(pos) -> str:
    """v79: bitta LOT uchun foyda — hozirgi hajm bo'yicha (qolgan lot bilan).

    «maqsad 4,345.00 (+3R) · foyda +359.55$»
    """
    from app.engine.risk import lot_target_price, lot_target_r, money_for_move
    d = str(getattr(pos, "direction", "") or "BUY").upper()
    entry = float(getattr(pos, "entry", 0) or 0)
    qty = float(getattr(pos, "qty_remaining", 0) or getattr(pos, "qty_total", 0) or 0)
    target = float(getattr(pos, "tp3", 0) or getattr(pos, "tp2", 0) or 0)
    _r = lot_target_r(getattr(pos, "stage", 0))
    _tp = lot_target_price(pos)
    if _tp > 0:
        target = _tp                      # v82: maqsad R bo'yicha (Lot1 +3R, Lot2 +5R)
    if entry <= 0 or qty <= 0 or target <= 0:
        return ""
    money = money_for_move(d, entry, target, qty)
    return (f"maqsad {fmt_price(target)} (+{_r:.0f}R) \u00B7 "
            f"\U0001F7E2 foyda {money:+,.2f}$")


def lot_money_text(pos) -> str:
    """v68: HAJM va shu hajmdagi pul — «0.50 lot · SL gacha 165.50$».

    Terminaldagi kabi: 1 lot = 100 oz, pul = narx farqi x hajm.
    (v62 talabi ham saqlanadi: lot necha dollarlik ekani ko'rinadi.)
    """
    qty = float(getattr(pos, "qty_total", 0) or 0)
    sym = str(getattr(pos, "symbol", "") or "").upper()
    risk = abs(float(getattr(pos, "risk_amount", 0) or 0))
    if qty <= 0:
        return "hajm —"
    lot = (qty / 100.0) if sym.startswith(("XAU", "GOLD")) else qty
    txt = f"{lot:,.2f} lot"
    if risk > 0:
        txt += f" · SL gacha {risk:,.2f}$"
    return txt


def lot_reason_text(reason: str | None, r: float | None = None) -> str:
    """Lot yopilish sababi. Himoya stopida FOYDA bilan yopilgan bo'lsa — aniq yozamiz."""
    raw = str(reason or "").strip().upper()
    txt = _LOT_REASON.get(raw, raw or "yopilgan")
    try:
        rr = float(r) if r is not None else None
    except (TypeError, ValueError):
        rr = None
    if raw in ("BE", "SL") and rr is not None and rr > 0.5:
        txt = f"himoya stopi (+{rr:.2f}R)"
    return txt


def _reason_text(signal: Signal) -> str:
    raw = str(getattr(signal, "close_reason", "") or "").strip()
    if raw:
        return _REASON_WORDS.get(raw.upper(), raw)
    st = str(getattr(signal, "status", "") or "").upper()
    st_map = {
        "SL_HIT": "SL", "TP1_HIT": "TP1", "TP2_HIT": "TP2",
        "TP3_HIT": "TP3", "TP4_HIT": "TP4", "TP5_HIT": "TP5",
        "EXPIRED": "VAQT TUGADI", "CANCELLED": "BEKOR",
    }
    return _REASON_WORDS.get(st_map.get(st, ""), "—")


def signal_risk_line(signal, *, balance: float | None = None,
                     risk_percent: float | None = None) -> str:
    """v82: risk % va hajm qatori (balans bo'yicha)."""
    try:
        from app.core.config import get_settings as _gs
        from app.engine import sizing as _sz
        st = _gs()
        _rp = risk_percent if risk_percent else getattr(st, "risk_percent", 0.5)
        return _sz.risk_line(float(balance or 0.0),
                             float(_rp or 0.5),
                             float(signal.entry or 0), float(signal.sl or 0),
                             contract=float(getattr(st, "contract_size", 100.0) or 100.0),
                             max_lot=float(getattr(st, "lot_size", 1.0) or 1.0))
    except Exception:  # noqa: BLE001
        return ""


def format_signal_short(signal: Signal, balance: float | None = None,
                        risk_percent: float | None = None) -> str:
    """v82: QISQA signal kartasi — faqat kerakli narsa.

    Manba, lotlar tafsiloti, foyda hisobi — hammasi «❓ Nega bu signal?» da.
    """
    is_buy = signal.direction == "BUY"
    emoji = "\U0001F7E2" if is_buy else "\U0001F534"
    word = "SOTIB OLISH (BUY)" if is_buy else "SOTISH (SELL)"
    pair = full_label(signal.symbol)
    no = f"\u2116{signal.signal_no}" if signal.signal_no else ""
    rl = signal_risk_line(signal, balance=balance, risk_percent=risk_percent)
    e = float(signal.entry or 0)
    sl = float(signal.sl or 0)
    buy = str(signal.direction).upper() == "BUY"
    from app.engine.risk import r_price as _rp
    _d = "BUY" if buy else "SELL"
    _l1, _l2, _l3 = (_rp(_d, e, sl, n) for n in (1, 2, 3))
    _l4, _l5 = _rp(_d, e, sl, 4), _rp(_d, e, sl, 5)
    lines = [
        f"{emoji} <b>{word} SIGNALI</b> {no}",
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
        f"\U0001F4B0 <b>{pair}</b>  \u2022  \u23F1 {signal.timeframe.upper()}  \u2022  "
        f"{format_tashkent(signal.created_at)}",
        f"\u25B6\uFE0F Kirish <b>{fmt_price(e)}</b>  \u00B7  \U0001F6D1 Stop "
        f"<b>{fmt_price(sl)}</b>",
        f"\u2705 +1R {fmt_price(_l1)} \u00b7 +2R {fmt_price(_l2)} \u00b7 "
        f"+3R {fmt_price(_l3)}",
        f"\U0001F3AF Lot2: +4R {fmt_price(_l4)} \u00b7 +5R {fmt_price(_l5)}",
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
    ]
    if rl:
        lines.append(rl)
    lines.append(f"\U0001F3AF G'alaba: <b>{signal.win_probability:.0f}%</b>  |  "
                 f"\U0001F4CA Kuch: {signal.score:.1f}/10  |  2 lot")
    lines.append(f"\u23F3 Amal muddati: {_expiry_text(signal)}")
    lines.append("<i>Batafsil (manba, lotlar, foyda): \u2753 Nega bu signal?</i>")
    return "\n".join(lines)


def format_signal_full(signal: Signal, balance: float | None = None,
                       risk_percent: float | None = None) -> str:
    """TO'LIQ signal tafsiloti — 'Nega bu signal?' bosilganda chiqadi.

    v82: manba bloki va hajm/risk tafsiloti SHU YERDA (qisqa kartada emas).
    """
    is_buy = signal.direction == "BUY"
    emoji = "🟢" if is_buy else "🔴"
    title = "SOTIB OLISH (BUY) SIGNALI" if is_buy else "SOTISH (SELL) SIGNALI"
    pair = full_label(signal.symbol)
    no = f"№{signal.signal_no}" if signal.signal_no else ""

    lines = [
        f"{emoji} <b>{title}</b>  {no}",
        "━━━━━━━━━━━━━━━━",
        f"💰 <b>{pair}</b>   ⏱ {signal.timeframe.upper()}",
        f"🕐 <b>Kirish vaqti:</b> {format_tashkent(signal.created_at)}",
    ]
    _sb_top = source_block(signal)      # v82: MANBA signal tafsilotidan TEPADA
    if _sb_top:
        lines += _sb_top
    lines += [
        "",
        "📍 <b>KIRISH (Entry):</b>",
        f"   <b>{fmt_price(signal.entry)}</b>",
        f"   (zona: {fmt_price(signal.entry_low)} – {fmt_price(signal.entry_high)})",
        "",
        format_r_map(signal.entry, signal.sl, signal.tp1, signal.tp2, signal.tp3),
        "",
        "━━━━━━━━━━━━━━━━",
        f"📊 Signal kuchi: <b>{signal.score:.1f} / 10</b>",
        f"🎯 G'alaba ehtimoli: <b>{signal.win_probability:.0f}%</b>",
        f"🔐 Ishonch darajasi: {signal.confidence:.0f}%",
        f"⚠️ Risk: {risk_label(signal.score)}",
        "",
        "📡 <b>Manba:</b>",
    ]
    lines.extend(f"   {l}" for l in strategy_vote_line(signal))

    lines += [
        "",
        f"📈 Bozor rejimi: {signal.regime or '—'}",
        f"🔗 Yuqori TF mosligi: {signal.mtf_alignment}",
    ]

    if signal.explanation:
        lines += ["", "🧠 <b>Nega bu signal?</b>", signal.explanation]

    # v82: RISK / MONEY MANAGEMENT + har lot tafsiloti (qisqa kartadan shu yerga)
    try:
        from app.core.config import get_settings as _gs2
        from app.engine import sizing as _sz2
        _st2 = _gs2()
        _ctr = float(getattr(_st2, "contract_size", 100.0) or 100.0)
        _mx = float(getattr(_st2, "lot_size", 1.0) or 1.0)
        _rp2 = float(risk_percent if risk_percent else
                     getattr(_st2, "risk_percent", 0.5) or 0.5)
        _bal2 = float(balance or 0.0)
        _dist2 = abs(float(signal.entry or 0) - float(signal.sl or 0))
        _s2 = _sz2.size_for(_bal2, _rp2, _dist2, contract=_ctr, max_lot=_mx)
        _rmoney2 = _bal2 * _rp2 / 100.0 if _bal2 else 0.0
        _how = (f"{_rmoney2:,.2f}$ risk \u00b7 balans {_bal2:,.2f}$" if _bal2
                else "balans /hisob da ko'rinadi")
        lines += [
            "", "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
            "\u2696\uFE0F <b>RISK va HAJM (money management)</b>",
            f"   Risk: <b>{_rp2:.2f}%</b> \u00b7 {_how}",
            f"   Hajm: <b>{_s2['half_lot']:,.2f} + {_s2['half_lot']:,.2f} lot</b> "
            f"(jami {_s2['lot']:,.2f} lot \u00b7 1 lot = {_ctr:,.0f} oz)",
            f"   Lot1 +3R da, Lot2 +4R/+5R da yopiladi \u00b7 stop {fmt_price(signal.sl)}",
        ]
        lines += lots_entry_lines(signal, lot=float(_s2["lot"]), contract=_ctr)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[NOTIFY] to'liq karta lotlari: %s", exc)

    lines += [
        "",
        "━━━━━━━━━━━━━━━━",
        "⚠️ Signal faqat <b>tahliliy maqsadda</b>. Moliyaviy tavsiya emas.",
    ]
    return "\n".join(lines)


def format_signal(signal: Signal) -> str:
    """Eski chaqiruvlar uchun — to'liq format."""
    return format_signal_full(signal)


def format_result_short(signal: Signal, paper_rows: list | None = None) -> str:
    """v82: QISQA natija kartasi — faqat asosiy raqamlar + to'liq tafsilot tugmasi."""
    won = (signal.result == "WIN")
    be = signal.result == "BREAKEVEN"
    icon = "\u2705" if won else ("\U0001F535" if be else "\u274C")
    word = "YUTDI" if won else ("ZARARSIZ" if be else "YUTQAZDI")
    pair = full_label(signal.symbol)
    no = f"\u2116{signal.signal_no}" if signal.signal_no else "\u2116-"
    d = signal.direction or ""
    r = float(signal.r_multiple or 0.0)
    lines = [
        f"{icon} <b>SIGNAL {no} \u2014 {word}</b>",
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
        f"\U0001F4B0 <b>{pair}</b>  \u2022  \u23F1 {str(signal.timeframe or '').upper()}  \u2022  "
        f"{'\U0001F7E2 BUY' if d == 'BUY' else '\U0001F534 SELL'}",
        f"\U0001F4CC Sabab: <b>{_reason_text(signal)}</b>",
    ]
    if paper_rows:
        money = 0.0
        parts = []
        rows_sorted = sorted(paper_rows, key=lambda q: int(getattr(q, "stage", 0) or 0))
        for pos in rows_sorted:
            rr = float(getattr(pos, "r_multiple", 0) or 0)
            pnl = float(getattr(pos, "realized_pnl", 0) or 0)
            money += pnl
            nm = "Lot2" if int(getattr(pos, "stage", 0) or 0) >= 10 else "Lot1"
            parts.append(f"{nm} <b>{rr:+.2f}R</b> ({pnl:+,.2f}$)")
        lines.append("\u2696\uFE0F " + " \u00b7 ".join(parts))
        ic = "\U0001F7E2" if money >= 0 else "\U0001F534"
        lines.append(f"\U0001F4B5 Jami: <b>{money:+,.2f}$</b> {ic} \u00b7 Jami R: "
                     f"<b>{r:+.2f}R</b>")
    else:
        lines.append(f"\U0001F4CA Natija: <b>{r:+.2f}R</b>")
    lines.append("<i>To'liq tafsilot (qanday bo'ldi, R xarita, lotlar): pastdagi "
                 "tugma bilan.</i>")
    return "\n".join(lines)


def format_result(signal: Signal, paper_rows: list | None = None) -> str:
    """Keng natija: qaysi R olindi, lotlar, qancha foyda/zarar."""
    from app.engine.risk import r_price

    won = (signal.result == "WIN")
    be = signal.result == "BREAKEVEN"
    icon = "✅" if won else ("🔵" if be else "❌")
    word = "YUTDI" if won else ("ZARARSIZ YOPILDI" if be else "YUTQAZDI")
    pair = full_label(signal.symbol)
    no = f"№{signal.signal_no}" if signal.signal_no else "№-"
    r = float(signal.r_multiple) if signal.r_multiple is not None else 0.0
    pnl = float(signal.pnl_percent) if signal.pnl_percent is not None else 0.0
    st = str(signal.status or "")
    entry = float(signal.entry or 0)
    sl = float(signal.sl or 0)
    close = float(signal.close_price) if signal.close_price else None
    d = signal.direction or "SELL"
    p1 = r_price(d, entry, sl, 1)
    p2 = r_price(d, entry, sl, 2)
    p3 = r_price(d, entry, sl, 3)
    p4 = r_price(d, entry, sl, 4)
    p5 = r_price(d, entry, sl, 5)
    risk = abs(entry - sl)

    hit = {
        "TP1_HIT": 1, "TP2_HIT": 2, "TP3_HIT": 3,
        "TP4_HIT": 4, "TP5_HIT": 5,
    }.get(st, 0)
    if r >= 4.9:
        hit = max(hit, 5)
    elif r >= 3.9:
        hit = max(hit, 4)
    elif r >= 2.4:
        hit = max(hit, 3)
    elif r >= 1.9:
        hit = max(hit, 2)
    elif r >= 0.9:
        hit = max(hit, 1)
    sl_hit = st == "SL_HIT" or r < -0.05

    def mark(n: int) -> str:
        if sl_hit and n > 0 and hit < n:
            return "➖"
        if hit >= n:
            return "✅"
        if sl_hit and n < 0:
            return "🛑"
        return "➖"

    # Paper lotlar bo'lsa — hikoya HAQIQIY R bilan yoziladi (kanal TP si 3R dan
    # yaqin yoki uzoq bo'lishi mumkin, shuning uchun quruq '+3R' yozilmaydi).
    lot_r: dict[str, float] = {}
    if paper_rows:
        for pos in paper_rows:
            key = "lot2" if int(getattr(pos, "stage", 0) or 0) >= 10 else "lot1"
            lot_r[key] = float(getattr(pos, "r_multiple", 0.0) or 0.0)

    story: list[str] = []
    if paper_rows and lot_r:
        r2 = lot_r.get("lot2")
        r1 = lot_r.get("lot1")
        v1 = float(r1) if r1 is not None else 0.0
        v2 = float(r2) if r2 is not None else 0.0
        why1 = str(getattr(paper_rows[0], "close_reason", "") or "TP")
        why2 = str(getattr(paper_rows[-1], "close_reason", "") or "TP")
        # HAR LOTNING HAQIQIY R si yoziladi (kanal TP si 3R dan yaqin/uzoq bo'lishi mumkin)
        if st == "EXPIRED":
            story.append("⏳ Muddat tugadi — pozitsiya <b>bozor narxida</b> yopildi.")
        elif v1 < -0.5 and v2 < -0.5:
            story.append("Narx <b>stopga</b> urildi — ikkala lot zarar bilan yopildi.")
        elif v1 > 0.5 and v2 > 0.5:
            if v1 >= 2.9 and v2 >= 3.9:
                story.append("Ikkala lot ham <b>foyda</b> bilan yopildi "
                             "(Lot 1 +3R, Lot 2 +4R/+5R darajalarida).")
            elif v2 >= 1.5:
                story.append("Lot 1 <b>foyda</b> bilan yopildi; Lot 2 ham foyda "
                             "bilan (himoya stopida) yopildi.")
            else:
                story.append("Lot 1 kanal TP siga yetdi; Lot 2 <b>+1R himoya</b> "
                             "stopida foyda bilan yopildi.")
        elif v1 > 0.5 >= abs(v2):
            story.append("Lot 1 <b>foyda</b> bilan yopildi; Lot 2 ni himoya stopi "
                         "(zararsiz) yopdi.")
        elif abs(v1) <= 0.5 < v2:
            story.append("Lot 1 zararsiz yopildi; Lot 2 <b>foyda</b> bilan yopildi.")
        elif abs(v1) <= 0.5 and abs(v2) <= 0.5:
            story.append("Narx +1R himoyaga yetdi, keyin qaytdi — lotlar zararsiz yopildi.")
        else:
            story.append("Lotlar turlicha darajada yopildi (aniq R pastda).")
        story.append(f"   Lot 1: <b>{v1:+.2f}R</b>  ({lot_reason_text(why1, v1)})")
        if r2 is not None:
            story.append(f"   Lot 2: <b>{v2:+.2f}R</b>  ({lot_reason_text(why2, v2)})")
        lot1_txt, lot2_txt = f"{v1:+.2f}R", (f"{v2:+.2f}R" if r2 is not None else "—")
    elif sl_hit and hit <= 0:
        story.append("Narx <b>stop (−1R)</b> ga urildi. Ikkala lot zarar bilan yopildi.")
        story.append("+1R himoyaga yetilmadi.")
        lot1_txt, lot2_txt = "−1R (stop)", "−1R (stop)"
    elif sl_hit and hit >= 1:
        story.append("+1R himoya olindi — stop kirishga ko‘chdi.")
        story.append("Keyin narx qaytdi: lotlar <b>zararsiz</b> (breakeven) yopildi.")
        lot1_txt, lot2_txt = "0R (himoya)", "0R (himoya)"
    elif st == "TP5_HIT" or r >= 4.5:
        story.append("Lot 1 <b>+3R</b> da to‘liq yopildi.")
        story.append("Lot 2 momentum bilan <b>+5R</b> gacha bordi va yopildi.")
        lot1_txt, lot2_txt = "+3R yopildi", "+5R yopildi"
    elif st == "TP4_HIT" or r >= 3.4:
        story.append("Lot 1 <b>+3R</b> da to‘liq yopildi.")
        story.append("Lot 2 <b>+4R</b> da yopildi (momentum yetmadi — +5R yo‘q).")
        lot1_txt, lot2_txt = "+3R yopildi", "+4R yopildi"
    elif st == "TP3_HIT" or r >= 2.4:
        story.append("Lot 1 <b>+3R</b> da yopildi.")
        story.append("Lot 2 +4R/+5R ga yetmay yopildi yoki qolmadi.")
        lot1_txt, lot2_txt = "+3R yopildi", "chala / yopildi"
    elif st == "EXPIRED":
        story.append(f"⏳ Muddat tugadi — pozitsiya <b>bozor narxida</b> yopildi ({r:+.2f}R).")
        lot1_txt, lot2_txt = f"{r:+.2f}R (muddat)", f"{r:+.2f}R (muddat)"
    elif be:
        story.append("Foyda va zarar deyarli teng — <b>zararsiz</b> yopildi.")
        lot1_txt, lot2_txt = "0R", "0R"
    else:
        story.append(f"Bitim <b>{r:+.2f}R</b> bilan yopildi.")
        lot1_txt = lot2_txt = f"{r:+.2f}R"

    # Paper lotlar — aniq $
    cash = 0.0
    lot_lines: list[str] = []
    lot_brief = ""
    lots_n = len(paper_rows) if paper_rows else 2
    if paper_rows:
        brief: list[str] = []
        rows_sorted = sorted(
            paper_rows, key=lambda q: int(getattr(q, "stage", 0) or 0)
        )
        for i, pos in enumerate(rows_sorted, 1):
            rr = pos.r_multiple if getattr(pos, "r_multiple", None) is not None else 0.0
            pnl_p = float(getattr(pos, "realized_pnl", 0) or 0)
            cash += pnl_p
            runner = int(getattr(pos, "stage", 0) or 0) >= 10
            nom = "Lot 2 (+4R/+5R)" if runner else "Lot 1 (+3R)"
            _money = lot_money_text(pos)
            lot_lines.append(
                f"   \U0001F4E6 {nom}: <b>{rr:+.2f}R</b>  ({pnl_p:+,.2f}$) "
                f"\u00B7 {_money + ' \u00B7 ' if _money else ''}"
                f"{lot_reason_text(getattr(pos, 'close_reason', ''), rr)}"
            )
            brief.append(f"Lot{i} {rr:+.2f}R ({pnl_p:+,.2f}$)")
        # HAR IKKALA lot yoziladi; biri hali ochiq bo'lsa ham nomi turadi
        if len(rows_sorted) < 2:
            first_runner = (int(getattr(rows_sorted[0], "stage", 0) or 0) >= 10)
            missing = "Lot 1 (+3R)" if first_runner else "Lot 2 (+4R/+5R)"
            lot_lines.append(f"   \U0001F4E6 {missing}: hali yopilmagan (ochiq)")
        if lot_lines:
            lot_lines.append(f"   \U0001F4B5 Jami: <b>{cash:+,.2f}$</b> (ikkala lot)")
        lot_brief = ", ".join(brief)
    else:
        lot_lines = [
            f"   \U0001F4E6 Lot 1: {lot1_txt}",
            f"   \U0001F4E6 Lot 2: {lot2_txt}",
        ]

    natija_icon = "\U0001F7E2 FOYDA" if r > 0.05 else ( "\U0001F535 ZARARSIZ" if abs(r) <= 0.05 else "\U0001F534 ZARAR")
    jami_lines = [f"\U0001F3F7 Holat: <b>{natija_icon}</b>"]
    if paper_rows:
        jami_lines.append(f"\U0001F4E6 Lotlar: <b>{lots_n}</b>" + (f" \u00B7 {lot_brief}" if lot_brief else ""))
    else:
        jami_lines.append(f"\U0001F4E6 Lotlar: <b>2</b> \u00B7 Lot1 {lot1_txt}, Lot2 {lot2_txt}")
    jami_lines.append(f"\U0001F4CA Jami R: <b>{r:+.2f}R</b>" + (" (2 lot o'rtachasi \u2014 Lot1 + Lot2 puli / umumiy risk)" if lots_n > 1 else " (1 lot)"))
    if paper_rows:
        jami_lines.append(f"\U0001F4B5 Jami pul: <b>{cash:+,.2f}$</b>")
        risk_sum = sum(float(getattr(q, "risk_amount", 0) or 0) for q in rows_sorted)
        if risk_sum > 0:
            jami_lines.append(
                f"\u2696\uFE0F Risk (1R): <b>{risk_sum:,.2f}$</b> "
                f"= " + " + ".join(
                    f"{float(getattr(q, 'risk_amount', 0) or 0):,.2f}$" for q in rows_sorted
                )
            )
    jami_lines.append(f"\U0001F4C8 Narx bo'yicha: <b>{pnl:+.2f}%</b>")

    def row(ok: str, tag: str, label: str, price: float) -> str:
        return f"{ok} <b>{tag}</b> {label}: <b>{fmt_price(price)}</b>"

    lines = [
        f"{icon} <b>SIGNAL {no} — {word}</b>",
        "━━━━━━━━━━━━━━━━",
        f"💰 <b>{pair}</b>  •  ⏱ {str(signal.timeframe or '').upper()}  •  "
        f"{'🟢 BUY' if d == 'BUY' else '🔴 SELL'}",
        f"🕐 Berilgan: {format_tashkent(signal.created_at)}",
        f"🏁 Yopilgan: {format_tashkent(signal.closed_at) if getattr(signal, 'closed_at', None) else '—'}",
        f"⏳ Davomiylik: {_duration_text(getattr(signal, 'created_at', None), getattr(signal, 'closed_at', None))}",
        f"📌 Sabab: <b>{_reason_text(signal)}</b>",
        _source_line(signal),
        "━━━━━━━━━━━━━━━━",
        "📖 <b>QANDAY BO‘LDI</b>",
        *[f"   {s}" for s in story],
        "━━━━━━━━━━━━━━━━",
        f"\U0001F4E6 <b>{lots_n} LOT</b> (risk 50/50):",
        *lot_lines,
        "━━━━━━━━━━━━━━━━",
        f"📐 <b>R XARITA — qaysi daraja olindi</b>",
        f"   1R masofa: <b>{fmt_price(risk)}</b>",
        row("🛑" if sl_hit and hit <= 0 else "➖", "−1R", "STOP", sl),
        row("📍", " 0R", "KIRISH", entry),
        row(mark(1), "+1R", "HIMOYA", p1),
        row(mark(2), "+2R", "FOYDA", p2),
        row(mark(3), "+3R", "LOT 1", p3),
        row(mark(4), "+4R", "LOT 2", p4),
        row(mark(5), "+5R", "LOT 2 momentum", p5),
        "━━━━━━━━━━━━━━━━",
        "💵 <b>JAMI NATIJA</b>",
        *jami_lines,
        f"📥 Kirish: <b>{fmt_price(entry)}</b>   "
        f"🏁 O'rtacha chiqish: <b>{fmt_price(close)}</b>"
        "━━━━━━━━━━━━━━━━",
        "<i>Paper (virtual) natija — moliyaviy tavsiya emas.</i>",
    ]
    return "\n".join(lines)


class TelegramNotifier:
    def __init__(self, bot: Bot | None = None) -> None:
        self._bot = bot
        self._settings = get_settings()

    def bind_bot(self, bot: Bot) -> None:
        self._bot = bot

    # ---------- Qabul qiluvchilar ----------
    async def _recipients(self) -> list[int]:
        """Barcha aktiv foydalanuvchilar + admin (natija xabari ham yetadi)."""
        ids: list[int] = []
        try:
            async with _session() as session:
                ids = list(await crud.get_all_active_users(session))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[NOTIFY] users: %s", exc)
        for aid in self._settings.admin_id_list or []:
            if aid not in ids:
                ids.append(aid)
        return ids

    async def _send(self, text: str, chat_ids: list[int] | None = None,
                    photo: bytes | None = None, caption: str | None = None,
                    reply_markup: InlineKeyboardMarkup | None = None) -> None:
        if self._bot is None:
            logger.warning("Bot yo'q — xabar yuborilmadi: %.60s", text[:60])
            return
        targets = chat_ids if chat_ids is not None else await self._recipients()
        for chat_id in targets:
            try:
                if photo is not None:
                    await self._bot.send_photo(
                        chat_id,
                        BufferedInputFile(photo, filename="signal.png"),
                        caption=caption or text[:1000],
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup,
                    )
                else:
                    await self._bot.send_message(
                        chat_id, text, parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup, disable_web_page_preview=True,
                    )
            except TelegramAPIError as exc:
                logger.error("Telegram yuborish xatosi %s: %s", chat_id, exc)
                try:
                    await self._bot.send_message(
                        chat_id, text, parse_mode=None, reply_markup=reply_markup,
                        disable_web_page_preview=True,
                    )
                except Exception as exc2:  # noqa: BLE001
                    logger.error("Telegram qayta yuborish %s: %s", chat_id, exc2)

    # ---------- Signal ----------
    async def send_signal(self, signal: Signal, decision=None,
                          chart_png: bytes | None = None,
                          reply_markup: InlineKeyboardMarkup | None = None) -> None:
        # v82: QISQA karta; manba/lot tafsiloti faqat «Nega bu signal?» sahifasida.
        # Hisob (balans + risk %) karta yasalishidan OLDIN olinadi.
        _bal = 0.0
        _risk_pct = float(getattr(self._settings, "risk_percent", 0.5) or 0.5)
        if reply_markup is None:
            from app.bot.keyboards import signal_card_kb
            reply_markup = signal_card_kb(signal.id)
        async with _session() as session:
            targets: list[int] = []
            for uid in await crud.get_all_active_users(session):
                us = await crud.get_user_settings(session, uid)
                is_ch = (signal.quality_mode or "").upper() == "CHANNEL"
                if not is_ch:
                    if us and us.strong_only and signal.strength != "STRONG":
                        continue
                    if us and signal.direction == "BUY" and not us.notify_buy:
                        continue
                    if us and signal.direction == "SELL" and not us.notify_sell:
                        continue
                targets.append(uid)
        for aid in self._settings.admin_id_list or []:
            if aid not in targets:
                targets.append(aid)
        if not targets:
            logger.error("[NOTIFY] recipients 0 VA admin yo'q — #%s yuborilmadi", signal.id)
            return

        # v82: hajm balansning risk % idan (0.5% / 1% / 2%) — hisobdan o'qiladi
        try:
            from app.paper_trading.engine import PaperEngine
            async with _session() as s2:
                acc = await PaperEngine().get_account(s2, targets[0])
                _bal = float(getattr(acc, "balance", 0) or 0)
                _rp = getattr(acc, "risk_percent", None)
                if _rp in (None, 0):
                    _rp = float(getattr(self._settings, "risk_percent", 0.5) or 0.5)
                _risk_pct = float(_rp)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[NOTIFY] hisob balansi o'qilmadi: %s", exc)

        text = format_signal_short(signal, balance=_bal, risk_percent=_risk_pct)
        await self._send(text, targets, reply_markup=reply_markup)
        logger.info("[NOTIFY] signal #%s %s → %d foydalanuvchiga yuborildi",
                    signal.id, signal.symbol, len(targets))

    async def send_result(self, signal: Signal) -> None:
        from sqlalchemy import select
        from app.bot.keyboards import collapse_kb
        from app.database.models.paper import PaperPosition
        rows = []
        try:
            async with _session() as session:
                stmt = (
                    select(PaperPosition)
                    .where(PaperPosition.signal_id == signal.id)
                    .order_by(PaperPosition.id)
                )
                rows = list((await session.execute(stmt)).scalars().all())
        except Exception as exc:  # noqa: BLE001
            logger.warning("[NOTIFY] paper natija: %s", exc)
        # Karta raqamlari BITTA hisob bo'yicha bo'lishi kerak: pul yig'indisi va
        # pastdagi "Virtual hisob" bir xil foydalanuvchiniki bo'lsin (ilgari pul
        # barcha hisoblar bo'yicha qo'shilib, hisob bilan mos kelmasdi).
        main_uid = rows[0].user_id if rows else None
        own = [p for p in rows if p.user_id == main_uid] if rows else []
        # v82: qisqa karta yuboriladi, to'liq tafsilot tugma bilan ochiladi
        text = format_result_short(signal, own)
        try:
            ids = list(self._settings.admin_id_list)
            if ids and rows:
                from app.paper_trading.engine import PaperEngine
                async with _session() as _s:
                    acc = await PaperEngine().account_summary(_s, rows[0].user_id)
                icon = "🟢" if acc["pnl"] >= 0 else "🔴"
                text += (
                    "\n🏦 <b>Virtual hisob:</b> "
                    f"<b>${acc['balance']:,.2f}</b>  "
                    f"{icon} {acc['pnl']:+,.2f}$ ({acc['pnl_pct']:+.1f}%)\n"
                    f"📊 Bitimlar: {acc['trades']} | G'alaba: {acc['winrate']:.0f}% | "
                    f"Ochiq: {acc['open_count']}"
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[NOTIFY] hisob qatori: %s", exc)
        try:
            from app.bot.keyboards import result_short_kb
            _kb = result_short_kb(int(signal.id))
        except Exception:  # noqa: BLE001
            _kb = collapse_kb()
        await self._send(text, reply_markup=_kb)

    async def send_event(self, text: str) -> None:
        await self._send(text)

    async def send_report(self, text: str) -> None:
        from app.bot.keyboards import collapse_kb
        await self._send(text, reply_markup=collapse_kb())

    async def send_admin(self, text: str) -> None:
        """Faqat admin — SIGNAL/EMAS farqi, akkaunt holati."""
        ids = self._settings.admin_id_list
        if not ids:
            logger.warning("Admin yo'q — xabar yuborilmadi")
            return
        await self._send(text, ids)

    async def send_error(self, component: str, message: str) -> None:
        # Tizim xatolari faqat adminga
        text = (
            "🚨 <b>TIZIM XATOSI</b>\n"
            "━━━━━━━━━━━━━━━━\n"
            f"🧩 Komponent: <b>{component}</b>\n"
            f"📝 Xato: {message}\n"
            "♻️ Avtomatik tiklash ishga tushdi."
        )
        if self._settings.admin_id_list:
            await self._send(text, self._settings.admin_id_list)
        else:
            logger.warning("Admin yo'q — tizim xatosi yuborilmadi")


def _session():
    # importni kechiktiramiz (aylana importni oldini olish)
    from app.database.session import async_session_factory
    return async_session_factory()
