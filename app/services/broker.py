"""v74: BROKER ULANISHI (MetaTrader 5 — demo va real).

Bot Render'da (Linux) ishlaydi, MT5 terminal esa foydalanuvchining Windows
kompyuterida. Shuning uchun aloqa "ko'prik" (bridge) orqali:
  • bot  -> navbatga buyruq qo'yadi (OPEN / CLOSE);
  • kompyuterdagi `mt5_bridge.py` navbatni olib (pull), MT5 da bajarib,
    natijani qaytaradi (ack) va hisob holatini yuboradi (report).

Ma'lumot SystemLog ichida saqlanadi (kanallar/statistika kabi):
  component "broker"     -> ulanish sozlamalari (kind/login/parol/server/token)
  component "broker_out" -> buyruqlar navbati va natijalari
"""
from __future__ import annotations

import base64
import json
import secrets
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.database.models.system import SystemLog

logger = get_logger(__name__)

COMPONENT = "broker"
OUT_COMPONENT = "broker_out"

KINDS = ("demo", "real")
ACTIONS = ("OPEN", "CLOSE", "MODIFY")
OUT_CAP = 200          # navbatda saqlanadigan oxirgi buyruqlar
RESEND_AFTER = 120.0   # sekund: yuborilgan, lekin tasdiqlanmagan buyruq qayta yuboriladi
STALE_AFTER = 120.0    # sekund: shu vaqtdan ko'p javob bo'lmasa — "aloqa yo'q"


# ------------------------------------------------------------------ yordamchi
async def _load(session: AsyncSession, component: str) -> dict:
    row = await session.scalar(
        select(SystemLog).where(SystemLog.component == component)
        .order_by(SystemLog.id.desc()).limit(1)
    )
    if not row or not row.message:
        return {}
    try:
        data = json.loads(row.message)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


async def _save(session: AsyncSession, component: str, data: dict) -> None:
    payload = json.dumps(data, ensure_ascii=False)
    row = await session.scalar(
        select(SystemLog).where(SystemLog.component == component)
        .order_by(SystemLog.id.desc()).limit(1)
    )
    if row:
        row.message = payload
    else:
        session.add(SystemLog(level="INFO", component=component, message=payload))
    await session.commit()


def new_token() -> str:
    return secrets.token_hex(12)


def _enc(pwd: str) -> str:
    return base64.b64encode((pwd or "").encode("utf-8")).decode()


def _dec(enc: str) -> str:
    try:
        return base64.b64decode((enc or "").encode()).decode("utf-8")
    except Exception:  # noqa: BLE001
        return ""


def mask_login(login: str | None) -> str:
    s = str(login or "")
    if len(s) <= 4:
        return s or "—"
    return s[:2] + "*" * (len(s) - 4) + s[-2:]


def kind_label(kind: str | None) -> str:
    return "DEMO (sinov hisobi)" if (kind or "").lower() != "real" else "REAL (haqiqiy hisob)"


# ------------------------------------------------------------------ sozlama
async def load_cfg(session: AsyncSession) -> dict:
    return await _load(session, COMPONENT)


async def save_cfg(session: AsyncSession, *, kind: str, login: str, password: str,
                   server: str, user_id: int | None = None, label: str = "") -> dict:
    """Broker ma'lumotlarini saqlaydi (parol base64 — fon ko'rinishida)."""
    old = await load_cfg(session)
    k = (kind or "demo").lower()
    cfg = {
        "kind": k if k in KINDS else "demo",
        "login": str(login or "").strip(),
        "password": _enc(password or ""),
        "server": str(server or "").strip(),
        "label": str(label or "").strip(),
        "token": old.get("token") or new_token(),
        "user_id": int(user_id if user_id is not None else (old.get("user_id") or 0)),
        "created_at": old.get("created_at") or datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": "kutish",
        "last_seen": 0.0,
        "balance": float(old.get("balance") or 0.0),
        "equity": float(old.get("equity") or 0.0),
        "positions": [],
        "bridge_ver": str(old.get("bridge_ver") or ""),
        "last_error": "",
    }
    await _save(session, COMPONENT, cfg)
    logger.info("[BRK] ulanish saqlandi: %s login=%s", cfg["kind"], mask_login(cfg["login"]))
    return cfg


async def clear(session: AsyncSession) -> None:
    await _save(session, COMPONENT, {})
    logger.info("[BRK] ulanish o'chirildi")


async def rotate_token(session: AsyncSession) -> str:
    cfg = await load_cfg(session)
    if not cfg:
        return ""
    cfg["token"] = new_token()
    cfg["updated_at"] = datetime.now(timezone.utc).isoformat()
    await _save(session, COMPONENT, cfg)
    return cfg["token"]


def creds(cfg: dict) -> dict:
    """Ko'prikka beriladigan ma'lumot (parol ochiq — faqat token bilan olinadi)."""
    return {
        "kind": cfg.get("kind") or "demo",
        "login": cfg.get("login") or "",
        "password": _dec(cfg.get("password") or ""),
        "server": cfg.get("server") or "",
        "symbol_suffix": cfg.get("symbol_suffix") or "",
    }


def is_ready(cfg: dict | None) -> bool:
    cfg = cfg or {}
    return bool(cfg.get("token") and cfg.get("login") and cfg.get("password"))


def owner_id(cfg: dict | None) -> int:
    try:
        return int((cfg or {}).get("user_id") or 0)
    except (TypeError, ValueError):
        return 0


def link_state(cfg: dict | None) -> str:
    """Aloqa holati: 'ulangan' / 'aloqa yo`q' / 'ulanmagan'."""
    cfg = cfg or {}
    if not cfg.get("login"):
        return "ulanmagan"
    seen = float(cfg.get("last_seen") or 0.0)
    if seen and (time.time() - seen) <= STALE_AFTER:
        return "ulangan"
    if seen:
        return "aloqa yo'q"
    return "ko'prik kutilmoqda"


def status_text(cfg: dict | None) -> str:
    from app.core.timeuz import format_tashkent

    cfg = cfg or {}
    if not cfg.get("login"):
        return ("🏦 <b>BROKER ULANMAGAN</b>\n"
                "Ulash uchun: /broker yoki «🏦 Broker» tugmasi.")
    st = link_state(cfg)
    icon = {"ulangan": "🟢", "aloqa yo'q": "🟠",
            "ko'prik kutilmoqda": "🟡"}.get(st, "⚪️")
    lines = [
        "🏦 <b>BROKER (MetaTrader 5)</b>",
        "━━━━━━━━━━━━━━━━",
        f"Hisob turi: <b>{kind_label(cfg.get('kind'))}</b>",
        f"Login: <code>{mask_login(cfg.get('login'))}</code> · Server: {cfg.get('server') or '—'}",
        f"{icon} Aloqa: <b>{st}</b>",
    ]
    if cfg.get("last_seen"):
        try:
            _seen_dt = datetime.fromtimestamp(float(cfg["last_seen"]), tz=timezone.utc)
            lines.append(f"⏱ Oxirgi aloqa: {format_tashkent(_seen_dt)}")
        except Exception:  # noqa: BLE001
            pass
    if cfg.get("balance"):
        lines.append(f"💵 Broker balansi: <b>{float(cfg['balance']):,.2f}$</b>")
        lines.append(f"📊 Equity: <b>{float(cfg.get('equity') or 0):,.2f}$</b>")
    pos = cfg.get("positions") or []
    if pos:
        lines.append(f"📂 Brokerda ochiq pozitsiya: <b>{len(pos)}</b>")
    pend = int(cfg.get("pending") or 0)
    if pend:
        lines.append(f"📤 Yuborilmagan buyruq: <b>{pend}</b>")
    if cfg.get("last_error"):
        lines.append(f"⚠️ Xato: {str(cfg['last_error'])[:120]}")
    return "\n".join(lines)


# ------------------------------------------------------------------ navbat
async def _load_out(session: AsyncSession) -> dict:
    data = await _load(session, OUT_COMPONENT)
    items = data.get("items")
    return {"seq": int(data.get("seq") or 0), "items": items if isinstance(items, list) else []}


async def _save_out(session: AsyncSession, data: dict) -> None:
    items = list(data.get("items") or [])
    if len(items) > OUT_CAP:
        data = {"seq": data.get("seq") or 0, "items": items[-OUT_CAP:]}
    await _save(session, OUT_COMPONENT, data)


async def enqueue(session: AsyncSession, action: str, **fields) -> int:
    """Buyruqni navbatga qo'yadi (OPEN / CLOSE). id qaytaradi."""
    act = str(action or "").upper()
    if act not in ACTIONS:
        logger.warning("[BRK] noma'lum amal: %s", action)
        return 0
    out = await _load_out(session)
    out["seq"] = int(out.get("seq") or 0) + 1
    item = {
        "id": out["seq"],
        "action": act,
        "created_at": time.time(),
        "state": "new",
        "attempts": 0,
        "ticket": 0,
        "price": 0.0,
        "error": "",
    }
    for k, v in (fields or {}).items():
        if v is not None:
            item[k] = v
    out["items"].append(item)
    await _save_out(session, out)
    logger.info("[BRK] navbatga: %s #%s %s", act, item["id"], fields)
    return int(item["id"])


def _sort_key(item: dict) -> float:
    try:
        return float(item.get("created_at") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def pending_items(out: dict, *, resend_after: float = RESEND_AFTER) -> list[dict]:
    """Hali bajarilmagan buyruqlar (yuborilgani eskirgan bo'lsa qayta yuboriladi)."""
    now = time.time()
    res: list[dict] = []
    for it in out.get("items") or []:
        st = str(it.get("state") or "new")
        if st in ("done", "failed"):
            continue
        if st == "sent" and (now - float(it.get("sent_at") or 0.0)) < resend_after:
            continue
        res.append(it)
    res.sort(key=_sort_key)
    return res[:20]


async def pull(session: AsyncSession, token: str) -> dict:
    """Ko'prik navbatni oladi (token bilan). Shu payt buyruqlar 'sent' bo'ladi."""
    cfg = await load_cfg(session)
    if not is_ready(cfg) or not token or token != cfg.get("token"):
        return {"ok": False, "error": "token noto'g'ri"}
    out = await _load_out(session)
    items = pending_items(out)
    now = time.time()
    ids = {int(i["id"]) for i in items}
    for it in out["items"]:
        if int(it.get("id") or 0) in ids:
            it["state"] = "sent"
            it["sent_at"] = now
            it["attempts"] = int(it.get("attempts") or 0) + 1
    if ids:
        await _save_out(session, out)
    return {
        "ok": True,
        "server_time": now,
        "creds": creds(cfg),
        "items": [dict(i) for i in items],
    }


async def ack(session: AsyncSession, token: str, results: list[dict]) -> dict:
    """Ko'prik natijalarni qaytaradi: ticket / narx / xato."""
    cfg = await load_cfg(session)
    if not is_ready(cfg) or not token or token != cfg.get("token"):
        return {"ok": False, "error": "token noto'g'ri"}
    out = await _load_out(session)
    by_id = {int(i.get("id") or 0): i for i in out["items"]}
    done = err = 0
    for r in results or []:
        try:
            rid = int(r.get("id") or 0)
        except (TypeError, ValueError):
            continue
        it = by_id.get(rid)
        if not it:
            continue
        if r.get("ok"):
            it["state"] = "done"
            it["ticket"] = int(r.get("ticket") or 0)
            it["price"] = float(r.get("price") or 0.0)
            it["error"] = ""
            done += 1
        else:
            it["state"] = "failed"
            it["error"] = str(r.get("error") or "")[:160]
            err += 1
    await _save_out(session, out)
    if done or err:
        logger.info("[BRK] natija: %d bajarildi, %d xato", done, err)
    return {"ok": True, "done": done, "failed": err}


async def report(session: AsyncSession, token: str, **data) -> dict:
    """Ko'prikdan hisob holati (balans/equity/pozitsiyalar/xato)."""
    cfg = await load_cfg(session)
    if not is_ready(cfg) or not token or token != cfg.get("token"):
        return {"ok": False, "error": "token noto'g'ri"}
    cfg["last_seen"] = time.time()
    cfg["status"] = "ulangan"
    if "balance" in data:
        cfg["balance"] = float(data.get("balance") or 0.0)
    if "equity" in data:
        cfg["equity"] = float(data.get("equity") or 0.0)
    if "positions" in data:
        pos = data.get("positions") or []
        cfg["positions"] = pos if isinstance(pos, list) else []
    if "bridge_ver" in data:
        cfg["bridge_ver"] = str(data.get("bridge_ver") or "")[:20]
    cfg["last_error"] = str(data.get("error") or "")[:200]
    await _save(session, COMPONENT, cfg)
    return {"ok": True}


async def summary(session: AsyncSession) -> dict:
    """Qisqa holat (bot kartasi uchun)."""
    cfg = await load_cfg(session)
    out = await _load_out(session)
    cfg = dict(cfg or {})
    cfg["pending"] = len(pending_items(out))
    cfg["queue"] = len(out.get("items") or [])
    return cfg
