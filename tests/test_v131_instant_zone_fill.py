"""Test SINO v131 (User Rule): Kanal aytgan zonaning o'rtasidan emas!
Kanal aytgan zonaning ichiga narx kirishi bilan DARHOL aynan o'sha narxdan kiriladi!
"""

from app.engine.entry import zone_hit


def test_zone_hit_instant_on_entry():
    # 1. JavaFX kabi BUY 3567 - 3562 zonasi:
    # Narx 3566.80 ga tushib zona ichiga kirishi bilan DARHOL shu narxdan kiradi (mid kutmaydi!)
    ok, fill = zone_hit("BUY", 3562.0, 3567.0, 3566.80)
    assert ok is True
    assert fill == 3566.80

    # Narx 3564.00 (zona ichi)
    ok2, fill2 = zone_hit("BUY", 3562.0, 3567.0, 3564.00)
    assert ok2 is True
    assert fill2 == 3564.00

    # Narx 3562.05 (zona pastki chegarasida)
    ok3, fill3 = zone_hit("BUY", 3562.0, 3567.0, 3562.05)
    assert ok3 is True
    assert fill3 == 3562.05

    # Narx zonadan tashqarida (3569.32) bo'lsa kirilmaydi
    ok4, fill4 = zone_hit("BUY", 3562.0, 3567.0, 3569.32)
    assert ok4 is False
    assert fill4 == 0.0


def test_zone_hit_instant_sell():
    # 2. SELL 3570 - 3575 zonasi:
    # Narx 3570.20 ga chiqib zona ichiga kirishi bilan DARHOL shu narxdan SELL
    ok, fill = zone_hit("SELL", 3570.0, 3575.0, 3570.20)
    assert ok is True
    assert fill == 3570.20

    # Narx zonadan tashqarida (3568.0) bo'lsa kirilmaydi
    ok2, fill2 = zone_hit("SELL", 3570.0, 3575.0, 3568.0)
    assert ok2 is False
    assert fill2 == 0.0
