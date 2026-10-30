# -*- coding: utf-8 -*-
"""v125: OLTIN BOZORI ISH VAQTI — yopiq paytda Kanal signali BLOKLANADI.

Mantiqi (XAUUSD spot, xalqaro bozor):
  • Haftalik DVERI: juma kechasi ~17:00 Nyu-Yorkdan yakshanba ~18:00 NY gacha
    bozor YOPIQ (Toshkentda: shanba ~02:00 → dushanba ~03:00/04:00).
  • Kunlik TANAAFFUS: har ish kuni NY 17:00-18:00 (Toshkent 02:00-03:00 EDT
    mavsumida; 03:00-04:00 EST mavsumida) bozor dam oladi.

Nima uchun kerak: foydalanuvchi bozor yopiq payt (shanba/yakshanba) test maqsadida
eski signallarni forward qilganda bot kartasini chiqarib, 60 daqiqa "kutishga"
qo'ymasligi kerak — signal "KUN BOYI" yozilgan darajalar bilan emas, shu paytning
jonli narxi bilan ishlashi shart. Yopiq paytdagi signal KARTasiz bloklanadi.

Qaytaradi: (ochiqmi: bool, izoh: str) — izoh faqat yopiq sababining tasviri.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

TZ_TASHKENT = timezone(timedelta(hours=5))


def _nth_sunday(year: int, month: int, n: int) -> datetime:
    """Oyning n-chi yakshanba kuni (AQSH DST uchun) — Toshkent jadvalida."""
    d = datetime(year, month, 1)
    while d.weekday() != 6:           # 6 = yakshanba
        d += timedelta(days=1)
    d += timedelta(days=7 * (n - 1))
    return d


def _us_dst(now_tashkent: datetime) -> bool:
    """AQSH yozgi vaqti (EDT): mart 2-yakshanba − noyabr 1-yakshanba."""
    y = now_tashkent.year
    start = _nth_sunday(y, 3, 2)      # mart, 2-yakshanba
    end = _nth_sunday(y, 11, 1)       # noyabr, 1-yakshanba
    day = datetime(y, now_tashkent.month, now_tashkent.day)  # sana (tzsiz)
    return start <= day < end


def gold_market_open(now: datetime | None = None) -> tuple[bool, str]:
    """(ochiqmi, izoh). `now` — Toshkent vaqtidigi; None bo'lsa hozir."""
    if now is None:
        now = datetime.now(TZ_TASHKENT)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=TZ_TASHKENT)
    else:
        now = now.astimezone(TZ_TASHKENT)

    wd = now.weekday()                # 0=Dushanba ... 6=Yakshanba
    t = now.time()
    dst = _us_dst(now)

    # --- haftalik dveri (xavfsiz: EDT/EST farqini yopishtiramiz) ---
    # yakshanba — butun kun YOPIQ
    if wd == 6:
        return False, "yakshanba — bozor butun kun yopiq"
    # shanba 02:00 dan keyin YOPIQ (juma 17:00 EDT = 21:00 UTC = shanba 02:00 Toshkent;
    # EST da esa 03:00 — ikkalasi uchun ham xavfsiz tekis chiziq)
    if wd == 5 and t >= datetime.strptime("02:00", "%H:%M").time():
        return False, "juma kechasi bozor yopilgan — dushanba tongda ochiladi"
    # dushanba tong: EDTda 03:00 da ochiladi, EST da 04:00 — xavfsiz chiziq: 04:00
    if wd == 0 and t < datetime.strptime("04:00", "%H:%M").time():
        return False, "dushanba tongi — bozor hali ochilmagan (≈ 03:00-04:00)"

    # --- kunlik tanaaffus (NY 17:00-18:00) ---
    if dst:
        tana_bosh = datetime.strptime("02:00", "%H:%M").time()
        tana_oxir = datetime.strptime("03:00", "%H:%M").time()
    else:
        tana_bosh = datetime.strptime("03:00", "%H:%M").time()
        tana_oxir = datetime.strptime("04:00", "%H:%M").time()
    if tana_bosh <= t < tana_oxir and wd not in (5, 6):
        return False, "kunlik tanaaffus (02:00-03:00 Toshkent) — bozor dam olmoqda"

    return True, ""
