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
