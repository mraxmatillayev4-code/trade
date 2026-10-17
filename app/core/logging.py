"""Markazlashtirilgan logging sozlamasi."""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

# DIQQAT: import modul darajasida bo'lsin — to'xtash (shutdown) paytida
# funksiya ichidan import qilinsa "sys.meta_path is None" xatosi chiqadi.
try:
    from app.core.timeuz import to_tashkent as _to_tashkent
except Exception:  # noqa: BLE001
    _to_tashkent = None

_CONFIGURED = False

LOG_FORMAT = "%(asctime)s | [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class TashkentFormatter(logging.Formatter):
    """Log vaqtlari TOSHKENT (UTC+5) bo'yicha — Render loglarida ham."""

    def formatTime(self, record, datefmt=None):  # noqa: A003
        """Hech qachon xato bermaydi.

        v87: Python to'xtab qolayotganda (shutdown) import ishlamaydi va
        logging «sys.meta_path is None» xatosi bilan yiqilardi.
        """
        try:
            stamp = datetime.fromtimestamp(record.created, tz=timezone.utc)
            if _to_tashkent is not None:
                try:
                    stamp = _to_tashkent(stamp)
                except Exception:  # noqa: BLE001
                    pass
            return stamp.strftime(datefmt or DATE_FORMAT)
        except Exception:  # noqa: BLE001
            try:
                return datetime.now(timezone.utc).strftime(DATE_FORMAT)
            except Exception:  # noqa: BLE001
                return "0000-00-00 00:00:00"


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
    # v87: logging ichidagi xatolar jarayonni bezovta qilmasin (stderr shovqini yo'q)
    logging.raiseExceptions = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
