"""v108: lot/pip kalkulyatori — ANIQ formula testlari (oltin XAUUSD).

Konvensiya (bot kodi bilan bir xil):
    1 pip = 0.1$ narx harakati, 1 lot = 100 untsiya
    ⇒ $ = pip × lot × 10
"""
from decimal import Decimal

from app.bot.handlers import calc as M
from app.bot.handlers.calc import CONTRACT, PIP_PRICE, pip_value_usd, usd_for


def test_router_registered():
    """v108: handler routeri to'g'ri nom bilan yaratilgan."""
    assert M.router.name == "calc"


def test_pip_consts():
    assert PIP_PRICE == Decimal("0.1")   # 1 pip = 0.1$ (XAU konvensiya)
    assert CONTRACT == Decimal("100")    # 1 lot = 100 untsiya


def test_usd_basic():
    assert usd_for("0.01", "50") == Decimal("5.00")
    assert usd_for("0.01", "10") == Decimal("1.00")
    assert usd_for("0.10", "50") == Decimal("50.00")
    assert usd_for("1.00", "50") == Decimal("500.00")


def test_usd_fractional_pips():
    assert usd_for("0.01", "12.5") == Decimal("1.25")
    assert usd_for("0.03", "33") == Decimal("9.90")


def test_usd_no_float_error():
    # float'da 0.1*0.07*100 kabi ko'paytmalar 2.0999999... chiqardi —
    # Decimal'da ANIQ 2.10:
    assert usd_for("0.07", "3") == Decimal("2.10")
    assert usd_for("0.03", "7") == Decimal("2.10")
    assert usd_for("0.01", "150") == Decimal("15.00")


def test_usd_rounding_half_up():
    # 0.005$ — yarmidan YUQORIGA (bankir yaxliti emas)
    assert usd_for("0.01", "0.05") == Decimal("0.01")
    assert usd_for("0.01", "1") == Decimal("0.10")


def test_pip_value_per_lot():
    assert pip_value_usd("0.01") == Decimal("0.10")
    assert pip_value_usd("0.1") == Decimal("1.00")
    assert pip_value_usd("1") == Decimal("10.00")


def test_parse_decimal_variants():
    assert M._parse_decimal("0,01") == Decimal("0.01")
    assert M._parse_decimal(" 50 ") == Decimal("50")
    assert M._parse_decimal("salom") is None
    assert M._parse_decimal("") is None


def test_money_format():
    assert M._money(Decimal("5.00")) == "5.00"
    assert M._money(Decimal("1234.50")) == "1,234.50"
    assert M._money(Decimal("0.001")) == "0.001"
