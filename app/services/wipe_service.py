"""v128: Baza va xotirani tozalash xizmati.

Kanal va Telegram akkaunt SAQLANIB QOLADI.
Barcha eski signallar, ochiq/yopiq savdolar, tarix va keshlar tozalanadi.
"""
from __future__ import annotations

import os
from sqlalchemy import text
from app.database.session import async_session_factory
from app.core.logging import get_logger

logger = get_logger(__name__)


async def wipe_trades_and_history() -> dict:
    """Kanal va akkauntdan BOSHQA barcha narsalarni tozalaydi."""
    stats = {}
    async with async_session_factory() as session:
        # 1. Eski bog'liq jadvallar
        res = await session.execute(text("DELETE FROM signal_confirmations;"))
        stats["signal_confirmations"] = res.rowcount if hasattr(res, "rowcount") else 0

        res = await session.execute(text("DELETE FROM paper_positions;"))
        stats["paper_positions"] = res.rowcount if hasattr(res, "rowcount") else 0

        res = await session.execute(text("DELETE FROM user_deliveries;"))
        stats["user_deliveries"] = res.rowcount if hasattr(res, "rowcount") else 0

        res = await session.execute(text("DELETE FROM signals;"))
        stats["signals"] = res.rowcount if hasattr(res, "rowcount") else 0

        res = await session.execute(text("DELETE FROM backtests;"))
        stats["backtests"] = res.rowcount if hasattr(res, "rowcount") else 0

        res = await session.execute(text("DELETE FROM candles;"))
        stats["candles"] = res.rowcount if hasattr(res, "rowcount") else 0

        res = await session.execute(text("DELETE FROM strategy_statistics;"))
        stats["strategy_statistics"] = res.rowcount if hasattr(res, "rowcount") else 0

        # System logs: faqat channels va tg_* saqlanadi
        res = await session.execute(
            text("DELETE FROM system_logs WHERE component NOT IN ('channels', 'tg_session', 'tg_api', 'tg_auth');")
        )
        stats["system_logs"] = res.rowcount if hasattr(res, "rowcount") else 0

        # Paper accountni tozalash: foydalanuvchi belgilagan boshlang'ich balansga qaytarish
        await session.execute(text("""
            UPDATE paper_accounts 
            SET balance = initial_balance, total_realized_pnl = 0.0, 
                total_trades = 0, total_wins = 0, consecutive_losses = 0, 
                paused_by_circuit = FALSE, auto_trade_enabled = TRUE
            WHERE user_id > 0;
        """))
        await session.execute(text("""
            UPDATE paper_accounts 
            SET balance = 0.0, initial_balance = 0.0, total_realized_pnl = 0.0, 
                total_trades = 0, total_wins = 0, consecutive_losses = 0, 
                paused_by_circuit = FALSE, auto_trade_enabled = FALSE
            WHERE user_id <= 0;
        """))

        await session.commit()

    # Xotiradagi kesh va jsonl fayllarni tozalash
    try:
        from app.services import channel_inbox
        channel_inbox._seen.clear()
    except Exception:  # noqa: BLE001
        pass

    try:
        from app.services import channel_context
        channel_context._STORE.clear()
    except Exception:  # noqa: BLE001
        pass

    try:
        from app.services import channel_stats
        p = getattr(channel_stats, "DATA_PATH", "data/chan_stats.jsonl")
        if os.path.exists(p):
            with open(p, "w", encoding="utf-8") as f:
                f.write("")
    except Exception:  # noqa: BLE001
        pass

    logger.info("[WIPE] Tozalash yakunlandi: %s", stats)
    return stats
