"""Binance REST API klienti — tarixiy shamlar, ticker, fallback mirrorlar bilan."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pandas as pd

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Geo-cheklovlarda avtomatik almashinadigan ommaviy endpointlar
FALLBACK_BASES = [
    "https://api.binance.com",
    "https://data-api.binance.vision",
    "https://api.binance.us",
]


class BinanceRest:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # .env da berilgan baza birinchi navbatda
        self._bases = [settings.binance_base_url.rstrip("/")]
        for b in FALLBACK_BASES:
            if b not in self._bases:
                self._bases.append(b)
        self._working_base: str | None = None
        headers = {}
        if settings.binance_api_key:
            headers["X-MBX-APIKEY"] = settings.binance_api_key
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=10.0),
            headers=headers,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict) -> httpx.Response:
        bases = [self._working_base] if self._working_base else self._bases
        last_exc: Exception | None = None
        for base in bases:
            try:
                resp = await self._client.get(f"{base}{path}", params=params)
                if resp.status_code in (451, 403, 418, 429, 500, 502, 503):
                    logger.warning("[REST] %s → %s, keyingi endpoint sinanadi", base, resp.status_code)
                    last_exc = httpx.HTTPStatusError(
                        str(resp.status_code), request=resp.request, response=resp
                    )
                    continue
                resp.raise_for_status()
                if self._working_base != base:
                    self._working_base = base
                    logger.info("[REST] ishchi endpoint: %s", base)
                return resp
            except httpx.HTTPError as exc:
                last_exc = exc
                continue
        raise last_exc or RuntimeError("Barcha Binance endpointlari ishlamadi")

    async def get_klines(self, symbol: str, timeframe: str,
                         limit: int = 500) -> pd.DataFrame:
        """Binance klines → DataFrame (faqat yopiq shamlar qaytariladi)."""
        resp = await self._get(
            "/api/v3/klines",
            {"symbol": symbol.upper(), "interval": timeframe, "limit": limit},
        )
        rows = []
        for k in resp.json():
            rows.append(
                {
                    "open_time": datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc),
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                    "taker_buy_volume": float(k[9]),
                    "close_time": datetime.fromtimestamp(k[6] / 1000, tz=timezone.utc),
                }
            )
        df = pd.DataFrame(rows)
        df.attrs["symbol"] = symbol.upper()
        df.attrs["timeframe"] = timeframe
        return df

    async def get_ticker_24h(self, symbol: str) -> dict:
        resp = await self._get("/api/v3/ticker/24hr", {"symbol": symbol.upper()})
        d = resp.json()
        return {
            "symbol": d["symbol"],
            "price": float(d["lastPrice"]),
            "price_change_pct": float(d["priceChangePercent"]),
            "high_24h": float(d["highPrice"]),
            "low_24h": float(d["lowPrice"]),
            "volume": float(d["volume"]),
            "quote_volume": float(d["quoteVolume"]),
        }

    async def get_last_price(self, symbol: str) -> float | None:
        try:
            resp = await self._get("/api/v3/ticker/price", {"symbol": symbol.upper()})
            return float(resp.json()["price"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("[REST] narx olinmadi %s: %s", symbol, exc)
            return None
