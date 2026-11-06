"""v76: baza zaxirasi — HAR 48 SOATDA, soat 23:00 (Toshkent), birinchi marta ERTAGA.

Foydalanuvchi so'rovi: «har 48 soatda tashlaydigan qilib ber, soat 23:00 da,
bugun tashlamasin, ertadan boshlaydi».

Render'ning bepul tarifida cron yo'q, shuning uchun taymer botning ichida:
har 60 sekundda tekshiradi, vaqti kelganda /DB bilan bir xil SQL dumpni
adminga o'zi yuboradi.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import time

from aiogram.types import BufferedInputFile
from sqlalchemy import select

from app.core.timeuz import format_tashkent, to_tashkent
from app.database.models.system import SystemLog

logger = logging.getLogger(__name__)

COMPONENT = "dbbackup"
DEFAULT_HOUR = 23
DEFAULT_EVERY_H = 48


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except Exception:  # noqa: BLE001
        return default


def cfg() -> tuple[int, int]:
    """(soat, necha soatda bir) — Toshkent vaqti bilan."""
    hour = min(23, max(0, _env_int("SINO_DB_BACKUP_HOUR", DEFAULT_HOUR)))
    every = max(1, _env_int("SINO_DB_BACKUP_EVERY_H", DEFAULT_EVERY_H))
    return hour, every


def first_run(now: dt.datetime | None = None) -> dt.datetime:
    """Birinchi yuborish vaqti (UTC): ERTAGA 23:00 (Toshkent) — bugun YO'Q."""
    hour, _ = cfg()
    cur = to_tashkent(now)
    cand = cur.replace(hour=hour, minute=0, second=0, microsecond=0)
    if cand <= cur:                      # bugungi vaqt o'tib ketgan
        cand += dt.timedelta(days=1)
    if cand.date() == cur.date():        # BUGUN tashlamaymiz -> ertaga
        cand += dt.timedelta(days=1)
    return cand.astimezone(dt.timezone.utc)


def next_after(last: dt.datetime) -> dt.datetime:
    """Keyingi yuborish = oxirgisi + 48 soat (soat o'zgarmaydi)."""
    _, every = cfg()
    return last + dt.timedelta(hours=every)


async def load_state(session) -> dict:
    res = await session.execute(
        select(SystemLog).where(SystemLog.component == COMPONENT)
        .order_by(SystemLog.id.desc()).limit(1)
    )
    row = res.scalars().first()
    if row is None:
        return {}
    try:
        return json.loads(row.message or "") or {}
    except Exception:  # noqa: BLE001
        return {}


async def save_state(session, st: dict) -> None:
    session.add(SystemLog(level="INFO", component=COMPONENT,
                          message=json.dumps(st, ensure_ascii=False)))
    await session.commit()


def _ts(value) -> dt.datetime | None:
    try:
        return dt.datetime.fromtimestamp(float(value), tz=dt.timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def status_line(st: dict) -> str:
    """«⏰ Avto-zaxira: har 48 soatda 23:00 (Toshkent) · keyingi: …»"""
    hour, every = cfg()
    nxt = _ts(st.get("next_ts"))
    txt = f"\u23F0 <b>Avto-zaxira</b>: har {every} soatda {hour:02d}:00 (Toshkent)"
    if nxt is not None:
        txt += f" \u00B7 keyingi: <b>{format_tashkent(nxt)}</b>"
        last = _ts(st.get("last_ts"))
        if last is not None:
            txt += f" \u00B7 oxirgisi: {format_tashkent(last)}"
    else:
        txt += " \u00B7 hali boshlanmagan"
    return txt


async def _admin_id() -> int | None:
    try:
        from app.core.config import get_settings
        ids = get_settings().admin_id_list
        return int(ids[0]) if ids else None
    except Exception:  # noqa: BLE001
        return None


async def tick(bot, now: dt.datetime | None = None, *, force: bool = False) -> bool:
    """Vaqti kelgan bo'lsa zaxirani yuboradi. True — yuborildi."""
    from app.database.session import async_session_factory

    now = now or dt.datetime.now(dt.timezone.utc)
    async with async_session_factory() as session:
        st = await load_state(session)
        if not st:
            # v76: birinchi ishga tushishda rejalashtiramiz — ERTAGA 23:00, bugun emas
            st = {"next_ts": first_run(now).timestamp(), "started_at": now.timestamp(),
                  "runs": 0, "hour": cfg()[0], "every_h": cfg()[1]}
            await save_state(session, st)
            logger.info("[DB-BACKUP] reja: birinchi zaxira %s",
                        format_tashkent(_ts(st["next_ts"])))
        due = force or now.timestamp() >= float(st.get("next_ts") or 0)
        if not due:
            return False

    admin = await _admin_id()
    if not admin:
        logger.warning("[DB-BACKUP] admin ID yo'q — zaxira yuborilmadi")
        return False

    from app.services import dbdump

    name, data, stats = await dbdump.build()
    kb = len(data) / 1024.0
    size = f"{kb / 1024:.1f} MB" if kb > 1024 else f"{kb:.0f} KB"
    hour, every = cfg()
    nxt = next_after(now)
    caption = (f"\u23F0 <b>AVTO-ZAXIRA</b> (har {every} soatda, {hour:02d}:00 Toshkent)\n"
               f"Jadvallar: <b>{stats.get('tables')}</b> \u00B7 "
               f"Yozuvlar: <b>{stats.get('rows')}</b> \u00B7 Hajm: <b>{size}</b>\n"
               f"Keyingisi: <b>{format_tashkent(nxt)}</b>\n"
               f"<i>Supabase/Neon ga tiklash: /DB xabaridagi qo'llanma.</i>")
    try:
        await bot.send_document(chat_id=admin,
                                document=BufferedInputFile(data, filename=name),
                                caption=caption)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[DB-BACKUP] yuborilmadi: %s", exc)
        return False

    async with async_session_factory() as session:
        st = await load_state(session)
        st.update({"last_ts": now.timestamp(), "next_ts": nxt.timestamp(),
                   "runs": int(st.get("runs") or 0) + 1, "name": name,
                   "rows": int(stats.get("rows") or 0)})
        await save_state(session, st)
    logger.info("[DB-BACKUP] yuborildi: %s (%s yozuv), keyingisi %s",
                name, stats.get("rows"), format_tashkent(nxt))
    return True


async def loop(bot, interval: float = 60.0) -> None:
    """Doimiy tekshiruv: uxlab qolsa (bepul rejim) — uyg'onganda yuboradi."""
    await asyncio.sleep(20)
    while True:
        try:
            await tick(bot)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[DB-BACKUP] tick xatosi: %s", exc)
        await asyncio.sleep(max(15.0, interval))


def started_at() -> float:
    return time.time()
