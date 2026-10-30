"""v116: tezkor narx tsikli — zona/SL/TP tekshiruvi 15 soniyalik siklni
KUTMAYDAN, har 2 soniyada (faol signal bo'lmasa 5 s dam).

Narx to'g'ridan-to'g'ri birja tickeridan (MEXC indexPrice) olinadi —
sham keshi chetlab o'tiladi, shuning uchun bozor harakati bilanosigh
(2 s ichida) ko'rinadi: zona tekkasi shu zahoti kirish, SL/TP shu zahoti
yopiladi. Avvalgi 15 s sikl ishlashda davom etadi (momentum/hisobotlar
uchun), bu — faqat tezkor daraja tekshiruvi.
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("fast_tick")

FAST_ACTIVE_S = 2.0    # ochiq signal bor payt
FAST_IDLE_S = 5.0      # hech qanday signal yo'q payt


async def fast_tick_once(*, session_factory, signals_loader, price_fn,
                         tracker, notifier=None) -> dict:
    """Bitta tezkor aylanma: barcha faol signallarni jonli narx bilan tekshiradi.

    signals_loader(session) — shu sessiyadan ochiq signallarni yuklaydi;
    price_fn(symbol) — to'g'ridan-to'g'ri birja tickeri (keshsiz).
    Qaytaradi: {"checked", "filled", "px", "syms", "err"}.
    """
    from app.engine import entry as EN
    out = {"checked": 0, "filled": 0, "px": 0.0, "syms": 0, "err": ""}
    async with session_factory() as session:
        sigs = await signals_loader(session)
        px_cache: dict = {}
        for sig in list(sigs or []):
            try:
                sym = str(getattr(sig, "symbol", "") or "").upper()
                if not sym:
                    continue
                px = float(px_cache.get(sym) or 0.0)
                if px <= 0:
                    try:
                        px = float(await price_fn(sym) or 0.0)
                    except Exception:  # noqa: BLE001
                        px = 0.0
                    if px > 0:
                        px_cache[sym] = px
                if px <= 0:
                    continue
                out["checked"] += 1
                out["px"] = px
                if EN.is_waiting(sig):
                    st = await tracker.entry_tick(
                        session, sig, float(px), notifier=notifier)
                    if st == "filled":
                        out["filled"] += 1
                else:
                    # df=None → jonli narxning o'zi "sham" bo'lib tekshiriladi:
                    # SL/TP yopilishini sham yopilishini kutmaysiz.
                    await tracker.live_tick(
                        session, sig, float(px), df=None, notifier=notifier)
                    try:
                        from app.services import watchdog as _wd
                        _wd.note_price(sym, float(px), "tez tik")
                    except Exception:  # noqa: BLE001
                        pass
            except Exception as exc:  # noqa: BLE001
                out["err"] = str(exc)[:120]
                logger.debug("[FAST] #%s: %s", getattr(sig, "id", "?"), exc)
        out["syms"] = len(px_cache)
    return out


async def fast_tick_loop(*, session_factory, signals_loader, price_fn,
                         tracker, notifier=None) -> None:
    """Doimiy tsikl: signal bor — 2 s da tekshiruv; yo'q — 5 s dam."""
    await asyncio.sleep(12)  # bot to'liq turg'unashguncha kutamiz
    while True:
        checked = 0
        try:
            res = await fast_tick_once(
                session_factory=session_factory, signals_loader=signals_loader,
                price_fn=price_fn, tracker=tracker, notifier=notifier)
            checked = int(res.get("checked") or 0)
            if res.get("err"):
                logger.debug("[FAST] oxirgi ichki xato: %s", res["err"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("[FAST] sikl: %s", exc)
        await asyncio.sleep(FAST_ACTIVE_S if checked else FAST_IDLE_S)
