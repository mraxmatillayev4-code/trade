"""v109: yangi qoidalar testlari.

TALABLAR (user rasm boshi: 'mana bu senga eng katta vazifa'):
  * Signal FAQAT aniq kirish + aniq SL bo'lsa yaratiladi (SL yo'q = signal yo'q);
  * TP aytilgan bo'lsa — hammasi (≤5), aytilmagan bo'lsa SL nisbati 1:3/1:4/1:5;
  * 2 lot ham OXIRGI TP da yopiladi (last_tp);
  * Reklama/broker postlari (JustMarkets) hech qachon signal bo'lmaydi;
  * Nosog'lom darajalar (teskari SL, juda uzoq SL) — signal EMAS.
"""
from __future__ import annotations

import importlib


def _sizing():
    return importlib.import_module("app.engine.sizing")


def _channel_real():
    return importlib.import_module("app.services.channel_real")


# ---------------------------------------------------------------- darajalar
def test_channel_levels_ok_with_all_tps():
    s = _sizing()
    r = s.channel_signal_levels(
        "BUY", 4190.0, 4185.0, [4195.0, 4199.0, 4203.0, 4000.0], "XAUUSD")
    assert r["ok"] is True
    assert r["tps_src"] == "CHANNEL"
    # nosog'lom (teskari) TP tashlab yuboriladi; yaqindan uzoqqa
    assert r["tps"] == [4195.0, 4199.0, 4203.0]
    assert r["last_tp"] == 4203.0


def test_channel_levels_r345_when_no_tp():
    s = _sizing()
    r = s.channel_signal_levels("BUY", 4200.0, 4199.0, [], "XAUUSD")
    assert r["ok"] is True
    assert r["tps_src"] == "R345"
    # dist = 1.0 → 3R, 4R, 5R
    assert r["tps"] == [4203.0, 4204.0, 4205.0]
    assert r["last_tp"] == 4205.0


def test_channel_levels_sell_r345():
    s = _sizing()
    r = s.channel_signal_levels("SELL", 4200.0, 4201.0, None, "XAUUSD")
    assert r["ok"] is True
    assert r["tps_src"] == "R345"
    assert r["tps"] == [4197.0, 4196.0, 4195.0]
    assert r["last_tp"] == 4195.0


def test_channel_levels_no_sl_fails():
    s = _sizing()
    for sl in (None, 0.0):
        r = s.channel_signal_levels("BUY", 4200.0, sl, [4210.0], "XAUUSD")
        assert r["ok"] is False
        assert "SL" in r["why"]


def test_channel_levels_wrong_side_sl_fails():
    s = _sizing()
    # BUY, lekin SL kirishdan YUQORIDA (image-2 xatoligi: R xaritasi buzilgan)
    r = s.channel_signal_levels("BUY", 4198.41, 1999.70, [2001.0, 2002.0], "XAUUSD")
    assert r["ok"] is False


def test_channel_levels_huge_sl_fails():
    s = _sizing()
    # 300 pipdan uzoq SL — signal EMAS (pip XAU = 0.1)
    r = s.channel_signal_levels("BUY", 4200.0, 4160.0, [4210.0], "XAUUSD")
    assert r["ok"] is False
    assert "uzoq" in r["why"]


def test_channel_levels_cross_side_tps_dropped():
    s = _sizing()
    # SELL: TP lari kirishdan yuqorida bo'lsa tashlab yuboriladi
    r = s.channel_signal_levels("SELL", 4200.0, 4205.0, [4210.0, 4220.0], "XAUUSD")
    assert r["ok"] is True
    assert r["tps_src"] == "R345"  # sog'lom TP yo'q → nisbatdan hisoblandi
    assert len(r["tps"]) == 3


def test_resanitize_r345_recomputes():
    s = _sizing()
    r = s.resanitize_levels("BUY", 4210.0, 4209.0, 0.0, 0.0, 0.0, "R345", "XAUUSD")
    assert r["ok"] is True
    assert r["tps_src"] == "R345"
    assert r["tp1"] == 4213.0 and r["tp2"] == 4214.0 and r["tp3"] == 4215.0


def test_resanitize_absurd_sl_rejects():
    s = _sizing()
    r = s.resanitize_levels("BUY", 4200.0, 4100.0, 4210.0, 4211.0, 4212.0,
                            "CHANNEL", "XAUUSD")
    assert r["ok"] is False


# ---------------------------------------------------------------- reklama
def test_looks_ad_justmarkets_post():
    cr = _channel_real()
    ad = ("JUST MARKET BROKER REGISTERATION LINK\n"
          "Join our recommend Broker — Leverage upto 1:2000, "
          "Less than 1 pip spread, Fast Execution, Instant Local Bank "
          "withdrawal, Trusted & Regulated Broker, Zero Spread. "
          "join justmakrets from this link. Potnor code to. 1nhd0m4e. "
          "Behind every successful Trader there is an honest broker.")
    assert cr.looks_ad(ad) is True


def test_looks_ad_plain_signal_no():
    cr = _channel_real()
    assert cr.looks_ad("XAUUSD BUY 4195-4193 SL 4190 TP1 4200 TP2 4205") is False
    assert cr.looks_ad("Sell gold now. sl 4205 tp1 4195 tp2 4190") is False


def test_looks_ad_single_word_not_enough():
    cr = _channel_real()
    # bitta "bank" so'zi signalni o'ldirmasligi kerak
    assert cr.looks_ad("Buy now sl 4190 tp 4200. bank holiday ehtiyot bo'ling") is False


# ---------------------------------------------------------------- tracker/risk
def test_last_tp_of_signal_prefers_tps_extra():
    import json
    risk = importlib.import_module("app.engine.risk")

    class _S:  # noqa: D106
        entry = 4200.0
        sl = 4199.0
        tp1, tp2, tp3 = 4201.0, 4202.0, 4203.0
        direction = "BUY"
        tps_extra = json.dumps([4201.0, 4202.0, 4203.0, 4205.5, 4208.0])

    assert risk.last_tp_of_signal(_S()) == 4208.0


def test_last_tp_of_signal_fallback_tp3():
    risk = importlib.import_module("app.engine.risk")

    class _S:  # noqa: D106
        entry = 4200.0
        sl = 4199.0
        tp1, tp2, tp3 = 0.0, 0.0, 4205.0
        direction = "BUY"
        tps_extra = ""

    assert risk.last_tp_of_signal(_S()) == 4205.0


def test_last_tp_of_signal_r_fallback():
    risk = importlib.import_module("app.engine.risk")

    class _S:  # noqa: D106
        entry = 4200.0
        sl = 4199.0
        tp1 = tp2 = tp3 = 0.0
        direction = "BUY"
        tps_extra = "not-json"

    assert risk.last_tp_of_signal(_S()) == risk.r_price("BUY", 4200.0, 4199.0, 5)


def test_tps_of_signal_dedup():
    tg = importlib.import_module("app.notifications.telegram")

    class _S:  # noqa: D106
        tp1, tp2, tp3 = 4201.0, 4202.0, 4202.0
        tps_extra = ""

    assert tg.tps_of(_S()) == [4201.0, 4202.0]


def test_information_only_signal_yo_q():
    """TP aytilmaganida ham R modeliga qaytgani tekshiriladi (tizim tushunishi)."""
    s = _sizing()
    r = s.channel_signal_levels("BUY", 4200.0, 4199.5, None, "XAUUSD")
    assert r["ok"] is True and r["tps_src"] == "R345"
