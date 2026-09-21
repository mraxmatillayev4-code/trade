"""📡 Kanallar — ulash, o'chirish, har kanal statistikasi."""
from __future__ import annotations

import asyncio

from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command, Filter
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)
from sqlalchemy import select

from app.bot import keyboards as kb
from app.core.config import get_settings
from app.core.logging import get_logger
from app.database.models.signal import Signal, SignalConfirmation
from app.database.models.stats import StrategyStat
from app.database.session import async_session_factory
from app.services.channel_store import (
    MAX_CHANNELS,
    add_channel,
    display_name,
    list_channels,
    remove_channel,
    stat_key,
)

router = Router(name="channels")
logger = get_logger(__name__)

_BTN_AKKAUNT = {"👤 Akkaunt", "Akkaunt"}
_QR_TTL = 30   # tg://login havolasi shuncha soniyada eskiradi
_MENU_BTNS = _BTN_AKKAUNT | {
    "⬅️ Orqaga", "📡 Kanallar", "➕ Qo'shish", "➖ O'chirish", "🔎 Holat",
    "🔥 Signallar", "📊 Bozor", "📚 Strategiyalar", "📈 Statistika",
    "💼 Hisob (paper)", "🗓 Hisobotlar", "💰 Balansni o'rnatish",
    "🤖 Avto-trade: yoqish/o'chirish", "⚙️ Sozlamalar", "ℹ️ Ma'lumot",
}


class ChannelState(StatesGroup):
    menu = State()
    awaiting_add = State()
    awaiting_remove = State()
    awaiting_api_id = State()
    awaiting_api_hash = State()
    awaiting_phone = State()
    awaiting_code = State()
    awaiting_2fa = State()


def _is_admin(user_id: int | None) -> bool:
    from app.core.access import is_admin
    return is_admin(user_id)


_tasks: set = set()


def _spawn(coro) -> None:
    """Fon vazifasi (havola yo'qolmasligi uchun to'plamda saqlanadi)."""
    try:
        t = asyncio.create_task(coro)
    except RuntimeError:
        return
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


async def _reload_watcher() -> None:
    """Kanallar o'zgarganda kuzatuvchi qayta ulanadi — yangi xabar DARHOL o'qiladi."""
    try:
        from app.services.channel_watcher import restart_watcher
        await restart_watcher()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[KANAL] kuzatuvchi: %s", exc)


_login_tmp: dict = {}

# Kanallarni qo'shish/o'chirish jarayonidagi foydalanuvchilar. Bu paytda kelgan
# forward yoki matn SIGNAL deb TAHLIL QILINMAYDI — faqat kanal manbasi sifatida
# o'qiladi («shunchaki kanalni ulasin»).
_ch_flow: set[int] = set()


def _is_forward(message: Message) -> bool:
    if getattr(message, "forward_from_chat", None) is not None:
        return True
    if getattr(message, "forward_origin", None) is not None:
        return True
    if getattr(message, "forward_date", None) is not None:
        return True
    return False


class AdminSignalIn(Filter):
    """Admin forward/rasm/signal-matn — istalgan menyudan."""

    async def __call__(self, message: Message) -> bool:
        user = message.from_user
        if user is None or not _is_admin(user.id):
            return False
        t = (message.text or "").strip()
        if t in _MENU_BTNS or (t.startswith("/") and len(t) > 1):
            return False
        step = (_login_tmp.get(user.id) or {}).get("step")
        if step:
            return False
        if user.id in _ch_flow:
            # ➕ Qo'shish / ➖ O'chirish jarayoni: bu xabar faqat kanal uchun
            return False
        if _is_forward(message):
            return True
        if getattr(message, "photo", None):
            return True
        doc = getattr(message, "document", None)
        mime = str(getattr(doc, "mime_type", "") or "") if doc is not None else ""
        if mime.startswith("image/"):
            return True
        cap = (getattr(message, "caption", None) or "").strip()
        if cap and not t:
            return True
        if t:
            try:
                from app.services.channel_parse import is_close_message, parse_signal
                if is_close_message(t):
                    return True
                if len(t) >= 6 and parse_signal(t) is not None:
                    return True
            except Exception:  # noqa: BLE001
                return False
        return False


@router.message(AdminSignalIn())
async def on_admin_signal(message: Message) -> None:
    uid = message.from_user.id if message.from_user else None
    if uid is not None and uid in _ch_flow:
        return       # kanal ulash jarayoni — signal tahlili qilinmaydi

    """Kanal xabari botga keldi — AI SIGNAL/EMAS."""
    try:
        from app.services.channel_inbox import ingest_from_bot_message
        status = await ingest_from_bot_message(message)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[CH] bot ingest: %s", exc)
        await message.reply(f"⚠️ O'qish xato: {exc}")
        return
    if status == "ok":
        await message.reply(
            "✅ <b>SIGNAL</b> — foydalanuvchilarga yuborildi, avto-trade ochildi.",
            parse_mode="HTML",
        )
    elif status == "closed":
        await message.reply(
            "✅ Eski paper/signal yopildi (admin tugatdi).",
            parse_mode="HTML",
        )
    elif status == "dedup":
        await message.reply("ℹ️ Shu juftlikda ochiq signal bor — qayta yuborilmadi.")
    elif status in ("not_signal", "seen", "skip"):
        return
    else:
        await message.reply(f"ℹ️ Holat: {status}")


def _extract_username(text: str) -> str | None:
    t = (text or "").strip()
    if not t:
        return None
    t = t.replace("https://t.me/", "").replace("http://t.me/", "").replace("t.me/", "")
    t = t.split("?")[0].strip().strip("/")
    if t.startswith("@"):
        t = t[1:]
    t = t.split("/")[0]
    if t and t.replace("_", "").isalnum() and 4 <= len(t) <= 32:
        return t.lower()
    return None


async def _week_stats(session, sk: str) -> tuple[int, int, int]:
    """(jami, yutuq, zarar) — so'nggi 7 kun, shu kanal tasdiqlari."""
    since = datetime.now(timezone.utc) - timedelta(days=7)
    ids = list((await session.execute(
        select(SignalConfirmation.signal_id).where(SignalConfirmation.strategy_name == sk)
    )).scalars().all())
    if not ids:
        return 0, 0, 0
    rows = list((await session.execute(
        select(Signal).where(Signal.id.in_(ids), Signal.created_at >= since)
    )).scalars().all())
    wins = sum(1 for s in rows if (s.r_multiple or 0) > 0.05)
    losses = sum(1 for s in rows if (s.r_multiple or 0) < -0.05)
    return len(rows), wins, losses


async def _menu_text(session, is_admin: bool) -> str:
    channels = await list_channels(session)
    from app.services.channel_user import is_linked
    linked = await is_linked()
    acc = "✅ akkaunt ulangan" if linked else "❌ akkaunt ulanmagan"
    lines = [
        "📡 <b>SIGNAL KANALLARI</b>",
        "━━━━━━━━━━━━━━━━",
        "Bot o'zi signal qidirmaydi. Faqat shu kanallardan oladi (matn + rasm).",
        f"👤 Telegram: {acc}",
        "Xabarda kanal nomi chiqadi. Har kanalning o'z statistikasi bor.",
        "Kod kelmasa: /qr — QR bilan ulash (kod kerak emas).",
        "",
    ]
    if not channels:
        lines.append("Hozircha kanal ulanmagan.")
    for i, ch in enumerate(channels, 1):
        sk = stat_key(ch.get("username"), ch.get("chat_id"))
        n, w, l = await _week_stats(session, sk)
        closed = w + l
        wr = f"{(w / closed * 100):.0f}%" if closed else "—"
        kind = "yopiq" if ch.get("kind") == "private" else "ommaviy"
        lines.append(
            f"{i}. <b>{display_name(ch)}</b> ({kind})\n"
            f"    1 hafta: <b>{n}</b> ta  |  🏆 {w}  💥 {l}  WR {wr}"
        )
        stat = await session.scalar(
            select(StrategyStat).where(StrategyStat.strategy_name == sk)
        )
        if stat and stat.total_signals:
            lines.append(
                f"    jami: {stat.total_signals}  WR {stat.win_rate:.0f}%  "
                f"PF {stat.profit_factor:.2f}"
            )
    lines += [
        "━━━━━━━━━━━━━━━━",
        f"Ulash: {len(channels)}/{MAX_CHANNELS}",
        "",
        "1️⃣ <b>Eng ishonchli:</b> kanal xabarini (matn/rasm) shu botga <b>forward</b> qiling.",
        "AI SIGNAL ni yuboradi, EMAS ni faqat hisobotga yozadi. Botni kanalga qo'shish shart emas.",
        "2️⃣ Ommaviy kanal uchun: <b>botni kanalga admin</b> qilib qo'shsangiz, "
        "postlar to'g'ridan-to'g'ri botga keladi (akkaunt kerak emas).",
        "3️⃣ Avtomatik: <b>👤 Akkaunt</b> ulansa, AI kanallarni o'zi o'qiydi "
        "(yopiq kanallar ham).",
        "Yopiq kanal: akkauntingiz obuna bo'lgan bo'lishi kerak.",
    ]
    if is_admin:
        lines.append("Admin: ➕ Qo'shish / ➖ O'chirish / 👤 Akkaunt.")
        lines.append("🗑 Kanalni o'chirish: <b>➖ O'chirish</b> tugmasini bosing — kanal nomlari "
                     "tugma bo'lib chiqadi va bir bosishda o'chadi.")
        lines.append("↩️ Adashsangiz: o'chirilgandan keyin chiqadigan «Qaytarish» tugmasini bosing.")
        lines.append("\U0001F9F9 Hamma signalni unutish (\u21161 dan boshlash): /tozalash")
    return "\n".join(lines)


# ======== v66/v71: kanalni BITTA bosishda o'chirish (+ qaytarish) ========
_DEL_HINT = ("\U0001F5D1 <b>Kanalni o'chirish</b> \u2014 kanal nomini bosing: "
             "<b>bir bosishda</b> o'chadi (adashsangiz «\u21A9\uFE0F Qaytarish»).")

# Oxirgi o'chirilgan kanal(lar) — adashib bosilsa qaytarish uchun
_LAST_DEL: dict[int, dict] = {}


def _esc_html(t: str) -> str:
    """HTML uchun xavfsiz matn."""
    return (str(t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _channels_inline(channels: list[dict]) -> InlineKeyboardMarkup | None:
    """Har bir kanal uchun BITTA o'chirish tugmasi + «hammasini» (v71)."""
    rows: list[list[InlineKeyboardButton]] = []
    for i, ch in enumerate(channels):
        name = display_name(ch)
        if len(name) > 32:
            name = name[:31] + "..."
        rows.append([InlineKeyboardButton(
            text="\U0001F5D1 " + name, callback_data="chdel:%d" % i,
        )])
    if not rows:
        return None
    if len(rows) >= 2:
        rows.append([InlineKeyboardButton(
            text="\U0001F5D1 Hammasini o'chirish (%d ta)" % len(rows),
            callback_data="chdelall",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _del_confirm_kb() -> InlineKeyboardMarkup:
    """Faqat «hammasini o'chirish» uchun tasdiq (bittasi tasdiqsiz o'chadi)."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="\u2705 Ha, hammasini", callback_data="chdelyall"),
        InlineKeyboardButton(text="\u274C Yo'q", callback_data="chdelno"),
    ]])


def _undo_kb(has: bool) -> InlineKeyboardMarkup | None:
    if not has:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="\u21A9\uFE0F Qaytarish", callback_data="chundo"),
    ]])


@router.message(F.text == "📡 Kanallar")
async def channels_menu(message: Message, state) -> None:
    adm = _is_admin(message.from_user.id if message.from_user else None)
    if not adm:
        await message.answer("📡 Kanallar — faqat admin.")
        return
    if message.from_user:
        _ch_flow.discard(message.from_user.id)
    await state.set_state(ChannelState.menu)
    async with async_session_factory() as session:
        text = await _menu_text(session, True)
        chans = await list_channels(session)
    await message.answer(text, parse_mode="HTML", reply_markup=kb.channels_reply(True))
    # v73: bu bo'limda o'chirish tugmalari chiqmaydi — faqat ma'lumot.
    # Kanal nomlari tugma bo'lib faqat «➖ O'chirish» bosilganda chiqadi.


# ===================== /100 — kanallardan xabar yozib olish =====================
_DUMP_TASK: asyncio.Task | None = None


async def _dump_job(message: Message, limit: int) -> None:
    try:
        from app.services import channel_archive as arc

        res = await arc.dump(limit=limit)
        lines = [f"\U0001F4E5 <b>Kanallardan yozib olindi</b> (limit {res.get('limit')})", ""]
        lines.append(
            f"Kanallar: <b>{res.get('ok')}/{res.get('channels')}</b> | "
            f"xabar: <b>{res.get('saved')}</b> | eski o'chirildi: {res.get('deleted')} | "
            f"{res.get('secs')}s"
        )
        if res.get("fail"):
            lines.append("\u26A0\uFE0F O'qilmadi: " + ", ".join(str(x) for x in res["fail"][:8]))
        for p in (res.get("per") or [])[:15]:
            lines.append(f"\u2022 {p['name']}: {p['n']} ta ({p['text']} matnli)")
        if res.get("error"):
            lines.append(f"\u274C {res['error']}")
        await message.answer("\n".join(lines), parse_mode="HTML")
        name, data = await arc.export_txt()
        await message.answer_document(
            BufferedInputFile(data, filename=name),
            caption="\U0001F4C4 Barcha yozilgan xabarlar (kanal bo'yicha).",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("[CH-DUMP] job: %s", exc)
        await message.answer(f"\u274C Xato: {type(exc).__name__}: {exc}")


async def _ocr_job(message: Message, per: int) -> None:
    """v48: jarayon ko'rsatkichi bilan OCR."""
    from app.services import channel_archive as arc

    state = {"t": 0.0, "txt": ""}

    async def _edit(text: str) -> None:
        try:
            await message.edit_text(text, parse_mode="HTML")
        except Exception:  # noqa: BLE001
            pass

    def _prog(done: int, total: int, name: str) -> None:
        import time as _t
        now = _t.time()
        if now - float(state["t"]) < 6:
            return
        state["t"] = now
        txt = (f"\U0001F524 <b>OCR: {done}/{total}</b>\n"
               f"hozir: {name}\n<i>(tesseract ~3s/rasm — kuting)</i>")
        try:
            asyncio.get_running_loop().create_task(_edit(txt))
        except Exception:  # noqa: BLE001
            pass

    try:
        res = await arc.ocr_pass(per_channel=per, progress=_prog)
        lines = ["\U0001F524 <b>OCR tugadi</b>", ""]
        lines.append(
            f"o'qildi: <b>{res.get('done')}</b> | bo'sh: {res.get('empty')} | "
            f"o'tkazildi: {res.get('skip')} | xato: {res.get('fail')} | {res.get('secs')}s"
        )
        for st in (res.get("per") or [])[:15]:
            lines.append(f"\u2022 {st['name']}: \u2705 {st['done']} \u2796 {st['empty']} \u274C {st['fail']}")
        if res.get("errors"):
            lines.append("")
            lines.append("<b>Xatolar (namuna):</b>")
            for e in res["errors"][:3]:
                lines.append(f"\u2022 <code>{e[:160]}</code>")
        if res.get("error"):
            lines.append(f"\u274C {res['error']}")
        await message.answer("\n".join(lines), parse_mode="HTML")
        name, data = await arc.export_txt()
        await message.answer_document(BufferedInputFile(data, filename=name),
                                      caption="\U0001F4C4 OCR qo'shilgan fayl.")
    except Exception as exc:  # noqa: BLE001
        logger.exception("[CH-DUMP] ocr: %s", exc)
        await message.answer(f"\u274C Xato: {type(exc).__name__}: {exc}")


@router.message(Command("100"))
async def cmd_dump100(message: Message) -> None:
    """Barcha kanallardan oxirgi 100 tadan xabarni bazaga yozadi."""
    global _DUMP_TASK
    if not _is_admin(getattr(message.from_user, "id", None)):
        return
    if _DUMP_TASK and not _DUMP_TASK.done():
        await message.reply("\u23F3 Avvalgi yozib olish tugamadi. Kuting...")
        return
    limit = 100
    for part in (message.text or "").split()[1:]:
        if part.isdigit():
            limit = max(5, min(int(part), 300))
    await message.reply(
        f"\u23F3 <b>{limit}</b> tadan xabar yozib olinmoqda (reply lar bilan)...\n"
        "1-3 daqiqa. Tugagach fayl yuboraman.",
        parse_mode="HTML",
    )
    _DUMP_TASK = asyncio.create_task(_dump_job(message, limit))


@router.message(Command("100ocr"))
async def cmd_dump100ocr(message: Message) -> None:
    """Rasm xabarlaridagi yozuvni OCR qilib bazaga qo'shadi."""
    global _DUMP_TASK
    if not _is_admin(getattr(message.from_user, "id", None)):
        return
    if _DUMP_TASK and not _DUMP_TASK.done():
        await message.reply("\u23F3 Avvalgi vazifa tugamadi. Kuting...")
        return
    per = 20
    for part in (message.text or "").split()[1:]:
        if part.isdigit():
            per = max(3, min(int(part), 100))
    await message.reply(
        f"\U0001F524 Har kanaldan <b>{per}</b> ta rasm o'qilmoqda (tesseract ~3s/rasm).\n"
        "Jarayonni shu xabarda ko'rsatib turaman.",
        parse_mode="HTML",
    )
    _DUMP_TASK = asyncio.create_task(_ocr_job(message, per))


@router.message(Command("100test"))
async def cmd_dump100test(message: Message) -> None:
    """Diagnostika: OCR zanjirini qadam-baqadam tekshiradi."""
    global _DUMP_TASK
    if not _is_admin(getattr(message.from_user, "id", None)):
        return
    if _DUMP_TASK and not _DUMP_TASK.done():
        await message.reply("\u23F3 Avvalgi vazifa tugamadi. Kuting...")
        return
    await message.reply("\U0001F9EA Tekshirilmoqda (10-20 soniya)...")

    async def _job() -> None:
        from app.services import channel_archive as arc

        try:
            rep = await arc.test_one()
        except Exception as exc:  # noqa: BLE001
            await message.answer(f"\u274C Xato: {type(exc).__name__}: {exc}")
            return
        lines = ["\U0001F9EA <b>Diagnostika natijasi</b>", ""]
        for st in rep.get("steps", []):
            mark = "\u2705" if st.startswith("ok") else "\u26A0\uFE0F"
            lines.append(f"{mark} {st.split(':', 1)[-1].strip()}")
        await message.answer("\n".join(lines), parse_mode="HTML")

    _DUMP_TASK = asyncio.create_task(_job())


@router.message(Command("100stat"))
async def cmd_dump100stat(message: Message) -> None:
    if not _is_admin(getattr(message.from_user, "id", None)):
        return
    from app.services import channel_archive as arc

    st = await arc.stats()
    lines = [f"\U0001F5C3 Bazadagi xabarlar: <b>{st.get('total')}</b>", ""]
    for c in (st.get("channels") or [])[:20]:
        lines.append(f"\u2022 {c['title'] or c['key']}: <b>{c['n']}</b> ta")
    if st.get("error"):
        lines.append(f"\u274C {st['error']}")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("100fayl"))
async def cmd_dump100file(message: Message) -> None:
    if not _is_admin(getattr(message.from_user, "id", None)):
        return
    from app.services import channel_archive as arc

    name, data = await arc.export_txt()
    await message.answer_document(BufferedInputFile(data, filename=name),
                                  caption="\U0001F4C4 Bazadagi barcha xabarlar.")
# ===============================================================================



@router.message(ChannelState.menu, F.text == "⬅️ Orqaga")
async def channels_back(message: Message, state) -> None:
    if message.from_user:
        _login_tmp.pop(message.from_user.id, None)
        _ch_flow.discard(message.from_user.id)
    await state.clear()
    await message.answer(
        "🏠 <b>Asosiy menyuga qaytdingiz.</b>\nPastdan bo'limni tanlang 👇",
        parse_mode="HTML",
        reply_markup=kb.main_menu_reply(message.from_user.id if message.from_user else None),
    )


@router.message(F.text == "🔎 Holat")
@router.message(ChannelState.menu, F.text == "🔎 Holat")
async def channel_status(message: Message) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Faqat admin.")
        return
    from app.services.channel_user import is_linked
    from app.services.channel_watcher import get_status
    st = get_status()
    linked = await is_linked()
    rec = st.get("recent") or []
    rec_txt = "\n".join(f"• {x}" for x in rec[:12]) or "—"
    ok = ", ".join(st.get("channels_ok") or []) or "—"
    fail = ", ".join(st.get("channels_fail") or []) or "—"
    await message.answer(
        "🔎 <b>KANAL KUZATUVI</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        f"👤 Akkaunt: {'✅ ulangan' if linked else '❌ ulanmagan'}\n"
        f"📡 Telethon: {'✅ ' + str(st.get('account') or '') if st.get('authorized') else '❌ oqimayapti'}\n"
        f"👁 Ko'rilgan xabar: <b>{st.get('seen') or 0}</b>\n"
        f"⏱ Oxirgi poll: {st.get('last_poll_local') or '—'} (Toshkent)\n"
        f"✅ O'qiladi: {ok}\n"
        f"⚠️ Topilmadi: {fail}\n"
        f"Xato: {st.get('last_error') or '—'}\n"
        "━━━━━━━━━━━━━━━━\n"
        "<b>Ishonchli yo'l:</b> kanal xabarini shu botga <b>forward</b> qiling.\n"
        "Bot kanalga admin bo'lishi shart emas.\n\n"
        f"<pre>{rec_txt}</pre>",
        parse_mode="HTML",
        reply_markup=kb.channels_reply(True),
    )


@router.message(F.text == "➕ Qo'shish")
@router.message(ChannelState.menu, F.text == "➕ Qo'shish")
async def ask_add(message: Message, state) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Faqat admin kanal qo'sha oladi.")
        return
    _ch_flow.add(message.from_user.id)
    await state.set_state(ChannelState.awaiting_add)
    await message.answer(
        "➕ Kanal qo'shish:\n"
        "• <code>@kanal_nomi</code> yuboring\n"
        "• yoki <code>t.me/kanal_nomi</code>\n"
        "• yoki kanaldan bitta xabarni shu yerga <b>forward</b> qiling\n\n"
        "Botni kanalga qo'shish shart emas.\nBekor: ⬅️ Orqaga.",
        parse_mode="HTML",
        reply_markup=kb.channels_reply(True),
    )


@router.message(ChannelState.awaiting_add, F.text == "⬅️ Orqaga")
async def add_cancel(message: Message, state) -> None:
    if message.from_user:
        _ch_flow.discard(message.from_user.id)
    await state.set_state(ChannelState.menu)
    async with async_session_factory() as session:
        text = await _menu_text(session, True)
    await message.answer(text, parse_mode="HTML", reply_markup=kb.channels_reply(True))


@router.message(ChannelState.awaiting_add)
async def do_add(message: Message, state) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Faqat admin.")
        return
    chat = getattr(message, "forward_from_chat", None)
    if chat is None:
        orig = getattr(message, "forward_origin", None)
        chat = getattr(orig, "chat", None) if orig is not None else None
    username = None
    chat_id = None
    title = ""
    kind = "public"
    if chat is not None:
        chat_id = int(chat.id)
        username = getattr(chat, "username", None)
        title = getattr(chat, "title", None) or ""
        kind = "public" if username else "private"
    else:
        username = _extract_username(message.text or "")
        if not username:
            await message.answer(
                "⚠️ Tushunmadim. @username yuboring yoki xabarni forward qiling.",
                reply_markup=kb.channels_reply(True),
            )
            return
        kind = "public"
    if message.from_user:
        _ch_flow.discard(message.from_user.id)
    async with async_session_factory() as session:
        ok, msg, _ch = await add_channel(
            session, username=username, chat_id=chat_id, title=title, kind=kind,
        )
        head = ("✅ Kanal ulandi — endi shu kanaldan signallar o'qiladi.\n"
                if ok else "⚠️ ")
        text = head + msg + "\nℹ️ Eski xabarlar o'qilmaydi — faqat YANGI postlar.\n\n" \
            + await _menu_text(session, True)
    await state.set_state(ChannelState.menu)
    await message.answer(text, parse_mode="HTML", reply_markup=kb.channels_reply(True))
    if ok:
        # yangi kanal DARHOL kuzatuvga qo'shiladi (event) — poll kutmasdan o'qiladi
        _spawn(_reload_watcher())


@router.message(F.text == "➖ O'chirish")
@router.message(ChannelState.menu, F.text == "➖ O'chirish")
async def ask_remove(message: Message, state) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Faqat admin o'chira oladi.")
        return
    _ch_flow.add(message.from_user.id)
    await state.set_state(ChannelState.awaiting_remove)
    await message.answer(
        "➖ Qaysi kanalni o'chiramiz? Pastdagi tugmani bosing yoki "
        "<code>@username</code> yuboring.\nBekor: ⬅️ Orqaga.",
        parse_mode="HTML", reply_markup=kb.channels_reply(True),
    )
    async with async_session_factory() as session:
        chans = await list_channels(session)
    ikb = _channels_inline(chans)
    if ikb is not None:
        await message.answer(_DEL_HINT, parse_mode="HTML", reply_markup=ikb)
    else:
        await message.answer("ℹ️ Hozir ulangan kanal yo'q — o'chiradigan narsa ham yo'q.")


@router.message(ChannelState.awaiting_remove, F.text == "⬅️ Orqaga")
async def remove_cancel(message: Message, state) -> None:
    if message.from_user:
        _ch_flow.discard(message.from_user.id)
    await state.set_state(ChannelState.menu)
    async with async_session_factory() as session:
        text = await _menu_text(session, True)
    await message.answer(text, parse_mode="HTML", reply_markup=kb.channels_reply(True))


@router.message(ChannelState.awaiting_remove, F.text)
async def do_remove(message: Message, state) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Faqat admin.")
        return
    key = _extract_username(message.text or "") or (message.text or "").lstrip("@").strip()
    if not key:
        await message.answer("⚠️ @username yuboring.")
        return
    if message.from_user:
        _ch_flow.discard(message.from_user.id)
    async with async_session_factory() as session:
        ok, msg = await remove_channel(session, key)
        text = ("✅ " if ok else "⚠️ ") + msg + "\n\n" + await _menu_text(session, True)
        chans = await list_channels(session)
    await state.set_state(ChannelState.menu)
    await message.answer(text, parse_mode="HTML", reply_markup=kb.channels_reply(True))
    ikb = _channels_inline(chans)
    if ikb is not None:
        await message.answer(_DEL_HINT, parse_mode="HTML", reply_markup=ikb)
    if ok:
        _spawn(_reload_watcher())


# =========== v66/v71: inline tugma orqali o'chirish (bir bosish) ===========

async def _del_one(session, ch: dict) -> tuple[bool, str, list[dict]]:
    """Bitta kanalni o'chiradi va qolganlar ro'yxatini qaytaradi."""
    key = (ch.get("username") or "").strip().lstrip("@") or str(ch.get("chat_id") or "")
    ok, msg = await remove_channel(session, key)
    left = await list_channels(session)
    return ok, msg, left


def _snapshot(ch: dict) -> dict:
    """Qaytarish uchun kanal nusxasi."""
    return {
        "username": (ch.get("username") or "") or None,
        "chat_id": ch.get("chat_id"),
        "title": ch.get("title") or "",
        "kind": ch.get("kind") or ("public" if ch.get("username") else "private"),
    }


@router.callback_query(F.data.startswith("chdel:"))
async def cb_del_pick(cq: CallbackQuery) -> None:
    """🗑 tugmasi bosildi -> kanal DARHOL o'chiriladi (tasdiq yo'q, bir bosish)."""
    uid = cq.from_user.id if cq.from_user else 0
    if not _is_admin(uid):
        await cq.answer("Faqat admin.", show_alert=True)
        return
    raw = (cq.data or "").split(":", 1)[1]
    async with async_session_factory() as session:
        chans = await list_channels(session)
        if not raw.isdigit() or int(raw) >= len(chans):
            await cq.answer("Kanal topilmadi — ro'yxatni yangilang.", show_alert=True)
            return
        ch = chans[int(raw)]
        name = display_name(ch)
        ok, msg, left = await _del_one(session, ch)
        text = await _menu_text(session, True)
    if ok:
        _LAST_DEL[uid] = {"items": [_snapshot(ch)], "ts": datetime.now(timezone.utc)}
        _spawn(_reload_watcher())
    await cq.answer("✅ O'chirildi: " + name if ok else "⚠️ Xato")
    if cq.message:
        try:
            await cq.message.edit_reply_markup(reply_markup=None)
        except Exception:  # noqa: BLE001
            pass
        tail = "" if ok else "\n<i>Qaytadan urinib ko'ring.</i>"
        await cq.message.answer(
            ("\u2705 <b>O'chirildi:</b> " + _esc_html(name) + tail if ok
             else "\u26A0\uFE0F " + _esc_html(msg)),
            parse_mode="HTML", reply_markup=_undo_kb(ok),
        )
        await cq.message.answer(text, parse_mode="HTML", reply_markup=kb.channels_reply(True))
        ikb = _channels_inline(left)
        if ikb is not None:
            await cq.message.answer(_DEL_HINT, parse_mode="HTML", reply_markup=ikb)


@router.callback_query(F.data.startswith("chdely:"))
async def cb_del_yes(cq: CallbackQuery) -> None:
    """Eski (v66) tasdiq tugmasi — moslik uchun: xuddi bitta bosish kabi o'chiradi."""
    await cb_del_pick(cq)


@router.callback_query(F.data == "chdelall")
async def cb_del_all_ask(cq: CallbackQuery) -> None:
    """«Hammasini o'chirish» — bu yerda tasdiq so'raladi (ko'p kanal)."""
    if not _is_admin(cq.from_user.id if cq.from_user else None):
        await cq.answer("Faqat admin.", show_alert=True)
        return
    async with async_session_factory() as session:
        chans = await list_channels(session)
    await cq.answer()
    if cq.message:
        await cq.message.answer(
            "🗑 <b>Hamma kanal o'chirilsinmi?</b> (%d ta)\n"
            "Keyin qaytarish tugmasi bilan qaytarish mumkin." % len(chans),
            parse_mode="HTML", reply_markup=_del_confirm_kb(),
        )


@router.callback_query(F.data == "chdelyall")
async def cb_del_all(cq: CallbackQuery) -> None:
    """BARCHA kanallarni o'chiradi (bitta bosishda, tasdiqdan keyin)."""
    uid = cq.from_user.id if cq.from_user else 0
    if not _is_admin(uid):
        await cq.answer("Faqat admin.", show_alert=True)
        return
    async with async_session_factory() as session:
        chans = await list_channels(session)
        snaps = [_snapshot(c) for c in chans]
        n = 0
        for ch in chans:
            key = (ch.get("username") or "").strip().lstrip("@") or str(ch.get("chat_id") or "")
            ok, _m = await remove_channel(session, key)
            n += 1 if ok else 0
        left = await list_channels(session)
        text = await _menu_text(session, True)
    if n:
        _LAST_DEL[uid] = {"items": snaps, "ts": datetime.now(timezone.utc)}
        _spawn(_reload_watcher())
    await cq.answer("✅ %d ta o'chirildi" % n)
    if cq.message:
        try:
            await cq.message.edit_reply_markup(reply_markup=None)
        except Exception:  # noqa: BLE001
            pass
        await cq.message.answer(
            "\u2705 <b>%d ta kanal o'chirildi.</b>" % n,
            parse_mode="HTML", reply_markup=_undo_kb(bool(n)),
        )
        await cq.message.answer(text, parse_mode="HTML", reply_markup=kb.channels_reply(True))
        ikb = _channels_inline(left)
        if ikb is not None:
            await cq.message.answer(_DEL_HINT, parse_mode="HTML", reply_markup=ikb)


@router.callback_query(F.data == "chundo")
async def cb_del_undo(cq: CallbackQuery) -> None:
    """«↩️ Qaytarish» — oxirgi o'chirilgan kanal(lar)ni qaytaradi."""
    uid = cq.from_user.id if cq.from_user else 0
    if not _is_admin(uid):
        await cq.answer("Faqat admin.", show_alert=True)
        return
    saved = _LAST_DEL.pop(uid, None) or {}
    items = saved.get("items") or []
    if not items:
        await cq.answer("Qaytarish uchun kanal yo'q.", show_alert=True)
        return
    back = 0
    async with async_session_factory() as session:
        for it in items:
            try:
                ok, _m, _ch = await add_channel(
                    session, username=it.get("username"), chat_id=it.get("chat_id"),
                    title=it.get("title") or "", kind=it.get("kind") or "public",
                )
                back += 1 if ok else 0
            except Exception as exc:  # noqa: BLE001
                logger.warning("[CH] qaytarish: %s", exc)
        text = await _menu_text(session, True)
        left = await list_channels(session)
    if back:
        _spawn(_reload_watcher())
    names = ", ".join((i.get("username") and "@" + i["username"])
                      or (i.get("title") or str(i.get("chat_id"))) for i in items[:5])
    await cq.answer("↩️ Qaytarildi: %d ta" % back)
    if cq.message:
        try:
            await cq.message.edit_reply_markup(reply_markup=None)
        except Exception:  # noqa: BLE001
            pass
        await cq.message.answer(
            "\u21A9\uFE0F <b>Qaytarildi (%d ta):</b> %s" % (back, _esc_html(names)),
            parse_mode="HTML", reply_markup=kb.channels_reply(True),
        )
        await cq.message.answer(text, parse_mode="HTML")
        ikb = _channels_inline(left)
        if ikb is not None:
            await cq.message.answer(_DEL_HINT, parse_mode="HTML", reply_markup=ikb)


@router.callback_query(F.data == "chdelno")
async def cb_del_no(cq: CallbackQuery) -> None:
    await cq.answer("Bekor qilindi.")
    if cq.message:
        try:
            await cq.message.edit_reply_markup(reply_markup=None)
        except Exception:  # noqa: BLE001
            pass


@router.message(Command("tozalash"))
@router.message(Command("forget"))
async def cmd_wipe(message: Message) -> None:
    """\U0001F9F9 Signallar/statistika tozalanadi. ULANGAN KANALLAR SAQLANADI (v65)."""
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer("\U0001F9F9 Tozalash — faqat admin.")
        return
    await message.answer(
        "\U0001F9F9 <b>TOZALASH — bot hamma narsani unutadi</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "\u2022 barcha signallar (raqamlash \u21161 dan boshlanadi)\n"
        "\u2022 paper (virtual) hisob va pozitsiyalar\n"
        "\u2022 strategiya + kanal statistikasi\n"
        "\n"
        "\u2705 Akkaunt ulanishi SAQLANADI — QR/kod kerak emas.\n"
        "\U0001F4E1 <b>Ulangan kanallar SAQLANADI</b> — kanallar o'chib ketmaydi.\n"
        "\u2139\uFE0F Kanal qo'shilganda eski xabarlar O'QILMAYDI — faqat YANGI postlar.\n"
        "\n"
        "Davom etamizmi?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="\u2705 Ha, tozala", callback_data="wipeok"),
            InlineKeyboardButton(text="\u274C Bekor", callback_data="wipeno"),
        ]]),
    )


@router.callback_query(F.data == "wipeno")
async def wipe_cancel(cb: CallbackQuery) -> None:
    await cb.answer("Bekor qilindi.")
    if cb.message is not None:
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:  # noqa: BLE001
            pass
        await cb.message.answer(
            "\u274C Tozalash bekor qilindi — hech narsa o'chirilmadi.",
            reply_markup=kb.channels_reply(True),
        )


@router.callback_query(F.data == "wipeok")
async def wipe_confirm(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("Faqat admin.", show_alert=True)
        return
    await cb.answer("Tozalanmoqda...")
    if cb.message is None:
        return
    from app.services.wipe import report_text, wipe_all
    try:
        res = await wipe_all(drop_channels=False)  # v65: kanallar SAQLANADI
    except Exception as exc:  # noqa: BLE001
        logger.exception("[TOZALASH] %s", exc)
        await cb.message.answer(f"\u274C Tozalashda xato: {exc}")
        return
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass
    _spawn(_reload_watcher())
    await cb.message.answer(
        report_text(res), parse_mode="HTML", reply_markup=kb.channels_reply(True),
    )


_LOGIN_SKIP = _MENU_BTNS


def _only_digits(text: str | None) -> str:
    return "".join(c for c in (text or "") if c.isdigit())


def _code_hint(delivery: str = "", phone: str = "") -> str:
    from app.services.channel_user import delivery_text
    raqam = f"\n📱 Raqam: <code>{phone}</code> — kod aynan shu raqamning "\
            f"Telegram akkauntiga keladi." if phone else ""
    return (
        delivery_text(delivery) + raqam + "\n\n"
        "Kodni <b>shundayligicha</b> yuboring — faqat raqamlar ham bo'ladi:\n"
        "<code>12345</code>  yoki  <code>A12345</code>  yoki  <code>12 345</code>\n"
        "Harf va bo'shliqni bot o'zi olib tashlaydi.\n\n"
        "Kod kelmasa: <b>qayta</b> (yana urinish) · <b>sms</b> (qo'shimcha urinish)\n"
        "Bekor qilish: <b>bekor</b>\n\n"
        "⚠️ Kod so'rashni tez-tez takrorlamang — Telegram cheklov (flood) qo'yadi.\n"
        "💡 Akkaunt kerak bo'lmasa: kanalga <b>botni admin</b> qilib qo'shsangiz, "
        "postlar to'g'ridan-to'g'ri botga keladi."
    )


def _digit_code(text: str | None) -> str:
    """Foydalanuvchi yozgan koddan raqamlarni ajratadi (3-8 xona)."""
    d = "".join(c for c in (text or "") if c.isdigit())
    return d if 3 <= len(d) <= 8 else ""


class LoginInProgress(Filter):
    """FSM emas — xotira. Shuning uchun /akkaunt doim javob beradi."""

    async def __call__(self, message: Message) -> bool:
        user = message.from_user
        if user is None or not _is_admin(user.id):
            return False
        step = (_login_tmp.get(user.id) or {}).get("step")
        if not step:
            return False
        t = (message.text or "").strip()
        if t in _LOGIN_SKIP or (t.startswith("/") and len(t) > 1):
            return False
        return True


@router.message(Command("akkaunt"))
@router.message(F.text.in_(_BTN_AKKAUNT))
async def account_start(message: Message, state) -> None:
    """Har qanday holatdan qayta boshlanadi."""
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Faqat admin akkaunt ulaydi.")
        return
    uid = message.from_user.id
    _login_tmp[uid] = {"step": "api_id"}
    await state.clear()
    from app.services.channel_user import session_status
    extra = ""
    st = await session_status()
    if st.get("alive"):
        extra = (f"Akkaunt ulangan va <b>tirik</b>: {st.get('account') or '—'}"
                 f" · kanallar: {st.get('channels', 0)}\n"
                 f"Qayta ulash (sessiya yangilanadi):\n\n")
    elif st.get("has_session"):
        extra = ("⚠️ Saqlangan sessiya <b>o'chgan</b> "
                 f"({st.get('error') or 'Telegram bekor qilgan'}).\n"
                 "Kanallar o'qilmayapti — qayta ulanamiz:\n\n")
    elif st.get("has_api"):
        extra = "api_id/api_hash bor, lekin akkaunt ulanmagan. Telefon va kod kerak:\n\n"
    await message.answer(
        "👤 <b>Telegram akkaunt ulash</b>\n"
        f"{extra}"
        "Botni kanalga qo'shmaymiz.\n\n"
        "1) my.telegram.org → API development tools\n"
        "2) <b>api_id</b> ni yuboring (raqam, nusxa ham bo'ladi)\n\n"
        "Kod umuman kelmasa (Telegram cheklovi): <b>/qr</b> — QR bilan ulash,\n"
        "kod ham, SMS ham kerak bo'lmaydi.\n\n"
        "Bekor: ⬅️ Orqaga yoki /menu",
        parse_mode="HTML",
        reply_markup=kb.channels_reply(True),
    )


def _qr_kb(link: str) -> InlineKeyboardMarkup:
    """«Havolani ochish» + «To'xtatish» tugmalari (tg://login ni Telegram o'zi tasdiqlaydi)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001F449 Havolani ochish (bosing)", url=link)],
        [InlineKeyboardButton(text="\u23F9 To'xtatish", callback_data="qrstop")],
    ])


def _qr_caption() -> str:
    return (
        "\U0001F533 <b>QR bilan ulash</b> — kod kerak emas.\n\n"
        "1) Pastdagi <b>«Havolani ochish»</b> tugmasini bosing.\n"
        "2) Telegram «Kirishni tasdiqlaysizmi?» deb so'raydi -> <b>Tasdiqlash</b>.\n\n"
        "Tugma ishlamasa: rasmdagi QR ni Telegram o'rnatilgan boshqa qurilma "
        "(kompyuter/ikkinchi telefon) bilan skanerlang.\n\n"
        f"\u23F3 Havola ~{_QR_TTL} soniyada eskiradi — shu xabarning O'ZI yangilanib turadi "
        "(yangi xabar kelmaydi).\n"
        "\u2139\uFE0F Telegram ilovangiz (telefon yoki Desktop) <b>so'nggi versiyada</b> bo'lsin: "
        "eski versiyada «app version is outdated» xatosi chiqadi.\n"
        "To'xtatish: <b>bekor</b> yoki pastdagi <b>\u23F9 To'xtatish</b> tugmasi"
    )


async def _qr_send(message: Message, link: str, png, target=None):
    """QR xabari: `target` bo'lsa O'SHA xabar tahrirlanadi (yangi xabar YUBORILMAYDI)."""
    caption = _qr_caption()
    if target is not None:
        if png:
            try:
                await target.edit_media(
                    media=InputMediaPhoto(
                        media=BufferedInputFile(png, filename="sino_qr.png"),
                        caption=caption, parse_mode="HTML",
                    ),
                    reply_markup=_qr_kb(link),
                )
                return target
            except Exception as exc:  # noqa: BLE001
                logger.info("[AKKAUNT] QR rasm tahrirlanmadi: %s", exc)
        try:
            await target.edit_reply_markup(reply_markup=_qr_kb(link))
        except Exception as exc:  # noqa: BLE001
            logger.info("[AKKAUNT] QR tugma tahrirlanmadi: %s", exc)
        return target
    try:
        if png:
            return await message.answer_photo(
                BufferedInputFile(png, filename="sino_qr.png"),
                caption=caption, parse_mode="HTML", reply_markup=_qr_kb(link),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AKKAUNT] QR rasm yuborilmadi: %s", exc)
    return await message.answer(caption, parse_mode="HTML", reply_markup=_qr_kb(link))


async def _login_done(message: Message, state=None) -> None:
    """Ulanishdan keyingi umumiy yakun: kuzatuvni qayta ishga tushirib, hisobot."""
    if state is not None:
        try:
            await state.set_state(ChannelState.menu)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AKKAUNT] holat: %s", exc)
    try:
        from app.services.channel_watcher import restart_watcher
        await restart_watcher()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AKKAUNT] watcher: %s", exc)
    st = {}
    try:
        from app.services.channel_user import session_status
        st = await session_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AKKAUNT] status: %s", exc)
    await message.answer(
        "✅ <b>Akkaunt ulandi.</b>\n"
        f"\U0001F464 {st.get('account') or '—'} · \U0001F4E1 kanallar: {st.get('channels', 0)}\n"
        "Kanallar kuzatilmoqda, signallar keladi.\n"
        "\u2139\uFE0F Eski xabarlar o'qilmaydi — faqat <b>yangi</b> postlar signal bo'ladi.",
        parse_mode="HTML",
        reply_markup=kb.channels_reply(True),
    )
    # Qaysi kanallar ulanganini TO'LIQ ko'rsatamiz (ro'yxat + statistika)
    try:
        async with async_session_factory() as session:
            menu = await _menu_text(session, True)
        await message.answer(menu, parse_mode="HTML", reply_markup=kb.channels_reply(True))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AKKAUNT] kanal ro'yxati: %s", exc)


async def _qr_loop(message: Message, msg=None, state=None) -> None:
    """Havolani bitta xabarni TAHRIRLAB yangilab turadi va tasdiqni kutadi."""
    from app.services.channel_user import qr_active, qr_step
    uid = message.from_user.id
    for _ in range(60):
        if not qr_active():
            return                    # to'xtatildi: «bekor» yoki ⏹ tugma
        res = await qr_step()
        state_name = res.get("state")
        if state_name == "ok":
            _login_tmp.pop(uid, None)
            if msg is not None:
                try:
                    await msg.edit_caption(caption="\u2705 Tasdiqlandi.", parse_mode="HTML")
                    await msg.edit_reply_markup(reply_markup=None)
                except Exception:  # noqa: BLE001
                    pass
            await _login_done(message, state)
            return
        if state_name == "password":
            _login_tmp[uid] = {"step": "qr2fa"}
            await message.answer(
                "\U0001F510 <b>Ikki bosqichli parol</b> kerak (QR tasdiqlandi).\n"
                "Telegram -> Sozlamalar -> Maxfiylik -> Two-Step Verification paroli.\n"
                "Parolni yozib yuboring. Bekor: <b>bekor</b>",
                parse_mode="HTML",
            )
            return
        if state_name == "new":
            msg = await _qr_send(message, str(res.get("link") or ""), res.get("qr"), target=msg)
            continue
        if not qr_active():
            return          # to'xtatilgan (bekor / ⏹) — jimgina chiqamiz, xabar yozmaymiz
        await message.answer("⚠️ " + str(res.get("msg") or "QR xatosi"))
        return
    await message.answer("\u23F3 Vaqt tugadi. /qr bilan qayta urinib ko'ring.")


@router.message(Command("qr"))
async def account_qr(message: Message, state) -> None:
    """QR bilan ulash — Telegram kod yubormayotganda ham ishlaydi."""
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Faqat admin akkaunt ulaydi.")
        return
    from app.services.channel_user import qr_begin
    res = await qr_begin()
    if res.get("err"):
        await message.answer("⚠️ " + str(res["err"]), parse_mode="HTML")
        return
    uid = message.from_user.id
    await state.clear()
    _login_tmp[uid] = {"step": "qr"}
    first = await _qr_send(message, str(res.get("link") or ""), res.get("qr"))
    await _qr_loop(message, first, state)


@router.callback_query(F.data == "qrstop")
async def qr_stop(cb: CallbackQuery, state) -> None:
    """\u23F9 tugma — QR oqimini shu zahoti to'xtatadi (xabar oqimi ham to'xtaydi)."""
    from app.services.channel_user import qr_cancel
    await qr_cancel()
    if cb.from_user:
        _login_tmp.pop(cb.from_user.id, None)
    try:
        await cb.message.edit_caption(
            caption="\u23F9 QR to'xtatildi. /qr bilan qayta boshlashingiz mumkin.",
            parse_mode="HTML",
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass
    try:
        await cb.answer("QR to'xtatildi")
    except Exception:  # noqa: BLE001
        pass


@router.message(LoginInProgress(), F.text)
async def account_wizard(message: Message, state) -> None:
    uid = message.from_user.id
    tmp = _login_tmp.setdefault(uid, {})
    step = tmp.get("step")
    t = (message.text or "").strip()
    try:
        if step == "api_id":
            raw = _only_digits(t)
            if len(raw) < 5:
                await message.answer("api_id kamida 5 ta raqam. Qayta yuboring.")
                return
            tmp["api_id"] = int(raw)
            tmp["step"] = "api_hash"
            await message.answer(
                f"✅ api_id: <code>{raw}</code>\nEndi <b>api_hash</b> ni yuboring.",
                parse_mode="HTML",
            )
            return
        if step == "api_hash":
            h = t.replace(" ", "")
            if len(h) < 16:
                await message.answer("api_hash juda qisqa. Qayta yuboring.")
                return
            tmp["api_hash"] = h
            tmp["step"] = "phone"
            await message.answer(
                "✅ api_hash qabul.\n\n"
                "O'zingizning telefon raqamingizni yuboring.\n"
                "Format: +998881234567",
            )
            return
        if step == "phone":
            phone = t.replace(" ", "").replace("-", "")
            if phone.isdigit() and phone.startswith("998"):
                phone = "+" + phone
            if not phone.startswith("+") or len(_only_digits(phone)) < 10:
                await message.answer("Format: +998881234567")
                return
            from app.services.channel_user import start_login
            err, kind = await start_login(
                int(tmp.get("api_id") or 0), str(tmp.get("api_hash") or ""), phone)
            if err:
                await message.answer(f"⚠️ {err}" + ("" if "kutish" not in err else ""))
                return
            tmp["phone"] = phone
            tmp["step"] = "code"
            tmp["delivery"] = kind
            await message.answer(_code_hint(kind, phone), parse_mode="HTML")
            return
        if step == "code":
            from app.services.channel_user import finish_login, resend_code, pending_info
            low = t.lower().strip()
            if low in {"bekor", "orqaga", "yo'q", "cancel"}:
                _login_tmp.pop(uid, None)
                await state.clear()
                await message.answer("Bekor qilindi. /akkaunt bilan qayta boshlashingiz mumkin.")
                return
            if low in {"qayta", "kod", "yangi", "resend", "sms"}:
                force = low == "sms"
                err, kind = await resend_code(force_sms=force)
                if err:
                    head = "⚠️ Qo'shimcha urinish ishlamadi.\n" if force else ""
                    await message.answer(head + err, parse_mode="HTML")
                    return
                tmp["delivery"] = kind
                head = ("🔄 Qo'shimcha urinish qilindi (Telegram SMS majburiy qilib "
                        "bo'lmaydi — qarorni o'zi qabul qiladi).") if force else \
                       "🔄 Yangi kod so'raldi."
                await message.answer(
                    head + "\n\n" + _code_hint(kind, tmp.get("phone") or ""),
                    parse_mode="HTML",
                )
                return
            code_in = _digit_code(t)
            if not code_in:
                info = await pending_info()
                if not info.get("phone"):
                    await message.answer("Avval telefon raqamingizni yuboring: /akkaunt")
                    return
                await message.answer(
                    "⚠️ Kodni raqam bilan yuboring (3-8 xona).\n"
                    "Masalan: <code>12345</code> yoki <code>A12345</code>\n"
                    "Yangi urinish: <b>qayta</b> · qo'shimcha urinish: <b>sms</b>",
                    parse_mode="HTML",
                )
                return
            err = await finish_login(code_in)
            if err == "2FA_NEEDED":
                tmp["step"] = "2fa"
                from app.services.channel_user import twofa_hint
                hint = await twofa_hint()
                extra = f"\nEslatma: <code>{hint}</code>" if hint else ""
                await message.answer(
                    "🔐 <b>Ikki bosqichli parol</b> kerak.\n"
                    "Telegram → Sozlamalar → Maxfiylik → Two-Step Verification.\n"
                    "Telefon qulfi EMAS. Katta-kichik harf muhim."
                    f"{extra}\n\n"
                    "Parolni yuboring. Bekor: ⬅️ Orqaga yoki /start",
                    parse_mode="HTML",
                )
                return
            if err == "EXPIRED":
                await message.answer(
                    "⚠️ Bu kod eskirgan (yoki almashtirilgan).\n"
                    "Yangi kod kerak — <b>qayta</b> deb yozing.\n"
                    "(SMS kerak bo'lsa: <b>sms</b>)",
                    parse_mode="HTML",
                )
                return
            if err == "INVALID":
                await message.answer(
                    "⚠️ Kod noto'g'ri. Ilojadagi kodni <b>to'liq</b> yozing: "
                    "<code>12345</code>\n"
                    "Yangi kod kerak: <b>qayta</b> · SMS kerak: <b>sms</b>",
                    parse_mode="HTML",
                )
                return
            if err:
                await message.answer(f"⚠️ {err}")
                return
            _login_tmp.pop(uid, None)
            await state.clear()
            await _login_done(message, state)
            return
        if step == "qr":
            from app.services.channel_user import qr_cancel
            if t.lower().strip() in {"bekor", "orqaga", "yo'q", "cancel"}:
                await qr_cancel()
                _login_tmp.pop(uid, None)
                await message.answer("QR bekor qilindi. /qr bilan qayta boshlang.")
                return
            await message.answer(
                "🔳 QR kutilmoqda — yuqoridagi <b>«Havolani ochish»</b> tugmasini bosing "
                "(yoki QR rasmni skanerlang).\nBekor qilish: <b>bekor</b>",
                parse_mode="HTML",
            )
            return
        if step == "qr2fa":
            from app.services.channel_user import qr_cancel, qr_password
            if t.lower().strip() in {"bekor", "orqaga", "cancel"}:
                await qr_cancel()
                _login_tmp.pop(uid, None)
                await message.answer("QR bekor qilindi.")
                return
            err = await qr_password(t)
            if err == "2FA_WRONG":
                await message.answer(
                    "⚠️ Parol Telegramda mos kelmadi (katta-kichik harf muhim).\n"
                    "Bu Two-Step Verification paroli, telefon qulfi emas.\n"
                    "Qayta yuboring. Bekor: <b>bekor</b>",
                    parse_mode="HTML",
                )
                return
            if err:
                await message.answer(f"⚠️ {err}")
                return
            _login_tmp.pop(uid, None)
            await state.clear()
            await _login_done(message, state)
            return
        if step == "2fa":
            from app.services.channel_user import finish_login, twofa_hint
            err = await finish_login("", password=t)
            if err == "2FA_WRONG":
                hint = await twofa_hint()
                extra = f"\nEslatma: <code>{hint}</code>" if hint else ""
                await message.answer(
                    "⚠️ Parol Telegramda mos kelmadi.\n"
                    "Bu Two-Step Verification paroli, telefon qulfi emas.\n"
                    "Katta-kichik harf muhim."
                    f"{extra}\n\n"
                    "Qayta yuboring. Bekor: ⬅️ Orqaga yoki /start",
                    parse_mode="HTML",
                )
                return
            if err:
                await message.answer(f"⚠️ {err}")
                return
            _login_tmp.pop(uid, None)
            await state.clear()
            await _login_done(message, state)
            return
    except Exception as exc:  # noqa: BLE001
        logger.exception("[AKKAUNT] %s", exc)
        await message.answer(f"⚠️ Xato: {exc}\n/akkaunt bilan qayta boshlang.")


class HasLoginStep(Filter):
    async def __call__(self, message: Message) -> bool:
        user = message.from_user
        if user is None:
            return False
        return bool((_login_tmp.get(user.id) or {}).get("step"))


@router.message(HasLoginStep(), F.text == "⬅️ Orqaga")
async def login_orqaga(message: Message, state) -> None:
    _login_tmp.pop(message.from_user.id, None)
    await state.set_state(ChannelState.menu)
    async with async_session_factory() as session:
        text = await _menu_text(session, True)
    await message.answer(text, parse_mode="HTML", reply_markup=kb.channels_reply(True))


@router.channel_post()
async def on_channel_post(message: Message) -> None:
    try:
        from app.services.channel_inbox import ingest_channel_post
        await ingest_channel_post(message)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[CH] channel_post xato: %s", exc)
