"""Coin/symbol nomlari — bozordagi rasmiy va tushunarli ko'rinish."""
from __future__ import annotations

# Ramz → to'liq nomi (rasmiy loyiha nomi)
COIN_NAMES: dict[str, str] = {
    "ETH": "Ethereum",
    "BNB": "BNB",
    "SOL": "Solana",
    "XRP": "XRP (Ripple)",
    "DOGE": "Dogecoin",
    "ADA": "Cardano",
    "AVAX": "Avalanche",
    "LINK": "Chainlink",
    "PAXG": "Oltin (PAX Gold)",
    "XAU": "Oltin (XAU/USD)",
    "SILVER": "Kumush (XAG/USD)",
    "USOIL": "Neft (WTI/USD)",
    "UKOIL": "Neft (Brent/USD)",
    "NGAS": "Tabiiy gaz (NG/USD)",
    "COPPER": "Mis (XCU/USD)",
    "AUD": "Avstraliya dollari (AUD/USD)",
    "GBP": "Funt (GBP/USD)",
    "EUR": "Yevro (EUR/USD)",
    "JPY": "Yen (USD/JPY)",
    "BTC": "Bitcoin (BTC/USD)",
}

# Juftlikdagi savdo valyutalari (qisqartma uchun)
_QUOTES = ("USDT", "USDC", "BUSD", "FDUSD", "BUSD", "TUSD", "BTC", "ETH", "BNB", "USD")


def split_symbol(symbol: str) -> tuple[str, str]:
    """'SOLUSDT' → ('SOL', 'USDT')."""
    symbol = symbol.upper()
    for q in _QUOTES:
        if symbol.endswith(q) and len(symbol) > len(q):
            return symbol[: -len(q)], q
    # Umumiy holat: oxirgi 4 harf quote deb olinadi (USDT kabi)
    if len(symbol) > 4:
        return symbol[:-4], symbol[-4:]
    return symbol, ""


def pair_display(symbol: str) -> str:
    """'SOLUSDT' → 'SOL/USDT'."""
    base, quote = split_symbol(symbol)
    return f"{base}/{quote}" if quote else base


def coin_name(symbol: str) -> str:
    """'SOLUSDT' → 'Solana'. Noma'lum bo'lsa ramzni qaytaradi."""
    base, _ = split_symbol(symbol)
    return COIN_NAMES.get(base, base)


def full_label(symbol: str) -> str:
    """'SOLUSDT' → 'SOL/USDT (Solana)'."""
    name = coin_name(symbol)
    pair = pair_display(symbol)
    if name and name != split_symbol(symbol)[0]:
        return f"{pair} ({name})"
    return pair


# Kanal parse / foydalanuvchi yozuvi → ichki ramz
_ALIASES: dict[str, str] = {
    "GOLD": "XAUUSDT", "XAU": "XAUUSDT", "XAUUSD": "XAUUSDT", "XAUUSDT": "XAUUSDT",
    "OLTIN": "XAUUSDT", "XAU/USD": "XAUUSDT", "GOLDUSD": "XAUUSDT", "XAUUS": "XAUUSDT",
    "BTC": "BTCUSDT", "BITCOIN": "BTCUSDT", "BTCUSD": "BTCUSDT", "BTCUSDT": "BTCUSDT",
    "BTC/USD": "BTCUSDT",
    "ETH": "ETHUSDT", "ETHUSD": "ETHUSDT", "ETHUSDT": "ETHUSDT",
    "EURUSD": "EURUSDT", "EUR/USD": "EURUSDT", "EUR": "EURUSDT", "EURUSDT": "EURUSDT",
    "GBPUSD": "GBPUSDT", "GBP/USD": "GBPUSDT", "GBP": "GBPUSDT", "GBPUSDT": "GBPUSDT",
    "USDJPY": "JPYUSDT", "USD/JPY": "JPYUSDT", "JPY": "JPYUSDT", "JPYUSDT": "JPYUSDT",
    "SILVER": "SILVERUSDT", "XAG": "SILVERUSDT", "XAGUSD": "SILVERUSDT",
    "SILVERUSDT": "SILVERUSDT",
    "OIL": "USOILUSDT", "WTI": "USOILUSDT", "USOIL": "USOILUSDT", "CL": "USOILUSDT",
    "USOILUSDT": "USOILUSDT",
    "BRENT": "UKOILUSDT", "UKOIL": "UKOILUSDT", "UKOILUSDT": "UKOILUSDT",
    "SOL": "SOLUSDT", "SOLANA": "SOLUSDT", "SOLUSDT": "SOLUSDT",
    "ETH": "ETHUSDT", "ETHEREUM": "ETHUSDT",
    "BNB": "BNBUSDT", "BNBUSDT": "BNBUSDT",
    "XRP": "XRPUSDT", "XRPUSDT": "XRPUSDT",
    "DOGE": "DOGEUSDT", "DOGEUSDT": "DOGEUSDT",
    "ADA": "ADAUSDT", "ADAUSDT": "ADAUSDT", "CARDANO": "ADAUSDT",
    "LINK": "LINKUSDT", "AVAX": "AVAXUSDT", "RIPPLE": "XRPUSDT",
    "LITECOIN": "LTCUSDT", "LTC": "LTCUSDT", "LTCUSDT": "LTCUSDT",
    "DOT": "DOTUSDT", "DOTUSDT": "DOTUSDT", "MATIC": "MATICUSDT",
    "ATOM": "ATOMUSDT", "NEAR": "NEARUSDT", "APT": "APTUSDT",
    "SUI": "SUIUSDT", "PEPE": "PEPEUSDT", "TRX": "TRXUSDT",
    "TON": "TONUSDT", "UNI": "UNIUSDT",

    "NZDUSD": "NZDUSDT", "NZD": "NZDUSDT", "AUDUSD": "AUDUSDT", "AUD": "AUDUSDT",
    "USDCAD": "CADUSDT", "CAD": "CADUSDT", "USDCHF": "CHFUSDT", "CHF": "CHFUSDT",
}


def resolve_symbol(raw: str | None) -> str | None:
    """'gold' / 'XAUUSD' / 'BTC' → 'XAUUSDT' / 'BTCUSDT'. Noma'lum → None."""
    if not raw:
        return None
    key = str(raw).strip().upper().replace(" ", "").replace("-", "").replace("_", "")
    key = key.replace("/", "")
    if key in _ALIASES:
        return _ALIASES[key]
    # BTCUSDT kabi to'liq ramz
    if key.endswith("USDT") and 6 <= len(key) <= 16 and key.isalnum():
        return key
    return None


# Taxminiy savdo diapazoni — noto'g'ri juftlikni narxga qarab tuzatish
_SYMBOL_RANGE: dict[str, tuple[float, float]] = {
    "XAUUSDT": (1500.0, 8000.0),
    "SILVERUSDT": (10.0, 80.0),
    "BTCUSDT": (10000.0, 500000.0),
    "ETHUSDT": (80.0, 20000.0),
    "ADAUSDT": (0.02, 15.0),
    "SOLUSDT": (5.0, 2000.0),
    "DOGEUSDT": (0.01, 5.0),
    "XRPUSDT": (0.1, 20.0),
    "BNBUSDT": (50.0, 2000.0),
    "EURUSDT": (0.7, 1.6),
    "GBPUSDT": (0.8, 2.2),
    "AUDUSDT": (0.4, 1.2),
    "USOILUSDT": (20.0, 200.0),
    "UKOILUSDT": (20.0, 200.0),
}


def fit_symbol(symbol: str | None, price: float | None) -> str | None:
    """CARDANO + 4009 (oltin) → XAUUSDT. ADA + 0.45 → ADAUSDT."""
    if not symbol:
        if price and 1500 <= float(price) <= 8000:
            return "XAUUSDT"
        return None
    if price is None:
        return symbol
    try:
        px = float(price)
    except (TypeError, ValueError):
        return symbol
    lo_hi = _SYMBOL_RANGE.get(symbol)
    if lo_hi and lo_hi[0] <= px <= lo_hi[1]:
        return symbol
    if 1500 <= px <= 8000:
        return "XAUUSDT"
    if 10000 <= px <= 500000:
        return "BTCUSDT"
    return symbol
