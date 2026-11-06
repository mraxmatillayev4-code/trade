"""
Binance WebSocket klienti — real vaqt kline oqimi.
- Avtomatik reconnect (eksponensial backoff)
- Faqat yopilgan sham (k.x = True) hodisasini callback'ga uzatadi
- Uzilishlarda log va admin ogohlantirishi
"""
from __future__ import annotations

import asyncio
import json
from typing import Awaitable, Callable

import aiohttp

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)

OnClosedCandle = Callable[[str, str, dict], Awaitable[None]]
OnError = Callable[[str, str], Awaitable[None]]


class BinanceWebSocket:
    # Geo-cheklovlarda fallback WebSocket bazalari (ildiz: combined stream uchun /ws qo'shilmaydi).
    # DIQQAT: binance.us ko'p juftliklarni (DOT, TRX, LTC, ATOM, NEAR, UNI...) tanimaydi -> 400 beradi.
    WS_FALLBACKS = [
        "wss://stream.binance.com:9443",
        "wss://data-stream.binance.vision",
    ]

    def __init__(self, settings: Settings, on_closed_candle: OnClosedCandle,
                 on_error: OnError | None = None) -> None:
        self._settings = settings
        self._on_closed = on_closed_candle
        self._on_error = on_error
        self._task: asyncio.Task | None = None
        self._running = False

        def _root(u: str) -> str:
            # Combined stream URL bazada /ws BO'LMAYDI: <host>/stream?streams=...
            # Konfigda /ws berilgan bo'lsa, uni kesib tashlaymiz.
            return u.rstrip("/").removesuffix("/ws").rstrip("/")

        self._bases = [_root(settings.binance_ws_url)]
        for b in self.WS_FALLBACKS:
            rb = _root(b)
            if rb not in self._bases:
                self._bases.append(rb)

    def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="binance-ws")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    def _build_url(self, base: str) -> str:
        streams = []
        for symbol in self._settings.symbol_list:
            try:
                from app.market.gold_rest import needs_mexc
                if needs_mexc(symbol):
                    continue  # forex/oltin Binance'da yo'q — MEXC REST poller orqali keladi
            except Exception:  # noqa: BLE001
                if symbol.upper().startswith(("XAU", "EUR", "JPY")):
                    continue
            for tf in self._settings.watch_timeframe_list:
                streams.append(f"{symbol.lower()}@kline_{tf}")
        return f"{base}/stream?streams={'/'.join(streams)}"

    async def _run_loop(self) -> None:
        backoff = 1
        consecutive = 0
        base_idx = 0
        async with aiohttp.ClientSession() as session:
            while self._running:
                base = self._bases[base_idx % len(self._bases)]
                try:
                    logger.info("[WS] Binance kline oqimiga ulanmoqda (%s)...", base)
                    async with session.ws_connect(self._build_url(base), heartbeat=20) as ws:
                        logger.info("[WS] Ulandi: %d ta stream (%s)",
                                    len(self._settings.symbol_list) *
                                    len(self._settings.timeframe_list), base)
                        backoff = 1
                        consecutive = 0
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                await self._handle(msg.data)
                            elif msg.type in (aiohttp.WSMsgType.CLOSED,
                                              aiohttp.WSMsgType.ERROR):
                                break
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    consecutive += 1
                    base_idx += 1  # keyingi fallback endpoint
                    logger.error("[WS] Uzilish (%s): %s — %d soniyada qayta ulanish",
                                 base, exc, backoff)
                    # REST poller zaxira sifatida signallarni baribir yetkazadi,
                    # shuning uchun WS xatosi haqida faqat uzoq uzilishda ogohlantiramiz.
                    if self._on_error and consecutive >= 8:
                        await self._safe_alert(
                            "Market WebSocket",
                            "Vaqtincha ulanish muammosi. Signallar REST orqali yetkazilmoqda.",
                        )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _safe_alert(self, component: str, message: str) -> None:
        try:
            if self._on_error:
                await self._on_error(component, message)
        except Exception:  # noqa: BLE001
            pass

    async def _handle(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        data = msg.get("data") or {}
        if data.get("e") != "kline":
            return
        k = data.get("k") or {}
        symbol = data.get("s", "").upper()
        tf = k.get("i", "").lower()
        if k.get("x"):  # sham yopildi
            logger.info("[WS] %s %s sham yopildi", symbol, tf)
            await self._on_closed(symbol, tf, k)
