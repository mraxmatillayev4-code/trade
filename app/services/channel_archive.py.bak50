"""Kanal xabarlarini bazaga yozib olish — /100 buyrug'i uchun.

Nima qiladi:
  dump(limit=100)      — barcha ulangan kanallardan oxirgi `limit` ta xabarni oladi
                         (reply lar, rasm/video belgilari bilan) va bazaga yozadi.
                         Har kanal uchun ESKI yozuvlar O'CHIRILADI, keyin yangisi yoziladi.
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

async def dump(limit: int = 100, client=None) -> dict:
    """Barcha kanallardan oxirgi `limit` ta xabarni bazaga yozadi (eskisini o'chirib)."""
    t0 = time.time()
    limit = max(5, min(int(limit or 100), 500))
    res: dict = {"limit": limit, "channels": 0, "ok": 0, "fail": [],
                 "saved": 0, "deleted": 0, "per": [], "secs": 0.0}
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
                    async for msg in client.iter_messages(entity, limit=limit):
                        if msg is None:
                            continue
                        mid = int(getattr(msg, "id", 0) or 0)
                        if not mid:
                            continue
                        dt = getattr(msg, "date", None)
                        rows.append({
                            "ch_key": key,
                            "username": (ch.get("username") or "").lstrip("@")[:64],
                            "title": (ch.get("title") or name)[:160],
                            "msg_id": mid,
                            "msg_date": dt,
                            "body": (_msg_body(msg) or "")[:8000],
                            "has_photo": _is_photo(msg),
                            "has_video": _is_video(msg),
                            "grouped_id": getattr(msg, "grouped_id", None),
                            "reply_to": _reply_to(msg),
                            "views": getattr(msg, "views", None),
                        })
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

async def ocr_pass(per_channel: int = 20, client=None, progress=None) -> dict:
    """Rasm xabarlarini tesseract bilan o'qib, `ocr` ustuniga yozadi.

    v48: har kanal uchun bitta API chaqiruvida xabarlar olinadi (get_messages ids=[...]),
    jarayon `progress(done, total, text)` orqali bildiriladi, xatolar namuna bilan qaytadi.
    """
    from app.services.channel_ocr import ocr_image

    out = {"done": 0, "empty": 0, "fail": 0, "skip": 0, "secs": 0.0,
           "errors": [], "per": [], "total": 0}
    t0 = time.time()
    per_channel = max(1, min(int(per_channel or 20), 100))

    def _err(msg: str) -> None:
        if len(out["errors"]) < 5:
            out["errors"].append(str(msg)[:200])

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

        picked: dict = {}
        for ch_key, mid in rows:
            lst = picked.setdefault(str(ch_key), [])
            if len(lst) < per_channel:
                lst.append(int(mid))
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
                stat = {"name": name, "n": 0, "done": 0, "empty": 0, "fail": 0}
                if not ch:
                    out["skip"] += len(ids)
                    stat["fail"] = len(ids)
                    out["per"].append(stat)
                    continue
                entity = await _resolve(client, ch)
                if entity is None:
                    out["fail"] += len(ids)
                    stat["fail"] = len(ids)
                    out["per"].append(stat)
                    _err(f"{name}: kanal entity topilmadi (@{ch.get('username')})")
                    continue

                # bitta chaqiruvda barcha kerakli xabarlar
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
                    _err(f"{name}: get_messages {type(exc).__name__}: {exc}")

                missing = [i for i in ids if i not in msgs]
                if missing:
                    try:
                        low = min(missing)
                        async for m in client.iter_messages(entity, limit=len(missing) + 60):
                            mid = int(getattr(m, "id", 0) or 0)
                            if mid and mid not in msgs and mid >= low:
                                msgs[mid] = m
                    except Exception as exc:  # noqa: BLE001
                        _err(f"{name}: iter_messages {type(exc).__name__}: {exc}")

                for mid in ids:
                    stat["n"] += 1
                    done_all += 1
                    msg = msgs.get(mid)
                    if msg is None:
                        out["fail"] += 1
                        stat["fail"] += 1
                        await _mark_ocr(ch_key, mid, "")
                        continue
                    if not (_is_photo(msg) or _is_video(msg)):
                        out["skip"] += 1
                        stat["fail"] += 1
                        await _mark_ocr(ch_key, mid, "")   # media yo'q — qayta urinmaymiz
                        continue
                    try:
                        buf = io.BytesIO()
                        got_b = await msg.download_media(file=buf)
                        data = got_b if isinstance(got_b, (bytes, bytearray)) else buf.getvalue()
                        if not data:
                            raise RuntimeError("rasm yuklanmadi (bo'sh)")
                        try:
                            txt = (ocr_image(bytes(data)) or "").strip()
                        except Exception as exc:  # noqa: BLE001
                            txt = ""
                            _err(f"OCR {name}#{mid}: {type(exc).__name__}: {exc}")
                        if txt:
                            out["done"] += 1
                            stat["done"] += 1
                        else:
                            out["empty"] += 1
                            stat["empty"] += 1
                        await _mark_ocr(ch_key, mid, txt)
                    except Exception as exc:  # noqa: BLE001
                        out["fail"] += 1
                        stat["fail"] += 1
                        _err(f"{name}#{mid}: {type(exc).__name__}: {exc}")
                        await _mark_ocr(ch_key, mid, "")
                    await asyncio.sleep(0.02)
                    if progress is not None and done_all % 5 == 0:
                        try:
                            progress(done_all, out["total"], name)
                        except Exception:  # noqa: BLE001
                            pass
                out["per"].append(stat)
                logger.warning("[CH-OCR] %s: o'qildi %d | bo'sh %d | xato %d",
                               name, stat["done"], stat["empty"], stat["fail"])
                if progress is not None:
                    try:
                        progress(done_all, out["total"], name)
                    except Exception:  # noqa: BLE001
                        pass
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
            txt = (ocr_image(bytes(data)) or "").strip()
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
    if v is None:
        return "?"
    if isinstance(v, str):
        return v[:16].replace("T", " ")
    try:
        return v.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        try:
            return v.strftime("%Y-%m-%d %H:%M")
        except Exception:  # noqa: BLE001
            return str(v)[:16]


async def export_txt() -> tuple[str, bytes]:
    """(fayl nomi, baytlar) — barcha yozilgan xabarlar, kanal bo'yicha."""
    lines: list[str] = []
    lines.append("SINO KANAL XABARLARI (oxirgi dump)")
    lines.append(f"Vaqt: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("Format: [msg_id] sana | bayroqlar | reply")
    lines.append("=" * 78)
    try:
        async with async_session_factory() as session:
            await ensure_table(session)
            r = await session.execute(text(
                f"SELECT ch_key, MAX(title) FROM {TABLE} GROUP BY ch_key ORDER BY ch_key"))
            keys = r.fetchall()
            for ch_key, title in keys:
                rr = (await session.execute(text(
                    f"SELECT msg_id, msg_date, body, ocr, has_photo, has_video, reply_to, views "
                    f"FROM {TABLE} WHERE ch_key = :k ORDER BY msg_id"), {"k": ch_key})).fetchall()
                lines.append("")
                lines.append(f"########## {title or ch_key}  ({ch_key}) — {len(rr)} ta xabar ##########")
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
                    lines.append(body if body else "(matn yo'q)")
                    ocr_s = str(ocr or "").strip()
                    if ocr_s and ocr_s not in ("\u2014", "-"):
                        lines.append(f"OCR: {ocr_s}")
                    lines.append("-" * 60)
    except Exception as exc:  # noqa: BLE001
        lines.append(f"XATO: {type(exc).__name__}: {exc}")
    data = ("\n".join(lines) + "\n").encode("utf-8")
    name = f"sino_kanallar_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.txt"
    return name, data
