"""v128: wipe_trades_and_history testi: kanallar va akkaunt saqlanadi, qolganlar o'chadi."""
import pytest
from sqlalchemy import text
from app.database.session import async_session_factory
from app.services import wipe_service


@pytest.mark.asyncio
async def test_wipe_service_keeps_channels_and_resets_trades():
    from app.database.session import init_db
    from app.database.models.system import SystemLog
    await init_db()

    async with async_session_factory() as session:
        session.add(SystemLog(component="channels", message="[]", level="INFO"))
        session.add(SystemLog(component="tg_session", message="sess_data", level="INFO"))
        session.add(SystemLog(component="other_comp", message="old_log", level="INFO"))
        await session.commit()

    stats = await wipe_service.wipe_trades_and_history()
    assert isinstance(stats, dict)

    async with async_session_factory() as session:
        # Kanallar va sessiya saqlanib qolganmi?
        res = await session.execute(text("SELECT component FROM system_logs;"))
        comps = [r[0] for r in res.fetchall()]
        assert "channels" in comps, "channels jadvali saqlanishi shart!"
        assert "tg_session" in comps, "tg_session saqlanishi shart!"
        assert "other_comp" not in comps, "Eski loglar o'chirilishi shart!"

        # Signallar bo'sh bo'lishi kerak
        res_sig = await session.execute(text("SELECT count(*) FROM signals;"))
        assert res_sig.scalar() == 0
