"""v127 (USER, 26-okt): kanal-ingest holat-kodlari tushunarli o'zbek
tilida yoziladi (botga yuborilgan test-xabar javobida).

Foydalanuvchi shikoyati: kanal xabarini botga tekshirishga yuborganda javob
"Holat: dup_msg" — tushunarsiz ichki kod. Endi uzun emas, lekin aniq
o'zbekcha izoh chiqadi:

  dup_msg       -> takror nusxa (bir signal ikki karra ochilmasin)
  seen          -> shu sessiyada allaqachon ko'rilgan
  market_closed -> bozor yopiq (v125 blok)
  ad            -> reklama/e'lon filtri o'tirishmadi
  not_signal    -> kirish/SL/TP topilmadi
  skip          -> qayta ishlanishga hojat yo'q
  db_error      -> baza xatosi
  error         -> ichki xato
  (noma'lum)    -> <code>xom-kod</code> lekin ko'rsatiladi

Qo'shimcha: not_signal endi JIM o'tmaydi — tushunarli izoh yuboriladi
(tekshiruvda qulay). seen/skip jim qoladi (takror shovqinini kamaytirish).

Tekshiruvlar:
  A) channels.py xodimlovdagi map mavjud va kalitlari to'liq.
  B) dup_msg javobi tushunarli ("ikki marta ochilmaydi").
  C) market_closed javobi bozor yopiq deb tushuntiradi.
  D) not_signal endi jim EMAS (silent-range da emas) — izoh chiqadi.
  E) noma'lum kod <code> ga o'raladi (HTML xavfsiz-ish).
  F) versiya: SINO-LAI-127+.
"""
import os
import sys
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402


_CH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "app/bot/handlers/channels.py")


def _src():
    with open(_CH, encoding="utf-8") as f:
        return f.read()


# ---------- A) map kalitlari to'liq
def test_holat_kalitlari_toliq():
    src = _src()
    for k in ("dup_msg", "seen", "market_closed", "ad", "not_signal",
              "skip", "db_error", "error"):
        assert f'"{k}"' in src, f"{k} kaliti yo'q"


# ---------- B) dup_msg izohi
def test_dup_msg_tushunarli():
    src = _src()
    assert "ikki marta ochilmaydi" in src    # takror himoya sababi aytib o'tilgan
    assert "ALLAQACHON" in src


# ---------- C) market_closed izohi
def test_market_closed_tushunarli():
    src = _src()
    assert "Bozor Hozir YOPIQ" in src


# ---------- D) not_signal endi jim emas
def test_not_signal_endi_jim_emas():
    src = _src()
    # eski qator: ("not_signal", "seen", "skip") return bo'lgan edi
    assert '"not_signal", "seen", "skip"' not in src
    assert '"seen", "skip"' in src          # seen/skip jim qoladi
    assert "kirish/SL/TP topilmadi" in src  # not_signal izohi joyda


# ---------- E) noma'lum kod himoyalangan ko'rsatiladi
def test_folbek_code_tag():
    src = _src()
    assert "<code>" in src and "{status}" in src


# ---------- F) versiya
def test_version_127():
    import app.services.local_ai as la
    assert la.__version__ == "SINO-LAI-128"


# ---------- G) QATTIQ ZONA QOIDASI (v127, USER bug: sell now 4017-4022
#    da bot 4024.17 dan kirib olgan edi — narx zona USTIDA bo'lsa ham
#    eski zone_hit "hit" deb qarshilgan)
from datetime import datetime, timezone  # noqa: E402
from app.engine import entry as EN  # noqa: E402
from app.services import channel_inbox as CI  # noqa: E402
from types import SimpleNamespace as NS  # noqa: E402


def _sig127(**kw):
    d = dict(symbol="XAUUSDT", direction="SELL", quality_mode="CHANNEL",
             entry=4019.50, entry_low=None, entry_high=None,
             sl=4025.0, tp1=4003.0, tp2=3997.5, tp3=3992.0,
             entry_status="", entry_mode="", entry_note="",
             entry_expires_at=None, entry_skip="", entry_tps_src="CHANNEL",
             status="ACTIVE", is_active=True, id=9001, close_reason="",
             closed_at=None, lots=None, raw_text="Xauusd sell now 4017-4022",
             created_at=datetime.now(timezone.utc))
    d.update(kw)
    return NS(**d)


def _parsed127(**kw):
    d = dict(entry_src="TEXT", zone_low=4017.0, zone_high=4022.0,
             entry=4019.5, direction="SELL",
             raw="Xauusd sell now 4017-4022\nSl 4025\nTp 4110")
    d.update(kw)
    return NS(**d)


class _FS127:
    async def commit(self):
        return None

    async def execute(self, *a, **kw):
        raise RuntimeError("db yo'q")


async def _nolive127(sym):
    return 0.0


@pytest.mark.asyncio
async def test_now_zona_ustida_narxda_kirilmaydi(monkeypatch):
    """REGRESSIYA: 'sell now 4017-4022', bozor narxi 4024 (zona USTIDA,
    0.1% farq) — endi KIRILMAYDI, kun oxirigacha zona qaytishi kutiladi."""
    monkeypatch.setattr(CI, "_last_px", lambda s: 4024.17)
    import app.services.live_state as ls
    monkeypatch.setattr(ls, "get_price", _nolive127)

    sig = _sig127()
    st = await CI._apply_entry_plan(_FS127(), sig, _parsed127(),
                                    NS(channel_expiry_minutes=240))
    assert st == "wait"
    assert sig.entry_status == "WAIT"
    assert sig.entry != 4024.17               # H O Z I R G I narxdan emas!
    assert sig.entry == 4019.5                # reja: zona o'rtasi
    assert sig.entry_low == 4017.0 and sig.entry_high == 4022.0
    note = sig.entry_note or ""
    assert "kirmaymiz" in note and "v126" not in note and "kanal zona" in note


@pytest.mark.asyncio
async def test_now_zona_ichida_mid_ga_yetsa_kiradi(monkeypatch):
    """v128 (USER): 'sell now 4017-4022', bozor 4021.0 — zona ICHIDA va
    O'RTADAN (4019.5) yuqorida -> zona O'RTASIDAN kiriladi (4021 EMAS)."""
    monkeypatch.setattr(CI, "_last_px", lambda s: 4021.0)
    import app.services.live_state as ls
    monkeypatch.setattr(ls, "get_price", _nolive127)

    sig = _sig127()
    st = await CI._apply_entry_plan(_FS127(), sig, _parsed127(),
                                    NS(channel_expiry_minutes=240))
    assert st == "filled"
    assert sig.entry == 4019.5                # aynan zona O'RTASI (v128 mid)
    assert sig.entry_low == sig.entry_high == 4019.5
    assert "zona o'rtasidan kirdi" in (sig.entry_note or "")


@pytest.mark.asyncio
async def test_now_zona_mid_dan_pastda_kutiladi(monkeypatch):
    """v128: SELL, bozor 4017.11 — zona ICHIDA lekin MID dan PASTDA ->
    kirilmaydi, mid gacha kutiladi (v126 dagi 4017.11-fill endi YO'Q)."""
    monkeypatch.setattr(CI, "_last_px", lambda s: 4017.11)
    import app.services.live_state as ls
    monkeypatch.setattr(ls, "get_price", _nolive127)

    sig = _sig127()
    st = await CI._apply_entry_plan(_FS127(), sig, _parsed127(),
                                    NS(channel_expiry_minutes=240))
    assert st == "wait"
    assert sig.entry_status == "WAIT"
    assert "kirmaymiz" in (sig.entry_note or "")


# ---------- H) qat'iy zone_hit + v128 mid-qoida (zona ICHI, fill=O'RTA)
def test_zone_hit_qatiy_127():
    ok, _ = EN.zone_hit("SELL", 4017.0, 4022.0, 4024.17)   # ustida — YO'Q
    assert not ok
    # v128: SELL mid (4019.5) ga yetgach -> fill = MID (joriy narx emas)
    ok2, f2 = EN.zone_hit("SELL", 4017.0, 4022.0, 4021.0)
    assert ok2 and abs(f2 - 4019.5) < 1e-9
    ok3, _ = EN.zone_hit("BUY", 4017.0, 4022.0, 4016.0)    # ostida — YO'Q
    assert not ok3
    # v128: SELL zona ichida, lekin MID dan PAST — kutiladi
    ok4, _ = EN.zone_hit("SELL", 4017.0, 4022.0, 4017.11)
    assert not ok4
    # v128: BUY mid ga tushgach -> fill = MID
    ok5, f5 = EN.zone_hit("BUY", 4017.0, 4022.0, 4018.0)
    assert ok5 and abs(f5 - 4019.5) < 1e-9
    # nuqta-zona (lo==hi): aynan nuqtadan
    ok6, f6 = EN.zone_hit("BUY", 4150.0, 4150.0, 4150.0)
    assert ok6 and abs(f6 - 4150.0) < 1e-9
    ok7, _ = EN.zone_hit("BUY", 4150.0, 4150.0, 4151.0)    # nuqta ustida — YO'Q
    assert not ok7
