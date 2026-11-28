"""v86: SNIPER (oltin) — tugma va /sniper buyrug'i.

Tugmalar:
    🎯 Sniper (oltin)        — holat: 50$ hisob, natija, yoqilgan/o'chirilgan
    🟢 Sniperni yoqish       — skanerni ishga tushiradi
    🔴 Sniperni o'chirish    — skanerni to'xtatadi
    📦 Sniper loti           — sniper signallari uchun lot (har bir lot)
    ♻️ Sniper hisobni 50$ ga qaytarish — hisobni noldan boshlaydi
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot import keyboards as kb
from app.database.session import async_session_factory
from app.services import sniper as SN

router = Router(name="sniper")

BTN_OPEN = "\U0001F3AF Sniper (oltin)"
BTN_ON = "\U0001F7E2 Sniperni yoqish"
BTN_OFF = "\U0001F534 Sniperni o'chirish"
BTN_LOT = "\U0001F4E6 Lot hajmi (hammasi uchun)"
BTN_RESET = "\u267B\uFE0F Sniper hisobni 50$ ga qaytarish"
BTN_SCAN = "\U0001F50E Hoziroq tekshirish (skan)"


def sniper_reply() -> "kb.ReplyKeyboardMarkup":
    return kb.sniper_reply()


async def _text() -> str:
    async with async_session_factory() as session:
        st = await SN.account_stats(session)
        from app.services import lot_settings as _LS
        lot = await _LS.get(session, None)   # umumiy lot
    st["lot"] = lot
    body = SN.status_line(st)
    body += (f"\n\n\U0001F4E6 Lot hajmi (HAMMA signallar uchun): <b>{lot:,.2f}</b> "
             f"(har bir lot; jami {lot * 2:,.2f} lot)")
    body += ("\n\nTugmalar: <b>\U0001F7E2 yoqish</b> \u00b7 <b>\U0001F534 o'chirish</b> "
             "\u00b7 <b>\U0001F4E6 lot</b> \u00b7 <b>\u267B\uFE0F 50$ ga qaytarish</b>")
    return body


@router.message(Command("sniper"))
async def cmd_sniper(message: Message) -> None:
    await message.answer(await _text(), parse_mode="HTML", reply_markup=sniper_reply())


@router.message(F.text == BTN_OPEN)
async def open_sniper(message: Message) -> None:
    await message.answer(await _text(), parse_mode="HTML", reply_markup=sniper_reply())


@router.message(Command("skan"))
async def cmd_scan(message: Message) -> None:
    """v93: /skan — sniperni HOZIR ishga tushiradi va nima ko'rganini yozadi."""
    await scan_now(message)


@router.message(F.text == BTN_SCAN)
async def scan_now(message: Message) -> None:
    wait = await message.answer("\U0001F50E Skan qilinmoqda (1d / 4h / 1h \u2192 M1)...")
    try:
        res = await SN.force_scan(None)
    except Exception as exc:  # noqa: BLE001
        res = {"made": 0, "diag": [f"\u26A0\uFE0F Skan xatosi: {type(exc).__name__}: {exc}"]}
    head = ("\u2705 <b>SIGNAL TOPILDI va ochildi!</b>" if res.get("made")
            else "\u2139\uFE0F <b>Bu skanda setup topilmadi</b> (sababi pastda)")
    try:
        await wait.delete()
    except Exception:  # noqa: BLE001
        pass
    await message.answer(head + "\n" + "\n".join(res.get("diag") or []),
                         parse_mode="HTML", reply_markup=sniper_reply())


@router.message(F.text == BTN_ON)
async def turn_on(message: Message) -> None:
    async with async_session_factory() as session:
        await SN.set_enabled(session, True)
        await SN.ensure_account(session)
    await message.answer(
        "\U0001F7E2 <b>SNIPER YOQILDI</b>\n"
        "Oltin (XAUUSD): <b>1d / 4h / 1h</b> kuzatiladi, tahlil va savdo <b>M1</b> da.\n"
        "M1 da: SNR supurilishi + impuls + FVG/OB (ball >= 7.0, 15 daqiqa oralig'i).\n"
        "<i>Signal topilsa karta keladi va savdo ALOHIDA 50$ hisobda ochiladi.</i>",
        parse_mode="HTML", reply_markup=sniper_reply())


@router.message(F.text == BTN_OFF)
async def turn_off(message: Message) -> None:
    async with async_session_factory() as session:
        await SN.set_enabled(session, False)
    await message.answer("\U0001F534 <b>SNIPER O'CHIRILDI</b>\n"
                         "Yangi sniper signallari qidirilmaydi (ochiq bitimlar "
                         "odatdagidek kuzatiladi).",
                         parse_mode="HTML", reply_markup=sniper_reply())


@router.message(F.text == BTN_LOT)
async def sniper_lot(message: Message) -> None:
    from app.services import lot_settings as _LS
    async with async_session_factory() as session:
        lot = await _LS.get(session, None)   # umumiy lot
    await message.answer(
        "\U0001F4E6 <b>LOT HAJMI (hammasi uchun)</b>\n"
        "Bu — <b>barcha signallar</b> uchun (kanal signallari ham, sniper ham) "
        "har bir lot hajmi:\n"
        + "\n".join(f"  \u2022 {c:,.2f} lot" for c in _LS.LOT_CHOICES)
        + f"\n\nJoriy: <b>{lot:,.2f}</b>\nMisol: 0.01 \u2192 har lot 0.01 "
          "(jami 0.02 lot).\n<i>O'zgartirish: /lot buyrug'i (Sozlamalar ichida ham bor).</i>",
        parse_mode="HTML")


@router.message(F.text == BTN_RESET)
async def sniper_reset(message: Message) -> None:
    async with async_session_factory() as session:
        await SN.ensure_account(session, reset=True)
        st = await SN.account_stats(session)
    await message.answer(
        f"\u267B\uFE0F Sniper hisobi <b>{SN.SNIPER_BALANCE:,.0f}$</b> ga qaytarildi.\n"
        f"Balans: <b>{st['balance']:,.2f}$</b> \u00b7 natija 0.00$",
        parse_mode="HTML", reply_markup=sniper_reply())
