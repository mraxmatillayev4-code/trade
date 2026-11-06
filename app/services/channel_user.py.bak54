"""Foydalanuvchi Telegram akkaunti (Telethon) — kanallarni admin'siz o'qish.

Sessiya SystemLog(component='tg_session') da saqlanadi (yangi jadval YO'Q).
API_ID/HASH: .env yoki SystemLog('tg_api').

v52 tuzatishlari (Telegram kod yuborishni rad etganda):
  * `SendCodeUnavailableError` ("all available options ... already used") tushunarli
    o'zbekcha matnga aylantiriladi + qancha kutish kerakligi aytiladi.
  * Ketma-ket kod so'rashga 60 soniya "sovutish" (cooldown) — flood kuchaymasin.
  * Xato bo'lsa ESKI kod hash saqlanib qoladi (kelgan kod ishlayveradi).
  * `sms` endi: Telethon force_sms ishlamaydi -> qo'shimcha "qayta yuborish" urinishi.

v51 tuzatishlari (kod kelmayapti / akkaunt chiqib ketdi muammolari):
  * Kod QANDAY yuborilgani aytiladi (ilova / SMS / qo'ng'iroq) — Telegram yangi
    api_id bilan ko'pincha SMS yubormaydi, kodni Telegram ilovasiga yozadi.
  * `sms` so'zi bilan majburiy SMS (force_sms=True) so'raladi.
  * FloodWait aniq daqiqa bilan ko'rsatiladi (necha daqiqa kutish kerak).
  * Kodni qayta so'rash FAQAT foydalanuvchi "qayta" desa bo'ladi.
  * `session_status()` — saqlangan sessiya tirikmi yoki o'chganmi (get_me bilan).
"""
from __future__ import annotations

import time
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
_delivery = ""   # kod qanday yuborildi: app | sms | call | flash
_last_request_ts = 0.0   # oxirgi kod so'rovi vaqti (cooldown uchun)

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


def flood_seconds(exc: BaseException) -> int:
    """FloodWaitError ichidan kutish sekundini oladi."""
    sec = int(getattr(exc, "seconds", 0) or 0)
    if sec:
        return sec
    import re
    m = re.search(r"(\d+)\s*second", str(exc) or "", re.I)
    return int(m.group(1)) if m else 0


def _wait_text(sec: int) -> str:
    if sec <= 0:
        return "Biroz kutib qayta urinib ko'ring."
    if sec < 60:
        return f"{sec} soniya kutib, <b>qayta</b> yozing."
    mins = sec // 60
    if mins < 60:
        return f"{mins} daqiqa kutib, <b>qayta</b> yozing."
    return f"{mins // 60} soat {mins % 60} daqiqa kutib, <b>qayta</b> yozing."


def _human_err(exc: BaseException) -> str:
    name = type(exc).__name__
    text = str(exc)
    low = f"{name} {text}".lower()
    if ("sendcodeunavailable" in low or "all available options" in low
            or "send_code_unavailable" in low):
        return (
            "Telegram hozir bu raqamga yangi kod yubormayapti "
            "(barcha yuborish usullari ishlatilgan).\n"
            "Odatda bu cheklov 30 daqiqadan 24 soatgacha turadi.\n"
            "Nima qilish kerak:\n"
            "1) Telegram ilovangizda <b>«Telegram»</b> chatini ochib ko'ring — "
            "kod o'sha yerga kelgan bo'lishi mumkin (u xabar o'chib ketmaydi).\n"
            "2) 30-60 daqiqa kutib, keyin <b>qayta</b> deb yozing.\n"
            "3) Kutish davomida kod so'ramang — har urinish cheklovni uzaytiradi.\n"
            "4) Akkaunt kerak bo'lmasa: kanalga botni admin qilib qo'shsangiz, "
            "postlar botga to'g'ridan-to'g'ri keladi."
        )
    if "flood" in low:
        return ("Telegram juda ko'p urinish uchun kutish qo'ydi — "
                + _wait_text(flood_seconds(exc))
                + "\n(Tez-tez kod so'ramang: har urinish kutishni uzaytiradi.)")
    if "api_id" in low or "api id" in low:
        return "api_id/api_hash noto'g'ri. my.telegram.org dan qiymatlarni qayta oling."
    if "phone_number_banned" in low or "number banned" in low:
        return "Bu raqam Telegram tomonidan cheklangan."
    if "phone" in low and "invalid" in low:
        return "Telefon raqam noto'g'ri. +998... formatida yuboring."
    if "banned" in low:
        return "Bu raqam Telegramda bloklangan."
    if "expired" in low:
        return "Kod eskirgan."
    if "invalid" in low and "code" in low:
        return "Kod noto'g'ri."
    return text[:240]


_DELIVERY_TEXT = {
    "app": ("📲 Kod <b>Telegram ilovasiga</b> keldi (Telegram xizmatidan xabar).\n"
            "Telegram yangi api_id uchun ko'p hollarda SMS yubormaydi.\n"
            "Boshqa telefonda/kompyuterda Telegram ochiq bo'lsa — o'sha yerdagi "
            "<b>Telegram</b> chatidan kodni oling.\n"
            "SMS kerak bo'lsa: <b>sms</b> deb yozing."),
    "sms": "📩 Kod <b>SMS</b> orqali yuborildi.",
    "call": "📞 Kod <b>qo'ng'iroq</b> orqali aytiladi (qo'ng'iroqni qabul qiling).",
    "flash": "📞 Kod <b>qisqa qo'ng'iroq</b> orqali keladi.",
    "unknown": "📲 Kod yuborildi (Telegram ilovasi yoki SMS).",
}


def delivery_of(res) -> str:
    """SentCode.type dan kod qanday yuborilganini aniqlaydi."""
    tname = type(getattr(res, "type", None)).__name__.lower()
    if "app" in tname:
        return "app"
    if "call" in tname and "flash" in tname:
        return "flash"
    if "call" in tname:
        return "call"
    if "sms" in tname:
        return "sms"
    return "unknown"


def delivery_text(kind: str) -> str:
    return _DELIVERY_TEXT.get(kind or "unknown", _DELIVERY_TEXT["unknown"])


async def session_status() -> dict:
    """Saqlangan sessiya tirikmi? (Telegram uni bekor qilgan bo'lishi mumkin.)"""
    out = {"has_api": False, "has_session": False, "alive": False,
           "account": "", "channels": 0, "error": ""}
    try:
        api_id, api_hash, session = await credentials()
        out["has_api"] = bool(api_id and api_hash)
        out["has_session"] = bool(session)
        if not (api_id and api_hash and session):
            return out
        client = make_client(session, api_id, api_hash)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                out["error"] = "sessiya o'chgan (Telegram bekor qilgan)"
                return out
            me = await client.get_me()
            uname = getattr(me, "username", "") or ""
            phone = getattr(me, "phone", "") or ""
            out["alive"] = True
            out["account"] = f"@{uname}" if uname else (phone or str(getattr(me, "id", "")))
        finally:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass
        try:
            from app.services.channel_store import list_channels
            async with async_session_factory() as db:
                out["channels"] = len(await list_channels(db))
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"[:160]
    return out


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
            {"session": sess, "phone": _phone, "code_hash": _code_hash,
             "delivery": _delivery},
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
    global _pending, _phone, _code_hash, _delivery
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
        _delivery = str(row.get("delivery") or "")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.exception("[TG-USER] pending restore: %s", exc)
        return False


async def start_login(api_id: int, api_hash: str, phone: str,
                      force_sms: bool = False) -> tuple[str, str]:
    """Kod yuboriladi. (xato_matni, yetkazish_turi) qaytaradi."""
    global _pending, _phone, _code_hash, _delivery, _last_request_ts
    try:
        import telethon  # noqa: F401
    except ImportError:
        return "Telethon o'rnatilmagan. Deploy qiling.", ""
    await save_api(api_id, api_hash)
    phone = phone.strip()
    left = cooldown_left()
    if left > 0 and _phone == phone:
        return (f"⏳ Kod yaqinda so'ralgan. Yana {left} soniya kutib, "
                f"<b>qayta</b> deb yozing.", "")
    await _drop_client()
    try:
        client = make_client("", int(api_id), api_hash)
        await client.connect()
        if force_sms:
            try:
                result = await client.send_code_request(phone, force_sms=True)
            except TypeError:
                result = await client.send_code_request(phone)
        else:
            result = await client.send_code_request(phone)
        _pending = client
        _phone = phone
        _code_hash = result.phone_code_hash
        _delivery = delivery_of(result)
        _last_request_ts = time.time()
        kind = _delivery
        await _dump_pending()
        logger.info("[TG-USER] kod yuborildi: %s (yetkazish=%s, force_sms=%s)",
                    phone[-4:], kind, force_sms)
        return "", kind
    except Exception as exc:  # noqa: BLE001
        logger.exception("[TG-USER] login start: %s", exc)
        await _drop_client()
        return f"Kod yuborilmadi: {_human_err(exc)}", ""


COOLDOWN_SECONDS = 60


def _clear_cached_hash(client, phone: str) -> None:
    """Telethon keshidagi eski phone_code_hash ni o'chiradi.

    Keshda hash bo'lsa Telethon `send_code_request` ichida ResendCodeRequest
    yuboradi va Telegram uni "all available options ... already used" bilan
    rad etadi (yangi kod umuman kelmaydi). Kesh tozalansa keyingi so'rov
    HAQIQIY yangi kod so'rovi (SendCodeRequest) bo'ladi.
    """
    try:
        cache = getattr(client, "_phone_code_hash", None)
        if isinstance(cache, dict):
            cache.pop(phone, None)
    except Exception:  # noqa: BLE001
        pass


def cooldown_left() -> int:
    """Kod so'rashga qolgan "sovutish" vaqti (sekund)."""
    if not _last_request_ts:
        return 0
    left = COOLDOWN_SECONDS - int(time.time() - _last_request_ts)
    return left if left > 0 else 0


async def resend_code(force_sms: bool = False) -> tuple[str, str]:
    """Yangi kod so'raydi. (xato_matni, yetkazish_turi).

    force_sms: Telethon'da endi ishlamaydi (deprecated) — shuning uchun bu
    "qo'shimcha urinish" (ResendCodeRequest yo'li) sifatida ishlaydi.
    Xato bo'lsa ESKI kod hash saqlanadi — kelgan kod ishlayveradi.
    """
    global _code_hash, _delivery, _last_request_ts
    if not await _ensure_pending():
        return "Sessiya yo'q. /akkaunt bilan qayta boshlang.", ""
    left = cooldown_left()
    if left > 0:
        return (f"⏳ Juda tez. Yana {left} soniya kutib, <b>qayta</b> yozing.\n"
                "(Ketma-ket so'rov Telegramda cheklov qo'zg'atadi.)", "")
    old_hash, old_delivery = _code_hash, _delivery
    try:
        result = None
        if force_sms:
            # Telethon force_sms ni qo'llamaydi — to'g'ridan-to'g'ri ResendCodeRequest
            if _code_hash:
                try:
                    from telethon.tl.functions.auth import ResendCodeRequest
                    result = await _pending(ResendCodeRequest(_phone, _code_hash))
                    try:  # Telethon keshini ham yangilab qo'yamiz
                        _pending._phone_code_hash[_phone] = result.phone_code_hash
                    except Exception:  # noqa: BLE001
                        pass
                except Exception:  # noqa: BLE001
                    logger.info("[TG-USER] ResendCodeRequest ishlamadi — yangi so'rov")
                    result = None
        if result is None:
            try:
                result = await _pending.send_code_request(_phone)
            except Exception as exc:  # noqa: BLE001
                if not _code_hash and not getattr(_pending, "_phone_code_hash", None):
                    raise
                # Keshdagi eski hash sabab Telegram rad etdi — keshni tozalab,
                # HAQIQIY yangi kod so'rovi bilan oxirgi marta urinamiz.
                logger.info("[TG-USER] kesh tozalanib yangi so'rov: %s", exc)
                _clear_cached_hash(_pending, _phone)
                result = await _pending.send_code_request(_phone)
        _code_hash = result.phone_code_hash or _code_hash
        _delivery = delivery_of(result)
        _last_request_ts = time.time()
        await _dump_pending()
        logger.info("[TG-USER] kod qayta yuborildi (yetkazish=%s, urinish=%s)",
                    _delivery, "sms" if force_sms else "oddiy")
        return "", _delivery
    except Exception as exc:  # noqa: BLE001
        logger.exception("[TG-USER] resend: %s", exc)
        # eski kod hash tiklanadi — avval kelgan kod ishlayveradi
        _code_hash, _delivery = old_hash, old_delivery
        await _dump_pending()
        return f"Yangi kod kelmadi: {_human_err(exc)}", ""


async def pending_info() -> dict:
    """Kutilayotgan login: telefon, yetkazish turi, qolgan cooldown."""
    out = {"phone": "", "delivery": "", "cooldown": cooldown_left()}
    if await _ensure_pending():
        out["phone"] = _phone
        out["delivery"] = _delivery
        out["cooldown"] = cooldown_left()
        return out
    async with async_session_factory() as db:
        row = await load_json_log(db, PENDING_COMPONENT)
    out["phone"] = str(row.get("phone") or "")
    out["delivery"] = str(row.get("delivery") or "")
    return out


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
                # v51: o'zi qayta so'ramaydi (flood bo'lmasin) — foydalanuvchi "qayta" yozadi
                return "EXPIRED"
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
            return "EXPIRED"
        return f"Kirish xato: {_human_err(exc)}"
