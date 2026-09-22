"""v82: `/zaxira` — akkaunt va kanallar zaxirasi (qayta ulash shart bo'lmasin).

* `/zaxira` — sessiya + kanallar ro'yxatini JSON fayl qilib beradi.
* Zaxira faylini botga yuborsangiz — hammasi avtomatik tiklanadi.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message

from app.core.access import is_admin
from app.core.logging import get_logger
from app.services import persist

router = Router(name="persist")
logger = get_logger(__name__)


@router.message(Command("zaxira"))
async def cmd_backup(message: Message) -> None:
    if message.from_user and not is_admin(message.from_user.id):
        return
    snap = await persist.snapshot()
    name, data = await persist.backup_file()
    ch = len(snap.get("channels") or [])
    _acc = "\u2705 akkaunt bor" if snap.get("session") else "\u274c akkaunt yo'q"
    try:
        await message.answer_document(
            BufferedInputFile(data, filename=name),
            caption=(
                "🛡 <b>ZAXIRA (akkaunt + kanallar)</b>\n"
                f"👤 {_acc} · 📡 Kanallar: <b>{ch}</b> ta\n"
                f"📁 Fayl: <code>{name}</code>\n\n"
                "<b>Bu faylni SAQLAB QO'YING.</b> Yangilanishdan keyin akkaunt yoki "
                "kanallar yo'qolsa — shu faylni botga yuboring, hammasi qaytadi.\n"
                "<i>Zaxira endi har 24 soatda shu chatga avtomatik yuboriladi.</i>"
            ),
            parse_mode="HTML",
        )
        if not (snap.get("session") or snap.get("channels")):
            warn = await persist.warn_if_empty(None)
            if warn:
                await message.answer(warn, parse_mode="HTML")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PERSIST] /zaxira: %s", exc)
        await message.answer(f"❌ Zaxira yuborilmadi: {type(exc).__name__}")


@router.message(F.document)
async def restore_document(message: Message) -> None:
    """Zaxira fayli yuborilsa — tiklaymiz."""
    if message.from_user and not is_admin(message.from_user.id):
        return
    doc = message.document
    name = str(getattr(doc, "file_name", "") or "").lower()
    if not name.endswith(".json"):
        return
    if "zaxira" not in name and "sino" not in name:
        return
    try:
        buf = await message.bot.download(doc)
        raw = buf.read() if buf else b""
    except Exception as exc:  # noqa: BLE001
        await message.answer(f"❌ Fayl yuklanmadi: {type(exc).__name__}")
        return
    res = await persist.restore_from_file(raw)
    await message.answer(res, parse_mode="HTML")
    try:
        from app.services import channel_watcher
        await channel_watcher.restart_watcher()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PERSIST] watcher qayta ishga tushmadi: %s", exc)
