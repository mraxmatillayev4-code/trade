"""Faqat 📡 Kanallar ro'yxatidagi kanallarni o'qiydi.

Botni kanalga qo'shish shart emas — user akkaunt (Telethon).
Global NewMessage YO'Q (ulanmagan kanal oqmasin).
TEZKOR rejim: yangi xabar kelishi bilan EVENT orqali DARHOL o'qiladi (0 kutish),
zaxira yo'l — har 2 soniyada poll (sekin internet/blokda ham signal kechikmaydi).
"""
from __future__ import annotations

import asyncio
import io
import time
from datetime import datetime, timezone

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.timeuz import hms_tashkent, stamp_tashkent
from app.database.session import async_session_factory
from app.services.channel_inbox import ingest_raw, ping_admin
from app.services.channel_store import (
    display_name,
    list_channels,
    match_channel,
    peer_bare,
    touch_channel,
)
from app.services.channel_user import credentials, make_client

logger = get_logger(__name__)

_POLL_SECONDS = 2.0   # v57: tezkor poll (avval 8 s edi)

_client = None
_task: asyncio.Task | None = None
_stop = False
_catchup: set[str] = set()
_alerted = False
_status: dict = {
    "linked": False,
    "authorized": False,
    "account": "",
    "last_poll": "",
    "last_poll_local": "",
    "last_error": "",
    "seen": 0,
    "signals": 0,
    "channels_ok": [],
    "channels_fail": [],
    "recent": [],
    "poll_seconds": _POLL_SECONDS,
}


# --------------------------------------------------------------------------- #
#  v93: YETAKCHI QULFI — Telegram sessiyasi FAQAT BITTA jarayondan ishlatiladi
# --------------------------------------------------------------------------- #
# Nega: Render yangi versiyani ishga tushirganda ESLI nusxa ham bir necha
# sekund/yuzlab sekund ishlab turadi. Ikkala nusxa BITTA Telegram sessiyasi
# bilan ulansa, Telegram buni shubhali deb topadi va sessiyani BEKOR QILADI —
# shu sababli har yangilanishdan keyin "akkaunt chiqib ketardi". Endi faqat
# qulfni ushlab turgan nusxa ulanadi; ikkinchisi kutadi.
LEADER_COMPONENT = "tg_leader"
LEADER_TTL_S = 120.0        # yurak urishi shuncha sekunddan eski bo'lsa qulf bo'sh
LEADER_RENEW_S = 30.0       # qulfni yangilash oralig'i


def _owner_id() -> str:
    import os
    import socket
    try:
        host = socket.gethostname()
    except Exception:  # noqa: BLE001
        host = "host"
    return f"{host}:{os.getpid()}"


async def _leader_read() -> dict:
    try:
        from app.services.channel_store import load_json_log
        async with async_session_factory() as db:
            row = await load_json_log(db, LEADER_COMPONENT)
        return dict(row or {})
    except Exception as exc:  # noqa: BLE001
        logger.debug("[CH-WATCH] qulf o'qilmadi: %s", exc)
        return {}


async def _leader_write(owner: str) -> None:
    try:
        from app.services.channel_store import save_json_log
        async with async_session_factory() as db:
            await save_json_log(db, LEADER_COMPONENT,
                                {"owner": owner, "ts": time.time(),
                                 "since": time.time()})
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH-WATCH] qulf yozilmadi: %s", exc)


async def acquire_leader(owner: str) -> tuple[bool, str]:
    """Qulfni olish. (True, "") bo'lsa ulanish mumkin; aks holda (False, sabab)."""
    row = await _leader_read()
    cur = str(row.get("owner") or "")
    ts = float(row.get("ts") or 0.0)
    age = time.time() - ts if ts else 1e9
    if cur and cur != owner and age < LEADER_TTL_S:
        return False, (f"boshqa nusxa faol ({cur}, {int(age)} s oldin yangilangan) "
                       "— sessiya ikki joydan ishlatilmasin")
    await _leader_write(owner)
    return True, ""


async def renew_leader(owner: str) -> bool:
    """Qulfni yangilaydi; boshqasi egallab olgan bo'lsa False."""
    row = await _leader_read()
    cur = str(row.get("owner") or "")
    if cur and cur != owner:
        ts = float(row.get("ts") or 0.0)
        if time.time() - ts < LEADER_TTL_S:
            return False
    await _leader_write(owner)
    return True


async def release_leader(owner: str) -> None:
    row = await _leader_read()
    if str(row.get("owner") or "") == owner:
        try:
            from app.services.channel_store import save_json_log
            async with async_session_factory() as db:
                await save_json_log(db, LEADER_COMPONENT, {"owner": "", "ts": 0.0})
        except Exception:  # noqa: BLE001
            pass


async def _leader_loop(owner: str) -> None:
    """Ulangan paytda qulfni har 30 s da yangilab turadi."""
    while not _stop and _client is not None:
        await asyncio.sleep(LEADER_RENEW_S)
        try:
            ok = await renew_leader(owner)
        except Exception:  # noqa: BLE001
            ok = True
        if not ok:
            logger.warning("[CH-WATCH] qulf boshqa nusxaga o'tdi — uzilamiz")
            _note("qulf boshqa nusxada — bu nusxa uzildi")
            try:
                if _client is not None:
                    await _client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            return


def get_client():
    """Faol Telethon klienti (yozib olish/dump uchun)."""
    return _client


def get_status() -> dict:
    return dict(_status)


_last_note_msg = ""
_last_note_at = 0.0
_last_note_repeat = 0


def _note(msg: str) -> None:
    """Holat qatori — TO'SHKENT vaqti bilan; bir xil satr 60 s ichida takrorlanmaydi."""
    global _last_note_msg, _last_note_at, _last_note_repeat
    now = time.monotonic()
    if msg == _last_note_msg and (now - _last_note_at) < 60:
        _last_note_repeat += 1
        _last_note_at = now
        return
    extra = f" (yuqoridagi {_last_note_repeat} marta takrori yashirildi)" if _last_note_repeat else ""
    _last_note_msg = msg
    _last_note_at = now
    _last_note_repeat = 0
    line = f"{hms_tashkent()} {msg}{extra}"
    rec = list(_status.get("recent") or [])
    rec.insert(0, line)
    _status["recent"] = rec[:24]
    logger.info("[CH-WATCH] %s", msg)


async def start_watcher() -> None:
    global _task, _stop
    _stop = False
    if _task and not _task.done():
        return
    _task = asyncio.create_task(_run(), name="ch-watch")


async def stop_watcher() -> None:
    global _stop, _client
    _stop = True
    if _client is not None:
        try:
            await _client.disconnect()
        except Exception:  # noqa: BLE001
            pass
        _client = None


async def restart_watcher() -> None:
    global _catchup, _alerted
    _catchup = set()
    _alerted = False
    await stop_watcher()
    await asyncio.sleep(0.4)
    await start_watcher()


def _msg_text(msg) -> str:
    parts: list[str] = []
    for attr in ("message", "raw_text", "text", "caption"):
        v = getattr(msg, attr, None)
        if v:
            s = str(v).strip()
            if s and s not in parts:
                parts.append(s)
    return "\n".join(parts)


def _is_image_msg(msg) -> bool:
    if getattr(msg, "photo", None) is not None:
        return True
    doc = getattr(msg, "document", None)
    mime = str(getattr(doc, "mime_type", "") or "") if doc is not None else ""
    if mime.startswith("image/"):
        return True
    return False


async def _download_image(msg) -> bytes | None:
    if not _is_image_msg(msg):
        return None
    try:
        buf = io.BytesIO()
        out = await msg.download_media(file=buf)
        if isinstance(out, (bytes, bytearray)):
            return bytes(out) if out else None
        data = buf.getvalue()
        return data or None
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH-WATCH] rasm: %s", exc)
        return None


def _chat_id_of(chat) -> int | None:
    if chat is None:
        return None
    try:
        from telethon.utils import get_peer_id
        return int(get_peer_id(chat))
    except Exception:  # noqa: BLE001
        pass
    try:
        n = int(getattr(chat, "id", 0) or 0)
        return n or None
    except (TypeError, ValueError):
        return None


async def _process_msg(msg, ch: dict) -> None:
    mid = int(getattr(msg, "id", 0) or 0)
    last = int(ch.get("last_msg_id") or 0)
    if mid and last and mid <= last:
        return
    text = _msg_text(msg)
    img = await _download_image(msg)
    chat = getattr(msg, "chat", None)
    if chat is None:
        try:
            chat = await msg.get_chat()
        except Exception:  # noqa: BLE001
            chat = None
    chat_id = _chat_id_of(chat) or ch.get("chat_id")
    title = (getattr(chat, "title", None) or "") if chat is not None else (ch.get("title") or "")
    username = getattr(chat, "username", None) if chat is not None else None
    username = username or ch.get("username")
    snippet = (text or "").replace("\n", " ")[:80]
    _status["seen"] = int(_status.get("seen") or 0) + 1
    _note(f"#{mid} {display_name(ch)} rasm={bool(img)} {snippet or '(bosh)'}")
    gid = getattr(msg, "grouped_id", None)
    reply_to = getattr(msg, "reply_to_msg_id", None)
    try:
        if reply_to is None:
            rt = getattr(msg, "reply_to", None)
            reply_to = getattr(rt, "reply_to_msg_id", None) if rt is not None else None
        if reply_to is not None:
            reply_to = int(reply_to)
    except (TypeError, ValueError):
        reply_to = None
    await ingest_raw(
        ch=ch, text=text, image_bytes=img,
        msg_id=mid, chat_id=chat_id, title=title, username=username,
        notify_verdict=False, grouped_id=gid, reply_to=reply_to,
        require_listed=True,
        posted_at=getattr(msg, "date", None),   # v81: post qachon tashlangan
    )
    async with async_session_factory() as session:
        await touch_channel(
            session, username=username, chat_id=chat_id,
            title=title, last_msg_id=mid,
        )
        ch["last_msg_id"] = max(last, mid)


async def _resolve(client, ch: dict):
    username = (ch.get("username") or "").lstrip("@")
    chat_id = ch.get("chat_id")
    try:
        if username:
            return await client.get_entity(username)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH-WATCH] entity @%s: %s", username, exc)
    if chat_id:
        bare = peer_bare(chat_id)
        try:
            from telethon.tl.types import PeerChannel
            if bare:
                return await client.get_entity(PeerChannel(int(bare)))
        except Exception:  # noqa: BLE001
            pass
        try:
            return await client.get_entity(int(chat_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CH-WATCH] entity id %s: %s", chat_id, exc)
    try:
        uname = username.lower() if username else ""
        want = peer_bare(chat_id) if chat_id else None
        async for d in client.iter_dialogs(limit=80):
            ent = d.entity
            eu = (getattr(ent, "username", None) or "").lower()
            if uname and eu == uname:
                return ent
            if want is not None and peer_bare(getattr(ent, "id", None)) == want:
                return ent
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH-WATCH] dialog: %s", exc)
    return None


async def _try_join(client, entity) -> None:
    try:
        from telethon.tl.functions.channels import JoinChannelRequest
        await client(JoinChannelRequest(entity))
    except Exception:  # noqa: BLE001
        pass


async def _poll_once(client) -> None:
    async with async_session_factory() as session:
        channels = await list_channels(session)
    ok, fail = [], []
    if not channels:
        _note("kanal ro'yxati bo'sh — 📡 Kanallar → ➕ Qo'shish")
        _status["channels_ok"] = []
        _status["channels_fail"] = []
        _status["last_poll"] = datetime.now(timezone.utc).isoformat()
        _status["last_poll_local"] = stamp_tashkent()
        return
    catchup_n = 0
    try:
        catchup_n = int(getattr(get_settings(), "channel_catchup_count", 0) or 0)
    except Exception:  # noqa: BLE001
        catchup_n = 0
    for ch in channels:
        entity = await _resolve(client, ch)
        if entity is None:
            fail.append(display_name(ch))
            continue
        ok.append(display_name(ch))
        last = int(ch.get("last_msg_id") or 0)
        key = str(ch.get("username") or ch.get("chat_id") or "")
        first = key not in _catchup
        try:
            batch = []
            async for msg in client.iter_messages(entity, limit=25):
                if msg is None:
                    continue
                mid = int(getattr(msg, "id", 0) or 0)
                if last and mid <= last:
                    break
                batch.append(msg)
            batch.reverse()

            if not last:
                # v56: bu kanalda suv belgisi yo'q (yangi ulandi) — TARIX O'QILMAYDI.
                # Aks holda bot 25 ta eski postni "signal" deb qayta ishlab yuborardi.
                newest = 0
                for m in batch:
                    newest = max(newest, int(getattr(m, "id", 0) or 0))
                if catchup_n > 0 and batch:
                    for msg in batch[-catchup_n:]:
                        await _process_msg(msg, ch)
                if newest:
                    async with async_session_factory() as session:
                        await touch_channel(
                            session, username=ch.get("username"),
                            chat_id=ch.get("chat_id"),
                            title=ch.get("title") or "",
                            last_msg_id=newest,
                        )
                    ch["last_msg_id"] = newest
                _note(f"suv belgisi {display_name(ch)} #{newest} "
                      f"(tarix o'qilmadi: {len(batch)} ta eski xabar)")
                if key:
                    _catchup.add(key)
                continue

            n_new = 0
            for msg in batch:
                await _process_msg(msg, ch)
                n_new += 1
            if n_new:
                _note(f"yangi {n_new} ta {display_name(ch)}")
            if key:
                _catchup.add(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CH-WATCH] %s o'qish: %s", ch.get("username"), exc)
            fail.append(display_name(ch))
            await _try_join(client, entity)
    _status["channels_ok"] = ok
    _status["channels_fail"] = fail
    _status["last_poll"] = datetime.now(timezone.utc).isoformat()
    _status["last_poll_local"] = stamp_tashkent()


async def _on_listed(event) -> None:
    """Faqat listed entity event — boshqa chatlar kelmaydi."""
    try:
        msg = getattr(event, "message", None) or event
        chat = None
        try:
            chat = await event.get_chat()
        except Exception:  # noqa: BLE001
            chat = getattr(msg, "chat", None)
        username = getattr(chat, "username", None) if chat is not None else None
        chat_id = _chat_id_of(chat)
        async with async_session_factory() as session:
            ch = await match_channel(session, chat_id=chat_id, username=username)
        if ch is None:
            return
        await _process_msg(msg, ch)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[CH-WATCH] event: %s", exc)
        _status["last_error"] = str(exc)[:200]


async def _run() -> None:
    global _client, _alerted
    await asyncio.sleep(3)
    while not _stop:
        api_id, api_hash, session = await credentials()
        _status["linked"] = bool(api_id and api_hash and session)
        if not api_id or not api_hash or not session:
            _status["authorized"] = False
            _note("akkaunt ulanmagan — /akkaunt")
            if not _alerted:
                _alerted = True
                await ping_admin(
                    "Akkaunt ulanmagan — kanallar o'qilmaydi. /akkaunt bosing "
                    "YOKI signalni botga forward qiling."
                )
            await asyncio.sleep(45)
            continue
        # v93: avval qulfni olamiz (ikki nusxa bir sessiyani ishlatmasin)
        _own = _owner_id()
        _got, _why = await acquire_leader(_own)
        if not _got:
            _status["authorized"] = False
            _note(_why)
            _status["last_error"] = _why
            logger.info("[CH-WATCH] %s", _why)
            await asyncio.sleep(30)
            continue
        try:
            from telethon import events
            client = make_client(session, int(api_id), api_hash)
            await client.connect()
            if not await client.is_user_authorized():
                _status["authorized"] = False
                _note("sessiya yaroqsiz — /akkaunt")
                if not _alerted:
                    _alerted = True
                    await ping_admin(
                        "\u26A0\uFE0F <b>Telegram akkaunt sessiyasi o'chgan.</b>\n"
                        "Telegram uni bekor qilgan (chiqib ketgan) — kanallar o'qilmayapti.\n"
                        "Tuzatish: <b>/qr</b> (yoki <b>/akkaunt</b>) — bir marta ulang.\n\n"
                        "<b>SABAB (v93 da tuzatildi):</b> sessiya bir vaqtda IKKI joydan\n"
                        "ishlatilgan bo'lsa Telegram uni o'chiradi. Endi bot qulf ishlatadi:\n"
                        "yangi versiya chiqqanda faqat BITTA nusxa ulanadi.\n"
                        "Shuning uchun botni kompyuterda va Render'da BIR VAQTDA\n"
                        "ishlatmang — kanallar o'qilmay qoladi."
                    )
                    logger.warning("[CH-WATCH] sessiya o'chgan — adminga xabar berildi")
                await release_leader(_own)
                await client.disconnect()
                await asyncio.sleep(90)
                continue
            _alerted = False
            _status["authorized"] = True
            me = await client.get_me()
            uname = getattr(me, "username", "") or ""
            _status["account"] = f"@{uname}" if uname else str(getattr(me, "id", ""))
            _client = client

            entities = []
            async with async_session_factory() as db:
                for ch in await list_channels(db):
                    ent = await _resolve(client, ch)
                    if ent is not None:
                        await _try_join(client, ent)
                        entities.append(ent)
                    else:
                        _note(f"topilmadi: {display_name(ch)}")
            _note(f"akkaunt {_status['account']} — {len(entities)} kanal")

            if entities:
                client.add_event_handler(
                    _on_listed, events.NewMessage(chats=entities, incoming=True),
                )

            async def _poll_loop() -> None:
                while not _stop and client.is_connected():
                    try:
                        await _poll_once(client)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("[CH-WATCH] poll: %s", exc)
                        _status["last_error"] = str(exc)[:200]
                        # v101: kalit duplikati — tashqi loop qayta ulaydi
                        if "AuthKey" in type(exc).__name__:
                            logger.error("[CH-WATCH] v101 AuthKey — reconnect")
                            try:
                                await client.disconnect()
                            except Exception:  # noqa: BLE001
                                pass
                            break
                    # v57: TEZKOR rejim — 2 s (bozor tez, kechikish xavf)
                    await asyncio.sleep(_POLL_SECONDS)

            poll_task = asyncio.create_task(_poll_loop(), name="ch-poll")
            lead_task = asyncio.create_task(_leader_loop(_own), name="ch-leader")
            try:
                await client.run_until_disconnected()
            except Exception as exc:  # noqa: BLE001
                # v101: aloqa uzilsa ham task o'lmaydi — tashqi loop qayta ulaydi
                logger.warning("[CH-WATCH] v101 aloqa uzildi: %s — qayta "
                               "ulanaman", type(exc).__name__)
            finally:
                poll_task.cancel()
                lead_task.cancel()
                for _t in (poll_task, lead_task):
                    try:
                        await _t
                    except (asyncio.CancelledError, Exception):  # noqa: BLE001
                        pass
                try:
                    await release_leader(_own)
                except Exception:  # noqa: BLE001
                    pass
            _client = None
        except Exception as exc:  # noqa: BLE001
            logger.exception("[CH-WATCH] %s", exc)
            _status["last_error"] = str(exc)[:200]
            _client = None
            await asyncio.sleep(20)
