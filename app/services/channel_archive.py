"""Kanal xabarlarini bazaga yozib olish — /100 buyrug'i uchun.

Nima qiladi:
  dump(limit=100)      — v88: BITTA kanaldan oxirgi 100 ta xabar (rasm ichidagi
                         yozuv OCR bilan birga) bazaga yoziladi. Kanal `/100 @kanal`
                         yoki tugma bilan tanlanadi; tanlanmasa — birinchi kanal.
                         Shu kanalning ESKI yozuvlari O'CHIRILADI, keyin yangisi yoziladi.
  ocr_pass(...)        — bazadagi rasm xabarlarini tesseract bilan o'qib, matnini qo'shadi.
  export_txt()         — hammasini bitta .txt faylga yig'adi (adminga yuborish uchun).
  stats()              — qaysi kanaldan nechta xabar yozilgani.

Jadval: channel_messages (raw SQL — sxema eskirib qolsa ham ishlaydi).
"""
from __future__ import annotations

import asyncio
import io
import time
from datetime import datetime, timezone

from sqlalchemy import text

from app.core.logging import get_logger
from app.core.timeuz import stamp_tashkent, to_tashkent
from app.database.session import async_session_factory
from app.services.channel_store import display_name, list_channels, peer_bare, stat_key

logger = get_logger(__name__)

TABLE = "channel_messages"
_DDL_PG = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    id SERIAL PRIMARY KEY,
    ch_key VARCHAR(64) NOT NULL,
    username VARCHAR(64),
    title VARCHAR(160),
    msg_id BIGINT NOT NULL,
    msg_date TIMESTAMPTZ,
    body TEXT,
    ocr TEXT,
    has_photo BOOLEAN DEFAULT FALSE,
    has_video BOOLEAN DEFAULT FALSE,
    grouped_id BIGINT,
    reply_to BIGINT,
    views INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
)"""
_DDL_SQLITE = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ch_key TEXT NOT NULL,
    username TEXT,
    title TEXT,
    msg_id INTEGER NOT NULL,
    msg_date TEXT,
    body TEXT,
    ocr TEXT,
    has_photo INTEGER DEFAULT 0,
    has_video INTEGER DEFAULT 0,
    grouped_id INTEGER,
    reply_to INTEGER,
    views INTEGER,
    created_at TEXT
)"""

_lock = asyncio.Lock()
_last: dict = {}

# v88: OCR shu dumpda nechta rasmni o'qiydi (juda ko'p bo'lsa vaqt ketadi)
OCR_MAX_DEFAULT = 60
# v90: /100 dagi TEZ rejim — shu qadar rasm o'qiladi (qolgani /100ocr bilan).
OCR_FAST_DEFAULT = 25

# v90: /100 jarayoni holati (restart bo'lsa ham bilinadi)
STATE_TABLE = "channel_dump_state"
_DDL_STATE = f"""
CREATE TABLE IF NOT EXISTS {STATE_TABLE} (
    id INTEGER PRIMARY KEY,
    status TEXT,
    stage TEXT,
    note TEXT,
    limit_n INTEGER,
    only_key TEXT,
    started TEXT,
    beat TEXT
)"""


def _err(out: dict, msg: str, limit: int = 5) -> None:
    """Xatolar namunasiga yozadi (spam qilmaydi)."""
    lst = out.setdefault("errors", [])
    if len(lst) < limit:
        lst.append(str(msg)[:200])


async def _ocr_ids(client, ch: dict | None, ch_key: str, ids: list[int], name: str,
                   out: dict, progress=None, done_base: int = 0,
                   total: int = 0) -> dict:
    """v88: bitta kanalning `ids` xabarlarini OCR qiladi (dump va ocr_pass uchun).

    `out` ga hisob yozadi: done / empty / fail / skip. Statistikani qaytaradi.
    """
    from app.services.channel_ocr import ocr_image

    stat = {"name": name, "n": 0, "done": 0, "empty": 0, "fail": 0}
    if not ids:
        return stat
    if not ch:
        out["skip"] = int(out.get("skip", 0)) + len(ids)
        stat["fail"] = len(ids)
        return stat
    entity = await _resolve(client, ch)
    if entity is None:
        out["fail"] = int(out.get("fail", 0)) + len(ids)
        stat["fail"] = len(ids)
        _err(out, f"{name}: kanal entity topilmadi (@{ch.get('username')})")
        return stat

    msgs: dict = {}
    try:
        got = await client.get_messages(entity, ids=ids)
        if isinstance(got, (list, tuple)):
            for m in got:
                if m is not None:
                    msgs[int(getattr(m, "id", 0) or 0)] = m
        elif got is not None:
            msgs[int(getattr(got, "id", 0) or 0)] = got
    except Exception as exc:  # noqa: BLE001
        _err(out, f"{name}: get_messages {type(exc).__name__}: {exc}")

    missing = [i for i in ids if i not in msgs]
    if missing:
        try:
            low = min(missing)
            async for m in client.iter_messages(entity, limit=len(missing) + 60):
                mid = int(getattr(m, "id", 0) or 0)
                if mid and mid not in msgs and mid >= low:
                    msgs[mid] = m
        except Exception as exc:  # noqa: BLE001
            _err(out, f"{name}: iter_messages {type(exc).__name__}: {exc}")

    for mid in ids:
        stat["n"] += 1
        msg = msgs.get(mid)
        if msg is None:
            out["fail"] = int(out.get("fail", 0)) + 1
            stat["fail"] += 1
            await _mark_ocr(ch_key, mid, "")
            continue
        if not (_is_photo(msg) or _is_video(msg)):
            out["skip"] = int(out.get("skip", 0)) + 1
            stat["fail"] += 1
            await _mark_ocr(ch_key, mid, "")       # media yo'q — qayta urinmaymiz
            continue
        try:
            buf = io.BytesIO()
            got_b = await msg.download_media(file=buf)
            data = got_b if isinstance(got_b, (bytes, bytearray)) else buf.getvalue()
            if not data:
                raise RuntimeError("rasm yuklanmadi (bo'sh)")
            try:
                # v89: OCR og'ir ish — EVENT LOOP BLOKLANMASIN (to_thread)
                txt = (await asyncio.to_thread(ocr_image, bytes(data)) or "").strip()
            except Exception as exc:  # noqa: BLE001
                txt = ""
                _err(out, f"OCR {name}#{mid}: {type(exc).__name__}: {exc}")
            if txt:
                out["done"] = int(out.get("done", 0)) + 1
                stat["done"] += 1
            else:
                out["empty"] = int(out.get("empty", 0)) + 1
                stat["empty"] += 1
            await _mark_ocr(ch_key, mid, txt)
        except Exception as exc:  # noqa: BLE001
            out["fail"] = int(out.get("fail", 0)) + 1
            stat["fail"] += 1
            _err(out, f"{name}#{mid}: {type(exc).__name__}: {exc}")
            await _mark_ocr(ch_key, mid, "")
        await asyncio.sleep(0.02)
        if progress is not None and stat["n"] % 3 == 0:
            try:
                progress(done_base + stat["n"], total or len(ids), name)
            except Exception:  # noqa: BLE001
                pass
    if progress is not None:
        try:
            progress(done_base + stat["n"], total or len(ids), name)
        except Exception:  # noqa: BLE001
            pass
    logger.warning("[CH-OCR] %s: o'qildi %d | bo'sh %d | xato %d",
                   name, stat["done"], stat["empty"], stat["fail"])
    return stat


def as_choices(chans: list[dict]) -> list[dict]:
    """v89: kanal dict'larini yagona ko'rinishga keltiradi.

    MUHIM: `match_channel` avval faqat `channel_choices()` ko'rinishidagi
    dict'lar bilan ishlardi; `dump()` esa XOM kanal dict'larini berardi
    (ularda `key`/`name` yo'q) -> «kanal topilmadi: ch:@...» xatosi chiqardi.
    Endi ikkalasi ham shu funksiyadan o'tadi.
    """
    out: list[dict] = []
    for ch in chans or []:
        if not isinstance(ch, dict):
            continue
        if "key" in ch and "name" in ch:
            item = dict(ch)
            item.setdefault("username", (ch.get("username") or "").lstrip("@"))
            item.setdefault("raw", ch.get("raw") if isinstance(ch.get("raw"), dict) else ch)
            out.append(item)
            continue
        out.append({
            "key": stat_key(ch.get("username"), ch.get("chat_id")),
            "name": display_name(ch),
            "username": (ch.get("username") or "").lstrip("@"),
            "raw": ch,
        })
    return out


async def channel_choices() -> list[dict]:
    """v88: tanlash uchun kanallar ro'yxati: [{key, name, username, raw}]."""
    out: list[dict] = []
    try:
        async with async_session_factory() as session:
            chans = await list_channels(session)
        out = as_choices(chans)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH-DUMP] kanallar ro'yxati: %s", exc)
    return out


def match_channel(chans: list[dict], only: str | None) -> list[dict]:
    """v88: `only` bo'yicha kanal(lar)ni tanlaydi (kalit / @username / nom bo'lagi)."""
    chans = as_choices(chans)          # v89: xom dict'lar ham bo'ladi
    if not only:
        return chans
    q = str(only).strip().lstrip("@").lower()
    if not q:
        return chans
    if q.startswith("ch:"):            # kalitning o'zi berilgan ("ch:@kanal")
        q2 = q[3:]
        for ch in chans:
            if str(ch.get("key", "")).lower() == str(only).strip().lower():
                return [ch]
            if str(ch.get("key", "")).lower() == "ch:" + q2:
                return [ch]
    for ch in chans:                                    # aynan kalit yoki username
        if q == str(ch.get("key", "")).lower() or q == str(ch.get("username", "")).lower():
            return [ch]
    hits = [ch for ch in chans if q in str(ch.get("name", "")).lower()]
    if hits:
        return hits[:1]
    if q.isdigit():                                     # tartib raqami bilan: /100 100 2
        i = int(q) - 1
        if 0 <= i < len(chans):
            return [chans[i]]
    return []


# --------------------------------------------------------------------------- #
#  DB
# --------------------------------------------------------------------------- #

def _dialect(session) -> str:
    try:
        return str(session.bind.dialect.name or "")
    except Exception:  # noqa: BLE001
        return "postgresql"


async def ensure_table(session) -> bool:
    d = _dialect(session)
    ddl = _DDL_SQLITE if d == "sqlite" else _DDL_PG
    await session.execute(text(ddl))
    await session.execute(text(
        f"CREATE UNIQUE INDEX IF NOT EXISTS ux_chmsg ON {TABLE} (ch_key, msg_id)"))
    await session.commit()
    return True


async def _delete_channel(session, key: str) -> int:
    r = await session.execute(text(f"DELETE FROM {TABLE} WHERE ch_key = :k"), {"k": key})
    return int(getattr(r, "rowcount", 0) or 0)


async def _insert_rows(session, rows: list[dict]) -> int:
    if not rows:
        return 0
    n = 0
    sql = text(
        f"INSERT INTO {TABLE} "
        "(ch_key, username, title, msg_id, msg_date, body, has_photo, has_video,"
        " grouped_id, reply_to, views) VALUES "
        "(:ch_key, :username, :title, :msg_id, :msg_date, :body, :has_photo,"
        " :has_video, :grouped_id, :reply_to, :views)"
    )
    for r in rows:
        try:
            await session.execute(sql, r)
            n += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CH-DUMP] insert %s#%s: %s", r.get("ch_key"), r.get("msg_id"), exc)
    return n


async def fetch_msg(msg_id: int, username: str | None = None) -> dict | None:
    """v81: arxivdagi postni topib beradi — matn, OCR va tashlangan vaqti.

    Signal kartasi eski bo'lsa (manba saqlanmagan) «Nega bu signal?» shu
    yerdan asl xabarni ko'rsatadi.
    """
    mid = int(msg_id or 0)
    if mid <= 0:
        return None
    try:
        async with async_session_factory() as session:
            await ensure_table(session)
            u = (username or "").lstrip("@").lower()
            if u:
                r = await session.execute(text(
                    f"SELECT username, title, msg_id, msg_date, body, ocr FROM {TABLE} "
                    f"WHERE msg_id = :m AND LOWER(COALESCE(username,'')) = :u "
                    f"ORDER BY id DESC LIMIT 1"), {"m": mid, "u": u})
            else:
                r = await session.execute(text(
                    f"SELECT username, title, msg_id, msg_date, body, ocr FROM {TABLE} "
                    f"WHERE msg_id = :m ORDER BY id DESC LIMIT 1"), {"m": mid})
            row = r.fetchone()
            if row is None and u:
                r = await session.execute(text(
                    f"SELECT username, title, msg_id, msg_date, body, ocr FROM {TABLE} "
                    f"WHERE msg_id = :m ORDER BY id DESC LIMIT 1"), {"m": mid})
                row = r.fetchone()
            if row is None:
                return None
            return {
                "username": row[0] or "", "title": row[1] or "", "msg_id": int(row[2] or 0),
                "date": row[3], "body": row[4] or "", "ocr": row[5] or "",
            }
    except Exception as exc:  # noqa: BLE001
        logger.info("[CH-ARCH] fetch_msg: %s", exc)
        return None


async def stats() -> dict:
    out: dict = {"total": 0, "channels": []}
    try:
        async with async_session_factory() as session:
            await ensure_table(session)
            r = await session.execute(text(f"SELECT COUNT(*) FROM {TABLE}"))
            out["total"] = int((r.scalar() or 0))
            r2 = await session.execute(text(
                f"SELECT ch_key, MAX(title), COUNT(*), MAX(msg_date), MIN(msg_date) "
                f"FROM {TABLE} GROUP BY ch_key ORDER BY ch_key"))
            for row in r2.fetchall():
                out["channels"].append({
                    "key": row[0], "title": row[1] or "", "n": int(row[2] or 0),
                    "from": row[4], "to": row[3],
                })
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH-DUMP] stats: %s", exc)
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


# --------------------------------------------------------------------------- #
#  Telegram (Telethon) klient
# --------------------------------------------------------------------------- #

async def _own_client():
    """Watcher ishlamasa — vaqtincha o'z klientini yasaydi."""
    from app.services.channel_user import credentials, make_client
    api_id, api_hash, session = await credentials()
    if not (api_id and api_hash and session):
        raise RuntimeError("Telegram akkaunt ulanmagan (api_id/session yo'q)")
    client = make_client(session, api_id, api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise RuntimeError("Telegram sessiya yaroqsiz — /akkaunt orqali qayta ulang")
    return client


async def _get_client():
    """(client, own) — watcher klienti bo'lsa o'sha ishlatiladi."""
    try:
        from app.services import channel_watcher
        c = getattr(channel_watcher, "get_client", None)
        cl = c() if callable(c) else getattr(channel_watcher, "_client", None)
        if cl is not None:
            return cl, False
    except Exception:  # noqa: BLE001
        pass
    return await _own_client(), True


async def _resolve(client, ch: dict):
    uname = (ch.get("username") or "").lstrip("@")
    if uname:
        try:
            return await client.get_entity(uname)
        except Exception as exc:  # noqa: BLE001
            logger.info("[CH-DUMP] @%s entity: %s", uname, exc)
    cid = ch.get("chat_id")
    if cid:
        bare = peer_bare(cid)
        try:
            from telethon.tl.types import PeerChannel
            if bare:
                return await client.get_entity(PeerChannel(int(bare)))
        except Exception:  # noqa: BLE001
            pass
        try:
            return await client.get_entity(int(cid))
        except Exception as exc:  # noqa: BLE001
            logger.info("[CH-DUMP] id %s entity: %s", cid, exc)
    return None


def _msg_body(msg) -> str:
    parts: list[str] = []
    for attr in ("message", "raw_text", "text", "caption"):
        v = getattr(msg, attr, None)
        if v:
            s = str(v).strip()
            if s and s not in parts:
                parts.append(s)
    return "\n".join(parts)


def _reply_to(msg) -> int | None:
    v = getattr(msg, "reply_to_msg_id", None)
    if v is None:
        rt = getattr(msg, "reply_to", None)
        v = getattr(rt, "reply_to_msg_id", None) if rt is not None else None
    try:
        return int(v) if v else None
    except (TypeError, ValueError):
        return None


def _is_video(msg) -> bool:
    if getattr(msg, "video", None) is not None:
        return True
    doc = getattr(msg, "document", None)
    mime = str(getattr(doc, "mime_type", "") or "") if doc is not None else ""
    return mime.startswith("video/")


def _is_photo(msg) -> bool:
    if getattr(msg, "photo", None) is not None:
        return True
    doc = getattr(msg, "document", None)
    mime = str(getattr(doc, "mime_type", "") or "") if doc is not None else ""
    return mime.startswith("image/")


# --------------------------------------------------------------------------- #
#  DUMP
# --------------------------------------------------------------------------- #

async def dump(limit: int = 100, client=None, only: str | None = None,
               with_ocr: bool = True, ocr_max: int = OCR_MAX_DEFAULT,
               progress=None, text_only: bool = False) -> dict:
    """v88: BITTA kanaldan oxirgi `limit` ta xabarni yozadi — rasm matni bilan.

    `only` — kanal kaliti / @username / nom bo'lagi yoki tartib raqami.
    Tanlanmasa: bitta kanal bo'lsa — o'sha; bir nechta bo'lsa — birinchisi
    (handler tugma ko'rsatadi).
    `with_ocr=True` — shu dumpning RASM xabarlari tesseract bilan o'qiladi va
    matni `ocr` ustuniga yoziladi (faylda `[RASM MATNI]` bo'lib chiqadi).
    `text_only=True` (v90) — FAQAT matnli xabarlar olinadi: rasm/video
    yuklanmaydi ham, OCR ham bo'lmaydi -> bir necha sekundda tugaydi (/500).
    """
    from app.services import channel_ocr as _ocr_mod
    from app.services.channel_ocr import ocr_image  # noqa: F401  (borligini tekshirish)
    t0 = time.time()
    limit = max(5, min(int(limit or 100), 200))
    ocr_max = max(0, min(int(ocr_max or 0), 200))
    res: dict = {"limit": limit, "channels": 0, "ok": 0, "fail": [],
                 "saved": 0, "deleted": 0, "per": [], "secs": 0.0,
                 "channel": "", "key": "", "only": (only or ""),
                 "photos": 0, "ocr_limit": ocr_max,
                 "ocr_engine": bool(_ocr_mod.available()),
                 "text_only": bool(text_only),
                 "ocr": {"done": 0, "empty": 0, "fail": 0, "skip": 0, "errors": []}}
    async with _lock:
        try:
            async with async_session_factory() as session:
                await ensure_table(session)
                chans = await list_channels(session)
        except Exception as exc:  # noqa: BLE001
            res["error"] = f"{type(exc).__name__}: {exc}"
            return res
        res["channels"] = len(chans)
        if not chans:
            res["secs"] = round(time.time() - t0, 1)
            return res
        # v88/v89: faqat BITTA kanal (foydalanuvchi aytgani yoki birinchisi)
        choices = as_choices(chans)
        if only:
            picked = match_channel(choices, only)
            if not picked:
                res["error"] = (f"kanal topilmadi: {only} "
                                f"(mavjud: {', '.join(c['name'] for c in choices[:5])})")
                res["secs"] = round(time.time() - t0, 1)
                return res
        else:
            picked = choices[:1]
        sel = picked[0]
        chans = [sel["raw"]]
        res["channel"] = sel["name"]
        res["key"] = sel["key"]

        own = False
        try:
            if client is None:
                client, own = await _get_client()
            for ch in chans:
                name = display_name(ch)
                key = stat_key(ch.get("username"), ch.get("chat_id"))
                try:
                    entity = await _resolve(client, ch)
                    if entity is None:
                        res["fail"].append(name)
                        continue
                    rows: list[dict] = []
                    cap = int(limit) * 3 if text_only else int(limit)
                    async for msg in client.iter_messages(entity, limit=cap):
                        if msg is None:
                            continue
                        mid = int(getattr(msg, "id", 0) or 0)
                        if not mid:
                            continue
                        body = (_msg_body(msg) or "")[:8000]
                        if text_only and not body.strip():
                            continue      # v90: rasm/video o'tkaziladi (faqat matn)
                        dt = getattr(msg, "date", None)
                        rows.append({
                            "ch_key": key,
                            "username": (ch.get("username") or "").lstrip("@")[:64],
                            "title": (ch.get("title") or name)[:160],
                            "msg_id": mid,
                            "msg_date": dt,
                            "body": body,
                            "has_photo": _is_photo(msg),
                            "has_video": _is_video(msg),
                            "grouped_id": getattr(msg, "grouped_id", None),
                            "reply_to": _reply_to(msg),
                            "views": getattr(msg, "views", None),
                        })
                        if text_only and len(rows) >= int(limit):
                            break

                    rows.reverse()  # eski → yangi
                    async with async_session_factory() as session:
                        await ensure_table(session)
                        res["deleted"] += await _delete_channel(session, key)
                        res["saved"] += await _insert_rows(session, rows)
                        await session.commit()
                    n_txt = sum(1 for r in rows if (r["body"] or "").strip())
                    res["ok"] += 1
                    res["per"].append({"name": name, "n": len(rows), "text": n_txt})
                    logger.warning("[CH-DUMP] %s: %d xabar yozildi (%d matnli)",
                                   name, len(rows), n_txt)
                    # v88: RASM ICHIDAGI YOZUV — shu dumpning rasmlari OCR qilinadi
                    photo_ids = [int(r["msg_id"]) for r in rows if r.get("has_photo")]
                    res["photos"] = len(photo_ids)
                    if with_ocr and photo_ids and ocr_max > 0:
                        pick = photo_ids[:ocr_max]
                        if len(photo_ids) > len(pick):
                            logger.warning("[CH-DUMP] OCR chegarasi: %d/%d rasm "
                                           "(qolganini /100ocr bilan o'qish mumkin)",
                                           len(pick), len(photo_ids))
                        res["per"][-1]["ocr_pick"] = len(pick)

                        def _prog(done: int, total: int, nm: str) -> None:
                            if progress is None:
                                return
                            try:
                                progress(done, total, nm)
                            except Exception:  # noqa: BLE001
                                pass

                        await _ocr_ids(client, ch, key, pick, name, res["ocr"],
                                       progress=_prog, total=len(pick))
                        logger.warning("[CH-DUMP] %s OCR: o'qildi %d | bo'sh %d | xato %d",
                                       name, res["ocr"]["done"], res["ocr"]["empty"],
                                       res["ocr"]["fail"])
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[CH-DUMP] %s xato: %s: %s", name, type(exc).__name__, exc)
                    res["fail"].append(f"{name} ({type(exc).__name__})")
        finally:
            if own and client is not None:
                try:
                    await client.disconnect()
                except Exception:  # noqa: BLE001
                    pass
    res["secs"] = round(time.time() - t0, 1)
    _last.update({"ts": datetime.now(timezone.utc).isoformat(), "res": dict(res)})
    return res


def last_dump() -> dict:
    return dict(_last)


# --------------------------------------------------------------------------- #
#  OCR pass (rasm xabarlaridagi yozuvni o'qish)
# --------------------------------------------------------------------------- #

def pick_ocr_ids(rows, per_channel: int = 20, only_key: str | None = None,
                 max_images: int | None = None) -> dict:
    """v90: OCR qilinadigan xabarlarni tanlaydi (sof funksiya — sinov uchun).

    `rows` — (ch_key, msg_id) juftliklari (msg_id DESC tartibda).
    `only_key` — faqat shu kanal; `max_images` — jami shu qadar rasm.
    """
    picked: dict = {}
    total = 0
    for ch_key, mid in rows:
        k = str(ch_key)
        if only_key and k != str(only_key):
            continue
        if max_images and total >= int(max_images):
            break
        lst = picked.setdefault(k, [])
        if len(lst) >= per_channel:
            continue
        lst.append(int(mid))
        total += 1
    return picked


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _state_ddl(session) -> None:
    try:
        await session.execute(text(_DDL_STATE))
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.info("[CH-STATE] jadval: %s", exc)


async def state_begin(limit: int, only: str | None = None) -> None:
    """v90: /100 boshlandi — holat bazaga yoziladi (restart bo'lsa bilinadi)."""
    try:
        async with async_session_factory() as session:
            await _state_ddl(session)
            await session.execute(text(f"DELETE FROM {STATE_TABLE} WHERE id = 1"))
            await session.execute(
                text(f"INSERT INTO {STATE_TABLE} "
                     f"(id, status, stage, note, limit_n, only_key, started, beat) "
                     f"VALUES (1, :s, :g, '', :l, :o, :a, :a)"),
                {"s": "running", "g": "boshlandi", "l": int(limit or 0),
                 "o": str(only or "")[:64], "a": _now_iso()},
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.info("[CH-STATE] begin: %s", exc)


async def state_beat(stage: str, note: str = "") -> None:
    """v90: «tirik» belgisi — jarayon ishlab turgani ko'rinadi."""
    try:
        async with async_session_factory() as session:
            await _state_ddl(session)
            await session.execute(
                text(f"UPDATE {STATE_TABLE} SET stage = :g, note = :n, beat = :a WHERE id = 1"),
                {"g": str(stage)[:120], "n": str(note)[:240], "a": _now_iso()},
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.info("[CH-STATE] beat: %s", exc)


async def state_end(status: str, note: str = "") -> None:
    """v90: «tayyor» / «uzildi» / «xato»."""
    try:
        async with async_session_factory() as session:
            await _state_ddl(session)
            await session.execute(
                text(f"UPDATE {STATE_TABLE} SET status = :s, note = :n, beat = :a WHERE id = 1"),
                {"s": str(status)[:24], "n": str(note)[:240], "a": _now_iso()},
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.info("[CH-STATE] end: %s", exc)


def state_age_s(st: dict | None) -> float:
    """Oxirgi «tirik» belgisidan beri o'tgan sekund (o'qib bo'lmasa — 0)."""
    v = (st or {}).get("beat") or (st or {}).get("started")
    if not v:
        return 0.0
    try:
        if isinstance(v, str):
            t = datetime.fromisoformat(v.replace("Z", "+00:00"))
        else:
            t = v
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - t).total_seconds())
    except Exception:  # noqa: BLE001
        return 0.0


async def state_get() -> dict:
    """v90: oxirgi /100 holati (bo'lmasa — bo'sh dict)."""
    out: dict = {}
    try:
        async with async_session_factory() as session:
            await _state_ddl(session)
            r = (await session.execute(text(
                f"SELECT status, stage, note, limit_n, only_key, started, beat "
                f"FROM {STATE_TABLE} WHERE id = 1"))).fetchone()
        if r:
            out = {"status": r[0], "stage": r[1], "note": r[2], "limit": r[3],
                   "only": r[4], "started": r[5], "beat": r[6]}
            out["age_s"] = state_age_s(out)
    except Exception as exc:  # noqa: BLE001
        logger.info("[CH-STATE] get: %s", exc)
    return out


async def ocr_pending(ch_key: str | None = None) -> int:
    """v90: hali o'qilmagan rasm xabarlari soni (ixtiyoriy: bitta kanal)."""
    try:
        async with async_session_factory() as session:
            await ensure_table(session)
            sql = (f"SELECT COUNT(*) FROM {TABLE} WHERE has_photo IS TRUE "
                   f"AND (ocr IS NULL OR ocr = '')")
            prm: dict = {}
            if ch_key:
                sql += " AND ch_key = :k"
                prm["k"] = ch_key
            return int((await session.execute(text(sql), prm)).scalar() or 0)
    except Exception as exc:  # noqa: BLE001
        logger.info("[CH-STATE] pending: %s", exc)
        return 0


async def ocr_pass(per_channel: int = 20, client=None, progress=None,
                   only_key: str | None = None, max_images: int | None = None) -> dict:
    """Rasm xabarlarini tesseract bilan o'qib, `ocr` ustuniga yozadi.

    v48: har kanal uchun bitta API chaqiruvida xabarlar olinadi (get_messages ids=[...]),
    jarayon `progress(done, total, text)` orqali bildiriladi, xatolar namuna bilan qaytadi.
    v90: `only_key` — faqat shu kanal; `max_images` — jami shu qadar rasm o'qiladi.
    """
    from app.services.channel_ocr import ocr_image

    out = {"done": 0, "empty": 0, "fail": 0, "skip": 0, "secs": 0.0,
           "errors": [], "per": [], "total": 0}
    t0 = time.time()
    per_channel = max(1, min(int(per_channel or 20), 100))

    async with _lock:
        # 1) OCR kerak bo'lgan qatorlar (rasm, hali o'qilmagan)
        try:
            async with async_session_factory() as session:
                await ensure_table(session)
                rows = (await session.execute(text(
                    f"SELECT ch_key, msg_id FROM {TABLE} "
                    f"WHERE has_photo IS TRUE AND (ocr IS NULL OR ocr = '') "
                    f"ORDER BY ch_key, msg_id DESC"))).fetchall()
        except Exception as exc:  # noqa: BLE001
            out["error"] = f"{type(exc).__name__}: {exc}"
            return out

        picked = pick_ocr_ids(rows, per_channel=per_channel, only_key=only_key,
                              max_images=max_images)
        out["total"] = sum(len(v) for v in picked.values())
        if not out["total"]:
            out["secs"] = round(time.time() - t0, 1)
            return out

        # 2) klient
        own = False
        try:
            if client is None:
                client, own = await _get_client()
        except Exception as exc:  # noqa: BLE001
            out["error"] = f"{type(exc).__name__}: {exc}"
            return out

        try:
            async with async_session_factory() as session:
                chans = await list_channels(session)
            ent = {stat_key(c.get("username"), c.get("chat_id")): c for c in chans}

            done_all = 0
            for ch_key, ids in picked.items():
                ch = ent.get(ch_key)
                name = display_name(ch) if ch else ch_key
                stat = await _ocr_ids(client, ch, ch_key, ids, name, out,
                                      progress=progress, done_base=done_all,
                                      total=out["total"])
                done_all += stat["n"]
                out["per"].append(stat)
        except Exception as exc:  # noqa: BLE001
            out["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            if own and client is not None:
                try:
                    await client.disconnect()
                except Exception:  # noqa: BLE001
                    pass
    out["secs"] = round(time.time() - t0, 1)
    return out


async def _mark_ocr(ch_key: str, msg_id: int, ocr: str) -> None:
    """OCR natijasini yozadi (bo'sh bo'lsa '—' — qayta urinmaslik uchun)."""
    try:
        async with async_session_factory() as session:
            await session.execute(
                text(f"UPDATE {TABLE} SET ocr = :o WHERE ch_key = :k AND msg_id = :m"),
                {"o": (ocr or "\u2014")[:4000], "k": ch_key, "m": int(msg_id)},
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.info("[CH-OCR] yozish %s#%s: %s", ch_key, msg_id, exc)


async def test_one(limit_channel: int = 0, client=None) -> dict:
    """Diagnostika: tesseract + baza + klient + 1 rasmni sinab ko'rish."""
    import shutil as _sh

    rep: dict = {"steps": []}

    def add(ok: bool, text: str) -> None:
        rep["steps"].append(("ok" if ok else "xato") + ": " + text)

    tp = ""
    try:
        from app.services import channel_ocr as _oc
        tp = getattr(_oc, "_TESS_EXE", "") or (_sh.which("tesseract") or "")
    except Exception as exc:  # noqa: BLE001
        add(False, f"OCR moduli: {type(exc).__name__}: {exc}")
    rep["tesseract"] = tp
    add(bool(tp), f"tesseract: {tp or 'TOPILMADI'}")

    need = 0
    try:
        async with async_session_factory() as session:
            await ensure_table(session)
            r = await session.execute(text(
                f"SELECT COUNT(*) FROM {TABLE} WHERE has_photo IS TRUE AND (ocr IS NULL OR ocr = '')"))
            need = int(r.scalar() or 0)
            r2 = await session.execute(text(f"SELECT COUNT(*) FROM {TABLE}"))
            rep["rows"] = int(r2.scalar() or 0)
        add(True, f"bazada: {rep['rows']} xabar | OCR kutayotgan rasm: {need}")
    except Exception as exc:  # noqa: BLE001
        add(False, f"baza: {type(exc).__name__}: {exc}")

    try:
        cl, own = (client, False) if client is not None else await _get_client()
        add(True, "Telegram klient: " + ("watcher klienti" if not own else "vaqtincha yangi klient"))
        async with async_session_factory() as session:
            chans = await list_channels(session)
        add(bool(chans), f"kanallar: {len(chans)}")
        picked = None
        async with async_session_factory() as session:
            for c in chans:
                k = stat_key(c.get("username"), c.get("chat_id"))
                r = (await session.execute(text(
                    f"SELECT msg_id FROM {TABLE} WHERE ch_key = :k AND has_photo IS TRUE "
                    f"AND (ocr IS NULL OR ocr = '') ORDER BY msg_id DESC LIMIT 1"), {"k": k})).fetchone()
                if r:
                    picked = (c, int(r[0]))
                    break
        if not picked:
            add(False, "sinov uchun rasm topilmadi (OCR allaqachon bajarilgan bo'lishi mumkin)")
            return rep
        c, mid = picked
        entity = await _resolve(cl, c)
        add(entity is not None, f"sinov kanali: {display_name(c)} | xabar #{mid}")
        if entity is None:
            return rep
        m = await cl.get_messages(entity, ids=mid)
        if isinstance(m, (list, tuple)):
            m = m[0] if m else None
        if m is None:
            add(False, "xabar topilmadi (o'chirilgan?)")
            return rep
        buf = io.BytesIO()
        got = await m.download_media(file=buf)
        data = got if isinstance(got, (bytes, bytearray)) else buf.getvalue()
        add(bool(data), f"rasm yuklandi: {len(data or b'')} bayt")
        if data:
            t0 = time.time()
            from app.services.channel_ocr import ocr_image
            txt = (await asyncio.to_thread(ocr_image, bytes(data)) or "").strip()
            add(bool(txt), f"OCR {time.time() - t0:.1f}s → {len(txt)} belgi. "
                           f"Boshi: {(txt[:100] or '(bo\'sh)')}")
        if own:
            try:
                await cl.disconnect()
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        add(False, f"klient/sinov: {type(exc).__name__}: {exc}")
    return rep


# --------------------------------------------------------------------------- #
#  EXPORT (adminga .txt fayl)
# --------------------------------------------------------------------------- #

def _fmt_date(v) -> str:
    """Sana — TOSHKENT vaqti bilan (UTC saqlanadi, ko'rsatish mahalliy)."""
    if v is None:
        return "?"
    if isinstance(v, str):
        return v[:16].replace("T", " ")
    try:
        return to_tashkent(v).strftime("%Y-%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        try:
            return v.strftime("%Y-%m-%d %H:%M")
        except Exception:  # noqa: BLE001
            return str(v)[:16]


async def export_txt(only: str | None = None) -> tuple[str, bytes]:
    """(fayl nomi, baytlar) — yozilgan xabarlar, kanal bo'yicha.

    v88: `only` berilsa — faqat shu kanal. Har bir rasm ostida uning ICHIDAGI
    YOZUV `[RASM MATNI]` blokida chiqadi (tesseract o'qigan matn).
    """
    lines: list[str] = []
    lines.append("SINO KANAL XABARLARI (oxirgi dump)")
    lines.append(f"Vaqt: {stamp_tashkent()} (Toshkent)")
    lines.append("Format: [msg_id] sana | bayroqlar | reply")
    lines.append("Rasm ostidagi [RASM MATNI] — rasm ichidagi yozuv (OCR, tesseract)")
    lines.append("=" * 78)
    only_key = ""
    if only:
        try:
            chans = await channel_choices()
            hit = match_channel(chans, only)
            only_key = hit[0]["key"] if hit else ""
        except Exception:  # noqa: BLE001
            only_key = ""
    try:
        async with async_session_factory() as session:
            await ensure_table(session)
            r = await session.execute(text(
                f"SELECT ch_key, MAX(title) FROM {TABLE} GROUP BY ch_key ORDER BY ch_key"))
            keys = r.fetchall()
            for ch_key, title in keys:
                if only_key and str(ch_key) != only_key:
                    continue
                rr = (await session.execute(text(
                    f"SELECT msg_id, msg_date, body, ocr, has_photo, has_video, reply_to, views "
                    f"FROM {TABLE} WHERE ch_key = :k ORDER BY msg_id"), {"k": ch_key})).fetchall()
                n_img = sum(1 for x in rr if x[4])
                n_ocr = sum(1 for x in rr if str(x[3] or "").strip()
                            and str(x[3]).strip() not in ("\u2014", "-"))
                lines.append("")
                lines.append(f"########## {title or ch_key}  ({ch_key}) \u2014 {len(rr)} ta xabar "
                             f"\u00b7 rasm: {n_img} \u00b7 rasm matni o'qildi: {n_ocr} "
                             f"##########")
                for mid, dt, body, ocr, ph, vi, rep, views in rr:
                    flags = []
                    if ph:
                        flags.append("RASM")
                    if vi:
                        flags.append("VIDEO")
                    if rep:
                        flags.append(f"reply->{rep}")
                    if views:
                        flags.append(f"{int(views)} ko'rish")
                    lines.append("")
                    lines.append(f"[{mid}] {_fmt_date(dt)} | " + " | ".join(flags))
                    body = (body or "").strip()
                    if body:
                        lines.append(f"[MATN] {body}")
                    ocr_s = str(ocr or "").strip()
                    if ocr_s and ocr_s not in ("\u2014", "-"):
                        lines.append(f"[RASM MATNI] {ocr_s}")
                    elif ph:
                        lines.append("[RASM MATNI] (o'qilmadi \u2014 /100ocr yuboring)")
                    elif not body:
                        lines.append("(matn yo'q)")
                    lines.append("-" * 60)
    except Exception as exc:  # noqa: BLE001
        lines.append(f"XATO: {type(exc).__name__}: {exc}")
    data = ("\n".join(lines) + "\n").encode("utf-8")
    name = f"sino_kanallar_{to_tashkent().strftime('%Y%m%d_%H%M')}.txt"
    return name, data
