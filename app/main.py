"""
Ilova kirish nuqtasi.
Modes:
  python -m app.main all   — bot + scheduler + websocket + API (local)
  python -m app.main bot   — bot + scheduler + websocket (docker)
  python -m app.main api   — faqat FastAPI (docker)
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.bot.handlers import get_main_router
from app.bot.middlewares import AccessMiddleware
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.core.redis_client import RedisCache
from app.database.seed import seed_db
from app.database.session import async_session_factory, init_db
from app.market.binance_rest import BinanceRest
from app.market.binance_ws import BinanceWebSocket
from app.market.candle_manager import CandleManager
from app.market.gold_rest import GoldRest, needs_mexc
from app.notifications.telegram import TelegramNotifier
from app.paper_trading.engine import PaperEngine
from app.services.pipeline import AnalysisPipeline
from app.services.tracker import SignalTracker

logger = get_logger(__name__)


class Application:
    def __init__(self) -> None:
        self.settings = get_settings()
        setup_logging(self.settings.log_level)

        self.bot: Bot | None = None
        self.dp: Dispatcher | None = None
        self.rest = BinanceRest(self.settings)
        self.gold = GoldRest()                      # MEXC — oltin (XAUUSDT) manbasi
        self.candles = CandleManager(self.settings, self.rest, gold_rest=self.gold)
        self.paper = PaperEngine()
        self.tracker = SignalTracker(self.paper, self.settings)
        self.notifier = TelegramNotifier()
        self.pipeline = AnalysisPipeline(
            self.settings, self.candles, self.paper, self.tracker, self.notifier
        )
        from app.services.channel_inbox import bind as bind_channels
        bind_channels(self.candles, self.paper, self.tracker, self.notifier, self.settings)
        self.cache = RedisCache(self.settings.redis_url)
        self._scheduler_tasks: list[asyncio.Task] = []
        self._ws: BinanceWebSocket | None = None

    async def startup_common(self) -> None:
        await init_db()
        async with async_session_factory() as session:
            await seed_db(session)
            try:
                from app.services.channel_store import wipe_reads_once
                if await wipe_reads_once(session):
                    logger.info("[CH] hisobot kanal sonlari bir marta 0 qilindi")
            except Exception as exc:  # noqa: BLE001
                logger.warning("[CH] wipe: %s", exc)
            try:
                from app.engine.brain import get_brain
                n = await get_brain().hydrate_from_db(session)
                logger.info("[AI] ishga tushish: %d ta eski xatodan xotira yuklandi", n)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[AI] xotira yuklanmadi: %s", exc)
            try:
                from app.engine.knowledge import get_knowledge
                get_knowledge()
                logger.info("[AI-WEB] internet xotirasi tayyor")
            except Exception as exc:  # noqa: BLE001
                logger.warning("[AI-WEB] xotira: %s", exc)
        # v50: yangi ustunlar (signals.close_reason, paper_positions.close_reason)
        # eski bazada ham bo'lishi shart — aks holda har bir yozuv xato beradi.
        try:
            from app.services.channel_inbox import _ensure_schema
            async with async_session_factory() as session:
                added = await _ensure_schema(session, force=True)
            if added:
                logger.warning("[DB] yetishmagan ustunlar qo'shildi: %s", added)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[DB] sxema tekshiruvi: %s", exc)
        await self.cache.connect()
        try:
            from app.core.access import hydrate_admins
            await hydrate_admins()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[ADMIN] hydrate: %s", exc)
        await self.candles.load_history()
        # v61: handlerlar jonli narxni olishi uchun manbani ulaymiz (/kuzat)
        try:
            from app.services import live_state
            live_state.set_price_provider(self.price_for)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[PX] live_state: %s", exc)

        if self.settings.bot_token:
            self.bot = Bot(
                token=self.settings.bot_token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            self.notifier.bind_bot(self.bot)
            self.dp = Dispatcher()
            self.dp.message.middleware(AccessMiddleware())
            self.dp.callback_query.middleware(AccessMiddleware())
            self.dp.include_router(get_main_router())
            # Telegram chap burchakdagi "Menu" tugmasi (buyruqlar menyusi)
            from aiogram.types import BotCommand
            try:
                # v62: botda MAVJUD bo'lgan BARCHA commandlar menyuga qo'yiladi
                await self.bot.set_my_commands([
                    BotCommand(command="start", description="🚀 Botni ishga tushirish"),
                    BotCommand(command="menu", description="☰ Pastki menyuni ochish"),
                    BotCommand(command="kuzat", description="🔎 Jonli kuzatuv (narx va R darajalar)"),
                    BotCommand(command="natija", description="📋 Oxirgi WIN/LOSE natijalar"),
                    BotCommand(command="hisob", description="💼 Virtual (paper) hisob"),
                    BotCommand(command="akkaunt", description="👤 Telegram akkaunt ulash"),
                    BotCommand(command="qr", description="🔳 Akkauntni QR bilan ulash"),
                    BotCommand(command="forget", description="🚪 Akkauntni uzish"),
                    BotCommand(command="100", description="🗂 Kanallardan 100 tadan xabar yozib olish"),
                    BotCommand(command="100stat", description="📊 Baza statistikasi (kanallar)"),
                    BotCommand(command="100fayl", description="📄 Baza (txt fayl)"),
                    BotCommand(command="100ocr", description="🔤 Rasmlardan yozuvni o'qish (OCR)"),
                    BotCommand(command="100test", description="🧪 Diagnostika (OCR zanjiri)"),
                    BotCommand(command="tozalash", description="🧹 Hammasini tozalash (noldan)"),
                ])
            except Exception as exc:  # noqa: BLE001
                logger.warning("Bot komandalari o'rnatilmadi: %s", exc)
        else:
            logger.warning("BOT_TOKEN yo'q — Telegram bot ishlamaydi (faqat API)")

    # ---------- Narx (muddat yopilishi uchun) ----------
    async def price_for(self, symbol: str) -> float | None:
        """Oxirgi narx: avval 1m shamdan, bo'lmasa birjadan."""
        try:
            df = self.candles.get_df(symbol, "1m", include_open=True)
            if df is not None and len(df):
                px = float(df.iloc[-1]["close"])
                if px > 0:
                    return px
        except Exception:  # noqa: BLE001
            pass
        try:
            if needs_mexc(symbol):
                return await self.gold.get_last_price(symbol)
            return await self.rest.get_last_price(symbol)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[PX] %s narx olinmadi: %s", symbol, exc)
            return None

    # ---------- Scheduler ----------
    def start_scheduler(self) -> None:
        """REST fallback poller + avtomatik hisobotlar."""
        async def poll_loop() -> None:
            while True:
                try:
                    for symbol in self.settings.symbol_list:
                        for tf in self.settings.watch_timeframe_list:
                            df = await self.candles.poll_closed_candle(symbol, tf)
                            if df is not None:
                                await self.pipeline.handle_closed_candle(symbol, tf, df)
                            await asyncio.sleep(0.2)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Poll loop xatosi: %s", exc)
                await asyncio.sleep(self.settings.rest_poll_seconds)

        async def report_loop() -> None:
            """Har kuni belgilangan vaqtda: kunlik (doim), dushanba haftalik,
            1-chi oylik hisobotni yuboradi."""
            last_day = None
            while True:
                try:
                    now = datetime.now(timezone.utc)
                    day_key = now.date()
                    if last_day != day_key and now.hour == self.settings.report_time_utc:
                        from app.services.reports import build_report
                        async with async_session_factory() as session:
                            daily = await build_report(session, "daily")
                            await self.notifier.send_report(daily)
                            if now.weekday() == 6:  # yakshanba
                                weekly = await build_report(session, "weekly")
                                await self.notifier.send_report(weekly)
                            if now.day == 1:
                                monthly = await build_report(session, "monthly")
                                await self.notifier.send_report(monthly)
                        last_day = day_key
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Hisobot xatosi: %s", exc)
                await asyncio.sleep(600)  # 10 daqiqada tekshirish

        async def study_loop() -> None:
            """Har 6 soatda internetdan (DDG/Yandex/YouTube RSS) treyding darsi."""
            await asyncio.sleep(8)
            while True:
                try:
                    from app.engine.knowledge import get_knowledge
                    n = await asyncio.to_thread(get_knowledge().study_web)
                    logger.info("[AI-WEB] internetdan %d ta kalit yangilandi", n)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[AI-WEB] o'rganish xato: %s", exc)
                await asyncio.sleep(6 * 3600)

        async def channel_watch() -> None:
            try:
                from app.services.channel_watcher import start_watcher
                await start_watcher()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[CH-WATCH] start: %s", exc)

        async def expiry_loop() -> None:
            """v50: muddati tugagan signallarni yopish (M1 — 4 soat).

            Kanal M1 signallari abadiy ochiq qolmasin: TP ham, SL ham urilmasa
            belgilangan daqiqadan keyin bozor narxida yopiladi va WIN/LOSE
            kartasi yuboriladi.
            """
            await asyncio.sleep(25)
            while True:
                try:
                    async with async_session_factory() as session:
                        n = await self.tracker.sweep_expired(
                            session, notifier=self.notifier,
                            price_lookup=self.price_for,
                        )
                    if n:
                        logger.info("[TRACKER] muddati tugagan %d signal yopildi", n)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[TRACKER] expiry loop: %s", exc)
                await asyncio.sleep(max(60, int(self.settings.expiry_sweep_seconds)))

        self._scheduler_tasks.append(asyncio.create_task(poll_loop(), name="rest-poller"))
        self._scheduler_tasks.append(asyncio.create_task(expiry_loop(), name="expiry-sweep"))
        self._scheduler_tasks.append(asyncio.create_task(report_loop(), name="reports"))
        self._scheduler_tasks.append(asyncio.create_task(channel_watch(), name="ch-watch"))
        logger.info(
            "Scheduler ishga tushdi: poller har %ss, hisobot %02d:00 UTC "
            "(%02d:00 Toshkent), muddat tekshiruvi har %ss (kanal M1 muddati: %s daqiqa)",
            self.settings.rest_poll_seconds, self.settings.report_time_utc,
            (int(self.settings.report_time_utc) + 5) % 24,
            self.settings.expiry_sweep_seconds, self.settings.channel_expiry_minutes,
        )

    def start_websocket(self) -> None:
        if not self.settings.ws_enabled:
            logger.info("WebSocket o'chirilgan (sozlamada)")
            return

        async def on_closed(symbol: str, tf: str, kline: dict) -> None:
            df = self.candles.update_from_ws(symbol, tf, kline)
            if df is not None:
                await self.pipeline.handle_closed_candle(symbol, tf, df)

        async def on_error(component: str, message: str) -> None:
            await self.notifier.send_error(component, message)

        self._ws = BinanceWebSocket(self.settings, on_closed, on_error)
        self._ws.start()

    async def run_bot_polling(self) -> None:
        if self.bot is None or self.dp is None:
            logger.error("Bot ishga tushmadi — BOT_TOKEN tekshiring")
            return
        await self.bot.delete_webhook(drop_pending_updates=True)
        logger.info("Telegram bot polling boshlandi")
        await self.dp.start_polling(self.bot, handle_signals=False)

    async def run_api(self) -> None:
        import os
        from app.api.server import create_app
        app = create_app()
        port = int(os.environ.get("PORT", "8000"))
        config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
        server = uvicorn.Server(config)
        logger.info("API server ishga tushdi: 0.0.0.0:%s", port)
        await server.serve()

    async def shutdown(self) -> None:
        logger.info("Tizim to'xtatilmoqda...")
        if self._ws:
            await self._ws.stop()
        try:
            from app.services.channel_watcher import stop_watcher
            await stop_watcher()
        except Exception:  # noqa: BLE001
            pass
        for task in self._scheduler_tasks:
            task.cancel()
        if self.bot:
            await self.bot.session.close()
        await self.rest.close()
        await self.gold.close()
        await self.cache.close()


async def amain(mode: str) -> None:
    app = Application()
    await app.startup_common()

    tasks: list[asyncio.Task] = []

    if mode in ("all", "bot"):
        app.start_scheduler()
        app.start_websocket()
        tasks.append(asyncio.create_task(app.run_bot_polling(), name="bot"))
    if mode in ("all", "api"):
        tasks.append(asyncio.create_task(app.run_api(), name="api"))

    try:
        await asyncio.gather(*tasks, return_exceptions=False)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await app.shutdown()


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode not in ("all", "bot", "api"):
        print("Usage: python -m app.main [all|bot|api]")
        sys.exit(1)
    try:
        asyncio.run(amain(mode))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
