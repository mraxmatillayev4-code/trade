"""v125 testlari:

1) BOZOR YOPIQ gate (market_hours): shanba/yakshanba/dushanba-tong va kunlik
   tanaaffusda signal bloqqa tushadi; oddiy ish vaqtida o'tadi.
   (User: "bozor yopiq payti kelgan istalgan signal xabarlari bloklansin".)
2) channel_inbox: bozor yopiq payt signal qabul qilmaydi (dirq "market_closed").
3) _be_sl_target: TP1 tekkanda Lot2 stopi TP1 ga suriladi (user qoidasi
   SL→TP1; ilgari BE = kirish narxi edi). xavfsizlik: TP1 yo'q → entry (BE).
4) _broker_open: Lot1 ga TP=TP1, Lot2 ga TP=TP2 (ilgari 2 lotga ham OXIRGI TP
   yozilar edi — xato; endi per-lot).
5) MODIFY navbat: MetaApi exec "noma'lum amal" demaydi — modify_sl chaqiriladi.
6) Tracked auto-yopilishda (VAQT TUGADI kabi narxiy sabablar) broker navbatiga
   CLOSE tushadi (ilgari real pozitsiya yopilmasdan qolar edi).
"""
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest

TZT = timezone(timedelta(hours=5))


# -------------------------------------------------- 1) bozor vaqti gate
def _tst(y, m, d, hh, mm=0):
    from app.services.market_hours import gold_market_open
    return gold_market_open(datetime(y, m, d, hh, mm, tzinfo=TZT))


def test_market_hours_dam_olish_yopiq():
    # shanba kunduzi — yopiq
    ok, why = _tst(2026, 10, 24, 12, 49)     # 2026-10-24 = shanba
    assert not ok and "shanba" in why
    # yakshanba — yopiq
    ok2, why2 = _tst(2026, 10, 25, 18, 0)
    assert not ok2 and "yakshanba" in why2
    # dushanba tong 02:00 — hali ochilmagan
    ok3 = _tst(2026, 10, 26, 2, 0)[0]
    assert not ok3


def test_market_hours_ish_vaqti_ochiq():
    # juma 21:35 (foydalanuvchi signal yuborib test qilgan payt) — ochiq
    assert _tst(2026, 10, 23, 21, 35)[0]
    # seshanba kunduz — ochiq
    assert _tst(2026, 10, 20, 14, 0)[0]
    # dushanba 05:00 — ochiq
    assert _tst(2026, 10, 26, 5, 0)[0]


def test_market_hours_kunlik_tanaaffus():
    # 2026-10 = AQSH EDT mavsumi (21:00-22:00 UTC = 02:00-03:00 Toshkent)
    ok, why = _tst(2026, 10, 21, 2, 30)      # chorshanba 02:30 — tanaaffus
    assert not ok and "tanaaffus" in why
    assert _tst(2026, 10, 21, 3, 30)[0]      # 03:30 — ochiq
    # EST mavsum (2027-yan): 03:00-04:00 Toshkent
    ok2 = _tst(2027, 1, 13, 3, 30)[0]
    assert not ok2
    assert _tst(2027, 1, 13, 4, 30)[0]


# --------------------------------------- 2) channel_inbox — bozor yopiq gate
@pytest.mark.asyncio
async def test_inbox_signal_bozor_yopiqda_bloklanadi(monkeypatch):
    from app.services import channel_inbox as CI
    # in-memory SystemLog stolina o'xshatamiz — baza kerak: load_cfg/... yo'q u yerda,
    # faqat record_read/match_channel async chaqiriladi — ularni stub qilamiz.
    calls = {"save": 0}

    async def _nosave(session, rec, parsed, settings, src, meta=None, **kw):
        calls["save"] += 1
        return "ok"

    async def _nop(*a, **kw):
        return None

    monkeypatch.setattr(CI, "_save", _nosave)
    monkeypatch.setattr(CI, "record_read", _nop)
    monkeypatch.setattr(CI, "match_channel", _nop)
    monkeypatch.setattr(CI, "_diag", _nop)
    monkeypatch.setattr(CI, "_diag_skip", _nop)
    monkeypatch.setattr(CI, "tell_admin", _nop)
    monkeypatch.setattr(CI, "bind_chat_id", _nop)

    # bozorni yopiq deb soxta qilamiz
    monkeypatch.setattr("app.services.market_hours.gold_market_open",
                        lambda now=None: (False, "yakshanba"))

    # DB ga urg'ash — fakeasync_session_factory
    class _S:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def execute(self, *a, **kw):
            raise RuntimeError("db yo'q")

        async def scalar(self, *a, **kw):
            return None

        async def commit(self):
            return None

    monkeypatch.setattr(CI, "async_session_factory", lambda: _S())
    res = await CI._run(
        ch={"username": "testchan", "chat_id": 1001},
        text="Xauusd sell now 4158-4162\nMinimal risk! Stop 4167",
        image_bytes=None, msg_id=9001, chat_id=1001, title="T",
        username="testchan", grouped_id=None, reply_to=None,
        require_listed=False,
    )
    assert res == "market_closed"
    assert calls["save"] == 0      # signal saqlanmadi — bloklandi!


# -------------------------------------------------- 3) SL TP1 ga sudriladi
def test_be_sl_target_tp1_ga():
    from app.services.tracker import _be_sl_target
    # BUY: entry 4000, TP1 4010 → SL2 = 4010 (TP1)
    assert _be_sl_target(NS(entry=4000.0, tp1=4010.0, direction="BUY",
                            tps_extra="")) == 4010.0
    # SELL: entry 4000, TP1 3990 → SL2 = 3990 (TP1)
    assert _be_sl_target(NS(entry=4000.0, tp1=3990.0, direction="SELL",
                            tps_extra="")) == 3990.0
    # tp1 yo'q → kirish narxi (BE, eski usulda)
    assert _be_sl_target(NS(entry=4000.0, tp1=0.0, direction="BUY",
                            tps_extra="")) == 4000.0
    # teskari yo'nalishda TP1 (nosoz ma'lumot) — xavfsizlik: BE
    assert _be_sl_target(NS(entry=4000.0, tp1=3990.0, direction="BUY",
                            tps_extra="")) == 4000.0


# ------------------------------- 4) _broker_open — Lot1 TP1 / Lot2 TP2
@pytest.mark.asyncio
async def test_broker_open_per_lot_tp(monkeypatch, async_session):
    from app.paper_trading import engine as pen
    from app.services import broker as brk

    cfg = await brk.save_cfg_metaapi(async_session, kind="demo",
                                     api_token="tok", account_id="ACC",
                                     user_id=7)
    await async_session.commit()

    got = []

    async def _enq(session, action, **fields):
        got.append((action, fields))
        return len(got)

    monkeypatch.setattr(brk, "enqueue", _enq)

    eng = pen.PaperEngine()
    mon1 = NS(symbol="XAUUSDT", direction="BUY", qty_total=50.0, stage=0,
              sl=3990.0, tp1=4010.0, tp3=4030.0, settings=None)
    mon2 = NS(symbol="XAUUSDT", direction="BUY", qty_total=50.0, stage=10,
              sl=3990.0, tp1=4010.0, tp3=4030.0, settings=None)

    async def _op(session, user_id=None, signal_id=None, **kw):
        return [mon1, mon2]

    monkeypatch.setattr(eng, "open_positions", _op)

    sig = NS(id=77, symbol="XAUUSDT", direction="BUY", tp1=4010.0,
             tp2=4020.0, tp3=4030.0, tps_extra="[4010.0, 4020.0, 4030.0]")
    await eng._broker_open(async_session, sig, [7])

    assert len(got) == 2
    l1 = [g for g in got if g[1]["comment"] == "SINO Lot1"][0][1]
    l2 = [g for g in got if g[1]["comment"] == "SINO Lot2"][0][1]
    assert l1["tp"] == 4010.0       # Lot1 → TP1 (XATO tuzatilgan: ilgari 4030 edi)
    assert l2["tp"] == 4020.0       # Lot2 → TP2 (ilgari 4030 edi)
    assert l1["sl"] == l2["sl"] == 3990.0


# ------------------------------- 5) MODIFY navbat metaapi exec orqali
class _FakeBridge125:
    opened, closed, modified = [], [], []

    def __init__(self, token, account_id, timeout=25.0):
        pass

    async def open_market(self, symbol, side, lot, sl=0.0, tp=0.0, comment=""):
        self.opened.append((symbol, side, lot, sl, tp, comment))
        return {"ok": True, "ticket": 555, "price": 4123.45}

    async def close_by_comment(self, symbol, comment_prefix="SINO", lot=0.0, price=0.0):
        self.closed.append((symbol, comment_prefix, lot, price))
        return {"ok": True, "closed": 1, "price": 4123.50}

    async def modify_sl(self, symbol, comment_prefix="SINO", lot=0.0, sl=0.0, tp=0.0):
        self.modified.append((symbol, comment_prefix, lot, sl, tp))
        return {"ok": True, "positionId": "p1", "sl": sl}

    async def account_info(self):
        return {"balance": 1000.0, "currency": "USD"}

    async def positions(self):
        return []


@pytest.mark.asyncio
async def test_metaapi_exec_modify_operates(async_session, monkeypatch):
    from app.services import broker as brk
    from app.services import broker_metaapi_exec as _BMX
    monkeypatch.setattr(_BMX, "MetaApiBridge", _FakeBridge125)
    await brk.save_cfg_metaapi(async_session, kind="demo",
                               api_token="tok9", account_id="ACC9", user_id=7)
    await async_session.commit()
    oid = await brk.enqueue(async_session, "MODIFY", symbol="XAUUSDT",
                            side="BUY", sl=4010.0, comment="SINO Lot2",
                            signal_id=88)
    await async_session.commit()
    _FakeBridge125.modified.clear()
    n = await _BMX.cycle_once(async_session)
    assert n == 1
    assert _FakeBridge125.modified == [("XAUUSDT", "SINO Lot2", 0.0, 4010.0, 0.0)]
    out = await brk._load_out(async_session)
    item = [i for i in out["items"] if i["id"] == oid][0]
    assert item["state"] == "done"


# ------------------------------- 6) tracker _fill → broker CLOSE navbatga
@pytest.mark.asyncio
async def test_tracker_fill_vaqt_tugaganda_broker_ga(monkeypatch, async_session):
    """VAQT TUGADI kabi vaqtiy sababli avto-yopilish — real broker navbatiga
    ham CLOSE tushadi. (SL/TP1/TP2 esa brokerning o'z buyurtmasi yopadi.)"""
    from app.services import tracker as TR
    from app.services import broker as brk

    await brk.save_cfg_metaapi(async_session, kind="demo",
                               api_token="tokx", account_id="ACCX", user_id=7)
    await async_session.commit()

    tr = TR.SignalTracker(paper_engine=NS(), settings=NS())

    async def _apply(session, pos, fill_price, portion, is_final,
                     exit_price_for_remaining=None, count_trade=True, reason=""):
        return 0.0

    tr._paper = NS(apply_fill=_apply)
    enq = []

    async def _enq(s, a, **kw):
        enq.append((a, kw))
        return len(enq)

    monkeypatch.setattr(brk, "enqueue", _enq)

    pos = NS(id=5, user_id=7, signal_id=99, symbol="XAUUSDT", direction="BUY",
             stage=10, qty_total=50.0)
    await tr._fill(async_session, pos, 4000.0, reason="VAQT TUGADI")
    assert enq and enq[0][0] == "CLOSE"
    assert enq[0][1]["comment"] == "SINO Lot2"
    assert enq[0][1]["signal_id"] == 99

    # SL sababli — navbatga TUSHMAYDI (brokerning o'z stop lossi bajaradi)
    enq.clear()
    await tr._fill(async_session, pos, 3985.0, reason="SL")
    assert enq == []


# ------------------------------- umumiy fixture (v119 dagidek in-memory)
@pytest.fixture
async def async_session():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

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
