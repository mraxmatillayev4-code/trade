"""
Konveyer: yopilgan sham → ochiq KANAL signallarini kuzatish (zarar −1R / foyda +3R).
Bot o'zi bozordan signal qidirmaydi.

v50: signal FAQAT o'z timeframe'ining shamlari bilan boshqariladi.
     Kanal signallari 1m (M1) — shuning uchun 1m shamlar asosiy.
     (Ilgari 4h sham ham 1m signalni yopib qo'yardi — bu xato edi.)
"""
from __future__ import annotations

import pandas as pd

from app.core.config import Settings
from app.core.logging import get_logger
from app.database.session import async_session_factory
from app.market.candle_manager import CandleManager, validate_candles
from app.paper_trading.engine import PaperEngine
from app.services.tracker import SignalTracker

logger = get_logger(__name__)


class AnalysisPipeline:
    def __init__(self, settings: Settings, candle_manager: CandleManager,
                 paper_engine: PaperEngine, tracker: SignalTracker,
                 notifier=None) -> None:
        self._settings = settings
        self._candles = candle_manager
        self._paper = paper_engine
        self._tracker = tracker
        self._notifier = notifier

    async def handle_closed_candle(self, symbol: str, timeframe: str,
                                   df: pd.DataFrame) -> None:
        symbol = symbol.upper()
        timeframe = timeframe.lower()
        try:
            await self._process(symbol, timeframe, df)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[PIPELINE] %s %s xatosi: %s", symbol, timeframe, exc)
            if self._notifier:
                await self._notifier.send_error(
                    "Analysis Pipeline",
                    f"{symbol} {timeframe}: {exc}",
                )

    async def _process(self, symbol: str, timeframe: str, df: pd.DataFrame) -> None:
        df.attrs["symbol"] = symbol
        df.attrs["timeframe"] = timeframe
        if df is None or len(df) < 3:
            logger.warning("[%s %s] kuzatish: sham yetarli emas", symbol, timeframe)
            return
        ok, reason = validate_candles(df, timeframe, 20)
        if not ok:
            logger.warning("[%s %s] Data quality (kuzatish davom): %s", symbol, timeframe, reason)
        try:
            from app.services import live_state
            live_state.note_check(symbol, timeframe)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[PIPELINE] live_state: %s", exc)
        await self._track_open_signals(symbol, timeframe, df)

    async def _track_open_signals(self, symbol: str, timeframe: str, df: pd.DataFrame) -> None:
        async with async_session_factory() as session:
            from sqlalchemy import select
            from app.core.enums import PaperStatus
            from app.database import crud
            from app.database.models.paper import PaperPosition
            from app.database.models.signal import Signal

            open_signals = await crud.get_active_signals(session, symbol)
            by_id = {s.id: s for s in open_signals}
            try:
                ids = list((await session.execute(
                    select(PaperPosition.signal_id).where(
                        PaperPosition.symbol == symbol,
                        PaperPosition.status == PaperStatus.OPEN.value,
                        PaperPosition.signal_id.isnot(None),
                    )
                )).scalars().all())
                ids = [i for i in ids if i and i not in by_id]
                if ids:
                    extra = list((await session.execute(
                        select(Signal).where(Signal.id.in_(ids))
                    )).scalars().all())
                    for s in extra:
                        by_id[s.id] = s
            except Exception as exc:  # noqa: BLE001
                logger.warning("[PIPELINE] paper signal: %s", exc)
            tracked = 0
            for sig in by_id.values():
                sig_tf = str(getattr(sig, "timeframe", "") or "").lower()
                is_channel = (getattr(sig, "quality_mode", "") or "").upper() == "CHANNEL"
                if sig_tf and sig_tf != timeframe:
                    # kanal M1 signali: 1m sham yo'q bo'lsa — boshqa TF bilan ham boshqariladi
                    if not (is_channel and timeframe == "1m"):
                        continue
                await self._tracker.update_for_candle(session, sig, df, self._notifier)
                tracked += 1
            if tracked and timeframe == "1m":
                logger.debug("[PIPELINE] %s %s: %d signal boshqarildi", symbol, timeframe, tracked)
