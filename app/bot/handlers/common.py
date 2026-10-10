"""Asosiy menyu va /start."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, Filter
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards as kb
from app.bot.texts import ABOUT, MENU_READY, WELCOME
from app.core.config import get_settings

router = Router(name="common")

_SKIP_LOGIN = {
    "⬅️ Orqaga",
    "📡 Kanallar",
    "➕ Qo'shish",
    "➖ O'chirish",
    "🔎 Holat",
    "👤 Akkaunt",
    "🔥 Signallar",
    "📊 Bozor",
    "📚 Strategiyalar",
    "📈 Statistika",
    "💼 Hisob (paper)",
    "🔎 Jonli kuzatuv",
    "🏦 Broker",
    "🗓 Hisobotlar",
    "💰 Balansni o'rnatish",
    "🤖 Avto-trade: yoqish/o'chirish",
    "⚙️ Sozlamalar",
    "ℹ️ Ma'lumot",
    "☰ Menyu",
}


def _cancel_login(user_id: int | None) -> None:
    if not user_id:
        return
    try:
        from app.bot.handlers.channels import _login_tmp
        _login_tmp.pop(user_id, None)
    except Exception:  # noqa: BLE001
        pass


class _AccountFlow(Filter):
    """Faqat akkaunt wizard matni. /start, Orqaga, menyu tugmalari yutilmasin."""

    async def __call__(self, message: Message) -> bool:
        if message.from_user is None or not (message.text or "").strip():
            return False
        if getattr(message, "forward_origin", None) or getattr(message, "forward_from_chat", None):
            return False
        from app.core.access import is_admin
        if not is_admin(message.from_user.id):
            return False
        t = message.text.strip()
        low = t.lower()
        if t in _SKIP_LOGIN:
            return False
        if t.startswith("/") and not low.startswith("/akkaunt"):
            return False
        if "akkaunt" in low:
            return True
        try:
            from app.bot.handlers.channels import _login_tmp
            step = (_login_tmp.get(message.from_user.id) or {}).get("step")
        except Exception:  # noqa: BLE001
            step = None
        return bool(step)


@router.message(_AccountFlow())
async def account_flow_first(message: Message, state) -> None:
    from app.bot.handlers.channels import _login_tmp, account_start, account_wizard
    t = (message.text or "").strip()
    if "akkaunt" in t.lower():
        await account_start(message, state)
        return
    uid = message.from_user.id
    if not (_login_tmp.get(uid) or {}).get("step"):
        _login_tmp[uid] = {"step": "api_id"}
    await account_wizard(message, state)


@router.message(CommandStart())
async def cmd_start(message: Message, state) -> None:
    uid = message.from_user.id if message.from_user else None
    _cancel_login(uid)
    await state.clear()
    from app.core.access import claim_admin
    admin = await claim_admin(uid)
    if uid:
        try:
            from app.paper_trading.engine import PaperEngine
            from app.database.session import async_session_factory
            async with async_session_factory() as session:
                await PaperEngine().get_account(session, uid)
        except Exception:  # noqa: BLE001
            pass
    if not admin and uid:
        # v95: oddiy user — faqat kontakt tugma (ro'yxatda bo'lsa signal keladi)
        from app.services import access as _ACC
        from app.database.session import async_session_factory as _asf
        wl = False
        try:
            async with _asf() as session:
                wl = await _ACC.is_allowed(session, get_settings(), uid)
        except Exception:  # noqa: BLE001
            wl = False
        if wl:
            # v98: oddiy user — admin tugmalari YO'Q; faqat shaxsiy menyu
            _lim = ""
            try:
                from app.services import access as _ACC98
                from app.database.session import async_session_factory as _asf98
                async with _asf98() as session:
                    _rws = await _ACC98.rows(session)
                    _row = [r for r in _rws if int(r.user_id) == int(uid)]
                    if _row:
                        _lim = "\n" + _ACC98.row_text(_row[0])
            except Exception:  # noqa: BLE001
                _lim = ""
            _txt = ("\u2705 Siz signal ro\u2018yxatidasiz \u2014 yangi "
                    "signallar avtomatik keladi." + _lim +
                    "\n\nBoshqa buyruqlar yopiq. Siz uchun tugmalar:")
            await message.answer(_txt, parse_mode="HTML",
                                 reply_markup=kb.user_menu_reply())
            return
        _txt = ("\U0001F44B Siz <b>bepul rejimdasiz</b>: har 2 kunda 1 ta "
                "signal va uning natijasi keladi.\n\nTo\u2018liq signal "
                "olish uchun adminga yozing:")
        await message.answer(_txt, parse_mode="HTML",
                             reply_markup=kb.contact_admin_kb())
        return
    extra = ""
    if admin:
        extra = (
            "\n🔑 Siz <b>adminsiz</b>: 📡 Kanallar, akkaunt, holat, /access.\n"
            "Oddiy user faqat signal kartalarini ko'radi.\n"
        )
    await message.answer(
        MENU_READY + extra +
        "\n🤖 Avto-trade <b>yoqilgan</b> — yangi signallar virtual hisobda ochiladi.\n"
        "\n⌨️ Pastdagi klaviatura <b>yashirinadigan</b> — uni pastga surib yig'ib qo'ysangiz "
        "bo'ladi, xohlaganda qayta ochasiz.\n"
        "<i>Commandlar ro'yxati: input yonidagi ☰ (yoki «/» belgisi).</i>",
        parse_mode="HTML",
        reply_markup=kb.main_menu_reply(uid),
    )
    # v69: klaviaturani yashirish / qayta ochish tugmalari (xabar ostida)
    await message.answer(
        "⌨️ <b>Klaviatura boshqaruvi</b>",
        parse_mode="HTML", reply_markup=kb.menu_controls_kb(),
    )


@router.message(F.text == "☰ Menyu")
async def menu_button(message: Message, state) -> None:
    """v69: tugma klaviaturadan olib tashlandi, lekin eski klaviatura bilan
    yozganlar uchun handler qoldirilgan — xuddi /menu kabi ishlaydi."""
    await cmd_menu(message, state)


@router.message(Command("menu"))
async def cmd_menu(message: Message, state) -> None:
    """Klaviatura yig'ilib qolgan bo'lsa: /menu qayta ochadi."""
    _cancel_login(message.from_user.id if message.from_user else None)
    await state.clear()
    uid = message.from_user.id if message.from_user else None
    await message.answer(
        "🏠 Siz asosiy menyuga qaytdingiz.\nPastdan bo'limni tanlang 👇",
        parse_mode="HTML",
        reply_markup=kb.main_menu_reply(uid),
    )
    await message.answer(
        "⌨️ <b>Klaviatura boshqaruvi</b>",
        parse_mode="HTML", reply_markup=kb.menu_controls_kb(),
    )


@router.callback_query(F.data == "menu:hide")
async def hide_menu(callback: CallbackQuery) -> None:
    """v69: pastdagi klaviaturani YASHIRADI (matn kiritish maydoni toza qoladi)."""
    try:
        await callback.message.edit_reply_markup(reply_markup=kb.reopen_menu_kb())
    except Exception:  # noqa: BLE001
        pass
    await callback.message.answer(
        "⌨️ Klaviatura yashirildi.\nQayta ochish: pastdagi <b>☰ Menyuni qayta ochish</b> "
        "yoki /menu.",
        parse_mode="HTML",
        reply_markup=kb.hide_reply_kb(),
    )
    await callback.answer("Klaviatura yashirildi")


@router.callback_query(F.data == "menu:reopen")
async def reopen_menu(callback: CallbackQuery) -> None:
    """Yig'ilgan klaviaturani qayta ochadi."""
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass
    await callback.message.answer(
        "☰ Menyu ochildi. Bo'limni pastdan tanlang 👇",
        reply_markup=kb.main_menu_reply(callback.from_user.id if callback.from_user else None),
    )
    await callback.answer()


@router.message(F.text == "ℹ️ Ma'lumot")
async def about_message(message: Message) -> None:
    await message.answer(ABOUT, parse_mode="HTML")


@router.callback_query(F.data == "msg:delete")
async def delete_message(callback: CallbackQuery) -> None:
    try:
        await callback.message.delete()
    except Exception:  # noqa: BLE001
        pass
    await callback.answer()


@router.callback_query(F.data == "menu:main")
async def show_main(callback: CallbackQuery) -> None:
    await callback.message.edit_text(WELCOME, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "menu:about")
async def show_about(callback: CallbackQuery) -> None:
    await callback.message.edit_text(ABOUT, reply_markup=kb.back_to_menu(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "menu:back")
async def generic_back(callback: CallbackQuery) -> None:
    await callback.message.edit_text(WELCOME, parse_mode="HTML")
    await callback.answer()


@router.message(Command("access"))
async def cmd_access(message: Message) -> None:
    """v97: signal ro'yxati.

    /access add ID                -> cheksiz
    /access add ID signal N       -> N ta signal limiti
    /access add ID kun N          -> N ta SIGNAL KUNI limiti
    /access limit ID signal N | kun N | cheksiz
    /access del ID  |  /access list  |  /access stat
    """
    from app.core.access import is_admin
    if message.from_user is None or not is_admin(message.from_user.id):
        await message.answer("\u26D4\uFE0F Faqat admin.", parse_mode="HTML",
                             reply_markup=kb.contact_admin_kb())
        return
    from app.services import access as _ACC
    from app.database.session import async_session_factory as _asf
    parts = (message.text or "").split()
    act = (parts[1] if len(parts) > 1 else "list").lower()

    def _mode_val(ps: list[str]):
        """parts[3:]: ('signal'|'kun', N) yoki ('none', 0)."""
        if len(ps) > 4 and ps[3].lower() in ("signal", "kun") \
                and ps[4].lstrip("-").isdigit():
            return ("sig" if ps[3].lower() == "signal" else "day"), int(ps[4])
        return "none", 0

    async with _asf() as session:
        if act == "add" and len(parts) > 2:
            try:
                uid = int(parts[2])
            except (TypeError, ValueError):
                await message.answer(
                    "ID raqam bo'lsin: /access add 123456789 signal 5 "
                    "yoki /access add 123456789 kun 7")
                return
            mode, val = _mode_val(parts)
            ok = await _ACC.add_user(session, uid, message.from_user.id,
                                     mode=mode, value=val)
            lim = {"sig": f"{val} ta signal", "day": f"{val} signal kuni",
                   "none": "cheksiz"}[mode]
            await message.answer(
                ("\u2705 Qo'shildi: <code>%d</code> \u00b7 limit: %s"
                 % (uid, lim)) if ok
                else ("\u2139\uFE0F <code>%d</code> allaqachon ro'yxatda." % uid),
                parse_mode="HTML")
        elif act == "limit" and len(parts) > 2:
            try:
                uid = int(parts[2])
            except (TypeError, ValueError):
                await message.answer(
                    "ID raqam bo'lsin: /access limit 123456789 signal 5 "
                    "yoki /access limit 123456789 kun 7 yoki ... cheksiz")
                return
            if len(parts) > 3 and parts[3].lower() == "cheksiz":
                mode, val = "none", 0
            else:
                mode, val = _mode_val(parts)
            ok = await _ACC.set_limits(session, uid, mode=mode, value=val)
            lim = {"sig": f"{val} ta signal", "day": f"{val} signal kuni",
                   "none": "cheksiz"}[mode]
            await message.answer(
                ("\u2705 Limit: <code>%d</code> \u00b7 %s (hisob nolga tushdi)"
                 % (uid, lim)) if ok
                else ("\u2139\uFE0F <code>%d</code> ro'yxatda yo'q." % uid),
                parse_mode="HTML")
        elif act == "del" and len(parts) > 2:
            try:
                uid = int(parts[2])
            except (TypeError, ValueError):
                await message.answer("ID raqam bo'lsin: /access del 123456789")
                return
            ok = await _ACC.remove_user(session, uid)
            await message.answer(
                ("\u2705 O'chirildi: <code>%d</code> \u2014 signal to'xtadi." % uid)
                if ok else ("\u2139\uFE0F <code>%d</code> ro'yxatda yo'q edi." % uid),
                parse_mode="HTML")
        elif act == "stat":
            st = await _ACC.stats(session)
            await message.answer(_stats_text(st), parse_mode="HTML")
        else:
            rws = await _ACC.rows(session)
            if rws:
                lines = "\n".join("  \u2022 " + _ACC.row_text(r) for r in rws)
            else:
                lines = "  (bo'sh \u2014 hozircha faqat admin oladi)"
            await message.answer(
                "\U0001F4CB <b>Signal ro'yxati</b> (%d ta):\n%s\n\n"
                "Qo'shish: /access add ID signal N \u2014 yoki \u2014 "
                "/access add ID kun N\n"
                "Limit: /access limit ID signal N | kun N | cheksiz\n"
                "O'chirish: /access del ID  \u00b7  Soni: /access stat\n"
                "Menyu: \U0001F510 Access (ro'yxat) tugmasi"
                % (len(rws), lines), parse_mode="HTML")


# ============ v96/v97: ACCESS BOSHQARUVI (menyu tugmalari) ============
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup


class AccStates(StatesGroup):
    add_id = State()
    add_mode = State()      # tugmadan limit turi tanlanadi
    add_val = State()       # signal soni YOKI kun soni
    del_id = State()
    lim_id = State()
    lim_mode = State()
    lim_val = State()
    reset_id = State()
    bc_text = State()       # v98: hammaga xabar (matn/rasm/video/fayl)
    bc_btn = State()        # v98: inline tugma (MATN | URL)
    bc_confirm = State()


def _acc_admin(message_from) -> bool:
    from app.core.access import is_admin
    return message_from is not None and is_admin(message_from.id)


async def _acc_list_text() -> str:
    from app.services import access as _ACC
    from app.database.session import async_session_factory as _asf
    async with _asf() as session:
        rows = await _ACC.rows(session)
    if not rows:
        return ("\U0001F4CB <b>Ro'yxat bo'sh</b> \u2014 hozircha signal faqat "
                "adminga boradi.\n\u2795 ID qo'shish tugmasi bilan qo'shing.")
    return ("\U0001F4CB <b>Signal ro'yxati</b> (%d ta):\n" % len(rows)
            + "\n".join(_ACC.row_text(r) for r in rows)
            + "\n\nLimit turi BITTA bo'ladi: signal soni YOKI kun soni. "
              "Kun limiti faqat signal berilgan kunlarni ayiradi.")


def _stats_text(st: dict) -> str:
    return ("\U0001F465 <b>Botdagi odamlar</b>\n"
            "  \u2022 Jami botga kirgan (/start bosgan): <b>%d</b>\n"
            "  \u2022 Signal ro'yxatida: <b>%d</b>\n"
            "  \u2022 Hozir signal oladi (limiti tugamagan): <b>%d</b>\n"
            "  \u2022 Limiti tugagan (signal to'xtagan): <b>%d</b>"
            % (int(st.get("db_users") or 0), int(st.get("list") or 0),
               int(st.get("active") or 0), int(st.get("stopped") or 0)))


@router.message(F.text == "\U0001F510 Access (ro'yxat)")
async def acc_menu_button(message: Message, state: FSMContext) -> None:
    if not _acc_admin(message.from_user):
        return
    await state.clear()
    await message.answer(await _acc_list_text(), parse_mode="HTML",
                         reply_markup=kb.access_menu_kb())


# ---------- v98: ODDIY USER — SHAXSIY HISOB ----------
@router.message(F.text == "\U0001F4CA Mening hisobim")
async def my_account_button(message: Message, state: FSMContext) -> None:
    """v98: limit + nechta signal olgan + g'alabalar + jami foyda (pip)."""
    if message.from_user is None:
        return
    uid = int(message.from_user.id)
    from app.services import access as _ACC
    from app.services import deliveries as _DLV
    from app.database.session import async_session_factory as _asf
    lim = None
    stats = {"received": 0, "closed": 0, "wins": 0, "pips": 0.0}
    try:
        async with _asf() as session:
            rws = await _ACC.rows(session)
            row = [r for r in rws if int(r.user_id) == uid]
            if row:
                lim = _ACC.row_text(row[0])
            stats = await _DLV.user_stats(session, uid)
    except Exception:  # noqa: BLE001
        pass
    wr = round(100.0 * stats["wins"] / stats["closed"]) if stats["closed"] else 0
    if lim:
        lim_line = "\U0001F511 Limit: " + lim
    else:
        lim_line = ("\U0001F511 Rejim: <b>bepul</b> \u2014 har 2 kunda "
                    "1 signal + natijasi")
    rec = int(stats["received"])
    wins = int(stats["wins"])
    pips = float(stats["pips"])
    wr_txt = f" ({wr}%)" if stats["closed"] else ""
    txt = ("\U0001F4CA <b>Mening hisobim</b>\n"
           + lim_line + "\n"
           + f"\U0001F4E8 Olingan signallar: <b>{rec}</b>\n"
           + f"\U0001F3C6 G\u2018alaba: <b>{wins}</b>{wr_txt}\n"
           + f"\U0001F4B0 Jami foyda: <b>{pips:+,.1f} pip</b>")
    await message.answer(txt, parse_mode="HTML",
                         reply_markup=kb.user_menu_reply())


@router.message(F.text == "\U0001F4DE Admin bilan bog'lanish")
async def contact_admin_button(message: Message, state: FSMContext) -> None:
    await message.answer(
        "\U0001F4DE Admin bilan bog\u2018lanish \u2014 quyidagi tugmani "
        "bosing:", reply_markup=kb.contact_admin_kb())


# ---------- v97: ODAMLAR SONI ----------
@router.message(F.text == "\U0001F465 Odamlar soni")
async def people_count_button(message: Message, state: FSMContext) -> None:
    if not _acc_admin(message.from_user):
        return
    await state.clear()
    from app.services import access as _ACC
    from app.database.session import async_session_factory as _asf
    async with _asf() as session:
        st = await _ACC.stats(session)
    await message.answer(_stats_text(st), parse_mode="HTML")


# ---------- v98: HAMMAGA XABAR (matn/rasm/video/fayl + inline tugma) ----------
@router.message(F.text == "\U0001F4E2 Hammaga xabar")
async def bc_start_button(message: Message, state: FSMContext) -> None:
    if not _acc_admin(message.from_user):
        return
    await state.set_state(AccStates.bc_text)
    await message.answer(
        "\U0001F4E2 <b>Hammaga xabar</b>\nNima yubormoqchisiz? <b>Matn, "
        "rasm, video yoki fayl</b> \u2014 shunchaki yuboring, bot uni "
        "BARCHA userlarga yetkazadi (start bosgan hamma + ro\u2018yxat + "
        "admin). Matnli xabarga <b>inline tugma</b> (havola) ham qo\u2018shsa "
        "bo\u2018ladi. Bekor: /start", parse_mode="HTML")


@router.message(AccStates.bc_text)
async def bc_text_in(message: Message, state: FSMContext) -> None:
    is_media = bool(message.photo or message.video or message.document
                    or message.animation or message.audio or message.voice
                    or message.video_note or message.sticker)
    if message.text and message.text.strip():
        txt = message.text.strip()
        await state.update_data(bc_kind="text", bc=txt)
        prev = txt if len(txt) <= 400 else txt[:400] + "\u2026"
    elif is_media:
        await state.update_data(bc_kind="media",
                                bc_chat=message.chat.id,
                                bc_mid=message.message_id)
        cap = (message.caption or "").strip()
        prev = "\U0001F4CE Media xabar" + (f": {cap[:200]}" if cap else "")
    else:
        await message.answer("Matn, rasm, video yoki fayl yuboring.")
        return
    await state.set_state(AccStates.bc_confirm)
    from app.database import crud as _CRUD
    from app.services import access as _ACC
    from app.database.session import async_session_factory as _asf
    n = 0
    try:
        from app.core.config import get_settings
        async with _asf() as session:
            ids = set(int(x) for x in await _ACC.allowed_ids(session))
            ids |= set(int(x) for x in await _CRUD.get_all_active_users(session))
            ids |= set(int(a) for a in (get_settings().admin_id_list or []))
            n = len(ids)
    except Exception:  # noqa: BLE001
        pass
    await message.answer(
        f"Quyidagi xabar <b>{n}</b> ta manzilga yuboriladi:\n\n{prev}",
        parse_mode="HTML", reply_markup=kb.bc_confirm_kb())


@router.callback_query(F.data == "bc:btn")
async def bc_btn_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not _acc_admin(cb.from_user):
        await cb.answer("\u26D4\uFE0F")
        return
    st = await state.get_data()
    if st.get("bc_kind") != "text":
        await cb.answer("Tugma faqat MATNLI xabarga qo'shiladi.")
        return
    await state.set_state(AccStates.bc_btn)
    await cb.message.answer(
        "Inline tugma: <b>MATN | HAVOLA</b> ko\u2018rinishida yuboring.\n"
        "Masalan: <code>Bizning kanal | https://t.me/xxxx</code>",
        parse_mode="HTML")
    await cb.answer()


@router.message(AccStates.bc_btn)
async def bc_btn_in(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if "|" not in raw:
        await message.answer("Format: <code>MATN | https://havola</code>",
                             parse_mode="HTML")
        return
    a, b = raw.split("|", 1)
    a, b = a.strip(), b.strip()
    if not a or not b.startswith("http"):
        await message.answer("Havola http(s) bilan boshlansin.")
        return
    await state.update_data(bc_btn=a, bc_url=b)
    await state.set_state(AccStates.bc_confirm)
    st = await state.get_data()
    prev = str(st.get("bc") or "")
    prev = prev if len(prev) <= 300 else prev[:300] + "\u2026"
    await message.answer(
        f"Xabar + tugma «{a}» \u2192 {b}\n\n{prev}",
        reply_markup=kb.bc_confirm_kb())


@router.callback_query(F.data == "bc:yes")
async def bc_yes(cb: CallbackQuery, state: FSMContext) -> None:
    if not _acc_admin(cb.from_user):
        await cb.answer("\u26D4\uFE0F Faqat admin.")
        return
    st = await state.get_data()
    kind = str(st.get("bc_kind") or "text")
    txt = str(st.get("bc") or "")
    btn = str(st.get("bc_btn") or "")
    url = str(st.get("bc_url") or "")
    chat = st.get("bc_chat")
    mid = st.get("bc_mid")
    await state.clear()
    import asyncio as _aio
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from app.database import crud as _CRUD
    from app.services import access as _ACC
    from app.database.session import async_session_factory as _asf
    targets: list[int] = []
    try:
        from app.core.config import get_settings
        async with _asf() as session:
            ids = set(int(x) for x in await _ACC.allowed_ids(session))
            ids |= set(int(x) for x in await _CRUD.get_all_active_users(session))
            ids |= set(int(a) for a in (get_settings().admin_id_list or []))
        targets = sorted(ids)
    except Exception:  # noqa: BLE001
        targets = []
    markup = None
    if kind == "text" and btn and url:
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=btn, url=url)]])
    sent = 0
    failed = 0
    for t in targets:
        try:
            if kind == "media" and chat is not None and mid is not None:
                await cb.bot.copy_message(chat_id=int(t),
                                          from_chat_id=int(chat),
                                          message_id=int(mid))
            elif kind == "text" and txt:
                await cb.bot.send_message(int(t), txt, reply_markup=markup)
            else:
                failed += 1
                continue
            sent += 1
        except Exception:  # noqa: BLE001
            failed += 1
        await _aio.sleep(0.05)
    await cb.message.edit_text(
        "\u2705 Xabar yuborildi: <b>%d</b> ta manzil \u00b7 xato: %d"
        % (sent, failed), parse_mode="HTML")
    await cb.answer("Yuborildi: %d" % sent)


@router.callback_query(F.data == "bc:no")
async def bc_no(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        await cb.message.edit_text("\u274C Xabar yuborish bekor qilindi.")
    except Exception:  # noqa: BLE001
        pass
    await cb.answer("Bekor")


# ---------- ACCESS inline menyu ----------
@router.callback_query(F.data == "acc:menu")
@router.callback_query(F.data == "acc:list")
async def acc_cb_list(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.edit_text(await _acc_list_text(), parse_mode="HTML",
                               reply_markup=kb.access_menu_kb())
    await cb.answer()


@router.callback_query(F.data == "acc:close")
async def acc_cb_close(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        await cb.message.delete_reply_markup()
    except Exception:  # noqa: BLE001
        pass
    await cb.answer("Yopildi")


@router.callback_query(F.data == "acc:add")
async def acc_cb_add(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AccStates.add_id)
    await cb.message.answer("\u2795 <b>User ID</b> yuboring (raqam):",
                            parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "acc:del")
async def acc_cb_del(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AccStates.del_id)
    await cb.message.answer("\u2796 O'chiriladigan <b>User ID</b> ni yuboring:",
                            parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "acc:limit")
async def acc_cb_limit(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AccStates.lim_id)
    await cb.message.answer("\u270F\uFE0F Limit qo'yiladigan <b>User ID</b> "
                            "ni yuboring:", parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "acc:reset")
async def acc_cb_reset(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AccStates.reset_id)
    await cb.message.answer("\U0001F504 Ishlatilgan hisobni nolga qo'yiladigan "
                            "<b>User ID</b> ni yuboring:", parse_mode="HTML")
    await cb.answer()


def _parse_int(txt: str | None):
    try:
        return int(str(txt or "").strip())
    except (TypeError, ValueError):
        return None


# ---- QO'SHISH: ID -> limit turi -> son ----
@router.message(AccStates.add_id)
async def acc_add_id(message: Message, state: FSMContext) -> None:
    uid = _parse_int(message.text)
    if not uid:
        await message.answer("Raqam yuboring, masalan: <code>123456789</code>",
                             parse_mode="HTML")
        return
    await state.update_data(uid=uid)
    await state.set_state(AccStates.add_mode)
    await message.answer(
        "ID <code>%d</code>: limit turini tanlang \u2014 YOKI signal soni "
        "YOKI kun soni (ikkalasi bir vaqtda bo'lmaydi):" % uid,
        parse_mode="HTML", reply_markup=kb.acc_mode_kb("add"))


@router.callback_query(F.data == "acc:add:sig")
async def acc_add_mode_sig(cb: CallbackQuery, state: FSMContext) -> None:
    st = await state.get_data()
    if not st.get("uid"):
        await cb.answer("Avval \u2795 ID qo'shish dan boshlang.")
        return
    await state.update_data(mode="sig")
    await state.set_state(AccStates.add_val)
    await cb.message.answer("<b>Nechta signal</b> beriladi? (musbat raqam)",
                            parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "acc:add:day")
async def acc_add_mode_day(cb: CallbackQuery, state: FSMContext) -> None:
    st = await state.get_data()
    if not st.get("uid"):
        await cb.answer("Avval \u2795 ID qo'shish dan boshlang.")
        return
    await state.update_data(mode="day")
    await state.set_state(AccStates.add_val)
    await cb.message.answer(
        "<b>Necha kun</b>? (musbat raqam) \u2014 faqat signal BERILGAN kunlar "
        "hisoblanadi, signal bo'lmagan kun ayirilmaydi.", parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "acc:add:none")
async def acc_add_mode_none(cb: CallbackQuery, state: FSMContext) -> None:
    st = await state.get_data()
    uid = st.get("uid")
    if not uid:
        await cb.answer("Avval \u2795 ID qo'shish dan boshlang.")
        return
    await state.clear()
    from app.services import access as _ACC
    from app.database.session import async_session_factory as _asf
    async with _asf() as session:
        ok = await _ACC.add_user(session, int(uid), cb.from_user.id,
                                 mode="none", value=0)
    await cb.message.answer(
        ("\u2705 Qo'shildi: <code>%s</code> \u00b7 limit: cheksiz" % uid)
        if ok else ("\u2139\uFE0F <code>%s</code> allaqachon ro'yxatda." % uid),
        parse_mode="HTML", reply_markup=kb.access_menu_kb())
    await cb.answer()


@router.message(AccStates.add_mode)
async def acc_add_mode_wait(message: Message, state: FSMContext) -> None:
    await message.answer("Limit turini pastdagi TUGMALARDAN tanlang.",
                         reply_markup=kb.acc_mode_kb("add"))


@router.message(AccStates.add_val)
async def acc_add_val(message: Message, state: FSMContext) -> None:
    n = _parse_int(message.text)
    if n is None or n <= 0:
        await message.answer("Musbat raqam yuboring (masalan: 5). Cheksiz "
                             "bo'lsa \u2014 bekor qilib, \u267E\uFE0F tanlang.")
        return
    st = await state.get_data()
    await state.clear()
    mode = str(st.get("mode") or "sig")
    uid = int(st.get("uid") or 0)
    from app.services import access as _ACC
    from app.database.session import async_session_factory as _asf
    async with _asf() as session:
        ok = await _ACC.add_user(session, uid, message.from_user.id,
                                 mode=mode, value=n)
    lim = (f"{n} ta signal" if mode == "sig" else f"{n} signal kuni")
    if ok:
        await message.answer(f"\u2705 Qo'shildi: <code>{uid}</code> \u00b7 "
                             f"limit: {lim}", parse_mode="HTML",
                             reply_markup=kb.access_menu_kb())
    else:
        await message.answer(f"\u2139\uFE0F <code>{uid}</code> allaqachon "
                             "ro'yxatda \u2014 \u270F\uFE0F Limit bilan "
                             "o'zgartiring.", parse_mode="HTML",
                             reply_markup=kb.access_menu_kb())


# ---- O'CHIRISH ----
@router.message(AccStates.del_id)
async def acc_del_id(message: Message, state: FSMContext) -> None:
    uid = _parse_int(message.text)
    await state.clear()
    if not uid:
        await message.answer("Raqam yuboring.")
        return
    from app.services import access as _ACC
    from app.database.session import async_session_factory as _asf
    async with _asf() as session:
        ok = await _ACC.remove_user(session, uid)
    await message.answer(
        (f"\u2705 O'chirildi: <code>{uid}</code> \u2014 signal to'xtadi." if ok
         else f"\u2139\uFE0F <code>{uid}</code> ro'yxatda yo'q edi."),
        parse_mode="HTML", reply_markup=kb.access_menu_kb())


# ---- LIMIT: ID -> tur -> son ----
@router.message(AccStates.lim_id)
async def acc_lim_id(message: Message, state: FSMContext) -> None:
    uid = _parse_int(message.text)
    if not uid:
        await message.answer("Raqam yuboring.")
        return
    await state.update_data(uid=uid)
    await state.set_state(AccStates.lim_mode)
    await message.answer(
        "ID <code>%d</code>: yangi limit turi \u2014 YOKI signal soni YOKI kun "
        "soni (eskisi tozalanadi, hisob nolga tushadi):" % uid,
        parse_mode="HTML", reply_markup=kb.acc_mode_kb("lim"))


@router.message(AccStates.lim_mode)
async def acc_lim_mode_wait(message: Message, state: FSMContext) -> None:
    await message.answer("Limit turini pastdagi TUGMALARDAN tanlang.",
                         reply_markup=kb.acc_mode_kb("lim"))


@router.callback_query(F.data == "acc:lim:sig")
async def acc_lim_mode_sig(cb: CallbackQuery, state: FSMContext) -> None:
    st = await state.get_data()
    if not st.get("uid"):
        await cb.answer("Avval \u270F\uFE0F Limit dan boshlang.")
        return
    await state.update_data(mode="sig")
    await state.set_state(AccStates.lim_val)
    await cb.message.answer("Yangi <b>signal soni</b>? (musbat raqam)",
                            parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "acc:lim:day")
async def acc_lim_mode_day(cb: CallbackQuery, state: FSMContext) -> None:
    st = await state.get_data()
    if not st.get("uid"):
        await cb.answer("Avval \u270F\uFE0F Limit dan boshlang.")
        return
    await state.update_data(mode="day")
    await state.set_state(AccStates.lim_val)
    await cb.message.answer("Yangi <b>kun soni</b>? (faqat signal berilgan "
                            "kunlar hisoblanadi)", parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "acc:lim:none")
async def acc_lim_mode_none(cb: CallbackQuery, state: FSMContext) -> None:
    st = await state.get_data()
    uid = st.get("uid")
    if not uid:
        await cb.answer("Avval \u270F\uFE0F Limit dan boshlang.")
        return
    await state.clear()
    from app.services import access as _ACC
    from app.database.session import async_session_factory as _asf
    async with _asf() as session:
        ok = await _ACC.set_limits(session, int(uid), mode="none")
    await cb.message.answer(
        (f"\u2705 <code>{uid}</code> limiti olib tashlandi \u2014 cheksiz.")
        if ok else (f"\u2139\uFE0F <code>{uid}</code> ro'yxatda yo'q."),
        parse_mode="HTML", reply_markup=kb.access_menu_kb())
    await cb.answer()


@router.message(AccStates.lim_val)
async def acc_lim_val(message: Message, state: FSMContext) -> None:
    n = _parse_int(message.text)
    if n is None or n <= 0:
        await message.answer("Musbat raqam yuboring (masalan: 5).")
        return
    st = await state.get_data()
    await state.clear()
    mode = str(st.get("mode") or "sig")
    uid = int(st.get("uid") or 0)
    from app.services import access as _ACC
    from app.database.session import async_session_factory as _asf
    async with _asf() as session:
        ok = await _ACC.set_limits(session, uid, mode=mode, value=n)
    lim = (f"{n} ta signal" if mode == "sig" else f"{n} signal kuni")
    await message.answer(
        (f"\u2705 Limit yangilandi: <code>{uid}</code> \u00b7 {lim} "
         "(hisob nolga tushdi)") if ok
        else (f"\u2139\uFE0F <code>{uid}</code> ro'yxatda yo'q."),
        parse_mode="HTML", reply_markup=kb.access_menu_kb())


# ---- HISOBNI NOLGA ----
@router.message(AccStates.reset_id)
async def acc_reset_id(message: Message, state: FSMContext) -> None:
    uid = _parse_int(message.text)
    await state.clear()
    if not uid:
        await message.answer("Raqam yuboring.")
        return
    from app.services import access as _ACC
    from app.database.session import async_session_factory as _asf
    async with _asf() as session:
        ok = await _ACC.set_limits(session, uid, reset_used=True)
    await message.answer(
        (f"\u2705 <code>{uid}</code> hisobi nolga tushdi (signal va kun)." if ok
         else f"\u2139\uFE0F <code>{uid}</code> ro'yxatda yo'q."),
        parse_mode="HTML", reply_markup=kb.access_menu_kb())


# ================= v102: AI BILAN SUHBAT (admin) =================
_AI_MEM: dict = {}


async def _ai_context(session) -> str:
    """Botning HOZIRGI holati — Gemini javobi shunga asoslansin."""
    parts = []
    try:
        from app.services import local_ai
        parts.append(f"versiya: {local_ai.__version__}")
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.services import channel_watcher as _cw
        st = getattr(_cw, "_status", {}) or {}
        parts.append(
            f"kanal akkaunti: {st.get('account', 'noma‘lum')}, "
            f"authorized={st.get('authorized')}, "
            f"oxirgi xato: {st.get('last_error', '') or 'yo‘q'}")
    except Exception:  # noqa: BLE001
        pass
    try:
        from sqlalchemy import func, select
        from app.database.models.signal import Signal
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        d0 = now - timedelta(hours=24)
        act = await session.scalar(
            select(func.count()).select_from(Signal).where(Signal.is_active.is_(True)))
        new = await session.scalar(
            select(func.count()).select_from(Signal).where(Signal.created_at >= d0))
        parts.append(f"faol signallar: {act or 0}, oxirgi 24h: {new or 0}")
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.services import gemini_ai as _g
        parts.append(f"gemini modeli: {_g._GOOD_MODEL.get('name') or 'tanlanmagan'}")
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.services import ai_chain as _ac
        _gk = "bor" if _ac.groq_key() else "yo'q"
        _gm = _ac._GOOD_GROQ.get("name") or "tanlanmagan"
        parts.append(f"ai zanjir: groq kalit {_gk}, groq modeli {_gm}")
    except Exception:  # noqa: BLE001
        pass
    return "; ".join(parts) or "holat noma’lum"


async def _ai_suhbat(message: Message, text: str) -> None:
    from app.core.access import is_admin
    uid = int(getattr(message.from_user, "id", 0) or 0)
    if not is_admin(uid):
        await message.answer("Bu buyruq faqat admin uchun.")
        return
    from app.services import ai_chain as _ac
    hist = _AI_MEM.setdefault(uid, [])
    async with async_session_factory() as session:
        ctx = await _ai_context(session)
    ans = await _ac.chat(hist, text, ctx)
    if not ans:
        # v103/v104: zanjir (Groq/Gemini) javob bermasa ham /ai ISHLAYDI —
        # lokal holat javobi
        ans = ("\u26A0\uFE0F AI zanjir (Groq/Gemini) hozir javob bermadi "
               "(limit/tarmoq). Lokal holat:\n" + ctx.replace("; ", "\n- "))
    else:
        hist.append({"role": "user", "text": text})
        hist.append({"role": "model", "text": ans})
        while len(hist) > 12:
            hist.pop(0)
    await message.answer(ans[:4000])


@router.message(Command("ai"))
async def cmd_ai(message: Message) -> None:
    """v102: /ai <savol> — bot holati va muammolar bo‘yicha javob."""
    text = (message.text or "").strip()
    if text.lower().startswith("/ai"):
        text = text[3:].strip()
    await _ai_suhbat(message, text or "Holatingni qisqacha ayt: nima ishlayapti, nima muammo?")


@router.message(Command("aitest"))
async def cmd_aitest(message: Message) -> None:
    """v104: /aitest — AI zanjirining JONLI tekshiruvi (Groq/Gemini/lokal).

    Deploy haqiqatan yangilanganmi shu buyruqdan ham ko'rinadi: hisobot
    boshida versiya (SINO-LAI-104+) chiqadi.
    """
    from app.core.access import is_admin
    uid = int(getattr(message.from_user, "id", 0) or 0)
    if not is_admin(uid):
        await message.answer("Bu buyruq faqat admin uchun.")
        return
    wait = await message.answer("🧪 AI zanjiri tekshirilyapti (10-30 soniya)...")
    try:
        from app.services import ai_chain as _ac
        rep = await _ac.aitest()
    except Exception as exc:  # noqa: BLE001
        rep = f"❌ AI test xatosi: {exc}"
    try:
        await wait.edit_text(rep[:4000])
    except Exception:  # noqa: BLE001
        await message.answer(rep[:4000])


@router.message(F.text == "\U0001F916 AI suhbat")
async def btn_ai(message: Message) -> None:
    await _ai_suhbat(message, "Salom! Bot hozir qanday ishlayapti? "
                              "Nimalarni ko‘ryapti va muammolar bormi?")
