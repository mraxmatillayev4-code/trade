"""tests/test_v130_advanced_tp_and_private_channel.py — v130 User Qoidalari:
1. TP aytilmagan bo'lsa — 1:3.5 nisbatda bitta TP (3.5R), yoki sozlamadan o'rnatilgan nisbatda.
2. TP ko'p aytilgan bo'lsa — 1:1 TP1 tashlanib, 1:3 ga (yoki sozlamaga) eng yaqin TP tanlanishi.
3. Maxfiy kanallarni ID si orqali (-1004357689041) ulash.
4. TP nisbatini sozlamalardan (1:2.0, 1:2.5, 1:4.0) dinamik o'zgartirish.
"""
import pytest
from app.engine.sizing import select_best_channel_tp
from app.services import entry_settings as ES


def test_tp_not_given_uses_3_5_ratio():
    """TP aytilmagan bo'lsa — aniq 1:3.5 nisbat (3.5R)."""
    # BUY: entry=3520, sl=3515 (risk=5) -> TP = 3520 + 3.5*5 = 3537.50
    tp_buy = select_best_channel_tp("BUY", 3520.0, 3515.0, [])
    assert abs(tp_buy - 3537.50) < 1e-6, f"Expected 3537.50, got {tp_buy}"

    # SELL: entry=3520, sl=3525 (risk=5) -> TP = 3520 - 3.5*5 = 3502.50
    tp_sell = select_best_channel_tp("SELL", 3520.0, 3525.0, None)
    assert abs(tp_sell - 3502.50) < 1e-6, f"Expected 3502.50, got {tp_sell}"


def test_tp_custom_ratio_setting():
    """Foydalanuvchi TP nisbatini 1:2.5 yoki 1:4.0 ga o'zgartirganda o'sha nisbat ishlatiladi."""
    # Custom ratio = 2.5
    tp_custom = select_best_channel_tp("BUY", 4000.0, 3990.0, [], target_ratio=2.5)
    # risk = 10 -> 4000 + 2.5 * 10 = 4025.0
    assert abs(tp_custom - 4025.0) < 1e-6, f"Expected 4025.0, got {tp_custom}"

    # Custom ratio = 4.0
    tp_custom4 = select_best_channel_tp("BUY", 4000.0, 3990.0, [], target_ratio=4.0)
    assert abs(tp_custom4 - 4040.0) < 1e-6, f"Expected 4040.0, got {tp_custom4}"


def test_tp_multiple_picks_closest_to_3r():
    """Ko'p TP bo'lsa — 1:1 o'rniga 1:3 (3R) ga eng yaqin TP tanlanadi."""
    # entry=4000, sl=3995 (risk=5) -> target 3R = 4015.0
    # tps: TP1=4005 (1R), TP2=4010 (2R), TP3=4016 (3.2R), TP4=4030 (6R)
    tps = [4005.0, 4010.0, 4016.0, 4030.0]
    best_tp = select_best_channel_tp("BUY", 4000.0, 3995.0, tps, target_ratio=3.0)
    assert best_tp == 4016.0, f"4015 ga eng yaqin 4016 tanlanishi kerak edi, lekin {best_tp} tanlandi"

    # SELL: entry=4000, sl=4005 (risk=5) -> target 3R = 3985.0
    # tps: [3995.0 (1R), 3990.0 (2R), 3984.0 (3.2R), 3970.0 (6R)]
    best_sell_tp = select_best_channel_tp("SELL", 4000.0, 4005.0, [3995.0, 3990.0, 3984.0, 3970.0], target_ratio=3.0)
    assert best_sell_tp == 3984.0, f"3985 ga eng yaqin 3984 tanlanishi kerak edi, lekin {best_sell_tp} tanlandi"


def test_private_channel_id_parsing():
    """Maxfiy kanallar va guruhlar ID sini (-1004357689041) to'g'ri ajratish."""
    import re

    samples = [
        ("-1004357689041", -1004357689041),
        ("ID: -1004357689041", -1004357689041),
        ("4357689041", -1004357689041),
        ("https://t.me/c/4357689041/123", -1004357689041),
    ]

    for raw_text, expected_id in samples:
        c_link = re.search(r"t\.me/c/(\d+)", raw_text)
        id_match = re.search(r"(-?100\d{8,14}|-\d{8,14}|\b\d{9,14}\b)", raw_text)
        if c_link:
            res_id = -int(f"100{c_link.group(1)}")
        elif id_match:
            raw_id = id_match.group(1)
            if raw_id.startswith("-100"):
                res_id = int(raw_id)
            elif raw_id.startswith("-"):
                res_id = -int(f"100{raw_id[1:]}")
            elif raw_id.startswith("100"):
                res_id = -int(raw_id)
            else:
                res_id = -int(f"100{raw_id}")
        else:
            res_id = None
        assert res_id == expected_id, f"Failed for '{raw_text}': expected {expected_id}, got {res_id}"
