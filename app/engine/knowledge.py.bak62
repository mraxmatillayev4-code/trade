"""SINO AI internet xotirasi — API kalitsiz.

Google/Yandex o'rniga ochiq qidiruv (DuckDuckGo + Yandex HTML) va
YouTube RSS o'qiydi. Kalit so'zlarni dars (lesson) ga bog'laydi.
Dars yomon ishlasa (yetarli tanlanma + past WR) — o'sha DARS bloklanadi,
botning o'zi emas.

Yangi DB jadval yo'q: JSON fayl + ixtiyoriy Redis.
Tarmoq ishlamasa seed-darslar baribir ishlayveradi (fail-open).
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Lock

from app.core.logging import get_logger
from app.core.timeuz import stamp_tashkent

logger = get_logger(__name__)

_MEM_PATH = Path(__file__).resolve().parent / "_ai_memory.json"
_LOCK = Lock()
_UA = "Mozilla/5.0 (compatible; SINOBot/1.0; +https://t.me) AppleWebKit/537.36"
_TIMEOUT = 8

# YouTube ta'lim kanallari (RSS — kalit yo'q)
_YT_RSS = (
    "https://www.youtube.com/feeds/videos.xml?channel_id=UCXRfIMqmyR21RNI4x2Woi1Q",  # FxDailyReport
)

_QUERIES = (
    "price action pullback do not chase trading",
    "RSI overbought do not buy trend pullback",
    "multi timeframe trend confirmation forex gold",
    "london new york killzone session trading",
    "wavetrend cipher b squeeze breakout",
)

# Matndan dars ID chiqarish
_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("no_chase", ("don't chase", "do not chase", "overextended", "fomo", "chasing price",
                  "quvlamang", "narxni quvlamang")),
    ("pullback", ("pullback", "retest", "discount zone", "qaytish", "ema pullback")),
    ("rsi_ob", ("overbought", "rsi high", "haddan oshgan", "don't buy overbought")),
    ("rsi_os", ("oversold", "rsi low", "haddan tushgan")),
    ("htf", ("higher timeframe", "multi timeframe", "htf trend", "yuqori timeframe",
             "trend confirmation")),
    ("volume", ("volume confirmation", "hajm tasdiq", "low volume fake")),
    ("sr_room", ("support resistance", "room to target", "next resistance", "s/r")),
    ("session", ("killzone", "london session", "new york session", "kill zone",
                 "asia session avoid")),
    ("squeeze", ("squeeze", "volatility contraction", "ttm squeeze", "keltner")),
    ("no_counter", ("counter trend", "don't trade against trend", "aks trend",
                    "against the trend")),
]


@dataclass
class Lesson:
    id: str
    title: str
    source: str  # seed | web | youtube
    kind: str    # boost | penalty
    cond: str
    w: float
    n: int = 0
    wins: int = 0
    losses: int = 0
    blocked: bool = False
    web_hits: int = 0
    text: str = ""
    last_src: str = ""

    @property
    def wr(self) -> float:
        d = self.wins + self.losses
        return (self.wins / d) if d else 0.5

    def avg_r(self) -> float:
        return ((self.wins - self.losses) / self.n) if self.n else 0.0


def _seed() -> dict[str, Lesson]:
    def L(i, title, kind, cond, w, text) -> Lesson:
        return Lesson(id=i, title=title, source="seed", kind=kind, cond=cond, w=w, text=text)

    items = [
        L("no_chase", "Narxni quvlamang (EMA20)", "penalty", "stretched", 1.4,
          "Internet: overextended kirish — keng zarar. Pullback kuting."),
        L("pullback", "Trend ichida qaytish", "boost", "near_ema20", 0.8,
          "Internet: sifatli kirish — EMA20/50 qaytishida."),
        L("rsi_ob", "RSI overbought — BUY quvlamang", "penalty", "rsi_ob", 1.6,
          "Internet: RSI >70 da long ochmang."),
        L("rsi_os", "RSI oversold — SELL quvlamang", "penalty", "rsi_os", 1.6,
          "Internet: RSI <30 da short ochmang."),
        L("htf", "Yuqori TF trend tasdig'i", "boost", "htf_align", 0.9,
          "Internet: HTF trend bilan bir yo'nalishda kiring."),
        L("volume", "Hajm tasdig'i", "boost", "vol_ok", 0.6,
          "Internet: hajmsiz breakout ko'p soxta."),
        L("sr_room", "S/R gacha joy", "penalty", "no_room", 1.1,
          "Internet: yaqin resistance/support oldida kirish — yomon R/R."),
        L("session", "O'lik sessiya ehtiyoti", "penalty", "asia_dead", 0.5,
          "Internet: London/NY killzone tashqarisida shovqin."),
        L("squeeze", "Squeeze chiqishi", "boost", "squeeze_rel", 0.7,
          "Internet: siqilishdan keyingi impuls — yaxshi timing."),
        L("no_counter", "Aks-trend 5m", "penalty", "counter_5m", 1.2,
          "Internet: past TF da HTF ga qarshi kirmang."),
    ]
    return {x.id: x for x in items}


@dataclass
class KnowledgeAdj:
    buy: float = 0.0
    sell: float = 0.0
    fired: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class KnowledgeBase:
    def __init__(self, persist: bool = True) -> None:
        self.lessons: dict[str, Lesson] = _seed()
        self.last_study: str = ""
        self._persist = persist
        if persist:
            self.load()

    # ---------- persist ----------
    def load(self) -> None:
        try:
            if not _MEM_PATH.exists():
                return
            data = json.loads(_MEM_PATH.read_text(encoding="utf-8"))
            for raw in data.get("lessons", []):
                lid = raw.get("id")
                if not lid:
                    continue
                if lid in self.lessons:
                    cur = self.lessons[lid]
                    cur.n = int(raw.get("n", cur.n))
                    cur.wins = int(raw.get("wins", cur.wins))
                    cur.losses = int(raw.get("losses", cur.losses))
                    cur.blocked = bool(raw.get("blocked", cur.blocked))
                    cur.web_hits = int(raw.get("web_hits", cur.web_hits))
                    cur.last_src = str(raw.get("last_src", cur.last_src) or "")
                    if raw.get("source") in ("web", "youtube"):
                        cur.source = raw["source"]
                else:
                    self.lessons[lid] = Lesson(**{**asdict(_seed()[next(iter(_seed()))]), **raw})
            self.last_study = str(data.get("last_study") or "")
            logger.info("[AI-WEB] xotira yuklandi: %d dars", len(self.lessons))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AI-WEB] xotira o'qilmadi: %s", exc)

    def save(self) -> None:
        if not getattr(self, "_persist", True):
            return
        try:
            payload = {
                "last_study": self.last_study,
                "lessons": [asdict(x) for x in self.lessons.values()],
            }
            _MEM_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=0), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AI-WEB] xotira yozilmadi: %s", exc)

    # ---------- internet ----------
    def study_web(self) -> int:
        """Qidiruv + YouTube RSS. Kalit yo'q. Xato bo'lsa 0."""
        hits = 0
        blobs: list[tuple[str, str]] = []
        for q in _QUERIES:
            html = _http("https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": q}))
            if html:
                blobs.append(("web", html.lower()))
            yq = "https://yandex.com/search/?" + urllib.parse.urlencode({"text": q, "lr": "0"})
            yhtml = _http(yq)
            if yhtml:
                blobs.append(("web", yhtml.lower()))
        for url in _YT_RSS:
            rss = _http(url)
            if rss:
                blobs.append(("youtube", rss.lower()))

        for src, text in blobs:
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text)[:80000]
            for lid, keys in _KEYWORDS:
                if any(k in text for k in keys):
                    les = self.lessons.get(lid)
                    if les is None:
                        continue
                    les.web_hits += 1
                    les.last_src = src
                    if src in ("web", "youtube"):
                        les.source = src
                    hits += 1
        from datetime import datetime, timezone
        self.last_study = stamp_tashkent() + " (Toshkent)"
        self.save()
        logger.info("[AI-WEB] o'rganish: %d ta kalit mosligi, darslar=%d", hits, len(self.lessons))
        return hits

    # ---------- signalga qo'llash ----------
    def apply(self, snap: dict) -> KnowledgeAdj:
        """Snapshot shartlariga qarab +/- ball. Bloklangan dars o'tkazib yuboriladi."""
        adj = KnowledgeAdj()
        for les in self.lessons.values():
            if les.blocked:
                continue
            if not _cond_match(les.cond, snap):
                continue
            w = les.w + (0.25 if les.web_hits > 0 else 0.0)
            buy_d = sell_d = 0.0
            c = les.cond
            if les.kind == "boost":
                if c == "htf_align":
                    buy_d, sell_d = (w, 0.0) if snap.get("htf_buy") else ((0.0, w) if snap.get("htf_sell") else (0, 0))
                elif c == "near_ema20":
                    buy_d, sell_d = (w, 0.0) if snap.get("near_ema20_up") else ((0.0, w) if snap.get("near_ema20_dn") else (0, 0))
                elif c == "vol_ok":
                    buy_d, sell_d = (w, 0.0) if snap.get("vol_buy") else ((0.0, w) if snap.get("vol_sell") else (0, 0))
                elif c == "squeeze_rel" and snap.get("squeeze_rel"):
                    buy_d, sell_d = (w, 0.0) if snap.get("green") else (0.0, w)
            else:
                if c == "stretched":
                    buy_d = -w if snap.get("stretched_up") else 0.0
                    sell_d = -w if snap.get("stretched_dn") else 0.0
                elif c == "rsi_ob" and snap.get("rsi_ob"):
                    buy_d = -w
                elif c == "rsi_os" and snap.get("rsi_os"):
                    sell_d = -w
                elif c == "no_room":
                    buy_d = -w if snap.get("no_room_up") else 0.0
                    sell_d = -w if snap.get("no_room_dn") else 0.0
                elif c == "asia_dead" and snap.get("asia_dead") and snap.get("traditional"):
                    buy_d = sell_d = -w * 0.5
                elif c == "counter_5m" and snap.get("mtf_against"):
                    buy_d = sell_d = -w
            if buy_d or sell_d:
                adj.buy += buy_d
                adj.sell += sell_d
                adj.fired.append(les.id)
                adj.notes.append(("WEB " if les.web_hits else "DARS ") + les.title)
        adj.fired = list(dict.fromkeys(adj.fired))
        return adj

    def credit(self, fired: list[str], r: float) -> list[str]:
        """Yopilgan bitim: dars yaxshi/yomon. Yomon dars BLOK."""
        notes = []
        tag_w = r > 0.05
        tag_l = r < -0.05
        for lid in fired or []:
            les = self.lessons.get(lid)
            if les is None:
                continue
            les.n += 1
            if tag_w:
                les.wins += 1
            elif tag_l:
                les.losses += 1
            decided = les.wins + les.losses
            if decided >= 8 and les.wr < 0.38 and les.avg_r() < 0:
                if not les.blocked:
                    les.blocked = True
                    notes.append(f"DARS BLOK: {les.title} WR {les.wr*100:.0f}% — internetdagi maslahat yomon chiqdi")
                    logger.info("[AI-WEB] dars bloklandi: %s WR=%.2f", les.id, les.wr)
            elif decided >= 8 and les.blocked and les.wr > 0.52:
                les.blocked = False
                notes.append(f"DARS OCHILDI: {les.title} yana foydali")
        self.save()
        return notes

    def summary(self, limit: int = 8) -> str:
        lines = ["🌍 <b>AI INTERNET XOTIRASI</b>"]
        if self.last_study:
            lines.append(f"  ⏳ Oxirgi o'rganish: {self.last_study}")
        blocked = [x for x in self.lessons.values() if x.blocked]
        active = [x for x in self.lessons.values() if not x.blocked]
        if blocked:
            lines.append("  🚫 Bloklangan darslar (yomon chiqdi):")
            for x in blocked[:5]:
                lines.append(f"    • {x.title} WR {x.wr*100:.0f}% ({x.n} ta)")
        else:
            lines.append("  ✅ Hali bloklangan dars yo'q")
        webbed = [x for x in active if x.web_hits > 0]
        lines.append(f"  📡 Internet tasdiqlagan: {len(webbed)} dars")
        for x in sorted(webbed, key=lambda z: -z.web_hits)[:limit]:
            src = x.source
            lines.append(f"    • {x.title} [{src}, {x.web_hits} hit]")
        return "\n".join(lines)


def _cond_match(cond: str, snap: dict) -> bool:
    return {
        "stretched": bool(snap.get("stretched_up") or snap.get("stretched_dn")),
        "near_ema20": bool(snap.get("near_ema20_up") or snap.get("near_ema20_dn")),
        "rsi_ob": bool(snap.get("rsi_ob")),
        "rsi_os": bool(snap.get("rsi_os")),
        "htf_align": bool(snap.get("htf_buy") or snap.get("htf_sell")),
        "vol_ok": bool(snap.get("vol_buy") or snap.get("vol_sell")),
        "no_room": bool(snap.get("no_room_up") or snap.get("no_room_dn")),
        "asia_dead": bool(snap.get("asia_dead")),
        "squeeze_rel": bool(snap.get("squeeze_rel")),
        "counter_5m": bool(snap.get("mtf_against") and snap.get("timeframe") == "5m"),
    }.get(cond, False)


def _http(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "text/html,application/atom+xml"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read()[:250000]
        return raw.decode("utf-8", errors="ignore")
    except Exception as exc:  # noqa: BLE001
        logger.info("[AI-WEB] fetch o'tmadi %s: %s", url[:70], exc)
        return ""


_KB: KnowledgeBase | None = None


def get_knowledge() -> KnowledgeBase:
    global _KB
    with _LOCK:
        if _KB is None:
            _KB = KnowledgeBase()
        return _KB
