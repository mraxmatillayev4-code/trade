"""v82: AKKАUNT va KANALLAR SAQLANIB QOLISHI (persist guard).

Muammo: yangilanishdan keyin (yoki baza almashganda — masalan Render'ning
bepul PostgreSQL muddati tugab yangisi yaratilganda) ulangan Telegram akkaunt
sessiyasi va kanallar ro'yxati yo'qolib qolgan edi — hammasini qaytadan
ulash kerak bo'lardi.

Yechim: har ishga tushishda va har o'zgarishda sessiya + kanallar ro'yxati
zaxira (guard) sifatida alohida saqlanadi va kerak bo'lsa O'ZI tiklaydi:

  * guard: SystemLog(component='persist_guard') — sessiya, api_id/hash, kanallar;
  * `restore_if_missing()` — akkaunt/kanal bo'sh bo'lsa guard'dan tiklaydi;
  * `backup_file()` — `/zaxira` buyrug'i beradigan JSON fayl (qo'lda tiklash);
  * qo'lda tiklash: faylni botga yuborish (handler `persist.py`).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.core.logging import get_logger
from app.database.session import async_session_factory

logger = get_logger(__name__)

GUARD_COMPONENT = "persist_guard"
BACKUP_NAME = "sino_zaxira.json"


async def snapshot() -> dict:
    """Sessiya + kanallar + api kalitlarini yig'adi."""
    from app.services.channel_store import (
        API_COMPONENT,
        SESSION_COMPONENT,
        list_channels,
        load_json_log,
    )
    out: dict = {"version": 82, "ts": datetime.now(timezone.utc).isoformat()}
    try:
        async with async_session_factory() as s:
            chans = await list_channels(s)      # ro'yxat (list) shu yerdan olinadi
            sess = await load_json_log(s, SESSION_COMPONENT)
            api = await load_json_log(s, API_COMPONENT)
        out["channels"] = chans if isinstance(chans, list) else []
        out["session"] = str(sess.get("session") or "") if isinstance(sess, dict) else ""
        out["api_id"] = str(api.get("api_id") or "") if isinstance(api, dict) else ""
        out["api_hash"] = str(api.get("api_hash") or "") if isinstance(api, dict) else ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PERSIST] snapshot: %s", exc)
    return out


async def save_guard(force: bool = False) -> dict:
    """Guard'ni yangilaydi (faqat mazmunli ma'lumot bo'lsa)."""
    from app.services.channel_store import save_json_log
    snap = await snapshot()
    if not (snap.get("session") or snap.get("channels")):
        return snap
    try:
        async with async_session_factory() as s:
            await save_json_log(s, GUARD_COMPONENT, snap)
        logger.info("[PERSIST] guard saqlandi: sessiya=%s kanallar=%d",
                    bool(snap.get("session")), len(snap.get("channels") or []))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PERSIST] guard saqlanmadi: %s", exc)
    return snap


async def load_guard() -> dict:
    from app.services.channel_store import load_json_log
    try:
        async with async_session_factory() as s:
            data = await load_json_log(s, GUARD_COMPONENT)
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PERSIST] guard o'qilmadi: %s", exc)
        return {}


async def restore_if_missing() -> str:
    """Akkaunt/kanallar yo'qolgan bo'lsa guard'dan tiklaydi. Hisobot qaytaradi."""
    guard = await load_guard()
    if not guard:
        return ""
    now = await snapshot()
    fixed: list[str] = []
    # 1) sessiya
    if not now.get("session") and guard.get("session"):
        try:
            from app.services.channel_user import save_session
            await save_session(str(guard["session"]))
            fixed.append("akkaunt sessiyasi")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[PERSIST] sessiya tiklanmadi: %s", exc)
    # 2) api kalitlar
    if (not now.get("api_id") or not now.get("api_hash")) and guard.get("api_id"):
        try:
            from app.services.channel_store import API_COMPONENT, save_json_log
            async with async_session_factory() as s:
                await save_json_log(s, API_COMPONENT, {
                    "api_id": str(guard.get("api_id") or ""),
                    "api_hash": str(guard.get("api_hash") or ""),
                })
            fixed.append("api_id/api_hash")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[PERSIST] api tiklanmadi: %s", exc)
    # 3) kanallar
    saved = guard.get("channels") or []
    have = now.get("channels") or []
    if saved and len(have) < len(saved):
        try:
            from app.services.channel_store import add_channel
            added = 0
            keys = {str(c.get("username") or c.get("chat_id") or "").lower() for c in have}
            async with async_session_factory() as s:
                for ch in saved:
                    k = str(ch.get("username") or ch.get("chat_id") or "").lower()
                    if not k or k in keys:
                        continue
                    ok, _msg, _row = await add_channel(
                        s, username=(ch.get("username") or None),
                        chat_id=(int(ch["chat_id"]) if ch.get("chat_id") else None),
                        title=str(ch.get("title") or ""),
                        kind=str(ch.get("kind") or "public"),
                    )
                    if ok:
                        added += 1
                        keys.add(k)
            if added:
                fixed.append(f"{added} kanal")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[PERSIST] kanallar tiklanmadi: %s", exc)
    if fixed:
        msg = "🛡 <b>Tiklandi:</b> " + ", ".join(fixed) + " (zaxira nusxadan)"
        logger.warning("[PERSIST] %s", msg)
        return msg
    return ""


async def backup_file() -> tuple[str, bytes]:
    """`/zaxira` uchun JSON fayl (qo'lda tiklash mumkin)."""
    snap = await snapshot()
    data = json.dumps(snap, ensure_ascii=False, indent=1).encode("utf-8")
    return BACKUP_NAME, data


async def restore_from_file(raw: bytes) -> str:
    """Botga yuborilgan zaxira faylidan tiklaydi."""
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        return f"❌ Fayl o'qilmadi: {type(exc).__name__}"
    if not isinstance(data, dict) or "channels" not in data:
        return "❌ Bu zaxira fayli emas (sino_zaxira.json kerak)."
    from app.services.channel_store import API_COMPONENT, save_json_log
    done: list[str] = []
    try:
        if data.get("session"):
            from app.services.channel_user import save_session
            await save_session(str(data["session"]))
            done.append("akkaunt sessiyasi")
        if data.get("api_id"):
            async with async_session_factory() as s:
                await save_json_log(s, API_COMPONENT, {
                    "api_id": str(data.get("api_id") or ""),
                    "api_hash": str(data.get("api_hash") or ""),
                })
            done.append("api kalitlar")
        if data.get("channels"):
            from app.services.channel_store import add_channel
            n = 0
            async with async_session_factory() as s:
                for ch in data["channels"]:
                    ok, _m, _r = await add_channel(
                        s, username=(ch.get("username") or None),
                        chat_id=(int(ch["chat_id"]) if ch.get("chat_id") else None),
                        title=str(ch.get("title") or ""),
                        kind=str(ch.get("kind") or "public"),
                    )
                    n += 1 if ok else 0
            done.append(f"{n} kanal")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PERSIST] fayldan tiklash: %s", exc)
        return f"❌ Tiklashda xato: {type(exc).__name__}: {str(exc)[:120]}"
    await save_guard(force=True)
    if not done:
        return "⚠️ Faylda tiklanadigan ma'lumot yo'q."
    return "✅ <b>Tiklandi:</b> " + ", ".join(done) + ".\n<i>Kanallarni qayta ulash shart emas.</i>"


async def status_line() -> str:
    """Qisqa holat qatori (xabarlar uchun)."""
    snap = await snapshot()
    g = await load_guard()
    ch = len(snap.get("channels") or [])
    gch = len(g.get("channels") or [])
    return (f"🛡 Zaxira: akkaunt {'✅' if snap.get('session') else '—'} · "
            f"kanallar <b>{ch}</b> ta · guard {gch} ta")
