"""v85: OFFLINE NAVBAT — baza ishlamaganda kanal xabarlari yo'qolmasin.

Baza (Postgres) o'chgan yoki manzili topilmayotgan bo'lsa, kanaldan kelgan
xabarlarni diskdagi JSONL faylga yozib turamiz. Baza qaytganda navbatdagi
xabarlar O'SHA TARTIBDA qayta ishlanadi: signal bo'lsa karta chiqadi va
hisobga olinadi.

Chegaralar: navbat 400 xabar (eng eskisi tushib qoladi), rasm 400 KB gacha
(base64). Qiymat: kanal signallari internet/baza uzilishida ham yo'qolmaydi.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import tempfile
import time
from datetime import datetime, timezone

from app.core.logging import get_logger

logger = get_logger(__name__)

MAX_RECORDS = 400
MAX_IMAGE_BYTES = 400_000
_FLUSH_EVERY_S = 60.0
_DOWN = False
_LAST_FLUSH = 0.0


def _path() -> str:
    p = os.environ.get("SINO_OFFLINE_PATH") or ""
    if p:
        return p
    return os.path.join(tempfile.gettempdir(), "sino_offline.jsonl")


def _dump(rec: dict) -> str:
    return json.dumps(rec, ensure_ascii=False, default=str)


def _load_all() -> list[dict]:
    out: list[dict] = []
    try:
        with open(_path(), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    if isinstance(r, dict):
                        out.append(r)
                except Exception:  # noqa: BLE001
                    continue
    except FileNotFoundError:
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("[OFF] navbat o'qilmadi: %s", exc)
        return []
    return out


def _save_all(recs: list[dict]) -> None:
    try:
        tmp = _path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for r in recs[-MAX_RECORDS:]:
                f.write(_dump(r) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _path())
    except Exception as exc:  # noqa: BLE001
        logger.warning("[OFF] navbat yozilmadi: %s", exc)


def count() -> int:
    return len(_load_all())


def mark_down() -> None:
    global _DOWN
    _DOWN = True


def mark_up() -> None:
    global _DOWN
    _DOWN = False


def is_down() -> bool:
    return _DOWN


def add(*, ch: dict | None = None, text: str = "", image_bytes: bytes | None = None,
        msg_id: int = 0, chat_id=None, title: str = "", username=None,
        grouped_id=None, reply_to=None, posted_at=None, reason: str = "") -> bool:
    """Xabarni navbatga qo'shadi. True = qo'shildi."""
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "ch": ch or {},
        "text": text or "",
        "msg_id": int(msg_id or 0),
        "chat_id": chat_id,
        "title": title or "",
        "username": username,
        "grouped_id": grouped_id,
        "reply_to": reply_to,
        "posted_at": (posted_at.isoformat() if hasattr(posted_at, "isoformat")
                      else posted_at),
        "reason": reason or "",
    }
    if image_bytes:
        try:
            if len(image_bytes) <= MAX_IMAGE_BYTES:
                rec["img_b64"] = base64.b64encode(image_bytes).decode("ascii")
        except Exception:  # noqa: BLE001
            pass
    try:
        recs = _load_all()
        recs.append(rec)
        _save_all(recs)
        mark_down()
        logger.warning("[OFF] navbatga qo'shildi (%d ta): %s", len(recs),
                       (text or "")[:70])
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("[OFF] navbatga qo'shilmadi: %s", exc)
        return False


async def flush(limit: int = 25) -> int:
    """Navbatdagi xabarlarni qayta ishlaydi. Nechta yozilganini qaytaradi."""
    global _LAST_FLUSH
    recs = _load_all()
    if not recs:
        return 0
    try:
        from app.services.channel_inbox import ingest_raw
    except Exception as exc:  # noqa: BLE001
        logger.warning("[OFF] ingest_raw yo'q: %s", exc)
        return 0
    done = 0
    for rec in recs[:max(1, int(limit))]:
        img = None
        b64 = rec.get("img_b64")
        if b64:
            try:
                img = base64.b64decode(b64)
            except Exception:  # noqa: BLE001
                img = None
        posted = rec.get("posted_at")
        try:
            if posted:
                posted = datetime.fromisoformat(str(posted))
        except Exception:  # noqa: BLE001
            posted = None
        try:
            res = await ingest_raw(
                ch=rec.get("ch") or {}, text=rec.get("text") or "",
                image_bytes=img, msg_id=int(rec.get("msg_id") or 0),
                chat_id=rec.get("chat_id"), title=rec.get("title") or "",
                username=rec.get("username"), grouped_id=rec.get("grouped_id"),
                reply_to=rec.get("reply_to"), require_listed=True,
                posted_at=posted,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[OFF] navbatdagi xabar qayta ishlanmadi: %s", exc)
            break
        if res == "db_error":
            break            # baza hali ham ishlamayapti — kutamiz
        recs.pop(0)
        _save_all(recs)
        done += 1
    _LAST_FLUSH = time.time()
    if done:
        logger.info("[OFF] navbatdan %d ta xabar yozildi (qoldi: %d)",
                    done, len(recs))
    mark_up()
    return done


async def loop(notifier=None) -> None:
    """Har 60 sekundda: baza ishlayaptimi — navbatni bo'shatadi."""
    await asyncio.sleep(45)
    while True:
        try:
            n = count()
            if n:
                try:
                    from app.services import dbhealth
                    ok = dbhealth.up() is True
                    if ok is None:
                        ok, _ = await dbhealth.ping()
                except Exception:  # noqa: BLE001
                    ok = False
                if ok:
                    done = await flush()
                    if done and notifier is not None:
                        left = count()
                        try:
                            await notifier.send_admin(
                                f"\U0001F4E5 <b>Navbatdan {done} ta xabar yozildi</b>"
                                + (f" (qoldi {left} ta)" if left else " \u2705")
                                + "\n<i>Baza uzilganda kelgan kanal xabarlari "
                                  "endi o'z vaqtida qayta ishlandi.</i>")
                        except Exception:  # noqa: BLE001
                            pass
        except Exception as exc:  # noqa: BLE001
            logger.debug("[OFF] loop: %s", exc)
        await asyncio.sleep(_FLUSH_EVERY_S)
