"""v124: NOW+ZONA darhol kirish (v115 uslubiga qaytarish) + 60 daq kutish +
jim-bekor taqiqi.

Foydalanuvchi shikoyati (23-okt): "signal berildi o'sha berilgan joydan yurib
berdiku, bot esa kartada 'KIRISH KUTILMOQDA' deb sobit qoldi, jim bekor bo'ldi,
30 daqiqani 1 soat qil".

Kod real-zanjir (dalillangan):
  1) v116 da "now+zona" signali zona kutilishiga o'tgan edi — tez signallar
     o'tib ketardi. v124: kanal "NOW" yozgan bo'lsa zona O'RTASIDAN darhol
     kiriladi (v115 uslubi).
  2) OCR/parse skala siljishi himoyasi: zona va joriy narx 1.5% dan ortiq
     farqda bo'lsa — kirilmaydi, DIQQAT-izoh bilan kutiladi.
  3) WAIT signallari bekor bo'lganda hech narsa yozilmaydi edi (v94: faqat
     kartasiz bekorlar uchun edi) — kartasi bo'lib WAIT bo'lgan signal
     eski kartasini sobit "KUTILMOQDA" holda qoldirardi.
     v124: bekor bo'lganda aniq xabar yuboriladi.
  4) K_WAIT standarti 30 → 60 daqiqa.

Tekshiruvlar:
  A) DEFAULT_WAIT == 60, WAIT_CHOICES da 60 bor.
  B) entry_settings.defaults() K_WAIT == 60; migratsiya matni mavjud.
  C) _apply_entry_plan: NOW+zona, narx 0.5% ichida → DARHOL FILLED (mid).
  D) _apply_entry_plan: NOW+zona, skala farqi 2.5% → WAIT + DIQQAT-izoh
     + 60 daqiqalik muddat.
  E) _apply_entry_plan: "now" so'zi YO'Q limit-zona → eski v116 WAIT,
     izohda joriy narx + 60 daq muddat ko'rinadi.
  F) tracker: muddat tugagan WAIT → CANCELLED + notifier "BEKOR" xabari.
  G) tracker: RAD (SL teskari) → CANCELLED + notifier "BEKOR" xabari.
  H) versiya: SINO-LAI-124.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from app.engine import entry as EN  # noqa: E402
from app.services import entry_settings as ES  # noqa: E402
from app.services import channel_inbox as CI  # noqa: E402


# --------------------------------------------- A) standart kutish: 60 daqiqa
def test_default_wait_60():
    assert EN.DEFAULT_WAIT == 60
    assert 60 in EN.WAIT_CHOICES


def test_entry_settings_defaults_k_wait_60():
    assert ES.defaults()[ES.K_WAIT] == 60
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "app/services/entry_settings.py"),
        encoding="utf-8").read()
    # bir martalik migratsiya bor
    assert "v124_wait60_done" in src


# --------------------------------------------- umumiy xarness
class _FakeSession:
    async def commit(self):
        return None

    async def execute(self, *a, **kw):
        raise RuntimeError("db yo'q")


class _Cap:
    def __init__(self):
        self.events = []

    async def send_event(self, text):
        self.events.append(text)


def _sig(**kw):
    d = dict(symbol="XAUUSDT", direction="SELL", quality_mode="CHANNEL",
             entry=4134.50, entry_low=None, entry_high=None,
             sl=4140.0, tp1=4120.0, tp2=4115.0, tp3=4110.0,
             entry_status="", entry_mode="", entry_note="",
             entry_expires_at=None, entry_skip="", entry_tps_src="CHANNEL",
             status="ACTIVE", is_active=True, id=8841, close_reason="",
             closed_at=None, lots=None, raw_text="Xauusd sell now 4132-4137")
    d.update(kw)
    return NS(**d)


def _parsed(**kw):
    d = dict(entry_src="TEXT", zone_low=4132.0, zone_high=4137.0,
             entry=4134.5, direction="SELL",
             raw="Xauusd sell now 4132-4137\nSl 4140\nTp 4120")
    d.update(kw)
    return NS(**d)


# ---------------------- C) NOW+zona yaqin narhda → DARHOL mid-dan kirish
@pytest.mark.asyncio
async def test_now_zona_yaqin_darhol_fill(monkeypatch):
    """BEK FXX 'sell now 4132-4137', joriy narx 4134 (zona ichida) —
    v115 uslubi: zona o'rtasidan DARHOL kirish, kutish yo'q."""
    monkeypatch.setattr(CI, "_last_px", lambda s: 4134.0)

    async def _nolive(sym):
        return 0.0
    import app.services.live_state as ls
    monkeypatch.setattr(ls, "get_price", _nolive)

    signal = _sig()
    parsed = _parsed()
    settings = NS(channel_expiry_minutes=240)
    st = await CI._apply_entry_plan(_FakeSession(), signal, parsed, settings)
    assert st == "filled"
    assert signal.entry_status == "FILLED"
    assert signal.entry == 4134.50          # zona o'rtasi
    assert signal.entry_low == signal.entry_high == 4134.50
    assert signal.entry_expires_at is None
    assert "v124" in (signal.entry_note or "")


@pytest.mark.asyncio
async def test_now_zona_zonadan_yaqin_ostda_darhol_fill(monkeypatch):
    """NOW signal: narx zonadan 0.5% pastda (SELL 4000, zona 4132-4137
    → 4115). 1.5% ichida → shu ham darhol mid-dan kiradi (quvish, v115)."""
    monkeypatch.setattr(CI, "_last_px", lambda s: 4115.0)

    async def _nolive(sym):
        return 0.0
    import app.services.live_state as ls
    monkeypatch.setattr(ls, "get_price", _nolive)

    signal = _sig()
    parsed = _parsed()
    st = await CI._apply_entry_plan(_FakeSession(), signal, parsed,
                                    NS(channel_expiry_minutes=240))
    assert st == "filled"
    assert signal.entry == 4134.50


# ------------------ D) NOW+zona katta skala farqida — DIQQAT bilan kutish
@pytest.mark.asyncio
async def test_now_zona_skala_farq_wait_60_daq(monkeypatch):
    """OCR-shift holati (bugungi bug): zona 4132-4137, narx 4034 — 2.5%
    farq. Kirilmaydi; DIQQAT-izoh + 60 daqiqalik muddat bilan WAIT."""
    monkeypatch.setattr(CI, "_last_px", lambda s: 4034.0)

    async def _nolive(sym):
        return 0.0
    import app.services.live_state as ls
    monkeypatch.setattr(ls, "get_price", _nolive)

    signal = _sig()
    parsed = _parsed()
    st = await CI._apply_entry_plan(_FakeSession(), signal, parsed,
                                    NS(channel_expiry_minutes=240))
    assert st == "wait"
    assert signal.entry_status == "WAIT"
    assert signal.entry_mode == "SIGNAL"
    assert "DIQQAT" in (signal.entry_note or "")
    assert "v124" in (signal.entry_note or "")
    # muddat ≈ 60 daqiqa
    assert signal.entry_expires_at is not None
    dt = signal.entry_expires_at - datetime.now(timezone.utc)
    assert timedelta(minutes=58) < dt < timedelta(minutes=62)


# ------------------ E) "now"siz limit-zona — eski WAIT oqimi saqlanadi
@pytest.mark.asyncio
async def test_limit_zona_nowsiz_kutiladi(monkeypatch):
    """'now' yozuvi bo'lmagan limit-zona: narx BUY zonasidan YUQORIDA
    (4200 > 4132-4137) — eski v116 usulda kutiladi; izohda joriy narx
    va 60 daqiqa ko'rsatiladi."""
    monkeypatch.setattr(CI, "_last_px", lambda s: 4200.0)

    async def _nolive(sym):
        return 0.0
    import app.services.live_state as ls
    monkeypatch.setattr(ls, "get_price", _nolive)

    signal = _sig(direction="BUY", sl=3990.0, tp1=4150.0, tp2=4160.0,
                  tp3=4170.0, raw_text="buy limit 4132-4137 sl 3990")
    parsed = _parsed(entry_src="TEXT", zone_low=4132.0, zone_high=4137.0,
                     entry=4134.5, direction="BUY",
                     raw="Xauusd buy limit 4132-4137 sl 3990")
    st = await CI._apply_entry_plan(_FakeSession(), signal, parsed,
                                    NS(channel_expiry_minutes=240))
    assert st == "wait"
    assert signal.entry_status == "WAIT"
    assert signal.entry_mode == "SIGNAL"        # UND emas (BUY, px > SL)
    note = signal.entry_note or ""
    assert "hozir" in note and "4,200.00" in note
    assert "60 daq" in note


# ------------------ F) tracker: muddat tugagan WAIT → ko'rinadigan bekor
@pytest.mark.asyncio
async def test_tracker_muddat_tugaganda_bekor_xabari():
    from app.services.tracker import SignalTracker
    trk = SignalTracker(paper_engine=None, settings=NS())
    sig = _sig(entry_status="WAIT", entry_mode="SIGNAL",
               entry_low=4132.0, entry_high=4137.0,
               entry_expires_at=datetime.now(timezone.utc)
               - timedelta(minutes=3))
    cap = _Cap()
    st = await trk.entry_tick(_FakeSession(), sig, 4000.0, notifier=cap)
    assert st == "expired"
    assert sig.entry_status == "CANCELLED"
    assert sig.status == "CANCELLED"
    assert sig.is_active is False
    assert cap.events, "bekor xabari yuborilishi shart (jim taqiq)"
    txt = cap.events[0]
    assert "BEKOR" in txt
    assert "№8841" in txt or "8841" in txt
    assert "60" in txt          # wait_min default 60 chiqishi
    assert "4,132.00" in txt    # zona ko'rsatib o'tiladi


# ------------------ G) tracker: RAD bekor — ko'rinadigan xabar
@pytest.mark.asyncio
async def test_tracker_rad_bekor_xabari():
    from app.services.tracker import SignalTracker
    trk = SignalTracker(paper_engine=None, settings=NS())
    # SELL zona 100-101, SL 99 (teskari) — fill direktivasi buzilgan
    sig = _sig(direction="SELL", entry=100.5, entry_low=100.0,
               entry_high=101.0, sl=99.0, tp1=98.0, tp2=97.0, tp3=96.0,
               entry_status="WAIT", entry_mode="SIGNAL",
               entry_expires_at=datetime.now(timezone.utc)
               + timedelta(minutes=45))
    cap = _Cap()
    st = await trk.entry_tick(_FakeSession(), sig, 100.5, notifier=cap)
    assert st == "cancelled"
    assert sig.entry_status == "CANCELLED"
    assert "RAD" in (sig.close_reason or "")
    assert cap.events, "RAD bekor xabari yuborilishi shart"
    assert "BEKOR" in cap.events[0]


# ------------------ H) versiya
def test_version_124():
    import app.services.local_ai as la
    assert la.__version__ == "SINO-LAI-125"
