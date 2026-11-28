"""v116: tez tik (2 s) + zona-qaytish + NORM-SAFE yopish + /narx.

  1) risk.norm_safe_targets: Lot1 — 1-chi TP, Lot2 — 2-chi TP (1 ta bo'lsa
     ikkalasi ham o'sha TP).
  2) fast_tick_once: WAIT signal entry_tick ga ketadi (jonli narx bilan),
     faol signal live_tick(df=None) ga — sham kutilmaydi.
  3) zone_hit semantikasi: narx zonaga KIRGANDA fill (v116 zona qaytadi).
  4) price_now.format_price_card: narx, manba, yosh va izoh matnda.
"""
import asyncio
import os
import sys
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.engine.risk import (norm_safe_targets, tp_at_index,  # noqa: E402
                             tps_of_signal)
from app.engine.entry import zone_hit, is_waiting  # noqa: E402
from app.services import fast_tick, price_now  # noqa: E402


def _sig(entry=4131.5, direction="BUY", tps_extra="", tp1=0.0, tp2=0.0, tp3=0.0):
    return NS(entry=entry, direction=direction, tps_extra=tps_extra,
              tp1=tp1, tp2=tp2, tp3=tp3)


# ------------------------------------------------------- norm-safe maqsadlar
def test_norm_safe_three_tps():
    s = _sig(tps_extra="[4142.0, 4148.0, 4153.0]")
    assert tps_of_signal(s) == [4142.0, 4148.0, 4153.0]
    assert norm_safe_targets(s) == (4142.0, 4148.0)
    assert tp_at_index(s, 0) == 4142.0 and tp_at_index(s, 1) == 4148.0
    assert tp_at_index(s, 5) == 4153.0          # oxirgiga qadaladi


def test_norm_safe_single_tp():
    s = _sig(tp1=4142.0)                        # tps_extra yo'q
    assert norm_safe_targets(s) == (4142.0, 4142.0)


def test_norm_safe_r345_bare():
    """BARE (10 pip SL) R345: Lot1 +3R, Lot2 +4R — user so'ragan sxema."""
    s = _sig(entry=4126.84, tps_extra="[4129.84, 4130.84, 4131.84]")
    t1, t2 = norm_safe_targets(s)
    assert abs(t1 - 4129.84) < 1e-9 and abs(t2 - 4130.84) < 1e-9


def test_norm_safe_empty():
    assert norm_safe_targets(_sig()) == (0.0, 0.0)


# ------------------------------------------------------- zona semantikasi
def test_zone_hit_waits_for_price_in_zone():
    # v128 (USER): fill endi ZONA O'RTASI (mid) — joriy narx emas;
    # trigger: narx zona ichida mid ga yetishi (BUY px<=mid, SELL px>=mid).
    ok, fill = zone_hit("BUY", 4129.0, 4134.0, 4129.99)   # mid 4131.5 ga yetdi
    assert ok and abs(fill - 4131.5) < 1e-9
    ok1b, _ = zone_hit("BUY", 4129.0, 4134.0, 4133.99)    # mid dan YUQORI — kutadi
    assert not ok1b
    ok2, _ = zone_hit("BUY", 4129.0, 4134.0, 4135.0)     # zona ustida — BUYIRMAYDI
    assert not ok2
    ok3, _ = zone_hit("SELL", 4188.0, 4191.0, 4187.5)    # zona ostida — SELL YO'Q
    assert not ok3
    # v127 (USER): SELL zonasi USTIDA (4192 > hi 4191) — v126gacha "hit"
    # edi, endi QATTIQ: zona o'tib ketgan bo'lsa KIRILMAYDI (aytilgan
    # zonadan boshqacha kirish taqiqlandi).
    ok4, fill4 = zone_hit("SELL", 4188.0, 4191.0, 4192.0)
    assert not ok4 and fill4 == 0.0
    # BUY zonasi ostida (gap-down bo'yicha) ham KIRILMAYDI (v127):
    ok5, fill5 = zone_hit("BUY", 4129.0, 4134.0, 4128.0)
    assert not ok5 and fill5 == 0.0
    # v128 SELL mid trigger: mid=4189.5; px 4190 zona ichida va mid dan yuqori
    ok6, fill6 = zone_hit("SELL", 4188.0, 4191.0, 4190.0)
    assert ok6 and abs(fill6 - 4189.5) < 1e-9


# ------------------------------------------------------- tez tik
class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def commit(self):
        return None


def _sf():
    return _FakeSession()


def test_fast_tick_once_waiting_and_active():
    calls = {"entry": [], "live": []}

    class FakeTracker:
        async def entry_tick(self, session, sig, price, notifier=None):
            calls["entry"].append((getattr(sig, "id", None), price))
            return "filled"

        async def live_tick(self, session, sig, price, df=None, notifier=None):
            calls["live"].append((getattr(sig, "id", None), price, df))
            return True

    sig_wait = NS(id=1, symbol="XAUUSDT", entry_status="WAIT",
                  entry_mode="SIGNAL", entry_low=4129.0, entry_high=4134.0)
    sig_open = NS(id=2, symbol="XAUUSDT", entry_status="FILLED",
                  entry_mode="MARKET", is_active=True)

    async def loader(session):
        return [sig_wait, sig_open]

    async def px(sym):
        return 4133.99

    assert is_waiting(sig_wait)
    assert not is_waiting(sig_open)

    res = asyncio.run(fast_tick.fast_tick_once(
        session_factory=_sf, signals_loader=loader, price_fn=px,
        tracker=FakeTracker()))
    assert res["checked"] == 2 and res["filled"] == 1
    assert calls["entry"] == [(1, 4133.99)]
    assert calls["live"] and calls["live"][0][2] is None    # df=None — tez


def test_fast_tick_once_idle():
    async def loader(session):
        return []

    async def px(sym):
        return 0.0

    res = asyncio.run(fast_tick.fast_tick_once(
        session_factory=_sf, signals_loader=loader, price_fn=px,
        tracker=NS()))
    assert res["checked"] == 0 and res["filled"] == 0


def test_fast_tick_price_error_skips():
    class FakeTracker:
        async def entry_tick(self, *a, **k):
            raise AssertionError("narx yo'q — chaqirilmasligi kerak")

        async def live_tick(self, *a, **k):
            raise AssertionError("narx yo'q — chaqirilmasligi kerak")

    sig = NS(id=9, symbol="XAUUSDT", entry_status="WAIT", entry_mode="SIGNAL",
             entry_low=4129.0, entry_high=4134.0)

    async def loader(session):
        return [sig]

    async def px(sym):
        raise RuntimeError("tarmoq xatosi")

    res = asyncio.run(fast_tick.fast_tick_once(
        session_factory=_sf, signals_loader=loader, price_fn=px,
        tracker=FakeTracker()))
    assert res["checked"] == 0


# ------------------------------------------------------- narx kartasi
def test_price_card_text():
    txt = price_now.format_price_card(
        "XAUUSDT", 4126.84, "MEXC index", 320, 4126.90, "tez tik", 2.0)
    assert "4,126.84" in txt and "MEXC index" in txt
    assert "320 ms" in txt and "2 s oldin" in txt
    assert "0.05" in txt and "MT5" in txt


def test_price_card_no_live():
    txt = price_now.format_price_card("XAUUSDT", None, "MEXC index", 0,
                                      None, "", None)
    assert "vaqtincha yo'q" in txt
