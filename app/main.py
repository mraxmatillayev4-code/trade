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

# v63/v76: commandlar ro'yxati — ko'k «Menu» ham, tayyor xabari ham shu yerdan oladi.
_cmds = [
    ("start", "🚀 Botni ishga tushirish"),
    ("menu", "☰ Asosiy menyu"),
    ("kuzat", "🔎 Jonli kuzatuv (narx, R darajalar)"),
    ("natija", "📋 Oxirgi WIN/LOSE natijalar"),
    ("hisob", "💼 Virtual (paper) hisob"),
    ("akkaunt", "👤 Telegram akkaunt ulash"),
    ("qr", "🔳 Akkauntni QR bilan ulash"),
    ("forget", "🚪 Akkauntni uzish"),
    ("100", "🗂 Kanallardan 100 tadan xabar yozib olish"),
    ("100stat", "📊 Baza statistikasi (kanallar)"),
    ("100fayl", "📄 Baza (txt fayl)"),
    ("100ocr", "🔤 Rasmlardan yozuvni o'qish (OCR)"),
    ("100test", "🧪 Diagnostika"),
    ("tozalash", "🧹 Hammasini tozalash (noldan)"),
    ("broker", "🏦 Broker (MT5 demo/real) ulash"),
    ("db", "💾 /DB - bazani yuklab olish (Supabase/Neon)"),
    ("risk", "⚖️ Risk foizi (0.5% / 1% / 2%) - money management"),
    ("zaxira", "🛡 Akkaunt va kanallar zaxirasi (qayta ulash shart emas)"),
]


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
        # v82/v83: akkaunt va kanallar zaxirasi — yangilanishdan keyin qayta ulanmaslik
        self.persist_ok = False
        try:
            from app.services import persist
            fixed = await persist.restore_if_missing()
            if fixed and self.notifier is not None:
                try:
                    await self.notifier.send_admin(fixed)
                except Exception:  # noqa: BLE001
                    pass
            await persist.save_guard()
            self.persist_ok = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("[PERSIST] guard: %s", exc)

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

        # v83: bot tayyor bo'lgach — bo'sh baza bo'lsa ogohlantirish, keyin avto-zaxira
        async def persist_tasks() -> None:
            """v83: zaxira faylini Telegramga yuborish (startup + har 24 soat)."""
            from app.services import persist
            await asyncio.sleep(15)
            try:
                warn = await persist.warn_if_empty(self.notifier)
                if warn and self.notifier is not None:
                    await self.notifier.send_admin(warn)
                else:
                    snap = await persist.snapshot()
                    if snap.get("session") or snap.get("channels"):
                        await persist.send_backup(
                            self.notifier,
                            note="\U0001F510 <b>ZAXIRA NUSXA</b> (startup)",
                        )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[PERSIST] startup zaxira: %s", exc)
            try:
                await persist.auto_loop(self.notifier)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[PERSIST] avto-loop: %s", exc)

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
            # v63: Telegram "Menu" tugmasi + BARCHA commandlar (xato bo'lsa ham menyu bo'sh qolmaydi)
            import re as _re

            from aiogram.types import BotCommand

            # v72: Chap pastdagi KO'K «Menu» tugmasi QAYTARILDI (foydalanuvchi so'radi).
            # Faqat pastdagi (reply) klaviaturaning ichidagi «☰ Menyu» tugmasi olib
            # tashlangan edi — bu ko'k Menu klaviatura tugmasi emas, u Telegramning
            # o'z tugmasi va commandlar ro'yxatini ochadi.
            _safe = [BotCommand(command=c, description=d) for c, d in _cmds
                     if _re.fullmatch(r"[a-z0-9_]{1,32}", c)]
            _done: list[str] = []
            try:
                await self.bot.set_my_commands(_safe)
                _done = [c.command for c in _safe]
                logger.info("[BOT] commandlar menyusi: %d ta", len(_safe))
            except Exception as exc:  # noqa: BLE001
                logger.warning("[BOT] komandalar to'liq o'rnatilmadi (%s) - harfdan boshlanadiganlari", exc)
                _safe2 = [c for c in _safe if not c.command[0].isdigit()]
                try:
                    await self.bot.set_my_commands(_safe2)
                    _done = [c.command for c in _safe2]
                except Exception as exc2:  # noqa: BLE001
                    logger.error("[BOT] komandalar o'rnatilmadi: %s", exc2)
            try:
                from aiogram.types import MenuButtonCommands
                await self.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
                logger.info("[BOT] ko'k MENU tugmasi o'rnatildi (v72)")
            except Exception as exc:  # noqa: BLE001
                logger.warning("[BOT] MENU tugmasi: %s", exc)
            try:
                # v76: matn versiyani local_ai dan oladi (eski «v72» yozuvi yo'q),
                # har versiya uchun FAQAT BIR MARTA yuboriladi (har restartda emas).
                from app.services import bootmsg

                async with async_session_factory() as _s:
                    _announce = await bootmsg.should_announce(_s)
                if _announce:
                    _txt = bootmsg.build_text([c.command for c in (_done or _safe)])
                    await self.notifier.send_admin(_txt)
                    async with async_session_factory() as _s:
                        await bootmsg.mark(_s)
                    logger.info("[BOT] tayyor xabari yuborildi (%s)", bootmsg.label())
                else:
                    logger.info("[BOT] tayyor xabari bu versiya uchun allaqachon yuborilgan (%s)",
                                bootmsg.label())
            except Exception as exc:  # noqa: BLE001
                logger.warning("[BOT] tayyor xabari: %s", exc)
        else:
            logger.warning("BOT_TOKEN yo'q — Telegram bot ishlamaydi (faqat API)")

    # ---------- Narx (muddat yopilishi uchun) ----------
    async def price_for(self, symbol: str) -> float | None:
        """Oxirgi narx: 1m shamdan (eskirmagan bo'lsa), aks holda birjadan.

        v81: eskirgan (kutubxonadagi) narx qaytarilmaydi — aks holda SL/TP
        noto'g'ri hisoblanardi.
        """
        from app.services import watchdog as _wd
        try:
            df = self.candles.get_df(symbol, "1m", include_open=True)
            if df is not None and len(df):
                px = float(df.iloc[-1]["close"])
                fresh = True
                try:
                    ot = df.iloc[-1].get("open_time")
                    if ot is not None:
                        age = (datetime.now(timezone.utc) - ot.to_pydatetime()).total_seconds()
                        fresh = age < 180
                except Exception:  # noqa: BLE001
                    fresh = True
                if px > 0 and fresh:
                    _wd.note_price(symbol, px, "1m sham")
                    return px
        except Exception:  # noqa: BLE001
            pass
        try:
            if needs_mexc(symbol):
                px2 = await self.gold.get_last_price(symbol)
                _wd.note_price(symbol, px2, "MEXC")
                return px2
            px2 = await self.rest.get_last_price(symbol)
            _wd.note_price(symbol, px2, "birja")
            return px2
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

        async def watch_guard() -> None:
            """v81: JONLI KUZATUV + oqim nazorati.

            1) Ochiq signallar uchun narx har ~20 sekundda tekshiriladi —
               sham yopilishini kutmasdan SL/TP urilishi aniqlanadi.
            2) Narx oqimi (WS/REST) uzilsa yoki sham kechiksa — ogohlantirish.
            """
            from app.services import watchdog
            await asyncio.sleep(20)
            while True:
                try:
                    open_syms: set[str] = set()
                    from sqlalchemy import select as _select
                    from app.database.models.signal import Signal as _Signal
                    async with async_session_factory() as session:
                        rows = list((await session.execute(
                            _select(_Signal).where(_Signal.is_active.is_(True))
                        )).scalars().all())
                        sigs = [s for s in rows if (s.quality_mode or "").upper() == "CHANNEL"]
                        for sig in sigs:
                            open_syms.add(str(sig.symbol or "").upper())
                        for sig in sigs:
                            sym = str(sig.symbol or "").upper()
                            px = await self.price_for(sym)
                            if not px:
                                continue
                            df = None
                            try:
                                df = self.candles.get_df(sym, "1m", include_open=True)
                            except Exception:  # noqa: BLE001
                                df = None
                            await self.tracker.live_tick(
                                session, sig, float(px), df=df, notifier=self.notifier,
                            )
                    await watchdog.check(
                        notifier=self.notifier,
                        symbols=self.settings.symbol_list,
                        timeframes=["1m"],
                        open_symbols=open_syms,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[WATCHDOG] sikl: %s", exc)
                await asyncio.sleep(20)

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

        async def db_backup_loop() -> None:
            """v76: har 48 soatda 23:00 (Toshkent) — baza SQL zaxirasini adminga yuboradi."""
            try:
                from app.services import dbbackup
                await dbbackup.loop(self.bot)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[DB-BACKUP] start: %s", exc)

        self._scheduler_tasks.append(asyncio.create_task(db_backup_loop(), name="db-backup"))
        self._scheduler_tasks.append(asyncio.create_task(watch_guard(), name="watch-guard"))
        # v83: zaxira faylini Telegramga yuborish (startup + har 24 soat)
        self._scheduler_tasks.append(asyncio.create_task(persist_tasks(), name="persist-backup"))
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
