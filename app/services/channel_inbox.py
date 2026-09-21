"""BITTA YO'L: kanal xabari → parse → DB + karta + 2 lot paper.

Hisobotga SIGNAL faqat karta/bitim urinilgandan KEYIN yoziladi.
Eski ochiq signal (CHANNEL yoki yo'q) yangisini BLOKLAMAYDI.
EMAS chatga yuborilmaydi.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
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
    is_loss_message,
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



# ======================= v46: o'z-o'zini diagnostika =======================
_DIAG: dict = {}
_DIAG_VER = "v46"
_boot_sent = False
_sig_sent = False


def _ver_info() -> str:
    """Versiya + muhit haqida qisqa ma'lumot (admin xabariga)."""
    try:
        from app.services import local_ai as _lai
        lai = str(getattr(_lai, "__version__", "?"))
    except Exception:  # noqa: BLE001
        lai = "yo'q"
    try:
        key = "bor" if getattr(_settings or get_settings(), "ai_api_key", "") else "yo'q"
    except Exception:  # noqa: BLE001
        key = "?"
    ocr_ok = False
    try:
        import shutil
        from app.services import channel_ocr as _ocr
        ocr_ok = bool(getattr(_ocr, "_TESS_EXE", "") or shutil.which("tesseract"))
    except Exception:  # noqa: BLE001
        pass
    return (f"AI: <b>{lai}</b> | rasm o'qish: {'ok' if ocr_ok else 'yo\'q'}"
            + (" | kalit: bor" if key == "bor" else ""))


async def _diag(key, src: str, kind: str, reason: str = "", sample: str = "") -> None:
    """Kanal bo'yicha hisob + admin ogohlantirishlari. Hech qachon xato bermaydi."""
    global _boot_sent, _sig_sent
    try:
        import time as _t
        now = _t.time()
        d = _DIAG.setdefault(str(key or src or "?"), {
            "read": 0, "sig": 0, "emas": 0, "err": 0, "skip": 0,
            "why": [], "smp": [], "ts": now,
        })
        d["read"] += 1
        if kind in ("sig", "emas", "err", "skip"):
            d[kind] += 1
        elif kind == "closed":
            d["read"] -= 1
        if reason:
            d["why"] = ([reason] + d["why"])[:3]
        if sample:
            _sm = ((sample or "").replace("\n", " "))[:110]
            d["smp"] = ([_sm] + d["smp"])[:3]

        if not _boot_sent:
            _boot_sent = True
            await tell_admin(f"\u2705 <b>SINO AI tayyor</b> | {_ver_info()}")
        if kind == "sig" and not _sig_sent:
            _sig_sent = True
        _na = int(d.get("alerts") or 0)
        if (d["sig"] == 0 and d["read"] >= 12 + 25 * _na
                and now - float(d.get("ts") or 0) >= 120):
            d["alerts"] = _na + 1
            d["ts"] = now
            why = "\n".join(f"\u2022 {_esc(w)}" for w in d["why"][:3]) or "\u2022 sabab yo'q"
            smp = "\n".join(f"\u2022 <code>{_esc(s)}</code>" for s in d["smp"][:3]) or "\u2022 -"
            await tell_admin(
                f"\u26A0\uFE0F <b>DIAGNOSTIKA</b> — {_esc(src)}\n"
                f"O'qildi: <b>{d['read']}</b> | SIGNAL: <b>0</b> | EMAS: {d['emas']} | "
                f"xato: {d['err']} | o'tkazildi: {d['skip']}\n"
                f"Sabablar:\n{why}\nNamunalar:\n{smp}"
            )
    except Exception:  # noqa: BLE001
        pass


async def _diag_skip(src: str, key, sample: str) -> None:
    await _diag(key, src, "skip", "ro'yxatda yo'q (chan_id/username mos kelmadi)", sample)

# ===========================================================================

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


DUP_WINDOW_MIN = 30     # shu daqiqa ichida bir xil setup = takroriy signal
DUP_TOL_PCT = 0.001     # narxning 0.1% (oltinda ~4$)
DUP_TOL_R = 0.6         # yoki 1R masofasining 60%


async def _recent_twin(session, *, symbol: str, direction: str,
                       entry: float, sl: float) -> Signal | None:
    """v65: yaqin vaqt ichida deyarli bir xil signal bo'lsa — o'shani qaytaradi.

    Kanal bir setupni bir necha marta tashlasa (yoki tahrirlab qayta yuborsa)
    yangi karta YUBORILMAYDI: bir xil juftlik + yo'nalish + narx zonasi = bitta signal.
    """
    try:
        since = datetime.now(timezone.utc) - timedelta(minutes=DUP_WINDOW_MIN)
        rows = list((await session.execute(
            select(Signal)
            .where(
                Signal.symbol == symbol,
                Signal.direction == direction,
                Signal.created_at >= since,
            )
            .order_by(Signal.id.desc())
            .limit(8)
        )).scalars().all())
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH] takroriy so'rovi: %s", exc)
        return None
    for old in rows:
        try:
            e0 = float(old.entry or 0.0)
        except Exception:  # noqa: BLE001
            continue
        if e0 <= 0:
            continue
        try:
            s0 = float(old.sl or 0.0)
        except Exception:  # noqa: BLE001
            s0 = 0.0
        tol = max(abs(e0) * DUP_TOL_PCT, (abs(e0 - s0) * DUP_TOL_R) if s0 else 0.0)
        if abs(float(entry) - e0) > tol:
            continue
        if s0 and abs(float(sl) - s0) > tol:
            continue
        return old
    return None


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


async def flatten(session, *, symbol: str | None, price: float,
                  loss: bool = False) -> int:
    """Faqat admin 'tugatdik' — paper yopiladi. Yangi SIGNAL buni chaqirmaydi.

    v65: `loss=True` (kanal 'SL/zarar' deb yozgan natija posti) — bitim MAHALLIY
    narxda emas, o'z STOP narxida yopiladi: minus stop lossgacha qancha bo'lsa,
    o'shancha hisoblanadi (foydalanuvchi talabi).
    """
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
        r_pct = 0.0
        try:
            ent = float(old.entry or 0)
            r_pct = abs(float(old.sl or ent) - ent) / ent * 100.0 if ent else 0.0
        except Exception:  # noqa: BLE001
            r_pct = 0.0
        try:
            if _paper is not None:
                for i, pos in enumerate(await _paper.open_positions(session, signal_id=old.id)):
                    use = fill
                    if loss:
                        stop = float(getattr(pos, "sl", 0) or old.sl or 0) or 0.0
                        if stop > 0:
                            use = stop  # v65: minus STOP narxigacha hisoblanadi
                    try:
                        await _paper.apply_fill(
                            session, pos, use, portion=0.0, is_final=True,
                            exit_price_for_remaining=use, count_trade=(i == 0),
                            reason=("SL (kanal)" if loss else "BEKOR (kanal)"),
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("[CH] paper yopish: %s", exc)
            if loss:
                await crud.close_signal(
                    session, old, status=SignalStatus.SL_HIT,
                    result="LOSS", r_multiple=-1.0, pnl_percent=-abs(r_pct),
                    close_price=fill, reason="SL (kanal)",
                )
            else:
                await crud.close_signal(
                    session, old, status=SignalStatus.CANCELLED,
                    result="CANCELLED", r_multiple=0.0, pnl_percent=0.0,
                    close_price=fill, reason="BEKOR (kanal)",
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
                status=(SignalStatus.SL_HIT.value if loss
                        else SignalStatus.CANCELLED.value),
                result=("LOSS" if loss else "CANCELLED"),
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
                if loss:
                    fill = float(getattr(pos, "sl", 0) or fill) or fill
                try:
                    await _paper.apply_fill(
                        session, pos, fill, portion=0.0, is_final=True,
                        exit_price_for_remaining=fill, count_trade=False,
                        reason=("SL (kanal)" if loss else "BEKOR (kanal)"),
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

        skey = stat_key(uname or None, chat_id)
        if listed is None and require_listed:
            logger.warning("[CH-SKIP] ro'yxatda yo'q: %s (chat_id=%s @%s)", src, chat_id, uname)
            await _diag_skip(src, skey, raw or text or "")
            return "skip"

        rec = dict(listed) if listed is not None else src_ch

        if closing and not cur_new:
            try:
                await record_read(session, rec, False)
            except Exception:  # noqa: BLE001
                pass
            sm = (cur.symbol if cur else None) or "XAUUSDT"
            loss_post = is_loss_message(text) or is_loss_message(raw)
            n = await flatten(session, symbol=sm, price=_last_px(sm), loss=loss_post)
            logger.info("[CH] yopish %s n=%d loss=%s", src, n, loss_post)
            await _diag(skey, src, "closed",
                        "stop loss natijasi" if loss_post else "yopish xabari", text or "")
            if n and _notifier is not None and loss_post:
                try:
                    await _notifier.send_event(
                        f"\U0001F6D1 <b>{sm}</b> — kanal STOP deb yozdi: bitim "
                        "<b>stop narxida</b> yopildi (minus stop lossgacha hisoblandi)."
                    )
                except Exception:  # noqa: BLE001
                    pass
            elif n and _notifier is not None:
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
        ai_reason = ""
        if parsed is None or not (parsed.direction and parsed.symbol):
            try:
                from app.services import channel_ai

                ai_img = image_bytes or None
                if ai_img and (raw or "").strip() != (text or "").strip():
                    ai_img = None  # OCR allaqachon ishlagan, ikkinchi marta o'qimaymiz
                ai = await channel_ai.interpret_async(raw or text or None, ai_img)
                ai_reason = str(getattr(channel_ai, "last_reason", "") or "")
            except Exception as exc:  # noqa: BLE001
                logger.warning("[CH] AI fallback xatosi: %s: %s", type(exc).__name__, exc)
                ai_reason = f"AI xatosi: {type(exc).__name__}"
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
            logger.warning("[CH-EMAS] %s | sabab=%s | matn=%s",
                           src, ai_reason or "-", (raw or text or "")[:120])
            await _diag(skey, src, "emas", ai_reason or "sabab aniqlanmadi", raw or text or "")
            return "not_signal"

        logger.warning(
            "[CH-SIG] %s | %s %s entry=%s sl=%s zona=%s/%s",
            src, parsed.direction, parsed.symbol, parsed.entry, parsed.sl,
            getattr(parsed, "zone_low", None), getattr(parsed, "zone_high", None),
        )
        await _diag(skey, src, "sig", "", raw or text or "")

        if chat_id:
            try:
                await bind_chat_id(session, rec, int(chat_id), title)
            except Exception:  # noqa: BLE001
                pass

        settings = _settings or get_settings()
        try:
            verdict = await _save(session, rec, parsed, settings, src)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CH-SAVE-ERR] %s: %s", type(exc).__name__, exc)
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001
                pass
            fixed = ""
            try:
                fixed = await _ensure_schema(session, force=True)
            except Exception:  # noqa: BLE001
                fixed = ""
            if fixed:
                try:
                    verdict = await _save(session, rec, parsed, settings, src)
                    logger.warning("[CH-SAVE-RETRY] sxema tuzatildi (%s) → %s",
                                   fixed, verdict)
                    if verdict == "ok":
                        await _diag(skey, src, "sig", "", raw or text or "")
                        try:
                            await record_read(session, rec, True)
                        except Exception:  # noqa: BLE001
                            pass
                        return verdict
                except Exception as exc2:  # noqa: BLE001
                    logger.warning("[CH-SAVE-RETRY-ERR] %s: %s", type(exc2).__name__, exc2)
            try:
                await tell_admin(
                    "\u26A0\uFE0F <b>Saqlashda xato</b>\n"
                    f"<code>{_esc(type(exc).__name__)}: {_esc(str(exc))[:240]}</code>\n"
                    f"Signal: {_esc(parsed.direction)} {_esc(parsed.symbol)}"
                )
            except Exception:  # noqa: BLE001
                pass
            await _diag(skey, src, "err", f"saqlash: {type(exc).__name__}", text or "")
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



# ===================== v46: DB sxemasini o'zi tuzatish =====================
_SCHEMA_DONE = False


async def _ensure_schema(session, force: bool = False) -> str:
    """Modelda bor, lekin bazada yo'q ustunlarni qo'shadi (Postgres).

    Eski bazada yangi ustun bo'lmasa har bir INSERT xato beradi — shu tufayli
    hamma signal "EMAS" bo'lib qolardi. Bu funksiya uni o'zi tuzatadi.
    """
    global _SCHEMA_DONE
    if _SCHEMA_DONE and not force:
        return ""
    _SCHEMA_DONE = True
    added: list = []
    try:
        from sqlalchemy import inspect, text

        from app.database.models.signal import Signal, SignalConfirmation

        models = [Signal, SignalConfirmation]
        try:
            from app.database.models.stats import StrategyStat
            models.append(StrategyStat)
        except Exception:  # noqa: BLE001
            pass
        try:
            from app.database.models.system import SystemLog
            models.append(SystemLog)
        except Exception:  # noqa: BLE001
            pass
        try:
            from app.database.models.paper import PaperAccount, PaperPosition
            models.append(PaperAccount)
            models.append(PaperPosition)
        except Exception:  # noqa: BLE001
            pass

        def _work(target):
            # AsyncSession.run_sync -> Session beradi; session.connection() -> Connection.
            # Ikkalasi bilan ham ishlashi kerak (v46 da Session uzatilardi va
            # inspect() xato berardi — shu sababli ustunlar qo'shilmasdi).
            conn = target
            if not hasattr(conn, "dialect"):
                try:
                    conn = conn.connection()
                except Exception:  # noqa: BLE001
                    conn = getattr(conn, "bind", None) or conn
            insp = inspect(conn)
            sync_conn = conn
            names = set(insp.get_table_names())
            for model in models:
                t = model.__table__
                if t.name not in names:
                    try:
                        t.create(sync_conn, checkfirst=True)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("[CH-SCHEMA] %s yaratilmadi: %s", t.name, exc)
                    continue
                have = {c["name"] for c in insp.get_columns(t.name)}
                for col in t.columns:
                    if col.name in have:
                        continue
                    try:
                        ddl = col.type.compile(sync_conn.dialect)
                        sync_conn.execute(text(
                            f'ALTER TABLE "{t.name}" ADD COLUMN "{col.name}" {ddl}'
                        ))
                        added.append(f"{t.name}.{col.name}")
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("[CH-SCHEMA] %s.%s: %s", t.name, col.name, exc)

        try:
            dialect = session.bind.dialect.name if session.bind is not None else ""
        except Exception:  # noqa: BLE001
            dialect = ""
        if dialect and dialect not in ("postgresql", "sqlite"):
            return ""
        try:
            conn = await session.connection()
            await conn.run_sync(_work)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CH-SCHEMA] connection yo'li: %s — session yo'li bilan urinib ko'ramiz", exc)
            await session.run_sync(_work)
        if added:
            logger.warning("[CH-SCHEMA] yetishmayotgan ustunlar qo'shildi: %s",
                           ", ".join(added))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH-SCHEMA] tekshiruv xatosi: %s", exc)
    return ", ".join(added)

# ==========================================================================

async def _active_signals_count(session, direction: str | None = None) -> int:
    """v62/v67: bir vaqtda ochiq signallar soni (ochiq lotlar + faol signal yozuvlari).

    v67: `direction` berilsa — FAQAT shu yo'nalishdagi signallar sanaladi
    ("BUY" yoki "SELL"). Sell va Buy alohida hisoblanadi.
    """
    from sqlalchemy import func, select

    from app.core.enums import PaperStatus
    from app.database.models.paper import PaperPosition
    from app.database.models.signal import Signal

    n = 0
    try:
        q = select(func.count(func.distinct(PaperPosition.signal_id))).where(
            PaperPosition.status == PaperStatus.OPEN.value,
            PaperPosition.signal_id.isnot(None),
        )
        if direction:
            q = q.where(PaperPosition.direction == direction)
        r = await session.execute(q)
        n = int(r.scalar() or 0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH] ochiq lotlar sanovi: %s", exc)
    try:
        q2 = select(func.count(Signal.id)).where(Signal.is_active.is_(True))
        if direction:
            q2 = q2.where(Signal.direction == direction)
        r2 = await session.execute(q2)
        n = max(n, int(r2.scalar() or 0))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH] faol signallar sanovi: %s", exc)
    return n


async def _opposite_blocked(session, direction: str | None) -> tuple[bool, int, str]:
    """v67: qarama-qarshi yo'nalishda ochiq (faol) signal bormi.

    Real savdoda bir vaqtda 2 SELL + 1 BUY o'ynalmaydi: bir yo'nalish ochiq
    bo'lsa, TESKARI yo'nalishdagi yangi signal OLINMAYDI.
    """
    if direction not in ("BUY", "SELL"):
        return False, 0, ""
    other = "SELL" if direction == "BUY" else "BUY"
    try:
        n_other = await _active_signals_count(session, other)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH] qarama-qarshi yo'nalish sanovi: %s", exc)
        return False, 0, other
    return (n_other > 0), n_other, other


async def _limit_blocked(session, settings,
                         direction: str | None = None) -> tuple[bool, int, int]:
    """v62/v67: (bloklanganmi, ochiq soni, limit).

    v67: chegara YO'NALISH bo'yicha — bir yo'nalishda maks. N ta faol signal.
    Ya'ni 3 ta SELL ochiq bo'lsa, yangi SELL tashlanadi; BUY o'z hisobida.
    """
    limit_act = int(getattr(settings, "max_active_signals", 3) or 3)
    n_act = await _active_signals_count(session, direction)
    return (n_act >= limit_act), n_act, limit_act


async def _save(session, ch: dict, parsed, settings: Settings, src: str) -> str:
    # v46: jadval ustunlari joyidami — yo'q bo'lsa qo'shamiz
    try:
        await _ensure_schema(session)
    except Exception as _se:  # noqa: BLE001
        logger.warning('[CH-SCHEMA] %s', _se)
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

    # ---- v50: kanal O'ZI yozgan TP darajalari bo'lsa — o'shalar ishlatiladi ----
    ch_tps: list = []
    if getattr(settings, "channel_use_post_tp", True):
        _raw_tps: list = []
        try:
            _raw_tps = [float(x) for x in (getattr(parsed, "tps", None) or []) if x]
        except Exception:  # noqa: BLE001
            _raw_tps = []
        if not _raw_tps and getattr(parsed, "tp", None):
            try:
                _raw_tps = [float(parsed.tp)]
            except Exception:  # noqa: BLE001
                _raw_tps = []
        _buy = direction == Direction.BUY
        _ok = [t for t in _raw_tps
               if (_buy and t > float(levels_entry)) or ((not _buy) and t < float(levels_entry))]
        ch_tps = sorted(_ok, reverse=not _buy)[:3]
    if ch_tps:
        _risk = abs(float(levels_entry) - float(levels_sl)) or float(levels_entry) * 0.004
        tp1 = float(ch_tps[0])
        tp2 = float(ch_tps[1]) if len(ch_tps) > 1 else r_price(
            direction, float(levels_entry), float(levels_sl), 2)
        tp3 = float(ch_tps[2]) if len(ch_tps) > 2 else r_price(
            direction, float(levels_entry), float(levels_sl), 3)
        if abs(float(levels_entry) - float(tp1)) < _risk * 0.3:
            tp1 = r_price(direction, float(levels_entry), float(levels_sl), 1)
            tp2 = r_price(direction, float(levels_entry), float(levels_sl), 2)
            tp3 = r_price(direction, float(levels_entry), float(levels_sl), 3)
        else:
            logger.info("[CH] TP kanal postidan: %s / %s / %s", tp1, tp2, tp3)

    # ---- v65: TAKRORIY signal himoyasi (kanal bir setupni bir necha marta tashlaydi) ----
    try:
        twin = await _recent_twin(
            session, symbol=symbol, direction=direction.value,
            entry=float(levels_entry), sl=float(levels_sl),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH] takroriy tekshiruvi: %s", exc)
        twin = None
    if twin is not None:
        logger.warning(
            "[CH] TAKRORIY signal tashlandi: %s %s entry=%s ~ #%s entry=%s (%s)",
            symbol, direction.value, levels_entry, getattr(twin, "id", "?"),
            getattr(twin, "entry", "?"), src,
        )
        return "dup"

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
    _tp_src = "kanal posti" if ch_tps else "R asosida (avto)"
    explanation = (
        f"<b>📡 Kanal:</b> {_esc(src)}\n"
        f"{parsed.direction} {symbol} {timeframe}\n"
        f"TP manbasi: {_tp_src}\n"
        f"Muddat: {int(getattr(settings, 'channel_expiry_minutes', 240))} daqiqa\n"
        f"<code>{snippet}</code>"
    )
    # v67: qarama-qarshi yo'nalish ochiq bo'lsa — yangi signal OLINMAYDI
    # (bir vaqtda 2 SELL + 1 BUY real savdoda o'ynalmaydi).
    try:
        _opp, n_other, other_dir = await _opposite_blocked(session, direction.value)
        if _opp:
            logger.warning(
                "[CH] QARAMA-QARSHI %s ochiq (%d ta) — yangi %s signal olinmadi: %s (%s)",
                other_dir, n_other, direction.value, symbol, src)
            try:
                await tell_admin(
                    f"\u23F8 <b>Qarama-qarshi yo\'nalish ochiq</b>: {other_dir} ({n_other} ta).\n"
                    f"Yangi {direction.value} signal olinmadi \u2014 {symbol} ({_esc(src)}).\n"
                    "<i>Bir vaqtda faqat BITTA yo'nalish ishlaydi: yo 3 ta SELL, yo 3 ta BUY. "
                    "Ochig'i yopilgach bot keyingi YANGI signalni oladi.</i>"
                )
            except Exception:  # noqa: BLE001
                pass
            return "opposite"
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH] qarama-qarshi yo'nalish tekshiruvi: %s", exc)

    # v62/v67: BIR YO'NALISHDA ko'pi bilan N ta faol signal. Ortiqchasi TASHLANADI
    # (navbat yo'q — bittasi yopilgach ham eski signal qaytarilmaydi, faqat YANGI olinadi).
    try:
        _blocked, n_act, limit_act = await _limit_blocked(session, settings, direction.value)
        if _blocked:
            logger.warning(
                "[CH] LIMIT %s %d/%d — yangi signal qabul qilinmadi: %s (%s)",
                direction.value, n_act, limit_act, symbol, src)
            try:
                await tell_admin(
                    f"\u23F8 <b>Faol signal chegarasi</b> ({direction.value}): "
                    f"{n_act}/{limit_act} ta ochiq.\n"
                    f"Yangi {direction.value} signal tashlab yuborildi — {symbol} ({_esc(src)}).\n"
                    "<i>Chegara yo'nalish bo'yicha: bir yo'nalishda 3 ta. "
                    "Bittasi yopilgach bot keyingi YANGI signalni oladi.</i>"
                )
            except Exception:  # noqa: BLE001
                pass
            return "limit"
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH] limit tekshiruvi: %s", exc)

    total = 0
    try:
        total = await crud.count_signals(session)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH] count_signals: %s", exc)

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
    try:
        session.add(SignalConfirmation(
            signal_id=signal.id, strategy_name=sk,
            direction=direction.value, score=6.5, confidence=60.0,
            reason=f"Kanal {src}",
            indicators_json=_dumps_json({"channel": src}),
        ))
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        # signal allaqachon yozilgan — tasdiq yozilmasa ham u saqlanadi
        logger.warning("[CH] tasdiq yozilmadi: %s: %s", type(exc).__name__, exc)
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        try:
            await tell_admin(
                "\u26A0\uFE0F Signal saqlandi, lekin tasdiq (SignalConfirmation) yozilmadi: "
                f"<code>{_esc(type(exc).__name__)}: {_esc(str(exc))[:180]}</code>"
            )
        except Exception:  # noqa: BLE001
            pass

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
