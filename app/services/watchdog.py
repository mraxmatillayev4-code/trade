"""v81: BOZOR KUZATUVI SOG'LIGI (nazorat qo'riqchisi).

Muammo: narx oqimi (WebSocket/REST) uzilib qolsa yoki sham kelmay qolsa,
kuzatuv "jimgina" to'xtab qoladi — natijada SL/TP vaqtida hisoblanmaydi va
signal ochiq qolib ketadi. Bu modul buni darhol aniqlaydi:

  * oxirgi sham qachon kelgani va qancha KECHIKAYOTGANI,
  * narx manbasi (WS / REST / MEXC) oxirgi marta qachon javob bergani,
  * ochiq signal bor va kuzatuv to'xtagan bo'lsa — bir marta ogohlantirish,
  * oqim tiklanganda — "kuzatuv tiklandi" xabari.

Hech qanday tashqi kalit talab qilinmaydi — faqat botning o'z holati.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.core.logging import get_logger

logger = get_logger(__name__)

# (symbol, tf) -> {"at": oxirgi qayta ishlangan vaqt, "open": sham open_time}
_candles: dict[tuple[str, str], dict] = {}
# symbol -> {"price": float, "at": datetime, "source": str}
_prices: dict[str, dict] = {}

# ogohlantirish holati: "sym|tf|level" -> True
_alerted: dict[str, bool] = {}
_ALERT_REPEAT_SEC = 1800     # bir ogohlantirishni 30 daqiqada bir martadan ko'p yubormaymiz
_started_at = datetime.now(timezone.utc)

_TF_SEC = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400,
}


def tf_seconds(tf: str) -> int:
    return _TF_SEC.get(str(tf or "1m").lower(), 60)


def note_candle(symbol: str, tf: str, open_time=None, price: float | None = None,
                at: datetime | None = None) -> None:
    """Sham qayta ishlanganini yozib qo'yamiz (kuzatuv tirikligi)."""
    key = (str(symbol or "").upper(), str(tf or "").lower())
    _candles[key] = {
        "at": at or datetime.now(timezone.utc),
        "open": open_time,
        "price": price,
    }


def note_price(symbol: str, price: float | None, source: str = "") -> None:
    """Narx manbasi javob berganini yozib qo'yamiz."""
    try:
        px = float(price) if price is not None else 0.0
    except (TypeError, ValueError):
        px = 0.0
    if px <= 0:
        return
    _prices[str(symbol or "").upper()] = {
        "price": px, "at": datetime.now(timezone.utc), "source": source or "",
    }


def candle_lag(symbol: str, tf: str) -> float | None:
    """Oxirgi sham qayta ishlanganidan beri o'tgan SEKUND."""
    rec = _candles.get((str(symbol or "").upper(), str(tf or "").lower()))
    if not rec:
        return None
    return (datetime.now(timezone.utc) - rec["at"]).total_seconds()


def price_age(symbol: str) -> float | None:
    rec = _prices.get(str(symbol or "").upper())
    if not rec:
        return None
    return (datetime.now(timezone.utc) - rec["at"]).total_seconds()


def last_price(symbol: str) -> tuple[float | None, float | None, str]:
    rec = _prices.get(str(symbol or "").upper())
    if not rec:
        return None, None, ""
    return float(rec["price"]), price_age(symbol), str(rec.get("source") or "")


def _fmt_age(sec: float | None) -> str:
    if sec is None:
        return "—"
    sec = max(0.0, float(sec))
    if sec < 90:
        return f"{int(sec)} soniya"
    if sec < 5400:
        return f"{int(sec // 60)} daqiqa"
    return f"{sec / 3600:.1f} soat"


def _level(symbol: str, tf: str, open_symbols: set[str]) -> tuple[str, str]:
    """OK / KECHIKDI / TO'XTADI + matn."""
    lag = candle_lag(symbol, tf)
    if lag is None:
        return "KUTILMOQDA", "sham hali kelmadi"
    expect = tf_seconds(tf)
    if str(symbol).upper() not in open_symbols:
        # ochiq signal yo'q — jim turamiz (faqat aniq nosozlik yoziladi)
        if lag > max(1200.0, 6 * expect):
            return "TO'XTADI", f"oxirgi sham {_fmt_age(lag)} oldin"
        return "OK", f"oxirgi sham {_fmt_age(lag)} oldin"
    if lag > max(900.0, 6 * expect):
        return "TO'XTADI", f"oxirgi sham {_fmt_age(lag)} oldin"
    if lag > max(180.0, 3 * expect):
        return "KECHIKDI", f"oxirgi sham {_fmt_age(lag)} oldin"
    return "OK", f"oxirgi sham {_fmt_age(lag)} oldin"


def status_lines(symbols: list[str] | None = None,
                 timeframes: list[str] | None = None,
                 open_symbols: set[str] | None = None) -> list[str]:
    """Kuzatuv holati: narx manbasi + sham rejimi (hisobot/handlerlar uchun)."""
    open_symbols = open_symbols or set()
    out: list[str] = []
    syms = [str(s).upper() for s in (symbols or [])]
    tfs = [str(t).lower() for t in (timeframes or ["1m"])]
    px, age, src = (None, None, "")
    for s in syms:
        p, a, sc = last_price(s)
        if p is not None:
            px, age, src = p, a, (sc or "")
            break
    if px is not None:
        out.append(f"💹 Narx: <b>{px:,.2f}</b> ({src or 'manba'}, {_fmt_age(age)} oldin)")
    else:
        out.append("💹 Narx: <b>hali olinmadi</b>")
    for s in syms:
        for tf in tfs:
            lvl, why = _level(s, tf, open_symbols)
            icon = {"OK": "🟢", "KECHIKDI": "🟡", "TO'XTADI": "🔴"}.get(lvl, "⚪")
            out.append(f"{icon} {s} {tf.upper()}: <b>{lvl}</b> — {why}")
    if not out:
        out.append("⚪ Ma'lumot yo'q")
    return out


def is_ok(symbol: str, tf: str, open_symbols: set[str] | None = None) -> bool:
    lvl, _ = _level(symbol, tf, open_symbols or set())
    return lvl == "OK"


async def check(notifier=None, symbols: list[str] | None = None,
                timeframes: list[str] | None = None,
                open_symbols: set[str] | None = None) -> list[str]:
    """Har daqiqada chaqiriladi: kuzatuv to'xtagan bo'lsa ogohlantiradi.

    Qaytaradi: yuborilgan ogohlantirishlar ro'yxati (matn).
    """
    sent: list[str] = []
    if notifier is None:
        return sent
    open_symbols = {str(s).upper() for s in (open_symbols or set())}
    syms = [str(s).upper() for s in (symbols or [])]
    tfs = [str(t).lower() for t in (timeframes or ["1m"])]
    # ishga tushgandan keyin 3 daqiqa "qizish" vaqti
    if (datetime.now(timezone.utc) - _started_at).total_seconds() < 180:
        return sent
    for s in syms:
        for tf in tfs:
            lvl, why = _level(s, tf, open_symbols)
            key = f"{s}|{tf}"
            prev = _alerted.get(key)
            if lvl in ("KECHIKDI", "TO'XTADI"):
                last_at = _alerted.get(key + "|at")
                now = datetime.now(timezone.utc)
                if last_at is not None and (now - last_at).total_seconds() < _ALERT_REPEAT_SEC:
                    continue
                _alerted[key + "|at"] = now
                _alerted[key] = True
                has_sig = s in open_symbols
                txt = (
                    f"⚠️ <b>BOZOR KUZATUVI {lvl}</b> — {s} {tf.upper()}\n"
                    f"Sabab: {why}.\n"
                    + ("<b>Ochiq signal bor</b> — SL/TP hisobi kechikmoqda.\n" if has_sig else "")
                    + "<i>Narx oqimi uzilgan bo'lishi mumkin (WS/REST). Bot qayta "
                    "ulanadi; baribir ochiq signal muddati tugasa bozor narxida "
                    "yopiladi.</i>"
                )
                try:
                    await notifier.send_event(txt)
                    sent.append(txt)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[WATCHDOG] ogohlantirish yuborilmadi: %s", exc)
            elif lvl == "OK" and prev:
                _alerted[key] = False
                _alerted.pop(key + "|at", None)
                txt = (f"✅ <b>Kuzatuv tiklandi</b> — {s} {tf.upper()} "
                       f"({why}).")
                try:
                    await notifier.send_event(txt)
                    sent.append(txt)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[WATCHDOG] tiklash xabari: %s", exc)
    return sent


def snapshot() -> dict:
    now = datetime.now(timezone.utc)
    return {
        "candles": {f"{k[0]} {k[1]}": v["at"].isoformat() for k, v in _candles.items()},
        "prices": {k: {"price": v["price"], "age_s": (now - v["at"]).total_seconds(),
                       "source": v.get("source")} for k, v in _prices.items()},
        "uptime_s": (now - _started_at).total_seconds(),
    }
