"""BITTA YO'L: kanal xabari → parse → DB + karta + 2 lot paper.

Hisobotga SIGNAL faqat karta/bitim urinilgandan KEYIN yoziladi.
Eski ochiq signal (CHANNEL yoki yo'q) yangisini BLOKLAMAYDI.
EMAS chatga yuborilmaydi.
"""
from __future__ import annotations

import asyncio
import re
import time
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


def db_status_lines() -> list[str]:
    """v85: baza holati + offline navbat (kuzatuv kartasi uchun)."""
    out: list[str] = []
    try:
        from app.services import dbhealth
        out.append(dbhealth.status_line())
        pend = dbhealth.pending_line()
        if pend:
            out.append(pend)
    except Exception:  # noqa: BLE001
        pass
    return out


def get_diag() -> dict:
    """v83: kanal bo'yicha hisob (ko'rildi / signal / signal emas + oxirgi sabab)."""
    try:
        return {str(k): dict(v) for k, v in (_DIAG or {}).items()}
    except Exception:  # noqa: BLE001
        return {}


def reject_reasons(limit: int = 8) -> list[str]:
    """v83: oxirgi rad etilgan xabarlar sabablari («nima uchun signal emas»)."""
    out: list[str] = []
    try:
        for _k, d in (get_diag() or {}).items():
            whys = list(d.get("why") or [])
            smp = list(d.get("smp") or [])
            if not whys:
                continue
            out.append(f"{d.get('name') or _k}: {whys[0][:70]} | {smp[0][:60] if smp else ''}")
    except Exception:  # noqa: BLE001
        pass
    return out[:limit]


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
            "why": [], "smp": [], "ts": now, "name": str(src or ""),
        })
        if src and not d.get("name"):
            d["name"] = str(src)
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


# ============ v70: XABAR XOTIRASI (bir xil xabar qayta ishlanmasin) ============
# Muammo: bitta xabar uchun bot 4 marta urindi — qaysi xabarni ko'rganini
# bilmasdi (jarayon qayta ishga tushsa yoki kanal bir xilini qayta tashlasa).
_MSG_FP: dict[str, float] = {}
_FP_TTL = 3 * 3600.0          # 3 soat ichida bir xil xabar qayta ishlanmaydi
_FP_MAX = 900
_FP_COMPONENT = "msgfp"
_fp_loaded = False

# Ogohlantirishlar (qarama-qarshi / chegara) — bir manbadan 10 daqiqada 1 marta
_ALERT_AT: dict[str, float] = {}
_ALERT_WINDOW = 600.0


def _fp_text(text: str) -> str:
    import re as _r
    return _r.sub(r"\s+", " ", (text or "").strip().lower())[:400]


def _fp_key(src_key: str, text: str, msg_id: int) -> str:
    import hashlib
    body = _fp_text(text)
    if not body:
        body = "mid:%d" % int(msg_id or 0)
    return "%s|%s" % (src_key or "?", hashlib.sha1(body.encode("utf-8")).hexdigest()[:16])


async def _fp_load() -> None:
    """Xabar xotirasini bazadan yuklaydi (qayta ishga tushgandan keyin ham eslaydi)."""
    global _fp_loaded
    if _fp_loaded:
        return
    _fp_loaded = True
    try:
        from app.database.session import async_session_factory
        from app.services.channel_store import load_json_log
        async with async_session_factory() as s:
            data = await load_json_log(s, _FP_COMPONENT)
        now = time.time()
        for k, v in (data.get("items") or {}).items():
            try:
                ts = float(v)
            except (TypeError, ValueError):
                continue
            if now - ts <= _FP_TTL:
                _MSG_FP[str(k)] = ts
        logger.info("[CH] xabar xotirasi yuklandi: %d ta", len(_MSG_FP))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH] xabar xotirasi yuklanmadi: %s", exc)


async def _fp_save() -> None:
    try:
        from app.database.session import async_session_factory
        from app.services.channel_store import save_json_log
        async with async_session_factory() as s:
            await save_json_log(s, _FP_COMPONENT, {"items": dict(_MSG_FP)})
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH] xabar xotirasi saqlanmadi: %s", exc)


async def _fp_seen(src_key: str, text: str, msg_id: int) -> bool:
    """True — shu xabar allaqachon ishlangan (takror). Xotira bazada saqlanadi."""
    if not _fp_text(text) and not msg_id:
        return False
    await _fp_load()
    now = time.time()
    for k in [k for k, v in list(_MSG_FP.items()) if now - v > _FP_TTL]:
        _MSG_FP.pop(k, None)
    key = _fp_key(src_key, text, msg_id)
    prev = _MSG_FP.get(key)
    _MSG_FP[key] = now
    if len(_MSG_FP) > _FP_MAX:
        for k, _v in sorted(_MSG_FP.items(), key=lambda kv: kv[1])[: len(_MSG_FP) - _FP_MAX]:
            _MSG_FP.pop(k, None)
    if prev is None:
        await _fp_save()
        return False
    logger.info("[CH] XABAR XOTIRASI: takror (%s) — %.0f s oldin ko'rilgan",
                key.split("|")[0], now - prev)
    return True


async def _alert_once(kind: str, src: str, text: str, minutes: float = 10.0) -> bool:
    """Bir xil ogohlantirishni 10 daqiqada bir martadan ko'p yubormaydi."""
    now = time.time()
    key = "%s|%s" % (kind, (src or "?").strip().lower())
    last = float(_ALERT_AT.get(key) or 0.0)
    if now - last < minutes * 60.0:
        logger.info("[CH] ogohlantirish TAKRORLANMADI (%s %s) — %.0f s oldin yuborilgan",
                    kind, src, now - last)
        return False
    _ALERT_AT[key] = now
    await tell_admin(text)
    return True


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
        from app.engine import entry as _EN
        await _notifier.send_signal(
            signal, None, chart_png=None,
            reply_markup=kb.signal_card_kb(int(signal.id),
                                           waiting=_EN.is_waiting(signal)),
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


_OCR_CACHE: dict = {}


def _ocr_cached(image_bytes: bytes | None) -> str:
    """v81: rasm matni BIR MARTA o'qiladi va signalda alohida saqlanadi."""
    if not image_bytes:
        return ""
    try:
        key = (len(image_bytes), hash(image_bytes[:256]))
    except Exception:  # noqa: BLE001
        key = (len(image_bytes), 0)
    if key in _OCR_CACHE:
        return _OCR_CACHE[key]
    txt = ""
    try:
        from app.services.channel_ocr import ocr_image
        txt = (ocr_image(image_bytes) or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.info("[CH] OCR o'qilmadi: %s", exc)
        txt = ""
    if len(_OCR_CACHE) > 60:
        _OCR_CACHE.clear()
    _OCR_CACHE[key] = txt
    return txt


def _read_text(text: str, image_bytes: bytes | None) -> str:
    parts = []
    if (text or "").strip():
        parts.append(text.strip())
    o = _ocr_cached(image_bytes)
    if o:
        parts.append(o)
    return "\n".join(parts)


async def _read_text_async(text: str, image_bytes: bytes | None) -> str:
    """v89: OCR ni ALOHIDA THREAD da bajaradi — bot qotib qolmaydi.

    Ilgari OCR (tesseract ~1-3 s/rasm) to'g'ridan-to'g'ri event loop ichida
    ishlardi: bir nechta rasm kelsa bot ham, API (/health) ham javob bermay
    qolardi — Render sog'liq tekshiruvi yiqilishi mumkin edi.
    """
    parts = []
    if (text or "").strip():
        parts.append(text.strip())
    if image_bytes:
        try:
            o = await asyncio.to_thread(_ocr_cached, image_bytes)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CH] OCR (thread): %s", exc)
            o = ""
        if o:
            parts.append(o)
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
                     require_listed: bool = True,
                     posted_at=None) -> str:
    async with _lock:
        try:
            return await _run(
                ch=ch or {}, text=text or "", image_bytes=image_bytes,
                msg_id=int(msg_id or 0), chat_id=chat_id, title=title or "",
                username=username, grouped_id=grouped_id, reply_to=reply_to,
                require_listed=require_listed, posted_at=posted_at,
            )
        except Exception as exc:  # noqa: BLE001
            # v85: BAZA uzilgan bo'lsa xabar NAVBATGA yoziladi (yo'qolmaydi)
            from app.services import dbhealth
            if not dbhealth.is_conn_error(exc):
                raise
            try:
                from app.services import offline
                offline.add(ch=ch, text=text, image_bytes=image_bytes,
                            msg_id=msg_id, chat_id=chat_id, title=title,
                            username=username, grouped_id=grouped_id,
                            reply_to=reply_to, posted_at=posted_at,
                            reason=type(exc).__name__)
            except Exception as exc2:  # noqa: BLE001
                logger.error("[CH] offline navbat: %s", exc2)
            try:
                await dbhealth.note_fail(
                    exc, _notifier,
                    source=f"kanal xabari ({title or username or chat_id})")
            except Exception:  # noqa: BLE001
                pass
            return "db_error"


def _aware_utc(v):
    """Telethon/Telegram vaqti → vaqt mintaqali UTC datetime (v81)."""
    if v is None:
        return None
    try:
        from datetime import timezone as _tz
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(float(v), tz=_tz.utc)
        if getattr(v, "tzinfo", None) is None:
            return v.replace(tzinfo=_tz.utc)
        return v
    except Exception:  # noqa: BLE001
        return None


async def _run(*, ch: dict, text: str, image_bytes, msg_id: int,
               chat_id, title: str, username, grouped_id, reply_to,
               require_listed: bool, posted_at=None) -> str:
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

    # v70: bir xil xabar (yoki qayta o'qilgan xabar) QAYTA ishlanmaydi —
    # na karta, na ogohlantirish. OCR ham qayta chaqirilmaydi.
    try:
        if await _fp_seen(uname or ("id%d" % bare if bare else "?"), text or "", msg_id):
            return "dup_msg"
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH] xabar xotirasi tekshiruvi: %s", exc)

    raw = await _read_text_async(text, image_bytes)
    ocr_txt = raw[len(text or ""):].strip() if image_bytes else ""
    # v95: RASM/OCR HECH QACHON SIGNAL MANBASI EMAS (user qoidasi).
    # OCR matni faqat ARXIV uchun saqlanadi - parse/gate/AI ga KIRMAYDI.
    posted_dt = _aware_utc(posted_at)
    closing = is_close_message(text or "")
    cur = _parse_now(text or "")
    cur_new = bool(
        cur and cur.direction and (cur.entry or cur.zone_low or cur.sl or cur.tp)
    )

    from app.services.channel_context import chan_key, combined_text, remember, stitch
    ck = chan_key(uname or None, chat_id)
    arr = remember(ck, text=(text or ""), msg_id=msg_id, grouped_id=grouped_id,
                   reply_to=reply_to)

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
            loss_post = is_loss_message(text or "")
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
        # v93: KONTEKST OYNASI (4 daqiqa) — kanal egasi signalni bo'lib yozadi
        # ("04-00" keyin "Buy"; "Buy scalp 47-44" keyin "37sl"). Shu sababli
        # qo'shni xabarlar ham o'qiladi, lekin JORIY xabar kontekstga kirmaydi.
        window = stitch(arr, msg_id=msg_id, grouped_id=grouped_id, reply_to=reply_to)
        blob = combined_text(window)
        _cur_txt = (raw or text or "").strip()
        ctx_txt = "\n".join(x for x in (blob or "").split("\n")
                             if x.strip() and x.strip() != _cur_txt)
        if parsed is None or not (parsed.entry or parsed.zone_low or parsed.sl):
            if blob and blob.strip() != (raw or "").strip():
                p2 = _parse_now(blob)
                parsed = merge_parsed(parsed, p2) if parsed else p2
                if parsed:
                    parsed = apply_levels(parsed, blob)

        # AI zaxira: lokal parser topa olmasa - kanal AI (emoji/rasm/persian/LLM)
        ai_reason = ""
        # v104: lokal o'qiy olmasa — AI ZANJIR: Groq (bepul) -> Gemini
        try:
            from app.services import ai_chain as _AC104
            if (parsed is None
                    or not (parsed.direction and parsed.symbol)):
                if _AC104.looks_candidate(text or ""):
                    _gv = await _AC104.extract_signal(text or "")
                    if _gv:
                        from app.services.channel_ai import _from_real as _FR102
                        parsed = _FR102(_gv, text or "")
                        _strict_ok = True
                        logger.info("[CH] v104 AI zanjir (%s) signal o'qidi: "
                                    "%s %s entry=%s sl=%s", _gv.get("src"),
                                    _gv["direction"], parsed.symbol,
                                    parsed.entry, parsed.sl)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CH] v104 ai_chain: %s", exc)
        # v101: symbol YOZILMAGAN scalp signal — jonli narxlar bo'yicha topamiz
        try:
            from app.services import symbol_universe as _SU101
            if (parsed is not None and parsed.direction
                    and not _SU101.has_symbol_word(text or "")):
                _zlo = float(getattr(parsed, "zone_low", 0) or 0)
                _zhi = float(getattr(parsed, "zone_high", 0) or 0)
                _px101 = float(parsed.entry or 0) or (
                    (_zlo + _zhi) / 2.0 if (_zlo and _zhi) else 0.0)
                _xau = _last_px("XAUUSDT")
                if _px101 > 0 and _xau > 0 and abs(_px101 - _xau) / _xau > 0.05:
                    _sym101 = await _SU101.guess_symbol(_px101)
                    if _sym101 and _sym101 != parsed.symbol:
                        logger.info("[CH] v101 symbol xulosa: %s (narx %.4f)",
                                    _sym101, _px101)
                        parsed.symbol = _sym101
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CH] v101 symbol xulosa: %s", exc)
        if parsed is None or not (parsed.direction and parsed.symbol):
            try:
                from app.services import channel_ai

                ai_img = image_bytes or None
                if ai_img and (raw or "").strip() != (text or "").strip():
                    ai_img = None  # OCR allaqachon ishlagan, ikkinchi marta o'qimaymiz
                ai = await channel_ai.interpret_async(
                    text or None, None, ctx=ctx_txt,
                    has_image=bool(image_bytes))
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

        # v83: OXIRGI DARVOZA — parser nima topgan bolsa ham, faqat haqiqiy signal
        # v93: qat'iy qatlam (channel_real) SIGNAL deb topgan bo'lsa, bu darvoza
        #      uni O'LDIRMAYDI — aks holda kontekstdan yig'ilgan signal ("Buy" +
        #      oldingi "04-00") yo'qqa chiqardi, chunki matnda narx yo'q.
        _strict_ok = False
        try:
            from app.services import channel_ai as _cai
            _strict_ok = bool(getattr(_cai, "last_strict_ok", False))
        except Exception:  # noqa: BLE001
            _strict_ok = False
        if parsed is not None and parsed.direction and parsed.symbol and not _strict_ok:
            try:
                from app.services.local_ai import strict_check as _strict
                _gate = _strict(text or "", parsed,
                                ref=_last_px(getattr(parsed, "symbol", None)))
                if _gate:
                    parsed = None
                    ai_reason = _gate
            except Exception as exc:  # noqa: BLE001
                logger.warning("[CH] strict gate: %s", exc)

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

        # v81: o'tgan signal haqidagi natija/maqtov posti YANGI signal emas
        try:
            _rep = await _repeat_result(session, text=text, raw=raw, parsed=parsed)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CH] takroriy natija tekshiruvi: %s", exc)
            _rep = ""
        if _rep:
            logger.warning("[CH-EMAS] %s | sabab=%s | matn=%s", src, _rep,
                           (text or raw or "")[:120])
            await _diag(skey, src, "emas", _rep, text or raw or "")
            try:
                await record_read(session, rec, False)
            except Exception:  # noqa: BLE001
                pass
            return "not_signal"

        _meta = {
            "channel": src,
            "username": (rec.get("username") or uname or ""),
            "chat_id": int(chat_id) if chat_id else 0,
            "msg_id": int(msg_id or 0),
            "posted_at": posted_dt,
            "text": (text or "").strip(),
            "ocr": ocr_txt or "",
        }
        try:
            verdict = await _save(session, rec, parsed, settings, src, meta=_meta)
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
                    verdict = await _save(session, rec, parsed, settings, src,
                                          meta=_meta)
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
        try:
            from app.database.models.app_setting import AppSetting
            models.append(AppSetting)
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


async def _flip_blocked(session, symbol: str, direction: str,
                        minutes: int) -> tuple[bool, str, int]:
    """v84: SL dan keyin darhol TESKARI tomonga o'tib ketmaslik.

    «buy signal berib, keyin sell tushib, keyin yana buyga chiqib ketadi —
    kichik balans sliv bo'ladi» shikoyatiga qarshi himoya.
    """
    if minutes <= 0 or direction not in ("BUY", "SELL"):
        return False, "", 0
    other = "SELL" if direction == "BUY" else "BUY"
    try:
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import select as _sel
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=int(minutes))
        rows = list((await session.execute(
            _sel(Signal).where(
                Signal.symbol == symbol,
                Signal.direction == other,
                Signal.status == "SL_HIT",
                Signal.closed_at.is_not(None),
                Signal.closed_at >= cutoff,
            ).order_by(Signal.closed_at.desc())
        )).scalars().all())
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH] flip tekshiruvi: %s", exc)
        return False, other, 0
    if not rows:
        return False, other, 0
    last = rows[0]
    try:
        when = last.closed_at
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        ago = int((datetime.now(timezone.utc) - when).total_seconds() // 60)
    except Exception:  # noqa: BLE001
        ago = int(minutes)
    return True, other, max(0, ago)


async def _users_for_signal(session, settings) -> list[int]:
    """v95: faqat ACCESS RO'YXATIDAGI ID lar + admin (signal ham, hisob ham)."""
    try:
        from app.services import access as _ACC
        db_ids = await _ACC.active_ids(session)   # v96: kvota/muddat bilan
    except Exception:  # noqa: BLE001
        db_ids = []
    return _recipient_ids(settings, db_ids)


async def _affordable(session, user_ids: list[int], entry: float, sl: float,
                      settings) -> list[int]:
    """v84: 0.01 lot bilan riski ham budjetga sig'maydigan hisoblarni olib tashlaydi."""
    from app.engine import entry as _EN
    from app.paper_trading.engine import PaperEngine
    ok_ids: list[int] = []
    pe = PaperEngine()
    for uid in user_ids or []:
        try:
            acc = await pe.get_account(session, uid)
            rp = getattr(acc, "risk_percent", None) or getattr(settings, "risk_percent", 0.5)
            g = _EN.balance_gate(float(getattr(acc, "balance", 0) or 0), float(rp),
                                 entry, sl,
                                 contract=float(getattr(settings, "contract_size", 100.0) or 100.0))
            if g["ok"]:
                ok_ids.append(uid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CH] balans tekshiruvi %s: %s", uid, exc)
            ok_ids.append(uid)
    return ok_ids


async def _apply_entry_plan(session, signal, parsed, settings, df=None) -> str:
    """v84: KIRISH NUQTASI rejasi.

    Qaytaradi: "wait"   — narx kutilmoqda (pozitsiya HALI ochilmaydi)
               "filled" — narx hozir zonada (darhol ochiladi)
               "no"     — reja yo'q (savdo ochilmaydi, signal bekor)
    """
    from app.engine import entry as EN
    from app.services import entry_settings as ES

    try:
        vals = await ES.load(session)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH] entry sozlamalari: %s", exc)
        vals = ES.cached()
    signal.entry_expires_at = None
    signal.entry_skip = ""
    if not bool(vals.get(ES.K_ENABLED, True)):
        signal.entry_mode = "OFF"
        signal.entry_status = "FILLED"
        signal.entry_note = "kirish rejimi o'chiq (darhol bozordan)"
        await session.commit()
        return "filled"

    symbol = str(signal.symbol or "")
    direction = str(signal.direction or "")
    # v95: KANAL SIGNALIGA BOT STRATEGIYASI QO'LLANMAYDI.
    # Kanal nima degan bo'lsa shu ishlatiladi:
    #   * zona/narx AYTILGAN bo'lsa  -> SHU zona kutiladi (narx kelguncha),
    #     zona eskirgan bo'lsa drift tekshiruvi kirishni to'sadi (quvish yo'q);
    #   * zona aytilMagan ("now"/bozor) bo'lsa -> darhol bozor narxida ochiladi.
    # Bot hech qachon kanal uchun o'zi zona HISOBLAMAYDI ("bot hisobladi" yo'q).
    _is_ch95 = (getattr(signal, "quality_mode", "") or "").upper() == "CHANNEL"
    if _is_ch95:
        _src95 = str(getattr(parsed, "entry_src", "") or "").upper()
        g_lo95, g_hi95 = (getattr(parsed, "zone_low", None),
                          getattr(parsed, "zone_high", None))
        if parsed is None:      # himoya: parsed kelmasa signal maydonlaridan
            g_lo95 = getattr(signal, "entry_low", None)
            g_hi95 = getattr(signal, "entry_high", None)
            _src95 = "TEXT" if (g_lo95 or g_hi95) else ""
        if _src95 in ("PIPS", "CTX"):
            g_lo95, g_hi95 = None, None
        if _src95 == "TEXT" and not (g_lo95 or g_hi95) \
                and getattr(parsed, "entry", None):
            g_lo95 = float(parsed.entry)      # kanal bitta narx aytdi ("now 4150")
        if g_lo95 or g_hi95:
            _lo95 = float(g_lo95 or g_hi95)
            _hi95 = float(g_hi95 or g_lo95)
            if _lo95 > _hi95:
                _lo95, _hi95 = _hi95, _lo95
            # narx AYNI PAYTDA zonada bo'lsa — kutmasdan ochiladi.
            # Manba tartibi: sham keshi -> jonli narx -> signal narxi.
            _ref95 = _last_px(symbol)
            if not _ref95:
                try:
                    from app.services import live_state as _ls95b
                    _ref95 = float(await _ls95b.get_price(symbol) or 0.0)
                except Exception:  # noqa: BLE001
                    _ref95 = 0.0
            _hit95, _fill95 = (False, 0.0)
            if _ref95:
                _hit95, _fill95 = EN.zone_hit(direction, _lo95, _hi95, _ref95)
            if _hit95 and _fill95:
                signal.entry_mode = "SIGNAL"
                signal.entry_status = "FILLED"
                signal.entry = float(_fill95)
                signal.entry_low = signal.entry_high = float(_fill95)
                signal.entry_expires_at = None
                signal.entry_note = ("kanal aytgan zona — narx shu yerda: "
                                     f"{float(_fill95):,.2f}")[:96]
                await session.commit()
                logger.info("[CH] #%s KANAL: zona ichida, darhol %.2f",
                            signal.id, _fill95)
                return "filled"
            signal.entry_mode = "SIGNAL"
            signal.entry_status = "WAIT"
            signal.entry = round((_lo95 + _hi95) / 2.0, 2)
            signal.entry_low, signal.entry_high = _lo95, _hi95
            signal.entry_expires_at = EN.deadline(int(vals.get(ES.K_WAIT, 30)))
            signal.entry_note = ("kanal aytgan zona — narx kelguncha kutamiz "
                                 "(bot strategiyasi yo'q)")[:96]
            await session.commit()
            logger.info("[CH] #%s KANAL: aytilgan zona %.2f-%.2f kutiladi",
                        signal.id, _lo95, _hi95)
            return "wait"
        _px95 = _last_px(symbol)                 # 1) sham keshi
        if not _px95:
            try:                                  # 2) jonli narx provayderi
                from app.services import live_state as _ls95
                _px95 = float(await _ls95.get_price(symbol) or 0.0)
            except Exception:  # noqa: BLE001
                _px95 = 0.0
        if not _px95:
            # v95: jonli narx yo'q bo'lsa kanal narxida "bozor fill" QILINMAYDI
            # (nomutanosiblik manbai edi): aytilgan narx bo'lsa — SHU kutiladi.
            if float(signal.entry or 0) > 0:
                signal.entry_mode = "SIGNAL"
                signal.entry_status = "WAIT"
                signal.entry_low = signal.entry_high = float(signal.entry)
                signal.entry = float(signal.entry)
                signal.entry_expires_at = EN.deadline(int(vals.get(ES.K_WAIT, 30)))
                signal.entry_note = ("jonli narx yo'q — kanal aytgan narx "
                                     "kutiladi (taxmin qilinmaydi)")[:96]
                await session.commit()
                logger.info("[CH] #%s KANAL: jonli narx yo'q, %s kutiladi",
                            signal.id, signal.entry)
                return "wait"
            signal.entry_status = "CANCELLED"
            signal.status = SignalStatus.CANCELLED.value
            signal.is_active = False
            signal.close_reason = "JONLI NARX YO'Q"
            await session.commit()
            return "no"
        signal.entry_mode = "MARKET"
        signal.entry_status = "FILLED"
        signal.entry = float(_px95)
        signal.entry_low = float(_px95)
        signal.entry_high = float(_px95)
        signal.entry_expires_at = None
        signal.entry_note = ("kanal zona aytmadi — bozor narxida darhol "
                             f"({(_px95 or 0):,.2f})")[:96]
        await session.commit()
        logger.info("[CH] #%s KANAL: zona aytilmadi, bozordan %s", signal.id, _px95)
        return "filled"
    ref = _last_px(symbol) or float(signal.entry or 0)
    df5 = df15 = None
    if _candles is not None:
        for tf_try, box in (("5m", "5"), ("15m", "15")):
            try:
                d = _candles.get_df(symbol, tf_try)
            except Exception:  # noqa: BLE001
                d = None
            if tf_try == "5m":
                df5 = d
            else:
                df15 = d
    if df5 is None:
        df5 = df
    # signal AYTGAN kirish faqat xabar matnidan olingan bo'lsa ishlatiladi
    _src = str(getattr(parsed, "entry_src", "") or "").upper()
    g_lo, g_hi = getattr(parsed, "zone_low", None), getattr(parsed, "zone_high", None)
    if _src in ("PIPS", "CTX"):
        g_lo = g_hi = None
    if _src == "TEXT" and not (g_lo or g_hi) and getattr(parsed, "entry", None):
        g_lo = float(parsed.entry)
    if _src == "" and (g_lo or g_hi) and getattr(parsed, "entry", None):
        pass    # boshqa parser zonani matndan olgan

    plan = EN.build_plan(direction, ref, float(signal.sl or 0), g_lo, g_hi,
                         df5=df5, df15=df15)
    if not plan.ok:
        signal.entry_mode = "NONE"
        signal.entry_status = "CANCELLED"
        signal.entry_skip = str(plan.why or "kirish nuqtasi topilmadi")[:160]
        signal.status = SignalStatus.CANCELLED.value
        signal.is_active = False
        try:
            signal.close_reason = EN.CANCEL_TEXT
            signal.closed_at = datetime.now(timezone.utc)
        except Exception:  # noqa: BLE001
            pass
        await session.commit()
        logger.warning("[CH] #%s KIRISH YO'Q: %s", signal.id, signal.entry_skip)
        return "no"

    # reja qiymatlarini signalga yozamiz
    signal.entry_mode = plan.mode
    signal.entry_note = plan.note[:96]
    signal.entry_low = float(plan.low)
    signal.entry_high = float(plan.high)
    signal.entry = float(plan.level)
    if plan.mode == "COMPUTED":
        # kanal R asosida TP bergan bo'lsa — yangi kirishga qarab qayta hisoblanadi
        if str(getattr(signal, "entry_tps_src", "") or "") != "CHANNEL":
            signal.tp1 = r_price(str(signal.direction), signal.entry, signal.sl, 1)
            signal.tp2 = r_price(str(signal.direction), signal.entry, signal.sl, 2)
            signal.tp3 = r_price(str(signal.direction), signal.entry, signal.sl, 3)
    # balans tekshiruvi: hech kim 0.01 lot bilan ham kira olmasa — kutmaymiz
    try:
        ids = await _users_for_signal(session, settings)
        ok_ids = await _affordable(session, ids, signal.entry, signal.sl, settings)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH] balans guruhi: %s", exc)
        ids, ok_ids = [], []
    if False:   # v94: balans darvozasi OLIP TASHLANDI (savdo har doim ochiladi)
        from app.engine import entry as _E2
        _one = ids[0]
        _txt = ""
        try:
            from app.paper_trading.engine import PaperEngine as _PE
            _acc = await _PE().get_account(session, _one)
            _g = _E2.balance_gate(float(getattr(_acc, "balance", 0) or 0),
                                  float(getattr(_acc, "risk_percent", 0.5) or 0.5),
                                  signal.entry, signal.sl,
                                  contract=float(getattr(settings, "contract_size", 100.0) or 100.0))
            _txt = _g["text"]
        except Exception:  # noqa: BLE001
            _txt = "0.01 lot bilan risk budjetdan katta"
        signal.entry_status = "CANCELLED"
        signal.entry_skip = ("balans yetmaydi: " + _txt)[:160]
        signal.status = SignalStatus.CANCELLED.value
        signal.is_active = False
        signal.close_reason = "BALANS YETMAYDI"
        signal.closed_at = datetime.now(timezone.utc)
        await session.commit()
        logger.warning("[CH] #%s BALANS YETMAYDI: %s", signal.id, signal.entry_skip)
        return "no"

    if plan.fill_now:
        fill = EN.fill_price(direction, plan.low, plan.high, ref) or plan.level
        # v99: entry ALMASHDI (bozor narxi) — SL/TP ni YANGI kirishga
        # qayta tekshiramiz. Teskari tomonda qolsa — signal RAD (karta yo'q).
        from app.engine.sizing import resanitize_levels as _RS99
        _rs = _RS99(direction.value, float(fill), signal.sl, signal.tp1,
                    signal.tp2, signal.tp3, signal.entry_tps_src, signal.symbol)
        if not _rs["ok"]:
            signal.entry = float(fill)
            signal.entry_low = signal.entry_high = float(fill)
            signal.entry_status = "CANCELLED"
            signal.status = SignalStatus.CANCELLED.value
            signal.is_active = False
            signal.close_reason = ("RAD: " + _rs["why"])[:96]
            signal.entry_skip = str(_rs["why"])[:160]
            signal.closed_at = datetime.now(timezone.utc)
            await session.commit()
            logger.warning("[CH] #%s v99 RAD (bozor fill): %s",
                           signal.id, _rs["why"])
            return "no"
        signal.sl = float(_rs["sl"])
        signal.tp1 = float(_rs["tp1"])
        signal.tp2 = float(_rs["tp2"])
        signal.tp3 = float(_rs["tp3"])
        signal.entry_tps_src = _rs["tps_src"]
        # v100: kanal jim edi -> darajalarni YANGI entry bo'yicha bozordan olamiz
        if str(signal.entry_skip or "") == "SILENT_LEVELS" and df is not None:
            try:
                from app.engine.market_levels import market_levels as _ML100
                _ml2 = _ML100(direction.value, float(fill), df, signal.symbol)
                if _ml2:
                    signal.sl = float(_ml2["sl"])
                    signal.tp1 = float(_ml2["tp1"])
                    signal.tp2 = float(_ml2["tp2"])
                    signal.tp3 = float(_ml2["tp3"])
                    signal.entry_tps_src = "MARKET"
                    signal.entry_skip = ""
                    logger.info("[CH] v100 fill bozor darajalari #%s: sl=%.2f "
                                "tp1=%.2f", signal.id, signal.sl, signal.tp1)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[CH] v100 fill market: %s", exc)
        signal.entry = float(fill)
        signal.entry_low = signal.entry_high = float(fill)
        signal.entry_status = "FILLED"
        signal.entry_note = (plan.note + f" · narx shu yerda: {fill:,.2f}")[:96]
        await session.commit()
        return "filled"

    signal.entry_status = "WAIT"
    signal.entry_expires_at = EN.deadline(int(vals.get(ES.K_WAIT, 30)))
    await session.commit()
    logger.info("[CH] #%s KUTILMOQDA %s %.2f-%.2f (%s) %s daq",
                signal.id, direction, plan.low, plan.high, plan.note,
                int(vals.get(ES.K_WAIT, 30)))
    return "wait"


async def _limit_blocked(session, settings,
                         direction: str | None = None) -> tuple[bool, int, int]:
    """v62/v67: (bloklanganmi, ochiq soni, limit).

    v67: chegara YO'NALISH bo'yicha — bir yo'nalishda maks. N ta faol signal.
    Ya'ni 3 ta SELL ochiq bo'lsa, yangi SELL tashlanadi; BUY o'z hisobida.
    """
    limit_act = int(getattr(settings, "max_active_signals", 3) or 3)
    n_act = await _active_signals_count(session, direction)
    return (n_act >= limit_act), n_act, limit_act


# ================= v81: o'tgan signal haqidagi postlar (maqtov/natija) =================
_RESULT_MARK = re.compile(
    r"(pips?|punkt|point|profit|foyda|zarar|natija|result|recap|oldik|oldi\b|"
    r"yopildi|hit\b|tp\s*\d?\s*(bajarildi|done|ok)|maqtov|rahmat|tabrik|"
    r"\+\s*\d{2,4}\s*%|\u2705|\u2705|\U0001F680|\U0001F525)", re.I)
_RESULT_HARD = re.compile(
    r"(natija|result|recap|pips?\s*\+?|\+\s*\d+\s*(pip|punkt|%|usd|\$)|"
    r"oldik|foyda|profit|tabrik|maqtov|rahmat|yopildi|hit)", re.I)
_NUM81 = re.compile(r"\b\d{3,5}(?:[.,]\d{1,3})?\b")


async def _tracked_levels(session, days: int = 7, limit: int = 60) -> list[float]:
    """Oxirgi kunlardagi signallarning narx darajalari (entry/sl/tp)."""
    from datetime import timedelta
    from sqlalchemy import select as _sel
    from app.database.models.signal import Signal as _S
    out: list[float] = []
    try:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        rows = list((await session.execute(
            _sel(_S).where(_S.created_at >= since).order_by(_S.id.desc()).limit(limit)
        )).scalars().all())
    except Exception:  # noqa: BLE001
        return out
    for r in rows:
        if getattr(r, "quality_mode", "") != "CHANNEL":
            continue
        for attr in ("entry", "sl", "tp1", "tp2", "tp3"):
            try:
                v = float(getattr(r, attr, 0) or 0)
            except (TypeError, ValueError):
                continue
            if v > 0:
                out.append(v)
    return out


async def _repeat_result(session, *, text: str, raw: str, parsed) -> str:
    """v81: «TP1 ✅ TP2 ✅ +250$ oldik», «signallarimiz yana ishladi» kabi post —
    yangi signal EMAS, o'tgan signalning natijasi (yolg'on signal manbai)."""
    blob = " ".join(x for x in ((text or ""), (raw or "")) if x)
    if not blob.strip():
        return ""
    # O'Z rejasi (SL yoki entry+TP) bo'lsa — yangi signal bo'lishi mumkin
    own = False
    try:
        from app.services.local_ai import _full_plan, analyze_ex
        own = bool(_full_plan((text or "").strip()))
        if not own:
            _s2, _w2, _v2 = analyze_ex(text or "", ocr="", has_image=False)
            own = _s2 is not None and not _v2
    except Exception:  # noqa: BLE001
        own = False
    # Matnning o'zi «natija/maqtov» bo'lsa — shu yerda ham veto (ikkinchi qavat)
    try:
        from app.services.local_ai import _result_veto
        _rv = _result_veto(blob, own)
        if _rv:
            return _rv
    except Exception:  # noqa: BLE001
        pass
    if not _RESULT_MARK.search(blob):
        return ""
    levels = await _tracked_levels(session)
    if not levels:
        return ""
    hits = 0
    seen: set[int] = set()
    for m in _NUM81.finditer(blob):
        try:
            v = float(m.group(0).replace(",", "."))
        except ValueError:
            continue
        if v < 100 or v in seen:
            continue
        seen.add(v)
        for lv in levels:
            if lv and abs(v - lv) / lv <= 0.0025:
                hits += 1
                break
    if hits <= 0:
        return ""
    if own:
        if hits >= 2 and _RESULT_HARD.search(blob):
            return f"oldingi signal natijasi (narxlar mos: {hits} daraja)"
        return ""
    return f"oldingi signal haqidagi post (narxlar mos: {hits} daraja)"


async def _save(session, ch: dict, parsed, settings: Settings, src: str,
                meta: dict | None = None) -> str:
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
        logger.warning("[CH] kirish narxi yo'q (matn/jonli) — signal RAD (v95)")
        return "bad_entry"

    # ============ v95: KANAL DARAJALARI — SANITIZE (user qoidasi) ============
    # SL/TP aytilmagan: SL = 10 pip, TP1 = 40 pip, TP2 = 50 pip.
    # Lot1 TP1 da yopiladi; Lot2 TP2 ga, bormasa TP1..TP2 orasida (pol = TP1).
    # SL teskari tomonda bo'lsa — bu SIGNAL EMAS (hisobga yozilmaydi).
    from app.engine.sizing import sanitize_channel_levels as _SAN95
    _san = _SAN95(direction.value, entry, getattr(parsed, "sl", None),
                  (getattr(parsed, "tps", None) or ([getattr(parsed, "tp", None)]
                   if getattr(parsed, "tp", None) else [])),
                  symbol)
    if not _san["ok"]:
        logger.warning("[CH] darajalar nosog'lom: %s — signal RAD (v95)", _san["why"])
        return "bad_levels"
    levels_entry = float(_san["entry"])
    levels_sl = float(_san["sl"])
    tp1 = float(_san["tp1"]); tp2 = float(_san["tp2"]); tp3 = float(_san["tp3"])
    _tps_src95 = _san["tps_src"]
    # ---- v100: kanal SL/TP aytmagan bo'lsa — darajalarni BOZOR beradi ----
    _silent100 = (getattr(parsed, "sl", None) is None
                  and not (getattr(parsed, "tps", None)
                           or getattr(parsed, "tp", None)))
    if _silent100 and df is not None:
        try:
            if len(df) >= 20:
                from app.engine.market_levels import market_levels as _ML100
                _ml = _ML100(direction.value, levels_entry, df, symbol)
                if _ml:
                    levels_sl = float(_ml["sl"])
                    tp1 = float(_ml["tp1"])
                    tp2 = float(_ml["tp2"])
                    tp3 = float(_ml["tp3"])
                    _tps_src95 = "MARKET"
                    logger.info("[CH] v100 bozor darajalari: sl=%.2f tp1=%.2f "
                                "tp2=%.2f (ATR=%.2f, risk=%.2f)", levels_sl,
                                tp1, tp2, float(_ml["atr"]), float(_ml["risk"]))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CH] v100 market levels: %s", exc)
    risk = abs(levels_entry - levels_sl)
    zlo = getattr(parsed, "zone_low", None)
    zhi = getattr(parsed, "zone_high", None)
    if zlo and zhi:
        a, b = float(zlo), float(zhi)
        entry_low, entry_high = (a, b) if a <= b else (b, a)
        if not parsed.entry:
            levels_entry = (a + b) / 2.0
    else:
        entry_low, entry_high = levels_entry - risk * 0.1, levels_entry + risk * 0.1
    ch_tps = [] if _tps_src95 == "DEFAULT" else [tp1, tp2]
    logger.info("[CH] v95 darajalar: entry=%.2f sl=%.2f tp1=%.2f tp2=%.2f (%s)",
                levels_entry, levels_sl, tp1, tp2, _tps_src95)

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
    _tp_src = "kanal posti" if ch_tps else "default 40/50 pip (v95)"
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
                await _alert_once(
                    "opposite:" + str(direction.value), src,
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

    # v84: SL dan keyin darhol TESKARI tomonga o'tish (flip-flop) himoyasi
    try:
        from app.services import entry_settings as _ES
        _vals = _ES.cached()
        _cool = int(_vals.get(_ES.K_COOL, 15) or 0)
        _flip, _odir, _ago = await _flip_blocked(session, symbol, direction.value, _cool)
        if _flip:
            logger.warning("[CH] FLIP-FLOP himoyasi: %s %s dan keyin %s olinmadi (%s daq)",
                           _odir, _ago, direction.value, _cool)
            try:
                await _alert_once(
                    "flip:" + str(direction.value), src,
                    f"\U0001F6E1 <b>Flip-flop himoyasi</b>: {_odir} {_ago} daqiqa oldin "
                    f"STOP bo'ldi.\nYangi {direction.value} signal olinmadi \u2014 "
                    f"{symbol} ({_esc(src)}).\n"
                    f"<i>Bitta yo'nalishda stop bo'lib, darhol teskari tomonga o'tish "
                    f"hisobni yeb qo'yadi. Tanaffus: {_cool} daqiqa "
                    f"(KANALLAR \u2192 Kirish nuqtasi).</i>")
            except Exception:  # noqa: BLE001
                pass
            return "flip"
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH] flip himoyasi: %s", exc)

    # v62/v67: BIR YO'NALISHDA ko'pi bilan N ta faol signal. Ortiqchasi TASHLANADI
    # (navbat yo'q — bittasi yopilgach ham eski signal qaytarilmaydi, faqat YANGI olinadi).
    try:
        _blocked, n_act, limit_act = await _limit_blocked(session, settings, direction.value)
        if _blocked:
            logger.warning(
                "[CH] LIMIT %s %d/%d — yangi signal qabul qilinmadi: %s (%s)",
                direction.value, n_act, limit_act, symbol, src)
            try:
                await _alert_once(
                    "limit:" + str(direction.value), src,
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

    _meta = dict(meta or {})

    def _mk() -> Signal:
        return Signal(
            source_channel=str(_meta.get("channel") or src or "")[:160],
            source_username=str(_meta.get("username") or "")[:64],
            source_msg_id=int(_meta.get("msg_id") or 0),
            source_posted_at=_meta.get("posted_at"),
            source_text=str(_meta.get("text") or "")[:1500],
            source_ocr=str(_meta.get("ocr") or "")[:900],
            symbol=symbol, timeframe=timeframe, direction=direction.value,
            status=SignalStatus.ACTIVE.value, is_active=True,
            score=6.5, confidence=60.0, win_probability=55.0,
            signal_no=total + 1, strength="GOOD",
            regime="", mtf_alignment="NONE", quality_mode="CHANNEL",
            entry=levels_entry, entry_low=entry_low, entry_high=entry_high,
            entry_tps_src=_tps_src95,
            entry_skip=("SILENT_LEVELS" if _silent100 else ""),
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
    except Exception as _cexc:  # noqa: BLE001
        # v85: baza uzilgan bo'lsa — chaqiruvchi (ingest_raw) navbatga qo'yadi
        from app.services import dbhealth as _dh
        if _dh.is_conn_error(_cexc):
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001
                pass
        raise

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

    # ================= v84: KIRISH NUQTASI REJASI =================
    # Narx kutilganda pozitsiya OCHILMAYDI; narx zonaga kelganda kuzatuv loopi ochadi.
    _plan_state = "filled"
    try:
        _plan_state = await _apply_entry_plan(session, signal, parsed, settings, df)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[CH] kirish rejasi: %s", exc)
        _plan_state = "filled"
    if _plan_state == "no":
        # v94: "KIRISH BO'LMADI" kartasi YUBORILMAYDI — faqat log va diagnostika
        logger.info("[CH] #%s kirish rejasi yo'q (karta yuborilmadi): %s",
                    signal.id, str(signal.entry_skip or "")[:120])
        try:
            await _diag(sk, src, "emas",
                        "kirish nuqtasi yo'q: " + str(signal.entry_skip or ""),
                        str(_meta.get("text") or ""))
        except Exception:  # noqa: BLE001
            pass
        return "entry_no"

    if _plan_state == "wait":
        try:
            await _notify(signal)          # karta: KIRISH KUTILMOQDA + muddat
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CH] kutish kartasi: %s", exc)
        logger.info("[CH] SIGNAL #%s %s %s KUTILMOQDA zona=%.2f-%.2f (%s)",
                    signal.id, symbol, direction.value,
                    signal.entry_low or 0, signal.entry_high or 0,
                    signal.entry_note or "")
        return "ok"

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


# ================= v101: FRAGMENT BUFFER (bo'lib yozilgan signal) =================
_FRAG101: dict = {}
_FRAG_WAIT = 60.0        # daraja qismi kutadi
_FRAG_NOW_WAIT = 45.0    # "Sell now" levels kutadi


def _frag_marks(t: str) -> dict:
    from app.services import channel_real as CR
    s = CR.norm(t)
    _lo, _hi, mid = CR._zone(s)
    slv, slp = CR._sl(s)
    nb, ns = len(CR._BUY.findall(s)), len(CR._SELL.findall(s))
    return {"zone": mid is not None,
            "sl": (slv is not None or bool(slp)),
            "dir": bool(nb or ns),
            "now": bool(CR._NOW.search(s)),
            "tp": bool(re.search(r"tp\s*\d", s))}


def _frag_drop(chat_id: int) -> None:
    b = _FRAG101.pop(chat_id, None)
    if b and b.get("task"):
        try:
            b["task"].cancel()
        except Exception:  # noqa: BLE001
            pass


async def _frag_later(chat_id: int, wait: float) -> None:
    import asyncio as _a
    try:
        await _a.sleep(wait)
    except Exception:  # noqa: BLE001
        return
    b = _FRAG101.pop(chat_id, None)
    if not b:
        return
    joined = "\n".join(b["parts"])
    logger.info("[CH] v101 buffer vaqti #%s: %r", chat_id, joined[:80])
    try:
        await ingest_raw(text=joined, **b["kwargs"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH] v101 flush: %s", exc)


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
    _kw = dict(
        ch=ch, msg_id=int(getattr(message, "message_id", 0) or 0),
        chat_id=chat_id, title=getattr(chat, "title", None) or "",
        username=username,
        grouped_id=getattr(message, "media_group_id", None),
        reply_to=getattr(getattr(message, "reply_to_message", None), "message_id", None),
        require_listed=True,
        posted_at=getattr(message, "date", None),   # v81
    )

    # ---- v101 (1): KO'P SATRLI post — har satr alohida signal bo'lsa ----
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    if len(lines) >= 2:
        from app.services.channel_real import strict_verdict as _SV101
        try:
            sig_lines = [l for l in lines
                         if str(_SV101(l).get("verdict") or "") == "SIGNAL"]
        except Exception:  # noqa: BLE001
            sig_lines = []
        if len(sig_lines) >= 2:
            logger.info("[CH] v101 ko'p satr: %d ta alohida signal", len(sig_lines))
            for l in sig_lines:
                await ingest_raw(text=l, image_bytes=img, **_kw)
            return

    # ---- v101 (2): FRAGMENT BUFFER — signal bo'lib yozilgan ----
    mk = _frag_marks(text or "")
    complete = bool(mk["dir"] and mk["zone"] and (mk["sl"] or mk["tp"]))
    now_only = bool(mk["dir"] and mk["now"]
                    and not mk["zone"] and not mk["sl"] and not mk["tp"])
    has_frag = bool(mk["dir"] or mk["zone"] or mk["sl"] or mk["tp"])
    if complete:
        _frag_drop(chat_id)
    elif now_only or has_frag:
        b = _FRAG101.setdefault(chat_id, {"parts": [], "task": None, "kwargs": _kw})
        b["parts"] = (b["parts"] + [text or ""])[-6:]
        b["kwargs"] = _kw
        joined = "\n".join(b["parts"])
        mj = _frag_marks(joined)
        if mj["dir"] and mj["zone"] and (mj["sl"] or mj["tp"]):
            _frag_drop(chat_id)
            logger.info("[CH] v101 buffer yig'di #%s: %r", chat_id, joined[:80])
            await ingest_raw(text=joined, image_bytes=img, **_kw)
            return
        wait = _FRAG_NOW_WAIT if now_only else _FRAG_WAIT
        if b.get("task"):
            try:
                b["task"].cancel()
            except Exception:  # noqa: BLE001
                pass
        import asyncio as _a
        b["task"] = _a.ensure_future(_frag_later(chat_id, wait))
        logger.info("[CH] v101 fragment buffer #%s (%.0fs): %r",
                    chat_id, wait, (text or "")[:60])
        return

    await ingest_raw(text=text, image_bytes=img, **_kw)


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
    _origin_date = None
    try:
        _origin_date = getattr(orig, "date", None) if orig is not None else None
    except Exception:  # noqa: BLE001
        _origin_date = None
    return await ingest_raw(
        ch=ch, text=text, image_bytes=img,
        msg_id=mid, chat_id=chat_id, title=title, username=username,
        require_listed=False,
        posted_at=_origin_date or getattr(message, "date", None),   # v81
    )
