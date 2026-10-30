"""v128 (USER, 28-okt): 12 audit-xato uchun HOTFIX to'plami.

Qabul qilingan dizayn (user tasdig'i):
  * Y-QOIDA (zona-o'rta): kirish zona 2 son orasida bo'lsa — fill har doim
    ZONA O'RTASIDAN ((lo+hi)/2). Trigger — narx zona ICHIDA mid ga yetishi
    (BUY px<=mid, SELL px>=mid); nuqta-zona (lo==hi) — aynan nuqtadan;
    zona tashqarisida — kirilmaydi (v127 strict saqlangan).
  * X2: fill paytida TP lar QAYTA HISOBLANMAYDI (kartadagi TP = ijro TP).
  * X3: TP1 ga surilgan (foyda-qulflangan) stop GAP fill qilmaydi —
    aynan darajada yopiladi.
  * X9/X12: izohlar butun ko'rinadi, yagona shablon.
  * X5: pips IKKALA ko'rinish — TP-harakat (1-lot) va JAMI netto (2-lot).
  * X10: "o'rtacha" yo'q — $-jami va R-jami alohida.
  * versiya: SINO-LAI-128.

Tekshiruvlar:
  A) zone_hit: 2-sonli zona mid fill (BUY/SELL); mid ga yetmagan ZONA-ICHI
     kutiladi; tashqarisi YO'Q (v127); nuqta-zona aynan nuqtadan.
  B) resanitize_levels: TP mavjud → FREEZE (qayta hisoblanmaydi);
     TP yo'q (BARE) → 1:3/1:4/1:5 saqlanadi.
  C) tracker._px: "tpsl" (foyda-qulflangan stop) gapdiga qaramay AYNAN
     darajada; "sl" (asli stop) esa gap da ochilish narxidan.
  D) signal_pips_pair: (1-lot move, 2-lot netto) to'g'ri.
  E) paper _closed_block: "o'rtachasi" yo'q; R-jami risk-fas xoli hisobda
     to'g'ri (risk bor yo'lda x2 bo'lmaydi!).
  F) versiya SINO-LAI-128.
"""
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from app.engine import entry as EN          # noqa: E402
from app.engine import sizing as SZ         # noqa: E402


# ------------------------------------------------------- A) zone_hit (v128)
def test_v128_mid_fill_buy():
    ok, fill = EN.zone_hit("BUY", 4005.0, 4017.0, 4009.0)   # mid=4011
    assert ok and abs(fill - 4011.0) < 1e-9
    # mid dan YUQORI (zona ichida) — hali kutiladi
    ok2, _ = EN.zone_hit("BUY", 4005.0, 4017.0, 4015.0)
    assert not ok2


def test_v128_mid_fill_sell():
    ok, fill = EN.zone_hit("SELL", 4005.0, 4017.0, 4015.0)
    assert ok and abs(fill - 4011.0) < 1e-9
    ok2, _ = EN.zone_hit("SELL", 4005.0, 4017.0, 4007.0)    # mid dan past — kutadi
    assert not ok2


def test_v128_zona_tashqarisi_kirilmaydi():
    assert not EN.zone_hit("BUY", 4005.0, 4017.0, 4004.9)[0]     # ostida
    assert not EN.zone_hit("BUY", 4005.0, 4017.0, 4018.0)[0]     # ustida
    assert not EN.zone_hit("SELL", 4005.0, 4017.0, 4018.0)[0]
    assert not EN.zone_hit("SELL", 4005.0, 4017.0, 4004.9)[0]


def test_v128_nuqta_zona_aynan_nuqtadan():
    ok, fill = EN.zone_hit("SELL", 4030.0, 4030.0, 4030.5)
    assert ok and abs(fill - 4030.0) < 1e-9
    assert not EN.zone_hit("SELL", 4030.0, 4030.0, 4029.9)[0]
    ok2, fill2 = EN.zone_hit("BUY", 4030.0, 4030.0, 4029.9)
    assert ok2 and abs(fill2 - 4030.0) < 1e-9


# ------------------------------------------------------- B) resanitize FREEZE
def test_x2_resanitize_tp_freeze():
    """X2: fill narxi siljiganda kanal TP lari QAYTA HISOBLANMAYDI —
    kartadagi 4017.00 ijroda ham aynan shu qoladi."""
    r = SZ.resanitize_levels("BUY", 3990.0, 3985.0, 4005.0, 4010.0, 4015.0,
                             "CHANNEL", "XAUUSD")
    assert r["ok"] is True
    assert r["tp1"] == 4005.0 and r["tp2"] == 4010.0 and r["tp3"] == 4015.0
    assert r["tps_src"] == "CHANNEL"


def test_x2_resanitize_bare_still_r345():
    """TP umuman yo'q (BARE) bo'lsa — 1:3/1:4/1:5 hisob saqlanadi."""
    r = SZ.resanitize_levels("BUY", 4200.0, 4199.0, 0.0, 0.0, 0.0,
                             "BARE", "XAUUSD")
    assert r["ok"] is True and r["tps_src"] == "R345"
    assert r["tp1"] == 4203.0 and r["tp2"] == 4204.0 and r["tp3"] == 4205.0


# ------------------------------------------------------- C) _px tpsl (X3)
def test_x3_himoya_stop_darajada_yopiladi():
    from app.services.tracker import SignalTracker
    bar = {"open": 4190.0}          # gap — SELL stop (4185) ustida ochilgan
    # asli stop: gap huquqiy — ochilish narxidan
    assert SignalTracker._px(bar, 4185.0, False, "sl") == 4190.0
    # foydaga qulflangan stop (TP1 ga surilgan): AYNAN darajada (X3)
    assert SignalTracker._px(bar, 4185.0, False, "tpsl") == 4185.0
    assert SignalTracker._px(bar, 4185.0, False, "tp") == 4185.0


# ------------------------------------------------------- D) pips ikkilamasi
def test_x5_signal_pips_pair():
    from app.notifications.telegram import signal_pips_pair, signal_pips
    sig = NS(symbol="XAUUSDT", direction="BUY", entry=4000.0,
             close_price=4008.0)
    mv, net, win = signal_pips_pair(sig)
    # XAUUSD pip_size = 0.1 -> 800 punkt/dispersiyali: (4008-4000)/0.1 = 80 pip
    assert mv == 80.0 and net == 160.0 and win is True
    # eski konvensiya (signal_pips) = netto — buzilmagan
    p, w = signal_pips(sig)
    assert p == 160.0 and w is True


# ------------------------------------------------------- E) _closed_block (X10)
def _lot(r, usd, stage=0, risk=0.0):
    return NS(symbol="XAUUSDT", direction="BUY", timeframe="m1",
              stage=stage, r_multiple=r, realized_pnl=usd,
              risk_amount=risk, close_reason="TP1", close_price=None,
              closed_at=datetime.now(timezone.utc), opened_at=None,
              signal_id=1, entry=4000.0)


def test_x10_closed_block_jami_alohida():
    from app.bot.handlers import paper as P
    lot1 = _lot(1.0, 8.0, stage=0, risk=8.0)
    lot2 = _lot(1.0, 8.0, stage=10, risk=8.0)
    out = P._closed_block([lot1, lot2], [])
    txt = "\n".join(out)
    assert "o'rtachasi" not in txt
    assert "Jami R" in txt and "+16.00$" in txt
    # risk bor yo'l: R jami = cash/risk = 16/16 = 1.00R (x2 EMAS!)
    assert "+1.00R" in txt


def test_x10_closed_block_risksiz_x2():
    """Zaxira yo'l (risk ma'lum emas): lotlar R o'rtachasi * 2 = R-jami."""
    from app.bot.handlers import paper as P
    lot1 = _lot(1.0, 8.0, stage=0)      # risk yo'q
    lot2 = _lot(2.0, 16.0, stage=10)    # risk yo'q
    out = P._closed_block([lot1, lot2], [])
    txt = "\n".join(out)
    assert "+3.00R" in txt              # (1+2)/2 o'rtacha=1.5 → jami 3.00R
    assert "o'rtachasi" not in txt


# ------------------------------------------------------- F) versiya
def test_v128_version():
    import app.services.local_ai as la
    assert la.__version__ == "SINO-LAI-128"
