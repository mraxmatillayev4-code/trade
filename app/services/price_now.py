"""v116/v117: /narx va "💲 Narx" tugmasi — bot hozir KO'RAYOTgan oltin narxi.

v117 TUZATISH: bot oltin narxi endi MEXC XAU_USDT indexidan EMAS (u USDT-da
kvotalanib ~+6$ chalkash keltirardi), OLTIN USD spot (Swissquote javon
kvotasi — broker/MT5 bilan bir xil) manbadan olinadi. Karta: spot bid/ask/mid,
MEXC bilan farqi va Toshkent vaqti (UTC+5).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone


def format_price_card(symbol: str, live_px: float | None, src: str,
                      fetch_ms: int, last_px: float | None,
                      last_src: str, last_age_s: float | None) -> str:
    """Tayyor karta matni (HTML) — sof funksiya, testsiz ham tekshiriladi."""
    sym = str(symbol or "").upper().replace("USDT", "/USD")
    lines = ["\U0001F4B2 <b>" + sym + "</b> — bot hozir ko'rayotgan narx"]
    if live_px and float(live_px) > 0:
        lines.append(f"   jonli: <b>{float(live_px):,.2f}</b> "
                     f"({src or 'birja'}, {max(0, fetch_ms)} ms da olindi)")
    else:
        lines.append("   jonli: <b>vaqtincha yo'q</b> — birja javob bermadi")
    if last_px and float(last_px) > 0:
        age = ("?" if last_age_s is None
               else (f"{last_age_s:.0f} s oldin" if last_age_s < 90
                     else f"{last_age_s / 60:.1f} daq oldin"))
        lines.append(f"   oxirgi kuzatilgan: <b>{float(last_px):,.2f}</b> "
                     f"({last_src or '?'}, {age})")
    now = datetime.now(timezone.utc)
    lines.append("   server vaqti: " + now.strftime("%H:%M:%S") + " UTC")
    lines.append("")
    lines.append("<i>Bot signallarni SHU narxlarga tayangan holda kuzatadi. "
                 "MT5 brokeringiz narxi bilan 0.05–0.30$ farq — normal "
                 "(turli manbalar).</i>")
    return "\n".join(lines)


_fetcher = None


def set_price_fetcher(fn) -> None:
    """main.py to'g'ridan-to'g'ri birja tikkerini ulaydi (keshsiz narx)."""
    global _fetcher
    _fetcher = fn


async def build_price_card(symbol: str, price_fetcher=None) -> str:
    """price_fetcher(symbol) → float | None — jonli birja tickeri
    (main ulagan global fetcher yoki parametr; test uchun parametr).

    v117: OLTIN uchun SPOT karta (bid/ask/mid + MEXC farqi + Toshkent vaqti).
    """
    sym = str(symbol or "").upper() or "XAUUSDT"
    fetcher = price_fetcher or _fetcher
    # ---- v117: oltin — spot kvota kartasi ----
    if str(sym).upper().startswith("XAU"):
        spot = None
        t0 = time.monotonic()
        try:
            from app.market import spot_quote as _SQ117
            spot = await _SQ117.fetch_spot(force=True)
        except Exception:  # noqa: BLE001
            spot = None
        fetch_ms = int((time.monotonic() - t0) * 1000)
        mexc_px = None
        mf = _mexc_fetcher or fetcher
        if mf is not None:
            try:
                mexc_px = await mf(sym)
                mexc_px = float(mexc_px) if mexc_px else None
            except Exception:  # noqa: BLE001
                mexc_px = None
        last_px = last_src = None
        last_age = None
        try:
            from app.services import watchdog as _wd
            lp = _wd.last_price(sym)
            if lp and lp[0]:
                last_px = float(lp[0])
                last_src = str(lp[2]) if len(lp) > 2 else ""
                try:
                    if len(lp) > 1 and lp[1] is not None:
                        last_age = float(lp[1])
                except (TypeError, ValueError):
                    last_age = None
        except Exception:  # noqa: BLE001
            pass
        trend = None
        try:
            from app.market import spot_quote as _SQ117
            trend = _SQ117.spot_trend()
        except Exception:  # noqa: BLE001
            trend = None
        return format_price_card_v117(sym, spot, fetch_ms, mexc_px,
                                      last_px, last_src, last_age, trend=trend)
    # ---- v116: boshqa juftliklar — eski yo'l ----
    t0 = time.monotonic()
    px = None
    if fetcher is not None:
        try:
            px = await fetcher(sym)
            px = float(px) if px else None
        except Exception:  # noqa: BLE001
            px = None
    fetch_ms = int((time.monotonic() - t0) * 1000)
    src = "MEXC index" if str(sym).upper().startswith("XAU") else "birja"
    last_px = last_src = None
    last_age = None
    try:
        from app.services import watchdog as _wd
        lp = _wd.last_price(sym)
        if lp and lp[0]:
            last_px = float(lp[0])
            last_src = str(lp[2]) if len(lp) > 2 else ""
            try:
                if len(lp) > 1 and lp[1] is not None:
                    last_age = float(lp[1])       # last_price -> yosh (soniya)
            except (TypeError, ValueError):
                last_age = None
    except Exception:  # noqa: BLE001
        pass
    return format_price_card(sym, px, src, fetch_ms, last_px, last_src, last_age)


# ---------- v117: SPOT karta (oltin uchun) ----------

_mexc_fetcher = None


def set_mexc_fetcher(fn) -> None:
    """main.py oltin zaxira birjasini (MEXC) ulaydi — faqat farq ko'rsatish."""
    global _mexc_fetcher
    _mexc_fetcher = fn


def _fmt_px(v: float) -> str:
    return f"{float(v):,.2f}"


def format_price_card_v117(symbol: str, spot: dict | None, fetch_ms: int,
                           mexc_px: float | None, last_px: float | None,
                           last_src: str, last_age_s: float | None,
                           trend: dict | None = None) -> str:
    """v118 karta: sodda, emoji bilan, bir qarashda narx + trend."""
    sym = str(symbol or "").upper().replace("USDT", "/USD")
    lines = []
    if spot:
        mid = float(spot["mid"])
        lines.append("\U0001F4B0 <b>" + sym + "</b>")
        lines.append("")
        lines.append("     \U0001F31F <b>" + _fmt_px(mid) + "</b> $")
        lines.append("     \U0001F7E2 sotish:  " + _fmt_px(spot["bid"]))
        lines.append("     \U0001F534 sotib olsangiz: " + _fmt_px(spot["ask"]))
        lines.append("")
        if trend:
            d, sec = float(trend["delta"]), max(1, int(trend["seconds"]))
            if sec >= 60:
                span = f"{sec // 60} daqiqada"
            else:
                span = f"{sec} soniyada"
            if trend["dir"] > 0:
                lines.append(f"\U0001F4C8 <b>O'SYAPTI</b>: {d:+.2f}$ ({span})")
            elif trend["dir"] < 0:
                lines.append(f"\U0001F4C9 <b>TUSHYAPTI</b>: {d:+.2f}$ ({span})")
            else:
                lines.append(f"\u23F8 <b>barqaror</b>: {d:+.2f}$ ({span})")
        else:
            lines.append("\u23F3 trend: bir ozdan keyin ko'rinadi...")
    else:
        lines.append("\u26A0 spot vaqtincha yo'q \u2014 MEXC zaxirada:")
        if mexc_px and float(mexc_px) > 0:
            lines.append("     \U0001F4B2 <b>" + _fmt_px(mexc_px) + "</b> $")
            lines.append("     (MEXC odatda spotdan +6$ tepada yuradi)")
    now_t = datetime.now(timezone.utc) + timedelta(hours=5)
    lines.append("")
    lines.append("\U0001F551 " + now_t.strftime("%H:%M:%S") + " Toshkent")
    lines.append("MT5 bilan 0.05\u20130.30$ farq normal")
    return "\n".join(lines)
