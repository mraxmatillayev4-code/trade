"""v86: LOT HAJMI — FOYDALANUVCHI O'ZI BELGILAYDI (risk % olib tashlandi).

Eski holat (v82): hajm balansning 0.5%/1%/2% riskidan hisoblanardi.
Yangi holat (v86, foydalanuvchi talabi): **foiz YO'Q** — foydalanuvchi qancha
lotdan ochishni o'zi tanlaydi (masalan «0.01 dan»), bot esa shuni ochadi.

Muhim izoh: bot har signalda **2 ta lot** ochadi (Lot1 -> TP1, Lot2 -> TP2).
Shuning uchun tanlangan qiymat — **HAR BIR LOT** hajmi:
    0.01 tanlansa -> Lot 1 = 0.01 va Lot 2 = 0.01 (jami 0.02 lot).
Karta esa SL urilsa qancha pul ketishini ($ da) ko'rsatib turadi.

Saqlash joyi: `app_settings` jadvali (yangi jadval YO'Q):
    paper_lot        — umumiy standart (admin uchun)
    paper_lot:<uid>  — foydalanuvchi tanlovi (har kimga alohida)
"""
from __future__ import annotations

from app.core.logging import get_logger

logger = get_logger(__name__)

LOT_CHOICES: tuple[float, ...] = (0.01, 0.02, 0.03, 0.05, 0.10, 0.20, 0.50, 1.00)
DEFAULT_LOT = 0.01
CONTRACT_OZ = 100.0          # 1 lot XAUUSD = 100 untsiya
K_BASE = "paper_lot"

_CACHE: dict[str, float] = {}


def key_for(uid: int | None = None) -> str:
    return K_BASE if uid in (None, 0) else f"{K_BASE}:{int(uid)}"


def clean(lot) -> float:
    """Qiymatni ruxsat etilgan ro'yxatga keltiradi (0.01 .. 1.00)."""
    try:
        x = round(float(lot), 2)
    except (TypeError, ValueError):
        return DEFAULT_LOT
    if x <= 0:
        return DEFAULT_LOT
    for c in LOT_CHOICES:
        if abs(x - c) < 0.005:
            return c
    return min(1.00, max(0.01, x))


def default_lot() -> float:
    """Standart lot: 0.01 (v86). Config`dagi `default_lot` bo'lsa — o'sha."""
    try:
        from app.core.config import get_settings
        v = getattr(get_settings(), "default_lot", None)
        return clean(v) if v else DEFAULT_LOT
    except Exception:  # noqa: BLE001
        return DEFAULT_LOT


def cached(uid: int | None = None) -> float:
    """Sinxron kesh (karta yasashda ishlatiladi) — baza bo'lmasa ham ishlaydi."""
    k = key_for(uid)
    if k in _CACHE:
        return _CACHE[k]
    if uid not in (None, 0) and key_for(None) in _CACHE:
        return _CACHE[key_for(None)]
    return default_lot()


async def get(session, uid: int | None = None) -> float:
    """Foydalanuvchining lot hajmi (bazadan; bo'lmasa standart)."""
    k = key_for(uid)
    try:
        from sqlalchemy import select
        from app.database.models.app_setting import AppSetting
        row = await session.scalar(select(AppSetting).where(AppSetting.key == k))
        if row is None and uid not in (None, 0):
            row = await session.scalar(
                select(AppSetting).where(AppSetting.key == key_for(None))
            )
        if row is not None and (row.value or "").strip():
            v = clean(row.value)
            _CACHE[k] = v
            return v
    except Exception as exc:  # noqa: BLE001
        logger.debug("[LOT] o'qish: %s", exc)
    return cached(uid)


async def set_lot(session, uid: int | None, lot) -> float:
    """Lot hajmini saqlaydi (app_settings) va keshni yangilaydi."""
    v = clean(lot)
    k = key_for(uid)
    try:
        from sqlalchemy import select
        from app.database.models.app_setting import AppSetting
        row = await session.scalar(select(AppSetting).where(AppSetting.key == k))
        if row is None:
            row = AppSetting(key=k, value=str(v))
            session.add(row)
        else:
            row.value = str(v)
        await session.commit()
        _CACHE[k] = v
    except Exception as exc:  # noqa: BLE001
        logger.warning("[LOT] saqlash: %s", exc)
    return v


async def load_all(session) -> dict:
    """Barcha lot sozlamalarini keshga oladi (startupda)."""
    out: dict[str, float] = {}
    try:
        from sqlalchemy import select
        from app.database.models.app_setting import AppSetting
        rows = (await session.execute(
            select(AppSetting).where(AppSetting.key.like(f"{K_BASE}%"))
        )).scalars().all()
        for r in rows:
            try:
                _CACHE[r.key] = clean(r.value)
                out[r.key] = _CACHE[r.key]
            except Exception:  # noqa: BLE001
                continue
    except Exception as exc:  # noqa: BLE001
        logger.debug("[LOT] yuklash: %s", exc)
    return out


def risk_money(lot: float, entry: float, sl: float,
               contract: float = CONTRACT_OZ) -> float:
    """SL urilsa yo'qoladigan pul ($) — IKKI lot uchun jami."""
    try:
        d = abs(float(entry or 0) - float(sl or 0))
        l = clean(lot)
        return round(2.0 * l * contract * d, 2)
    except Exception:  # noqa: BLE001
        return 0.0


def per_lot_risk_money(lot: float, entry: float, sl: float,
                       contract: float = CONTRACT_OZ) -> float:
    """Bitta lot uchun risk ($)."""
    try:
        d = abs(float(entry or 0) - float(sl or 0))
        return round(clean(lot) * contract * d, 2)
    except Exception:  # noqa: BLE001
        return 0.0


def line(lot: float, entry: float = 0.0, sl: float = 0.0,
         balance: float | None = None, tp1: float = 0.0,
         tp2: float = 0.0, contract: float = CONTRACT_OZ) -> str:
    """Signal kartasi uchun lot qatori (foiz YO'Q — qo'lda tanlangan hajm)."""
    l = clean(lot)
    txt = (f"\U0001F4E6 <b>Hajm: {l:,.2f} + {l:,.2f} lot</b> "
           f"(jami {2 * l:,.2f} lot \u00B7 har bir lot {l:,.2f})")
    if balance:
        txt += f" \u00B7 hisob {float(balance):,.2f}$"
    r = risk_money(l, entry, sl, contract)
    if r > 0:
        txt += f"\n      \U0001F6D1 SL urilsa: <b>\u2212{r:,.2f}$</b> (2 lot jami)"
    for name, px in (("TP1", tp1), ("TP2", tp2)):
        try:
            p = float(px or 0)
            if p > 0 and float(entry or 0) > 0:
                prof = 2.0 * l * contract * abs(p - float(entry))
                txt += f" \u00B7 {name}da +{prof:,.2f}$"
        except Exception:  # noqa: BLE001
            continue
    return txt


def btn_label(lot: float) -> str:
    return f"\U0001F4E6 {clean(lot):,.2f} lot"
