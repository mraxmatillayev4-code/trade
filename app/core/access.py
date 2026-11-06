"""Admin vs oddiy foydalanuvchi.

ADMIN_IDS (.env) + SystemLog('admins') — yangi jadval yo'q.
Agar hech kim yo'q bo'lsa, birinchi /start bosgan odam admin bo'ladi.
"""
from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

ADMIN_COMPONENT = "admins"
_extra: set[int] = set()
_hydrated = False


def is_admin(user_id: int | None) -> bool:
    if not user_id:
        return False
    uid = int(user_id)
    if uid in get_settings().admin_id_list:
        return True
    return uid in _extra


async def hydrate_admins() -> None:
    global _hydrated, _extra
    try:
        from app.database.session import async_session_factory
        from app.services.channel_store import load_json_log
        async with async_session_factory() as session:
            data = await load_json_log(session, ADMIN_COMPONENT)
        ids: set[int] = set()
        for x in data.get("ids") or []:
            try:
                ids.add(int(x))
            except (TypeError, ValueError):
                pass
        _extra = ids
        _hydrated = True
        logger.info("[ADMIN] env=%s db=%s", get_settings().admin_id_list, list(_extra))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ADMIN] hydrate: %s", exc)
        _hydrated = True


async def claim_admin(user_id: int | None) -> bool:
    """Admin bo'lsa True. Hech kim yo'q bo'lsa — shu user admin."""
    if not user_id:
        return False
    uid = int(user_id)
    if not _hydrated:
        await hydrate_admins()
    if is_admin(uid):
        return True
    if get_settings().admin_id_list or _extra:
        return False
    _extra.add(uid)
    try:
        from app.database.session import async_session_factory
        from app.services.channel_store import save_json_log
        async with async_session_factory() as session:
            await save_json_log(session, ADMIN_COMPONENT, {"ids": [uid]})
        logger.info("[ADMIN] birinchi foydalanuvchi admin: %s", uid)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ADMIN] saqlash: %s", exc)
    return True


# ======================= v121: ADMIN BOSHQARUVI =======================
# SUPER-ADMIN = env ADMIN_IDS ichidagi birinchi ID (yoki DB da saqlanganlar
# ichidan birinchi) — uni HECH KIM o'chira OLMAYDI (qalqon). Qolgan adminlar
# hamma ishni qila oladi, lekin super-adminni o'chira olmaydi.
# Qo'shish/o'chirish FAQAT super-admin dan. Har bir harakat — audit xabari.

def super_admin_id() -> int | None:
    """Birinchi (asosiy) admin — himoyada."""
    ids = get_settings().admin_id_list
    if ids:
        return int(ids[0])
    if _extra:
        return min(_extra)
    return None


def is_super_admin(user_id: int | None) -> bool:
    if not user_id:
        return False
    return int(user_id) == int(super_admin_id() or -1)


def list_admins() -> list[dict]:
    """BARCHA adminlar: super (qalqon) + odatiy."""
    sup = super_admin_id()
    out: list[dict] = []
    seen: set[int] = set()
    for src_ids, role in ((_extra, "admin"),):
        for x in sorted(src_ids):
            if x in seen:
                continue
            seen.add(x)
            out.append({"id": x, "role": "super" if x == sup else role})
    for x in get_settings().admin_id_list:
        if x in seen:
            continue
        seen.add(x)
        out.append({"id": x, "role": "super" if x == sup else "env"})
    out.sort(key=lambda d: (d["role"] == "super", -d["id"]))
    out.reverse()
    return out


async def add_admin(user_id: int) -> bool:
    """Yangi admin qo'shish (DB + xotira). True = qo'shildi (yangi)."""
    global _extra
    if not user_id:
        return False
    uid = int(user_id)
    if uid in get_settings().admin_id_list or uid in _extra:
        return False
    _extra.add(uid)
    try:
        from app.database.session import async_session_factory
        from app.services.channel_store import save_json_log
        async with async_session_factory() as session:
            await save_json_log(session, ADMIN_COMPONENT, {"ids": sorted(_extra)})
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ADMIN] add saqlash: %s", exc)
    logger.info("[ADMIN] qo'shildi: %s", uid)
    return True


async def remove_admin(user_id: int) -> str:
    """Admin o'chirish. 'ok' / 'super' (qalqon!) / 'notfound'."""
    global _extra
    if not user_id:
        return "notfound"
    uid = int(user_id)
    if uid in get_settings().admin_id_list or int(uid) == int(super_admin_id() or -2):
        return "super"
    if uid not in _extra:
        return "notfound"
    _extra.discard(uid)
    try:
        from app.database.session import async_session_factory
        from app.services.channel_store import save_json_log
        async with async_session_factory() as session:
            await save_json_log(session, ADMIN_COMPONENT, {"ids": sorted(_extra)})
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ADMIN] remove saqlash: %s", exc)
    logger.info("[ADMIN] o'chirildi: %s", uid)
    return "ok"


async def notify_super(bot, text: str, except_uid: int | None = None) -> None:
    """Super-adminga TELEGRAM xabar (audit). Botdan tashqarida xato yutildi."""
    sup = super_admin_id()
    if not sup or bot is None:
        return
    if except_uid is not None and int(except_uid) == int(sup):
        # super o'zi qilgan ish — o'ziga xabar yuborilmaydi
        return
    try:
        await bot.send_message(int(sup), text, parse_mode="HTML")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AUDIT] super-ga xabar: %s", exc)


def audit_text(actor_id: int, actor_name: str, action: str) -> str:
    """v121 AUDIT: superga yuboriladigan matn (admin emas-deyiladi?)."""
    from app.core.timeuz import format_tashkent
    from datetime import datetime, timezone
    now = format_tashkent(datetime.now(timezone.utc))
    role = "SUPER" if is_super_admin(actor_id) else "ADMIN"
    return ("\U0001F6A8 <b>AUDIT: admin harakati</b>\n"
            f"Kim: <b>{actor_name}</b> <code>{actor_id}</code> ({role})\n"
            f"Amal: {action}\nVaqt: {now}")

