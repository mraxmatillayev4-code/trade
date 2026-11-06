"""Tozalash (v57) — bot eski signallarni, statistikani va kanallar ro'yxatini UNUTADI.

Akkaunt ulanishi (tg_api / tg_session) SAQLANADI: QR yoki kod qaytadan kerak emas.
Tozalashdan keyin: signal raqamlash №1 dan boshlanadi; kanal qo'shilganda eski
tarix O'QILMAYDI — faqat YANGI kelgan xabarlar signal bo'ladi.
"""
from __future__ import annotations

from sqlalchemy import delete, func, select, text

from app.core.logging import get_logger
from app.database.models.paper import PaperAccount, PaperPosition
from app.database.models.signal import Signal, SignalConfirmation
from app.database.models.stats import StrategyStat
from app.database.models.system import SystemLog
from app.database.session import async_session_factory
from app.services.channel_store import (
    API_COMPONENT,
    COMPONENT,
    READ_COMPONENT,
    SESSION_COMPONENT,
)

logger = get_logger(__name__)

# Akkaunt ulanishi — tozalashda TEGILMAYDI
SAQLANADI = (SESSION_COMPONENT, API_COMPONENT)
SEQUENCES = (
    "signals_id_seq",
    "signal_confirmations_id_seq",
    "paper_positions_id_seq",
    "paper_accounts_id_seq",
)


async def _count(session, model) -> int:
    try:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)
    except Exception:  # noqa: BLE001
        return 0


async def _restart_sequences(session) -> None:
    """Postgres: id hisoblagichlarni 1 dan boshlash (№1 bo'lishi uchun)."""
    try:
        dialect = getattr(getattr(session.bind, "dialect", None), "name", "") or ""
    except Exception:  # noqa: BLE001
        dialect = ""
    if dialect != "postgresql":
        return
    for name in SEQUENCES:
        try:
            await session.execute(text(f"ALTER SEQUENCE IF EXISTS {name} RESTART WITH 1"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[TOZALASH] %s: %s", name, exc)


async def wipe_all(*, drop_channels: bool = True) -> dict:
    """Hammasini unutadi. Qaytaradi: {jadval: o'chirilgan qatorlar soni}."""
    res: dict = {}

    # 1) Virtual savdo + signallar (avval bog'langan jadvallar)
    async with async_session_factory() as session:
        for model, key in (
            (PaperPosition, "paper_positions"),
            (SignalConfirmation, "signal_confirmations"),
            (Signal, "signals"),
            (PaperAccount, "paper_accounts"),
        ):
            res[key] = await _count(session, model)
            await session.execute(delete(model))
        await session.commit()
        await _restart_sequences(session)
        await session.commit()

    # 2) Statistika (kanal statistikasi ch:@... ham shu yerda)
    async with async_session_factory() as session:
        res["statistika"] = await _count(session, StrategyStat)
        await session.execute(delete(StrategyStat))
        await session.commit()

    # 3) Kanallar ro'yxati + o'qish hisoblagichlari (akkaunt SAQLANADI)
    if drop_channels:
        async with async_session_factory() as session:
            q = select(SystemLog).where(
                SystemLog.component.in_((COMPONENT, READ_COMPONENT))
            )
            rows = list((await session.scalars(q)).all())
            res["kanal_yozuvi"] = len(rows)
            await session.execute(
                delete(SystemLog).where(
                    SystemLog.component.in_((COMPONENT, READ_COMPONENT))
                )
            )
            await session.commit()

    logger.warning("[TOZALASH] %s", res)
    return res


def report_text(res: dict) -> str:
    """Tozalash hisoboti (HTML)."""
    lines = [
        "\U0001F9F9 <b>TOZALANDI — bot toza holatda.</b>",
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
        f"\U0001F4CA signallar: <b>{int(res.get('signals') or 0)}</b> ta o'chirildi (raqamlash \u21161 dan boshlanadi)",
        f"\U0001F4CB tasdiqlar: {int(res.get('signal_confirmations') or 0)}",
        f"\U0001F4BC paper pozitsiya: {int(res.get('paper_positions') or 0)}, hisob: {int(res.get('paper_accounts') or 0)}",
        f"\U0001F4C8 statistika qatorlari: {int(res.get('statistika') or 0)} (kanal statistikasi ham)",
        f"\U0001F4E1 kanallar ro'yxati: <b>{int(res.get('kanal_yozuvi') or 0)}</b> yozuv tozalandi",
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
        "\u2705 Akkaunt ulanishi SAQLANDI (kuzatuvchi qayta ishga tushdi).",
        "\u27A1\uFE0F Endi kanallarni o'zingiz qo'shing: \U0001F4E1 Kanallar \u2192 \u2795 Qo'shish.",
        "\U0001F195 Eski (tarixiy) xabarlar O'QILMAYDI — faqat YANGI postlar signal bo'ladi.",
    ]
    return "\n".join(lines)
