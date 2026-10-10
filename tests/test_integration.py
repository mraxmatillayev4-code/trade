"""Integration test: market data → strategiyalar → signal engine → dedup → DB."""
import pytest

from app.core.enums import Direction
from app.database import crud
from app.database.models.signal import Signal
from app.database.seed import seed_db
from app.database.session import async_session_factory, init_db
from app.engine.deduplication import is_signal_allowed
from app.indicators.bundle import compute_bundle
from app.engine import signal_engine


@pytest.mark.asyncio
async def test_full_pipeline_creates_signal(uptrend_df, settings):
    await init_db()
    async with async_session_factory() as session:
        await seed_db(session)

    # Tahlil
    decision, bundle = await signal_engine.analyze(uptrend_df, "15m", settings)
    assert decision.direction in (Direction.BUY, Direction.SELL, Direction.NEUTRAL)

    if decision.passes_threshold:
        async with async_session_factory() as session:
            allowed, _ = await is_signal_allowed(
                session, "TESTUSDT", "15m", decision.direction, settings
            )
            assert allowed is True

            signal = Signal(
                symbol="TESTUSDT", timeframe="15m",
                direction=decision.direction.value,
                status="ACTIVE", is_active=True,
                score=decision.score, confidence=decision.confidence,
                strength=decision.strength.value,
                regime=decision.regime.value, mtf_alignment=decision.mtf.value,
                quality_mode="BALANCED",
                entry=bundle.last_close,
                entry_low=bundle.last_close * 0.999,
                entry_high=bundle.last_close * 1.001,
                sl=bundle.last_close * 0.99,
                tp1=bundle.last_close * 1.01,
                tp2=bundle.last_close * 1.02,
                tp3=bundle.last_close * 1.03,
                atr_value=bundle.last_atr,
                candle_open_time=uptrend_df.iloc[-1]["open_time"],
            )
            session.add(signal)
            await session.commit()
            await session.refresh(signal)
            signal_id = signal.id

            # Xuddi shu yo'nalishda takror signal RAD etiladi
            allowed2, reason = await is_signal_allowed(
                session, "TESTUSDT", "15m", decision.direction, settings
            )
            assert allowed2 is False
            assert "ochiq signal" in reason

        # Signal DB dan o'qiladi
        async with async_session_factory() as session:
            loaded = await crud.get_signal_by_id(session, signal_id)
            assert loaded is not None
            assert loaded.symbol == "TESTUSDT"


@pytest.mark.asyncio
async def test_dedup_allows_opposite_direction(uptrend_df, settings):
    await init_db()
    async with async_session_factory() as session:
        await seed_db(session)
        # Qarshi yo'nalishda ochiq signal bo'lmasa ruxsat
        allowed, _ = await is_signal_allowed(session, "ETHUSDT", "1h",
                                             Direction.BUY, settings)
        assert allowed is True


def test_bundle_computes(uptrend_df, settings):
    b = compute_bundle(uptrend_df, settings)
    assert b.last_close > 0
    assert b.last_atr > 0
    assert b.support is not None
    assert b.resistance is not None
