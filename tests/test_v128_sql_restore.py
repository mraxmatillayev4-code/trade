"""v128: SQL dump orqali bazani tiklash (restore_sql) va zaxira fayllari signal emasligi testi."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services import dbdump
from app.bot.handlers.channels import AdminSignalIn


@pytest.mark.asyncio
async def test_restore_sql_empty():
    ok, msg, stats = await dbdump.restore_sql(b"")
    assert not ok
    assert "bo'sh" in msg.lower()


@pytest.mark.asyncio
async def test_restore_sql_invalid():
    ok, msg, stats = await dbdump.restore_sql(b"salom dunyo bu sql emas")
    assert not ok
    assert "bu sino ai baza dumpi emas" in msg.lower()


@pytest.mark.asyncio
async def test_restore_sql_sqlite_execution():
    sql = b"""-- SINO AI dump
    CREATE TABLE IF NOT EXISTS test_restore_t (id INT, val TEXT);
    INSERT INTO test_restore_t VALUES (1, 'sino_test');
    """
    ok, msg, stats = await dbdump.restore_sql(sql)
    assert ok
    assert "MUVAFFAQIYATLI TIKLANDI" in msg
    assert stats["tables"] >= 1
    assert stats["inserts"] >= 1


@pytest.mark.asyncio
async def test_admin_signal_in_rejects_non_image_documents():
    filt = AdminSignalIn()
    msg = MagicMock()
    msg.from_user.id = 12345
    msg.text = ""
    msg.caption = "⏰ AVTO-ZAXIRA sino_db_20261026_1804.sql"
    msg.photo = None

    # SQL fayl keldi:
    doc = MagicMock()
    doc.file_name = "sino_db_20261026_1804.sql"
    doc.mime_type = "application/sql"
    msg.document = doc

    # FORWARD qilingan bo'lsa ham rad etilishi SHART!
    with patch("app.bot.handlers.channels._is_admin", return_value=True), \
         patch("app.bot.handlers.channels._is_forward", return_value=True):
        res = await filt(msg)
        assert res is False, "Forward qilingan SQL fayl signal deb hisoblanmasligi SHART!"


@pytest.mark.asyncio
async def test_admin_signal_in_accepts_image_documents():
    filt = AdminSignalIn()
    msg = MagicMock()
    msg.from_user.id = 12345
    msg.text = ""
    msg.caption = "Buy Gold 4010-4015"
    msg.photo = None
    
    doc = MagicMock()
    doc.file_name = "chart.png"
    doc.mime_type = "image/png"
    msg.document = doc
    
    with patch("app.bot.handlers.channels._is_admin", return_value=True), \
         patch("app.bot.handlers.channels._is_forward", return_value=False):
        res = await filt(msg)
        assert res is True, "Rasm bo'lgan document qabul qilinishi kerak"
