"""Coin nomlari testi."""
from app.core.symbols import coin_name, full_label, pair_display, split_symbol


def test_split_symbol():
    assert split_symbol("SOLUSDT") == ("SOL", "USDT")
    assert split_symbol("BTCUSDT") == ("BTC", "USDT")
    assert split_symbol("ETHBTC") == ("ETH", "BTC")


def test_pair_display():
    assert pair_display("SOLUSDT") == "SOL/USDT"
    assert pair_display("BTCUSDT") == "BTC/USDT"


def test_coin_name():
    assert coin_name("SOLUSDT") == "Solana"
    assert coin_name("BTCUSDT") == "Bitcoin"
    assert coin_name("ETHUSDT") == "Ethereum"
    assert coin_name("DOGEUSDT") == "Dogecoin"


def test_full_label():
    assert full_label("SOLUSDT") == "SOL/USDT (Solana)"
    assert full_label("XRPUSDT") == "XRP/USDT (XRP (Ripple))"
    # Noma'lum ramz — buzilmaydi
    assert pair_display("NEWCOINUSDT") == "NEWCOIN/USDT"
