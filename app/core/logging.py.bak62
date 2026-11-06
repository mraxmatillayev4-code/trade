"""Markazlashtirilgan logging sozlamasi."""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

_CONFIGURED = False

LOG_FORMAT = "%(asctime)s | [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class TashkentFormatter(logging.Formatter):
    """Log vaqtlari TOSHKENT (UTC+5) bo'yicha — Render loglarida ham."""

    def formatTime(self, record, datefmt=None):  # noqa: A003
        from app.core.timeuz import to_tashkent
        return to_tashkent(
            datetime.fromtimestamp(record.created, tz=timezone.utc)
        ).strftime(datefmt or DATE_FORMAT)


def setup_logging(level: str = "INFO") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(TashkentFormatter(LOG_FORMAT, DATE_FORMAT))
    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()
    root.addHandler(handler)

    # Tashqi kutubxonalarning shovqinini kamaytirish
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
