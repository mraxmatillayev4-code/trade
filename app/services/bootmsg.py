"""v76: «SINO AI tayyor» xabari — TO'G'RI versiya bilan va FAQAT BIR MARTA.

Muammo (foydalanuvchi shikoyati): har restart/deploy da eski «tayyor (v72)»
xabari qayta-qayta kelardi. Yechim:
  * matn endi local_ai.__version__ dan olinadi — hech qachon eskirib qolmaydi;
  * har bir versiya uchun FAQAT BIR MARTA yuboriladi (bazada eslab qolinadi).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select

from app.database.models.system import SystemLog

COMPONENT = "boot"


def version() -> str:
    """Masalan: 'SINO-LAI-76'."""
    from app.services import local_ai
    return str(getattr(local_ai, "__version__", "SINO-LAI-?"))


def label() -> str:
    """'SINO-LAI-76' -> 'v76'. Raqam bo'lmasa — versiyaning o'zi."""
    ver = version()
    tail = ver.rsplit("-", 1)[-1]
    return f"v{tail}" if tail.isdigit() else ver


def build_text(cmds: list[str] | None = None) -> str:
    """Tayyor xabari: qisqa, faqat amaldagi imkoniyatlar (v76 kontrakti)."""
    lines = [
        f"\u2705 <b>SINO AI tayyor ({label()})</b>",
        "\u2022 \U0001F50E <b>Jonli kuzatuv</b> \u2014 pastdagi asosiy tugma: "
        "lotlarni qo'lda yopish ham shu yerda.",
        "\u2022 \U0001F3E6 <b>Broker</b>: /broker \u2014 MT5 (avval DEMO, keyin REAL).",
        "\u2022 \U0001F4BE <b>Baza</b>: /DB \u2014 SQL fayl (Supabase/Neon) + "
        "har 48 soatda avto-zaxira (23:00).",
        "\u2022 \U0001F5D1 <b>Kanal o'chirish</b> \u2014 bir bosishda o'chadi "
        "(\u21A9\uFE0F Qaytarish bor).",
        "\u2022 Faqat SIGNALLAR o'qiladi: grafik/terminal skrinshotlari signal emas "
        "\u2014 matnda to'liq reja (yo'nalish + SL/TP) bo'lishi kerak.",
        "\u2022 Bir xil xabar takror ishlanmaydi (xabar xotirasi).",
    ]
    if cmds:
        lines.append(f"Commandlar ({len(cmds)} ta): " + " ".join("/" + c for c in cmds))
    return "\n".join(lines)


async def last_version(session) -> str | None:
    """Oxirgi e'lon qilingan versiya (bazadan)."""
    res = await session.execute(
        select(SystemLog).where(SystemLog.component == COMPONENT)
        .order_by(SystemLog.id.desc()).limit(1)
    )
    row = res.scalars().first()
    if row is None:
        return None
    try:
        return (json.loads(row.message or "") or {}).get("version")
    except Exception:  # noqa: BLE001
        return (row.message or "").strip() or None


async def should_announce(session, ver: str | None = None) -> bool:
    """Shu versiya hali e'lon qilinmaganmi? (bir marta yuborish qoidasi)"""
    return (await last_version(session)) != (ver or version())


async def mark(session, ver: str | None = None) -> None:
    """E'lon qilingan versiyani yozib qo'yamiz."""
    ver = ver or version()
    session.add(SystemLog(
        level="INFO", component=COMPONENT,
        message=json.dumps({"version": ver,
                            "at": datetime.now(timezone.utc).isoformat()},
                           ensure_ascii=False),
    ))
    await session.commit()
