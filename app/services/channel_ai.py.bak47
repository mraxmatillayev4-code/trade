"""Har kanal xabarini AI ajratadi: SIGNAL yoki EMAS (matn + rasm + qisqa izoh).

1) Mahalliy detektor (kalit shart emas)
2) OCR (rasm/skrin)
3) Ixtiyoriy public LLM (kalit bo'lsa) — qiyin formatlar
"""
from __future__ import annotations

import json
import re

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.symbols import resolve_symbol
from app.services.channel_ocr import ocr_image
from app.services.channel_parse import ParsedSignal, parse_signal
from app.services.local_ai import analyze_ex as _lai_ex
try:
    from app.services.local_ai import __version__ as _lai_ver
except Exception:  # noqa: BLE001
    _lai_ver = '?'

logger = get_logger(__name__)

_NOISE = re.compile(
    r"(good\s*morning|good\s*night|hello\s*traders|join\s*vip|subscribe|"
    r"payment|invoice|deposit|withdraw|congratulations|tp\s*hit|sl\s*hit|"
    r"target\s*hit|closed\s*(in\s*)?(profit|loss)|breakeven|"
    r"xayrli\s*(tong|kech)|obuna|to'lov|tabriklaymiz|"
    r"result(s)?\s*:|weekly\s*recap|follow\s*us|reklama|"
    r"kanalga|تبلیغ|لینک|عضویت)",
    re.I,
)

_DIR_BUY = re.compile(
    r"(?:\b(?:buy|long|bull(?:ish)?|alish|sotib|покуп|лонг|купит|call|almoq|"
    r"olamiz|longga|tepaga|ko'?taril|kotariladi)\w*"
    r"|#buy|🟢|📈|⬆️|🔼|🟩|🚀|💙|▲|△|▴"
    r"|خرید|بخر|بخری|صعودی|صعود|لانگ|شراء|شرا|اشتري)",
    re.I,
)
_DIR_SELL = re.compile(
    r"(?:\b(?:sell|short|bear(?:ish)?|sotish|продаж|шорт|прода|put|sotmoq|"
    r"sotamiz|sotyapmiz|sotdik|sotmoqda|sotilmoqda|sotuv|shortga|pastga|tushadi|tushishi)\w*"
    r"|#sell|🔴|📉|⬇️|🔽|🟥|🔻|💥|💔|▼|▽|▾"
    r"|فروش|بفروش|نزولی|نزول|شورت|هبوط|بيع)",
    re.I,
)

_PAIR_WORDS = re.compile(
    r"\b(xauusd|xau/usd|xauusdt|xau|gold|oltin|btc(?:usd)?|bitcoin|"
    r"eth(?:usd)?|ethereum|eurusd|gbpusd|usdjpy|usdchf|audusd|nzdusd|"
    r"silver|xag|kumush|usoil|ukoil|wti|brent|oil|neft|sol(?:ana)?|"
    r"bnb|xrp|doge|ada|link|avax|طلا|ذهب)(?:usdt?)?\b",
    re.I,
)


def _ocr(image_bytes: bytes | None) -> str:
    if not image_bytes:
        return ""
    try:
        return (ocr_image(image_bytes) or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.info("[CH-AI] ocr: %s", exc)
        return ""


def _is_noise(blob: str) -> bool:
    if not blob:
        return False
    if _NOISE.search(blob) and not (_DIR_BUY.search(blob) or _DIR_SELL.search(blob)):
        return True
    if _NOISE.search(blob) and not _PAIR_WORDS.search(blob):
        return True
    return False


def _find_symbol(blob: str) -> str | None:
    m = _PAIR_WORDS.search(blob or "")
    if m:
        got = resolve_symbol(m.group(1))
        if got:
            return got
    for tok in re.findall(r"[A-Za-z]{3,16}", blob or ""):
        got = resolve_symbol(tok)
        if got:
            return got
    return None


def _find_direction(blob: str) -> str:
    b = len(_DIR_BUY.findall(blob or ""))
    s = len(_DIR_SELL.findall(blob or ""))
    if b and s:
        if b > s:
            return "BUY"
        if s > b:
            return "SELL"
        return ""
    if b:
        return "BUY"
    if s:
        return "SELL"
    return ""


def _loose_parse(blob: str, has_image: bool, caption: str = "") -> ParsedSignal | None:
    """Qiyin format: emoji + juftlik, rasm ostidagi 1 qator, OCR."""
    if not blob and not has_image:
        return None
    if _is_noise(blob):
        return None
    # Avval qisqa izoh (caption) — OCR dagi Buy/Sell tugmalari chalg'itmasin
    direction = _find_direction(caption) if caption else ""
    if not direction:
        direction = _find_direction(blob)
    symbol = _find_symbol(caption) if caption else None
    if not symbol:
        symbol = _find_symbol(blob)
    p = parse_signal(caption) if caption else None
    if p:
        return p
    p = parse_signal(blob) if blob else None
    if p:
        return p
    # Rasm + yo'nalish, juftlik yo'q → oltin (asosiy)
    if has_image and direction and not symbol:
        symbol = "XAUUSDT"
    if not direction or not symbol:
        return None
    return ParsedSignal(
        direction=direction,
        symbol=symbol,
        timeframe="1m",
        raw=(blob or "")[:800],
    )


def interpret(text: str | None, image_bytes: bytes | None = None) -> ParsedSignal | None:
    cap = (text or "").strip()
    ocr = _ocr(image_bytes)
    blob = "\n".join(p for p in (cap, ocr) if p)
    got, _reason = _classify(cap, blob, bool(image_bytes), bool(ocr))
    return got


def _classify(caption: str, blob: str, has_image: bool, has_ocr: bool):
    # v46: mahalliy AI xatosi hech qachon oqimni to'xtatmasin
    try:
        _lp, _lwhy, _lveto = _lai_ex(blob or caption or '', '', bool(has_image))
    except Exception as _le:  # noqa: BLE001
        logger.warning('[CH-AI] lokal AI xato: %s: %s', type(_le).__name__, _le)
        _lp, _lwhy, _lveto = None, '', False
    if _lp is not None:
        return _lp, 'lokal-ai'
    if _lveto:
        return None, _lwhy
    if _is_noise(blob or caption):
        return None, "shovqin (salom/reklama/TP HIT)"
    if caption:
        p = parse_signal(caption)
        if p:
            return p, "ok"
    if blob:
        p = parse_signal(blob)
        if p:
            return p, "ok"
    p = _loose_parse(blob or caption, has_image, caption)
    if p:
        return p, "ok"
    d = _find_direction(caption) or _find_direction(blob)
    s = _find_symbol(caption) or _find_symbol(blob)
    if d and s:
        return ParsedSignal(
            direction=d, symbol=s, timeframe="1m",
            raw=(blob or caption or "")[:800],
        ), "ok"
    if has_image and not blob:
        return None, "rasmda yozuv o'qilmadi"
    if has_image and not has_ocr and not _find_symbol(caption) and not _find_direction(caption):
        return None, "rasm + izohdan juftlik/yo'nalish yo'q"
    if not _find_symbol(blob or caption) and not _find_direction(blob or caption):
        return None, "juftlik/yo'nalish yo'q"
    return None, "aniqlanmadi"


async def interpret_async(text: str | None,
                          image_bytes: bytes | None = None) -> ParsedSignal | None:
    """Har xabarni ko'radi: avval mahalliy AI, yetmasa LLM. reason oxirgi chaqiriqda."""
    global last_reason
    cap = (text or "").strip()
    ocr = _ocr(image_bytes)
    blob = "\n".join(p for p in (cap, ocr) if p)
    snippet = (blob or cap or "").replace("\n", " ")[:100]
    logger.info(
        "[CH-AI] ko'rindi rasm=%s ocr=%s belgi=%d: %s",
        bool(image_bytes), bool(ocr), len(blob or ""), snippet or "(bo'sh)",
    )
    got, reason = _classify(cap, blob, bool(image_bytes), bool(ocr))
    if got:
        last_reason = "SIGNAL"
        logger.info("[CH-AI] SIGNAL %s %s", got.direction, got.symbol)
        return got
    maybe = bool(image_bytes) or bool(_find_symbol(blob or cap) or _find_direction(blob or cap))
    if maybe:
        llm = await _llm_parse(blob or cap or "(chart image, short caption)", bool(image_bytes))
        if llm:
            last_reason = "SIGNAL"
            logger.info("[CH-AI] SIGNAL(LLM) %s %s", llm.direction, llm.symbol)
            return llm
    last_reason = reason
    logger.warning("[CH-AI] EMAS (%s) | %s", reason, snippet or "(bosh)")
    return None


last_reason: str = ""


async def _llm_parse(blob: str, has_image: bool) -> ParsedSignal | None:
    settings = get_settings()
    if not getattr(settings, "ai_api_key", ""):
        return None
    url = (settings.ai_api_url or "").strip()
    if not url:
        return None
    extra = " There is a chart screenshot with a short caption." if has_image else ""
    prompt = (
        "You read Telegram trading-channel posts (any language, emoji, OCR junk)."
        f"{extra}\n"
        "Any format is a SIGNAL if pair + buy/sell/long/short OR a gold idea. "
        "Examples: 'xauusd h1 idea buy asosiy entry 4419-4411'; "
        "'4250 korreksiya bn oqib kelishi kerak' = gold level 4250. "
        "Short zones 28-32 or 4339-29 are gold last digits. Default TF 1m. "
        "Not a signal only if greeting, VIP ad, or TP/SL HIT result.\n"
        "Return JSON only:\n"
        '{"is_signal":true|false,"direction":"BUY"|"SELL"|"" ,'
        '"symbol":"BTCUSDT"|"XAUUSDT"|other,'
        '"timeframe":"5m"|"15m"|"1h"|"4h","entry":null,"sl":null,"tp":null,'
        '"tps":[]}\n'
        "Map gold/xau/xauusd/oltin -> XAUUSDT, btc -> BTCUSDT, eurusd -> EURUSDT, "
        "silver/xag -> SILVERUSDT, oil/wti -> USOILUSDT.\n"
        "If not a new signal, is_signal=false and direction=\"\".\n\n"
        f"MESSAGE:\n{(blob or '')[:2200]}"
    )
    headers = {
        "Authorization": f"Bearer {settings.ai_api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": settings.ai_api_model or "llama-3.1-8b-instant",
        "messages": [
            {"role": "system", "content": "Return only JSON. Trading signal classifier."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "max_tokens": 280,
    }
    try:
        import httpx
        async with httpx.AsyncClient(timeout=12.0) as client:
            r = await client.post(url, headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
        content = (
            (data.get("choices") or [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        return _json_to_parsed(content, blob)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH-AI] public API: %s", exc)
        return None


def _json_to_parsed(content: str, raw: str) -> ParsedSignal | None:
    if not content:
        return None
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if obj.get("is_signal") is False:
        return None
    direction = str(obj.get("direction") or "").upper()
    if direction not in ("BUY", "SELL"):
        return None
    symbol = resolve_symbol(str(obj.get("symbol") or ""))
    if not symbol:
        symbol = _find_symbol(raw or "")
    if not symbol:
        return None
    tf = str(obj.get("timeframe") or "1m").lower()
    if tf not in ("1m", "5m", "15m", "1h", "4h", "30m", "1d"):
        tf = "1m"

    def _f(key: str) -> float | None:
        v = obj.get(key)
        try:
            return float(v) if v is not None and v != "" else None
        except (TypeError, ValueError):
            return None

    tps: list[float] = []
    raw_tps = obj.get("tps") or []
    if isinstance(raw_tps, list):
        for x in raw_tps:
            try:
                tps.append(float(x))
            except (TypeError, ValueError):
                pass
    tp = _f("tp")
    if tp and tp not in tps:
        tps.insert(0, tp)
    return ParsedSignal(
        direction=direction, symbol=symbol, timeframe=tf,
        entry=_f("entry"), sl=_f("sl"), tp=tp or (tps[0] if tps else None),
        tps=tps, raw=(raw or "")[:800],
    )
