"""Har xil kanal formatini o'qish: matn, OCR, TP1–TP5, zona, emoji.

Ikki aniq qarama-qarshi yo'nalish (reklama) tashlanadi.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.symbols import fit_symbol, resolve_symbol

BUY_WORDS = re.compile(
    r"(?:\b(?:buy|long|bull(?:ish)?|alish|sotib|покуп|лонг|купит|call|almoq|"
    r"olamiz|longga|tepaga|ko'?taril|kotariladi|o'sadi|oshadi)\w*"
    r"|#buy|🟢|📈|⬆️|🔼|🟩|✅|🚀|💙|▲|△|▴"
    r"|خرید|بخر|بخری|صعودی|صعود|لانگ|شراء|شرا|اشتري)",
    re.IGNORECASE,
)
SELL_WORDS = re.compile(
    r"(?:\b(?:sell|short|bear(?:ish)?|sotish|продаж|шорт|прода|put|sotmoq|"
    r"sotamiz|sotyapmiz|sotdik|sotmoqda|sotilmoqda|sotuv|shortga|pastga|tushadi|tushishi)\w*"
    r"|#sell|🔴|📉|⬇️|🔽|🟥|🔻|💥|💔|▼|▽|▾"
    r"|فروش|بفروش|نزولی|نزول|شورت|هبوط|بيع)",
    re.IGNORECASE,
)

# "idea buy", "korreksiya", "oqib kelishi kerak"
_IDEA_RE = re.compile(
    r"korreksiya|korrektsiya|correction|retrace|retracement|retest|"
    r"oqib|kelishi|kutiladi|kutamiz|kutaver|idea|setup|asosiy|"
    r"looking|wait\s*for|target|maqsad|borishi|yetishi|yetadi|"
    r"boradi|yetib|keladi",
    re.I,
)
_TOWARD_RE = re.compile(
    r"oqib|kelishi|boradi|yetadi|yetishi|borishi|yetib|keladi|"
    r"target|maqsad|borishi\s*kerak",
    re.I,
)

TF_PAT = re.compile(
    r"\b(?:tf[:\s]*)?(m1|1m|m5|5m|5min|m15|15m|m30|30m|h1|1h|60m|h4|4h|d1|1d|daily|w1|1w)\b",
    re.IGNORECASE,
)
TF_MAP = {
    "m1": "1m", "1m": "1m",
    "m5": "5m", "5m": "5m", "5min": "5m",
    "m15": "15m", "15m": "15m",
    "m30": "30m", "30m": "30m",
    "h1": "1h", "1h": "1h", "60m": "1h",
    "h4": "4h", "4h": "4h",
    "d1": "1d", "1d": "1d", "daily": "1d",
    "w1": "1d", "1w": "1d",
}

NUM = r"([0-9]{1,8}(?:[.,][0-9]{1,6})?)"
ENTRY_PAT = re.compile(
    rf"\b(?:entry|kirish|price|narx|open|вход|enter|buy\s*at|sell\s*at|@)\s*[:=]?\s*{NUM}",
    re.I,
)
ENTRY_ZONE = re.compile(
    rf"\b(?:limit|lim|entry|kirish|zona|zone|@)\s*[:=]?\s*{NUM}\s*[-–/]\s*{NUM}",
    re.I,
)
# "4290-96" / "1.0850-60" — qisqa zona
BARE_ZONE = re.compile(rf"(?<![A-Za-z]){NUM}\s*[-–/]\s*{NUM}")
# "4309 43011" / "zona 4309 4311" — bo'shliq bilan zona (admin xatosi ham)
SPACE_ZONE = re.compile(rf"(?<![A-Za-z0-9.]){NUM}\s+{NUM}(?!\d)")
SL_PAT = re.compile(
    rf"\b(?:sl|s/l|stop(?:\s*-?\s*loss)?|stoploss|стоп|sloss|"
    rf"حد\s*ضرر|حدضرر|استاپ|ستاپ|وقف\s*الخسار)[ \t]*[:=]?[ \t]*{NUM}",
    re.I,
)
# "4011 STOP" / "4319 STOP !!" — raqam OLDIN
SL_NUM_FIRST = re.compile(
    rf"(?<![A-Za-z0-9.]){NUM}[ \t]*[^\w\n]{{0,8}}[ \t]*"
    rf"(?:stop(?:\s*-?loss)?|stoploss|s/l|sloss|стоп|"
    rf"حد\s*ضرر|حدضرر|استاپ|ستاپ|وقف\s*الخسار)\b",
    re.I,
)
# "4009 SELL"  /  "4316 - 4318 SELL"
PRICE_THEN_DIR = re.compile(
    rf"(?:(?<![\w.])(?P<a>{NUM})\s*[-–/]\s*(?P<b>{NUM})|(?<![\w.])(?P<c>{NUM}))\s+"
    rf"(?P<d>buy+|sell+|long|short)\b",
    re.I,
)
# "Tp 1/2 -1/3" — R ulushi, narx EMAS
_R_TP_LINE = re.compile(
    r"\btp[s]?\s*[:\-]?\s*[1-5](?:\s*[\/:]\s*[1-5]){1,4}"
    r"(?:\s*-\s*-?[1-5](?:\s*[\/:]\s*[1-5]){0,4})?",
    re.I,
)
TP_PAT = re.compile(
    rf"\b(?:tp\s*1?|t/p|target|take\s*profit|maqsad|тейк|"
    rf"هدف|تارگت|سود)\s*[:=]?\s*{NUM}",
    re.I,
)
TPN_PAT = re.compile(
    rf"\b(?:tp|target|t)[\s\-]*([1-5])(?!\d)\s*[:=\-]?\s*{NUM}",
    re.I,
)
TPS_LINE = re.compile(
    rf"\b(?:tps?|targets?|maqsadlar?|тейки)\s*[:=]?\s*"
    rf"{NUM}(?:\s*[/|,;–-]+\s*{NUM}){{1,4}}",
    re.I,
)

PAIR_DIR = re.compile(
    r"(?:#)?\b(buy+|sell+|long|short|call|put)\b\s*[#@]?\s*"
    r"([A-Za-z]{2,16}(?:/?USD[T]?)?)",
    re.I,
)
DIR_AFTER = re.compile(
    r"\b([A-Za-z]{2,16}(?:/?USD[T]?)?)\s*[#]?\s*(buy+|sell+|long|short|call|put)\b",
    re.I,
)
GLUED = re.compile(
    r"\b(xauusd|xau/usd|gold|xagusd|silver|btc|bitcoin|eth|eurusd|gbpusd|"
    r"usdjpy|sol|oil|wti|brent)\s*"
    r"(buy+|sell+|long|short)(?![a-z])",
    re.I,
)
HASH_PAIR = re.compile(r"#([A-Za-z]{3,16})")

_SKIP_TOK = {
    "buy", "sell", "long", "short", "now", "entry", "stop", "take",
    "profit", "signal", "free", "vip", "the", "and", "for", "from",
    "call", "put", "strong", "scalp", "swing", "intraday", "update",
    "tp", "sl", "open", "close", "price", "pair", "trade", "setup",
    "limit", "lim", "zone", "zona", "sniper", "forex", "crypto", "fx",
    "analysis", "chart", "alert", "news", "premium", "daily", "weekly",
    "idea", "scalping", "intraday", "breakout", "bos", "choch", "fvg",
    "order", "block", "liquidity", "premium", "discount", "otc",
}


@dataclass
class ParsedSignal:
    direction: str
    symbol: str
    timeframe: str
    entry: float | None = None
    sl: float | None = None
    tp: float | None = None
    tps: list[float] = field(default_factory=list)
    raw: str = ""
    tf_explicit: bool = False
    zone_low: float | None = None
    zone_high: float | None = None


def _to_float(s: str | None) -> float | None:
    if not s:
        return None
    try:
        t = str(s).replace(" ", "").replace(",", "")
        return float(t)
    except (TypeError, ValueError):
        return None


def _expand_abbr(a_s: str, b_s: str) -> tuple[float | None, float | None]:
    """4290-96 → (4290, 4296); 1.0850-60 → (1.0850, 1.0860)."""
    a_s = (a_s or "").replace(" ", "").replace(",", "")
    b_s = (b_s or "").replace(" ", "").replace(",", "")
    a, b = _to_float(a_s), _to_float(b_s)
    if a is None or b is None:
        return a, b
    whole = a_s.split(".")[0]
    if "." not in b_s and 0 < len(b_s) < len(whole):
        try:
            b2 = float(whole[:-len(b_s)] + b_s)
            if abs(b2 - a) / max(abs(a), 1e-9) <= 0.08:
                b = b2
        except ValueError:
            pass
    if "." in a_s and "." not in b_s:
        w, frac = a_s.split(".", 1)
        if 0 < len(b_s) <= len(frac):
            try:
                b2 = float(w + "." + frac[:-len(b_s)] + b_s)
                if abs(b2 - a) / max(abs(a), 1e-9) <= 0.08:
                    b = b2
            except ValueError:
                pass
    return a, b


def _repair_zone_pair(a: float, b: float) -> tuple[float, float] | None:
    """4309 va 43011 (xato) → 4309–4311. Yil emas."""
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return None
    if a <= 0 or b <= 0:
        return None
    lo, hi = (a, b) if a <= b else (b, a)
    if 2020 <= lo <= 2035 and 2020 <= hi <= 2035:
        return None
    span = (hi - lo) / max(hi, 1e-9)
    if span <= 0.08 or (hi < 1200 and (hi - lo) <= 40):
        return lo, hi
    sa, sb = str(int(round(a))), str(int(round(b)))
    longer, shorter = (sa, sb) if len(sa) >= len(sb) else (sb, sa)
    other = float(shorter)
    best = None
    for i in range(len(longer)):
        s = longer[:i] + longer[i + 1:]
        if len(s) < 3:
            continue
        try:
            cand = float(s)
        except ValueError:
            continue
        if cand <= 0:
            continue
        d = abs(cand - other) / max(abs(other), 1.0)
        if d <= 0.08:
            dist = abs(cand - other)
            if best is None or dist < best[0]:
                best = (dist, cand, other)
    if best:
        x, y = best[1], best[2]
        return (x, y) if x <= y else (y, x)
    for div in (10.0, 100.0):
        cand = hi / div
        if abs(cand - lo) / max(abs(lo), 1.0) <= 0.08:
            x, y = cand, lo
            return (x, y) if x <= y else (y, x)
    return None


def _zone_bounds(raw: str) -> tuple[float | None, float | None, float | None]:
    """(past, yuqori, o'rta). 4339-29 → (4329, 4339, 4334). 4309 43011 → 4309–4311."""
    zm = ENTRY_ZONE.search(raw)
    if zm:
        a, b = _expand_abbr(zm.group(1), zm.group(2))
        if a and b:
            fixed = _repair_zone_pair(a, b)
            if fixed:
                lo, hi = fixed
                return lo, hi, (lo + hi) / 2.0
    for zm in BARE_ZONE.finditer(raw):
        a_s, b_s = zm.group(1), zm.group(2)
        a, b = _expand_abbr(a_s, b_s)
        if not a or not b:
            continue
        # "Tp 1/2" — R ulushi, zona emas (28-32 qisqa oltin zona qoladi)
        if "." not in str(a_s) and "." not in str(b_s) and a < 20 and b < 20:
            continue
        fixed = _repair_zone_pair(a, b)
        if fixed:
            lo, hi = fixed
            return lo, hi, (lo + hi) / 2.0
    for zm in SPACE_ZONE.finditer(raw):
        a, b = _expand_abbr(zm.group(1), zm.group(2))
        if not a or not b:
            continue
        if min(a, b) < 50:
            continue
        fixed = _repair_zone_pair(a, b)
        if fixed:
            lo, hi = fixed
            return lo, hi, (lo + hi) / 2.0
    return None, None, None


_CLOSE_NOW = re.compile(
    r"(?:\btugat(?:dik|ildi|amiz|ib)?\b|\byopildi\b|\byopdik\b|\byopib\b|"
    r"\bbekor(?:qil(?:dik|indi|amiz))?|\bcancel(?:led|ed)?\b|"
    r"^\s*(?:trade\s+|position\s+)?clos(?:ed|e)?\b"
    r"(?!\s*(?:above|below|near|at|in|from|on|over|under)\b)|"
    r"\bclos(?:ed|e)\s+(?:now|all|trades?|positions?|orders?|it)\b|"
    r"\b(?:trade|position|order)s?\s+clos(?:ed|e)\b|"
    r"\btp\s*hit\b|\bsl\s*hit\b|\binvalid(?:ated)?\b|\boff\s*now\b|"
    r"\bsignal\s*off\b|\boff\s*qil|\bto'?xtat(?:dik|amiz)?\b|"
    r"\bclose\s*(?:now|all|trade|it)\b|\bsignalni\s*yop|"
    r"\bishlamaymiz\b|\bclosed\s*(?:in\s*)?(?:profit|loss)\b|"
    r"\btp\s*olindi\b|\bsl\s*ur(?:di|ildi)\b|بسته|اغلق|\baktivmas\b|"
    r"\baktiv\s*emas\b|\bfaol\s*emas\b)",
    re.I,
)
_YOPAMIZ = re.compile(r"\byopamiz\b|\byopish\b", re.I)
_CLOSE_COND = re.compile(
    r"\b(?:buzsa|buzilsa|kelsa|bo'?lsa|agar|if|when|qilsa|break(?:s|ing)?)\b",
    re.I,
)


def is_close_message(text: str | None) -> bool:
    """Kanal admini bitimni hozir yopdi / tugatdi. 'buzsa yopamiz' — shart, yopish emas."""
    raw = str(text or "")
    if not raw.strip():
        return False
    if _CLOSE_NOW.search(raw):
        return True
    if _YOPAMIZ.search(raw) and not _CLOSE_COND.search(raw):
        return True
    return False


_LOSS_NOW = re.compile(
    r"(\bsl\s*(?:hit|ur(?:di|ildi|dimi)?|bo'?ldi|da\s*yop|ni\s*ur)|"
    r"\bstop\s*loss\b|\bstoploss\b|"
    r"-\s*\d{1,4}\s*(?:pip|pips|punkt|point)|\bzarar\b|\bloss\b)",
    re.I,
)
_LOSS_PLAN = re.compile(
    r"\b(?:sl|stop\s*loss|stoploss)\b\s*[:=]?\s*\d{3,5}(?:[.,]\d{1,3})?", re.I
)


def is_loss_message(text: str | None) -> bool:
    """Kanal 'stop loss / zarar' deb yozgan natija posti (v65).

    Bunday postda paper bitim MAHALLIY narxda emas, o'z STOP narxida yopiladi —
    minus stop lossgacha qancha bo'lsa, o'shancha hisoblanadi.
    Yangi signal rejasi («SL: 4367.44») bunga KIRMAYDI.
    """
    raw = str(text or "")
    if not raw.strip():
        return False
    if _LOSS_PLAN.search(raw):
        return False
    return bool(_LOSS_NOW.search(raw))


def _zone_entry(raw: str) -> float | None:
    _lo, _hi, mid = _zone_bounds(raw)
    return mid


INV_SL = re.compile(
    rf"{NUM}\s*(?:ni\s*)?(?:tana(?:si)?|body|buz(?:sa|ilsa)?|yopamiz|invalid)",
    re.I,
)


def _gold_levels(raw: str | None) -> list[float]:
    """Matndagi barcha 4 xonali oltin narxlar (4250), yil (2026) emas."""
    out: list[float] = []
    for m in re.finditer(r"(?<![A-Za-z0-9.])(\d{4}(?:[.,]\d{1,3})?)(?!\d)", raw or ""):
        v = _to_float(m.group(1))
        if not v:
            continue
        if 2020 <= v <= 2035:
            continue
        if 1800 <= v <= 5600:
            out.append(v)
    return out


def _gold_level(raw: str | None) -> float | None:
    """4 xonali oltin narx (4250), yil (2026) emas."""
    vals = _gold_levels(raw)
    return vals[-1] if vals else None


def refine_idea(p: ParsedSignal | None, ref: float | None = None) -> ParsedSignal | None:
    """'4250 korreksiya / oqib kelishi' — bozor narxiga qarab BUY yoki SELL."""
    if p is None:
        return None
    raw = p.raw or ""
    if not _IDEA_RE.search(raw):
        return p
    lvl = p.tp or p.entry or p.zone_low or _gold_level(raw)
    if not lvl:
        return p
    toward = bool(_TOWARD_RE.search(raw))
    if ref and ref > 0 and abs(float(lvl) - float(ref)) / max(abs(float(ref)), 1) > 0.003:
        if toward:
            p.direction = "SELL" if lvl < float(ref) else "BUY"
            p.tp = float(lvl)
            if p.tp and p.tp not in (p.tps or []):
                p.tps = [p.tp] + list(p.tps or [])
        else:
            p.direction = "BUY" if lvl < float(ref) else "SELL"
            if not p.entry:
                p.entry = float(lvl)
    elif toward and not p.tp:
        p.tp = float(lvl)
        if p.tp not in (p.tps or []):
            p.tps = [p.tp] + list(p.tps or [])
    elif not toward and not p.entry:
        p.entry = float(lvl)
    return p


def ref_from_text(raw: str | None) -> float | None:
    """Matndagi to'liq narx (4324) — qisqa zona (28-32) ni tiklash uchun.
    43011 kabi 5 xonali xato oltin narx emas."""
    nums: list[float] = []
    for m in re.finditer(NUM, raw or ""):
        v = _to_float(m.group(1))
        if v and v >= 200:
            nums.append(v)
    if not nums:
        return None
    goldish = [v for v in nums if 1800 <= v <= 5600]
    if goldish:
        return max(goldish)
    return max(nums)


def snap_price(n: float | None, ref: float | None) -> float | None:
    """28 + ref 4330 → 4328; 96 + 4290 → 4296."""
    if n is None:
        return None
    try:
        n = float(n)
    except (TypeError, ValueError):
        return None
    if not ref or ref <= 0 or n <= 0:
        return n
    ref = float(ref)
    if abs(n - ref) / ref <= 0.12:
        return n
    if 0.4 * ref <= n <= 1.6 * ref:
        return n
    sn = str(int(round(n))) if abs(n - round(n)) < 1e-6 else None
    sref = str(int(round(abs(ref))))
    if sn and 0 < len(sn) < len(sref):
        try:
            cand = float(sref[: -len(sn)] + sn)
            if abs(cand - ref) / ref <= 0.05:
                return cand
        except ValueError:
            pass
    if n < ref * 0.2:
        return None
    return n


def snap_parsed(p: ParsedSignal | None, ref: float | None) -> ParsedSignal | None:
    if p is None or not ref:
        return p

    def s(x):
        return snap_price(x, ref)

    p.entry = s(p.entry)
    p.sl = s(p.sl)
    p.tp = s(p.tp)
    p.zone_low = s(p.zone_low)
    p.zone_high = s(p.zone_high)
    if p.zone_low and p.zone_high and p.zone_low > p.zone_high:
        p.zone_low, p.zone_high = p.zone_high, p.zone_low
    if p.zone_low and p.zone_high and not p.entry:
        p.entry = (p.zone_low + p.zone_high) / 2.0
    p.tps = [s(x) or x for x in (p.tps or [])]
    if p.entry is None or (p.entry < ref * 0.2):
        if p.zone_low and p.zone_high:
            p.entry = (p.zone_low + p.zone_high) / 2.0
        elif not _TOWARD_RE.search(p.raw or ""):
            p.entry = float(ref)
    return refine_idea(p, ref)


def _num(m: re.Match | None, group: int = 1) -> float | None:
    if not m:
        return None
    return _to_float(m.group(group))


def _dir_word(w: str) -> str:
    w = (w or "").lower()
    if w.startswith("buy") or w.startswith("long") or w in ("call",):
        return "BUY"
    return "SELL"


def _strip_r_tp(raw: str) -> str:
    return _R_TP_LINE.sub(" ", raw or "")


def _tp_is_price(v: float | None, raw: str) -> bool:
    if not v or v <= 0:
        return False
    if v <= 20:
        return bool(re.search(r"eur|gbp|aud|nzd|usdchf|usdcad", raw or "", re.I)) and v >= 0.5
    return True


def _compact_levels(raw: str) -> tuple:
    """SNIPER: '4009 SELL' + '4011 STOP'  /  '4316-4318 SELL' + '4319 STOP'."""
    text = _strip_r_tp(raw or "")
    direction = entry = sl = zlo = zhi = None
    m = PRICE_THEN_DIR.search(text)
    if m:
        direction = _dir_word(m.group("d"))
        if m.group("a") and m.group("b"):
            a, b = _expand_abbr(m.group("a"), m.group("b"))
            if a and b:
                fixed = _repair_zone_pair(a, b)
                if fixed:
                    zlo, zhi = fixed
                    entry = (zlo + zhi) / 2.0
                else:
                    entry = (a + b) / 2.0
                    zlo, zhi = (a, b) if a <= b else (b, a)
        elif m.group("c"):
            entry = _to_float(m.group("c"))
            if entry and 2020 <= entry <= 2035:
                entry = None
    sm = SL_NUM_FIRST.search(text)
    sp = SL_PAT.search(text)
    sl = None
    if sp and sm:
        # "стоп 4390" va "4011 STOP 4000 TP" — raqam TP bo'lsa, oldingi shakl olinadi
        cand = _to_float(sp.group(1))
        tps_now = _collect_tps(text)
        if cand and any(abs(cand - t) < 1e-9 for t in tps_now):
            sl = _to_float(sm.group(1))
        else:
            sl = cand
    elif sp:
        sl = _to_float(sp.group(1))
    elif sm:
        sl = _to_float(sm.group(1))
    if sl and 2020 <= sl <= 2035:
        sl = None
    return direction, entry, sl, zlo, zhi


def _collect_tps(raw: str) -> list[float]:
    raw = _strip_r_tp(raw or "")
    found: dict[int, float] = {}
    for m in TPN_PAT.finditer(raw):
        n = int(m.group(1))
        v = _to_float(m.group(2))
        if v and _tp_is_price(v, raw):
            found[n] = v
    ordered = [found[i] for i in range(1, 6) if i in found]
    line = TPS_LINE.search(raw)
    if line:
        extras = [_to_float(x) for x in re.findall(NUM, line.group(0))]
        extras = [x for x in extras if x and _tp_is_price(x, raw)]
        for x in extras:
            if x not in ordered:
                ordered.append(x)
    for mm in TP_PAT.finditer(raw):
        v2 = _num(mm)
        if v2 and v2 not in ordered and _tp_is_price(v2, raw):
            ordered.append(v2)
    seen: list[float] = []
    for x in ordered:
        if x not in seen:
            seen.append(x)
    return seen[:5]


def parse_signal(text: str | None) -> ParsedSignal | None:
    """Matn/OCR dan signal. Reklama (ikkala yo'nalish, juftlik yo'q) → None."""
    if not text or not str(text).strip():
        return None
    raw = str(text).strip()
    if len(raw) > 4000:
        raw = raw[:4000]

    buys = len(BUY_WORDS.findall(raw))
    sells = len(SELL_WORDS.findall(raw))

    symbol = None
    direction = ""

    m = GLUED.search(raw)
    if m:
        symbol = resolve_symbol(m.group(1))
        direction = _dir_word(m.group(2))
    if not symbol:
        m = PAIR_DIR.search(raw)
        if m:
            direction = _dir_word(m.group(1))
            symbol = resolve_symbol(m.group(2))
    if not symbol:
        m2 = DIR_AFTER.search(raw)
        if m2:
            direction = _dir_word(m2.group(2))
            symbol = resolve_symbol(m2.group(1))
    if not symbol:
        for hm in HASH_PAIR.finditer(raw):
            tok = hm.group(1)
            if (tok or "").lower() in _SKIP_TOK:
                continue
            got = resolve_symbol(tok)
            if got:
                symbol = got
                break

    if buys and sells and not symbol:
        return None

    compact_dir, compact_entry, compact_sl, compact_zlo, compact_zhi = _compact_levels(raw)
    if compact_dir and not direction:
        direction = compact_dir
    if not direction:
        direction = "BUY" if buys else ("SELL" if sells else "")
    gold_lvl = _gold_level(raw)
    idea = bool(_IDEA_RE.search(raw))
    if not direction:
        if idea and (symbol or gold_lvl):
            symbol = symbol or "XAUUSDT"
            toward = bool(_TOWARD_RE.search(raw))
            down = len(SELL_WORDS.findall(raw))
            up = len(BUY_WORDS.findall(raw))
            if down and not up:
                direction = "SELL"
            elif up and not down:
                direction = "BUY"
            elif toward:
                direction = "SELL"
            else:
                direction = "BUY"
        else:
            return None
    if not direction:
        return None

    if symbol is None:
        tokens = re.findall(r"[A-Za-z]{2,16}", raw)
        for tok in tokens:
            low = tok.lower()
            if low in _SKIP_TOK:
                continue
            if low == "gold":
                symbol = "XAUUSDT"
                break
            got = resolve_symbol(tok)
            if got:
                symbol = got
                break
        if symbol is None and re.search(r"gold|xau|oltin|золот|طلا|ذهب", raw, re.I):
            symbol = "XAUUSDT"
        if symbol is None and re.search(r"\bbtc\b|bitcoin|биткоин", raw, re.I):
            symbol = "BTCUSDT"
        if symbol is None and re.search(r"\beth\b|ethereum", raw, re.I):
            symbol = "ETHUSDT"
        if symbol is None and re.search(r"silver|xag|kumush", raw, re.I):
            symbol = "SILVERUSDT"
        if symbol is None and re.search(r"\bwti\b|\boil\b|neft|usoil", raw, re.I):
            symbol = "USOILUSDT"
    if not symbol and direction:
        zlo0, _, _ = _zone_bounds(raw)
        if zlo0 or _gold_level(raw) or re.search(r"(?:\b(zona|zone|gold|xau|oltin)\b|طلا|ذهب)", raw, re.I):
            symbol = "XAUUSDT"
    if not symbol:
        return None

    tf = "1m"
    tf_explicit = False
    tm = TF_PAT.search(raw)
    if tm:
        tf = TF_MAP.get(tm.group(1).lower(), "15m")
        tf_explicit = True

    zlo, zhi, zmid = _zone_bounds(raw)
    if compact_zlo and compact_zhi:
        zlo, zhi = compact_zlo, compact_zhi
        zmid = (zlo + zhi) / 2.0
    entry = zmid
    if entry is None:
        entry = compact_entry
    if entry is None:
        entry = _num(ENTRY_PAT.search(raw))

    sl = compact_sl
    if not sl:
        sl = _num(SL_PAT.search(raw))
    if not sl:
        sl = _num(INV_SL.search(raw))
    tps = _collect_tps(raw)
    tp = tps[0] if tps else None
    if gold_lvl:
        toward = bool(_TOWARD_RE.search(raw))
        if toward:
            if gold_lvl not in tps:
                tps.insert(0, gold_lvl)
            if not tp:
                tp = gold_lvl
        elif entry is None:
            # SL/TP da ishlatilgan raqamni kirish deb olmaymiz
            used = {float(v) for v in ([sl] + list(tps) + [tp]) if v}
            pick = next(
                (v for v in _gold_levels(raw) if float(v) not in used), None
            )
            if pick is None:
                pick = gold_lvl
            if not (sl and abs(float(pick) - float(sl)) < 1e-9):
                entry = pick
    # STOP raqamini kirishga yozmasin
    if compact_entry and entry and compact_sl and abs(entry - compact_sl) < 1e-9:
        entry = compact_entry
    if compact_entry and (entry is None or (compact_sl and abs(float(entry) - float(compact_sl)) < 1e-6)):
        entry = compact_entry
    ref = ref_from_text(raw)
    if ref:
        # 28-32 + 4324 → 4328-4332
        tmp = ParsedSignal(
            direction=direction, symbol=symbol, timeframe=tf,
            entry=entry, sl=sl, tp=tp, tps=tps, raw=raw[:800],
            tf_explicit=tf_explicit, zone_low=zlo, zone_high=zhi,
        )
        tmp = snap_parsed(tmp, ref)
        entry, sl, tp, tps = tmp.entry, tmp.sl, tmp.tp, tmp.tps
        zlo, zhi = tmp.zone_low, tmp.zone_high

    # 5 xonali xato: "XAUUSD BUY 44150-44120" -> 4415.0-4412.0
    if (symbol or "").upper().startswith("XAU"):
        vals = [float(v) for v in (entry, sl, tp) if v]
        if vals and all(10000 <= v <= 99999 for v in vals):
            scaled = [v / 10.0 for v in vals]
            if all(1500 <= v <= 8000 for v in scaled):
                entry = entry / 10.0 if entry else entry
                sl = sl / 10.0 if sl else sl
                tp = tp / 10.0 if tp else tp
                tps = [t / 10.0 for t in tps]
                zlo = zlo / 10.0 if zlo else zlo
                zhi = zhi / 10.0 if zhi else zhi

    px = entry or sl or gold_lvl
    symbol = fit_symbol(symbol, px) or symbol
    got = ParsedSignal(
        direction=direction,
        symbol=symbol,
        timeframe=tf,
        entry=entry,
        sl=sl,
        tp=tp,
        tps=tps,
        raw=raw[:800],
        tf_explicit=tf_explicit,
        zone_low=zlo,
        zone_high=zhi,
    )
    return refine_idea(got, ref)


def extract_levels(text: str | None) -> tuple[float | None, float | None, list[float]]:
    """Faqat SL/TP/entry — juftlik bo'lmasa ham (pastdagi yarmi)."""
    raw = str(text or "")
    if not raw.strip():
        return None, None, []
    entry = _zone_entry(raw)
    if entry is None:
        entry = _num(ENTRY_PAT.search(raw))
    sl = _num(SL_PAT.search(raw))
    if not sl:
        sl = _num(INV_SL.search(raw))
    tps = _collect_tps(raw)
    g = _gold_level(raw)
    if g and _IDEA_RE.search(raw):
        if _TOWARD_RE.search(raw):
            if g not in tps:
                tps.append(g)
        elif entry is None:
            entry = g
    return entry, sl, tps


def _score(p: ParsedSignal) -> int:
    return (
        (4 if p.direction else 0)
        + (4 if p.symbol else 0)
        + (2 if p.entry else 0)
        + (2 if p.sl else 0)
        + (1 if p.tp or p.tps else 0)
    )


def merge_parsed(a: ParsedSignal | None, b: ParsedSignal | None) -> ParsedSignal | None:
    """Tepa + past xabarlarni bitta signalga yig'ish."""
    if a is None:
        return b
    if b is None:
        return a
    if a.symbol and b.symbol and a.symbol != b.symbol:
        return a if _score(a) >= _score(b) else b
    if a.direction and b.direction and a.direction != b.direction and a.symbol == b.symbol:
        return a if _score(a) >= _score(b) else b
    base, other = (a, b) if _score(a) >= _score(b) else (b, a)
    tps = list(base.tps or [])
    for x in (other.tps or []):
        if x not in tps:
            tps.append(x)
    raw = (base.raw or "") + ("\n" + other.raw if other.raw and other.raw not in (base.raw or "") else "")
    tf_ex = bool(getattr(base, "tf_explicit", False) or getattr(other, "tf_explicit", False))
    if getattr(base, "tf_explicit", False):
        tf = base.timeframe or "1m"
    elif getattr(other, "tf_explicit", False):
        tf = other.timeframe or "1m"
    else:
        tf = base.timeframe or other.timeframe or "1m"
    return ParsedSignal(
        direction=base.direction or other.direction,
        symbol=base.symbol or other.symbol,
        timeframe=tf,
        entry=base.entry or other.entry,
        sl=base.sl or other.sl,
        tp=base.tp or other.tp or (tps[0] if tps else None),
        tps=tps,
        raw=raw[:800],
        tf_explicit=tf_ex,
        zone_low=getattr(base, "zone_low", None) or getattr(other, "zone_low", None),
        zone_high=getattr(base, "zone_high", None) or getattr(other, "zone_high", None),
    )


def apply_levels(parsed: ParsedSignal, text: str | None) -> ParsedSignal:
    """Pastdagi xabardagi SL/TP/entry ni mavjud signalga yopishtirish."""
    entry, sl, tps = extract_levels(text)
    if entry and not parsed.entry:
        parsed.entry = entry
    if sl and not parsed.sl:
        parsed.sl = sl
    if tps:
        for x in tps:
            if x not in parsed.tps:
                parsed.tps.append(x)
        if not parsed.tp:
            parsed.tp = parsed.tps[0]
    zlo, zhi, zmid = _zone_bounds(text or "")
    if zmid and not parsed.entry:
        parsed.entry = zmid
    if zlo and not parsed.zone_low:
        parsed.zone_low = zlo
        parsed.zone_high = zhi
    if text and text not in (parsed.raw or ""):
        parsed.raw = ((parsed.raw or "") + "\n" + text)[:800]
    return parsed
