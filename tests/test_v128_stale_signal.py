"""v128: Eskirgan xabarlarga (1 soatdan eski) savdo ochilmasligi testi."""
import pytest
from datetime import datetime, timezone, timedelta
from app.services import channel_inbox


@pytest.mark.asyncio
async def test_stale_signal_rejected():
    # 71 soat oldingi post (user skrinshotidagi holat)
    old_date = datetime.now(timezone.utc) - timedelta(hours=71)
    
    status = await channel_inbox.ingest_raw(
        ch={"username": "bek_fxx", "title": "BEK FXX"},
        text="BUY GOLD 4010-4012 SL 4000 TP 4030",
        msg_id=54421,
        chat_id=123456,
        posted_at=old_date,
    )
    assert status == "stale_signal", f"Eski signal rad etilishi kerak edi, lekin: {status}"


@pytest.mark.asyncio
async def test_fresh_signal_not_rejected_by_stale_check():
    # 2 daqiqa oldingi yangi post
    fresh_date = datetime.now(timezone.utc) - timedelta(minutes=2)
    
    # Text signal emas deb chiqsa ham, stale_signal deb rad etilmasligi kerak
    status = await channel_inbox.ingest_raw(
        ch={"username": "bek_fxx", "title": "BEK FXX"},
        text="Salom bugun savdo qilamiz",
        msg_id=54422,
        chat_id=123456,
        posted_at=fresh_date,
    )
    assert status != "stale_signal", "Yangi xabar stale_signal deb rad etilmasligi kerak"
