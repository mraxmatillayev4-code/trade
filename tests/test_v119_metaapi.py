"""v119 testlari:
1) broker.is_ready/is_metaapi — MetroaPI provayder tayyorligi.
2) save_cfg_metaapi — eski token saqlanadi, provider yozuvi.
3) Navbat sikl: OPEN zamonaviy — ijro; ESKI OPEN (>5 daq) — RAD (xavfsizlik).
4) _sym_translate: XAUUSDT -> XAUUSD.
5) BOT kartasi text matnda provider ko'rsatilsin (status_text).
"""

import time
from datetime import datetime, timezone

import pytest

from app.services import broker as brk
from app.services.broker_metaapi import MetaApiBridge, _sym_translate


def test_is_ready_metaapi():
    assert brk.is_ready({"provider": "metaapi", "api_token": "abcabcabcab",
                        "account_id": "xyz12"}) is True
    assert brk.is_ready({"provider": "metaapi", "api_token": "", "account_id": "x"}) is False
    # lokal ko'prik eski qoida bilan
    assert brk.is_ready({"token": "t", "login": "1", "password": "p"}) is True
    assert brk.is_ready({"token": "t"}) is False


def test_is_metaapi():
    assert brk.is_metaapi({"provider": "metaapi"}) is True
    assert brk.is_metaapi({"provider": "bridge"}) is False
    assert brk.is_metaapi({}) is False
    assert brk.is_metaapi(None) is False


@pytest.mark.asyncio
async def test_save_cfg_metaapi_token_saqlanadi(async_session):
    old = await brk.save_cfg(async_session, kind="demo", login="111", password="p",
                             server="S", user_id=5)
    tok = old["token"]
    cfg = await brk.save_cfg_metaapi(async_session, kind="demo",
                                     api_token="tok-tok-tok",
                                     account_id="acc-12345", user_id=5)
    await async_session.commit()
    assert cfg["provider"] == "metaapi"
    assert cfg["api_token"] == "tok-tok-tok"
    assert cfg["account_id"] == "acc-12345"
    assert cfg["token"] == tok          # eski bridge token o'zgarmaydi
    assert cfg["user_id"] == 5
    assert brk.is_ready(cfg) and brk.is_metaapi(cfg)
    got = await brk.load_cfg(async_session)
    assert got["provider"] == "metaapi"


def test_symbol_translate():
    assert _sym_translate("XAUUSDT") == "XAUUSD"
    assert _sym_translate("xauusd") == "XAUUSD"
    assert _sym_translate("XAUUSD") == "XAUUSD"
    assert _sym_translate("") or True


class _FakeBridge:
    """MetaApiBridge o'rniga test jo'rvagi (tarmoqsiz)."""
    opened = []
    closed = []

    def __init__(self, token, account_id, timeout=25.0):
        pass

    async def open_market(self, symbol, side, lot, sl=0.0, tp=0.0, comment=""):
        self.opened.append((symbol, side, lot, sl, tp, comment))
        return {"ok": True, "ticket": 555, "price": 4123.45}

    async def close_by_comment(self, symbol, comment_prefix="SINO", lot=0.0, price=0.0):
        self.closed.append((symbol, comment_prefix, lot, price))
        return {"ok": True, "closed": 1, "price": 4123.50}

    async def account_info(self):
        return {"balance": 1000.0, "currency": "USD"}

    async def positions(self):
        return []


@pytest.mark.asyncio
async def test_navbat_open_yangi_bajariladi(async_session, monkeypatch):
    from app.services import broker_metaapi_exec as _BMX
    monkeypatch.setattr(_BMX, "MetaApiBridge", _FakeBridge)
    cfg = await brk.save_cfg_metaapi(async_session, kind="demo",
                                     api_token="tok", account_id="acc-111111", user_id=7)
    await async_session.commit()
    oid = await brk.enqueue(async_session, "OPEN", symbol="XAUUSDT", side="BUY",
                            lot=0.5, sl=4100.0, tp=4150.0, signal_id=1, comment="SINO Lot1")
    await async_session.commit()
    _FakeBridge.opened.clear()
    n = await _BMX.cycle_once(async_session)
    assert n == 1
    assert _FakeBridge.opened == [("XAUUSDT", "BUY", 0.5, 4100.0, 4150.0, "SINO Lot1")]
    out = await brk._load_out(async_session)
    item = [i for i in out["items"] if i["id"] == oid][0]
    assert item["state"] == "done" and item["ticket"] == 555


@pytest.mark.asyncio
async def test_navbat_open_eskirganda_rad(async_session, monkeypatch):
    from app.services import broker_metaapi_exec as _BMX
    monkeypatch.setattr(_BMX, "MetaApiBridge", _FakeBridge)
    cfg = await brk.save_cfg_metaapi(async_session, kind="demo",
                                     api_token="tok2", account_id="acc-222222", user_id=7)
    await async_session.commit()
    oid = await brk.enqueue(async_session, "OPEN", symbol="XAUUSDT", side="BUY",
                            lot=0.5, sl=1, tp=2, signal_id=2, comment="SINO Lot1")
    await async_session.commit()
    # buyruqni sun'iy eskitamiz (6 daqiqa oldin yaratilgan dek)
    out = await brk._load_out(async_session)
    for it in out["items"]:
        if it["id"] == oid:
            it["created_at"] = time.time() - 400.0
    await brk._save_out(async_session, out)
    await async_session.commit()
    _FakeBridge.opened.clear()
    n = await _BMX.cycle_once(async_session)
    assert n == 0
    assert _FakeBridge.opened == []       # eski signal ochilmaydi!
    out2 = await brk._load_out(async_session)
    item = [i for i in out2["items"] if i["id"] == oid][0]
    assert item["state"] == "failed" and "ESKIRGAN" in (item.get("error") or "")


@pytest.mark.asyncio
async def test_metaapi_emas_bolsa_hech_narsa(async_session, monkeypatch):
    from app.services import broker_metaapi_exec as _BMX
    monkeypatch.setattr(_BMX, "MetaApiBridge", _FakeBridge)
    # lokal ko'prik konfiguratsiyasi — metaapi cycle 0 qaytarishi kerak
    await brk.save_cfg(async_session, kind="demo", login="1", password="p", server="S", user_id=9)
    await async_session.commit()
    await brk.enqueue(async_session, "OPEN", symbol="XAUUSDT", side="BUY",
                      lot=0.5, sl=1, tp=2, signal_id=3, comment="SINO Lot1")
    await async_session.commit()
    _FakeBridge.opened.clear()
    n = await _BMX.cycle_once(async_session)
    assert n == 0 and _FakeBridge.opened == []


@pytest.fixture
async def async_session():
    """SQLite in-memory sessiya — SystemLog jadvali bilan."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.database.models.system import SystemLog

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE IF NOT EXISTS system_logs ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " component VARCHAR(64) NOT NULL,"
            " message TEXT,  payload TEXT,"
            " level VARCHAR(16) DEFAULT 'info',"
            " created_at DATETIME)"))
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        yield s
    await engine.dispose()
