"""v128: Yagona balans testi — balans $50 qilinganda $50 bo'ladi, 10050 emas!"""
import pytest
from app.database.session import init_db, async_session_factory
from app.paper_trading.engine import PaperEngine
from app.services.paper_split import bucket_stats
from app.services.wipe_service import wipe_trades_and_history


@pytest.mark.asyncio
async def test_balance_is_strictly_single_and_not_polluted():
    await init_db()
    engine = PaperEngine()
    user_id = 12345

    async with async_session_factory() as session:
        # 1. Standart hisob yaratildi
        acc = await engine.get_account(session, user_id)
        assert acc.balance == 10000.0

        # Boshqa bir user ham bor deylik (masalan 99999)
        other_acc = await engine.get_account(session, 99999)
        assert other_acc.balance == 10000.0

        # 2. Foydalanuvchi balansini 50$ qildi
        acc = await engine.set_balance(session, user_id, 50.0)
        assert acc.balance == 50.0
        session.expire_all()

        # 3. Barcha haqiqiy hisoblar 50$ ga sinxronlashgan bo'lishi kerak!
        other_acc_fresh = await engine.get_account(session, 99999)
        assert other_acc_fresh.balance == 50.0

        # 4. bucket_stats chaqirilganda balans aniq 50$ bo'lishi shart (10050 yoki 10000 emas!)
        stats = await bucket_stats(session, user_id)
        assert stats["jami"]["balance"] == 50.0
        assert stats["jami"]["initial"] == 50.0

        # 5. Foydalanuvchi yana 50$ deb kiritdi (50 + 50 = 100 bo'lmasligi, faqat 50 bo'lishi kerak!)
        acc2 = await engine.set_balance(session, user_id, 50.0)
        assert acc2.balance == 50.0

        stats2 = await bucket_stats(session, user_id)
        assert stats2["jami"]["balance"] == 50.0
        assert stats2["jami"]["initial"] == 50.0

    # 6. /tozalash qilinganda ham 50$ buzilmasdan saqlanib qoladi!
    await wipe_trades_and_history()
    async with async_session_factory() as session:
        acc_after_wipe = await engine.get_account(session, user_id)
        assert acc_after_wipe.balance == 50.0, "Tozalashdan keyin ham 50$ balansi saqlanishi kerak!"
