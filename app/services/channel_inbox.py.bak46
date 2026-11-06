"""BITTA YO'L: kanal xabari → parse → DB + karta + 2 lot paper.

Hisobotga SIGNAL faqat karta/bitim urinilgandan KEYIN yoziladi.
Eski ochiq signal (CHANNEL yoki yo'q) yangisini BLOKLAMAYDI.
EMAS chatga yuborilmaydi.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings, get_settings
from app.core.enums import Direction, SignalStatus
from app.core.logging import get_logger
from app.core.serialize import dumps as _dumps_json
from app.database import crud
from app.database.models.signal import Signal, SignalConfirmation
from app.database.session import async_session_factory
from app.engine.risk import calculate_levels, r_price
from app.services.channel_parse import (
    apply_levels,
    is_close_message,
    merge_parsed,
    parse_signal,
    ref_from_text,
    snap_parsed,
)
from app.services.channel_store import (
    add_channel,
    bind_chat_id,
    display_name,
    match_channel,
    peer_bare,
    record_read,
    stat_key,
)

logger = get_logger(__name__)

_candles = None
_paper = None
_tracker = None
_notifier = None
_settings: Settings | None = None
_lock = asyncio.Lock()
_seen: set[tuple] = set()


def bind(candles, paper, tracker, notifier, settings: Settings) -> None:
    global _candles, _paper, _tracker, _notifier, _settings
    _candles, _paper, _tracker, _notifier, _settings = candles, paper, tracker, notifier, settings


async def tell_admin(text: str) -> None:
    if _notifier is None:
        return
    try:
        await _notifier.send_admin(text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH] admin: %s", exc)


async def ping_admin(text: str) -> None:
    await tell_admin(text)


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _last_px(symbol: str) -> float:
    if _candles is None or not symbol:
        return 0.0
    for tf in ("1m", "5m", "15m", "1h", "4h"):
        try:
            df = _candles.get_df(symbol, tf)
        except Exception:  # noqa: BLE001
            df = None
        if df is not None and len(df):
            try:
                return float(df.iloc[-1]["close"])
            except Exception:  # noqa: BLE001
                continue
    return 0.0


def _recipient_ids(settings: Settings, db_ids: list[int]) -> list[int]:
    ids: list[int] = []
    for x in list(db_ids or []) + list(settings.admin_id_list or []):
        try:
            n = int(x)
        except (TypeError, ValueError):
            continue
        if n and n not in ids:
            ids.append(n)
    return ids


async def _park_unique(session, *, symbol: str, timeframe: str, direction: str) -> None:
    """Unique index: eski qator is_active=False. Lot/paper TEGILMAYDI."""
    try:
        await session.execute(
            update(Signal)
            .where(
                Signal.symbol == symbol,
                Signal.timeframe == timeframe,
                Signal.direction == direction,
                Signal.is_active.is_(True),
            )
            .values(is_active=False)
        )
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH] park unique: %s", exc)
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass


async def flatten(session, *, symbol: str | None, price: float) -> int:
    """Faqat admin 'tugatdik' — paper yopiladi. Yangi SIGNAL buni chaqirmaydi."""
    n = 0
    px = float(price or 0) or 0.0
    sm = symbol or "XAUUSDT"
    try:
        opens = await crud.get_active_signals(session, sm)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH] flatten list: %s", exc)
        opens = []
    for old in opens:
        fill = px if px > 0 else float(old.entry or 0)
        try:
            if _paper is not None:
                for i, pos in enumerate(await _paper.open_positions(session, signal_id=old.id)):
                    try:
                        await _paper.apply_fill(
                            session, pos, fill, portion=0.0, is_final=True,
                            exit_price_for_remaining=fill, count_trade=(i == 0),
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("[CH] paper yopish: %s", exc)
            await crud.close_signal(
                session, old, status=SignalStatus.CANCELLED,
                result="CANCELLED", r_multiple=0.0, pnl_percent=0.0,
                close_price=fill,
            )
            n += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CH] flatten #%s: %s", old.id, exc)
            try:
                old.is_active = False
                old.status = SignalStatus.CANCELLED.value
                await session.commit()
                n += 1
            except Exception:  # noqa: BLE001
                await session.rollback()
    # Unique index: ORM o'tkazib yuborgan qatorlar
    try:
        await session.execute(
            update(Signal)
            .where(Signal.symbol == sm, Signal.is_active.is_(True))
            .values(
                is_active=False,
                status=SignalStatus.CANCELLED.value,
                result="CANCELLED",
                closed_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH] flatten update: %s", exc)
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
    if _paper is not None:
        try:
            for pos in await _paper.open_positions(session, symbol=sm):
                fill = px if px > 0 else float(pos.entry or 0)
                try:
                    await _paper.apply_fill(
                        session, pos, fill, portion=0.0, is_final=True,
                        exit_price_for_remaining=fill, count_trade=False,
                    )
                    n += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[CH] leftover: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CH] leftover list: %s", exc)
    return n


async def _notify(signal) -> None:
    if _notifier is None or signal is None or not getattr(signal, "id", None):
        logger.error("[CH] notifier yo'q — karta yuborilmadi")
        return
    try:
        from app.bot import keyboards as kb
        await _notifier.send_signal(
            signal, None, chart_png=None,
            reply_markup=kb.signal_card_kb(int(signal.id)),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("[CH] karta: %s", exc)
        try:
            await tell_admin(
                f"⚠️ Karta yuborilmadi #{getattr(signal, 'id', '?')} "
                f"{getattr(signal, 'symbol', '')} {exc}"
            )
        except Exception:  # noqa: BLE001
            pass


def _read_text(text: str, image_bytes: bytes | None) -> str:
    from app.services.channel_ocr import ocr_image
    parts = []
    if (text or "").strip():
        parts.append(text.strip())
    if image_bytes:
        try:
            o = (ocr_image(image_bytes) or "").strip()
            if o:
                parts.append(o)
        except Exception:  # noqa: BLE001
            pass
    return "\n".join(parts)


def _parse_now(raw: str):
    if not raw or not str(raw).strip():
        return None
    p = parse_signal(raw)
    _old_dir = p.direction if p is not None else ''
    try:
        from app.services.local_ai import analyze as _lai
        _lref = _last_px(p.symbol) if (p is not None and p.symbol) else None
        _lq = _lai(str(raw), ref=_lref)
        if _lq is not None:
            if p is None:
                p = _lq
            else:
                p = merge_parsed(p, _lq)
                if _old_dir and p is not None:
                    p.direction = _old_dir
    except Exception as _e:
        logger.warning('[CH] lokal AI: %s', _e)
    if p is None:
        return None
    ref = ref_from_text(raw) or _last_px(p.symbol)
    if ref:
        p = snap_parsed(p, ref)
    return p


async def ingest_raw(*, ch: dict, text: str, image_bytes: bytes | None = None,
                     msg_id: int = 0, chat_id: int | None = None,
                     title: str = "", username: str | None = None,
                     notify_verdict: bool = False,
                     grouped_id=None, reply_to: int | None = None,
                     require_listed: bool = True) -> str:
    async with _lock:
        return await _run(
            ch=ch or {}, text=text or "", image_bytes=image_bytes,
            msg_id=int(msg_id or 0), chat_id=chat_id, title=title or "",
            username=username, grouped_id=grouped_id, reply_to=reply_to,
            require_listed=require_listed,
        )


async def _run(*, ch: dict, text: str, image_bytes, msg_id: int,
               chat_id, title: str, username, grouped_id, reply_to,
               require_listed: bool) -> str:
    uname = (username or ch.get("username") or "").lstrip("@").lower()
    bare = int(peer_bare(chat_id) or chat_id or 0)
    key = (bare, msg_id, uname)
    if msg_id and key in _seen:
        return "seen"
    if msg_id:
        _seen.add(key)
        if len(_seen) > 4000:
            _seen.clear()
            _seen.add(key)

    raw = _read_text(text, image_bytes)
    closing = is_close_message(text) or is_close_message(raw)
    cur = _parse_now(text) or _parse_now(raw)
    cur_new = bool(
        cur and cur.direction and (cur.entry or cur.zone_low or cur.sl or cur.tp)
    )

    from app.services.channel_context import chan_key, combined_text, remember, stitch
    ck = chan_key(uname or None, chat_id)
    arr = remember(ck, text=raw, msg_id=msg_id, grouped_id=grouped_id, reply_to=reply_to)

    async with async_session_factory() as session:
        listed = None
        try:
            listed = await match_channel(session, chat_id=chat_id, username=uname or None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CH] match: %s", exc)

        src_ch = dict(listed or ch or {})
        if uname:
            src_ch["username"] = uname
        if chat_id:
            try:
                src_ch["chat_id"] = int(chat_id)
            except (TypeError, ValueError):
                pass
        if title:
            src_ch["title"] = title
        src = display_name(src_ch)

        if listed is None and require_listed:
            logger.info("[CH] tashlandi (ro'yxatda yo'q): %s", src)
            return "skip"

        rec = dict(listed) if listed is not None else src_ch

        if closing and not cur_new:
            try:
                await record_read(session, rec, False)
            except Exception:  # noqa: BLE001
                pass
            sm = (cur.symbol if cur else None) or "XAUUSDT"
            n = await flatten(session, symbol=sm, price=_last_px(sm))
            logger.info("[CH] yopish %s n=%d", src, n)
            if n and _notifier is not None:
                try:
                    await _notifier.send_event(
                        f"📂 <b>{sm}</b> — paper yopildi (kanal / admin)."
                    )
                except Exception:  # noqa: BLE001
                    pass
            return "closed"

        parsed = cur
        if parsed is None or not (parsed.entry or parsed.zone_low or parsed.sl):
            window = stitch(arr, msg_id=msg_id, grouped_id=grouped_id, reply_to=reply_to)
            blob = combined_text(window)
            if blob and blob.strip() != (raw or "").strip():
                p2 = _parse_now(blob)
                parsed = merge_parsed(parsed, p2) if parsed else p2
                if parsed:
                    parsed = apply_levels(parsed, blob)

        # AI zaxira: lokal parser topa olmasa - kanal AI (emoji/rasm/persian/LLM)
        if parsed is None or not (parsed.direction and parsed.symbol):
            try:
                from app.services import channel_ai

                ai_img = image_bytes or None
                if ai_img and (raw or "").strip() != (text or "").strip():
                    ai_img = None  # OCR allaqachon ishlagan, ikkinchi marta o'qimaymiz
                ai = await channel_ai.interpret_async(raw or text or None, ai_img)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[CH] AI fallback: %s", exc)
                ai = None
            if ai is not None:
                if parsed is None:
                    parsed = ai
                else:
                    parsed.direction = parsed.direction or ai.direction
                    parsed.symbol = parsed.symbol or ai.symbol
                    parsed.entry = parsed.entry or ai.entry
                    parsed.sl = parsed.sl or ai.sl
                    if not parsed.tps:
                        parsed.tps = list(ai.tps or [])
                    if not parsed.tp and parsed.tps:
                        parsed.tp = parsed.tps[0]
                logger.info(
                    "[CH] AI zaxira OK: %s %s entry=%s",
                    parsed.direction, parsed.symbol, parsed.entry,
                )

        is_sig = parsed is not None and parsed.direction and parsed.symbol
        if not is_sig:
            try:
                await record_read(session, rec, False)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[CH] stats: %s", exc)
            logger.info("[CH] %s EMAS — chatga yuborilmadi: %s", src, (raw or "")[:80])
            return "not_signal"

        logger.info(
            "[CH] parse %s %s %s entry=%s sl=%s zona=%s/%s",
            src, parsed.direction, parsed.symbol, parsed.entry, parsed.sl,
            getattr(parsed, "zone_low", None), getattr(parsed, "zone_high", None),
        )

        if chat_id:
            try:
                await bind_chat_id(session, rec, int(chat_id), title)
            except Exception:  # noqa: BLE001
                pass

        settings = _settings or get_settings()
        try:
            verdict = await _save(session, rec, parsed, settings, src)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[CH] saqlash: %s", exc)
            try:
                await record_read(session, rec, False)
            except Exception:  # noqa: BLE001
                pass
            return "error"

        try:
            await record_read(session, rec, verdict == "ok")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CH] stats: %s", exc)
        return verdict


async def _save(session, ch: dict, parsed, settings: Settings, src: str) -> str:
    symbol = parsed.symbol
    timeframe = "1m"
    if getattr(parsed, "tf_explicit", False) and parsed.timeframe in (
        "1m", "5m", "15m", "1h", "4h", "30m", "1d",
    ):
        timeframe = parsed.timeframe
    direction = Direction.BUY if parsed.direction == "BUY" else Direction.SELL

    entry = parsed.entry
    atr = 0.0
    df = None
    if _candles is not None:
        for tf_try in (timeframe, "1m", "5m", "15m"):
            try:
                df = _candles.get_df(symbol, tf_try)
            except Exception:  # noqa: BLE001
                df = None
            if df is not None and len(df):
                break
    if df is not None and len(df) >= 14:
        try:
            from app.indicators.bundle import compute_bundle
            bundle = compute_bundle(df, settings)
            atr = float(bundle.last_atr or 0)
            if not entry:
                entry = float(bundle.last_close)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CH] atr: %s", exc)
    if not entry:
        entry = _last_px(symbol) or None
    if not entry:
        entry = 100.0
        logger.warning("[CH] kirish yo'q — 100")

    sl_ok = None
    if parsed.sl and float(parsed.sl) > 0:
        cand = float(parsed.sl)
        if abs(float(entry) - cand) > 1e-9:
            buy = direction == Direction.BUY
            if (buy and cand < float(entry)) or ((not buy) and cand > float(entry)):
                sl_ok = cand
    if sl_ok is not None:
        levels_entry, levels_sl = float(entry), sl_ok
        tp1 = r_price(direction, levels_entry, levels_sl, 1)
        tp2 = r_price(direction, levels_entry, levels_sl, 2)
        tp3 = r_price(direction, levels_entry, levels_sl, 3)
        risk = abs(levels_entry - levels_sl)
    else:
        if atr <= 0:
            atr = abs(float(entry)) * 0.006
        lv = calculate_levels(direction, float(entry), atr, settings)
        levels_entry, levels_sl = lv.entry, lv.sl
        tp1, tp2, tp3 = lv.tp1, lv.tp2, lv.tp3
        risk = lv.risk_distance

    zlo = getattr(parsed, "zone_low", None)
    zhi = getattr(parsed, "zone_high", None)
    if zlo and zhi:
        a, b = float(zlo), float(zhi)
        entry_low, entry_high = (a, b) if a <= b else (b, a)
        if not parsed.entry:
            levels_entry = (a + b) / 2.0
            if sl_ok is not None:
                tp1 = r_price(direction, levels_entry, levels_sl, 1)
                tp2 = r_price(direction, levels_entry, levels_sl, 2)
                tp3 = r_price(direction, levels_entry, levels_sl, 3)
    else:
        risk = abs(levels_entry - levels_sl) or (levels_entry * 0.008)
        entry_low, entry_high = levels_entry - risk * 0.1, levels_entry + risk * 0.1

    await _park_unique(
        session, symbol=symbol, timeframe=timeframe, direction=direction.value,
    )

    sk = stat_key(ch.get("username"), ch.get("chat_id"))
    checks = [
        {"label": f"KANAL: {src}", "passed": True,
         "channel": ch.get("username") or src, "source": "channel"},
        {"label": "AI xabarni o'qidi (matn/rasm)", "passed": True, "source": "channel"},
    ]
    snippet = _esc((parsed.raw or "")[:180])
    explanation = (
        f"<b>📡 Kanal:</b> {_esc(src)}\n"
        f"{parsed.direction} {symbol} {timeframe}\n"
        f"<code>{snippet}</code>"
    )
    total = await crud.count_signals(session)

    def _mk() -> Signal:
        return Signal(
            symbol=symbol, timeframe=timeframe, direction=direction.value,
            status=SignalStatus.ACTIVE.value, is_active=True,
            score=6.5, confidence=60.0, win_probability=55.0,
            signal_no=total + 1, strength="GOOD",
            regime="", mtf_alignment="NONE", quality_mode="CHANNEL",
            entry=levels_entry, entry_low=entry_low, entry_high=entry_high,
            sl=levels_sl, tp1=tp1, tp2=tp2, tp3=tp3, atr_value=atr or 0.0,
            explanation=explanation, checks_json=_dumps_json(checks),
            candle_open_time=datetime.now(timezone.utc),
        )

    signal = _mk()
    session.add(signal)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        logger.warning("[CH] unique — park qilib qayta yoziladi %s %s", symbol, direction.value)
        await _park_unique(
            session, symbol=symbol, timeframe=timeframe, direction=direction.value,
        )
        signal = _mk()
        session.add(signal)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            logger.error("[CH] unique qoldi %s %s %s", symbol, timeframe, direction.value)
            return "error"

    await session.refresh(signal)
    session.add(SignalConfirmation(
        signal_id=signal.id, strategy_name=sk,
        direction=direction.value, score=6.5, confidence=60.0,
        reason=f"Kanal {src}",
        indicators_json=_dumps_json({"channel": src}),
    ))
    await session.commit()

    if _paper is not None:
        try:
            db_ids = await crud.get_all_active_users(session)
            user_ids = _recipient_ids(settings, db_ids)
            if not user_ids:
                logger.error("[CH] paper: user/admin id yo'q")
            else:
                n_open = await _paper.open_for_signal(session, signal, user_ids)
                logger.info("[CH] avto-trade #%s → %d lot  users=%s",
                            signal.id, n_open, user_ids)
                if n_open <= 0:
                    logger.error("[CH] paper 0 lot #%s (avto-trade o'chiq yoki pauza?)", signal.id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[CH] paper: %s", exc)

    logger.info("[CH] SIGNAL #%s %s %s %s via %s entry=%s sl=%s",
                signal.id, symbol, timeframe, direction.value, src,
                levels_entry, levels_sl)
    await _notify(signal)
    return "ok"


async def ingest_channel_post(message) -> None:
    chat = getattr(message, "chat", None)
    if chat is None:
        return
    chat_id = int(chat.id)
    username = (getattr(chat, "username", None) or "") or None
    async with async_session_factory() as session:
        ch = await match_channel(session, chat_id=chat_id, username=username)
        if ch is None:
            logger.info("[CH] channel_post tashlandi @%s", username)
            return
    text = message.text or message.caption or ""
    img = None
    try:
        if getattr(message, "photo", None) and message.bot:
            buf = await message.bot.download(message.photo[-1])
            img = buf.read() if buf else None
    except Exception as exc:  # noqa: BLE001
        logger.info("[CH] bot rasm: %s", exc)
    await ingest_raw(
        ch=ch, text=text, image_bytes=img,
        msg_id=int(getattr(message, "message_id", 0) or 0),
        chat_id=chat_id, title=getattr(chat, "title", None) or "",
        username=username,
        grouped_id=getattr(message, "media_group_id", None),
        reply_to=getattr(getattr(message, "reply_to_message", None), "message_id", None),
        require_listed=True,
    )


async def ingest_from_bot_message(message) -> str:
    """Admin botga yozdi/forward qildi."""
    chat = None
    orig = getattr(message, "forward_origin", None)
    if orig is not None:
        chat = getattr(orig, "chat", None)
    if chat is None:
        chat = getattr(message, "forward_from_chat", None)
    username = (getattr(chat, "username", None) or "") or None
    title = (getattr(chat, "title", None) or "") if chat is not None else ""
    chat_id = int(chat.id) if chat is not None and getattr(chat, "id", None) else None
    mid = int(getattr(orig, "message_id", 0) or getattr(message, "message_id", 0) or 0)
    text = (getattr(message, "text", None) or getattr(message, "caption", None) or "") or ""
    img = None
    try:
        bot = getattr(message, "bot", None)
        if bot is not None:
            if getattr(message, "photo", None):
                buf = await bot.download(message.photo[-1])
                img = buf.read() if buf else None
            else:
                doc = getattr(message, "document", None)
                mime = str(getattr(doc, "mime_type", "") or "") if doc is not None else ""
                if mime.startswith("image/"):
                    buf = await bot.download(doc)
                    img = buf.read() if buf else None
    except Exception as exc:  # noqa: BLE001
        logger.info("[CH] bot rasm: %s", exc)
    async with async_session_factory() as session:
        ch = None
        if chat_id or username:
            ch = await match_channel(session, chat_id=chat_id, username=username)
            if ch is None:
                _ok, _msg, ch = await add_channel(
                    session, username=username, chat_id=chat_id, title=title,
                    kind="public" if username else "private",
                )
                logger.info("[CH] forward qo'shildi: %s (%s)", display_name(ch or {}), _msg)
        if ch is None:
            ch = {
                "username": username or "forward",
                "chat_id": chat_id,
                "title": title or "Botga yuborilgan",
                "kind": "manual",
            }
    return await ingest_raw(
        ch=ch, text=text, image_bytes=img,
        msg_id=mid, chat_id=chat_id, title=title, username=username,
        require_listed=False,
    )
