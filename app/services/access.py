"""v95: SIGNAL RO'YXATI (whitelist) — kim signal oladi, kim yo'q.

Qoida (user #60):
  * Admin — hamma narsani ko'radi va boshqaradi.
  * Ro'yxatdagi (whitelist) ID lar — signal kartalarini ko'radi,
    boshqa hech narsa qila olmaydi (buyruqlar bloklanadi).
  * Qolganlar — hech narsa ko'rmaydi; yagona tugma: ADMIN BILAN BOG'LANISH.

v97 LIMIT qoidalari (user #62):
  * Har ID ga YOKI signal soni limiti YOKI kun limiti — IKKALASI EMAS.
  * Kun limiti FAQAT signal berilgan kunlarni ayiradi: signal bo'lmagan
    kun hisobdan ketmaydi (bir kunda 10 signal bo'lsa ham 1 kun ayiriladi).
  * Limit tugagach signal to'xtaydi (ro'yxatdan o'chirmasa ham bo'ladi).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select

# Admin shu havolaga olib boradi (user aytgan username)
ADMIN_USERNAME = "asilbek_nematov01"
ADMIN_CONTACT_URL = "https://t.me/asilbek_nematov01"
CONTACT_LABEL = "\U0001F4DE Admin bilan bog'lanish"


from app.database.models.access import AccessUser  # noqa: F401


def is_admin_id(settings, uid: int) -> bool:
    try:
        return int(uid) in [int(x) for x in (settings.admin_id_list or [])]
    except (TypeError, ValueError):
        return False


async def is_allowed(session, settings, uid: int) -> bool:
    """Admin yoki ro'yxatda bormi?"""
    if is_admin_id(settings, uid):
        return True
    try:
        row = (await session.execute(
            select(AccessUser.user_id).where(AccessUser.user_id == int(uid))
        )).scalar_one_or_none()
        return row is not None
    except Exception:  # noqa: BLE001
        return False


async def allowed_ids(session) -> list[int]:
    try:
        rows = (await session.execute(select(AccessUser.user_id))).scalars().all()
        return [int(x) for x in rows]
    except Exception:  # noqa: BLE001
        return []


def _today() -> str:
    """UTC kun (YYYY-MM-DD) — kun hisobi shu bilan yuritiladi."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _alive(row) -> bool:
    """v97: limit hali tugamaganmi (signal soni YOKI kun soni)?"""
    try:
        mx = int(row.max_signals or 0)
        us = int(row.used_signals or 0)
        if mx > 0 and us >= mx:
            return False
        md = int(row.max_days or 0)
        du = int(row.days_used or 0)
        if md > 0 and du >= md:
            return False
        return True
    except Exception:  # noqa: BLE001
        return True


async def active_ids(session) -> list[int]:
    """v96/v97: signal OLISHI MUMKIN bo'lgan ID lar (limit bilan)."""
    try:
        rows = (await session.execute(select(AccessUser))).scalars().all()
        return [int(r.user_id) for r in rows if _alive(r)]
    except Exception:  # noqa: BLE001
        return []


async def consume(session) -> int:
    """Bitta signal yuborildi — har faol user hisobiga +1.

    v97: kun limiti bo'lsa va BUGUN hali hisoblanmagan bo'lsa — kun ham +1.
    Signal bo'lmagan kunlar AYIRILMAYDI (faqat signal kelgan kun sanaladi).
    """
    try:
        today = _today()
        rows = (await session.execute(select(AccessUser))).scalars().all()
        n = 0
        for r in rows:
            if _alive(r):
                r.used_signals = int(r.used_signals or 0) + 1
                if int(r.max_days or 0) > 0 and (r.last_day or "") != today:
                    r.days_used = int(r.days_used or 0) + 1
                    r.last_day = today
                n += 1
        await session.commit()
        return n
    except Exception:  # noqa: BLE001
        return 0


async def rows(session) -> list:
    try:
        return list((await session.execute(select(AccessUser))).scalars().all())
    except Exception:  # noqa: BLE001
        return []


def row_text(row) -> str:
    """Ro'yxat qatori: limit holati (signal YOKI kun YOKI cheksiz)."""
    mx = int(row.max_signals or 0)
    us = int(row.used_signals or 0)
    md = int(row.max_days or 0)
    du = int(row.days_used or 0)
    if mx > 0:
        qtxt = f"signal {us}/{mx}" + (" (TUGADI)" if us >= mx else "")
    elif md > 0:
        qtxt = (f"kun {du}/{md}" + (" (TUGADI)" if du >= md else "")
                + " · faqat signal berilgan kunlar")
        if (row.last_day or "") == _today():
            qtxt += " · bugun hisoblandi"
    else:
        qtxt = f"cheksiz (signal {us} yuborilgan)"
    return f"<code>{row.user_id}</code> — {qtxt}"


async def add_user(session, uid: int, by: int = 0,
                   mode: str = "none", value: int = 0) -> bool:
    """v97: mode = 'sig' (nechta signal) | 'day' (necha kun) | 'none' (cheksiz).

    Ikkala limit BIR VAQTDA qo'yilmaydi — user qoidasi.
    """
    uid = int(uid)
    row = (await session.execute(
        select(AccessUser).where(AccessUser.user_id == uid))).scalar_one_or_none()
    if row is not None:
        return False
    mx = int(value or 0) if mode == "sig" else 0
    md = int(value or 0) if mode == "day" else 0
    session.add(AccessUser(user_id=uid, added_by=int(by or 0),
                           max_signals=mx, max_days=md))
    await session.commit()
    return True


async def set_limits(session, uid: int, mode: str | None = None,
                     value: int | None = None, reset_used: bool = False) -> bool:
    """v97: limitni o'zgartirish. mode berilsa — ESKISI TOZALANADI
    (yoki signal yoki kun), hisoblar nolga tushadi."""
    uid = int(uid)
    row = (await session.execute(
        select(AccessUser).where(AccessUser.user_id == uid))).scalar_one_or_none()
    if row is None:
        return False
    if mode == "sig":
        row.max_signals = int(value or 0)
        row.max_days = 0
        row.used_signals = 0
        row.days_used = 0
        row.last_day = None
    elif mode == "day":
        row.max_days = int(value or 0)
        row.max_signals = 0
        row.used_signals = 0
        row.days_used = 0
        row.last_day = None
    elif mode == "none":
        row.max_signals = 0
        row.max_days = 0
        row.used_signals = 0
        row.days_used = 0
        row.last_day = None
    elif reset_used:
        # faqat hisobni nolga tushirish (limitlar joyida qoladi)
        row.used_signals = 0
        row.days_used = 0
        row.last_day = None
    await session.commit()
    return True


async def remove_user(session, uid: int) -> bool:
    uid = int(uid)
    row = (await session.execute(
        select(AccessUser).where(AccessUser.user_id == uid))).scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True


async def stats(session) -> dict:
    """v97: botda nechta odam bor — 👥 tugmasi uchun."""
    out = {"db_users": 0, "list": 0, "active": 0, "stopped": 0}
    try:
        from app.database.models.user import User
        out["db_users"] = int((await session.execute(
            select(func.count()).select_from(User))).scalar() or 0)
    except Exception:  # noqa: BLE001
        pass
    try:
        rws = (await session.execute(select(AccessUser))).scalars().all()
        out["list"] = len(rws)
        out["active"] = sum(1 for r in rws if _alive(r))
        out["stopped"] = out["list"] - out["active"]
    except Exception:  # noqa: BLE001
        pass
    return out
