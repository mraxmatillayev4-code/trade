"""v75: /DB — butun bazani Supabase/Neon ga ko'chirish uchun SQL fayl qilib beradi.

Nega: Render'ning bepul PostgreSQL bazasi 30 kunda o'chadi. /DB bosilsa bot
bazani to'liq SQL dump qilib yuboradi — yangi (bepul, muddatsiz) bazaga
bir marta qo'yib tiklash kifoya.
"""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message

from app.core.access import is_admin

router = Router(name="dbadmin")

HOWTO = """\U0001F4BE <b>BAZANI KO'CHIRISH — 2 daqiqalik ish</b>

<b>1) Supabase (bepul, muddatsiz)</b>
  a) supabase.com \u2192 <i>New project</i> (parolni saqlab qo'ying)
  b) <i>SQL Editor</i> \u2192 <i>New query</i> \u2192 fayl ichidagi hammasini
     nusxalab qo'ying \u2192 <b>RUN</b>
  c) <i>Project Settings</i> \u2192 <i>Database</i> \u2192 <b>Connection string (URI)</b>
  d) Render \u2192 Environment \u2192 <code>DATABASE_URL</code> = shu URI \u2192 <b>Save</b>

<b>2) Neon (bepul, muddatsiz)</b>
  a) neon.tech \u2192 <i>New project</i> \u2192 connection string'ni nusxalang
  b) Kompyuterda: <code>psql "&lt;URL&gt;" -f sino_db_....sql</code>
  c) Render \u2192 Environment \u2192 <code>DATABASE_URL</code> ni yangilang \u2192 <b>Save</b>

\u26A0\uFE0F Faylda <b>barcha</b> ma'lumot bor (kanallar, signallar, statistika) —
hech kimga yubormang. Render'ga yozadigan URL'da parol bor: uni ham boshqalarga
ko'rsatmang.
\u2139\uFE0F <code>DATABASE_URL</code> ni o'zgartirsangiz Render o'zi qayta deploy qiladi
(3\u20136 daqiqa) — shundan keyin bot yangi bazada ishlaydi.
\u2139\uFE0F Yangi baza <b>bo'sh</b> bo'ladi, shuning uchun bu fayl hammasini qaytaradi:
kanallar, signallar, paper hisob, tarix."""


@router.message(Command("db", ignore_case=True))
async def cmd_db(message: Message) -> None:
    """\U0001F4BE /DB — bazani SQL dump qilib yuboradi (faqat admin)."""
    uid = getattr(message.from_user, "id", None)
    if not is_admin(uid):
        await message.answer("\U0001F4BE /DB — bazani yuklab olish faqat admin uchun.")
        return

    note = await message.answer("\U0001F4BE Baza o'qilmoqda, fayl tayyorlanmoqda\u2026")
    from app.services import dbdump

    try:
        name, data, st = await dbdump.build()
    except Exception as exc:  # noqa: BLE001
        try:
            await note.edit_text(f"\u274C Dump qilinmadi: <code>{exc}</code>",
                                 parse_mode="HTML")
        except Exception:  # noqa: BLE001
            await message.answer(f"\u274C Dump qilinmadi: <code>{exc}</code>",
                                 parse_mode="HTML")
        return

    kb = len(data) / 1024.0
    size = f"{kb / 1024:.1f} MB" if kb > 1024 else f"{kb:.0f} KB"
    per = st.get("per_table") or {}
    top = sorted(per.items(), key=lambda kv: -kv[1])[:6]
    lines = [
        "\U0001F4BE <b>BAZA DUMPI TAYYOR</b>",
        f"Jadvallar: <b>{st.get('tables')}</b> \u00B7 Yozuvlar: <b>{st.get('rows')}</b> \u00B7 Hajm: <b>{size}</b>",
    ]
    if top:
        lines.append("Eng katta jadvallar: " +
                     ", ".join(f"{n} ({c})" for n, c in top))
    if name.endswith(".gz"):
        lines.append("\u2139\uFE0F Fayl katta bo'lgani uchun <code>.gz</code> qilib yuborildi "
                     "(Supabase'ga qo'yishdan oldin ochib oling).")
    try:
        await note.edit_text("\n".join(lines), parse_mode="HTML")
    except Exception:  # noqa: BLE001
        await message.answer("\n".join(lines), parse_mode="HTML")

    await message.answer_document(
        BufferedInputFile(data, filename=name),
        caption="\U0001F4BE <b>SINO AI baza dumpi</b>\nSupabase SQL Editor'iga yoki "
                "Neon'ga <code>psql -f</code> bilan tiklanadi.",
        parse_mode="HTML",
    )
    await message.answer(HOWTO, parse_mode="HTML")
