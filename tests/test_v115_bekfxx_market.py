"""v115: BEK FXX kanali uchun real-vaqt rejim + BARE signal + /kanalstat.

O'zgarishlar:
  1) parser: "Xauusd buy now" (darajasiz) endi entry_src="BARE" signal beradi;
     dampdagi 13 ta REAL matnning 12 tasi avval ham o'qilgan — regressiya.
  2) _save: BARE uchun SL = 10 pip (oltinda 1.0$), TP esa v109 R345
     (1:3 / 1:4 / 1:5) avtomatik hisoblanadi.
  3) _apply_entry_plan: zona KUTILMAYDI — bozordan darhol; narx SL/TP1 dan
     oshib ketgan bo'lsa RAD (quvilmasin).
  4) channel_stats: signal/da'vo/stop sinflari, kunlik o'rtacha, render.
"""
import json
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.channel_parse import bare_now, parse_signal  # noqa: E402
from app.engine.sizing import channel_signal_levels  # noqa: E402
from app.services import channel_stats  # noqa: E402

# ---------------------------------------------------------------- parser
FULL_CASES = [
    "Xauusd buy noww 4134-4129\nSl 4127.00\nTp 4142\nTp 4148\nTp 4153",
    "Xauusd buy now 4150-4147\nSl 4145\nTp 4157\nTp 4163\nTp 4170",
    "Xauusd sell now 4188-4191\nSl 4193\nTp 4180\nTp 4175\nTp 4170",
    "Xauusd sell now 4187-4190\nSl 4192\nTp 4180\nTp 4177\nTp 4173",
    "Xauusd sell now 4168-4172\nSl 4174\nTp 4160\nTp 4155\nTp 4150",
    "Xauusd sell now 4158-4163\nSl 4165\nTp 4150\nTp 4145\nTp 4140",
    "Xauusd buy now 4149-4144\nSl 4143\nTp 4153\nTp 4155\nTp 4158",
    "Xauusd sell now 4185-4190\nSl 4192\nTp 4178\nTp 4173\nTp 4168",
    "Xauusd buy now 4172-4168\nSl 4165.0\nTp 4180\nTp 4185\nTp 4190",
    # SL va TP orasida ozoda gap (real damp, 10-20 10:52)
    "Xauusd buy now 4124-4119\nSl 4117.00\nNorm risk bn krng..!\n"
    "Tp 4130\nTp 4138\nTp 4143",
]


def test_full_formats_still_parsed():
    for txt in FULL_CASES:
        p = parse_signal(txt)
        assert p is not None, txt
        assert p.entry and p.sl and p.tps, txt
        assert p.entry_src != "BARE"


def test_bare_buy_sell_now():
    p = parse_signal("Xauusd buy now")
    assert p is not None and p.direction == "BUY"
    assert p.entry_src == "BARE" and not p.entry and not p.sl and not p.tps
    p2 = parse_signal("Xauusd sell now scalp")
    assert p2 is not None and p2.direction == "SELL" and p2.entry_src == "BARE"
    p3 = parse_signal("buy now minimal")          # symbolsiz qisqa — olinadi
    assert p3 is not None and p3.direction == "BUY"
    p4 = parse_signal("buy noww")                 # noww yozuv xatosi
    assert p4 is not None and p4.entry_src == "BARE"


def test_bare_rejects_chatter_and_results():
    assert bare_now("[RASM] 40pips ✅") is None             # natija
    assert bare_now("sl") is None
    assert bare_now("slni surdm") is None
    assert bare_now("buy now qilamizmi bolga sorab?") is None   # savol
    long_chat = ("Bolaaa buy now qilishga tayyormisilauu "
                 "bozori korip turipsila aktiv?")
    assert bare_now(long_chat) is None                       # uzun suhbat
    # darajali matn BARE EMAS — zona parseriga ketadi (yoki rad)
    assert bare_now("Xauusd buy now 4150-4147") is None
    p = parse_signal("Xauusd buy now 4150-4147")
    assert p is None or p.entry_src != "BARE"


def test_bare_levels_math():
    """User qoidasi: bozordan + SL 10 pip, TP 1:3/1:4/1:5 (oltin pip = 0.1)."""
    e = 4126.84
    sl = round(e - 10.0 * 0.1, 8)            # 4125.84 (10 pip = 1.0$)
    lv = channel_signal_levels("BUY", e, sl, [], "XAUUSD")
    assert lv["ok"], lv["why"]
    assert abs(lv["sl"] - 4125.84) < 1e-6
    # risk = 1.0$ → TP: e+3, e+4, e+5 (R345)
    assert abs(lv["tps"][0] - (e + 3.0)) < 1e-6
    assert abs(lv["tps"][1] - (e + 4.0)) < 1e-6
    assert abs(lv["tps"][2] - (e + 5.0)) < 1e-6
    assert lv["tps_src"] == "R345"


def test_bare_sell_levels_math():
    e = 4189.5
    sl = round(e + 1.0, 8)
    lv = channel_signal_levels("SELL", e, sl, [], "XAUUSD")
    assert lv["ok"]
    assert abs(lv["tps"][0] - (e - 3.0)) < 1e-6


# ---------------------------------------------------------------- stats
def _w(tmp_path, rows):
    p = tmp_path / "s.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return str(p)


def test_classify():
    assert channel_stats.classify("Xauusd buy now") == [("signal", 0)]
    assert channel_stats.classify("40pips ✅") == [("claim", 40)]
    assert channel_stats.classify("[RASM] 120 PIPS ✅🫡") == [("claim", 120)]
    assert channel_stats.classify("sl") == [("sl", 0)]
    assert channel_stats.classify("slni surdm") == [("sl", 0)]
    assert channel_stats.classify("shotimiz stop qilindi") == [("sl", 0)]
    assert channel_stats.classify("") == []
    assert channel_stats.classify(None) == []
    # pips da'vosi bo'lgan xabar signal emas
    assert channel_stats.classify("buy nowkurdik 40pips ✅") == [("claim", 40)]


def test_summary_avg_and_deleted_sl_kept(tmp_path):
    d1, d2 = "2026-10-19", "2026-10-20"
    rows = [
        {"ts": d1 + " 05:45:00", "d": d1, "ch": "bek", "title": "BEK FXX",
         "kind": "signal", "pips": 0},
        {"ts": d1 + " 06:20:00", "d": d1, "ch": "bek", "title": "BEK FXX",
         "kind": "claim", "pips": 100},
        {"ts": d2 + " 10:21:00", "d": d2, "ch": "bek", "title": "BEK FXX",
         "kind": "signal", "pips": 0},
        # kanal buni keyin O'CHIRGAN bo'lsa ham yozuv saqlanadi:
        {"ts": d2 + " 10:48:00", "d": d2, "ch": "bek", "title": "BEK FXX",
         "kind": "sl", "pips": 0},
    ]
    path = _w(tmp_path, rows)
    s = channel_stats.summary(days=7, path=path,
                              today=date(2026, 10, 20))
    assert "bek" in s
    b = s["bek"]
    assert b["days_active"] == 2 and b["signals"] == 2 and b["sl"] == 1
    assert b["claims_total"] == 100
    assert b["avg_per_day"] == 50.0
    # sof taxmin: (100 - 1*60)/2 = 20
    assert abs(b["net_est_per_day"] - 20.0) < 1e-9


def test_render_empty_and_filled(tmp_path):
    empty = channel_stats.render(30, path=str(tmp_path / "yoq.jsonl"))
    assert "ma'lumot yo'q" in empty.lower() or "Hali" in empty
    rows = [{"ts": "2026-10-20 08:00:00", "d": "2026-10-20", "ch": "x",
             "title": "BEK FXX", "kind": "claim", "pips": 165}]
    txt = channel_stats.render(30, path=_w(tmp_path, rows))
    assert "BEK FXX" in txt and "+165" in txt and "Da'volar kanalniki" in txt
