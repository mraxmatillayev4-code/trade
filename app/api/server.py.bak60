"""FastAPI — o'qish endpointlari va TradingView webhook."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.timeuz import to_tashkent
from app.core.security import verify_webhook_signature
from app.database import crud
from app.database.models.backtest import Backtest
from app.database.session import async_session_factory, init_db
from app.database.seed import seed_db
from app.market.binance_rest import BinanceRest
from app.services.statistics import overall_statistics, strategy_statistics

logger = get_logger(__name__)


class WebhookPayload(BaseModel):
    symbol: str
    timeframe: str
    direction: str  # BUY | SELL
    timestamp: int | None = None
    secret: str | None = None


def create_app() -> FastAPI:
    app = FastAPI(title="Trading Signal Bot API", version="1.0.0")
    settings = get_settings()
    rest = BinanceRest(settings)
    app.state.rest = rest

    @app.on_event("startup")
    async def _startup() -> None:
        await init_db()
        async with async_session_factory() as session:
            await seed_db(session)

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await rest.close()

    @app.get("/")
    @app.api_route("/health", methods=["GET", "HEAD"])
    async def health() -> dict:
        return {"status": "ok", "time": to_tashkent().isoformat()}

    @app.get("/api/signals")
    async def list_signals(limit: int = 20, direction: str | None = None) -> list[dict]:
        async with async_session_factory() as session:
            signals = await crud.get_recent_signals(
                session, limit=min(limit, 100),
                direction=direction if direction in ("BUY", "SELL") else None,
            )
            return [_signal_dict(s) for s in signals]

    @app.get("/api/signals/{signal_id}")
    async def get_signal(signal_id: int) -> dict:
        async with async_session_factory() as session:
            s = await crud.get_signal_by_id(session, signal_id)
            if s is None:
                raise HTTPException(404, "Signal topilmadi")
            confirms = await crud.get_confirmations(session, signal_id)
            data = _signal_dict(s)
            data["confirmations"] = [
                {"strategy": c.strategy_name, "direction": c.direction,
                 "score": c.score, "reason": c.reason}
                for c in confirms
            ]
            return data

    @app.get("/api/statistics")
    async def get_statistics() -> dict:
        async with async_session_factory() as session:
            return await overall_statistics(session)

    @app.get("/api/strategies")
    async def get_strategies() -> list[dict]:
        async with async_session_factory() as session:
            return await strategy_statistics(session)

    @app.get("/api/market/{symbol}")
    async def get_market(symbol: str) -> dict:
        try:
            return await rest.get_ticker_24h(symbol.upper())
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"Binance xatosi: {exc}")

    @app.post("/api/backtest")
    async def list_backtests(limit: int = 20) -> list[dict]:
        from sqlalchemy import select
        async with async_session_factory() as session:
            rows = (await session.execute(
                select(Backtest).order_by(Backtest.created_at.desc()).limit(limit)
            )).scalars().all()
            return [
                {"id": b.id, "symbol": b.symbol, "timeframe": b.timeframe,
                 "period": b.period, "strategy": b.strategy,
                 "metrics": json.loads(b.metrics_json or "{}"),
                 "created_at": b.created_at.isoformat()}
                for b in rows
            ]

    @app.get("/api/backtest/{backtest_id}")
    async def get_backtest(backtest_id: int) -> dict:
        async with async_session_factory() as session:
            b = await session.get(Backtest, backtest_id)
            if b is None:
                raise HTTPException(404, "Backtest topilmadi")
            return {
                "id": b.id, "symbol": b.symbol, "timeframe": b.timeframe,
                "period": b.period, "strategy": b.strategy,
                "metrics": json.loads(b.metrics_json or "{}"),
            }

    @app.post("/webhook/tradingview")
    async def tradingview_webhook(
        request: Request,
        x_signature: str | None = Header(default=None),
        x_timestamp: str | None = Header(default=None),
    ) -> dict:
        if not settings.webhook_secret:
            raise HTTPException(403, "Webhook o'chiq")
        body = await request.body()
        if not verify_webhook_signature(
            settings.webhook_secret, body, x_signature or "", x_timestamp
        ):
            logger.warning("[WEBHOOK] noto'g'ri imzo rad etildi")
            raise HTTPException(401, "Noto'g'ri imzo")

        try:
            payload = WebhookPayload(**json.loads(body))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(422, f"Noto'g'ri payload: {exc}")

        if payload.direction not in ("BUY", "SELL"):
            raise HTTPException(422, "Yo'nalish BUY yoki SELL bo'lishi kerak")
        if payload.timeframe not in settings.timeframe_list:
            raise HTTPException(422, "Timeframe qo'llab-quvvatlanmaydi")

        # Tashqi signal AVTOMATIK ishonchli emas — o'z dvigatelimiz bilan tasdiqlaymiz
        confirmed = await _externally_confirm(payload.symbol, payload.timeframe)
        logger.info(
            "[WEBHOOK] %s %s %s → dvigatel tasdig'i: %s",
            payload.symbol, payload.timeframe, payload.direction, confirmed,
        )
        return {"received": True, "engine_confirmed": confirmed}

    async def _externally_confirm(symbol: str, timeframe: str) -> bool:
        """Webhook signalini o'z tahlilimiz bilan solishtiramiz."""
        from app.engine import signal_engine
        from app.market.candle_manager import CandleManager
        df = await rest.get_klines(symbol.upper(), timeframe.lower(),
                                   settings.history_candles)
        boundary = CandleManager._expected_open_time(timeframe)
        df = df[df["open_time"] < boundary].copy()
        if len(df) < settings.min_candles:
            return False
        decision, _ = signal_engine.analyze(df, timeframe, settings)
        return decision.passes_threshold

    return app


def _signal_dict(s) -> dict:
    return {
        "id": s.id,
        "symbol": s.symbol,
        "timeframe": s.timeframe,
        "direction": s.direction,
        "status": s.status,
        "score": s.score,
        "confidence": s.confidence,
        "strength": s.strength,
        "regime": s.regime,
        "mtf": s.mtf_alignment,
        "entry": s.entry,
        "sl": s.sl,
        "tp1": s.tp1,
        "tp2": s.tp2,
        "tp3": s.tp3,
        "result": s.result,
        "r_multiple": s.r_multiple,
        "pnl_percent": s.pnl_percent,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "closed_at": s.closed_at.isoformat() if s.closed_at else None,
    }
