"""SINO Local AI (LAI v50) — kalitsiz, internetsiz ishlaydigan signal o'quvchi dvigatel.

Nima qiladi (hammasi mahalliy, API key kerak emas):
  1) Normalizatsiya: o'zbek/rus/ingliz/arab yozuvi, emoji, OCR xatolari (0<->O, 1<->l, 5<->S ...)
  2) Juftlik/aktiv topish: gold/oltin/xauusd/xau/xag/btc/forex ... xato yozilgani ham (xauu5d, 60ld)
  3) Yo'nalish: vaznli lug'at (buy/sell/long/short/sotib olish/sotish/pokupka/prodazha ...) + inkor
  4) Entry / zona / SL / TP1..TP5 raqamlarini ajratish; "4339-29", "28-32" kabi qisqartmalarni to'ldirish
  5) Yo'nalish yozilmagan bo'lsa — SL/TP geometriyasidan aniqlash (SL pastda + TP yuqorida = BUY)
  6) RAD ETISH (veto): natija posti (TP HIT, +40 pip), reklama/obuna, salomlashish, "yopamiz"
  7) Takror signallarni bosish (dedupe), ishonch balli

Asosiy API:
    analyze(text, ocr="", has_image=False, ref=None) -> ParsedSignal | None
    analyze_ex(...) -> (signal | None, sabab: str, veto: bool)   # veto=True → boshqa parserlarga o'tmasin
"""
from __future__ import annotations

__version__ = "SINO-LAI-72"

import difflib
import re
import time
import unicodedata

try:  # bot ichida oddiy holat
    from app.services.channel_parse import ParsedSignal  # type: ignore
except Exception:  # mustaqil sinov (app yo'q)
    from dataclasses import dataclass, field

    @dataclass
    class ParsedSignal:  # type: ignore[no-redef]
        direction: str
        symbol: str
        timeframe: str = "1m"
        entry: float | None = None
        sl: float | None = None
        tp: float | None = None
        tps: list = field(default_factory=list)
        raw: str = ""
        tf_explicit: bool = False
        zone_low: float | None = None
        zone_high: float | None = None

    def merge_parsed(a, b):
        return a or b

try:
    from app.core.logging import get_logger

    logger = get_logger(__name__)
except Exception:  # pragma: no cover
    class _Quiet:
        def info(self, *a, **k):
            pass

        def debug(self, *a, **k):
            pass

        def warning(self, *a, **k):
            pass

    logger = _Quiet()

try:
    from app.core.symbols import fit_symbol as _fit_symbol  # type: ignore
except Exception:  # pragma: no cover
    _fit_symbol = None


# ---------------------------------------------------------------------------
# 1. NORMALIZATSIYA
# ---------------------------------------------------------------------------

_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ц": "c",
    "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "і": "i", "ї": "i", "є": "e", "ґ": "g", "ў": "o", "қ": "q", "ғ": "g",
    "ҳ": "h", "ј": "j", "ѕ": "s", "ѐ": "e", "ѣ": "e",
}

# OCR: raqam <-> harf chalkashligi. Ikkala tomon ham shu jadval bilan "kanon" qilinadi.
_CONF = {
    "0": "o", "1": "i", "2": "z", "3": "e", "4": "a", "5": "s", "6": "g", "7": "t", "8": "b", "9": "g",
    "l": "i", "|": "i", "!": "i", "q": "o", "v": "u", "w": "u",
}

# Raqam ichidagi harflar (OCR) -> raqam
_L2D = {
    "o": "0", "O": "0", "q": "0", "Q": "0", "D": "0", "d": "0",
    "i": "1", "I": "1", "l": "1", "L": "1", "|": "1", "!": "1",
    "z": "2", "Z": "2", "e": "3", "E": "3", "a": "4", "A": "4",
    "s": "5", "S": "5", "g": "6", "G": "6", "b": "8", "B": "8",
    "t": "7", "T": "7", "g": "6",
}

_ZW = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
_DASH = re.compile(r"[\u2010-\u2015\u2212\u2043\u30fc]")
_EMOJI = re.compile(
    "([\U0001F000-\U0001FAFF\u2190-\u21FF\u2300-\u23FF\u2600-\u27BF\u2B00-\u2BFF"
    "\uFE0F\u20E3\u2122\u00ae]+)"
)
_KEYCAP = {"1": "tp1", "2": "tp2", "3": "tp3", "4": "tp4", "5": "tp5",
           "6": "tp6", "7": "tp7", "8": "tp8", "9": "tp9"}

_SEP = re.compile(r"[()\[\]{}\"'`:;!?*=~^_]+")


def _pre(text: str) -> str:
    """Matnni ko'rinishga keltirish: emoji alohida, raqamlar toza."""
    t = unicodedata.normalize("NFKC", str(text or ""))
    for k, v in _KEYCAP.items():
        t = t.replace(k + "\u20e3", " " + v + " ")
    for i, ch in enumerate("\u2460\u2461\u2462\u2463\u2464\u2465\u2466\u2467\u2468", start=1):
        t = t.replace(ch, " tp%d " % i)
    t = _ZW.sub("", t).lower()
    for _q in ("'", "\u2018", "\u2019", "\u02bc", "\u2032", "`", "\u00b4", "\u2035"):
        t = t.replace(_q, "")
    t = _DASH.sub("-", t)
    t = _EMOJI.sub(r" \1 ", t)
    t = t.replace("\u00a0", " ").replace("\u202f", " ")
    # 8.000 / 4,415 -> 8000 / 4415 (raqam ichidagi minglik ajratgichi)
    t = re.sub(r"(\d)[.,](?=\d{3}(?!\d))", r"\1", t)
    t = re.sub(r"(\d),(\d)", r"\1.\2", t)          # 4415,50 -> 4415.50
    t = re.sub(r"\b(sl|stoploss|stop|tp|tps|target|entry|kirish|limit|zona|zone|zones|zonasi|zonalari)"
               r"(\d)(\d{3,})\b", r"\1\2 \3", t)
    t = re.sub(r"\b(sl|stoploss|stop|tp|tps|target|maqsad|nishon|entry|kirish|limit)"
               r"(\d{3,})\b", r"\1 \2", t)
    t = _SEP.sub(" ", t)
    t = re.sub(r"[^\w\s@#+./%:-]", " ", t, flags=re.UNICODE)
    return re.sub(r"\s+", " ", t).strip()


def _canon_word(w: str) -> str:
    """So'zning 'kanon' shakli: kirill->lotin, raqam<->harf chalkashligi yo'qoladi."""
    out = []
    for ch in str(w or "").lower():
        ch = _CYR.get(ch, ch)
        ch = _CONF.get(ch, ch)
        if ch.isalnum():
            out.append(ch)
    return "".join(out)


# ---------------------------------------------------------------------------
# 2. JUFTLIK / AKTIV
# ---------------------------------------------------------------------------

_ALIAS = {
    "gold": "XAUUSDT", "xau": "XAUUSDT", "xauusd": "XAUUSDT", "oltin": "XAUUSDT",
    "goldusd": "XAUUSDT", "xauusdt": "XAUUSDT", "tilla": "XAUUSDT", "paxg": "XAUUSDT",
    "silver": "SILVERUSDT", "xag": "SILVERUSDT", "kumush": "SILVERUSDT", "xagusd": "SILVERUSDT",
    "btc": "BTCUSDT", "bitcoin": "BTCUSDT", "btcusd": "BTCUSDT", "btcusdt": "BTCUSDT",
    "eth": "ETHUSDT", "ethereum": "ETHUSDT", "ethusd": "ETHUSDT", "ethusdt": "ETHUSDT",
    "eurusd": "EURUSDT", "eur": "EURUSDT", "gbpusd": "GBPUSDT", "gbp": "GBPUSDT",
    "usdjpy": "JPYUSDT", "jpy": "JPYUSDT", "audusd": "AUDUSDT", "aud": "AUDUSDT",
    "nzdusd": "NZDUSDT", "nzd": "NZDUSDT", "usdcad": "CADUSDT", "cad": "CADUSDT",
    "usdchf": "CHFUSDT", "chf": "CHFUSDT",
    "oil": "USOILUSDT", "wti": "USOILUSDT", "usoil": "USOILUSDT", "neft": "USOILUSDT",
    "brent": "UKOILUSDT", "ukoil": "UKOILUSDT",
    "sol": "SOLUSDT", "solana": "SOLUSDT", "bnb": "BNBUSDT", "xrp": "XRPUSDT",
    "ripple": "XRPUSDT", "doge": "DOGEUSDT", "ada": "ADAUSDT", "cardano": "ADAUSDT",
    "link": "LINKUSDT", "avax": "AVAXUSDT", "ltc": "LTCUSDT", "litecoin": "LTCUSDT",
    "dot": "DOTUSDT", "matic": "MATICUSDT", "atom": "ATOMUSDT", "near": "NEARUSDT",
    "apt": "APTUSDT", "sui": "SUIUSDT", "pepe": "PEPEUSDT", "trx": "TRXUSDT",
    "ton": "TONUSDT", "uni": "UNIUSDT", "ethbtc": "ETHBTC",
}
_ALIAS_C: dict[str, str] = {_canon_word(k): v for k, v in _ALIAS.items()}
_SYM_LEN: dict[int, list[tuple[str, str]]] = {}
for _a, _s in _ALIAS.items():
    _SYM_LEN.setdefault(len(_a), []).append((_canon_word(_a), _s))

_BAND = {
    "XAUUSDT": (1200.0, 9000.0), "SILVERUSDT": (8.0, 120.0), "BTCUSDT": (5000.0, 900000.0),
    "ETHUSDT": (50.0, 30000.0), "SOLUSDT": (2.0, 3000.0), "BNBUSDT": (20.0, 3000.0),
    "XRPUSDT": (0.05, 50.0), "DOGEUSDT": (0.005, 10.0), "ADAUSDT": (0.02, 15.0),
    "EURUSDT": (0.6, 2.0), "GBPUSDT": (0.6, 2.5), "AUDUSDT": (0.3, 1.5), "NZDUSDT": (0.3, 1.5),
    "JPYUSDT": (50.0, 400.0), "CADUSDT": (0.6, 2.2), "CHFUSDT": (0.6, 2.2),
    "USOILUSDT": (10.0, 300.0), "UKOILUSDT": (10.0, 300.0), "LINKUSDT": (1.0, 200.0),
    "AVAXUSDT": (1.0, 500.0), "LTCUSDT": (10.0, 1000.0), "DOTUSDT": (0.5, 100.0),
    "MATICUSDT": (0.05, 10.0), "ATOMUSDT": (1.0, 200.0), "NEARUSDT": (0.3, 100.0),
    "APTUSDT": (1.0, 200.0), "SUIUSDT": (0.1, 50.0), "PEPEUSDT": (0.0000001, 0.01),
    "TRXUSDT": (0.01, 5.0), "TONUSDT": (0.5, 100.0), "UNIUSDT": (1.0, 200.0),
}
_BAND_DEF = (0.0000001, 1000000.0)
_GOLDISH = (1400.0, 9000.0)

_AR_GOLD = re.compile(r"طلا|ذهب|گلد")
_AR_BUY = re.compile(r"خرید|بای|لانگ")
_AR_SELL = re.compile(r"فروش|سل|شورت")


def _band(symbol: str | None) -> tuple[float, float]:
    return _BAND.get(symbol or "", _BAND_DEF)


def _in_band(v: float | None, symbol: str | None) -> bool:
    if v is None:
        return False
    lo, hi = _band(symbol)
    return lo <= float(v) <= hi


def _find_symbol(toks: list[str], raw: str) -> str | None:
    """Birinchi topilgan juftlik."""
    syms = _find_symbols(toks, raw)
    return syms[0] if syms else None


def _find_symbols(toks: list[str], raw: str) -> list[str]:
    """Juftliklarni topadi: aniq yozuv, xato yozuv (60ld, xauu5d), yoki arab yozuvi."""
    found: list[str] = []
    for tok in toks:
        if "%" in tok or tok.startswith("tp"):
            continue
        c = _canon_word(tok.strip("@#.:-"))
        if len(c) < 2 or c.isdigit():
            continue
        hit = None
        if c in _ALIAS_C:
            hit = _ALIAS_C[c]
        elif len(c) >= 4:
            for lg in (len(c) - 1, len(c), len(c) + 1):
                for cand, sym in _SYM_LEN.get(lg, ()):  # noqa: B007
                    if abs(cand[0] != c[0]):
                        continue
                    if difflib.SequenceMatcher(None, c, cand).ratio() >= 0.86:
                        hit = sym
                        break
                if hit:
                    break
        if hit and hit not in found:
            found.append(hit)
    # "xau usd", "gold usd" kabi ajratilgan yozuv
    ctext = " ".join(_canon_word(t) for t in toks)
    for k, v in (("xau usd", "XAUUSDT"), ("gold usd", "XAUUSDT"), ("usd jpy", "JPYUSDT")):
        if k in ctext and v not in found:
            found.append(v)
    if _AR_GOLD.search(raw) and "XAUUSDT" not in found:
        found.append("XAUUSDT")
    return found


# ---------------------------------------------------------------------------
# 3. YO'NALISH (BUY / SELL)
# ---------------------------------------------------------------------------

_GLYPH_BUY = ["\U0001F7E2", "\U0001F7E9", "\U0001F4C8", "\u2B06", "\U0001F53C", "\U0001F680",
              "\U0001F4B0", "\U0001F49A", "\u25B2", "\u25B4", "\u25B3", "\u2191", "\U0001F525"]
_GLYPH_SELL = ["\U0001F534", "\U0001F7E5", "\U0001F4C9", "\u2B07", "\U0001F53D", "\U0001F4A5",
               "\U0001F494", "\u25BC", "\u25BE", "\u25BD", "\u2193", "\u26AA", "\U0001F9CA"]

_BUY_STRONG = ["buy", "buying", "buys", "bay", "bai", "buyu", "buyzone", "buynow", "buylimit", "long", "longs",
               "longterm", "buyer", "sotibolish", "sotibolamiz", "sotiboldik", "xarid",
               "pokupka", "pokupaem", "pokupayu", "kupit", "kuplya", "kyupit",
               "\u043a\u0443\u043f\u0438\u0442\u044c"]
_SELL_STRONG = ["sell", "selling", "sells", "sel", "seil", "seyil", "sellzone", "sellnow", "selllimit", "short",
                "shorts", "shortterm", "seller", "sotish", "sotamiz", "sotmoq",
                "prodazha", "prodaem", "prodavat", "prodadim", "shortsell"]
_BUY_MED = ["bullish", "bull", "kotarilish", "kotariladi", "kotarilsa", "osadi", "osish",
            "osmoqda", "yuqoriga", "tepaga", "yukariga", "up", "call", "rost", "vverx",
            "verx", "green", "yashil", "yuqori", "sakraydi", "kuchayadi"]
_SELL_MED = ["bearish", "bear", "tushadi", "tushish", "tushushi", "tushsa", "pasayadi",
             "pasayish", "pastga", "past", "down", "put", "padenie", "padeniya", "vniz",
             "nij", "red", "qizil", "arzonlashadi"]
_NEG = {"emas", "yoq", "ne", "no", "not", "bez", "without", "cancel", "canceled", "bekor"}

# Ko'p so'zli iboralar (kanon matn ichidan qidiriladi)
_MW_BUY = ["sotib olish", "sotib olamiz", "sotib olishni", "sotib olsak", "sotib ol",
           "buy order", "buy limit", "long pozitsiya", "pokupka zolota", "na pokupku"]
_MW_SELL = ["sotib tashlash", "sotishni maslahat", "sell limit", "sell order",
            "short pozitsiya", "na prodazhu"]


def _mw_canon(phrases: list[str]) -> list[str]:
    return [" ".join(_canon_word(w) for w in p.split()) for p in phrases]


_MW_BUY_C = _mw_canon(_MW_BUY)
_MW_SELL_C = _mw_canon(_MW_SELL)

_STRONG_W = 3.0
_MED_W = 1.2
_GLYPH_W = 1.5
_FUZZY_K = 0.8


def _mk_index(words: list[str]) -> tuple[dict[str, float], dict[int, list[str]]]:
    exc: dict[str, float] = {}
    byl: dict[int, list[str]] = {}
    for w in words:
        c = _canon_word(w)
        if not c:
            continue
        exc.setdefault(c, 0.0)
        if len(c) >= 4:
            byl.setdefault(len(c), []).append(c)
    return exc, byl


_IDX = {
    "BUY_S": _mk_index(_BUY_STRONG), "SELL_S": _mk_index(_SELL_STRONG),
    "BUY_M": _mk_index(_BUY_MED), "SELL_M": _mk_index(_SELL_MED),
}


def _word_hit(tok_c: str, idx_key: str) -> tuple[float, bool]:
    """(vazn, aniqmi) — so'z kanon shakl bo'yicha lug'atga mos keladimi."""
    exc, byl = _IDX[idx_key]
    if tok_c in exc:
        return 1.0, True
    n = len(tok_c)
    if n < 4:
        return 0.0, False
    th = 0.80 if n >= 7 else 0.87
    best = 0.0
    for lg in (n - 1, n, n + 1):
        for cand in byl.get(lg, ()):
            if difflib.SequenceMatcher(None, tok_c, cand).ratio() >= th:
                best = 1.0
                break
        if best:
            break
    return best, False


def _direction(toks: list[str], raw: str) -> tuple[str, float, bool, str, float, float]:
    """(yo'nalish, ball, kuchli-cue, sabab, buy_ball, sell_ball)"""
    bu = se = 0.0
    strong = False
    seen_b = seen_s = False
    for i, tok in enumerate(toks):
        c = _canon_word(tok.strip("@#.:-"))
        if not c or c.isdigit() or len(c) < 3:
            continue
        neg = any(_canon_word(toks[j]) in _NEG for j in range(max(0, i - 2), i))
        for key in ("BUY_S", "SELL_S", "BUY_M", "SELL_M"):
            w, exact = _word_hit(c, key)
            if not w:
                continue
            wt = (_STRONG_W if key.endswith("_S") else _MED_W) * (1.0 if exact else _FUZZY_K)
            if neg:
                wt = 0.0
            if key.startswith("BUY"):
                bu += wt
                seen_b = True
                strong = strong or (exact and key == "BUY_S")
            else:
                se += wt
                seen_s = True
                strong = strong or (exact and key == "SELL_S")
    # emoji / belgilar
    gb = sum(1 for g in _GLYPH_BUY if g in raw)
    gs = sum(1 for g in _GLYPH_SELL if g in raw)
    if gb and not seen_b:
        bu += _GLYPH_W * min(gb, 3)
    if gs and not seen_s:
        se += _GLYPH_W * min(gs, 3)
    # ko'p so'zli iboralar ("sotib olish" = BUY)
    ctext = " ".join(_canon_word(t) for t in toks)
    if any(p in ctext for p in _MW_BUY_C):
        bu += _STRONG_W
        strong = True
    if any(p in ctext for p in _MW_SELL_C):
        se += _STRONG_W
        strong = True
    # arab yozuvi
    if _AR_BUY.search(raw):
        bu += _STRONG_W
        strong = True
    if _AR_SELL.search(raw):
        se += _STRONG_W
        strong = True

    if bu <= 0 and se <= 0:
        return "", 0.0, False, "yo'nalish ko'rinmadi", bu, se
    if bu > 0 and se > 0:
        if abs(bu - se) < 1.0:
            return "", max(bu, se), False, "ikki xil yo'nalish (tahlil/reklama)", bu, se
        if min(bu, se) >= 3.0:
            return "", max(bu, se), False, "ikki xil yo'nalish (tahlil/reklama)", bu, se
    if bu > se:
        return "BUY", bu - se, strong, "", bu, se
    if se > bu:
        return "SELL", se - bu, strong, "", bu, se
    return "", 0.0, False, "yo'nalish ko'rinmadi", bu, se


# ---------------------------------------------------------------------------
# 4. RAQAMLAR / LEVELS
# ---------------------------------------------------------------------------

_NUM_CHARS = r"0-9OoQqDdIiLlZzEeAaSsGgBbTt|!"


def _numval(tok: str) -> float | None:
    """'4415' / '44l5' / '441O' / '4 415' / '4415.50' -> float. Aks holda None."""
    s = str(tok or "").strip("@#+=:;")
    if not s or len(s) > 12:
        return None
    digits = sum(1 for ch in s if ch.isdigit())
    if digits < 2:
        return None
    mapped = "".join(_L2D.get(ch, ch) for ch in s)
    letters = sum(1 for ch in mapped if not ch.isdigit() and ch != ".")
    if letters > max(1, digits // 2):
        return None
    if not re.fullmatch(r"\d+(?:\.\d+)?", mapped):
        return None
    try:
        v = float(mapped)
    except ValueError:
        return None
    return v if v > 0 else None


def _range_pair(tok: str) -> tuple[float, float] | None:
    """'4415-4420', '4415/4420', '4415..4420' -> (4415, 4420)"""
    m = re.fullmatch(rf"([{_NUM_CHARS}]+)[-/]([{_NUM_CHARS}]+)", str(tok or ""))
    if not m:
        return None
    a, b = _numval(m.group(1)), _numval(m.group(2))
    if a is None or b is None:
        return None
    fa, fb = m.group(1), m.group(2)
    if "." not in fb and len(fb) < len(fa.split(".")[0]) and len(fb) <= 3:
        # 4339-29 -> 4329 ; 4290-96 -> 4296
        head = fa.split(".")[0]
        try:
            b2 = float(head[: max(0, len(head) - len(fb))] + fb)
            if b2 and abs(b2 - a) / max(a, 1e-9) <= 0.06:
                b = b2
        except ValueError:
            pass
    return (a, b) if a != b else None


def _expand_short(v: float, anchor: float | None) -> float | None:
    """'28' + anchor 4428 -> 4428. Faqat 1-2 xonali qisqa yozuvlar."""
    if anchor is None or v >= 100:
        return v
    base = int(anchor // 100) * 100
    cand = base + v
    if abs(cand - anchor) > 80:
        cand += 100 if cand < anchor else -100
    return cand if abs(cand - anchor) <= 200 else None


_UNIT_TOK = {"pip", "pips", "punkt", "punktlar", "foiz", "usd", "dollar", "dollars",
             "%", "pipslar", "pipp", "gram", "gr", "loot", "lot"}

_ENTRY_LBL = {"entry", "entries", "enter", "kirish", "kirishlar", "kir", "zona", "zone",
              "zonasi", "zonada", "zonega", "zonaldan", "diapazon", "range", "limit",
              "zones", "zonalari", "zonani", "zonalar", "zone",
              "buyzone", "sellzone", "order", "buylimit", "selllimit", "kirim", "idish",
              "vhod", "ot", "sichas", "hozir", "now", "at", "@", "narvon", "level", "uroven",
              "savdo", "trade", "tradezonasi", "0.5", "0.618", "50%"}
_SL_LBL = {"sl", "stop", "stoploss", "stops", "zarar", "stopga", "slga", "slzona",
           "stopu", "zashit", "stopk", "slash"}
_TP_LBL = {"tp", "tps", "target", "targets", "maqsad", "maqsadlar", "maqsadim", "nishon",
           "take", "takeprofit", "profit", "foyda", "cel", "teyk", "tpzona", "goal"}
_TP_IDX = re.compile(r"^tp[-_ ]?(\d)$")


def _label_of(tok: str) -> tuple[str, int]:
    """token -> ('entry'|'sl'|'tp'|'', tp_index)."""
    t = str(tok or "").strip("@#.:-*+()")
    if not t:
        return "@", 0
    if t in _ENTRY_LBL:
        return "entry", 0
    if t in _SL_LBL or re.fullmatch(r"s[/-]?l", t):
        return "sl", 0
    if t in _TP_LBL:
        return "tp", 0
    m = _TP_IDX.match(t)
    if m:
        return "tp", int(m.group(1))
    c = _canon_word(t)
    if len(c) >= 4:
        for w in ("target", "maqsad", "nishon", "stopp", "stop", "entry", "kirish", "zona"):
            if difflib.SequenceMatcher(None, c, _canon_word(w)).ratio() >= 0.85:
                if w in ("target", "maqsad", "nishon"):
                    return "tp", 0
                if w in ("stopp", "stop"):
                    return "sl", 0
                return "entry", 0
    return "", 0


_DATE_TOK = {"yil", "year", "sana", "kun", "vaqt", "daqiqa", "minut", "soat",
             "yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust",
             "sentabr", "sentabr", "oktabr", "noyabr", "dekabr", "января", "февраля"}


def _collect_levels(toks: list[str], anchor: float | None) -> dict:
    """Tokenlar oqimidan entry / sl / tp larni yig'adi."""
    out: dict = {"entry": None, "zone": None, "sl": None, "tps": [], "free": [], "nums": []}
    cur, cur_i, budget = "", 0, 0
    yearish = any(t in _DATE_TOK for t in toks)
    skip_next = False
    for i, tok in enumerate(toks):
        if skip_next:
            skip_next = False
            continue
        lab, tpi = _label_of(tok)
        if lab and lab != "@":
            cur = lab
            if lab == "tp" and tpi:
                cur_i = tpi
            elif lab == "tp":
                cur_i = cur_i + 1 if cur_i else 1
            else:
                cur_i = 0
            budget = 6
            continue
        if lab == "@":  # faqat "@" belgisi
            cur, cur_i, budget = "entry", 0, 4
            continue
        if tok.startswith("+") or (i + 1 < len(toks) and toks[i + 1] in _UNIT_TOK):
            budget = max(0, budget - 1)
            continue
        rng = _range_pair(tok)
        v = None if rng else _numval(tok)
        if (v is None and rng is None and cur and i + 1 < len(toks)
                and re.fullmatch(r"\d{1,2}", tok) and re.fullmatch(r"\d{3}", toks[i + 1])):
            v = float(tok + toks[i + 1])       # "entry 4 415" -> 4415
            skip_next = True
        if v is not None and cur == "" and yearish and 2010 <= v <= 2035:
            v = None                            # yil /sana raqami
        if v is None and rng is None:
            if tok in ("-", "/"):
                continue
            budget = max(0, budget - 1)
            if budget == 0 and cur not in ("entry",) and i + 1 < len(toks) and not _label_of(toks[i + 1])[0]:
                cur = ""
            continue
        vals = list(rng) if rng else [v]
        if rng:
            a, b = vals
            if b < 1000 <= a:
                b = _expand_short(b, anchor) or b
            elif a < 1000 <= b:
                a = _expand_short(a, anchor) or a
            vals = [a, b]
        vals = [x for x in vals if x]
        if not vals:
            cur = ""
            budget = 0
            continue
        if cur == "entry":
            if len(vals) == 2 or (out["zone"] is None and len(vals) == 2):
                lo, hi = min(vals), max(vals)
                out["zone"] = (lo, hi)
                out["entry"] = out["entry"] or (lo + hi) / 2.0
            else:
                out["entry"] = out["entry"] or vals[0]
        elif cur == "sl":
            out["sl"] = out["sl"] or vals[0]
        elif cur == "tp":
            for x in vals:
                if x not in out["tps"]:
                    out["tps"].append(x)
        else:
            out["free"].extend(vals)
        out["nums"].extend(vals)
        budget = max(0, budget - 1)
        if budget == 0:
            cur, cur_i = "", 0
    # Raqamli ro'yxat: "1) 4430  2) 4420"
    for m in re.finditer(rf"(?:^|\s)(\d)[\).:]\s*([{_NUM_CHARS}]{{2,}}(?:[.,]\d{{1,4}})?)", " ".join(toks)):
        v = _numval(m.group(2))
        if v and v not in out["tps"] and m.group(2) != (str(out["entry"] or "")):
            out["tps"].append(v)
    return out


def _fix_levels(levels: dict, symbol: str, ref: float | None) -> dict:
    """Qisqa yozuvlarni to'ldirish va diapazondan tashqarisini tashlash."""
    lo, hi = _band(symbol)
    anchor = ref
    for x in list(levels["nums"]):
        if anchor is None and x and 1000 <= x <= 9000:
            anchor = x
    def _ok(v):
        return v is not None and lo <= v <= hi

    def _repair(v):
        if v is None or _ok(v):
            return v
        s = str(int(v)) if float(v).is_integer() else str(v)
        for cut in (1, 2):
            if len(s) > 4:
                try:
                    v2 = float(s[:-cut])
                except ValueError:
                    break
                if _ok(v2):
                    return v2
        return None

    entry = _repair(levels["entry"])
    if entry is None and levels["entry"] is not None:
        entry = _expand_short(levels["entry"], anchor)
        entry = _repair(entry)
    zone = levels["zone"]
    if zone:
        a, b = _repair(zone[0]), _repair(zone[1])
        if a is None:
            a = _expand_short(zone[0], anchor)
        if b is None:
            b = _expand_short(zone[1], anchor)
        if a and b and (lo <= a <= hi) and (lo <= b <= hi) and abs(a - b) / max(a, b) <= 0.03:
            zone = (min(a, b), max(a, b))
            entry = entry or (zone[0] + zone[1]) / 2.0
        else:
            zone = None
    sl = _repair(levels["sl"])
    tps = []
    for t in levels["tps"]:
        t2 = _repair(t)
        if t2 is None and t is not None:
            t2 = _expand_short(t, anchor)
            t2 = _repair(t2)
        if t2 and t2 not in tps:
            tps.append(t2)
    free = []
    for v in levels["free"]:
        x = _repair(v)
        if x is None:
            x = _repair(_expand_short(v, anchor))
        if x and x not in free:
            free.append(x)
    return {"entry": entry, "zone": zone, "sl": sl, "tps": tps, "free": free}


# ---------------------------------------------------------------------------
# 5. VETO (natija / reklama / salom / yopish)
# ---------------------------------------------------------------------------

# 1-daraja: o'tgan zamondagi natija/hisobot — reja bo'lsa ham veto
_V_HIT = re.compile(
    r"(tp\s*\d?\s*(hit|bo[`']?ldi|bajarildi|oldik|ok|done)|sl\s*\d?\s*(hit|bo[`']?ldi|bajarildi)|"
    r"\bhit\b\s*(✅|☑|✔)|natija(lar)?|result(s)?\b|recap|statistika|statistics|hisobot|"
    r"closed?\s*(in|at)\s*(profit|loss)|foyda\s*oldik|zarar\s*bo[`']?ldi|"
    r"take\s*profit\s*(hit|done)|target\s*(reached|hit)|bajarildi|olds?\s*✅|"
    r"successfully|running\s*profit|all\s*tp\s*done|enjoy\s*\d|\btp\s*\d?\s*(oldi|oldik|done)\b|"
    r"target\s*\d?\s*complete|\bcomplete(d)?\b|\b1/1\b|"
    r"\bnafsizga\b|\bfoyda\b|\braketa\b|\bshedevr\b|"
    r"signal\s*yopildi|yopildi|итог|результат|профит\s*\+)", re.I)
# 2-daraja: pip/foyda hisobi — reja (entry+SL) bo'lsa signal bo'lishi mumkin
_V_RESULT = re.compile(
    r"(\+\s*\d{2,4}\s*(pip|pips|punkt|%)|"
    r"\b(sumka|balans|depozit|withdraw|касса|kassa)\b)", re.I)

_V_CLOSE = re.compile(
    r"(yopamiz|yopdim|yopildi|yopish|yopiq|close\s*all|closing|closing\s*now|closed|"
    r"nakamiz|zakryvaem|zakryt|закрыва|крышка|end\s*of\s*trade|kapat)", re.I)

_V_AD = re.compile(
    r"(obuna|subscribe|vip\s*(kanal|signal|guruh)|kanalimizga|kanalga\s*qo[`']?shil|qo[`']?shiling|"
    r"join\s*(now|us|vip|channel)|t\.me/|@\w+kanal|link\s*bio|reklama|reklama\s*uchun|chegirma|"
    r"to[`']?lov|payme|click\s*up|karta\s*\d|podpiska|подпис|реклам|оплата|"
    r"kurs|dars|lesson|mentor|signallar\s*kanali|bepul\s*kurs|king\s*trader|"
    r"promokod|murojat|murojaat|bonus|ro\s*yxatdan\s*ot|registratsiya)", re.I)

_V_GREET = re.compile(
    r"(assalomu\s*alaykum|salom\s*(do[`']?stlar|traders|hammaga)?|xayrli\s*(tong|kun|kech)|hayrli|"
    r"good\s*(morning|evening|night|afternoon)|hello|hi\s+(all|traders)|hey\s*traders|"
    r"привет|доброе\s*утро|добрый\s*(день|вечер)|доброй\s*ночи)", re.I)

_V_ANALYSIS = re.compile(
    r"(tahlil|analiz|analysis|technical\s*analysis|fundamental|prognoz\s*uchun|sabab(lari)?|"
    r"yangilik|news|kalendar|calendar|nonfarm|nfp|fomc|cpi\s*chiqadi|"
    r"кak\s*torg|dars|o[`']?qitish|bilmaganlar\s*uchun|maqola|statya)", re.I)

_SOFT_COMMENT = re.compile(
    r"\b(boladi|kere|kerak|qilsak|qziqsak|qzsak|fokus|fokusda|oqad|oqadi|oqib|oqdi|"
    r"boshladik|boslaymiz|boshlimiz|kotamiz|kutamiz|kuzatamiz)\b", re.I)

_AKTIV_RE = re.compile(r"\b(aktiv|active|faol|kuchda|aktivda)\b", re.I)
_IDEA_RE = re.compile(r"\b(idea|tahlil|signal|setup|proyekt|fikr)\b", re.I)
_DIR_WORD_RE = re.compile(r"\b(buy|sell|sel|long|short)\b", re.I)
_NOW_RE = re.compile(r"\b(now|hozir|hozirda|bozordan|market)\b", re.I)

_V_WARN = re.compile(
    r"\b(fake|feyk|aldan|aldanib|zagon|pul\s*ko\s*paytir|kopaytirib\s*ber|"
    r"ishonib\s*qolmang|tarqating)\b", re.I)

_EDU_RULE = re.compile(
    r"(sl\s*ga\s*tegsa|sl\s*tegsa|bekor\s*bo[`']?ladi|kutamiz|kutib\s*turamiz|kuzatamiz|"
    r"kuzatish|kutish|борьба|risk\s*1|"
    r"lot\s*\d|depozitni|90\s*%|95\s*%|100\s*%|ishonchli\s*signal|kafolat)", re.I)


# --- v62: natija / otziv / bekor qilingan xabarlar (asosiy yolg'on signal manbai) ---
_PIPS_WORD = re.compile(r"\b(pips?|punkt|point)\b", re.I)
_PLAN_CUE62 = re.compile(
    r"(buy|sell|long|short|entry|kirish|zona|zone|\bsl\b|\bstop|stoploss|tp\s*\d|"
    r"target|take\s*profit|limit\s*order|order)", re.I)
_PRICE_LIKE = re.compile(r"(\b\d{3,5}[.,]\d{2}\b|\b\d{4}\b)")
_AKTIVMAS = re.compile(r"(aktivmas|aktiv\s*emas|faol\s*emas|otmena|отмена|не\s*активно)", re.I)
_TICK_RESULT = re.compile(
    r"(\u2705\s*\u2705|pips?\s*\u2705|profit\s*\u2705|oldi\s*\u2705|oldik\s*\u2705|"
    r"pips?\s*\U0001f680|pips?\s*\U0001f525)", re.I)
_OZIV_MARK = re.compile(
    r"(zo[`']?r\s*signal|signal\s*zo[`']?r|rahmat|tashakkur|barakalla|shogird|"
    r"o[`']?quvchi|yordi\b|foyda\s*oldim|katta\s*rahmat|minnatdor|maqtov|"
    r"alhamdullilah|alhamdulillah)", re.I)
_PAST_CLAIM = re.compile(r"(berdim|aytdim|aytgan\s*edim|bergan\s*edim|yozdim|dedim)", re.I)
_LOSS_REPORT = re.compile(r"(?<![\w])(?:-\s*\d{1,4}\s*(?:pip|pips|punkt|point))(?![\w])", re.I)


def _struck_share(t: str) -> float:
    """Matnning qancha qismi ~~chizilgan~~ — bekor qilingan xabar belgisi."""
    t = t or ""
    if "~~" not in t:
        return 0.0
    n = sum(len(m.group(0)) for m in re.finditer(r"~~.+?~~", t, re.S))
    return n / max(1, len(t))


def _result_veto(text: str, has_plan: bool) -> str:
    """v62: '50 pips🚀', 'aktivmas', chizilgan xabar, obunachi otzivi — SIGNAL EMAS."""
    s = text or ""
    if _AKTIVMAS.search(s):
        return "bekor qilingan xabar (aktivmas)"
    if _struck_share(s) >= 0.45:
        return "chizilgan (bekor qilingan) xabar"
    price_like = bool(_PRICE_LIKE.search(s))
    plan = bool(_PLAN_CUE62.search(s))
    if _PIPS_WORD.search(s) and not plan and not price_like:
        return "natija xabari (pips hisoboti)"
    for m in _LOSS_REPORT.finditer(s):
        pre = s[max(0, m.start() - 16):m.start()]
        if not _PLAN_CUE62.search(pre):
            return "natija xabari (zarar hisoboti)"
    if _TICK_RESULT.search(s) and not price_like:
        return "natija xabari (natija belgisi)"
    if _OZIV_MARK.search(s) and not has_plan and not price_like:
        return "obunachi izohi/otziv"
    if _PAST_CLAIM.search(s) and not has_plan and not price_like:
        return "eski signalga ishora (yangi signal emas)"
    return ""


# --- v70: terminal (MT5) skrinshoti — natija/history rasmi, SIGNAL EMAS ---
_SCREEN_MONEY = re.compile(r"[+-]\s*\d+(?:[.,]\d+)?\s*(?:USD|usd|\$)", re.I)
_SCREEN_USD = re.compile(r"\b\d+(?:[.,]\d{1,2})?\s*USD\b", re.I)
_SCREEN_PL = re.compile(
    r"\b(?:P\s*/?\s*L|profit|profitability|loss|foyda|zarar|equity|floating)\b"
    r"\s*[:=\-]?\s*[+-]?\d", re.I)
_SCREEN_TABS = re.compile(
    r"(?:free\s*margin|margin\s*level|equity|balance\s*[:=]|balans\s*[:=]|"
    r"history\b.{0,60}\b(?:trade|settings|quotes)|quotes\s+chart\s+trade)", re.I | re.S)
# "SELL 4350.5" — reja darajasi bilan yozilgan (HAQIQIY narx), "SELL 0.11" emas
_SCREEN_LEVEL = re.compile(
    r"\b(?:sl|stop|stoploss|tp|target|entry|kirish|buy|sell|long|short|order)\b"
    r"\s*[:=\-]?\s*\d{3,5}(?:[.,]\d{1,3})?", re.I)
_SCREEN_PIPS = re.compile(r"[+-]?\s*\d{1,4}\s*(?:pip|pips|punkt)\b", re.I)


def _screen_veto(ocr: str, cap: str = "") -> str:
    """v70: MT5/terminal skrinshoti — ochiq bitim yoki history rasmi.

    Bunday rasmda «SELL 0.11 +48.69 USD», «P/L», «Equity», hajm va pul turadi;
    aniq reja (SL/TP yonida HAQIQIY 3-5 xonali narx) bo'lmasa — bu signal emas.
    """
    s = ocr or ""
    if not s.strip():
        return ""
    has_money = bool(_SCREEN_MONEY.search(s)) or bool(_SCREEN_USD.search(s))
    has_level = bool(_SCREEN_LEVEL.search(s))
    if has_level and not has_money:
        return ""          # haqiqiy signal kartasi (daraja bilan yozilgan)
    if _SCREEN_MONEY.search(s):
        return "terminal skrinshoti (P/L pul qiymati)"
    if _SCREEN_PL.search(s):
        return "terminal skrinshoti (foyda/zarar qatori)"
    if _SCREEN_PIPS.search(s) and not has_level:
        return "natija skrinshoti (pips hisoboti)"
    if _SCREEN_TABS.search(s) and has_money:
        return "terminal skrinshoti (hisob qatori)"
    return ""


def _veto(text: str, raw: str, has_plan: bool, strong_dir: bool) -> str:
    """Sabab qaytarsa — bu signal EMAS (qat'iy).

    has_plan = entry/zona/SL bor (haqiqiy savdo rejasi).
    Kuchli "natija" belgilari reja bo'lmasa har doim veto qiladi.
    """
    t = text or ""
    # v62: matn `_pre()` bilan tozalanganda ~~ va emoji yo'qoladi — xom matnni ham tekshiramiz
    _v62 = _result_veto(t, has_plan) or _result_veto(raw or "", has_plan)
    if _v62:
        return _v62
    if _V_WARN.search(t):
        return "firibgarlik ogohlantirishi/reklama"
    if _SOFT_COMMENT.search(t) and not has_plan:
        return "izoh/tahlil posti"
    if _V_HIT.search(t):
        return "natija/hisobot posti"
    if _V_RESULT.search(t) and not (has_plan and strong_dir):
        return "natija/hisobot posti"
    if _EDU_RULE.search(t) and not has_plan:
        return "qoidalar/ta'lim posti"
    if _V_CLOSE.search(t) and not has_plan:
        return "yopish xabari"
    if _V_AD.search(t) and not (has_plan and strong_dir):
        return "reklama/obuna posti"
    if _V_ANALYSIS.search(t) and not strong_dir and not has_plan:
        return "tahlil/yangilik posti"
    if _V_GREET.search(t) and not has_plan and not _num_count(t):
        return "salomlashish posti"
    return ""


def _num_count(t: str) -> int:
    return len(re.findall(r"\d{2,}", t or ""))


# ---------------------------------------------------------------------------
# 6. TIME FRAME
# ---------------------------------------------------------------------------

_TF_TOKEN = {
    "m1": "1m", "1m": "1m", "m5": "5m", "5m": "5m", "m15": "15m", "15m": "15m",
    "m30": "30m", "30m": "30m", "h1": "1h", "1h": "1h", "h4": "4h", "4h": "4h",
    "d1": "1d", "1d": "1d", "w1": "1d",
}


def _timeframe(toks: list[str], raw: str) -> tuple[str, bool]:
    for tok in toks[:8]:
        t = str(tok).strip(".:-")
        if t in _TF_TOKEN:
            return _TF_TOKEN[t], True
    m = re.search(r"\b(\d{1,2})\s*(m|min|minut|soat|h|hour|hours)\b", raw or "", re.I)
    if m:
        n, u = int(m.group(1)), m.group(2).lower()
        if u in ("h", "soat", "hour", "hours"):
            return ("1h" if n == 1 else "4h" if n == 4 else "1h"), True
        if n in (1, 5, 15, 30):
            return f"{n}m", True
    return "1m", False


# ---------------------------------------------------------------------------
# 7. TAKROR (dedupe)
# ---------------------------------------------------------------------------

_SEEN: dict[tuple, tuple[float, str]] = {}

# Kontekst: oxirgi muvaffaqiyatli signaldagi juftlik va narx (qisqa yozuvlarni to'ldirish uchun)
_CTX: dict = {"sym": "", "px": 0.0, "ts": 0.0}
_CTX_TTL = 7200.0  # 2 soat


def _ctx(now: float | None = None) -> tuple[str, float | None]:
    now = now or time.time()
    if not _CTX["sym"] or now - _CTX["ts"] > _CTX_TTL:
        return "", None
    return _CTX["sym"], (_CTX["px"] or None)


def _ctx_set(symbol: str, px: float | None) -> None:
    _CTX["sym"] = symbol or ""
    _CTX["px"] = float(px or 0.0)
    _CTX["ts"] = time.time()


def _is_dup(symbol: str, direction: str, text: str, now: float) -> bool:
    key = (symbol, direction)
    prev = _SEEN.get(key)
    _SEEN[key] = (now, text)
    if len(_SEEN) > 200:
        for k in list(_SEEN)[:100]:
            _SEEN.pop(k, None)
    if not prev:
        return False
    ts, old = prev
    if now - ts > 1800:
        return False
    if old and text and difflib.SequenceMatcher(None, old[:400], text[:400]).ratio() >= 0.88:
        return True
    return False


# ---------------------------------------------------------------------------
# 8. ASOSIY
# ---------------------------------------------------------------------------

def analyze_ex(text: str | None, ocr: str = "", has_image: bool = False,
               ref: float | None = None) -> tuple[ParsedSignal | None, str, bool]:
    cap = (text or "").strip()
    ocra = (ocr or "").strip()
    if not cap and not ocra:
        if has_image:
            return None, "rasmda yozuv o'qilmadi", False
        return None, "bo'sh xabar", False
    raw = "\n".join(p for p in (cap, ocra) if p)
    # v62: natija/otziv/bekor xabarlari — juftlik va kontekstdan qat'i nazar SIGNAL EMAS
    _early = _result_veto(raw, False) or _result_veto(cap, False)
    if not _early:
        # v70: OCR — MT5 terminal skrinshoti (ochiq bitim / history / P/L)
        _early = _screen_veto(ocra, cap)
    if _early:
        return None, _early, True
    body = _pre(raw)
    toks = [t for t in body.split() if t]
    if not toks:
        return None, "matn bo'sh", False

    hint_sym, hint_px = _ctx()
    if ref is None and hint_px:
        ref = hint_px
    levels_raw = _collect_levels(toks, ref)
    syms = _find_symbols(toks, raw)
    symbol = syms[0] if syms else None
    direction, score, strong, why, bu_s, se_s = _direction(toks, raw)
    if len(syms) >= 2 and bu_s > 0 and se_s > 0:
        return None, "bir nechta aktiv + qarama-qarshi yo'nalish", True

    # juftlik yo'q bo'lsa — raqamlar diapazonidan aniqlash (oltin asosiy aktiv)
    if symbol is None:
        for v in levels_raw["nums"]:
            if v and _GOLDISH[0] <= v <= _GOLDISH[1]:
                symbol = "XAUUSDT"
                break
    if symbol is None and has_image and (direction or levels_raw["entry"] or levels_raw["free"]):
        symbol = "XAUUSDT"
    if (symbol is None and ref and direction
            and (levels_raw["free"] or levels_raw["entry"] or levels_raw["sl"])):
        # narx ankeri bo'yicha aktiv (masalan, 4360 -> oltin)
        if _GOLDISH[0] <= float(ref) <= _GOLDISH[1]:
            symbol = "XAUUSDT"
    if (symbol is None and direction and hint_sym
            and (levels_raw["free"] or levels_raw["entry"] or levels_raw["sl"])):
        # kanalning oxirgi juftligi (qisqa yozuvlar: "57-61 buy otkat")
        symbol = hint_sym
    if (symbol is None and direction and _DIR_WORD_RE.search(body)
            and (_AKTIV_RE.search(body) or _NOW_RE.search(body))):
        # "Faqat SEL AKTIV", "buy now" — juftlik yozilmagan, oltin kanallari
        symbol = "XAUUSDT"
    if symbol is None:
        return None, "juftlik/aktiv ko'rinmadi", False

    lv = _fix_levels(levels_raw, symbol, ref)
    entry, zone, sl, tps = lv["entry"], lv["zone"], lv["sl"], lv["tps"]

    # yo'nalishsiz raqamlar: entry bo'sh bo'lsa birinchi mantiqiy raqam
    if entry is None and lv["free"]:
        used = {x for x in ([sl] if sl else []) + tps}
        cand = [x for x in lv["free"] if x not in used]
        if cand:
            if len(cand) >= 2 and abs(cand[0] - cand[1]) / max(cand[0], cand[1]) <= 0.015:
                zone = zone or (min(cand[0], cand[1]), max(cand[0], cand[1]))
                entry = (cand[0] + cand[1]) / 2.0
            else:
                entry = cand[0]

    # yo'nalishni geometriyadan aniqlash
    geom = ""
    if not direction:
        base = entry or (sum(tps) / len(tps) if tps else None)
        if sl and base:
            if sl < base and tps and max(tps) > base:
                geom = "BUY"
            elif sl > base and tps and min(tps) < base:
                geom = "SELL"
            elif sl < base and not tps:
                geom = "BUY"
            elif sl > base and not tps:
                geom = "SELL"
        if not geom:
            direction, score, strong = "", 0.0, False
            why = why or "yo'nalish yo'q"

    veto = _veto(body, raw, bool(entry or zone or sl), bool(direction or geom))
    if veto:
        return None, veto, True

    direction = direction or geom
    has_levels = bool(entry or zone or sl or tps)

    if not direction:
        if _V_GREET.search(raw) or _V_AD.search(raw):
            return None, "signal emas (salom/reklama)", True
        return None, why or "yo'nalish aniqlanmadi", False

    # ishonch: kuchli cue, yoki level bilan medium cue, yoki bir necha kuchsiz cue
    ok = bool(strong) or (score >= 2.0 and has_levels) or score >= 4.0
    _exempt = bool(_IDEA_RE.search(body)) or (
        bool(_DIR_WORD_RE.search(body)) and (_AKTIV_RE.search(body) or _NOW_RE.search(body)))
    if ok and not has_levels and not has_image and not _exempt:
        # "BUY ZONES", "Men bir buy berme ekanda" kabi shovqin — darajasiz signal emas
        return None, "yo'nalish bor, daraja/now yo'q (izoh)", False
    if not ok and score >= 1.5 and entry and (sl or tps):
        ok = True
    if not ok and has_image and has_levels and len(body) <= 80:
        ok = True
    if not ok and direction and score >= 1.0 and not has_levels and len(body) <= 40:
        ok = True
    if not ok:
        return None, f"ishonch past (ball={score:.1f})", False

    # SL/TP mantiqiy joylashuvi (noto'g'ri bo'lsa tashlaymiz)
    if entry and sl:
        if direction == "BUY" and sl > entry:
            if tps and max(tps) < entry:
                direction = "SELL"
            else:
                sl = None
        elif direction == "SELL" and sl < entry:
            if tps and min(tps) > entry:
                direction = "BUY"
            else:
                sl = None
    if entry and tps:
        good = [t for t in tps if (t > entry if direction == "BUY" else t < entry)]
        if good:
            tps = good
        elif len(tps) >= 2:
            tps = []
    if not entry and zone:
        entry = (zone[0] + zone[1]) / 2.0

    tf, tf_ex = _timeframe(toks, raw)
    now = time.time()
    if _is_dup(symbol, direction, body, now):
        return None, "takror signal (oxirgi bilan bir xil)", True

    sig = ParsedSignal(
        direction=direction, symbol=symbol, timeframe=tf,
        entry=entry, sl=sl, tp=(tps[0] if tps else None), tps=list(tps),
        raw=raw[:800], tf_explicit=tf_ex,
        zone_low=(zone[0] if zone else None), zone_high=(zone[1] if zone else None),
    )
    try:
        _ctx_set(symbol, entry or (sum(tps) / len(tps) if tps else None)
                 or (zone[0] if zone else None) or sl)
    except Exception:  # noqa: BLE001
        pass
    reason = (f"SIGNAL {direction} {symbol} ball={score:.1f} entry={entry} sl={sl} "
              f"tp={tps[:4]} zona={zone}")
    logger.info("[LAI] %s | %s", reason, body[:90])
    return sig, reason, False


def analyze(text: str | None, ocr: str = "", has_image: bool = False,
            ref: float | None = None) -> ParsedSignal | None:
    """Qulay o'ram: faqat signal yoki None."""
    try:
        sig, why, veto = analyze_ex(text, ocr=ocr, has_image=has_image, ref=ref)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[LAI] xato: %s", exc)
        return None
    if sig is None and (veto or why):
        logger.debug("[LAI] EMAS (%s)", why)
    return sig


# ---------------------------------------------------------------------------
# 9. O'ZINI SINASH
# ---------------------------------------------------------------------------

_DEMO = [
    ("xauusd h1 idea buy asosiy entry 4419-4411", "BUY", "XAUUSDT"),
    ("GOLD SELL 4415-4420 SL 4425 TP 4400 4390", "SELL", "XAUUSDT"),
    ("\U0001F7E2 XAUUSD BUY NOW @4410 SL 4400 TP 4425", "BUY", "XAUUSDT"),
    ("\u0417\u043e\u043b\u043e\u0442\u043e \u043f\u043e\u043a\u0443\u043f\u043a\u0430 4400-4405 \u0441\u0442\u043e\u043f 4390 \u0446\u0435\u043b\u0438 4420 4430", "BUY", "XAUUSDT"),
    ("XAUU5D 8UY 441O 5L 44OO TP 4425", "BUY", "XAUUSDT"),
    ("sotib olish xauusd 4400 zona sl 4390 tp 4425", "BUY", "XAUUSDT"),
    ("TP HIT \u2705 XAUUSD +40 pip", None, None),
    ("VIP kanalga qo'shiling, obuna 50$", None, None),
    ("Assalomu alaykum traders, xayrli tong!", None, None),
]


def _self_test() -> None:
    bad = 0
    for text, want_d, want_s in _DEMO:
        _SEEN.clear()
        s, why, veto = analyze_ex(text, has_image=False)
        got_d = s.direction if s else None
        got_s = s.symbol if s else None
        ok = (got_d == want_d) and (got_s == want_s) if want_d else s is None
        bad += 0 if ok else 1
        print(("OK  " if ok else "XATO"), repr(text[:45]), "->", got_d, got_s, "|", why)
    print("Xato:", bad, "/", len(_DEMO))


if __name__ == "__main__":  # pragma: no cover
    _self_test()
