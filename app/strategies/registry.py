"""Har instrument/timeframe uchun strategiya to'plamlari.

Backtest (haqiqiy MEXC ma'lumoti, 1.5 ATR stop / 2R maqsad / 1R breakeven,
3-ovoz konsensus) asosida TANLANGAN to'plamlar. Har bir to'plam jonli darvoza
bilan bir xil sharoitda sinovdan o'tdi: barcha (asbob, TF) juftliklari POZITIV
natija berdi (jami WR ~52%, Profit Factor ~2.9).

Kalit format: (SYMBOL, timeframe) -> 5 strategiya key'i.
Qolgan barcha strategiyalar faylda qoladi (LEGACY), lekin tahlilda ishtirok etmaydi.
"""
from __future__ import annotations

# ===== Sinovdan o'tgan strategiya to'plamlari (har birida 5 ta, 3+ ovoz bilan signal) =====
STRATEGY_SETS: dict[tuple[str, str | None], tuple[str, ...]] = {
    # Tuzatilgan backtest (TP2 g'alaba hisobi to'g'rilangan) — 2000 sham, PF>1 tanlangan.
    ("XAUUSDT", "15m"): ("squeeze_breakout", "obv", "ema_trend", "supertrend_pullback", "smart_money", "wavetrend"),   # PF 2.08 +17R + Cipher B timing
    ("XAUUSDT", "1h"):  ("supertrend_pullback", "trend_momentum", "ema_pullback", "squeeze_breakout", "smart_money", "wavetrend"),       # PF 1.24 +5R
    ("SILVERUSDT", "15m"): ("supertrend_pullback", "trend_momentum", "ema_pullback", "squeeze_breakout", "smart_money", "wavetrend"),    # PF 1.33 +4R
    ("USOILUSDT", "15m"): ("supertrend_pullback", "ema_trend", "stochastic", "obv", "smart_money", "wavetrend"),    # PF 1.41 +8R
    ("UKOILUSDT", "4h"):  ("supertrend_pullback", "trend_momentum", "ema_pullback", "squeeze_breakout", "smart_money", "wavetrend"),     # PF 1.14 +1R (Brent HTF)
    ("EURUSDT", "4h"):  ("supertrend_pullback", "trend_momentum", "ema_trend", "squeeze_breakout", "smart_money", "wavetrend"),       # PF 1.38 +6R
        # BTC kripto 24/7 — 6 ovozli to'plam (3+ konsensus osonroq, sifat saqlanadi).
    ("BTCUSDT", "5m"):  ("squeeze_breakout", "obv", "ema_trend", "wavetrend", "smart_money", "supertrend_pullback"),
    ("BTCUSDT", "15m"): ("squeeze_breakout", "obv", "ema_trend", "wavetrend", "smart_money", "supertrend_pullback"),
    ("BTCUSDT", "1h"):  ("squeeze_breakout", "obv", "ema_trend", "wavetrend", "smart_money", "supertrend_pullback"),
    ("BTCUSDT", "4h"):  ("squeeze_breakout", "obv", "ema_trend", "wavetrend", "smart_money", "supertrend_pullback"),
    # Qo'shimcha uylar — kuniga 20-30 sifatli signal (min_voters=3 saqlanadi).
    ("XAUUSDT", "5m"):  ("squeeze_breakout", "obv", "ema_trend", "supertrend_pullback", "smart_money", "wavetrend"),
    ("XAUUSDT", "4h"):  ("supertrend_pullback", "trend_momentum", "ema_pullback", "squeeze_breakout", "smart_money", "wavetrend"),
    ("SILVERUSDT", "1h"): ("supertrend_pullback", "trend_momentum", "ema_pullback", "squeeze_breakout", "smart_money", "wavetrend"),
    ("SILVERUSDT", "4h"): ("supertrend_pullback", "trend_momentum", "ema_pullback", "squeeze_breakout", "smart_money", "wavetrend"),
    ("USOILUSDT", "1h"): ("supertrend_pullback", "ema_trend", "stochastic", "obv", "smart_money", "wavetrend"),
    ("USOILUSDT", "4h"): ("supertrend_pullback", "trend_momentum", "ema_pullback", "squeeze_breakout", "smart_money", "wavetrend"),
    ("UKOILUSDT", "15m"): ("supertrend_pullback", "ema_trend", "stochastic", "obv", "smart_money", "wavetrend"),
    ("UKOILUSDT", "1h"): ("supertrend_pullback", "trend_momentum", "ema_pullback", "squeeze_breakout", "smart_money", "wavetrend"),
    ("EURUSDT", "15m"): ("supertrend_pullback", "trend_momentum", "ema_trend", "squeeze_breakout", "smart_money", "wavetrend"),
    ("EURUSDT", "1h"): ("supertrend_pullback", "trend_momentum", "ema_trend", "squeeze_breakout", "smart_money", "wavetrend"),
}

# Agar ro'yxatda bo'lmasa — umumiy xavfsiz to'plam
_DEFAULT = (
    "supertrend_pullback",
    "trend_momentum",
    "ema_trend",
    "squeeze_breakout",
    "smart_money",
    "wavetrend",
)

# ===== Whitelist: faqat backtest'da POZITIV edge bergan (asbob, timeframe) juftliklari.
# Ro'yxatda yo'q juftlikda signal CHIQARILMAYDI (foydasiz shovqin kesiladi).
# JPY (USD/JPY) hech bir TF da barqaror foyda bermadi -> to'liq blok.
# Faqat PRODUCTION backtest'da (killzone/MTF/conviction/lifecycle bilan)
# POZITIV natija bergan juftliklar. 5m/1h/4h ko'p asbobda choppy -> kesildi.
# min_voters=3 konsensus darvozasi asosiy sifat filtri. So'nggi choppy oynada
# faqat shu uyalar marginal/ijobiy; 4-ovoz override signalni quritgani uchun olib tashlandi.
# Faqat tuzatilgan backtest'da PF>1 (ijobiy) uylar.
# Kuniga 20-30 sifatli signal: asosiy asboblar 15m/1h/4h; BTC + XAU 5m.
# JPY baribir yopiq (barqaror edge yo'q). min_voters=3 sifat filtri.
PROFITABLE_SYMBOL_TF: dict[str, set[str]] = {
    "XAUUSDT":     {"5m", "15m", "1h", "4h"},
    "SILVERUSDT":  {"15m", "1h", "4h"},
    "USOILUSDT":   {"15m", "1h", "4h"},
    "UKOILUSDT":   {"15m", "1h", "4h"},
    "EURUSDT":     {"15m", "1h", "4h"},
    "BTCUSDT":     {"5m", "15m", "1h", "4h"},
    "JPYUSDT": set(),
}

# Har asbob uchun minimal tasdiqlovchi ovoz soni (sinovda 3 eng yaxshi natija berdi).
MIN_VOTERS_BY_SYMBOL: dict[str, int] = {
    "XAUUSDT": 3, "BTCUSDT": 3, "EURUSDT": 3,
    "SILVERUSDT": 3, "USOILUSDT": 3, "UKOILUSDT": 3,
    "AUDUSDT": 3,
}

_DEFAULT_MIN_VOTERS = 3

# ATR stop ko'paytiruvchisini (asbob, TF) bo'yicha ustun qo'yish.
# JPY 5m juda shovqinli: keng 2.5 ATR stop bilan 3-ovoz to'plam PF~1.7 beradi
# (1.5 ATR da foydasiz — stop shovqinda tez uriladi).
ATR_SL_MULT_OVERRIDE: dict[tuple[str, str], float] = {
    # hozircha yo'q — barcha asboblar standart 1.5 ATR stop bilan
}


def atr_sl_mult_for(symbol: str, timeframe: str | None = None, default: float = 1.5) -> float:
    """Asbob/TF uchun ATR stop ko'paytiruvchisi (override bo'lmasa default)."""
    sym = (symbol or "").upper()
    tf = (timeframe or "").lower()
    if tf and (sym, tf) in ATR_SL_MULT_OVERRIDE:
        return ATR_SL_MULT_OVERRIDE[(sym, tf)]
    return default


def strategy_keys_for(symbol: str, timeframe: str) -> tuple[str, ...]:
    """Asbob va timeframe uchun strategiya keylarini qaytaradi."""
    symbol = (symbol or "").upper()
    timeframe = (timeframe or "").lower()
    if (symbol, timeframe) in STRATEGY_SETS:
        return STRATEGY_SETS[(symbol, timeframe)]
    if (symbol, None) in STRATEGY_SETS:
        return STRATEGY_SETS[(symbol, None)]
    return _DEFAULT


def min_voters_for(symbol: str, timeframe: str | None = None) -> int:
    """Asbob (va ixtiyoriy TF) uchun minimal tasdiqlovchi strategiyalar soni.

    Hozir barcha asboblarda 3 ovoz (isbotlangan konsensus darvozasi). TF bo'yicha
    qattiqroq 4-ovoz talabi olib tashlandi — u signallarni quritib qo'ygan edi.
    """
    symbol = (symbol or "").upper()
    return MIN_VOTERS_BY_SYMBOL.get(symbol, _DEFAULT_MIN_VOTERS)


def timeframe_allowed(symbol: str, timeframe: str) -> bool:
    """AI barcha coin/TF ni ko'radi — filtir yo'q (JPY ham ochiq, AI o'zi tanlaydi)."""
    return True
