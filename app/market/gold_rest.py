"""MEXC Fyuchers REST klienti — haqiqiy OLTIN (XAU_USDT) va boshqa MEXC juftliklari.

Binance'da XAUUSD yo'q. MEXC va Gate'da XAU_USDT PERPETUAL mavjud — bu token emas,
haqiqiy oltin indeksi narziga bog'langan fyuchers (narxi oltin spot bilan bir xil yuradi).

BinanceRest bilan BIR XIL interfeys: get_klines / get_ticker_24h / get_last_price.
Qaytariladigan DataFrame ustunlari Binance bilan mos:
open_time, open, high, low, close, volume, close_time.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pandas as pd

from app.core.logging import get_logger

logger = get_logger(__name__)

# Bot timeframe → MEXC interval
TF_TO_MEXC = {
    "1m": "Min1", "3m": "Min3", "5m": "Min5", "15m": "Min15",
    "30m": "Min30", "1h": "Min60", "2h": "Hour2", "4h": "Hour4",
    "6h": "Hour6", "8h": "Hour8", "12h": "Hour12",
    "1d": "Day1", "1w": "Week1", "1M": "Month1",
}

BASE = "https://contract.mexc.com"

# MEXC'da olinadigan (Binance'da yo'q) instrumentlar: oltin va forex
MEXC_SYMBOLS = ("XAU", "SILVER", "USOIL", "UKOIL", "NGAS", "COPPER", "EUR", "JPY", "GBP", "AUD")


def needs_mexc(symbol: str) -> bool:
    s = symbol.upper()
    return any(s.startswith(p) for p in MEXC_SYMBOLS)


def to_mexc_symbol(symbol: str) -> str:
    """XAUUSDT → XAU_USDT."""
    s = symbol.upper()
    for quote in ("USDT", "USDC", "BUSD"):
        if s.endswith(quote) and len(s) > len(quote):
            return f"{s[:-len(quote)]}_{quote}"
    return s


def _invert_series(df: pd.DataFrame) -> pd.DataFrame:
    """JPY_USDT (=JPY per USD) → USD/JPY: narxni 1/p ga o'giradi, high/low almashadi."""
    if df is None or df.empty:
        return df
    out = df.copy()
    inv_o = 1.0 / df["open"]
    inv_c = 1.0 / df["close"]
    inv_hi = 1.0 / df["low"]    # eng past narx → teskari eng yuqori
    inv_lo = 1.0 / df["high"]   # eng yuqori narx → teskari eng past
    out["open"], out["close"] = inv_o, inv_c
    out["high"], out["low"] = inv_hi, inv_lo
    return out


class GoldRest:
    """MEXC fyuchers ma'lumotlari (oltin uchun asosiy manba)."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=10.0))

    async def close(self) -> None:
        await self._client.aclose()

    async def get_klines(self, symbol: str, timeframe: str,
                         limit: int = 500) -> pd.DataFrame:
        mx = to_mexc_symbol(symbol)
        interval = TF_TO_MEXC.get(timeframe.lower(), "Min5")
        try:
            r = await self._client.get(
                f"{BASE}/api/v1/contract/kline/{mx}",
                params={"interval": interval},
            )
            r.raise_for_status()
            payload = r.json()
        except Exception as exc:  # noqa: BLE001
            logger.error("[GOLD] MEXC kline olinmadi %s %s: %s", symbol, timeframe, exc)
            return pd.DataFrame()

        data = payload.get("data") if isinstance(payload, dict) else None
        if not data or not data.get("time"):
            logger.warning("[GOLD] MEXC kline bo'sh: %s %s", symbol, timeframe)
            return pd.DataFrame()

        times = data["time"]
        opens = data.get("open", [])
        closes = data.get("close", [])
        highs = data.get("high", [])
        lows = data.get("low", [])
        vols = data.get("vol", data.get("amount", []))
        # interval sekundlari (oxirgi ikki sham orasidan)
        step = int(times[-1] - times[-2]) if len(times) >= 2 else 300

        rows = []
        now_sec = datetime.now(tz=timezone.utc).timestamp()
        for i in range(len(times)):
            ot = int(times[i])
            ct = ot + step
            # Faqat YOPIQ shamlar (hali yopilmagani chiqarib tashlanadi)
            if ct > now_sec:
                continue
            rows.append({
                "open_time": datetime.fromtimestamp(ot, tz=timezone.utc),
                "open": float(opens[i]),
                "high": float(highs[i]),
                "low": float(lows[i]),
                "close": float(closes[i]),
                "volume": float(vols[i]) if i < len(vols) else 0.0,
                "close_time": datetime.fromtimestamp(ct, tz=timezone.utc),
            })

        rows = rows[-limit:]
        df = pd.DataFrame(rows)
        # JPY_USDT (Yen per USD) → USD/JPY (dollar per yen) inversiya
        if symbol.upper().startswith("JPY"):
            df = _invert_series(df)
        df.attrs["symbol"] = symbol.upper()
        df.attrs["timeframe"] = timeframe
        if not df.empty:
            logger.info("[GOLD] %s %s: %d ta yopiq sham (MEXC)", symbol, timeframe, len(df))
        return df

    async def get_ticker_24h(self, symbol: str) -> dict:
        mx = to_mexc_symbol(symbol)
        try:
            r = await self._client.get(
                f"{BASE}/api/v1/contract/ticker", params={"symbol": mx}
            )
            r.raise_for_status()
            d = r.json().get("data", {})
            return {
                "symbol": symbol.upper(),
                "price": float(d.get("lastPrice", 0.0)),
                "price_change_pct": float(d.get("riseFallRate", 0.0)) * 100.0,
                "high_24h": float(d.get("high24Price", 0.0)),
                "low_24h": float(d.get("lower24Price", 0.0)),
                "volume": float(d.get("volume24", 0.0)),
                "quote_volume": float(d.get("amount24", 0.0)),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("[GOLD] ticker olinmadi %s: %s", symbol, exc)
            return {}

    async def get_last_price(self, symbol: str) -> float | None:
        t = await self.get_ticker_24h(symbol)
        return t.get("price") or None
