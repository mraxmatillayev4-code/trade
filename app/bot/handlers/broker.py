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


class BrokerState(StatesGroup):
    kind = State()
    login = State()
    password = State()
    server = State()


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
        "ℹ️ <b>Qanday ishlaydi:</b> bot Render'da, MT5 terminal sizning kompyuteringizda. "
        "Shuning uchun kompyuterda <code>mt5_bridge.py</code> ishlaydi: u botdan buyruq olib "
        "MT5 da bajaradi. Avval <b>DEMO</b> hisob bilan sinab ko'ring — keyin REAL.\n"
        "To'liq qo'llanma: «📥 Ko'prik skripti» ichida.",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "brk:add")
async def cb_add(cb: CallbackQuery, state) -> None:
    if not _is_admin(cb.from_user.id if cb.from_user else None):
        await cb.answer("Faqat admin.", show_alert=True)
        return
    _TMP[int(cb.from_user.id)] = {}
    await state.set_state(BrokerState.kind)
    await cb.message.answer(
        "🏦 <b>Broker ulash — 1-qadam</b>\nHisob turini tanlang:\n"
        "🧪 <b>DEMO</b> — sinov hisobi (birinchi shuni tavsiya qilaman)\n"
        "💰 <b>REAL</b> — haqiqiy hisob (ehtiyot bo'ling!)",
        parse_mode="HTML", reply_markup=_kb_kind(),
    )
    await cb.answer()


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
    await cb.answer("Uzildi")


@router.callback_query(F.data == "brk:cancel")
async def cb_cancel(cb: CallbackQuery, state) -> None:
    await state.clear()
    _TMP.pop(int(cb.from_user.id), None)
    await cb.message.answer("Bekor qilindi.")
    await cb.answer()
