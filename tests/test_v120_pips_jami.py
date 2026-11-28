"""v120: JAMI pip (2 lot yig'indisi) — eski o'rtacha emas."""
from app.notifications.telegram import signal_pips


class _S:
    symbol = "XAUUSDT"
    direction = "SELL"
    entry = 4131.97
    close_price = 4117.5   # avg(4120, 4115)
    close_reason = "TP2"


def test_jami_pips_2_lot():
    pips, win = signal_pips(_S())
    # mean move 14.47 -> 144.7 avg -> JAMI = 289.4
    assert pips == 289.4 and win is True


def test_jami_pips_buy_yoqtiradi():
    class B(_S):
        direction = "BUY"
        entry = 4150.00
        close_price = 4157.0   # +7$ harakat
    pips, win = signal_pips(B())
    # 7 / 0.1 = 70 avg -> JAMI 140
    assert pips == 140.0 and win is True


def test_none_input():
    class C(_S):
        close_price = None
    assert signal_pips(C()) == (None, None)
