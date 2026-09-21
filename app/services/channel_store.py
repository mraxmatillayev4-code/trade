"""Signal kanallari ro'yxati — mavjud SystemLog jadvalida (yangi jadval YO'Q).

component='channels', message=JSON list.
Har kanal statistikasi StrategyStat.strategy_name='ch:@user' (String 40).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.system import SystemLog

COMPONENT = "channels"
SESSION_COMPONENT = "tg_session"
API_COMPONENT = "tg_api"
MAX_CHANNELS = 15
READ_COMPONENT = "ch_reads"
READ_WIPE_ONCE = "wipe-v1"


def peer_bare(chat_id: int | None) -> int | None:
    """Bot API -100xxxxxxxxxx va Telethon xxxxxxxxxxx ni bir xil qiladi."""
    if chat_id is None:
        return None
    try:
        n = abs(int(chat_id))
    except (TypeError, ValueError):
        return None
    s = str(n)
    if s.startswith("100") and len(s) >= 12:
        return int(s[3:])
    return n


def stat_key(username: str | None, chat_id: int | None) -> str:
    """StrategyStat.strategy_name — max 40 belgi."""
    if username:
        u = username.lstrip("@").lower()[:32]
        return f"ch:@{u}"[:40]
    if chat_id is not None:
        s = str(int(chat_id))
        return f"ch:{s}"[:40]
    return "ch:unknown"


def display_name(ch: dict) -> str:
    title = (ch.get("title") or "").strip()
    user = (ch.get("username") or "").lstrip("@")
    if user:
        return f"@{user}" + (f" ({title})" if title and title.lower() != user.lower() else "")
    if title:
        return title
    cid = ch.get("chat_id")
    return f"id:{cid}" if cid else "noma'lum"


async def list_channels(session: AsyncSession) -> list[dict]:
    row = await session.scalar(
        select(SystemLog)
        .where(SystemLog.component == COMPONENT)
        .order_by(SystemLog.id.desc())
        .limit(1)
    )
    if not row or not row.message:
        return []
    try:
        data = json.loads(row.message)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


async def _save(session: AsyncSession, channels: list[dict]) -> None:
    payload = json.dumps(channels, ensure_ascii=False)
    row = await session.scalar(
        select(SystemLog)
        .where(SystemLog.component == COMPONENT)
        .order_by(SystemLog.id.desc())
        .limit(1)
    )
    if row:
        row.message = payload
    else:
        session.add(SystemLog(level="INFO", component=COMPONENT, message=payload))
    await session.commit()


def _same(ch: dict, *, username: str | None, chat_id: int | None) -> bool:
    if chat_id is not None and ch.get("chat_id") is not None:
        try:
            if peer_bare(ch["chat_id"]) == peer_bare(chat_id):
                return True
        except (TypeError, ValueError):
            pass
    if username:
        a = (ch.get("username") or "").lstrip("@").lower()
        b = username.lstrip("@").lower()
        if a and b and a == b:
            return True
    return False


async def add_channel(session: AsyncSession, *, username: str | None = None,
                      chat_id: int | None = None, title: str = "",
                      kind: str = "public") -> tuple[bool, str, dict | None]:
    channels = await list_channels(session)
    for ch in channels:
        if _same(ch, username=username, chat_id=chat_id):
            # chat_id yangilash
            if chat_id is not None:
                ch["chat_id"] = int(chat_id)
            if title:
                ch["title"] = title
            if username:
                ch["username"] = username.lstrip("@").lower()
            await _save(session, channels)
            return True, "Kanal allaqachon ro'yxatda — ma'lumot yangilandi.", ch
    if len(channels) >= MAX_CHANNELS:
        return False, f"Maksimum {MAX_CHANNELS} ta kanal. Avval birini o'chiring.", None
    ch = {
        "username": (username or "").lstrip("@").lower() or None,
        "chat_id": int(chat_id) if chat_id is not None else None,
        "title": title or "",
        "kind": kind,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    channels.append(ch)
    await _save(session, channels)
    return True, "Kanal qo'shildi.", ch


async def remove_channel(session: AsyncSession, key: str) -> tuple[bool, str]:
    key = (key or "").strip().lstrip("@").lower()
    channels = await list_channels(session)
    keep = []
    removed = None
    for ch in channels:
        user = (ch.get("username") or "").lower()
        cid = str(ch.get("chat_id") or "")
        if key and (key == user or key == cid or key == f"@{user}"):
            removed = ch
            continue
        keep.append(ch)
    if removed is None:
        return False, "Bunday kanal topilmadi."
    await _save(session, keep)
    return True, f"O'chirildi: {display_name(removed)}"


async def match_channel(session: AsyncSession, *, chat_id: int | None,
                        username: str | None) -> dict | None:
    channels = await list_channels(session)
    for ch in channels:
        if _same(ch, username=username, chat_id=chat_id):
            return ch
    return None


async def bind_chat_id(session: AsyncSession, ch: dict, chat_id: int,
                       title: str = "") -> None:
    channels = await list_channels(session)
    for item in channels:
        if _same(item, username=ch.get("username"), chat_id=ch.get("chat_id")):
            item["chat_id"] = int(chat_id)
            if title:
                item["title"] = title
            break
    await _save(session, channels)


async def touch_channel(session: AsyncSession, *, username: str | None,
                        chat_id: int | None, title: str = "",
                        last_msg_id: int | None = None) -> None:
    channels = await list_channels(session)
    changed = False
    for item in channels:
        if _same(item, username=username, chat_id=chat_id):
            if chat_id is not None:
                item["chat_id"] = int(chat_id)
            if title:
                item["title"] = title
            if last_msg_id is not None:
                prev = int(item.get("last_msg_id") or 0)
                if int(last_msg_id) > prev:
                    item["last_msg_id"] = int(last_msg_id)
            changed = True
            break
    if changed:
        await _save(session, channels)


async def load_json_log(session: AsyncSession, component: str) -> dict:
    row = await session.scalar(
        select(SystemLog)
        .where(SystemLog.component == component)
        .order_by(SystemLog.id.desc())
        .limit(1)
    )
    if not row or not row.message:
        return {}
    try:
        data = json.loads(row.message)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        if component == SESSION_COMPONENT and row.message.strip():
            return {"session": row.message.strip()}
        return {}


def _day_key() -> str:
    from datetime import timedelta, timezone as tz
    local = tz(timedelta(hours=5))
    return datetime.now(local).strftime("%Y-%m-%d")


def _bump(row: dict, is_signal: bool) -> None:
    row["seen"] = int(row.get("seen") or 0) + 1
    if is_signal:
        row["signal"] = int(row.get("signal") or 0) + 1
    else:
        row["emas"] = int(row.get("emas") or 0) + 1


def stats_for_channel(by_stats: dict, ch: dict | None) -> dict:
    """Hisobot qatori: avval username, bo'lmasa chat_id kaliti (qo'shib yubormaydi)."""
    by_stats = by_stats or {}
    ch = ch or {}
    keys = [
        stat_key(ch.get("username"), ch.get("chat_id")),
        stat_key(ch.get("username"), None) if ch.get("username") else None,
        stat_key(None, ch.get("chat_id")) if ch.get("chat_id") is not None else None,
    ]
    used: set[str] = set()
    for k in keys:
        if not k or k in used:
            continue
        used.add(k)
        row = by_stats.get(k)
        if row:
            return {
                "seen": int(row.get("seen") or 0),
                "signal": int(row.get("signal") or 0),
                "emas": int(row.get("emas") or 0),
                "name": row.get("name") or display_name(ch),
            }
    return {"seen": 0, "signal": 0, "emas": 0, "name": display_name(ch)}


async def wipe_reads_once(session: AsyncSession) -> bool:
    """Faqat ch_reads sonlari. Boshqa jadvallarga tegilmaydi. Bir marta."""
    data = await load_json_log(session, READ_COMPONENT)
    if data.get("_once") == READ_WIPE_ONCE:
        return False
    await save_json_log(session, READ_COMPONENT, {
        "_once": READ_WIPE_ONCE,
        "all": {"seen": 0, "signal": 0, "emas": 0},
        "by": {},
        "days": {},
    })
    return True


async def record_read(session: AsyncSession, ch: dict | None, is_signal: bool) -> None:
    """Har kanal xabari: seen / signal / emas. Yangi jadval yo'q."""
    data = await load_json_log(session, READ_COMPONENT)
    all_ = data.setdefault("all", {"seen": 0, "signal": 0, "emas": 0})
    _bump(all_, is_signal)
    sk = stat_key((ch or {}).get("username"), (ch or {}).get("chat_id"))
    by = data.setdefault("by", {})
    row = by.setdefault(sk, {"seen": 0, "signal": 0, "emas": 0, "name": display_name(ch or {})})
    if ch:
        row["name"] = display_name(ch)
    _bump(row, is_signal)
    day = _day_key()
    days = data.setdefault("days", {})
    drow = days.setdefault(day, {"seen": 0, "signal": 0, "emas": 0, "by": {}})
    _bump(drow, is_signal)
    dby = drow.setdefault("by", {})
    dch = dby.setdefault(sk, {"seen": 0, "signal": 0, "emas": 0, "name": row.get("name") or sk})
    _bump(dch, is_signal)
    # 90 kundan eski kunlarni olib tashlash
    if len(days) > 100:
        for k in sorted(days.keys())[:-90]:
            days.pop(k, None)
    await save_json_log(session, READ_COMPONENT, data)


async def read_stats_for_days(session: AsyncSession, day_from: str, day_to: str) -> dict:
    data = await load_json_log(session, READ_COMPONENT)
    days = data.get("days") or {}
    out = {"seen": 0, "signal": 0, "emas": 0, "by": {}}
    for k, v in days.items():
        if not (day_from <= str(k) <= day_to):
            continue
        if not isinstance(v, dict):
            continue
        out["seen"] += int(v.get("seen") or 0)
        out["signal"] += int(v.get("signal") or 0)
        out["emas"] += int(v.get("emas") or 0)
        for sk, row in (v.get("by") or {}).items():
            acc = out["by"].setdefault(
                sk, {"seen": 0, "signal": 0, "emas": 0, "name": (row or {}).get("name") or sk},
            )
            acc["seen"] += int((row or {}).get("seen") or 0)
            acc["signal"] += int((row or {}).get("signal") or 0)
            acc["emas"] += int((row or {}).get("emas") or 0)
            if (row or {}).get("name"):
                acc["name"] = row["name"]
    if not out["seen"]:
        all_ = data.get("all") or {}
        out["seen"] = int(all_.get("seen") or 0)
        out["signal"] = int(all_.get("signal") or 0)
        out["emas"] = int(all_.get("emas") or 0)
        if not out["by"]:
            out["by"] = data.get("by") or {}
    return out


async def save_json_log(session: AsyncSession, component: str, data: dict) -> None:
    payload = json.dumps(data, ensure_ascii=False)
    row = await session.scalar(
        select(SystemLog)
        .where(SystemLog.component == component)
        .order_by(SystemLog.id.desc())
        .limit(1)
    )
    if row:
        row.message = payload
    else:
        session.add(SystemLog(level="INFO", component=component, message=payload))
    await session.commit()
