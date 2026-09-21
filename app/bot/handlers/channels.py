"""📡 Kanallar — ulash, o'chirish, har kanal statistikasi."""
from __future__ import annotations

import asyncio

from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command, Filter
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, Message
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


_login_tmp: dict = {}


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
        "2️⃣ Avtomatik: <b>👤 Akkaunt</b> ulansa, AI kanallarni o'zi o'qiydi.",
        "Yopiq kanal: akkauntingiz obuna bo'lgan bo'lishi kerak.",
    ]
    if is_admin:
        lines.append("Admin: ➕ Qo'shish / ➖ O'chirish / 👤 Akkaunt.")
    return "\n".join(lines)


@router.message(F.text == "📡 Kanallar")
async def channels_menu(message: Message, state) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer("📡 Kanallar — faqat admin.")
        return
    await state.set_state(ChannelState.menu)
    async with async_session_factory() as session:
        text = await _menu_text(session, _is_admin(message.from_user.id if message.from_user else None))
    await message.answer(text, parse_mode="HTML", reply_markup=kb.channels_reply(
        _is_admin(message.from_user.id if message.from_user else None)
    ))


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
    try:
        from app.services import channel_archive as arc

        res = await arc.ocr_pass(per_channel=per)
        await message.answer(
            "\U0001F524 <b>Rasmlardagi yozuv o'qildi</b>\n"
            f"o'qildi: <b>{res.get('done')}</b> | bo'sh: {res.get('empty')} | "
            f"xato: {res.get('fail')} | {res.get('secs')}s"
            + (f"\n\u274C {res['error']}" if res.get("error") else ""),
            parse_mode="HTML",
        )
        name, data = await arc.export_txt()
        await message.answer_document(BufferedInputFile(data, filename=name),
                                      caption="\U0001F4C4 OCR qo'shilgan fayl.")
    except Exception as exc:  # noqa: BLE001
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
    per = 30
    for part in (message.text or "").split()[1:]:
        if part.isdigit():
            per = max(5, min(int(part), 100))
    await message.reply(f"\U0001F524 Har kanaldan {per} ta rasm o'qilmoqda...", parse_mode="HTML")
    _DUMP_TASK = asyncio.create_task(_ocr_job(message, per))


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
        f"⏱ Oxirgi poll: {st.get('last_poll') or '—'}\n"
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


@router.message(ChannelState.menu, F.text == "➕ Qo'shish")
async def ask_add(message: Message, state) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Faqat admin kanal qo'sha oladi.")
        return
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
    async with async_session_factory() as session:
        ok, msg, _ch = await add_channel(
            session, username=username, chat_id=chat_id, title=title, kind=kind,
        )
        text = ("✅ " if ok else "⚠️ ") + msg + "\n\n" + await _menu_text(session, True)
    await state.set_state(ChannelState.menu)
    await message.answer(text, parse_mode="HTML", reply_markup=kb.channels_reply(True))


@router.message(ChannelState.menu, F.text == "➖ O'chirish")
async def ask_remove(message: Message, state) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Faqat admin o'chira oladi.")
        return
    await state.set_state(ChannelState.awaiting_remove)
    await message.answer(
        "➖ Qaysi kanalni o'chiramiz? <code>@username</code> yuboring.\nBekor: ⬅️ Orqaga.",
        parse_mode="HTML", reply_markup=kb.channels_reply(True),
    )


@router.message(ChannelState.awaiting_remove, F.text == "⬅️ Orqaga")
async def remove_cancel(message: Message, state) -> None:
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
    async with async_session_factory() as session:
        ok, msg = await remove_channel(session, key)
        text = ("✅ " if ok else "⚠️ ") + msg + "\n\n" + await _menu_text(session, True)
    await state.set_state(ChannelState.menu)
    await message.answer(text, parse_mode="HTML", reply_markup=kb.channels_reply(True))


_LOGIN_SKIP = _MENU_BTNS


def _only_digits(text: str | None) -> str:
    return "".join(c for c in (text or "") if c.isdigit())


_CODE_HINT = (
    "📲 Telegram kod yubordi (ilova yoki SMS).\n\n"
    "⚠️ <b>Kodni yolg'iz raqam qilib yozmang.</b>\n"
    "Telegram uni o'chirib tashlaydi — shu sabab oldin kira olmadingiz.\n\n"
    "Kod 12345 bo'lsa, shunday yuboring:\n"
    "<code>A12345</code>\n"
    "yoki\n"
    "<code>12 345</code>\n\n"
    "Harf/bo'shliqni bot o'zi olib tashlaydi.\n"
    "Yangi kod: <b>qayta</b>"
)


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
    from app.services.channel_user import is_linked
    extra = ""
    if await is_linked():
        extra = "Akkaunt allaqachon ulangan. Qayta ulash:\n\n"
    await message.answer(
        "👤 <b>Telegram akkaunt ulash</b>\n"
        f"{extra}"
        "Botni kanalga qo'shmaymiz.\n\n"
        "1) my.telegram.org → API development tools\n"
        "2) <b>api_id</b> ni yuboring (raqam, nusxa ham bo'ladi)\n\n"
        "Bekor: ⬅️ Orqaga yoki /menu",
        parse_mode="HTML",
        reply_markup=kb.channels_reply(True),
    )


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
            err = await start_login(int(tmp.get("api_id") or 0), str(tmp.get("api_hash") or ""), phone)
            if err:
                await message.answer(f"⚠️ {err}")
                return
            tmp["phone"] = phone
            tmp["step"] = "code"
            await message.answer(_CODE_HINT, parse_mode="HTML")
            return
        if step == "code":
            from app.services.channel_user import finish_login, resend_code
            low = t.lower()
            if low in {"qayta", "kod", "sms", "yangi", "resend"}:
                err = await resend_code()
                if err:
                    await message.answer(f"⚠️ {err}")
                    return
                await message.answer("Yangi kod yuborildi.\n\n" + _CODE_HINT, parse_mode="HTML")
                return
            digits = _only_digits(t)
            naked = t.replace(" ", "").replace("-", "").replace(".", "")
            if naked == digits and 4 <= len(digits) <= 6:
                await resend_code()
                await message.answer(
                    "⛔ Yalang'och kodni Telegram o'zi o'chiradi "
                    "(oldingi urinish shu sabab yiqildi).\n\n"
                    "Yangi kod keladi. Uni <b>harf bilan</b> yuboring, "
                    "masalan: <code>A12345</code> yoki <code>12 345</code>.",
                    parse_mode="HTML",
                )
                return
            err = await finish_login(t)
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
            if err == "EXPIRED_RESENT":
                await message.answer(
                    "⚠️ Eski kod o'chgan. Yangi kod keldi.\n\n" + _CODE_HINT,
                    parse_mode="HTML",
                )
                return
            if err == "INVALID":
                await message.answer(
                    "⚠️ Kod noto'g'ri. Qayta yozing: <code>A12345</code>\n"
                    "Yangi kod: <b>qayta</b>",
                    parse_mode="HTML",
                )
                return
            if err:
                await message.answer(f"⚠️ {err}")
                return
            _login_tmp.pop(uid, None)
            await state.clear()
            try:
                from app.services.channel_watcher import restart_watcher
                await restart_watcher()
            except Exception:  # noqa: BLE001
                pass
            await message.answer(
                "✅ Akkaunt ulandi. Kanallar kuzatiladi.",
                reply_markup=kb.channels_reply(True),
            )
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
            try:
                from app.services.channel_watcher import restart_watcher
                await restart_watcher()
            except Exception:  # noqa: BLE001
                pass
            await message.answer("✅ Akkaunt ulandi (2FA).", reply_markup=kb.channels_reply(True))
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
