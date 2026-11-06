"""Faqat 📡 Kanallar ro'yxatidagi kanallarni o'qiydi.

Botni kanalga qo'shish shart emas — user akkaunt (Telethon).
Global NewMessage YO'Q (ulanmagan kanal oqmasin).
Asosiy: har 8 soniyada poll. Qo'shimcha: listed entity event.
"""
from __future__ import annotations

import asyncio
import io
from datetime import datetime, timezone

from app.core.logging import get_logger
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
    "last_error": "",
    "seen": 0,
    "signals": 0,
    "channels_ok": [],
    "channels_fail": [],
    "recent": [],
}


def get_client():
    """Faol Telethon klienti (yozib olish/dump uchun)."""
    return _client


def get_status() -> dict:
    return dict(_status)


def _note(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} {msg}"
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
        return
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
            n_new = 0
            for msg in batch:
                await _process_msg(msg, ch)
                n_new += 1
            if n_new:
                _note(f"yangi {n_new} ta {display_name(ch)}")
            elif first and last <= 0:
                newest = 0
                for m in batch:
                    newest = max(newest, int(getattr(m, "id", 0) or 0))
                if newest:
                    async with async_session_factory() as session:
                        await touch_channel(
                            session, username=ch.get("username"),
                            chat_id=ch.get("chat_id"),
                            title=ch.get("title") or "",
                            last_msg_id=newest,
                        )
                    ch["last_msg_id"] = newest
                    _note(f"watermark {display_name(ch)} #{newest}")
            if key:
                _catchup.add(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CH-WATCH] %s o'qish: %s", ch.get("username"), exc)
            fail.append(display_name(ch))
            await _try_join(client, entity)
    _status["channels_ok"] = ok
    _status["channels_fail"] = fail
    _status["last_poll"] = datetime.now(timezone.utc).isoformat()


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
                        "Tuzatish: <b>/akkaunt</b> → api_id → api_hash → telefon → kod."
                    )
                    logger.warning("[CH-WATCH] sessiya o'chgan — adminga xabar berildi")
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
                    await asyncio.sleep(8)

            poll_task = asyncio.create_task(_poll_loop(), name="ch-poll")
            try:
                await client.run_until_disconnected()
            finally:
                poll_task.cancel()
                try:
                    await poll_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            _client = None
        except Exception as exc:  # noqa: BLE001
            logger.exception("[CH-WATCH] %s", exc)
            _status["last_error"] = str(exc)[:200]
            _client = None
            await asyncio.sleep(20)
