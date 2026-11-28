# -*- coding: utf-8 -*-
"""v110: 4 real kanal (@rahimbfxproo, @xauusdsingle0, @the_gold_kingvip,
@bullgold_fx70) formatlarini o'qish — regressiya testlari.

800 xabarlik korpus bo'yicha natija: 0 yolg'on signal, 0 o'tkazilgan signal
(#1428 tipidagi buzilgan-SL'li signal to'g'ri RAD qilinadi).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.channel_real import strict_verdict, _DIRPX, _TP_ANY  # noqa: E402
from app.engine.sizing import channel_signal_levels  # noqa: E402


# ------------------------- Haqiqiy kanal matnlari -------------------------- #
GOLDKING_DOTTED_BUY = ("#XAUUSD BUYY.NOW.4422\n\nTP¹ .....\xa0 4426\n"
                       "TP² .....\xa0 4430\nTP³ .....\xa0 4434\n"
                       "TP⁴ .....\xa0 4438\nTP⁵ .....\xa0 4442\n\n"
                       "SLL.....\xa0 4412\n\nFOLLOW MY MANAGEMENT✅🔥🔥")
GOLDKING_DOTTED_SELL = ("📉XAUUSD SELL.NOW.4425\n\nTP¹ .....\xa0 4422\n"
                        "TP² .....\xa0 4419\nTP³ .....\xa0 4416\n"
                        "TP⁴ .....\xa0 4413\nTP⁵ .....\xa0 4410\n\n"
                        "SLL.....\xa0 4433")
GOLDKING_SLASH_SELL = ("GOLD\xa0SELL 4280/4284\n\nTP.\xa0\xa0 4277\nTP.\xa0\xa0 4274\n"
                       "TP.\xa0\xa0 4271\nTP.\xa0\xa0 4268\nTP.\xa0\xa0 4265\n"
                       "SL.\xa0\xa04290\n\nUSE PROPER MONEY MANAGEMENT🔥✔️")
GOLDKING_UNDERSCORE_BUY = ("📈XAUUSD_BUYY 4388_4383\n✔️TP 4392\n✔️TP 4396\n"
                           "✔️TP 4400\n✔️TP 4404\n✔️TP 4408\n❌SL 4378")
GOLDKING_BROKEN_SL = ("GOLD\xa0SELL 4139/4143\n\nTP.\xa0\xa0 4136\nTP.\xa0\xa0 4133\n"
                      "TP.\xa0\xa0 4130\nTP.\xa0\xa0 4127\nTP.\xa0\xa0 4124\n"
                      "SL.\xa0\xa04249\n\nUSE PROPER MONEY MANAGEMENT🔥")
BULLGOLD_6TP = ("GOLD Buy 4132\nMORE Buy 4130\n\nTP1 4134\nTP2 4136\n"
                "TP3 4138\nTP4 4140\nTP5 4142\nTP6 4144\n\n"
                "SL_ 4122\n\nUse proper money management")
RAHIMB_BUY = ("GOLD BUY NOW 4364\n\nTP 4367\nTP 4370\nTP 4373\nTP 4376\n"
              "TP 4379\n\nSL 4351")
XAUUSD0_6TP = ("GOLD SELL NOW 4315\n\nTP 4312\nTP 4309\nTP 4306\nTP 4303\n"
               "TP 4300\nTP 4297\n\nSL 4328")


def _lv(v: dict) -> dict:
    return channel_signal_levels(v["direction"], v["entry"], v["sl"],
                                 v["tps"], "XAUUSD")


def _sig(text: str) -> dict:
    v = strict_verdict(text, ref=None)
    assert v["verdict"] == "SIGNAL", f"SIGNAL kutilardi: {v}"
    return v


# --------------------------------------------------------------------------- #
class TestRealSignals:
    def test_goldking_dotted_buyyy(self):
        v = _sig(GOLDKING_DOTTED_BUY)        # BUYY/SLL takrorli harfli format
        assert v["direction"] == "BUY"
        assert v["entry"] == 4422.0
        assert v["sl"] == 4412.0
        assert v["tps"] == [4426.0, 4430.0, 4434.0, 4438.0, 4442.0]
        lv = _lv(v)
        assert lv["ok"] and lv["tps_src"] == "CHANNEL"
        assert lv["last_tp"] == 4442.0

    def test_goldking_dotted_sell(self):
        v = _sig(GOLDKING_DOTTED_SELL)
        assert v["direction"] == "SELL"
        assert v["entry"] == 4425.0
        assert v["sl"] == 4433.0
        assert len(v["tps"]) == 5
        assert _lv(v)["ok"] and _lv(v)["last_tp"] == 4410.0

    def test_goldking_slash_zone(self):
        v = _sig(GOLDKING_SLASH_SELL)
        assert v["direction"] == "SELL"
        assert abs(v["entry"] - 4282.0) < 1e-9   # zona o'rtasi
        assert v["sl"] == 4290.0
        assert v["tps"][0] == 4277.0
        assert _lv(v)["ok"]

    def test_goldking_underscore_zone(self):
        v = _sig(GOLDKING_UNDERSCORE_BUY)     # XAUUSD_BUY 4388_4383
        assert v["direction"] == "BUY"
        assert abs(v["entry"] - 4385.5) < 1e-9
        assert v["sl"] == 4378.0
        assert v["tps"][0] == 4392.0          # 392 pips EMAS — to'g'ri narx
        assert _lv(v)["ok"] and _lv(v)["last_tp"] == 4408.0

    def test_goldking_broken_sl_rejected(self):
        """SL 1064+ pip — kanal xatosi; savdo OCHILMASLIGI kerak."""
        v = _sig(GOLDKING_BROKEN_SL)
        assert v["sl"] == 4249.0              # parse bo'ladi...
        lv = _lv(v)
        assert not lv["ok"]                    # ...lekin xavfsizlik radi

    def test_bullgold_6_tp(self):
        v = _sig(BULLGOLD_6TP)
        assert v["direction"] == "BUY" and v["entry"] == 4132.0
        assert v["sl"] == 4122.0
        assert v["tps"] == [4134.0, 4136.0, 4138.0, 4140.0, 4142.0, 4144.0]
        lv = _lv(v)
        assert lv["ok"] and len(lv["tps"]) == 6    # 6 TP yo'qolmaydi

    def test_rahimbfx_buy_now(self):
        v = _sig(RAHIMB_BUY)
        assert v["direction"] == "BUY" and v["entry"] == 4364.0
        assert v["sl"] == 4351.0
        assert v["tps"][0] == 4367.0          # "TP 4367" ≠ 367 pips!
        assert _lv(v)["ok"] and _lv(v)["last_tp"] == 4379.0

    def test_xauusdsingle0_6_tp(self):
        v = _sig(XAUUSD0_6TP)
        assert v["direction"] == "SELL" and v["entry"] == 4315.0
        assert v["sl"] == 4328.0
        assert len(v["tps"]) == 6
        assert _lv(v)["ok"] and _lv(v)["last_tp"] == 4297.0


# --------------------------------------------------------------------------- #
class TestNonSignals:
    def test_tp_hit_result_not_signal(self):
        v = strict_verdict("TP1 HIT 40+PIPS PROFIT ✅ Done 👍🤑")
        assert v["verdict"] != "SIGNAL"

    def test_vip_reklama_not_signal(self):
        v = strict_verdict("VIP KANALIMIZDA 7 KUNDA 2400+ PIPS ✔️✔️")
        assert v["verdict"] != "SIGNAL"

    def test_broker_ad_not_signal(self):
        v = strict_verdict("BROKER BONUS 100% leverage 1:2000 eng yaxshi broker,"
                           " ro'yxatdan o'ting 👉 https://t.me/x")
        assert v["verdict"] != "SIGNAL"
        assert "reklama" in v["flags"]

    def test_direction_without_sl_no_card(self):
        """Yo'nalish+narx bor, lekin aniq SL yo'q — daraja harakati rad."""
        v = strict_verdict("Gold buy 4182 LFG 🚀🚀")
        if v["verdict"] == "SIGNAL":          # verdict SIGNAL bo'lishi mumkin...
            assert not _lv(v)["ok"]            # lekin SLsiz karta/savdo yo'q

    def test_empty_result_ladder_not_signal(self):
        v = strict_verdict("• TP1 +40 pips\n• TP2 +80 pips\n• TP3 +120 pips")
        assert v["verdict"] != "SIGNAL"


# --------------------------------------------------------------------------- #
class TestSafeRegex:
    def test_tp_index_does_not_eat_price(self):
        """'TP 4392' -> 4392 (bir necha yildan beri 392 pips o'qilardi)."""
        m = _TP_ANY.search("TP 4392")
        assert float(m.group(2)) == 4392.0
        m2 = _TP_ANY.search("TP1 4426")
        assert m2.group(1) == "1" and float(m2.group(2)) == 4426.0

    def test_dirpx_lot_not_entry(self):
        assert _DIRPX.search("buy 0.5 lot") is None
        assert _DIRPX.search("buy 50 pip") is None
        m = _DIRPX.search("gold buy now 4364")
        assert m is not None and float(m.group(1)) == 4364.0
        m2 = _DIRPX.search("#XAUUSD BUYY.NOW.4422")
        assert m2 is not None and float(m2.group(1)) == 4422.0


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
