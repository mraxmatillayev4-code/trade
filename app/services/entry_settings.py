"""v84: kirish nuqtasi sozlamalari (bazada saqlanadi, zaxiraga ham tushadi).

Sozlamalar:
    entry_enabled   — kirish nuqtasi rejimi YOQILGAN/O'CHIQ (standart: YOQILGAN)
    entry_wait_min  — narx necha daqiqa kutiladi (15 / 30 / 60 / 120)
    entry_cool_min  — SL dan keyin qarama-qarshi tomonga o'tish tanaffusi
                      (0 / 15 / 30 / 60 daqiqa)
"""
from __future__ import annotations

from app.core.logging import get_logger

logger = get_logger(__name__)

K_ENABLED = "entry_enabled"
K_WAIT = "entry_wait_min"
K_COOL = "entry_cool_min"

_CACHE: dict = {}


def _cf(settings_key: str, default):
    try:
        from app.core.config import get_settings
        return getattr(get_settings(), settings_key, default)
    except Exception:  # noqa: BLE001
        return default


def clamp_wait(v) -> int:
    from app.engine import entry as _e
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return int(_e.DEFAULT_WAIT)
    if n in _e.WAIT_CHOICES:
        return n
    return int(_e.DEFAULT_WAIT)


def clamp_cool(v) -> int:
    from app.engine import entry as _e
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return int(_e.DEFAULT_COOLDOWN)
    if n in _e.COOLDOWN_CHOICES:
        return n
    return int(_e.DEFAULT_COOLDOWN)


def defaults() -> dict:
    return {
        K_ENABLED: bool(_cf("entry_enabled", True)),
        K_WAIT: clamp_wait(_cf("entry_wait_minutes", 30)),
        K_COOL: clamp_cool(_cf("entry_cooldown_minutes", 15)),
    }


def cached() -> dict:
    """Tez o'qish (handlerlar uchun)."""
    if not _CACHE:
        _CACHE.update(defaults())
    return dict(_CACHE)


def values() -> dict:
    return cached()


async def load(session) -> dict:
    """Bazadan o'qiydi (bo'lmasa standart)."""
    out = defaults()
    try:
        from sqlalchemy import select

        from app.database.models.app_setting import AppSetting
        rows = list((await session.execute(select(AppSetting))).scalars().all())
        got = {r.key: (r.value or "") for r in rows}
        if K_ENABLED in got:
            out[K_ENABLED] = str(got[K_ENABLED]).strip().lower() not in ("0", "off", "false", "")
        if K_WAIT in got:
            out[K_WAIT] = clamp_wait(got[K_WAIT])
        if K_COOL in got:
            out[K_COOL] = clamp_cool(got[K_COOL])
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ENTRY-SET] o'qish: %s", exc)
    _CACHE.update(out)
    return dict(out)


async def save(session, **kw) -> dict:
    """Saqlaydi (faqat berilgan kalitlar)."""
    cur = await load(session)
    if K_ENABLED in kw:
        cur[K_ENABLED] = bool(kw[K_ENABLED])
    if K_WAIT in kw:
        cur[K_WAIT] = clamp_wait(kw[K_WAIT])
    if K_COOL in kw:
        cur[K_COOL] = clamp_cool(kw[K_COOL])
    try:
        from sqlalchemy import select

        from app.database.models.app_setting import AppSetting
        rows = list((await session.execute(select(AppSetting))).scalars().all())
        have = {r.key: r for r in rows}
        pairs = {
            K_ENABLED: "1" if cur[K_ENABLED] else "0",
            K_WAIT: str(cur[K_WAIT]),
            K_COOL: str(cur[K_COOL]),
        }
        for k, v in pairs.items():
            if k in have:
                have[k].value = v
            else:
                session.add(AppSetting(key=k, value=v))
        await session.commit()
        _CACHE.update(cur)
    except Exception as exc:  # noqa: BLE001
        logger.error("[ENTRY-SET] saqlash: %s", exc)
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
    return dict(cur)


def text_summary(vals: dict | None = None) -> str:
    v = vals or cached()
    on = bool(v.get(K_ENABLED))
    return (
        f"Rejim: <b>{'YOQILGAN' if on else 'OCHIQ'}</b> \u00B7 "
        f"Kutish: <b>{int(v.get(K_WAIT, 30))} daqiqa</b> \u00B7 "
        f"Qarama-qarshi tomonga tanaffus: <b>{int(v.get(K_COOL, 15))} daqiqa</b>"
    )
