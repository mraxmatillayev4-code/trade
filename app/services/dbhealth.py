"""v85: BAZA SOG'LIG'I (DB health) — xato spamini to'xtatadi va sababni aytadi.

Muammo (foydalanuvchi skrinshoti): 「TIZIM XATOSI — Component: Analysis Pipeline
Xato: EURUSDT 1m: [Errno -2] Name or service not known」 — har bir juftlik va har
bir timeframe uchun bir xil xato kelardi.

Sabab: `[Errno -2] Name or service not known` — bu DNS xatosi. Bot Telegramga
xabar yubora olayapti (demak internet bor), lekin BAZANING manzili topilmayapti.
Render bepul PostgreSQL 30 kundan keyin o'chiriladi — host nomi DNS dan
o'chadi va aynan shu xato chiqadi.

Nima qiladi:
  * baza xatosini ANIQLAYDI (DNS / ulanish / ruxsat / boshqa);
  * bir xil xatoni HAR SHAM uchun alohida yubormaydi — 15 daqiqada bir marta,
    nech marta takrorlanganini sanab, BITTA xabar yuboradi;
  * bazaning holatini har 60 sekundda tekshiradi: uzilsa — nima qilish
    kerakligini yozadi, qaytsa — «baza qaytdi» deb aytadi;
  * /kuzat va «Holat» kartasida baza holatini ko'rsatadi.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from app.core.logging import get_logger

logger = get_logger(__name__)

NOTIFY_EVERY_S = 900.0        # bir xil xato uchun eng kam oraliq (15 daqiqa)
PING_EVERY_S = 60.0           # baza holatini tekshirish oralig'i

_UP: bool | None = None       # None = hali tekshirilmagan
_SINCE: datetime | None = None
_LAST_MSG_AT = 0.0
_LAST_ERR = ""
_REPEAT = 0
_LAST_OK_AT: datetime | None = None
_SENT_UP = False


# ------------------------------------------------------------------ aniqlash
_CONN_HINTS = (
    "name or service not known",
    "temporary failure in name resolution",
    "nodename nor servname",
    "getaddrinfo",
    "connection refused",
    "connection reset",
    "connection was closed",
    "server closed the connection",
    "could not connect",
    "connect call failed",
    "timeout expired",
    "timeout",
    "too many connections",
    "the database system is starting up",
    "terminating connection",
    "asyncpg",
    "postgresql",
    "operationalerror",
    "interfaceerror",
    "invalidcatalognameerror",
    "unable to open database file",
    "no such file or directory",
)


def is_conn_error(exc) -> bool:
    """Xato bazaga/ulanishga tegishlimi (kod xatosi emas)?"""
    if exc is None:
        return False
    try:
        import socket
        if isinstance(exc, (socket.gaierror, ConnectionError, TimeoutError, OSError)):
            return True
    except Exception:  # noqa: BLE001
        pass
    name = type(exc).__name__.lower()
    if name in ("gaierror", "connecterror", "connecttimeout", "interfaceerror",
                "operationalerror", "invalidcatalognameerror", "pooltimeout",
                "connectionerror"):
        return True
    txt = f"{type(exc).__name__}: {exc}".lower()
    return any(h in txt for h in _CONN_HINTS)


def classify(exc) -> str:
    """Xatoning TUSHUNARLI sababi (qisqa)."""
    txt = f"{type(exc).__name__}: {exc}".lower()
    if ("name or service not known" in txt or "getaddrinfo" in txt
            or "name resolution" in txt or "nodename nor servname" in txt):
        return ("baza manzili topilmayapti (DNS). Render bepul baza 30 kundan "
                "keyin o'chadi — manzil DNS dan o'chib ketadi")
    if "connection refused" in txt or "could not connect" in txt:
        return "baza serverga ulanmadi (server o'chgan yoki port yopiq)"
    if "password" in txt or "authentication" in txt or "role" in txt:
        return "baza paroli/foydalanuvchisi mos emas (DATABASE_URL xato)"
    if "timeout" in txt or "timed out" in txt:
        return "baza javob bermadi (timeout — sekin yoki band)"
    if "too many connections" in txt:
        return "bazaga ulanishlar soni tugadi (bir oz kutish kerak)"
    return "baza bilan aloqa xatosi"


def db_host() -> str:
    """Baza manzili (parolsiz) — xabarda ko'rsatish uchun."""
    try:
        from app.core.config import get_settings
        url = str(getattr(get_settings(), "database_url_async", "")
                  or getattr(get_settings(), "database_url", ""))
        if "@" in url:
            tail = url.split("@", 1)[1]
            return tail.split("/", 1)[0]
        return url.split("://", 1)[-1][:60]
    except Exception:  # noqa: BLE001
        return "?"


def _is_sqlite() -> bool:
    try:
        from app.core.config import get_settings
        return "sqlite" in str(getattr(get_settings(), "database_url", "")).lower()
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------------ holat
def up() -> bool | None:
    return _UP


def since_text() -> str:
    if _SINCE is None:
        return ""
    try:
        mins = int((datetime.now(timezone.utc) - _SINCE).total_seconds() // 60)
    except Exception:  # noqa: BLE001
        return ""
    if mins < 60:
        return f"{mins} daqiqa"
    return f"{mins // 60} soat {mins % 60} daqiqa"


def status_line() -> str:
    """Karta/«Holat» uchun qisqa qator."""
    if _UP is True:
        return "\U0001F4BE Baza: <b>ishlayapti</b>"
    if _UP is False:
        return (f"\u26A0\uFE0F Baza: <b>ishlamayapti</b> ({since_text()}) \u2014 "
                f"{_LAST_ERR or 'aloqa xatosi'}")
    return "\U0001F4BE Baza: tekshirilmoqda..."


def status_plain() -> str:
    """HTML'siz qisqa holat (log yoki /health uchun)."""
    if _UP is True:
        return "ishlayapti"
    if _UP is False:
        return f"ishlamayapti ({_LAST_ERR or 'aloqa xatosi'})"
    return "tekshirilmoqda"


def pending_line() -> str:
    try:
        from app.services import offline
        n = offline.count()
    except Exception:  # noqa: BLE001
        n = 0
    if n:
        return (f"\U0001F4E5 Baza qaytishi bilan yoziladi: <b>{n}</b> ta xabar "
                f"navbatda")
    return ""


# ------------------------------------------------------------------ xabar
def _advice() -> str:
    return (
        "<b>Nima qilish kerak (5 daqiqa) \u2014 SUPABASE:</b>\n"
        "1) <b>supabase.com</b> \u2192 Sign in \u2192 <b>New project</b> "
        "(nom: sino-bot, parol: kuchli parol yozib QO'YING).\n"
        "2) Loyiha ochilgach yuqoridagi <b>Connect</b> tugmasi \u2192 "
        "<b>Connection pooling</b> / <b>Session pooler</b> qatorini nusxalang.\n"
        "3) Manzil shunday ko'rinadi: "
        "<code>postgresql://postgres.REF:PAROL@aws-0-REGION.pooler.supabase.com:5432/postgres</code>"
        "\n      \u26A0 Render IPv6 ni ko'rmaydi \u2014 SHUNING UCHUN "
        "<b>pooler</b> manzili kerak (db.REF.supabase.co EMAS, u ishlamaydi).\n"
        "      \u26A0 Port <b>5432</b> (session) bo'lsin; 6543 (transaction) "
        "bot uchun yaramaydi.\n"
        "4) Parolda <code>@ # %</code> kabi belgi bo'lsa, uni "
        "<code>%40 %23 %25</code> qilib yozing.\n"
        "5) Render \u2192 Trading bot xizmati \u2192 <b>Environment</b> \u2192 "
        "<code>DATABASE_URL</code> ni shu manzilga o'zgartiring \u2192 "
        "<b>Save</b> (Render o'zi qayta deploy qiladi, 3\u20136 daqiqa).\n"
        "6) Akkaunt/kanallar yo'qolmasin: botga <b>zaxira faylini</b> "
        "(<code>sino_zaxira.json</code>) yuboring \u2014 o'zi tiklaydi.\n"
        "<i>Baza ishlamaguncha kanallardan kelgan signallar navbatga yozib "
        "qo'yiladi va baza qaytishi bilan o'zi saqlanadi.</i>\n"
        "<i>Muqobil: neon.tech \u2014 u ham bepul va IPv4 manzil beradi.</i>"
    )


def advice() -> str:
    """Baza ishlamasa nima qilish kerak (ommaviy) + manzilga qarab aniq maslahat."""
    h = host_hint()
    return ((h + "\n") if h else "") + _advice()


async def send(notifier, text: str) -> None:
    if notifier is None:
        return
    try:
        await notifier.send_admin(text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[DBH] xabar yuborilmadi: %s", exc)


async def note_fail(exc, notifier=None, *, source: str = "") -> bool:
    """Baza xatosini qayd etadi. Xabar yuborilgan bo'lsa True."""
    global _UP, _SINCE, _LAST_MSG_AT, _LAST_ERR, _REPEAT, _SENT_UP
    why = classify(exc)
    _LAST_ERR = why
    _REPEAT += 1
    if _UP is not False:
        _UP = False
        _SINCE = datetime.now(timezone.utc)
        _LAST_MSG_AT = 0.0            # birinchi xabar darhol ketadi
    now = time.time()
    if notifier is not None and (now - _LAST_MSG_AT) >= NOTIFY_EVERY_S:
        _LAST_MSG_AT = now
        rep = f" (oxirgi 15 daqiqada <b>{_REPEAT}</b> marta)" if _REPEAT > 1 else ""
        _SENT_UP = False
        await send(notifier, (
            "\U0001F5C4 <b>BAZA BILAN ALOQA YO'Q</b>\n"
            "\u2500" * 16 + "\n"
            f"\U0001F517 Manzil: <code>{db_host()}</code>\n"
            f"\u2757 Sabab: {why}{rep}\n"
            f"{('Manba: ' + source) if source else ''}\n\n"
            + advice()))
        _REPEAT = 0
        return True
    logger.warning("[DBH] baza xatosi (%s): %s", why, exc)
    return False


async def note_ok(notifier=None) -> bool:
    """Baza ishlayapti. Qaytgan bo'lsa True (xabar yuborildi)."""
    global _UP, _SINCE, _LAST_MSG_AT, _REPEAT, _LAST_OK_AT, _SENT_UP, _LAST_ERR
    _LAST_OK_AT = datetime.now(timezone.utc)
    was_down = _UP is False
    _UP = True
    _SINCE = None
    _REPEAT = 0
    _LAST_ERR = ""
    if not was_down:
        return False
    if notifier is None or _SENT_UP:
        return False
    _SENT_UP = True
    _LAST_MSG_AT = time.time()
    # baza qaytdi — jadvallar/ustunlar joyidami, tekshirib tiklaymiz
    try:
        from app.database.session import init_db
        await init_db()
        logger.info("[DBH] sxema tekshirildi/tiklandi")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[DBH] sxema tiklanmadi: %s", exc)
    extra = pending_line()
    await send(notifier, (
        "\u2705 <b>BAZA QAYTDI</b> \u2014 bot normal ishlayapti.\n"
        + (extra + "\n" if extra else "")
        + "<i>Endi signallar o'z vaqtida saqlanadi va kuzatiladi.</i>"))
    return True


# ------------------------------------------------------------------ tekshiruv
async def ping() -> tuple[bool, str]:
    """Bazaga ulanishni sinaydi (SELECT 1)."""
    try:
        from sqlalchemy import text

        from app.database.session import engine
        async with engine.connect() as conn:
            await asyncio.wait_for(conn.execute(text("SELECT 1")), timeout=8.0)
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


async def check(notifier=None, *, source: str = "tekshiruv") -> bool:
    """Bir marta tekshiradi va holatni yangilaydi. True = baza ishlayapti."""
    ok, err = await ping()
    if ok:
        await note_ok(notifier)
        return True
    try:
        from app.services import offline
        offline.mark_down()
    except Exception:  # noqa: BLE001
        pass
    # v89: bu yerga faqat xato bilan kelinadi — shartsiz qayd etamiz
    await note_fail(err, notifier, source=source)
    return False


async def loop(notifier=None) -> None:
    """Har 60 sekundda baza holatini tekshiradi (fon vazifasi)."""
    await asyncio.sleep(10)
    while True:
        try:
            it_ok, err = await ping()
            if it_ok:
                await note_ok(notifier)
            else:
                await note_fail(err, notifier, source="davriy tekshiruv")
        except Exception as exc:  # noqa: BLE001
            logger.debug("[DBH] loop: %s", exc)
        await asyncio.sleep(PING_EVERY_S)

# ------------------------------------------------- v87: manzil diagnostikasi
def db_target() -> dict:
    """URL dan host/port/user ajratib oladi (parolsiz!)."""
    out = {"scheme": "", "host": "", "port": "", "user": "", "raw_ok": True}
    try:
        from app.core.config import get_settings
        st = get_settings()
        url = str(getattr(st, "database_url_async", "")
                  or getattr(st, "database_url", "") or "").strip()
    except Exception:  # noqa: BLE001
        return out
    if not url:
        return out
    try:
        head, rest = url.split("://", 1)
        out["scheme"] = head.replace("+asyncpg", "")
        if "@" in rest:
            cred, hostpart = rest.rsplit("@", 1)
            out["user"] = cred.split(":", 1)[0]
        else:
            hostpart = rest
        hostpart = hostpart.split("?", 1)[0]
        if "/" in hostpart:
            hostpart = hostpart.split("/", 1)[0]
        if ":" in hostpart:
            out["host"], out["port"] = hostpart.rsplit(":", 1)
        else:
            out["host"] = hostpart
    except Exception:  # noqa: BLE001
        out["raw_ok"] = False
    return out


def host_hint() -> str:
    """Aniq QADAM: manzildagi xato turi bo'yicha maslahat (bo'sh bo'lishi mumkin)."""
    try:
        from app.core.config import get_settings
        raw = str(getattr(get_settings(), "database_url", "") or "")
    except Exception:  # noqa: BLE001
        raw = ""
    url = raw.strip()
    low = url.lower()
    tips: list[str] = []
    if not url:
        return ("\u274C <code>DATABASE_URL</code> umuman o'rnatilmagan. Render \u2192 "
                "Environment \u2192 Add Environment Variable.")
    if raw != raw.strip() or url.startswith(("\"", "'")) or url.endswith(("\"", "'")):
        tips.append("Qiymatda <b>qo'shtirnoq</b> yoki <b>bo'sh joy</b> bor \u2014 "
                    "toza nusxa qo'ying.")
    if url.count("@") > 1:
        tips.append("Parolda <code>@</code> belgisi bor va kodlanmagan \u2014 "
                    "<code>%40</code> qilib yozing.")
    t = db_target()
    host, port = (t.get("host") or "").lower(), str(t.get("port") or "")
    if "render.com" in host or host.startswith("dpg-"):
        tips.append("Bu <b>Render'ning eski bepul bazasi</b> \u2014 u 30 kunda "
                    "o'chadi. Yangi baza (Supabase) manzilini qo'ying.")
    elif host.startswith("db.") and host.endswith(".supabase.co"):
        tips.append("Bu Supabase'ning <b>direct</b> manzili \u2014 u faqat IPv6, "
                    "Render ko'rmaydi. <b>Connect \u2192 Session pooler</b> "
                    "manzilini oling "
                    "(<code>...pooler.supabase.com:5432</code>).")
    elif host.endswith(".pooler.supabase.com") and port == "6543":
        tips.append("Port <b>6543</b> (transaction) \u2014 bot uchun yaramaydi. "
                    "Port <b>5432</b> (session pooler) kerak.")
    elif host.endswith(".pooler.supabase.com") and port == "5432":
        tips.append("Manzil to'g'ri ko'rinadi (session pooler). Agar shunday bo'lsa: "
                    "baza <b>pauza</b>da bo'lishi mumkin \u2014 Supabase "
                    "dashboard \u2192 <b>Restore project</b>.")
    elif "neon.tech" in host:
        tips.append("Neon manzili. Muammo bo'lsa: parol yoki <b>pooler</b> host "
                    "ishlatilganini tekshiring.")
    elif host in ("localhost", "127.0.0.1", "::1"):
        tips.append("Render serverida <code>localhost</code> baza YO'Q \u2014 "
                    "tashqi baza manzili kerak.")
    elif t.get("raw_ok") is False:
        tips.append("Manzil formati buzilgan: "
                    "<code>postgresql://user:parol@host:5432/postgres</code> "
                    "ko'rinishida bo'lsin.")
    if host and port and port not in ("5432", "6543", ""):
        tips.append(f"Port <b>{port}</b> g'alati \u2014 PostgreSQL uchun "
                    "odatda <b>5432</b>.")
    return ("\U0001F50E <b>Manzil bo'yicha aniq maslahat:</b>\n"
            + "\n".join(f"   \u2022 {x}" for x in tips) + "\n") if tips else ""


def target_line() -> str:
    """Log uchun: [DB] manzil (parolsiz)."""
    t = db_target()
    if not t.get("host"):
        return "[DB] manzil: (yo'q yoki o'qilmadi)"
    return (f"[DB] manzil: {t['host']}:{t.get('port') or '?'} "
            f"(user={t.get('user') or '?'}, {t.get('scheme') or '?'})")


async def safe_startup(notifier=None) -> bool:
    """Baza tayyorlash — XATO BO'LSA HAM KO'TARILMAYDI (bot/API ishlashda davom).

    v87: ilgari API server ishga tushishida `init_db()` xatosi butun jarayonni
    yiqitardi (Render: «Application startup failed» + port yo'q).
    """
    try:
        from app.database.session import init_db
        await init_db()
    except Exception as exc:  # noqa: BLE001
        if is_conn_error(exc):
            logger.error("%s | %s", target_line(), classify(exc))
            try:
                await note_fail(exc, notifier, source="ishga tushish")
            except Exception:  # noqa: BLE001
                pass
        else:
            logger.warning("[DB] init_db: %s: %s", type(exc).__name__, exc)
        return False
    try:
        from app.database.seed import seed_db
        from app.database.session import async_session_factory
        async with async_session_factory() as session:
            await seed_db(session)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[DB] seed: %s: %s", type(exc).__name__, exc)
    try:
        await note_ok(notifier)
    except Exception:  # noqa: BLE001
        pass
    return True
