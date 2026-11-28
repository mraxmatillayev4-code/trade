"""v117: OLTIN USD spot narx (Swissquote javon kvotasi) — broker bilan bir xil.

Sababa: MEXC `XAU_USDT` indexPrice USD emas, USDT da kvotalanadi — USDT
premiyasi sabab spot USD dan ~+6$ (0.15%) yuqori yuradi. Bot zona/SL/TP ni
shu noto'g'ri narxlarga o'lchardi.

Manba: forex-data-feed.swissquote.com — bid/ask (broker darajalari bilan
deyarli bir xil; farq odatda 0.05–0.30$).

API:
  fetch_spot() -> dict(bid, ask, mid, ts_ms, src) | None
  fetch_mid()  -> float | None          — mid = (bid+ask)/2
  adjust_df(df, offset) -> df           — sham ustunlarini offsetga surish
                                          (MEXC keshdagi kamlar spotga tekislanadi)
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("spot_quote")

URL = ("https://forex-data-feed.swissquote.com/public-quotes/bboquotes/"
       "instrument/XAU/USD")

_CLIENT = None
_CACHE: dict = {"ts": 0.0, "data": None}
CACHE_S = 1.4          # tez tik 2 s da — manbani bezovta qilmaymiz


async def _client():
    global _CLIENT
    if _CLIENT is None or _CLIENT.closed:
        import aiohttp
        _CLIENT = aiohttp.ClientSession()
    return _CLIENT


def parse_bbo(payload: list) -> dict | None:
    """Javob massividan median bid/ask/mid ni ajratadi (sofa funksiya)."""
    bids, asks = [], []
    ts_ms = 0
    if isinstance(payload, list):
        for item in payload:
            try:
                ts_ms = max(ts_ms, int(item.get("ts") or 0))
                for pr in (item.get("spreadProfilePrices") or []):
                    b = float(pr.get("bid") or 0.0)
                    a = float(pr.get("ask") or 0.0)
                    if b > 0 and a > 0 and a >= b:
                        bids.append(b)
                        asks.append(a)
            except Exception:  # noqa: BLE001
                continue
    if not bids:
        return None
    bids.sort()
    asks.sort()
    mid_b = bids[len(bids) // 2]
    mid_a = asks[len(asks) // 2]
    mid = round((mid_b + mid_a) / 2.0, 3)
    return {"bid": round(mid_b, 3), "ask": round(mid_a, 3), "mid": mid,
            "ts_ms": ts_ms, "src": "swissquote"}


async def fetch_spot(force: bool = False) -> dict | None:
    """Jonli spot kvota (1.4 s kesh bilan). Xato/eskirsa — None."""
    now = time.monotonic()
    if not force and _CACHE["data"] and (now - _CACHE["ts"]) < CACHE_S:
        return _CACHE["data"]
    try:
        client = await _client()
        async with client.get(URL, timeout=6.0) as resp:
            if resp.status != 200:
                logger.warning("[SPOT] HTTP %s", resp.status)
                return None
            payload = await resp.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[SPOT] tarmoq: %s", type(exc).__name__)
        return None
    data = parse_bbo(payload)
    if data:
        _CACHE["ts"] = now
        _CACHE["data"] = data
        _note_hist(data["mid"])
    return data


async def fetch_mid() -> float | None:
    q = await fetch_spot()
    return float(q["mid"]) if q else None


def adjust_df(df, offset: float):
    """Sham narx ustunlarini offsetga suradi (nusxa qaytaradi).

    MEXC sham kesha USDT-premiya bilan saqlanadi; trekerga berganda
    spot-MEXC farqiga surib, shakl (momentum) saqlangan, darajalar esa
    REAL (spot) bo'lgan ramka olamiz.
    """
    if df is None or not offset:
        return df
    try:
        out = df.copy()
        for col in ("open", "high", "low", "close"):
            if col in out.columns:
                out[col] = out[col].astype(float) + float(offset)
        return out
    except Exception:  # noqa: BLE001
        return df


def last_spot(max_age_s: float = 10.0) -> dict | None:
    """Sinxron: oxirgi olingan spot kvota (keshdan, yangi bo'lsa).

    Async bo'la olmaydigan joylar (_last_px kabi) shuni ishlatadi —
    keshni tez tik / price_for davomiy qizdirib turadi.
    """
    try:
        d = _CACHE.get("data")
        if d and (time.monotonic() - _CACHE.get("ts", 0.0)) < float(max_age_s):
            return d
    except Exception:  # noqa: BLE001
        pass
    return None


# ---------- v118: TREND (oxirgi ~1-2 daqiqada o'syaptimi/tushyaptimi) ----------

import collections as _coll

_HIST = _coll.deque(maxlen=200)   # (monotonic_s, mid) — ~4-6 daqiqalik deraza


def _note_hist(mid: float) -> None:
    try:
        _HIST.append((time.monotonic(), float(mid)))
    except Exception:  # noqa: BLE001
        pass


def spot_trend() -> dict | None:
    """So'nggi harakat xulosasi: {'dir':1/-1/0,'delta':$,'seconds':s}.

    dir: +1 o'syapti (delta>+0.04$), -1 tushyapti (<-0.04$), 0 barqaror.
    Baza — eng so'nggi 45+ soniya oldingi namuna; bo'lmasa eng eskisi.
    Kamida 2 namuna kerak, aks holda None (bot endi yoqilgan)."""
    h = list(_HIST)
    if len(h) < 2:
        return None
    now, cur = h[-1]
    base = base_ts = None
    for ts, m in reversed(h[:-1]):
        if ts <= now - 45.0:
            base, base_ts = m, ts
            break
    if base is None:
        base_ts, base = h[0]
    d = round(cur - base, 2)
    return {"dir": 1 if d > 0.04 else (-1 if d < -0.04 else 0),
            "delta": d, "seconds": max(1.0, now - base_ts),
            "cur": cur, "base": base}


def _reset_hist() -> None:
    _HIST.clear()
