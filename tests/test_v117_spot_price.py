"""v117 testlari:
1) Swissquote bboquotes javobi to'g'ri parse qilinadi (median bid/ask/mid).
2) Chirkin javob → None (zaxira yo'lga tushadi).
3) fetch_spot keshi: yangi kesh borligida tarmoqqa chiqmasdan qaytaradi.
4) last_spot (sinxron): yangi kesh → kvota; eskirgan → None.
5) adjust_df: sham ustunlari offsetga suriladi, shakl saqlanadi.
6) format_price_card_v117: mid/bid/ask, MEXC farqi (to'g'ri ishora),
   TOSHKENT vaqti (UTC+5) matnda.
7) build_price_card: XAU → v117 spot karta (fetch monkeypatch qilinadi).
"""

import time
from datetime import datetime, timezone

import pandas as pd
import pytest

from app.market import spot_quote as SQ
from app.services import price_now


# 2026-10-20 haqiqiy Swissquote javobining namunasi (qisqartirilgan)
SAMPLE = [
    {"topo": {"platform": "SQ", "server": "1"},
     "spreadProfilePrices": [
         {"spreadProfile": "standard", "bid": "4121.510", "ask": "4122.200",
          "bidSpread": "0", "askSpread": "0"},
         {"spreadProfile": "premium", "bid": "4121.620", "ask": "4122.090",
          "bidSpread": "0", "askSpread": "0"}],
     "ts": "1760000000000"},
    {"topo": {"platform": "LMAX", "server": "2"},
     "spreadProfilePrices": [
         {"spreadProfile": "standard", "bid": "4121.480", "ask": "4122.310",
          "bidSpread": "0", "askSpread": "0"}],
     "ts": "1760000001000"},
]


def test_parse_bbo_haqiqiy_format():
    q = SQ.parse_bbo(SAMPLE)
    assert q is not None
    # median bid: [4121.510, 4121.620, 4121.480] sort -> 4121.510
    assert q["bid"] == pytest.approx(4121.510, abs=0.001)
    assert q["ask"] > q["bid"] > 4000
    assert q["mid"] == pytest.approx((q["bid"] + q["ask"]) / 2, abs=0.01)
    assert q["ts_ms"] == 1760000001000
    assert q["src"] == "swissquote"


def test_parse_bbo_chirkin():
    assert SQ.parse_bbo(None) is None
    assert SQ.parse_bbo([]) is None
    assert SQ.parse_bbo([{"ts": "1"}]) is None
    assert SQ.parse_bbo([{"spreadProfilePrices": [{"bid": "0", "ask": "0"}]}]) is None
    assert SQ.parse_bbo("hodjasox") is None


@pytest.mark.asyncio
async def test_fetch_spot_keshdan_tarmoqsiz(monkeypatch):
    SQ._CACHE["ts"] = time.monotonic()
    SQ._CACHE["data"] = {"bid": 4121.5, "ask": 4122.2, "mid": 4121.85,
                         "ts_ms": 1, "src": "swissquote"}

    async def _boom():
        raise AssertionError("tarmoqqa chiqilmasligi kerak!")

    monkeypatch.setattr(SQ, "_client", _boom)
    q = await SQ.fetch_spot()          # kesh 1.4 s ichida → tarmoqsiz
    assert q and q["mid"] == pytest.approx(4121.85, abs=0.001)


def test_last_spot_sinxron():
    SQ._CACHE["ts"] = time.monotonic()
    SQ._CACHE["data"] = {"bid": 1, "ask": 2, "mid": 1.5, "ts_ms": 1, "src": "swissquote"}
    assert SQ.last_spot(10.0)["mid"] == pytest.approx(1.5)
    SQ._CACHE["ts"] = time.monotonic() - 9999
    assert SQ.last_spot(10.0) is None
    SQ._CACHE["ts"] = 0.0
    SQ._CACHE["data"] = None


def test_adjust_df_surish_va_shakl():
    df = pd.DataFrame({
        "open": [100.0, 101.0, 102.0],
        "high": [102.0, 103.0, 104.0],
        "low": [99.0, 100.0, 101.0],
        "close": [101.0, 102.0, 103.0],
        "volume": [1, 1, 1],
    })
    out = SQ.adjust_df(df, -6.0)
    assert out is not df
    assert float(out.iloc[-1]["close"]) == pytest.approx(97.0)
    assert float(out.iloc[0]["open"]) == pytest.approx(94.0)
    # shakl (yotoq oralig'i) saqlanadi
    assert (float(out["high"].max() - out["low"].min())
            == pytest.approx(float(df["high"].max() - df["low"].min())))
    # kilometr yo'q: asl DF tegilmaydi?
    assert float(df.iloc[-1]["close"]) == pytest.approx(103.0)
    assert SQ.adjust_df(df, 0.0) is df
    assert SQ.adjust_df(None, 5.0) is None


def test_karta_v117_matn():
    spot = {"bid": 4121.51, "ask": 4122.20, "mid": 4121.85,
            "ts_ms": 1, "src": "swissquote"}
    tr = {"dir": 1, "delta": 0.45, "seconds": 62.0}
    txt = price_now.format_price_card_v117("XAUUSDT", spot, 213, 4127.71,
                                           4121.85, "spot USD", 2.0, trend=tr)
    assert "4,121.85" in txt                       # mid — eng katta/ko'zga tashlanuvchi
    assert "4,121.51" in txt and "4,122.20" in txt  # bid/ask
    assert "O'SYAPTI" in txt and "+0.45" in txt and "daqiqada" in txt
    assert "Toshkent" in txt
    # keraksiz qatorlar olib tashlandi
    assert "UTC)" not in txt and "bot ko'rgan" not in txt
    # Toshkent = server UTC + 5
    m_u = datetime.now(timezone.utc)
    m_t = m_u.hour + 5
    exp = f"{(m_t) % 24:02d}:"
    assert exp in txt


def test_karta_v117_trend_boshqa_yonalish():
    spot = {"bid": 1.0, "ask": 2.0, "mid": 1.5, "ts_ms": 1, "src": "swissquote"}
    t1 = price_now.format_price_card_v117("XAUUSDT", spot, 0, None, None, None, None,
                                          trend={"dir": -1, "delta": -0.32, "seconds": 20.0})
    assert "TUSHYAPTI" in t1 and "-0.32" in t1 and "soniyada" in t1
    t2 = price_now.format_price_card_v117("XAUUSDT", spot, 0, None, None, None, None,
                                          trend={"dir": 0, "delta": 0.01, "seconds": 50.0})
    assert "barqaror" in t2
    t3 = price_now.format_price_card_v117("XAUUSDT", spot, 0, None, None, None, None,
                                          trend=None)
    assert "trend" in t3.lower()


def test_karta_v117_spot_yoq_zaxira():
    txt = price_now.format_price_card_v117("XAUUSDT", None, 0, 4127.71,
                                           None, None, None)
    assert "zaxira" in txt.lower()
    assert "4,127.71" in txt


def test_spot_trend_grafika():
    SQ._reset_hist()
    assert SQ.spot_trend() is None               # namuna kam
    now = time.monotonic()
    SQ._HIST.append((now - 60.0, 4100.00))
    SQ._HIST.append((now, 4101.50))
    tr = SQ.spot_trend()
    assert tr and tr["dir"] == 1 and tr["delta"] == pytest.approx(1.50, abs=0.01)
    assert 40 <= tr["seconds"] <= 65
    SQ._reset_hist()
    SQ._HIST.append((now - 60.0, 4101.50))
    SQ._HIST.append((now, 4100.00))
    assert SQ.spot_trend()["dir"] == -1
    SQ._reset_hist()
    SQ._HIST.append((now - 60.0, 4101.00))
    SQ._HIST.append((now, 4101.02))              # ±0.04 ichida → barqaror
    assert SQ.spot_trend()["dir"] == 0
    SQ._reset_hist()


@pytest.mark.asyncio
async def test_build_price_card_xau_spot(monkeypatch):
    async def fake_spot(force=False):
        return {"bid": 4121.51, "ask": 4122.20, "mid": 4121.85,
                "ts_ms": 1, "src": "swissquote"}

    async def fake_mexc(sym):
        return 4127.71

    monkeypatch.setattr(SQ, "fetch_spot", fake_spot)
    price_now.set_mexc_fetcher(fake_mexc)
    try:
        txt = await price_now.build_price_card("XAUUSDT")
    finally:
        price_now.set_mexc_fetcher(None)
    assert "4,121.85" in txt
    assert "Toshkent" in txt


def test_menyu_komandalarida_narx_kanalstat_fayl():
    # v118: Telegram Menu tugmasi ro'yxati (set_my_commands) bu buyruqlarni
    # ham o'z ichiga olsin — app/main.py _cmds ro'yxatini matndan tekshiramiz
    import pathlib
    src = pathlib.Path("app/main.py").read_text(encoding="utf-8")
    for cmd in ("narx", "kanalstat", "fayl"):
        pat = '("' + cmd + '",'
        assert pat in src, cmd + " Menu ro'yxatida yo'q!"


@pytest.mark.asyncio
async def test_fetch_mid_monkeypatched(monkeypatch):
    async def fake(force=False):
        return {"bid": 2.0, "ask": 4.0, "mid": 3.0, "ts_ms": 1, "src": "swissquote"}
    monkeypatch.setattr(SQ, "fetch_spot", fake)
    assert await SQ.fetch_mid() == pytest.approx(3.0)

    async def none_f(force=False):
        return None
    monkeypatch.setattr(SQ, "fetch_spot", none_f)
    assert await SQ.fetch_mid() is None
