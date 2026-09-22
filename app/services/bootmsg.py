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
        "\u2022 <b>Faqat HAQIQIY signallar</b> o'qiladi: matnda ANIQ narx "
        "(masalan 4394.37 yoki 4290-4295 zona) bo'lishi shart.",
        "\u2022 Signal EMAS: dars/kurs/vebinar postlari, tahlil-so'rov, rasm "
        "skrinshotlari, \u00ABbuy now\u00BB kabi darajasiz chaqiruvlar "
        "(narx yozilmagan), natija/maqtov postlari va kontekstdan olingan raqamlar.",
        "\u2022 SIGNAL kartasi QISQA; manba, lotlar va foyda hisobi \u00AB\u2753 Nega bu "
        "signal?\u00BB sahifasida.",
        "\u2022 Natija (WIN/LOSE) kartasi ham qisqa \u2014 to'liq tafsilot \u00AB\U0001F4D6 To'liq "
        "tafsilot\u00BB tugmasida.",
        "\u2022 RISK/MONEY MANAGEMENT: hajm balansning <b>0.5%</b> (yoki 1%/2%) riskidan "
        "hisoblanadi \u2014 /risk.",
        "\u2022 TP har doim AYNAN TP narxida, SL esa bozor narxida (gap bo'lsa) \u2014 "
        "brokerdagidek.",
        "\u2022 Eski/kechikkan signal (narx kirishdan uzoq) ochilmaydi \u2014 yolg'on "
        "natija yozilmasin.",
        "\u2022 Akkaunt va kanallar ZAXIRADA: /zaxira \u2014 zaxira fayli buyruq "
        "berilganda, startupda va <b>har 24 soatda shu chatga avtomatik</b> yuboriladi.",
        "\u2022 Baza almashib ketsa ham: faylni botga yuboring \u2014 akkaunt va kanallar "
        "o'zi tiklanadi (qayta ulash shart emas).",
        "\u2022 O'tgan signallar haqidagi maqtov/natija postlari SIGNAL EMAS.",
        "\u2022 Bozor kuzatuvi aniq: sham yetib kelmasa yoki narx to'xtasa \u2014 "
        "darhol ogohlantirish keladi.",
        "\u2022 <b>Lot 2</b>: +4R da qulf \u2014 momentum kuchli bo'lsa +5R, "
        "so'nsa +4R da yopiladi (foyda 4R dan past bo'lmaydi).",
        "\u2022 Zarar ham, FOYDA ham aniq ko'rsatiladi (dollar hisobida) "
        "(har lot: risk + maqsadga yetsa qancha).",
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
