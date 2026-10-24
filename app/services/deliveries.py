"""v98: YETKAZISH JURNALI — kim qaysi signalni oldi.

Qoidalar (user #63):
  * /start bosgan har bir user bazaga BIR marta yoziladi (users jadvali,
    middleware get_or_create bilan allaqachon qiladi).
  * Ro'yxatda YO'Q (yoki limiti tugagan) user har 2 KUNDA (48 soat) bitta
    BEPUL signal oladi — TRIAL. Natijasi ham unga boradi.
  * Rad etilgan signallar HECH KIMGA bormaydi (bu funksiyaga umuman kirmaydi).
  * Admin signallarni DOIM oladi (bitta ham qolmay) — telegram.py da.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.core.logging import get_logger
from app.database.models.delivery import UserDelivery
from app.database.models.user import User

logger = get_logger(__name__)

TRIAL_HOURS = 48   # har 2 kunda 1 bepul signal


def _now():
    return datetime.now(timezone.utc)


async def log(session, uids: list[int], signal_id: int, kind: str) -> int:
    """Kartani olgan userlarni yozib qo'yadi (FULL = ro'yxatdagi, TRIAL = bepul)."""
    n = 0
    try:
        for uid in uids or []:
            session.add(UserDelivery(user_id=int(uid), signal_id=int(signal_id),
                                     kind=str(kind or "FULL")))
            n += 1
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[DLV] log xatosi: %s", exc)
    return n


async def last_sent_map(session, uids: list[int]) -> dict[int, datetime]:
    """user_id -> oxirgi karta vaqti."""
    out: dict[int, datetime] = {}
    if not uids:
        return out
    try:
        rows = await session.execute(
            select(UserDelivery.user_id, func.max(UserDelivery.delivered_at))
            .where(UserDelivery.user_id.in_([int(x) for x in uids]))
            .group_by(UserDelivery.user_id)
        )
        for uid, mx in rows.all():
            if mx is not None:
                if mx.tzinfo is None:
                    mx = mx.replace(tzinfo=timezone.utc)
                out[int(uid)] = mx
    except Exception as exc:  # noqa: BLE001
        logger.warning("[DLV] last_sent xatosi: %s", exc)
    return out


async def eligible_trial(session, exclude: set[int]) -> list[int]:
    """Bepul signalga navbatdagi userlar: bazadagi (start bosgan) HAMMA,
    ro'yxatdagi faol userlardan tashqari, oxirgi kartasidan 48 soat o'tgan
    (yoki umuman olmagan)."""
    try:
        cutoff = _now() - timedelta(hours=TRIAL_HOURS)
        all_ids = list((await session.execute(
            select(User.id).where(User.is_blocked.is_(False))
        )).scalars().all())
        cand = [int(x) for x in all_ids if int(x) not in exclude]
        if not cand:
            return []
        last = await last_sent_map(session, cand)
        return [uid for uid in cand
                if uid not in last or last[uid] <= cutoff]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[DLV] eligible xatosi: %s", exc)
        return []


async def receivers_of(session, signal_id: int) -> list[int]:
    """Shu signal kartasini olgan userlar (natija shularga ham boradi)."""
    try:
        rows = (await session.execute(
            select(UserDelivery.user_id)
            .where(UserDelivery.signal_id == int(signal_id))
        )).scalars().all()
        seen: list[int] = []
        for r in rows:
            if int(r) not in seen:
                seen.append(int(r))
        return seen
    except Exception as exc:  # noqa: BLE001
        logger.warning("[DLV] receivers xatosi: %s", exc)
        return []


async def mark_results(session, signal_id: int, pips: float | None,
                       win: bool | None) -> int:
    """Signal yopildi — shu signalni olganlarga natija yoziladi."""
    n = 0
    try:
        rows = (await session.execute(
            select(UserDelivery)
            .where(UserDelivery.signal_id == int(signal_id))
        )).scalars().all()
        for r in rows:
            if r.result_pips is None:
                r.result_pips = float(pips) if pips is not None else None
                r.win = bool(win) if win is not None else None
                n += 1
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[DLV] mark_results xatosi: %s", exc)
    return n


async def user_stats(session, uid: int) -> dict:
    """📊 Mening hisobim: olgan signallar, g'alabalar, jami foyda (pip)."""
    out = {"received": 0, "closed": 0, "wins": 0, "pips": 0.0}
    try:
        rows = (await session.execute(
            select(UserDelivery).where(UserDelivery.user_id == int(uid))
        )).scalars().all()
        out["received"] = len(rows)
        pips = 0.0
        wins = 0
        closed = 0
        for r in rows:
            if r.result_pips is not None:
                closed += 1
                pips += float(r.result_pips or 0.0)
                if r.win:
                    wins += 1
        out["closed"] = closed
        out["wins"] = wins
        out["pips"] = round(pips, 1)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[DLV] user_stats xatosi: %s", exc)
    return out
