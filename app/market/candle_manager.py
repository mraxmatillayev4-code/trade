"""
CandleManager — xotiradagi shamlar keshi, WS/REST yangilanishlari, data quality.
- Faqat yopiq shamlar signal tahliliga yuboriladi.
- Duplicate / yetishmaydigan sham / noto'g'ri narx tekshiriladi.
"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd

from app.core.config import Settings
from app.core.enums import Timeframe
from app.core.logging import get_logger
from app.market.binance_rest import BinanceRest

logger = get_logger(__name__)


def _is_gold(symbol: str) -> bool:
    from app.market.gold_rest import needs_mexc
    return needs_mexc(symbol)


class CandleManager:
    def __init__(self, settings: Settings, rest: BinanceRest, gold_rest=None) -> None:
        self._settings = settings
        self._rest = rest
        self._gold = gold_rest  # MEXC klienti (oltin/Xau va boshqa MEXC juftliklari)
        self._cache: dict[tuple[str, str], pd.DataFrame] = {}
        # Qayta ishlashni oldini olish: (symbol, tf) -> oxirgi ishlangan open_time
        self._processed: dict[tuple[str, str], pd.Timestamp] = {}

    def _rest_for(self, symbol: str):
        """Oltin (XAU...) → MEXC klienti, qolganlari → Binance."""
        if _is_gold(symbol) and self._gold is not None:
            return self._gold
        return self._rest

    async def load_history(self) -> None:
        for symbol in self._settings.symbol_list:
            for tf in self._settings.watch_timeframe_list:
                try:
                    df = await self._rest_for(symbol).get_klines(
                        symbol, tf, self._settings.history_candles
                    )
                    # Oxirgi sham hali ochiq bo'lishi mumkin — tahlilda ishlatmaymiz
                    self._cache[(symbol, tf)] = df
                    gaps = self.find_gaps(df, tf)
                    if gaps:
                        logger.warning(
                            "[%s %s] %d ta yetishmagan sham aniqlandi", symbol, tf, len(gaps)
                        )
                    logger.info("[%s %s] %d ta tarixiy sham yuklandi", symbol, tf, len(df))
                except Exception as exc:  # noqa: BLE001
                    logger.error("[%s %s] tarix yuklanmadi: %s", symbol, tf, exc)

    def get_df(self, symbol: str, tf: str, include_open: bool = False) -> pd.DataFrame | None:
        df = self._cache.get((symbol.upper(), tf.lower()))
        if df is None or df.empty:
            return None
        out = df
        if not include_open:
            # Oxirgi sham ochiq bo'lishi mumkin — faqat yopiq shamlar
            expected = self._expected_open_time(tf)
            if df.iloc[-1]["open_time"] >= expected:
                out = df.iloc[:-1]
        out = out.copy()
        out.attrs["symbol"] = symbol.upper()
        out.attrs["timeframe"] = tf.lower()
        return out

    def get_closed_bars_count(self, symbol: str, tf: str) -> int:
        df = self.get_df(symbol, tf)
        return 0 if df is None else len(df)

    def update_from_ws(self, symbol: str, tf: str, kline: dict) -> pd.DataFrame | None:
        """WebSocket kline. Yangi yopiq sham bo'lsa DataFrame qaytaradi."""
        row = self._kline_to_row(kline)
        key = (symbol, tf)
        df = self._cache.get(key)
        if df is None:
            return None

        ot = row["open_time"]
        if (df["open_time"] == ot).any():
            idx = df.index[df["open_time"] == ot][0]
            for col in ("open", "high", "low", "close", "volume", "close_time"):
                df.loc[idx, col] = row[col]
        else:
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
            max_len = self._settings.history_candles + 50
            if len(df) > max_len:
                df = df.iloc[-max_len:].reset_index(drop=True)

        self._cache[key] = df
        is_closed = bool(kline.get("x", False))
        if is_closed and self._processed.get(key) != ot:
            self._processed[key] = ot
            closed = df[df["open_time"] <= ot].copy()
            closed.attrs["symbol"] = symbol
            closed.attrs["timeframe"] = tf
            return closed
        return None

    async def poll_closed_candle(self, symbol: str, tf: str) -> pd.DataFrame | None:
        """REST fallback: yangi yopiq sham bormi? (WebSocket ishlamasa)."""
        try:
            fresh = await self._rest_for(symbol).get_klines(symbol, tf, 3)
        except Exception:  # noqa: BLE001
            return None
        if fresh is None or fresh.empty:
            return None
        key = (symbol, tf)
        cached = self._cache.get(key)
        if cached is not None:
            merged = pd.concat([cached, fresh], ignore_index=True)
            merged = merged.drop_duplicates(subset=["open_time"], keep="last")
            merged = merged.sort_values("open_time").reset_index(drop=True)
            max_len = self._settings.history_candles + 50
            self._cache[key] = merged.iloc[-max_len:].reset_index(drop=True)
        else:
            self._cache[key] = fresh

        expected = self._expected_open_time(tf)
        df = self._cache[key]
        closed = df[df["open_time"] < expected]
        if closed.empty:
            return None
        last_closed_time = closed.iloc[-1]["open_time"]
        if self._processed.get(key) == last_closed_time:
            return None
        self._processed[key] = last_closed_time
        out = closed.copy()
        out.attrs["symbol"] = symbol
        out.attrs["timeframe"] = tf
        return out

    def mark_processed(self, symbol: str, tf: str, open_time: pd.Timestamp) -> None:
        self._processed[(symbol, tf)] = open_time

    # ---- yordamchilar ----
    @staticmethod
    def _kline_to_row(k: dict) -> dict:
        return {
            "open_time": pd.to_datetime(int(k["t"]), unit="ms", utc=True),
            "close_time": pd.to_datetime(int(k["T"]), unit="ms", utc=True),
            "open": float(k["o"]),
            "high": float(k["h"]),
            "low": float(k["l"]),
            "close": float(k["c"]),
            "volume": float(k["v"]),
        }

    @staticmethod
    def _expected_open_time(tf: str) -> pd.Timestamp:
        minutes = Timeframe(tf).minutes
        now = pd.Timestamp.utcnow().tz_localize(None) if False else pd.Timestamp.now(tz="UTC")
        floored = now.floor(f"{minutes}min")
        return pd.Timestamp(floored)

    @staticmethod
    def _norm_time(t) -> pd.Timestamp:
        ts = pd.Timestamp(t)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts

    @classmethod
    def find_gaps(cls, df: pd.DataFrame, tf: str) -> list[pd.Timestamp]:
        """Yetishmagan shamlarni tekshiradi."""
        if len(df) < 2:
            return []
        delta = timedelta(minutes=Timeframe(tf).minutes)
        times = [cls._norm_time(t) for t in df["open_time"].sort_values().tolist()]
        gaps: list[pd.Timestamp] = []
        for i in range(1, len(times)):
            if times[i] - times[i - 1] != delta:
                gaps.append(times[i])
        return gaps


def validate_candles(df: pd.DataFrame, tf: str, min_candles: int) -> tuple[bool, str]:
    """Data quality: yetarli uzunlik va narx. Bo'sh sham — OGOHLANTIRISH, blok emas."""
    need = min(int(min_candles or 50), 50)
    if df is None or len(df) < need:
        return False, f"Yetarli ma'lumot yo'q ({0 if df is None else len(df)} sham, {need} kerak)"

    prices = df[["open", "high", "low", "close"]]
    if (prices <= 0).any().any():
        return False, "Noto'g'ri narx (0 yoki manfiy) aniqlandi"

    if (df["high"] < df["low"]).any():
        return False, "high < low bo'lgan sham bor"

    # Bo'shliq / hajm — signalni O'LDIRMAYDI (AI o'zi qaror qiladi)
    return True, "OK"
