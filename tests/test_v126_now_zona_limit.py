"""v126 (USER, 24-okt): NOW + zona = ZONADAN kirish — v124 "zona o'rtasidan
darhol kirish" bekor qilindi.

Foydalanuvchi shikoyati (24-okt, BEK FXX №1 skrinlari): kanal
"Xauusd sell now 4017-4022 Sl 4025" deb yozgan, bot esa NOW so'zini ko'rib
zona o'rtasidan (4019.50) DARHOL FILLED qilgan. User: "zona aytib now
deyilgan bo'lsa aytilgan zonadan kiraversin; zona aytilmay now bo'lsa
hozirgi narxdan; aytilgan zona bo'la turib hozirgi narxdan kirish — ahmoqlik".

Yangi qoidalar (v126):
  - NOW + ZONA: narx zona ichida/tegib turgan bo'lsa → zone_hit narxidan
    DARHOL kiriladi (zona chegarasi, o'rtasi emas).
  - NOW + ZONA, narx zonadan uzoqda (lekin <1.5%) → zona QAYTGANDA kiriladi,
    tez tik, muddat — Toshkent kuni oxirigacha (signal jim o'tib ketmaydi).
    Hozirgi narxdan KIRILMAYDI.
  - NOW + ZONA, skala farqi >1.5% (OCR himoya) → o'zgarishsiz: 60 daq WAIT
    + DIQQAT izohi (v126 tegi).
  - NOW-YO'Q limit-zona oqimi (v116) o'zgarishsiz: 60 daq kutiladi.
  - NOW + zona YO'Q (masalan "sell now 4030") — bitta narx orqali market
    kirish avvalgidek (bu blokka tushmaydi).
  - tracker: kun-oxirigacha kutgan signal bekor bo'lganda xabar matnida
    "Toshkent kuni oxiri" yoziladi (60 daq deb yolg'on gapirmaydi).

Tekshiruvlar:
  A) DEFAULT_WAIT == 60 saqlanadi (migratsiya o'zgarsiz).
  B) NOW+zona, narx zona ICHIDA → FILLED, narx = joriy (zona tekkizilgan)
     narx, o'rta nuqta EMAS; izoh "(v126".
  C) NOW+zona, narx zonadan ostida (0.5%) → WAIT, kun oxirigacha, izohda
     "KIRILMAYDI" + "v126".
  D) NOW+zona, skala farqi 2.5% → WAIT, 60 daq, DIQQAT, izoh "(v126".
  E) "now"siz limit-zona → 60 daq WAIT (v116 oqimi saqlangan).
  F) tracker: 60 daqli WAIT tugaganda "60" ko'rinadi (oddiy signal).
  G) tracker: kun-oxirigacha v126 signal tugaganda "Toshkent kuni oxiri".
  H) versiya: SINO-LAI-126.
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
    assert "v124_wait60_done" in src   # bir martalik migratsiya ko'chirilmaydi


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
             closed_at=None, lots=None, raw_text="Xauusd sell now 4132-4137",
             created_at=datetime.now(timezone.utc))
    d.update(kw)
    return NS(**d)


def _parsed(**kw):
    d = dict(entry_src="TEXT", zone_low=4132.0, zone_high=4137.0,
             entry=4134.5, direction="SELL",
             raw="Xauusd sell now 4132-4137\nSl 4140\nTp 4120")
    d.update(kw)
    return NS(**d)


async def _nolive(sym):
    return 0.0


# ---------------------- B) NOW+zona: v128 MID-qoida — fill = zona O'RTASI
@pytest.mark.asyncio
async def test_now_zona_ichida_zonadan_fill(monkeypatch):
    """v128 (USER, 28-okt): 'sell now 4132-4137', joriy narx 4136 — zona
    ICHIDA va O'RTADAN yuqorida: zona O'RTASIDAN (4134.50) kiriladi —
    joriy narx/chegara EMAS (v126 fill=joriy qoidasi YANGILANDI)."""
    monkeypatch.setattr(CI, "_last_px", lambda s: 4136.0)
    import app.services.live_state as ls
    monkeypatch.setattr(ls, "get_price", _nolive)

    signal = _sig()
    st = await CI._apply_entry_plan(_FakeSession(), signal, _parsed(),
                                    NS(channel_expiry_minutes=240))
    assert st == "filled"
    assert signal.entry_status == "FILLED"
    assert signal.entry == 4134.50          # zona O'RTASI (v128 mid)
    assert signal.entry != 4136.00
    assert signal.entry_low == signal.entry_high == 4134.50
    assert signal.entry_expires_at is None
    note = signal.entry_note or ""
    assert "zona o'rtasidan kirdi" in note and "v126" not in note


@pytest.mark.asyncio
async def test_now_zona_pastki_yarimda_mid_kutiladi(monkeypatch):
    """v128: SELL, narx zona ICHIDA lekin MID dan PASTDA (4133) — hali
    kirilmaydi; mid (4134.50) gacha kutiladi (kun oxirigacha tez tik)."""
    monkeypatch.setattr(CI, "_last_px", lambda s: 4133.0)
    import app.services.live_state as ls
    monkeypatch.setattr(ls, "get_price", _nolive)

    signal = _sig()
    st = await CI._apply_entry_plan(_FakeSession(), signal, _parsed(),
                                    NS(channel_expiry_minutes=240))
    assert st == "wait"
    assert signal.entry_status == "WAIT"
    note = signal.entry_note or ""
    assert "kirmaymiz" in note and "4,133.00" in note


# ---------------------- C) NOW+zona, narx ostida → ZONA KUTILADI, kirilmaydi
@pytest.mark.asyncio
async def test_now_zona_ostida_kirilmaydi_kun_oxirigacha(monkeypatch):
    """BEK FXX holati: 'sell now 4132-4137', narx 4115 (0.5% ostida) —
    zona tegilmaguncha KIRILMAYDI; kun oxirigacha tez tik bilan kutiladi."""
    monkeypatch.setattr(CI, "_last_px", lambda s: 4115.0)
    import app.services.live_state as ls
    monkeypatch.setattr(ls, "get_price", _nolive)

    signal = _sig()
    st = await CI._apply_entry_plan(_FakeSession(), signal, _parsed(),
                                    NS(channel_expiry_minutes=240))
    assert st == "wait"
    assert signal.entry_status == "WAIT"
    assert signal.entry_mode == "SIGNAL"
    note = signal.entry_note or ""
    assert "kirmaymiz" in note
    assert "kun oxirigacha" in note
    assert "4,115.00" in note              # joriy narx ko'rsatiladi
    # kun oxirigacha — muddat ancha uzoq (> 2 soat)
    assert signal.entry_expires_at is not None
    dt = signal.entry_expires_at - datetime.now(timezone.utc)
    assert dt > timedelta(hours=2)


# ------------------ D) NOW+zona, skala farqi 2.5% → OCR DIQQAT + 60 daq WAIT
@pytest.mark.asyncio
async def test_now_zona_skala_farq_wait_60_daq(monkeypatch):
    monkeypatch.setattr(CI, "_last_px", lambda s: 4034.0)
    import app.services.live_state as ls
    monkeypatch.setattr(ls, "get_price", _nolive)

    signal = _sig()
    st = await CI._apply_entry_plan(_FakeSession(), signal, _parsed(),
                                    NS(channel_expiry_minutes=240))
    assert st == "wait"
    assert signal.entry_status == "WAIT"
    assert signal.entry_mode == "SIGNAL"
    note = signal.entry_note or ""
    assert "DIQQAT" in note and "kanal zona" in note and "v126" not in note
    assert signal.entry_expires_at is not None
    dt = signal.entry_expires_at - datetime.now(timezone.utc)
    assert timedelta(minutes=58) < dt < timedelta(minutes=62)


# ------------------ E) "now"siz limit-zona — 60 daq esaolar WAIT saqlanadi
@pytest.mark.asyncio
async def test_limit_zona_nowsiz_kutiladi(monkeypatch):
    monkeypatch.setattr(CI, "_last_px", lambda s: 4200.0)
    import app.services.live_state as ls
    monkeypatch.setattr(ls, "get_price", _nolive)

    signal = _sig(direction="BUY", sl=3990.0, tp1=4150.0, tp2=4160.0,
                  tp3=4170.0, raw_text="buy limit 4132-4137 sl 3990")
    parsed = _parsed(direction="BUY",
                     raw="Xauusd buy limit 4132-4137 sl 3990")
    st = await CI._apply_entry_plan(_FakeSession(), signal, parsed,
                                    NS(channel_expiry_minutes=240))
    assert st == "wait"
    assert signal.entry_status == "WAIT"
    assert signal.entry_mode == "SIGNAL"
    note = signal.entry_note or ""
    assert "hozir" in note and "4,200.00" in note
    assert "60 daq" in note


# ------------------ F) tracker: oddiy 60 daq signal tugaganda "60" matni
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
    assert sig.is_active is False
    assert cap.events, "bekor xabari yuborilishi shart (jim taqiq)"
    txt = cap.events[0]
    assert "BEKOR" in txt
    assert "8841" in txt
    assert "60" in txt                      # oddiy signalda 60 daqiqa matni
    assert "4,132.00" in txt


# ------------------ G) tracker: v126 kun-oxiri signaliga to'g'ri matn
@pytest.mark.asyncio
async def test_tracker_v126_kun_oxiri_bekor_xabari():
    from app.services.tracker import SignalTracker
    trk = SignalTracker(paper_engine=None, settings=NS())
    # signal 5 soat oldin yaratilgan, muddati kun oxirigacha edi
    sig = _sig(entry_status="WAIT", entry_mode="SIGNAL",
               entry_low=4132.0, entry_high=4137.0,
               created_at=datetime.now(timezone.utc) - timedelta(hours=5),
               entry_expires_at=datetime.now(timezone.utc)
               - timedelta(minutes=3))
    cap = _Cap()
    st = await trk.entry_tick(_FakeSession(), sig, 4000.0, notifier=cap)
    assert st == "expired"
    txt = cap.events[0]
    assert "BEKOR" in txt
    assert "Toshkent kuni oxiri" in txt     # 60 daq emas — haqiqiy muddat
    assert "60 daqiqa" not in txt
    assert "v126" in txt
    # entry_skip ham v126 tagi
    assert "v126" in (sig.entry_skip or "")


# ------------------ H) versiya
def test_version_126():
    import app.services.local_ai as la
    assert int(la.__version__.split("-")[-1]) >= 126
