"""v108 (SINO-CALC-108): 🧮 LOT/PIP KALKULYATORI — oltin (XAUUSD), FAQAT ADMIN.

Oqim: /calc yoki menyudagi «🧮 Kalkulyator» tugmasi
      → LOT kiritiladi → PIP kiritiladi
      → bot necha DOLLAR ekanini ANIQ hisoblaydi.

ANIQLIK (foydalanuvchi talabi): float ishlatilmaydi — faqat Decimal,
natija «yarim yuqoriga» (ROUND_HALF_UP) 2 xonaga yaxlitlanadi.

Botdagi oltin konvensiyasi (channel_parse.py v107 «XAU 1 pip = 0.1»
va lot_settings.CONTRACT_OZ = 100 bilan bir xil):

    * 1 pip = 0.1$ narx harakati
    * 1 lot = 100 untsiya
    ⇒  PUL($) = pip × 0.1 × 100 × lot  =  pip × lot × 10

Misollar:
    0.01 lot × 50 pip = 5.00$
    0.10 lot × 50 pip = 50.00$
      1 lot × 50 pip = 500.00$
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from app.bot import keyboards as kb
from app.core.access import is_admin
from app.core.logging import get_logger

logger = get_logger(__name__)
router = Router(name="calc")

# --- OLTIN konstantalari (ANIQLIK: Decimal — hech qanday float yo'q) ---
PIP_PRICE = Decimal("0.1")   # 1 pip = 0.1$ narx harakati (XAUUSD — bot konvensiyasi)
CONTRACT = Decimal("100")    # 1 lot = 100 untsiya (contract_size / CONTRACT_OZ)

# --- Ruxsat etilgan kiritish chegaralari (xatolardan himoya) ---
LOT_MIN = Decimal("0.001")
LOT_MAX = Decimal("100")
PIP_MAX = Decimal("100000")

BTN_TEXT = "🧮 Kalkulyator"
_CANCEL = "✖️ Bekor qilish"

_CENT = Decimal("0.01")


class CalcState(StatesGroup):
    """v108: kalkulyator holatlari — avval lot, keyin pip."""

    lot = State()
    pips = State()


# ---------------- Hisob (ANIQLIK yadrosi) ----------------

def usd_for(lot, pips) -> Decimal:
    """LOT va PIP → DOLLAR (oltin XAUUSD). ANIQ: Decimal arifmetikasi.

    $ = pips × 0.1 (pip narxi) × 100 (kontrakt) × lot
    Natija ROUND_HALF_UP bilan 2 xonaga (5 dan yuqoriga) yaxlitlanadi.
    """
    usd = Decimal(str(pips)) * PIP_PRICE * CONTRACT * Decimal(str(lot))
    return usd.quantize(_CENT, rounding=ROUND_HALF_UP)


def pip_value_usd(lot) -> Decimal:
    """Shu lotda 1 pip necha dollar (masalan 0.01 lotda $0.10)."""
    return (PIP_PRICE * CONTRACT * Decimal(str(lot))).quantize(
        _CENT, rounding=ROUND_HALF_UP)


def _parse_decimal(raw: str | None) -> Decimal | None:
    """'0.01' / '0,01' / ' 50 ' kabi yozuvni Decimal ga (xavfsiz) o'giradi."""
    t = (raw or "").strip().replace(",", ".").replace(" ", "")
    if not t:
        return None
    try:
        d = Decimal(t)
    except InvalidOperation:
        return None
    if not d.is_finite():
        return None
    return d


def _money(v: Decimal) -> str:
    """$5.00 kabi; juda kichik summa bo'lsa (0.01 dan kam) 4 xonaga."""
    if Decimal("0") < v < _CENT:
        return f"{v:.4f}".rstrip("0")
    return f"{v:,.2f}"


def _num_txt(d: Decimal) -> str:
    """0.01 / 50 / 12.5 — ortiqcha nollarsiz."""
    t = format(d.normalize(), "f")
    return t.rstrip("0").rstrip(".") if "." in t else t


# ---------------- Klaviaturalar ----------------

def _cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=_CANCEL)]],
        resize_keyboard=True,
        input_field_placeholder="Raqam yozing...",
    )


def _result_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔁 Shu lot bilan yana", callback_data="calc:again"),
        InlineKeyboardButton(text="📦 Lotni o'zgartirish", callback_data="calc:newlot"),
    ]])


# ---------------- Yordamchi ----------------
def _is_cancel_text(raw: str | None) -> bool:
    """v111: '✖️ Bekor qilish', 'bekor qilish', 'BEKOR' — har qanday variant."""
    t = (raw or "").strip().lower()
    if not t:
        return False
    return t == _CANCEL.lower() or ("bekor" in t and "qilish" in t) or t == "bekor"


def _admin(message: Message | CallbackQuery) -> bool:
    u = message.from_user
    return bool(u) and is_admin(u.id)


async def _deny(message: Message) -> None:
    await message.answer(
        "🔐 Kalkulyator faqat <b>admin</b> uchun.", parse_mode="HTML")


async def _ask_lot(target: Message, state: FSMContext) -> None:
    await state.set_state(CalcState.lot)
    await target.answer(
        "🧮 <b>LOT/PIP KALKULYATORI</b> — oltin (XAUUSD)\n"
        "━━━━━━━━━━━━━━━━\n"
        "📦 1-qadam: <b>LOT hajmini</b> yozing\n"
        "Misol: <code>0.01</code>, <code>0.05</code>, <code>0.1</code>, <code>1</code>\n\n"
        "<i>1 lot oltin = 100 untsiya · 1 pip = $0.1 harakat</i>",
        parse_mode="HTML",
        reply_markup=_cancel_kb(),
    )


async def _ask_pips(target: Message, state: FSMContext, lot: Decimal) -> None:
    await state.update_data(lot=str(lot))
    await state.set_state(CalcState.pips)
    await target.answer(
        f"📦 Lot: <b>{_num_txt(lot)}</b> · 1 pip = <b>${pip_value_usd(lot):,.2f}</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        "📏 2-qadam: <b>PIP sonini</b> yozing\n"
        "Misol: <code>20</code>, <code>50</code>, <code>150</code>",
        parse_mode="HTML",
        reply_markup=_cancel_kb(),
    )


# ---------------- Handlerlar ----------------

@router.message(F.text == _CANCEL, CalcState.lot)
@router.message(F.text == _CANCEL, CalcState.pips)
async def calc_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "✖️ Kalkulyator yopildi.",
        reply_markup=kb.main_menu_reply(
            message.from_user.id if message.from_user else None),
    )


@router.message(Command("calc"))
@router.message(F.text == BTN_TEXT)
async def calc_start(message: Message, state: FSMContext) -> None:
    """v108: kalkulyatorni boshlash — FAQAT ADMIN (menyu tugmasi ham shu yerga keladi)."""
    if not _admin(message):
        await _deny(message)
        return
    await state.clear()
    await _ask_lot(message, state)


@router.message(CalcState.lot)
async def calc_got_lot(message: Message, state: FSMContext) -> None:
    # v111 XATO TUZATISH: aiogram birinchi MOS handler'ni o'qiydi — shu handler
    # barcha matnlarni ushlaydi, shu sababli "Bekor qilish" ham shu yerga kelib
    # «Lot xato» deb o'qilardi. Avval bekor tekshiruvi qilamiz.
    if _is_cancel_text(message.text) or message.text == _CANCEL:
        await calc_cancel(message, state)
        return
    if not _admin(message):
        await state.clear()
        await _deny(message)
        return
    lot = _parse_decimal(message.text)
    if lot is None or lot < LOT_MIN or lot > LOT_MAX:
        await message.answer(
            "⚠️ Lot xato. <b>0.001</b> dan <b>100</b> gacha raqam yozing "
            "(masalan: <code>0.01</code>)\nYoki: " + _CANCEL,
            parse_mode="HTML", reply_markup=_cancel_kb())
        return
    await _ask_pips(message, state, lot)


@router.message(CalcState.pips)
async def calc_got_pips(message: Message, state: FSMContext) -> None:
    if not _admin(message):
        await state.clear()
        await _deny(message)
        return
    if _is_cancel_text(message.text) or message.text == _CANCEL:
        await calc_cancel(message, state)
        return
    pips = _parse_decimal(message.text)
    if pips is None or pips <= 0 or pips > PIP_MAX:
        await message.answer(
            "⚠️ Pip xato. <b>0</b> dan katta raqam yozing "
            "(masalan: <code>50</code>)\nYoki: " + _CANCEL,
            parse_mode="HTML", reply_markup=_cancel_kb())
        return
    data = await state.get_data()
    lot = _parse_decimal(str(data.get("lot") or "")) or Decimal("0.01")
    # Natija kartasi — ANIQ hisob (Decimal)
    usd = usd_for(lot, pips)
    move = (pips * PIP_PRICE).quantize(_CENT, rounding=ROUND_HALF_UP)
    await state.set_state(None)  # ma'lumot saqlanadi (calc:again uchun), holat yopiladi
    await message.answer(
        "🧮 <b>NATIJA</b> — oltin (XAUUSD)\n"
        "━━━━━━━━━━━━━━━━\n"
        f"📦 Lot: <b>{_num_txt(lot)}</b>\n"
        f"📏 Pip: <b>{_num_txt(pips)}</b> (narx harakati: <b>${_money(move)}</b>)\n"
        "━━━━━━━━━━━━━━━━\n"
        f"💰 <b>${_money(usd)}</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        f"<i>Hisob: {_num_txt(pips)} pip × $0.1 × 100 × {_num_txt(lot)} lot\n"
        f"📌 Shu lotda 1 pip = <b>${pip_value_usd(lot):,.2f}</b>\n"
        "TP bo'lsa foyda, SL bo'lsa zarar — summa bir xil.</i>",
        parse_mode="HTML",
        reply_markup=kb.main_menu_reply(message.from_user.id),
    )
    await message.answer("Yana hisoblashni xohlaysizmi? 👇",
                         reply_markup=_result_kb())
    logger.info("[CALC] admin=%s lot=%s pips=%s -> $%s",
                message.from_user.id, lot, pips, usd)


# --- Natija ostidagi tugmalar ---

@router.callback_query(F.data == "calc:again")
async def cb_calc_again(cb: CallbackQuery, state: FSMContext) -> None:
    """Shu lot bilan qayta — faqat yangi pip so'raladi."""
    if not _admin(cb):
        await cb.answer("🔐 Faqat admin uchun.", show_alert=True)
        return
    data = await state.get_data()
    lot = _parse_decimal(str(data.get("lot") or ""))
    await cb.answer()
    if lot is None or cb.message is None:
        await _ask_lot(cb.message, state)
        return
    await _ask_pips(cb.message, state, lot)


@router.callback_query(F.data == "calc:newlot")
async def cb_calc_newlot(cb: CallbackQuery, state: FSMContext) -> None:
    """Lotni ham o'zgartirib qayta hisoblash."""
    if not _admin(cb):
        await cb.answer("🔐 Faqat admin uchun.", show_alert=True)
        return
    await cb.answer()
    if cb.message is not None:
        await _ask_lot(cb.message, state)
