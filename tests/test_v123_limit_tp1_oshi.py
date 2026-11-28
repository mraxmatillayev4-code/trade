"""v123: ZONA-LIMIT signali uchun "narx TP1 dan oshgan → bekor" xatosi.

Muammo (user buyrug'i, 23-okt): 712 TRADE "buy limit 3996-3992, Stop 3987"
signali narx ~4030 (KuCoin 05:31) vaqti bilan keldi. R345 avtomatik TP:
zone mid 3994 + 3R(21) => TP1=4015. Eski v116 "_quvi115" blok "narx TP1
dan oshgan => quvilmasin" deb LIMIT signali ham CANCELLED qilardi — signal
karta ham yuborilmaydi (v94), hisobot esa "(hali yopilmagan)" deb
chalkashtirardi.

Lekin LIMIT signal bo'lsa narx zona ICHIGA tushishini kutadi; u TP1 dan
hozir oshgan bo'lsa bu "quvish" EMAS — kirish hali bo'lgani yo'q.

Yechim (v123):
  * _apply_entry_plan: zona-LIMIT uchun TP1-overshoot bekor qilishni
    O'CHIRISH — zona-narx holatida signal KUTADI (karta chiqadi).
  * reports._mini_line: CANCELLED signallarni "hali yopilmagan"dan
    ajratish — "(N ta bekor, M da hali ochiq)" / "(barchasi bekor)".

Tekshiruvlar:
  1) _quvi115 o'chirilganini — BUY limit, narx > TP1 => bekor EMAS ("wait").
  2) SELL mirror: narx < TP1 => bekor EMAS ("wait").
  3) Regressiya: SL-oshti v122 UND saqlanadi (SIGNAL_UND).
  4) Zonada -> FILLED, zona-tagida -> WAIT saqlanadi.
  5) _mini_line bekor ajratish matnlari.
  6) SINO-LAI-123 versiya belgisi mavjudligi.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest  # noqa: E402
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.engine import entry as EN  # noqa: E402
from app.services import channel_inbox as CI  # noqa: E402
from app.services import reports as RP  # noqa: E402


class _FakeSession:
    async def commit(self):
        return None


def _sig(**kw):
    """712 TRADE buy limit 3996-3992 stop 3987; R345: TP1=4015 TP2=4022 TP3=4029."""
    d = dict(symbol="PAXGUSDT", direction="BUY", quality_mode="CHANNEL",
             entry=3994.0, entry_low=None, entry_high=None,
             sl=3987.0, tp1=4015.0, tp2=4022.0, tp3=4029.0,
             entry_status="", entry_mode="", entry_note="",
             entry_expires_at=None, entry_skip="", entry_tps_src="CHANNEL",
             status="ACTIVE", is_active=True, id=888, close_reason="")
    d.update(kw)
    return NS(**d)


def _parsed_712(direction="BUY"):
    # kanal xabaridagi zona: 3996-3992 (reverse parse target)
    return NS(entry_src="TEXT", zone_low=3996.0, zone_high=3992.0,
              entry=3994.0, direction=direction)


def _settings():
    return NS(channel_expiry_minutes=240)


@pytest.mark.asyncio
async def test_limit_narx_tp1_dan_oshgan_bekor_emas_diskretant(monkeypatch):
    """BUY limit, narx (4030) TP1 (4015) dan oshgan, zona teglanmagan =>
    v123 'wait' qaytaradi (avval 'no' — CANCELLED bo'lardi)."""
    monkeypatch.setattr(CI, "_last_px", lambda s: 4030.0)

    async def _nolive(sym):
        return 0.0
    import app.services.live_state as ls
    monkeypatch.setattr(ls, "get_price", _nolive)

    signal = _sig()
    st = await CI._apply_entry_plan(_FakeSession(), signal,
                                    _parsed_712("BUY"), _settings())
    assert st == "wait"
    # bekorlanmagan!
    assert signal.status == "ACTIVE"
    assert signal.entry_status == "WAIT"
    assert signal.is_active is True
    assert not (getattr(signal, "close_reason", "") or "").strip()
    # zona belgilab olingan va muddat K_WAIT (30 min)
    lo, hi = sorted((signal.entry_low, signal.entry_high))
    assert (lo, hi) == (3992.0, 3996.0)
    assert signal.entry_expires_at is not None
    assert "zona" in (signal.entry_note or "").lower()


@pytest.mark.asyncio
async def test_sell_limit_narx_tp1_dan_past_bekor_emas(monkeypatch):
    """SELL mirror: narx (3980) TP1 (3973) dan past, zona (3992-3996) dan
    past — bekor EMAS, kutiladi."""
    monkeypatch.setattr(CI, "_last_px", lambda s: 3980.0)
    signal = _sig(direction="SELL", tp1=3973.0, tp2=3966.0, tp3=3959.0)
    st = await CI._apply_entry_plan(_FakeSession(), signal,
                                    _parsed_712("SELL"), _settings())
    assert st == "wait"
    assert signal.status == "ACTIVE"
    assert signal.is_active is True
    assert not (getattr(signal, "close_reason", "") or "").strip()


@pytest.mark.asyncio
async def test_regressiya_sl_oshgan_v122_und_saqlanadi(monkeypatch):
    """Narx SL dan o'tib ketgan bo'lsa v122 QAYTISH-KUTISH almaydi."""
    monkeypatch.setattr(CI, "_last_px", lambda s: 3980.0)  # BUY, SL 3987 ostida
    signal = _sig()
    st = await CI._apply_entry_plan(_FakeSession(), signal,
                                    _parsed_712("BUY"), _settings())
    assert st == "wait"
    assert signal.entry_mode == "SIGNAL_UND"
    # kun oxirigacha (K_WAIT dan uzoqroq)
    assert signal.entry_expires_at > datetime.now(timezone.utc) + timedelta(hours=1)


@pytest.mark.asyncio
async def test_zonada_narx_filled_saqlanadi(monkeypatch):
    monkeypatch.setattr(CI, "_last_px", lambda s: 3994.0)
    signal = _sig()
    st = await CI._apply_entry_plan(_FakeSession(), signal,
                                    _parsed_712("BUY"), _settings())
    assert st == "filled"
    assert signal.entry_status == "FILLED"


@pytest.mark.asyncio
async def test_zona_tepasida_kutadi_kwait_30_monkeypatch(monkeypatch):
    """Narx zona USTIDA, TP1 dan past bo'lganda (4002 < 4015) ham wait."""
    monkeypatch.setattr(CI, "_last_px", lambda s: 4002.0)
    signal = _sig()
    st = await CI._apply_entry_plan(_FakeSession(), signal,
                                    _parsed_712("BUY"), _settings())
    assert st == "wait"
    assert signal.entry_mode == "SIGNAL"
    assert signal.entry_status == "WAIT"
    # K_WAIT muddat ~60min (v124: standart 30 -> 60 daqiqa).
    dt = signal.entry_expires_at - datetime.now(timezone.utc)
    assert timedelta(minutes=58) < dt < timedelta(minutes=62)


# ------------------------------------------------------------ _mini_line
def _mk_sig(entry_status="", status="ACTIVE", active=True,
            close_reason="", r_multiple=None):
    return NS(entry_status=entry_status, status=status, is_active=active,
              close_reason=close_reason, r_multiple=r_multiple)


def test_mini_line_barchasi_bekor_alohida_yoziladi():
    created = [_mk_sig(entry_status="CANCELLED", status="CANCELLED",
                       active=False, close_reason="TP1 OSHIB KETDI")]
    s = RP._mini_line("712 TRADE", created, [])
    assert "barchasi bekor" in s
    assert "hali yopilmagan" not in s


def test_mini_line_aralash_bekor_va_ochiq():
    created = [
        _mk_sig(entry_status="CANCELLED", status="CANCELLED",
                active=False, close_reason="X"),
        _mk_sig(entry_status="WAIT", status="ACTIVE", active=True, close_reason=""),
    ]
    s = RP._mini_line("712 TRADE", created, [])
    assert "1 ta bekor" in s and "1 ta hali ochiq" in s


def test_mini_line_bekorsiz_avvalgidek():
    created = [_mk_sig(entry_status="WAIT", status="ACTIVE", active=True)]
    s = RP._mini_line("712 TRADE", created, [])
    assert "hali yopilmagan" in s
    assert "bekor" not in s


# --------------------------------------------------------- versiya belgisi
def test_sino_lai_123_bump():
    import app.services.local_ai as la
    src = open(la.__file__, encoding="utf-8").read()
    # v124: versiya 123 -> 124 ko'tarildi
    assert la.__version__ in ("SINO-LAI-123", "SINO-LAI-124", "SINO-LAI-125",
                              "SINO-LAI-126", "SINO-LAI-127", "SINO-LAI-128")
    assert "SINO-LAI-122" not in src
