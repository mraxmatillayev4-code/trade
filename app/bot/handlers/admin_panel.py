# -*- coding: utf-8 -*-
"""v121: ADMIN panel — bir nechta adminlarni boshqarish.

- Super-admin (eng birinchi) — hech kim uni adminlikdan o'chira olmaydi.
- Admin qo'shish/o'chirish — FAQAT super-admin.
- Boshqa adminlar — hamma ishlarni bajarishi mumkin (aslida is_admin tekshiradi).
- AUDIT: biror admin nima qilsa (paper toggl, signal, broker ulash) — super-ga
  Telegram xabar boradi (audit_text + notify_super).
"""
from __future__ import annotations

import html
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.core import access as ACC
from app.core.logging import get_logger
from app.bot import keyboards as kb

logger = get_logger(__name__)
router = Router(name="admin_panel")


class AdminState(StatesGroup):
    add_id = State()
    del_id = State()


def _is_admin(uid: int | None) -> bool:
    return ACC.is_admin(uid)


def _actor(message) -> tuple[int, str]:
    u = message.from_user
    if not u:
        return 0, "?"
    name = ("@" + u.username) if u.username else html.escape(u.full_name or "?")
    return int(u.id), name


def _kb_panel(uid: int) -> InlineKeyboardMarkup:
    """Super-gacha to'liq panel; odatiy admin — faqat ro'yxat."""
    rows: list[list[InlineKeyboardButton]] = [[
        InlineKeyboardButton(text="📋 Adminlar ro'yxati", callback_data="adm:list"),
        InlineKeyboardButton(text="📜 Oxirgi harakatlar", callback_data="adm:audit"),
    ]]
    if ACC.is_super_admin(uid):
        rows.append([
            InlineKeyboardButton(text="➕ Admin qo'shish", callback_data="adm:add"),
            InlineKeyboardButton(text="➖ Adminni o'chirish", callback_data="adm:del"),
        ])
    rows.append([InlineKeyboardButton(text="❌ Yopish", callback_data="adm:close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _admins_text() -> str:
    rows = ACC.list_admins()
    if not rows:
        return ("👥 <b>ADMINLAR</b>\n━━━━━━━━━━━━━━━━\n"
                "Hozircha hech kim admin emas.")
    lines = ["👥 <b>ADMINLAR</b>", "━━━━━━━━━━━━━━━━"]
    for i, r in enumerate(rows, 1):
        sup = r["role"] == "super"
        icon = "👑" if sup else "🛡"
        tag = " <b>(SUPER-ADMIN — o'chirilmaydi)</b>" if sup else " (admin)"
        lines.append(f"{i}. {icon} <code>{r['id']}</code>{tag}")
    return "\n".join(lines)


# -------------------------------------------------------------- menyu
@router.message(Command("admin"))
@router.message(F.text == "\U0001F6E1 Adminlar")
async def cmd_admin(message: Message, state) -> None:
    uid = message.from_user.id if message.from_user else None
    if not _is_admin(uid):
        await message.answer("👥 Adminlar — faqat admin.")
        return
    await state.clear()
    text = await _admins_text()
    sup = ACC.is_super_admin(uid)
    kb_ = _kb_panel(int(uid))
    tail = ("\n\n👑 Siz <b>SUPER-ADMIN</b> siz — admin qo'shish/o'chirish sizniki."
            if sup else
            "\n\n🛡 Siz adminsiz — admin qo'shish/o'chirish faqat super-adminga.")
    await message.answer(text + tail, parse_mode="HTML", reply_markup=kb_)


# ---------------------------------------------------------- ro'yxat
@router.callback_query(F.data == "adm:list")
async def cb_adm_list(cb: CallbackQuery, state) -> None:
    if not _is_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("Faqat admin.", show_alert=True)
        return
    text = await _admins_text()
    await cb.message.answer(text, parse_mode="HTML")
    await cb.answer()


# ------------------------------------------------------- audit ko'rish
@router.callback_query(F.data == "adm:audit")
async def cb_adm_audit(cb: CallbackQuery, state) -> None:
    if not _is_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("Faqat admin.", show_alert=True)
        return
    await cb.message.answer(
        "📜 <b>Audit jurnali</b>\n"
        "Boshqa admin nima qilsa, super-admin Telegram'da ANIQ xabar oladi:\n"
        "• 🟢/🔴 Paper avto-trade yoqish/o'chirish\n"
        "• ☁️ MetaaAPI ulash · 💻 Lokal ko'prik ulash · 🔗 Uzish\n"
        "• ➕/➖ Admin qo'shish/o'chirish\n"
        "• ⚙️ Risk/lot sozlamalarini o'zgartirish\n\n"
        "Yozuvlar SystemLog da 'audit' komponentida saqlanadi.",
        parse_mode="HTML")
    await cb.answer()


# ---------------------------------------------------------- qo'shish
@router.callback_query(F.data == "adm:add")
async def cb_adm_add(cb: CallbackQuery, state) -> None:
    uid = int(cb.from_user.id) if cb.from_user else 0
    if not ACC.is_super_admin(uid):
        await cb.answer("⛔ Faqat SUPER-ADMIN admin qo'sha oladi.", show_alert=True)
        return
    await state.set_state(AdminState.add_id)
    await cb.message.answer(
        "➕ <b>Admin qo'shish</b>\n"
        "Yangi adminning <b>Telegram ID</b> (raqam) yuboring.\n"
        "ID qayerdan: u odam @userinfobot ga /start bossa chiqadi.\n"
        "Bekor: /admin",
        parse_mode="HTML")
    await cb.answer()


# ---------------------------------------------------------- o'chirish
@router.callback_query(F.data == "adm:del")
async def cb_adm_del(cb: CallbackQuery, state) -> None:
    uid = int(cb.from_user.id) if cb.from_user else 0
    if not ACC.is_super_admin(uid):
        await cb.answer("⛔ Faqat SUPER-ADMIN admanni o'chira oladi.", show_alert=True)
        return
    await state.set_state(AdminState.del_id)
    await cb.message.answer(
        "➖ <b>Admenni o'chirish</b>\n"
        "O'chiriladigan admin ID (raqam) yuboring.\n"
        "ESLATMA: SUPER-ADMIN (👑) o'chirilmaydi — hech qachon.\n"
        "Bekor: /admin",
        parse_mode="HTML")
    await cb.answer()


# ---------------------------------------------------------- holatlar
@router.message(AdminState.add_id, F.text)
async def st_add(message: Message, state) -> None:
    uid, actor = _actor(message)
    if not ACC.is_super_admin(uid):
        await state.clear()
        return
    txt = (message.text or "").strip()
    if not re.fullmatch(r"\d{4,20}", txt):
        await message.answer("Noto'g'ri fig raqam. Telegram ID faqat raqamlardan iborat (4-20 raqam).")
        return
    new_id = int(txt)
    if new_id == uid:
        await state.clear()
        await message.answer("Bu sizsiz — allaqachon adminsiz 😀")
        return
    if ACC.is_admin(new_id):
        await state.clear()
        await message.answer("Bu ID allaqachon admin.")
        return
    ok = await ACC.add_admin(new_id)
    await state.clear()
    if ok:
        await message.answer(
            f"✅ Admin qo'shildi: <code>{new_id}</code>\n"
            "U endi botning barcha admin bo'limlarini ishlata oladi.",
            parse_mode="HTML")
        # super-ga xabar KERAK EMAS — super o'zi qildi
        # lekin YANGI ADMINGA xush kelibsiz xabari
        try:
            bot = message.bot
            await bot.send_message(new_id,
                "🎉 Sizga SINO botda <b>ADMIN</b> huquqi berildi!\n"
                "Endi barcha admin bo'limlari ochiq. Savollar: /start",
                parse_mode="HTML")
        except Exception as exc:  # noqa: BLE001
            logger.warning("/admin qo'shildi xabari: %s", exc)
    else:
        await message.answer("Saqlanmadi — qaytadan urinib ko'ring.")


@router.message(AdminState.del_id, F.text)
async def st_del(message: Message, state) -> None:
    uid, actor = _actor(message)
    if not ACC.is_super_admin(uid):
        await state.clear()
        return
    txt = (message.text or "").strip()
    if not re.fullmatch(r"\d{4,20}", txt):
        await message.answer("Noto'g'ri fig. Telegram ID raqamlaridan iborat.")
        return
    old_id = int(txt)
    res = await ACC.remove_admin(old_id)
    await state.clear()
    if res == "super":
        await message.answer(
            "👑 <b>SUPER-ADMIN o'chirilmaydi!</b>\n"
            "Bu ID — asosiy admin; uni hech kim, hech qachon o'chira olmaydi.",
            parse_mode="HTML")
    elif res == "notfound":
        await message.answer("Bu ID adminlar ro'yxatida yo'q.")
    else:
        await message.answer(
            f"✅ Admin o'chirildi: <code>{old_id}</code>\n"
            "U endi botni oddiy foydalanuvchi sifatida ishlata oladi (agar ro'yxatda bo'lsa).",
            parse_mode="HTML")
        try:
            bot = message.bot
            await bot.send_message(old_id,
                "ℹ️ Sino botda ADMIN huquqingiz olib tashlandi. Rahmat uchun oldingi yordam!",
                parse_mode="HTML")
        except Exception as exc:  # noqa: BLE001
            logger.warning("/admin o'chirildi xabari: %s", exc)


# ---------------------------------------------------------- yopish
@router.callback_query(F.data == "adm:close")
async def cb_adm_close(cb: CallbackQuery, state) -> None:
    await state.clear()
    try:
        await cb.message.delete()
    except Exception:  # noqa: BLE001
        pass
    await cb.answer()
