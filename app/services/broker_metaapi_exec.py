"""v119: MetaAPI navbat-ijro aylanmasi — bot o'zi buyruqlarni bajaradi.

Lokal ko'prik (mt5_bridge.py sizning kompyuteringizda) ni almashtiradi:
provider=='metaapi' bo'lsa, Render dagi bot o'zi MetaAPI ga ulanib Navbatdagi
OPEN/CLOSE buyruqlarini bajaradi. Kompyuteringiz o'chiq bo'lsa ham ishlaydi.

Eskirgan-buyruq himoyasi: OPEN 5 daqiqadan oshib qolgan bo'lsa — bajarilmasdan
"eskirgan" deb rad etiladi (kutilmagan yashirin savdo xavfi).
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from app.core.logging import get_logger
from app.services import broker as brk
from app.services.broker_metaapi import MetaApiBridge

logger = get_logger("broker_metaapi_exec")

OPEN_TTL_S = 300.0        # OPEN shu vaqtdan keyin bajarilmaydi (zona moslanmagan)
POLL_S = 2.0

_STATE: dict = {"bridge": None, "key": ""}


def _fresh_bridge(cfg: dict) -> MetaApiBridge | None:
    global _STATE
    key = "|".join([str(cfg.get("api_token") or "")[:8], str(cfg.get("account_id") or "")])
    if _STATE.get("key") == key and _STATE.get("bridge"):
        return _STATE["bridge"]
    if not cfg.get("api_token") or not cfg.get("account_id"):
        return None
    br = MetaApiBridge(cfg["api_token"], cfg["account_id"])
    _STATE = {"bridge": br, "key": key, "last_report": 0.0}
    return br


REPORT_EVERY_S = 30.0


async def _maybe_report(session, cfg, bridge, items_count: int) -> None:
    """Muntazam holat hisoboti — navbat bo'sh ham bo'lsa status yangilanadi."""
    global _STATE
    now = time.time()
    if items_count == 0 and (now - float(_STATE.get("last_report") or 0.0)) < REPORT_EVERY_S:
        return
    try:
        info = await bridge.account_info()
        poss = await bridge.positions()
        await brk.report(
            session, cfg["token"],
            balance=float(info.get("balance") or 0.0),
            equity=float(info.get("balance") or 0.0),
            positions=poss, bridge_ver="metaapi-v119")
        _STATE["last_report"] = now
    except Exception as exc:  # noqa: BLE001
        logger.warning("[METAAPI-EXEC] report: %s", exc)


async def _ack_results(session, token: str, results: list[dict]) -> None:
    try:
        await brk.ack(session, token, results)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[METAAPI-EXEC] ack: %s", exc)


async def cycle_once(session) -> int:
    """Bir aylana: navbatni ko'radi, MetaAPI da bajaradi. Bajarilganlar soni."""
    cfg = await brk.load_cfg(session)
    if not brk.is_metaapi(cfg) or not brk.is_ready(cfg):
        return 0
    bridge = _fresh_bridge(cfg)
    if bridge is None:
        return 0
    # 1) navbat — faqat alohida yuklanmagan, bridge.get nosandalmaisedi
    out = await brk._load_out(session)
    items = brk.pending_items(out)
    if not items:
        await _maybe_report(session, cfg, bridge, 0)
        return 0
    # mark sent to avoid double-processing by local bridge
    await brk.pull(session, cfg["token"])
    now = time.time()
    results: list[dict] = []
    n_done = 0
    for it in items:
        act = str(it.get("action") or "").upper()
        created = float(it.get("created_at") or 0.0)
        if act == "OPEN" and now - created > OPEN_TTL_S:
            results.append({"id": it["id"], "error": "ESKIRGAN (5 daqiqadan oshdi) — bajarilmadi"})
            logger.warning("[METAAPI-EXEC] OPEN #%s ESKIRGAN — rad", it["id"])
            continue
        if act == "OPEN":
            res = await bridge.open_market(
                it.get("symbol"), it.get("side"), float(it.get("lot") or 0.01),
                sl=float(it.get("sl") or 0.0), tp=float(it.get("tp") or 0.0),
                comment=str(it.get("comment") or "SINO"))
            if res.get("ok"):
                results.append({"id": it["id"], "ok": True,
                                "ticket": int(res.get("ticket") or 0),
                                "price": float(res.get("price") or 0.0)})
                n_done += 1
            else:
                results.append({"id": it["id"], "error": str(res.get("error") or "?")})
        elif act == "CLOSE":
            res = await bridge.close_by_comment(
                it.get("symbol"), str(it.get("comment") or "SINO"),
                lot=float(it.get("lot") or 0.0), price=float(it.get("price") or 0.0))
            results.append({"id": it["id"], "price": float(res.get("price") or 0.0),
                            **({"ok": True, "ticket": 0} if res.get("ok") else {"ok": False, "error": str(res.get("error") or "?")})})
            if res.get("ok"):
                n_done += 1
        elif act == "MODIFY":
            # v125: Lot2 stopini TP1 ga sudrash — SL o'zgaruvi REAL akkauntda
            try:
                res = await bridge.modify_sl(
                    it.get("symbol"), str(it.get("comment") or "SINO Lot2"),
                    lot=float(it.get("lot") or 0.0), sl=float(it.get("sl") or 0.0))
                results.append({"id": it["id"], "ok": bool(res.get("ok")),
                                **({"error": str(res.get("error") or "?")} if not res.get("ok") else {})})
                if res.get("ok"):
                    n_done += 1
            except Exception as exc:  # noqa: BLE001
                results.append({"id": it["id"], "error": f"modify: {exc}"[:100]})
        else:
            results.append({"id": it["id"], "error": "noma'lum amal"})
    # 2) natijalarni ack qilamiz
    await _ack_results(session, cfg["token"], results)
    # 3) hisobot (balans, equity, pozitsiyalar) — muntazam yangilanadi
    await _maybe_report(session, cfg, bridge, len(items))
    logger.info("[METAAPI-EXEC] sajra: %d/%d bajarildi", n_done, len(items))
    return n_done


async def loop(session_factory) -> None:
    """MetaAPI ijro aylanmasi — har POLL_S soniyada."""
    logger.info("[METAAPI-EXEC] aylana ishga tushdi (%s s)", POLL_S)
    while True:
        try:
            async with session_factory() as session:
                await cycle_once(session)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("[METAAPI-EXEC] sikl: %s", exc)
        await asyncio.sleep(POLL_S)
