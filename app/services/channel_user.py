"""Foydalanuvchi Telegram akkaunti (Telethon) — kanallarni admin'siz o'qish.

Sessiya SystemLog(component='tg_session') da saqlanadi (yangi jadval YO'Q).
API_ID/HASH: .env yoki SystemLog('tg_api').
"""
from __future__ import annotations

import unicodedata

from app.core.config import get_settings
from app.core.logging import get_logger
from app.database.session import async_session_factory
from app.services.channel_store import (
    API_COMPONENT,
    SESSION_COMPONENT,
    load_json_log,
    save_json_log,
)

logger = get_logger(__name__)

PENDING_COMPONENT = "tg_pending"

_pending = None  # TelegramClient during login
_phone = ""
_code_hash = ""

_CLIENT_KW = dict(
    device_model="Desktop",
    system_version="Windows 10",
    app_version="4.16.8 x64",
    lang_code="en",
    system_lang_code="en",
)


def make_client(session_str: str, api_id: int, api_hash: str):
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    return TelegramClient(
        StringSession(session_str or ""),
        int(api_id),
        str(api_hash),
        **_CLIENT_KW,
    )


def _digits(text: str | None) -> str:
    return "".join(c for c in (text or "") if c.isdigit())


_CYR_LAT = str.maketrans({
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H",
    "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X", "І": "I",
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y",
    "х": "x", "і": "i", "ё": "e",
})


def _clean_password(text: str | None) -> str:
    p = unicodedata.normalize("NFC", text or "")
    p = "".join(c for c in p if c.isprintable() and ord(c) >= 32)
    return p.translate(_CYR_LAT)


def _human_err(exc: BaseException) -> str:
    name = type(exc).__name__
    text = str(exc)
    low = f"{name} {text}".lower()
    if "flood" in low:
        return "Telegram kutish qo'ydi. 5–10 daqiqa keyin /akkaunt."
    if "phone" in low and "invalid" in low:
        return "Telefon raqam noto'g'ri. +998... formatida yuboring."
    if "banned" in low:
        return "Bu raqam Telegramda bloklangan."
    if "expired" in low:
        return "Kod eskirgan."
    if "invalid" in low and "code" in low:
        return "Kod noto'g'ri."
    return text[:240]


async def credentials() -> tuple[int, str, str]:
    """(api_id, api_hash, session_string)."""
    s = get_settings()
    api_id = int(getattr(s, "telegram_api_id", 0) or 0)
    api_hash = (getattr(s, "telegram_api_hash", "") or "").strip()
    session = (getattr(s, "telegram_session", "") or "").strip()
    async with async_session_factory() as db:
        if not api_id or not api_hash:
            api = await load_json_log(db, API_COMPONENT)
            api_id = api_id or int(api.get("api_id") or 0)
            api_hash = api_hash or str(api.get("api_hash") or "")
        if not session:
            row = await load_json_log(db, SESSION_COMPONENT)
            session = str(row.get("session") or "")
    return api_id, api_hash, session


async def save_api(api_id: int, api_hash: str) -> None:
    async with async_session_factory() as db:
        await save_json_log(db, API_COMPONENT, {"api_id": int(api_id), "api_hash": api_hash})


async def save_session(session_str: str) -> None:
    async with async_session_factory() as db:
        await save_json_log(db, SESSION_COMPONENT, {"session": session_str})
        await save_json_log(db, PENDING_COMPONENT, {})


async def clear_session() -> None:
    async with async_session_factory() as db:
        await save_json_log(db, SESSION_COMPONENT, {})


async def is_linked() -> bool:
    api_id, api_hash, session = await credentials()
    return bool(api_id and api_hash and session)


async def _dump_pending() -> None:
    sess = ""
    try:
        if _pending is not None:
            sess = _pending.session.save()
    except Exception:  # noqa: BLE001
        sess = ""
    async with async_session_factory() as db:
        await save_json_log(
            db,
            PENDING_COMPONENT,
            {"session": sess, "phone": _phone, "code_hash": _code_hash},
        )


async def _drop_client() -> None:
    global _pending
    if _pending is None:
        return
    try:
        await _pending.disconnect()
    except Exception:  # noqa: BLE001
        pass
    _pending = None


async def _ensure_pending() -> bool:
    global _pending, _phone, _code_hash
    if _pending is not None:
        try:
            if not _pending.is_connected():
                await _pending.connect()
            return True
        except Exception:  # noqa: BLE001
            _pending = None
    api_id, api_hash, _sess = await credentials()
    async with async_session_factory() as db:
        row = await load_json_log(db, PENDING_COMPONENT)
    if not row.get("session") or not row.get("phone") or not api_id or not api_hash:
        return False
    try:
        client = make_client(str(row.get("session") or ""), api_id, api_hash)
        await client.connect()
        _pending = client
        _phone = str(row.get("phone") or "")
        _code_hash = str(row.get("code_hash") or "")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.exception("[TG-USER] pending restore: %s", exc)
        return False


async def start_login(api_id: int, api_hash: str, phone: str) -> str:
    """Kod yuboriladi. Xato matnini qaytaradi (bo'sh = OK)."""
    global _pending, _phone, _code_hash
    try:
        import telethon  # noqa: F401
    except ImportError:
        return "Telethon o'rnatilmagan. Deploy qiling."
    await save_api(api_id, api_hash)
    phone = phone.strip()
    await _drop_client()
    try:
        client = make_client("", int(api_id), api_hash)
        await client.connect()
        result = await client.send_code_request(phone)
        _pending = client
        _phone = phone
        _code_hash = result.phone_code_hash
        await _dump_pending()
        logger.info("[TG-USER] kod yuborildi: %s", phone[-4:])
        return ""
    except Exception as exc:  # noqa: BLE001
        logger.exception("[TG-USER] login start: %s", exc)
        await _drop_client()
        return f"Kod yuborilmadi: {_human_err(exc)}"


async def resend_code() -> str:
    """Yangi kod so'raydi. Bo'sh = OK."""
    global _code_hash
    if not await _ensure_pending():
        return "Sessiya yo'q. /akkaunt bilan qayta boshlang."
    try:
        result = await _pending.send_code_request(_phone)
        _code_hash = result.phone_code_hash
        await _dump_pending()
        logger.info("[TG-USER] kod qayta yuborildi")
        return ""
    except Exception as exc:  # noqa: BLE001
        logger.exception("[TG-USER] resend: %s", exc)
        return f"Yangi kod kelmadi: {_human_err(exc)}"


async def twofa_hint() -> str:
    if not await _ensure_pending():
        return ""
    try:
        from telethon.tl.functions.account import GetPasswordRequest
        pwd = await _pending(GetPasswordRequest())
        return str(getattr(pwd, "hint", None) or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[TG-USER] 2fa hint: %s", exc)
        return ""


async def _try_passwords(password: str) -> None:
    from telethon.errors import PasswordHashInvalidError

    raw = _clean_password(password)
    variants: list[str] = []
    for v in (raw, raw.strip(), password or "", (password or "").strip()):
        if v and v not in variants:
            variants.append(v)
    last: BaseException | None = None
    for v in variants:
        try:
            logger.info("[TG-USER] 2fa urinish len=%s", len(v))
            await _pending.sign_in(password=v)
            return
        except PasswordHashInvalidError as exc:
            last = exc
            continue
    if last:
        raise last
    raise RuntimeError("2FA parol bo'sh")


async def finish_login(code: str, password: str | None = None) -> str:
    """Kod (va ixtiyoriy 2FA). Bo'sh = OK. Maxsus: 2FA_NEEDED, 2FA_WRONG, EXPIRED_RESENT."""
    global _pending, _phone, _code_hash
    if not await _ensure_pending():
        return "Avval telefon yuboring. /akkaunt"
    code = _digits(code)
    try:
        from telethon.errors import (
            PasswordHashInvalidError,
            PhoneCodeExpiredError,
            PhoneCodeInvalidError,
            SessionPasswordNeededError,
        )

        if password and not code:
            await _try_passwords(password)
        else:
            try:
                await _pending.sign_in(_phone, code, phone_code_hash=_code_hash)
            except SessionPasswordNeededError:
                await _dump_pending()
                if not password:
                    return "2FA_NEEDED"
                await _try_passwords(password)
            except PhoneCodeExpiredError:
                err = await resend_code()
                if err:
                    return f"Kod eskirgan. {err}"
                return "EXPIRED_RESENT"
            except PhoneCodeInvalidError:
                return "INVALID"
        sess = _pending.session.save()
        await save_session(sess)
        await _drop_client()
        logger.info("[TG-USER] akkaunt ulandi")
        return ""
    except Exception as exc:  # noqa: BLE001
        logger.exception("[TG-USER] sign_in: %s", exc)
        name = type(exc).__name__
        low = f"{name} {exc}".lower()
        if "passwordhashinvalid" in low or "hash value" in low:
            return "2FA_WRONG"
        if "password" in low and "needed" in low:
            await _dump_pending()
            return "2FA_NEEDED"
        if "expired" in low:
            err = await resend_code()
            if not err:
                return "EXPIRED_RESENT"
        return f"Kirish xato: {_human_err(exc)}"
