"""v122: QAYTISH KUTILMOQDA (SIGNAL_UND) — narx SL dan o'tib ketgan signal.

Kelishuv (user): 1-a) kun oxirigacha kutadi, 2-a) masofa cheklovisiz,
3-ha) xabar kartasi yuboriladi.

Tekshiruvlar:
  1) zone_hit_reverse — teskari zona tekshiruvi (narx zona ichiga QAYTishi).
  2) _apply_entry_plan — _oshti115 bo'lsa bekor EMAS, SIGNAL_UND + WAIT.
  3) _toshkent_kun_oxiri — muddat keyingi yarim tun (Toshkent).
  4) plan_lines — SIGNAL_UND "kanal aytgan · qaytish rejimi" deb yoziladi.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.engine import entry as EN  # noqa: E402
from app.services import channel_inbox as CI  # noqa: E402


# ------------------------------------------------------- zona_hit_reverse
def test_reverse_buy_ichida():
    ok, fill = EN.zone_hit_reverse("BUY", 4178.0, 4183.0, 4180.5)
    assert ok and abs(fill - 4180.5) < 1e-9


def test_reverse_buy_zona_ustida_bosib_otdi():
    ok, fill = EN.zone_hit_reverse("BUY", 4178.0, 4183.0, 4185.0)
    assert ok and abs(fill - 4183.0) < 1e-9      # yuqori chegarada fill


def test_reverse_buy_hali_ostda_kutadi():
    ok, _ = EN.zone_hit_reverse("BUY", 4178.0, 4183.0, 4090.0)
    assert not ok


def test_reverse_sell_ichida_va_tagida():
    ok, fill = EN.zone_hit_reverse("SELL", 4158.0, 4162.0, 4160.0)
    assert ok and abs(fill - 4160.0) < 1e-9
    ok2, fill2 = EN.zone_hit_reverse("SELL", 4158.0, 4162.0, 4155.0)
    assert ok2 and abs(fill2 - 4158.0) < 1e-9    # pastki chegarada fill


def test_reverse_sell_hali_ustda_kutadi():
    ok, _ = EN.zone_hit_reverse("SELL", 4158.0, 4162.0, 4190.0)
    assert not ok


def test_reverse_nol_narx_xavfsiz():
    assert EN.zone_hit_reverse("BUY", 4178.0, 4183.0, 0.0) == (False, 0.0)
    assert EN.zone_hit_reverse("BUY", 0.0, 0.0, 4088.0) == (False, 0.0)


# ------------------------------------------------------- Toshkent kun oxiri
def test_toshkent_kun_oxiri_kelajakda():
    exp = CI._toshkent_kun_oxiri()
    assert exp.tzinfo is not None
    now = datetime.now(timezone.utc)
    assert exp > now
    # keyingi yarim tungacha — 0..24 soat ichida (+1 sek bufer)
    assert exp - now <= timedelta(hours=24, seconds=2)
    local = exp.astimezone(timezone(timedelta(hours=5)))
    assert (local.hour, local.minute, local.second) == (0, 0, 0)


# ------------------------------------------------------- _apply_entry_plan
class _FakeSession:
    async def commit(self):
        return None

    async def execute(self, *a, **kw):
        raise RuntimeError("db yo'q")


def _sig_und(**kw):
    d = dict(symbol="XAUUSDT", direction="BUY", quality_mode="CHANNEL",
             entry=4180.5, entry_low=None, entry_high=None,
             sl=4175.0, tp1=4193.0, tp2=4198.0, tp3=4198.0,
             entry_status="", entry_mode="", entry_note="",
             entry_expires_at=None, entry_skip="", entry_tps_src="CHANNEL",
             status="ACTIVE", is_active=True, id=777, close_reason="")
    d.update(kw)
    return NS(**d)


import pytest  # noqa: E402


@pytest.mark.asyncio
async def test_apply_plan_oshti_emas_qaytish_kutadi(monkeypatch):
    """BUG holati: BUY zona 4178-4183, SL 4175, joriy narx 4088.
    v122: bekor EMAS — SIGNAL_UND + WAIT, kun oxirigacha."""
    monkeypatch.setattr(CI, "_last_px", lambda s: 4088.0)

    async def _nolive(sym):
        return 0.0
    import app.services.live_state as ls
    monkeypatch.setattr(ls, "get_price", _nolive)

    parsed = NS(entry_src="TEXT", zone_low=4178.0, zone_high=4183.0,
                entry=4180.5, direction="BUY")
    signal = _sig_und()
    settings = NS(channel_expiry_minutes=240)
    st = await CI._apply_entry_plan(_FakeSession(), signal, parsed, settings)
    assert st == "wait"
    assert signal.entry_mode == "SIGNAL_UND"
    assert signal.entry_status == "WAIT"
    lo, hi = sorted((4178.0, 4183.0))
    assert signal.entry_low == lo and signal.entry_high == hi
    assert signal.entry_expires_at is not None
    assert signal.entry_expires_at > datetime.now(timezone.utc)
    # v128: yagona izoh-shablon — "SL o'tgan; zona qaytganda kiramiz ..."
    note = signal.entry_note or ""
    assert "SL o'tgan" in note and "kun oxirigacha" in note
    # signal FAOL qoladi — bekor qilinmagan
    assert signal.is_active is True


@pytest.mark.asyncio
async def test_apply_plan_zonada_darhol_kiradi(monkeypatch):
    """Narx zonaning ichida bo'lsa v122 devrey yangi yo'lga kirmaydi."""
    monkeypatch.setattr(CI, "_last_px", lambda s: 4180.0)
    parsed = NS(entry_src="TEXT", zone_low=4178.0, zone_high=4183.0,
                entry=4180.5, direction="BUY")
    signal = _sig_und()
    settings = NS(channel_expiry_minutes=240)
    st = await CI._apply_entry_plan(_FakeSession(), signal, parsed, settings)
    assert st == "filled"
    assert signal.entry_mode == "SIGNAL"
    assert signal.entry_status == "FILLED"


@pytest.mark.asyncio
async def test_apply_plan_sell_oshgan_qaytish(monkeypatch):
    """SELL: narx SL dan yuqorida — qaytish rejimi kutiladi."""
    monkeypatch.setattr(CI, "_last_px", lambda s: 4185.0)
    parsed = NS(entry_src="TEXT", zone_low=4178.0, zone_high=None,
                entry=4179.0, direction="SELL")
    signal = _sig_und(direction="SELL", entry=4179.0, sl=4183.0,
                      tp1=4160.0, tp2=4155.0)
    settings = NS(channel_expiry_minutes=240)
    st = await CI._apply_entry_plan(_FakeSession(), signal, parsed, settings)
    assert st == "wait"
    assert signal.entry_mode == "SIGNAL_UND"


# ------------------------------------------------------- karta matni
def test_plan_lines_qaytish_rejimi_yozuvi():
    sig = NS(entry_mode="SIGNAL_UND", entry_status="WAIT",
             entry_note="narx zona ostida (SL chapda) — zona qaytganda kiramiz",
             entry_low=4178.0, entry_high=4183.0,
             entry_expires_at=datetime.now(timezone.utc) + timedelta(hours=5))
    lines = EN.plan_lines(sig)
    txt = "\n".join(lines)
    assert "KIRISH KUTILMOQDA" in txt
    assert "kanal aytgan" in txt
    assert "qaytish rejimi" in txt


def test_plan_lines_oddiy_signal_rejimi_ozgarmagan():
    sig = NS(entry_mode="SIGNAL", entry_status="WAIT",
             entry_note="kanal aytgan zona", entry_low=4150.0, entry_high=4155.0,
             entry_expires_at=datetime.now(timezone.utc) + timedelta(minutes=20))
    txt = "\n".join(EN.plan_lines(sig))
    assert "kanal aytgan" in txt
    assert "qaytish rejimi" not in txt
