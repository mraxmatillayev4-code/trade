"""v74: 🏦 BROKER USTASI — MetaTrader 5 (demo / real) ulash.

Oqim:
  1) «🏦 Broker» tugmasi yoki /broker;
  2) hisob turi: DEMO (birinchi shu) yoki REAL;
  3) login (raqam) → parol (xabar o'chiriladi) → server (masalan MetaQuotes-Demo);
  4) bot token beradi va kompyuterda ishga tushiriladigan
     `mt5_bridge.py` ko'prigini aytadi;
  5) ko'prik ulangach holat: balans, equity, ochiq pozitsiyalar, navbat.

Bot Render'da, MT5 terminal sizning kompyuteringizda — shuning uchun ko'prik
o'zi botga murojaat qiladi (faqat chiquvchi aloqa, port ochish shart emas).
"""
from __future__ import annotations

import base64
import gzip

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.bot import keyboards as kb
from app.core.access import is_admin
from app.core.logging import get_logger
from app.database.session import async_session_factory
from app.services import broker as brk

router = Router(name="broker")
logger = get_logger(__name__)

_TMP: dict[int, dict] = {}


async def _menu_exit(message: Message, state: FSMContext) -> None:
    """v111: broker wizard ichida menyu tugmasi bosilsa — wizard yopilib,
    tugma xabari menyu handleriga o'tadi."""
    from app.bot.keyboards import is_menu_text
    if is_menu_text(getattr(message, "text", None)):
        try:
            await state.clear()
        finally:
            raise SkipHandler()



class BrokerState(StatesGroup):
    kind = State()
    login = State()
    password = State()
    server = State()
    api_token = State()
    account_id = State()
    # v125: bot o'zi akkaunt yaratadigan (OSON) yo'l — saytda account ID qidirish
    # kerak emas, faqat MT5 login/parol/server yuboriladi.
    mlogin = State()
    mpassword = State()
    mserver = State()


def _kb_kind() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🧪 DEMO (sinov)", callback_data="brk:kind:demo"),
        InlineKeyboardButton(text="💰 REAL (haqiqiy)", callback_data="brk:kind:real"),
    ], [
        InlineKeyboardButton(text="⬅️ Bekor", callback_data="brk:cancel"),
    ]])


def _kb_status() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔄 Holatni yangilash", callback_data="brk:status"),
    ], [
        InlineKeyboardButton(text="📥 Ko'prik skripti", callback_data="brk:script"),
        InlineKeyboardButton(text="🔑 Yangi token", callback_data="brk:token"),
    ], [
        InlineKeyboardButton(text="🗑 Ulanishni uzish", callback_data="brk:off"),
    ]])


def _kb_start() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="➕ Broker ulash", callback_data="brk:add"),
    ], [
        InlineKeyboardButton(text="📥 Ko'prik skripti", callback_data="brk:script"),
    ]])


BRIDGE_SCRIPT = '''#!/usr/bin/env python3
"""SINO AI <-> MetaTrader 5 ko'prigi (sizning kompyuteringizda ishlaydi).

1) MetaTrader 5 terminalini ochib, DEMO hisobga kiring (yoki real hisobga).
2) Terminalda: Tools -> Options -> Expert Advisors -> "Allow algorithmic trading".
3) O'rnatish:  pip install MetaTrader5 requests
4) Ishga tushirish (Windows cmd):
       set SINO_BOT=https://SIZNING-RENDER-URL
       set SINO_TOKEN=<botdan olingan token>
       python mt5_bridge.py
   Har 1 sekundda botdan buyruq oladi va natijani qaytaradi.
"""
from __future__ import annotations

import os
import time

import requests

try:
    import MetaTrader5 as mt5
except Exception:  # noqa: BLE001
    raise SystemExit("MetaTrader5 topilmadi. Avval: pip install MetaTrader5 requests")

BOT = os.environ.get("SINO_BOT", "").rstrip("/")
TOKEN = os.environ.get("SINO_TOKEN", "")
VER = "v74"
POLL = float(os.environ.get("SINO_POLL", "1.0"))

if not BOT or not TOKEN:
    raise SystemExit("SINO_BOT va SINO_TOKEN muhit o'zgaruvchilarini o'rnating.")


def _post(path: str, payload: dict) -> dict:
    try:
        r = requests.post(BOT + path, json={"token": TOKEN, **(payload or {})}, timeout=20)
        return r.json() if r.content else {}
    except Exception as exc:  # noqa: BLE001
        print("[!] aloqa:", exc)
        return {}


def _symbol(name: str) -> str:
    """Brokerda 'XAUUSD' nomi boshqacha bo'lishi mumkin (XAUUSD.a va h.k.)."""
    name = (name or "XAUUSD").upper()
    if mt5.symbol_info(name) is not None:
        return name
    for cand in (name + ".a", name + "m", name + "-", name + "_i", name + ".r", name + "c"):
        if mt5.symbol_info(cand) is not None:
            return cand
    for s in (mt5.symbols_get() or []):
        if s.name.upper().startswith(name[:6]):
            return s.name
    return name


def _deal(item: dict) -> dict:
    """Bitta buyruqni bajaradi: OPEN yoki CLOSE."""
    sym = _symbol(str(item.get("symbol") or "XAUUSD"))
    lot = float(item.get("lot") or 0.5)
    lot = max(0.01, round(lot, 2))
    info = mt5.symbol_info(sym)
    if info is None:
        return {"id": item.get("id"), "ok": False, "error": "symbol topilmadi: " + sym}
    if not info.visible:
        mt5.symbol_select(sym, True)
    spread = float(info.ask - info.bid)
    if str(item.get("action")) == "OPEN":
        buy = str(item.get("side") or "BUY").upper() == "BUY"
        px = float(info.ask if buy else info.bid)
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": sym,
            "volume": lot,
            "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
            "price": px,
            "deviation": max(10, int(spread * 100000)),
            "magic": 20260921,
            "comment": str(item.get("comment") or "SINO")[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        sl = float(item.get("sl") or 0.0)
        tp = float(item.get("tp") or 0.0)
        if sl > 0:
            req["sl"] = sl
        if tp > 0:
            req["tp"] = tp
    else:  # CLOSE
        pos = mt5.positions_get(symbol=sym) or []
        if not pos:
            return {"id": item.get("id"), "ok": False, "error": "pozitsiya yo'q: " + sym}
        p = pos[0]
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": p.symbol,
            "volume": min(lot, float(p.volume)),
            "type": mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
            "position": p.ticket,
            "price": float(mt5.symbol_info(p.symbol).bid if p.type == 0
                           else mt5.symbol_info(p.symbol).ask),
            "deviation": 30,
            "magic": 20260921,
            "comment": "SINO close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
    res = mt5.order_send(req)
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        return {"id": item.get("id"), "ok": False,
                "error": str(getattr(res, "comment", "order_send xato"))}
    return {"id": item.get("id"), "ok": True,
            "ticket": int(getattr(res, "order", 0) or 0),
            "price": float(getattr(res, "price", 0.0) or 0.0)}


def main() -> None:
    if not mt5.initialize():
        raise SystemExit("MT5 initialize xato: " + str(mt5.last_error()))
    print("[OK] MT5 ulandi:", mt5.terminal_info().name)
    while True:
        data = _post("/api/broker/pull", {})
        if data.get("ok"):
            for item in data.get("items") or []:
                out = _deal(item)
                print(("  [OK] " if out.get("ok") else "  [x] ")
                      + str(item.get("action")) + " " + str(item.get("symbol")) + " "
                      + str(out.get("ticket") or out.get("error")))
                _post("/api/broker/ack", {"results": [out]})
            acc = mt5.account_info()
            pos = mt5.positions_get() or []
            _post("/api/broker/report", {
                "bridge_ver": VER,
                "balance": float(getattr(acc, "balance", 0.0) or 0.0),
                "equity": float(getattr(acc, "equity", 0.0) or 0.0),
                "positions": [{"ticket": int(p.ticket), "symbol": p.symbol,
                               "side": "BUY" if p.type == 0 else "SELL",
                               "lot": float(p.volume), "profit": float(p.profit),
                               "price": float(p.price_open)} for p in pos],
            })
        time.sleep(POLL)


if __name__ == "__main__":
    main()
'''

GUIDE = """SINO AI — BROKER (MetaTrader 5) ULASH QO'LLANMASI
=================================================
Bot o'zi broker bilan gaplashmaydi; aloqa KO'PRIK orqali bo'ladi:
  bot (Render)  <--  mt5_bridge.py (sizning kompyuteringiz)  <-->  MT5 terminal

1. BOT TOMONI (2 daqiqa)
   1) Botda «🏦 Broker» tugmasini yoki /broker ni bosing.
   2) «➕ Broker ulash» -> 🧪 DEMO (birinchi shu) ni tanlang.
   3) MT5 hisob logini (raqam), parol va server nomini yozing
      (server: MT5 da hisob ochganda ko'rinadi, masalan MetaQuotes-Demo).
   4) Bot sizga TOKEN beradi — uni nusxalab oling.

2. KOMPYUTER TOMONI (Windows)
   1) MetaTrader 5 ni ochib, DEMO hisobga kiring.
   2) Tools -> Options -> Expert Advisors -> "Allow algorithmic trading" ni belgilang.
   3) Python o'rnatilgan bo'lsin, keyin:
        pip install MetaTrader5 requests
   4) Botdan «📥 Ko'prik skripti» ni bosib mt5_bridge.py ni yuklab oling.
   5) Windows cmd da (bir qatorda):
        set SINO_BOT=https://SIZNING-BOT-URL
        set SINO_TOKEN=<botdan olingan token>
        python mt5_bridge.py
   6) Botda /broker -> holat 🟢 «ulangan» bo'lishi kerak.

3. ISHLASH TARTIBI
   • Signal kelganda bot MT5 ga ochish buyrug'ini yuboradi (Lot1 0.50, Lot2 0.50).
   • Jonli kuzatuvda «✅ Yopish — foyda ol» bosilsa — MT5 da ham yopiladi.
   • Bot hisobi (paper) baribir yuritiladi — taqqoslab ko'rasiz.

4. XAVFSIZLIK
   • REAL hisobni keyinroq ulang; avval DEMO da sinab ko'ring.
   • Parol faqat botning bazasida (kodlangan holda) turadi, tokensiz hech kim olmaydi.
   • Token oshib ketsa: /broker -> «🔑 Yangi token» (eski ko'prik to'xtaydi).
"""


def _script_file() -> BufferedInputFile:
    raw = BRIDGE_SCRIPT.encode("utf-8")
    return BufferedInputFile(gzip.compress(raw), filename="mt5_bridge.py.gz")


async def _status_text() -> str:
    async with async_session_factory() as s:
        cfg = await brk.summary(s)
    return brk.status_text(cfg)


def _is_admin(uid: int | None) -> bool:
    return is_admin(uid)


@router.message(Command("broker"))
@router.message(F.text == "\U0001F3E6 Broker")
async def cmd_broker(message: Message, state) -> None:
    uid = message.from_user.id if message.from_user else None
    if not _is_admin(uid):
        await message.answer("🏦 Broker ulash — faqat admin.")
        return
    await state.clear()
    text = await _status_text()
    async with async_session_factory() as s:
        cfg = await brk.load_cfg(s)
    kb_ = _kb_status() if brk.is_ready(cfg) else _kb_start()
    await message.answer(text, parse_mode="HTML", reply_markup=kb_)
    await message.answer(
        "ℹ️ <b>Ikki yo'l bor (v119):</b>\n"
        "☁️ <b>MetaAPI (bulut)</b> — tavsiya! MT5 akkaunt Metaapi bulutida ishlaydi: "
        "kompyuteringiz shart emas, 24/7. 1 hisobga bepul.\n"
        "💻 <b>Lokal ko'prik</b> — kompyuteringizda <code>mt5_bridge.py</code> doimiy ishlashi kerak; "
        "komp o'chsa yangi signal ochilmaydi (SL/TP broker serverida qoladi).\n"
        "«➕ Broker ulash» → yo'lni tanlang. Avval <b>DEMO</b> bilan sinab ko'ring!",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "brk:add")
async def cb_add(cb: CallbackQuery, state) -> None:
    if not _is_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("Faqat admin.", show_alert=True)
        return
    _TMP[int(cb.from_user.id)] = {}
    kb_prov = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="\u2601 MetaAPI (bulut - KOMP shart emas)", callback_data="brk:prov:metaapi"),
    ], [
        InlineKeyboardButton(text="\U0001F4BB Lokal ko\u2019prik (v74, MT5 kompyuterda)", callback_data="brk:prov:bridge"),
    ], [
        InlineKeyboardButton(text="\u2B05 Bekor", callback_data="brk:cancel"),
    ]])
    await cb.message.answer(
        "<b>Qaysi yo\u2019l bilan ulaysiz?</b>\n"
        "<b>MetaAPI (bulut)</b> - kompyuteringiz o\u2019chiq bo\u2019lsa ham savdo ishlaydi; "
        "MT5 akkauntingiz MetaaPI bulutida ulanadi. FREE tier: 1 hisobga bepul. "
        "Yaratish uchun https://app.metaaPI.cloud da ro\u2019yxatdan o\u2019tasiz.\n"
        "<b>Lokal ko\u2019prik (v74)</b> - sizning kompyuteringizda mt5_bridge.py doimiy ishlashi kerak; "
        "komp o\u2019chsa yangi signal ochilmaydi (SL/TP esa broker serverida turibdi).",
        parse_mode="HTML", reply_markup=kb_prov)
    await cb.answer()


@router.callback_query(F.data == "brk:prov:bridge")
async def cb_prov_bridge(cb: CallbackQuery, state) -> None:
    if not _is_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("Faqat admin.", show_alert=True)
        return
    _TMP[int(cb.from_user.id)] = {}
    await state.set_state(BrokerState.kind)
    await cb.message.answer(
        "\U0001F4BB <b>Lokal ko\u2019prik bilan ulash - 1-qadam</b>\nHisob turini tanlang:\n"
        "\U0001F9EA <b>DEMO</b> - sinov hisobi (avval shu) \n"
        "\U0001F4B0 <b>REAL</b> - haqiqiy hisob (ehtiyot)",
        parse_mode="HTML", reply_markup=_kb_kind(),
    )
    await cb.answer()


@router.callback_query(F.data == "brk:prov:metaapi")
async def cb_prov_metaapi(cb: CallbackQuery, state) -> None:
    if not _is_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("Faqat admin.", show_alert=True)
        return
    kb_m = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="\U0001F9EA DEMO akkaunt", callback_data="brk:mk:demo"),
        InlineKeyboardButton(text="\U0001F4B0 REAL akkaunt", callback_data="brk:mk:real"),
    ], [InlineKeyboardButton(text="\u2B05 Bekor", callback_data="brk:cancel")]])
    await cb.message.answer(
        "\u2601 <b>MetaAPI ulash - 1-qadam</b>\nHisob turini tanlang. \n"
        "URL: https://app.metaapi.cloud da ro\u2019yxatdan o\u2019tib, "
        "\u201CAccounts\u201D bo\u2019limida MT5 DEMO/REAL akkauntingizni qo\u2019shgansiz deb hisoblayman.",
        parse_mode="HTML", reply_markup=kb_m)
    await cb.answer()


@router.callback_query(F.data.startswith("brk:mk:"))
async def cb_mk(cb: CallbackQuery, state) -> None:
    if not _is_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("Faqat admin.", show_alert=True)
        return
    kind = (cb.data or "").split(":")[-1]
    _TMP[int(cb.from_user.id)] = {"kind": kind if kind in brk.KINDS else "demo", "provider": "metaapi"}
    await state.set_state(BrokerState.api_token)
    await cb.message.answer(
        "\u2601 MetaAPI <b>2-qadam: API TOKEN</b> ni yuboring.\n"
        "Qayerdan olinadi: app.metaapi.cloud \u2192 o\u2019ng ustun \u201CAPI\u201D \u2192 \u201CTokens\u201D \u2192 \u201CCreate token\u201D.\n"
        "Token shu yerda yuboriladi, bot uni bazaga saqlab qo\u2019yadi. Bekor qilish: /broker",
        parse_mode="HTML")
    await cb.answer()


@router.message(BrokerState.api_token, F.text)
async def st_api_token(message: Message, state) -> None:
    await _menu_exit(message, state)
    tok = (message.text or "").strip()
    if len(tok) < 10:
        await message.answer("Token juda qisqa - to\u2019g\u2019ri MetaaPI tokenni yuboring.")
        return
    _TMP[int(message.from_user.id)].setdefault("metaapi", {})["api_token"] = tok
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        pass
    # v125: ikki yo'l. User tavsiyasi oson yo'l — faqat LOGIN/PAROL/SERVER.
    kb15 = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="\U0001F6E0 OSON: login/parol/server yuboram (bot yaratadi)",
                             callback_data="brk:mkauto"),
    ], [
        InlineKeyboardButton(text="\U0001F511 Tayyor account ID bor (saytda ochganman)",
                             callback_data="brk:mkid"),
    ]])
    await message.answer(
        "Token qabul qilindi \u2705\n<b>3-qadam:</b> akkaunt qaysi usulda bo\u2018lsin?\n\n"
        "\U0001F6E0 <b>OSON</b> — shunchaki MT5 akkauntingiz <b>login, parol va server nomini</b> "
        "yuborasiz; bot MetaaPI da akkauntni <b>o\u2018zi yaratadi</b> (account ID kerak emas).\n"
        "\U0001F511 <b>Qo\u2019lda</b> — saytda allaqachon akkaunt ochgan bo\u2019lsangiz, Account ID sini yuborasiz.",
        parse_mode="HTML", reply_markup=kb15)


@router.callback_query(F.data == "brk:mkid")
async def cb_mkid(cb: CallbackQuery, state) -> None:
    if not _is_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("Faqat admin.", show_alert=True)
        return
    await state.set_state(BrokerState.account_id)
    await cb.message.answer(
        "<b>Qo\u2019lda yo\u2019l:</b> Account ID yuboring.\n"
        "Qayerdan: app.metaapi.cloud \u2192 Accounts \u2192 kartochkangizni bosing \u2192 "
        "\u201CAccount ID\u201D (uzun lotin satr, masalan 8c7f6...).",
        parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "brk:mkauto")
async def cb_mkauto(cb: CallbackQuery, state) -> None:
    if not _is_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("Faqat admin.", show_alert=True)
        return
    await state.set_state(BrokerState.mlogin)
    await cb.message.answer(
        "\U0001F6E0 <b>OSON yo\u2019l — 1/3 qadam: MT5 LOGIN</b> (raqam)\n"
        "Masalan: <code>67056789</code> (MetaTrader 5 ilovasidagi hisob raqamingiz).\n"
        "Bekor qilish: /broker",
        parse_mode="HTML")
    await cb.answer()


@router.message(BrokerState.mlogin, F.text)
async def st_mlogin(message: Message, state) -> None:
    await _menu_exit(message, state)
    lv = (message.text or "").strip()
    if not lv.isdigit() or len(lv) < 4:
        await message.answer("Login ko\u2018rinishi noto\u2019g\u2019ri — MT5 hisobingiz raqamini yuboring "
                             "(masalan 67056789).")
        return
    _TMP[int(message.from_user.id)]["metaapi"]["login"] = lv
    await state.set_state(BrokerState.mpassword)
    await message.answer(
        "Login olindi \u2705\n<b>2/3 qadam: MT5 PAROLI</b>\n"
        "(Xavfsizlik: bot parolni faqat MetaaPI ga uzatadi, keyin o\u2019chiriladi; "
        "xabar ham o\u2019chiriladi.)",
        parse_mode="HTML")


@router.message(BrokerState.mpassword, F.text)
async def st_mpassword(message: Message, state) -> None:
    await _menu_exit(message, state)
    pv = (message.text or "").strip()
    if len(pv) < 4 or " " in pv:
        await message.answer("Parol juda qisqa yoki bo\u2019sh joyli — qayta yuboring.")
        return
    _TMP[int(message.from_user.id)]["metaapi"]["password"] = pv
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        pass
    await state.set_state(BrokerState.mserver)
    await message.answer(
        "Parol olindi \u2705\n<b>3/3 qadam: SERVER NOMI</b>\n"
        "MT5 ilovasida: Sozlamalar \u2192 Hisob \u2192 ustunda server yozilgan; "
        "yoki broker uchuvchi xati (masalan <code>Exness-MT5Real8</code>, "
        "<code>Exness-MT5Trial</code>, <code>XMGlobal-MT5 2</code>...).\n"
        "DEMO hisob uchun ko\u2019pincha <code>Trial</code> yozuvi bo\u2019ladi.",
        parse_mode="HTML")


@router.message(BrokerState.mserver, F.text)
async def st_mserver(message: Message, state) -> None:
    await _menu_exit(message, state)
    sv = (message.text or "").strip()
    if len(sv) < 3:
        await message.answer("Server nomi juda qisqa.")
        return
    rec = _TMP[int(message.from_user.id)]
    mp = rec.get("metaapi") or {}
    await message.answer("\u23F3 MetaaPI da akkaunt yaratilmoqda va tekshirilmoqda "
                         "(30 s gacha ketishi mumkin)...")
    from app.services.broker_metaapi import MetaApiBridge, create_metaapi_account
    aid, err = await create_metaapi_account(
        mp.get("api_token", ""), mp.get("login", ""), mp.get("password", ""), sv)
    if not aid:
        await message.answer(
            "\u274C Akkaunt yaratilmadi: <code>" + err.replace("<", "&lt;") + "</code>\n\n"
            "Ko\u2019pincha server nomi xato bo\u2019ladi — broker xatidagi Aniq nomini yuboring.",
            parse_mode="HTML")
        return
    br = MetaApiBridge(mp.get("api_token", ""), aid, timeout=30.0)
    ok, err2 = await br.connect()
    if not ok:
        await message.answer(
            "\u274C Akkaunt yaratildi (ID: <code>" + aid + "</code>), lekin ulanish bo\u2019lmadi: "
            "<code>" + err2.replace("<", "&lt;") + "</code>\n"
            "Muamdo login/parol xato bo\u2019lishi mumkin — tekshirib yana urinib ko\u2019ring.",
            parse_mode="HTML")
        return
    info = await br.account_info()
    await br.close()
    async with async_session_factory() as s:
        cfg = await brk.save_cfg_metaapi(
            s, kind=rec.get("kind") or "demo",
            api_token=mp.get("api_token", ""), account_id=aid,
            user_id=int(message.from_user.id))
    await state.clear()
    _TMP.pop(int(message.from_user.id), None)
    await message.answer(
        "\u2705 <b>MetaaPI ULANDI!</b> (" + (cfg["kind"]).upper() + ", bot yaratgan yo\u2019l)\n"
        "\u2022 Broker server: <b>" + str(info.get("server") or "?") + "</b>\n"
        "\u2022 Balans: <b>" + str(info.get("balance") or "?") + "</b> "
        + str(info.get("currency") or "") + "\n\n"
        "Bundan keyin that fierta signallar avtomatik ochiladi — KOMPYUTER KERAK EMAS!\n"
        "Tekshirish: /broker \u2192 Holatni yangilash.",
        parse_mode="HTML")


@router.message(BrokerState.account_id, F.text)
async def st_account_id(message: Message, state) -> None:
    await _menu_exit(message, state)
    aid = (message.text or "").strip()
    if len(aid) < 6 or " " in aid:
        await message.answer("Account ID formati noto\u2019g\u2019ri - bo\u2019sh joy bo\u2019lmasligi kerak.")
        return
    rec = _TMP[int(message.from_user.id)]
    mp = rec.get("metaapi") or {}
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        pass
    # tekshiruv: MetaaPI SDK orqali ulanib ko\u2019ramiz
    from app.services.broker_metaapi import MetaApiBridge
    br = MetaApiBridge(mp.get("api_token", ""), aid, timeout=30.0)
    await message.answer("\u23F3 MetaaPI ga ulanyapman (26-30 s) - akkauntingiz tekshiriladi...")
    ok, err = await br.connect()
    if not ok:
        await message.answer(
            "\u274C Ulanib bo\u2019lmadi: <code>" + err.replace("<", "&lt;") + "</code>\n\n"
            "Tekshirib qayta yuboring yoki /broker bilan bekor qiling.",
            parse_mode="HTML")
        return
    info = await br.account_info()
    await br.close()
    async with async_session_factory() as s:
        cfg = await brk.save_cfg_metaapi(
            s, kind=rec.get("kind") or "demo",
            api_token=mp.get("api_token", ""), account_id=aid,
            user_id=int(message.from_user.id))
    await state.clear()
    _TMP.pop(int(message.from_user.id), None)
    # v121 AUDIT:
    try:
        from app.core import access as _ACC
        if not _ACC.is_super_admin(int(message.from_user.id)):
            uname2 = ("@" + message.from_user.username) if message.from_user.username else (message.from_user.full_name or "?")
            await _ACC.notify_super(message.bot, _ACC.audit_text(int(message.from_user.id), uname2,
                "☁️ MetaaAPI BULUT ULANDI (" + str(rec.get('kind') or 'demo').upper() + ")"),
                except_uid=int(message.from_user.id))
    except Exception:  # noqa: BLE001
        pass
    await message.answer(
        "\u2705 <b>MetaaPI ULANDI!</b> (" + (cfg["kind"]).upper() + ")\n"
        "\u2022 Broker server: <b>" + str(info.get("server") or "?") + "</b>\n"
        "\u2022 Valyuta: " + str(info.get("currency") or "?") + "\n\n"
        "Bundan keyin yangi signallar bot tomonidan avtomatik ochiladi - KOMPYUTER KERAK EMAS!\n"
        "Tekshirish: /broker \u2192 Holatni yangilash.",
        parse_mode="HTML")


@router.callback_query(F.data.startswith("brk:kind:"))
async def cb_kind(cb: CallbackQuery, state) -> None:
    if not _is_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("Faqat admin.", show_alert=True)
        return
    kind = (cb.data or "").split(":")[-1]
    _TMP[int(cb.from_user.id)] = {"kind": kind if kind in brk.KINDS else "demo"}
    await state.set_state(BrokerState.login)
    await cb.message.answer(
        ("🧪 DEMO" if kind == "demo" else "💰 REAL") + " tanlandi.\n"
        "2-qadam: <b>MT5 hisob logini</b> (raqam) yuboring, masalan "
        "<code>12345678</code>.\nBekor qilish: /broker",
        parse_mode="HTML",
    )
    await cb.answer()


@router.message(BrokerState.login, F.text)
async def step_login(message: Message, state) -> None:
    await _menu_exit(message, state)
    digits = "".join(ch for ch in (message.text or "") if ch.isdigit())
    if not digits:
        await message.answer("⚠️ Login raqam bo'lishi kerak. Qaytadan yuboring.")
        return
    _TMP.setdefault(int(message.from_user.id), {})["login"] = digits
    await state.set_state(BrokerState.password)
    await message.answer(
        "3-qadam: <b>MT5 parolini</b> yuboring (xabar o'qilgach o'chiriladi).\n"
        "<i>Parol faqat bazada kodlangan holda saqlanadi.</i>",
        parse_mode="HTML",
    )


@router.message(BrokerState.password, F.text)
async def step_password(message: Message, state) -> None:
    await _menu_exit(message, state)
    uid = int(message.from_user.id)
    pwd = (message.text or "").strip()
    if len(pwd) < 3:
        await message.answer("⚠️ Parol juda qisqa. Qaytadan yuboring.")
        return
    _TMP.setdefault(uid, {})["password"] = pwd
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        pass
    await state.set_state(BrokerState.server)
    await message.answer(
        "4-qadam: <b>server nomini</b> yuboring.\n"
        "Masalan: <code>MetaQuotes-Demo</code>, <code>ICMarketsSC-Demo</code>, "
        "<code>Exness-MT5Trial8</code>.\n"
        "<i>MT5 da login oynasida «Server» ro'yxatida turadi.</i>",
        parse_mode="HTML",
    )


@router.message(BrokerState.server, F.text)
async def step_server(message: Message, state) -> None:
    await _menu_exit(message, state)
    uid = int(message.from_user.id)
    tmp = _TMP.setdefault(uid, {})
    tmp["server"] = (message.text or "").strip()
    await state.clear()
    if not tmp.get("login") or not tmp.get("password"):
        await message.answer("⚠️ Ma'lumot to'liq emas. /broker bilan qaytadan boshlang.")
        return
    async with async_session_factory() as s:
        cfg = await brk.save_cfg(s, kind=tmp.get("kind") or "demo",
                                 login=tmp["login"], password=tmp["password"],
                                 server=tmp["server"], user_id=uid,
                                 label=str(getattr(message.from_user, "full_name", "") or ""))
        cfg = await brk.load_cfg(s)
    # v121 AUDIT:
    try:
        from app.core import access as _ACC
        if not _ACC.is_super_admin(uid):
            uname = ("@" + message.from_user.username) if message.from_user.username else (message.from_user.full_name or "?")
            await _ACC.notify_super(message.bot, _ACC.audit_text(uid, uname,
                "💻 Lokal ko'prik ulash saqlandi (" + str(tmp.get('kind') or 'demo') + ")"),
                except_uid=uid)
    except Exception:  # noqa: BLE001
        pass

    await message.answer(
        "✅ <b>Broker saqlandi</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        f"Hisob turi: <b>{brk.kind_label(cfg.get('kind'))}</b>\n"
        f"Login: <code>{brk.mask_login(cfg.get('login'))}</code> · Server: {cfg.get('server')}\n"
        f"🔑 TOKEN: <code>{cfg.get('token')}</code>\n"
        "━━━━━━━━━━━━━━━━\n"
        "Endi kompyuteringizda ko'prikni ishga tushiring:\n"
        "<code>pip install MetaTrader5 requests</code>\n"
        "<code>set SINO_BOT=https://SIZNING-BOT-URL</code>\n"
        f"<code>set SINO_TOKEN={cfg.get('token')}</code>\n"
        "<code>python mt5_bridge.py</code>\n\n"
        "Skriptni «📥 Ko'prik skripti» tugmasidan olasiz (/broker).",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "brk:status")
async def cb_status(cb: CallbackQuery) -> None:
    await cb.message.answer(await _status_text(), parse_mode="HTML", reply_markup=_kb_status())
    await cb.answer("Yangilandi")


@router.callback_query(F.data == "brk:script")
async def cb_script(cb: CallbackQuery) -> None:
    await cb.message.answer_document(
        _script_file(),
        caption=("📥 <b>mt5_bridge.py</b> — ko'prik skripti.\n"
                 "Telegram faylni yuklab olib, nomidagi .gz ni olib tashlang "
                 "(yoki arxivdan chiqarib) va Windows'da ishlating.\n"
                 "To'liq qadamlar: skript ichidagi izohlar va qo'llanma."),
        parse_mode="HTML",
    )
    await cb.message.answer(
        "<b>QO'LLANMA (qisqa)</b>\n" + GUIDE.replace("<", "&lt;")[:3500],
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(F.data == "brk:token")
async def cb_token(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("Faqat admin.", show_alert=True)
        return
    async with async_session_factory() as s:
        tok = await brk.rotate_token(s)
    await cb.message.answer(
        ("🔑 <b>Yangi token:</b> <code>%s</code>\n"
         "<i>Eski ko'prik endi ishlamaydi — yangi tokenni ko'prikda ham yangilang.</i>" % tok),
        parse_mode="HTML",
    )
    await cb.answer("Token yangilandi")


@router.callback_query(F.data == "brk:off")
async def cb_off(cb: CallbackQuery) -> None:
    if not _is_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("Faqat admin.", show_alert=True)
        return
    async with async_session_factory() as s:
        cfg = await brk.load_cfg(s)
        await brk.clear(s)
    await cb.message.answer("🗑 Broker ulanishi uzildi."
                            + (" Ochiq pozitsiyalar MT5 da qoldi — ularni terminalda yoping."
                               if cfg.get("positions") else ""),
                            reply_markup=_kb_start())
    # v121 AUDIT:
    try:
        from app.core import access as _ACC
        _uid2 = int(cb.from_user.id)
        if not _ACC.is_super_admin(_uid2):
            uname3 = ("@" + cb.from_user.username) if cb.from_user.username else (cb.from_user.full_name or "?")
            await _ACC.notify_super(cb.bot, _ACC.audit_text(_uid2, uname3,
                "🔗 BROKER ULANISHI UZILDI"), except_uid=_uid2)
    except Exception:  # noqa: BLE001
        pass
    await cb.answer("Uzildi")


@router.callback_query(F.data == "brk:cancel")
async def cb_cancel(cb: CallbackQuery, state) -> None:
    await state.clear()
    _TMP.pop(int(cb.from_user.id), None)
    await cb.message.answer("Bekor qilindi.")
    await cb.answer()
