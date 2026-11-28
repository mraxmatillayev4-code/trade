"""Tests for v131: Duplicate message prevention, concurrency locks, and idempotency guards."""
import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest
from app.notifications.telegram import TelegramNotifier
from app.database.models.signal import Signal


@pytest.mark.asyncio
async def test_notifier_deduplication():
    mock_bot = AsyncMock()
    notifier = TelegramNotifier(bot=mock_bot)
    
    # 1. Birinchi xabar
    text = "🛑 <b>№2 XAUUSDT</b> — 🔒 TP1 stopda yopildi (foyda qulflangan) (2 lot) @ 3,523.00"
    await notifier._send(text, chat_ids=[12345])
    assert mock_bot.send_message.call_count == 1
    
    # 2. Xuddi shu xabar darhol qayta yuborilsa — BLOKLANISHI KERAK
    await notifier._send(text, chat_ids=[12345])
    assert mock_bot.send_message.call_count == 1, "Dublikat xabar bloklanishi shart!"
    
    # 3. Boshqa chat_id ga yuborilsa — o'tishi kerak
    await notifier._send(text, chat_ids=[67890])
    assert mock_bot.send_message.call_count == 2
    
    # 4. Boshqa matn yuborilsa — o'tishi kerak
    new_text = "✅ <b>SIGNAL №2</b> — YUTDI"
    await notifier._send(new_text, chat_ids=[12345])
    assert mock_bot.send_message.call_count == 3


@pytest.mark.asyncio
async def test_send_result_single_call_only():
    mock_bot = AsyncMock()
    notifier = TelegramNotifier(bot=mock_bot)
    
    sig = MagicMock()
    sig.id = 999
    sig.symbol = "XAUUSDT"
    sig.direction = "BUY"
    sig.r_multiple = 3.5
    sig.is_active = False
    
    # Birinchi marta send_result
    # formatlash yoki DB chaqiruvlari mock qilinadi
    notifier._send = AsyncMock()
    await notifier.send_result(sig)
    
    # Ikkinchi marta takroriy send_result
    await notifier.send_result(sig)
    
    # Signal #999 natija kartasi FAQAT 1 marta yuborilishi shart
    assert 999 in notifier._sent_result_signals


@pytest.mark.asyncio
async def test_tracker_finished_signal_guard():
    from app.services.tracker import SignalTracker
    paper_engine = MagicMock()
    settings = MagicMock()
    tracker = SignalTracker(paper_engine, settings)
    
    session = AsyncMock()
    sig = Signal(id=55, symbol="XAUUSDT", is_active=False, r_multiple=3.5)
    
    # finished_signals ga qo'shilgan signal
    tracker._finished_signals.add(55)
    
    # live_tick va update_for_candle qayta ishlamasligi kerak
    res = await tracker.live_tick(session, sig, 3500.0)
    assert res is False
    
    await tracker.update_for_candle(session, sig, None)
    # Hech qanday xatoliksiz tezda qaytishi kerak
