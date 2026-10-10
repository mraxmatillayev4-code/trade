"""Klaviaturalar: inline (xabar osti) va reply (doimiy pastki tugmalar)."""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from app.core.config import get_settings


def main_menu_reply(user_id: int | None = None) -> ReplyKeyboardMarkup:
    """Doimiy pastki klaviatura — admin va user farqi."""
    from app.core.access import is_admin
    admin = is_admin(user_id)
    kb = ReplyKeyboardBuilder()
    kb.row(
        KeyboardButton(text="🔥 Signallar"),
        KeyboardButton(text="📊 Bozor"),
    )
    kb.row(
        KeyboardButton(text="📈 Statistika"),
        KeyboardButton(text="🗓 Hisobotlar"),
    )
    kb.row(
        KeyboardButton(text="🔎 Jonli kuzatuv"),
        KeyboardButton(text="\U0001F3AF Sniper (oltin)"),
        KeyboardButton(text="💼 Hisob (paper)"),
    )
    kb.row(
        KeyboardButton(text="🤖 Avto-trade: yoqish/o'chirish"),
    )
    kb.row(
        KeyboardButton(text="💰 Balansni o'rnatish"),
        KeyboardButton(text="⚙️ Sozlamalar"),
    )
    if admin:
        kb.row(
            KeyboardButton(text="📡 Kanallar"),
            KeyboardButton(text="📚 Strategiyalar"),
        )
        # v96: ACCESS boshqaruvi — tugma orqali (buyruq shart emas)
        kb.row(KeyboardButton(text="🔐 Access (ro'yxat)"))
        # v97: odamlar soni + hammaga xabar — tugmalarda
        kb.row(
            KeyboardButton(text="🤖 AI suhbat"),
        )
        kb.row(
            KeyboardButton(text="👥 Odamlar soni"),
            KeyboardButton(text="📢 Hammaga xabar"),
        )
    # v69: «☰ Menyu» tugmasi OLIB TASHLANDI. Klaviatura endi YASHIRINADIGAN:
    # is_persistent=False — pastga surilsa yig'iladi, kerak bo'lganda xabar
    # ostidagi «☰ Menyuni qayta ochish» tugmasi bilan qaytariladi.
    kb.row(KeyboardButton(text="ℹ️ Ma'lumot"))
    return kb.as_markup(
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=False,
        input_field_placeholder="Kerakli bo'limni tanlang 👇",
    )

def channels_reply(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Kanallar bo'limi — pastki tugmalar."""
    kb = ReplyKeyboardBuilder()
    if is_admin:
        kb.row(
            KeyboardButton(text="➕ Qo'shish"),
            KeyboardButton(text="➖ O'chirish"),
        )
        kb.row(
            KeyboardButton(text="👤 Akkaunt"),
            KeyboardButton(text="🔎 Holat"),
        )
    kb.row(KeyboardButton(text="⬅️ Orqaga"))
    return kb.as_markup(
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=False,
        input_field_placeholder="Kanal qo'shing yoki orqaga 👇",
    )


def reports_reply() -> ReplyKeyboardMarkup:
    """Hisobotlar bo'limi — oddiy pastki tugmalar (kunlik/haftalik/oylik + orqaga)."""
    kb = ReplyKeyboardBuilder()
    kb.row(
        KeyboardButton(text="📅 Kunlik hisobot"),
        KeyboardButton(text="🗓 Haftalik hisobot"),
    )
    kb.row(
        KeyboardButton(text="📆 Oylik hisobot"),
        KeyboardButton(text="🔎 Sana bo'yicha"),
    )
    kb.row(KeyboardButton(text="⬅️ Orqaga"))
    return kb.as_markup(
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=False,
        input_field_placeholder="Davrni tanlang yoki sanani kiriting (KK.OO.YYYY) 👇",
    )


def settings_reply(us, risk: float | None = None) -> ReplyKeyboardMarkup:
    """Sozlamalar bo'limi — oddiy pastki tugmalar (lot, rejim, filtrlar + orqaga).

    v86: `risk` argumenti endi **LOT hajmini** bildiradi (foiz olib tashlandi).
    """
    strong = "✅" if (us and us.strong_only) else "⬜"
    buy = "✅" if (us is None or us.notify_buy) else "⬜"
    sell = "✅" if (us is None or us.notify_sell) else "⬜"
    mode = us.quality_mode if us else "BALANCED"
    try:
        from app.services import lot_settings as _LS
        _d = _LS.default_lot()
    except Exception:  # noqa: BLE001
        _d = 0.01
    _rv = risk if risk is not None else (
        getattr(us, "lot_size", None) if us is not None else None)
    try:
        _lv = _LS.clean(_rv) if _rv else _d
    except Exception:  # noqa: BLE001
        _lv = _d
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text=f"\U0001F4E6 Lot {_lv:,.2f}"), KeyboardButton(text=f"🎚 Rejim: {mode}"))
    kb.row(KeyboardButton(text=f"{strong} Faqat kuchli signallar"))
    kb.row(
        KeyboardButton(text=f"{buy} BUY xabarlari"),
        KeyboardButton(text=f"{sell} SELL xabarlari"),
    )
    kb.row(KeyboardButton(text="⬅️ Orqaga"))
    return kb.as_markup(
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=False,
        input_field_placeholder="Sozlamani tanlang 👇",
    )


def entry_reply(vals: dict | None = None) -> ReplyKeyboardMarkup:
    """v84: «KIRISH NUQTASI» sozlamalari (rejim / kutish / tanaffus)."""
    v = dict(vals or {})
    on = bool(v.get("entry_enabled", True))
    wait = int(v.get("entry_wait_min", 30) or 30)
    cool = int(v.get("entry_cool_min", 15) or 0)
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(
        text=("\U0001F535 Kirish rejimi: YOQILGAN" if on
              else "\u26AA Kirish rejimi: OCHIQ")))
    kb.row(*[KeyboardButton(text=f"\u23F1 Kutish {m} daqiqa")
             for m in (15, 30, 60, 120)])
    kb.row(*[KeyboardButton(text=f"\U0001F6E1 Tanaffus {m} daqiqa")
             for m in (0, 15, 30, 60)])
    kb.row(KeyboardButton(text="\u2B05\uFE0F Orqaga"))
    return kb.as_markup(
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=False,
        input_field_placeholder=f"Kutish {wait} daq \u00B7 tanaffus {cool} daq",
    )


def risk_reply(per_lot: float | None = None) -> ReplyKeyboardMarkup:
    """v86: LOT hajmini tanlash (har bir lot uchun) — foiz Yo'Q."""
    try:
        from app.services import lot_settings as _LS
        choices = _LS.LOT_CHOICES
        cur = _LS.clean(per_lot or _LS.DEFAULT_LOT)
    except Exception:  # noqa: BLE001
        choices, cur = (0.01, 0.02, 0.05, 0.10), 0.01
    kb = ReplyKeyboardBuilder()
    marks = [(f"\U0001F4E6 {c:,.2f} lot", c) for c in choices]
    row: list = []
    for label, _c in marks:
        row.append(KeyboardButton(text=label))
        if len(row) == 4:
            kb.row(*row)
            row = []
    if row:
        kb.row(*row)
    kb.row(KeyboardButton(text="⬅️ Orqaga"))
    return kb.as_markup(
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=False,
        input_field_placeholder=f"Lot hajmi (hozir {cur:,.2f}) 👇",
    )


def mode_reply() -> ReplyKeyboardMarkup:
    """Rejim tanlash pastki klaviaturasi."""
    kb = ReplyKeyboardBuilder()
    kb.row(
        KeyboardButton(text="🟢 Aggressive"),
        KeyboardButton(text="🟡 Balanced"),
        KeyboardButton(text="🔴 Conservative"),
    )
    kb.row(KeyboardButton(text="⬅️ Orqaga"))
    return kb.as_markup(
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=False,
        input_field_placeholder="Rejimni tanlang 👇",
    )


def hide_reply_kb() -> ReplyKeyboardRemove:
    """Pastki klaviaturani butunlay yig'adi (Telegram'ga 'olib tashla' deydi)."""
    return ReplyKeyboardRemove()


def track_kb(rows: list[tuple[str, str]], extra: list[tuple[str, str]] | None = None
             ) -> InlineKeyboardMarkup:
    """v74: jonli kuzatuv tugmalari — lotni qo'lda yopish (inson omili).

    rows: [(matn, callback_data), ...] — har bir signal uchun «✅ Yopish» tugmasi.
    """
    kb = InlineKeyboardBuilder()
    for label, data in rows:
        kb.button(text=label, callback_data=data)
    for label, data in (extra or []):
        kb.button(text=label, callback_data=data)
    kb.adjust(1)
    return kb.as_markup()


def reopen_menu_kb() -> InlineKeyboardMarkup:
    """Klaviatura yig'ilgandan keyin xabar ostida 'Qayta ochish' tugmasi."""
    kb = InlineKeyboardBuilder()
    kb.button(text="☰ Menyuni qayta ochish", callback_data="menu:reopen")
    return kb.as_markup()


def menu_controls_kb() -> InlineKeyboardMarkup:
    """v69: pastdagi klaviaturani YASHIRISH yoki QAYTA OCHISH (xabar ostida)."""
    kb = InlineKeyboardBuilder()
    kb.button(text="⌨️ Klaviaturani yashirish", callback_data="menu:hide")
    kb.button(text="☰ Menyuni qayta ochish", callback_data="menu:reopen")
    return kb.as_markup()


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔥 Signallar", callback_data="menu:signals")
    kb.button(text="📊 Bozor", callback_data="menu:market")
    kb.button(text="📚 Strategiyalar", callback_data="menu:strategies")
    kb.button(text="📈 Statistika", callback_data="menu:stats")
    kb.button(text="🧪 Backtest", callback_data="menu:backtest")
    kb.button(text="💼 Paper Trading", callback_data="menu:paper")
    kb.button(text="🗓 Hisobotlar", callback_data="menu:reports")
    kb.button(text="⚙️ Sozlamalar", callback_data="menu:settings")
    kb.button(text="ℹ️ Ma'lumot", callback_data="menu:about")
    kb.adjust(2, 2, 2, 2, 1)
    return kb.as_markup()


def reports_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📅 Kunlik", callback_data="rep:daily")
    kb.button(text="🗓 Haftalik", callback_data="rep:weekly")
    kb.button(text="📆 Oylik", callback_data="rep:monthly")
    kb.button(text="⬅️ Menyu", callback_data="menu:main")
    kb.adjust(3, 1)
    return kb.as_markup()


def signals_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📋 Barchasi", callback_data="sig:filter:all")
    kb.button(text="🟢 BUY", callback_data="sig:filter:BUY")
    kb.button(text="🔴 SELL", callback_data="sig:filter:SELL")
    kb.button(text="🔥 Kuchlilar", callback_data="sig:filter:STRONG")
    kb.button(text="⬅️ Menyu", callback_data="menu:main")
    kb.adjust(2, 2, 1)
    return kb.as_markup()


def signal_card_kb(signal_id: int, waiting: bool = False) -> InlineKeyboardMarkup:
    """Qisqa signal kartasi ostidagi tugmalar.

    v84: narx kutilayotgan bo'lsa — kutishni to'xtatish tugmasi ham chiqadi.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="❓ Nega bu signal?", callback_data=f"sig:why:{signal_id}")
    if waiting:
        kb.button(text="⏹ Kutishni bekor qilish", callback_data=f"ent:stop:{signal_id}")
    kb.button(text="🗑 Yopish", callback_data="msg:delete")
    kb.adjust(1, 1, 1)
    return kb.as_markup()


def result_short_kb(signal_id: int) -> InlineKeyboardMarkup:
    """v82: qisqa natija kartasi ostidagi tugmalar."""
    kb = InlineKeyboardBuilder()
    kb.button(text="\U0001F4D6 To'liq tafsilot", callback_data=f"res:full:{int(signal_id)}")
    kb.button(text="\U0001F5D1 Yopish", callback_data="msg:delete")
    kb.adjust(1, 1)
    return kb.as_markup()


def result_full_kb(signal_id: int) -> InlineKeyboardMarkup:
    """v82: to'liq natija sahifasi ostidagi tugmalar (orqaga qaytish)."""
    kb = InlineKeyboardBuilder()
    kb.button(text="\u2B05\uFE0F Qisqa kartaga qaytish",
              callback_data=f"res:card:{int(signal_id)}")
    kb.button(text="\U0001F5D1 Yopish", callback_data="msg:delete")
    kb.adjust(1, 1)
    return kb.as_markup()


def signal_detail_kb(signal_id: int) -> InlineKeyboardMarkup:
    """To'liq tafsilot ('Nega?') sahifasi ostidagi tugmalar."""
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Signalga qaytish", callback_data=f"sig:card:{signal_id}")
    kb.button(text="🗑 Yopish", callback_data="msg:delete")
    kb.adjust(1, 1)
    return kb.as_markup()


def signal_view_kb(signal_id: int) -> InlineKeyboardMarkup:
    """Eski nom — moslik uchun (signal kartasi bilan bir xil)."""
    return signal_card_kb(signal_id)


def report_summary_inline(token: str) -> InlineKeyboardMarkup:
    """Qisqa hisobot ostidagi inline tugma: to'liq hisobotga o'tish.
    token: 'daily' | 'weekly' | 'monthly' | 'date:YYYY-MM-DD'."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 To'liq hisobot", callback_data=f"rep:full:{token}")
    kb.adjust(1)
    return kb.as_markup()


def report_full_inline(token: str) -> InlineKeyboardMarkup:
    """To'liq hisobot ostidagi inline tugma: qisqa hisobotga qaytish."""
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Qisqa hisobotga qaytish", callback_data=f"rep:back:{token}")
    kb.button(text="🗑 Yopish", callback_data="msg:delete")
    kb.adjust(1, 1)
    return kb.as_markup()


def collapse_kb() -> InlineKeyboardMarkup:
    """Xabarni yig'ishtirish (o'chirish) tugmasi."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 Yopish", callback_data="msg:delete")
    return kb.as_markup()


def back_to_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Asosiy menyu", callback_data="menu:main")
    return kb.as_markup()


def symbols_kb(prefix: str, back_cb: str = "menu:main") -> InlineKeyboardMarkup:
    """prefix: 'mkt:sym' yoki 'bt:sym' — oxiriga ':' qo'shiladi."""
    settings = get_settings()
    kb = InlineKeyboardBuilder()
    for i, sym in enumerate(settings.symbol_list):
        kb.button(text=sym.replace("USDT", ""), callback_data=f"{prefix}:{sym}")
        if (i + 1) % 3 == 0:
            kb.adjust(3)
    kb.button(text="⬅️", callback_data=back_cb)
    n = len(settings.symbol_list)
    rows = [3] * (n // 3)
    rem = n % 3
    if rem:
        rows.append(rem)
    rows.append(1)
    kb.adjust(*rows)
    return kb.as_markup()


def timeframe_kb(prefix: str, symbol: str) -> InlineKeyboardMarkup:
    """prefix: 'mkt:tf' yoki 'bt:tf'."""
    settings = get_settings()
    kb = InlineKeyboardBuilder()
    for tf in settings.timeframe_list:
        kb.button(text=tf.upper(), callback_data=f"{prefix}:{symbol}:{tf}")
    kb.button(text="⬅️", callback_data="menu:back")
    kb.adjust(5, 1)
    return kb.as_markup()


def backtest_period_kb(symbol: str, tf: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for label, days in [("7 kun", "7d"), ("30 kun", "30d"), ("90 kun", "90d")]:
        kb.button(text=label, callback_data=f"bt:period:{symbol}:{tf}:{days}")
    kb.button(text="⬅️", callback_data="menu:backtest")
    kb.adjust(3, 1)
    return kb.as_markup()


def backtest_strategy_kb(symbol: str, tf: str, period: str) -> InlineKeyboardMarkup:
    options = [
        ("🎯 Barcha strategiyalar", "ALL"),
        ("EMA+RSI+MACD", "ema_trend"),
        ("Supertrend", "supertrend"),
        ("VWAP+RSI", "vwap"),
        ("Breakout", "breakout"),
        ("Divergence", "divergence"),
        ("Squeeze", "squeeze"),
        ("Ichimoku", "ichimoku"),
        ("Price Action", "price_action"),
        ("Stochastic", "stochastic"),
        ("OBV hajm", "obv"),
    ]
    kb = InlineKeyboardBuilder()
    for label, key in options:
        kb.button(text=label, callback_data=f"bt:run:{symbol}:{tf}:{period}:{key}")
    kb.button(text="🧬 Walk-Forward", callback_data=f"bt:wf:{symbol}:{tf}:{period}:ALL")
    kb.adjust(2, 2, 2, 2, 2, 1)
    return kb.as_markup()


def paper_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💵 Hisob", callback_data="paper:account")
    kb.button(text="📂 Ochiq pozitsiyalar", callback_data="paper:open")
    kb.button(text="📜 Tarix", callback_data="paper:history")
    kb.button(text="⬅️ Menyu", callback_data="menu:main")
    kb.adjust(2, 1, 1)
    return kb.as_markup()


def market_tf_kb(symbol: str, current_tf: str) -> InlineKeyboardMarkup:
    settings = get_settings()
    kb = InlineKeyboardBuilder()
    for tf in settings.timeframe_list:
        mark = "• " if tf == current_tf else ""
        kb.button(text=f"{mark}{tf.upper()}", callback_data=f"mkt:tf:{symbol}:{tf}")
    kb.button(text="🔄 Coin almashtirish", callback_data="menu:market")
    kb.button(text="⬅️ Menyu", callback_data="menu:main")
    kb.adjust(5, 1, 1)
    return kb.as_markup()


def settings_kb(us) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    mode = us.quality_mode if us else "BALANCED"
    kb.button(text=f"🎚 Rejim: {mode}", callback_data="set:mode")
    kb.button(text=f"{'✅' if (us and us.strong_only) else '⬜'} Faqat kuchli signallar",
              callback_data="set:strong")
    kb.button(text=f"{'✅' if (us is None or us.notify_buy) else '⬜'} BUY xabarlari",
              callback_data="set:buy")
    kb.button(text=f"{'✅' if (us is None or us.notify_sell) else '⬜'} SELL xabarlari",
              callback_data="set:sell")
    kb.button(text="⬅️ Menyu", callback_data="menu:main")
    kb.adjust(1, 1, 2, 1)
    return kb.as_markup()


def mode_choice_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🟢 Aggressive", callback_data="set:mode:AGGRESSIVE")
    kb.button(text="🟡 Balanced", callback_data="set:mode:BALANCED")
    kb.button(text="🔴 Conservative", callback_data="set:mode:CONSERVATIVE")
    kb.button(text="⬅️", callback_data="menu:settings")
    kb.adjust(3, 1)
    return kb.as_markup()

def sniper_reply() -> ReplyKeyboardMarkup:
    """v86: Sniper (oltin) boshqaruv tugmalari."""
    from aiogram.types import ReplyKeyboardMarkup as _RKM
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text="\U0001F7E2 Sniperni yoqish"),
           KeyboardButton(text="\U0001F534 Sniperni o'chirish"))
    kb.row(KeyboardButton(text="\U0001F50E Hoziroq tekshirish (skan)"))
    kb.row(KeyboardButton(text="\U0001F4E6 Lot hajmi (hammasi uchun)"),
           KeyboardButton(text="\u267B\uFE0F Sniper hisobni 50$ ga qaytarish"))
    kb.row(KeyboardButton(text="\u2B05\uFE0F Orqaga"))
    return kb.as_markup(resize_keyboard=True, one_time_keyboard=False,
                        is_persistent=False,
                        input_field_placeholder="Sniper: yoqish / o'chirish / lot")


def contact_admin_kb() -> InlineKeyboardMarkup:
    """v95: yagona tugma — ADMIN BILAN BOG'LANISH (user qoidasi)."""
    from app.services import access as _ACC
    b = InlineKeyboardBuilder()
    b.button(text=_ACC.CONTACT_LABEL, url=_ACC.ADMIN_CONTACT_URL)
    return b.as_markup()


def access_menu_kb() -> InlineKeyboardMarkup:
    """v96: Access boshqaruvi — inline tugmalar (faqat admin)."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📋 Ro'yxat", callback_data="acc:list"))
    b.row(InlineKeyboardButton(text="➕ ID qo'shish", callback_data="acc:add"),
          InlineKeyboardButton(text="➖ O'chirish", callback_data="acc:del"))
    b.row(InlineKeyboardButton(text="✏️ Limit/muddat", callback_data="acc:limit"),
          InlineKeyboardButton(text="🔄 Kvotani yangilash", callback_data="acc:reset"))
    b.row(InlineKeyboardButton(text="❌ Yopish", callback_data="acc:close"))
    return b.as_markup()


def acc_mode_kb(prefix: str) -> InlineKeyboardMarkup:
    """v97: limit turi tanlovi — YOKI signal soni YOKI kun soni (ikkalasi emas).

    prefix: 'add' (qo'shish) yoki 'lim' (limit o'zgartirish).
    """
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="\U0001F522 Nechta signal", callback_data=f"acc:{prefix}:sig"))
    b.row(InlineKeyboardButton(
        text="\U0001F4C5 Necha kun", callback_data=f"acc:{prefix}:day"))
    b.row(InlineKeyboardButton(
        text="\u267E\uFE0F Cheksiz", callback_data=f"acc:{prefix}:none"))
    b.row(InlineKeyboardButton(text="\u274C Bekor", callback_data="acc:menu"))
    return b.as_markup()


def bc_confirm_kb() -> InlineKeyboardMarkup:
    """v98: hammaga xabar — tasdiqlash + inline tugma qo'shish."""
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="\u2705 Ha, yuborilsin", callback_data="bc:yes"),
        InlineKeyboardButton(text="\u274C Bekor", callback_data="bc:no"),
    )
    b.row(InlineKeyboardButton(
        text="\U0001F517 Inline tugma qo'shish", callback_data="bc:btn"))
    return b.as_markup()


def user_menu_reply() -> ReplyKeyboardMarkup:
    """v98: ro'yxatdagi ODDIY user menyusi — admin tugmalari ko'rinmaydi.

    Faqat: shaxsiy hisob (limit + statistika) va admin bilan bog'lanish.
    """
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="\U0001F4CA Mening hisobim"))
    b.row(KeyboardButton(text="\U0001F4DE Admin bilan bog'lanish"))
    return b.as_markup(
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=False,
        input_field_placeholder="Tugmadan foydalaning \U0001F447",
    )
