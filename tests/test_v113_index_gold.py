# -*- coding: utf-8 -*-
"""v113: BOT ODATIY OLTINNI KUZATSIN — narx manbai MEXC perp o'rniga INDEX.

Xato: MEXC XAU_USDT perpetual lastPrice spot indeksdan ~$3+ yuqori turardi
(hozirgi jonli tekshiruvda: lastPrice 4207.77, indexPrice 4204.48). Kanal
spot narxlar bilan gaplashadi (MT5 brokerlari spot). Shuning uchun tor
SL/TP zonalarida perp premiyasi signal natijasini burardi (SL tegdi
deyapti, aslida spot SL ga bormagan).

Tuzatish: GoldRest — get_ticker_24h/get_last_price endi INDEX narxini
beradi (mavjud bo'lmasa lastPrice), get_klines esa index_price shamlarini
qaytaradi (bo'lmasa perp shamlari — fallback).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from app.market.gold_rest import GoldRest  # noqa: E402


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._p


class _StubClient:
    """Httpx klienti o'rniga: endpoint -> payload xaritasi."""

    def __init__(self, payloads):
        self.payloads = payloads
        self.calls: list[str] = []

    async def get(self, url, params=None):
        self.calls.append(url)
        for key, val in self.payloads.items():
            if key in url:
                if isinstance(val, Exception):
                    raise val
                return _Resp(val)
        raise RuntimeError(f"noma'lum endpoint: {url}")

    async def aclose(self):
        return None


def _kl_payload(n=3):
    return {"success": True, "data": {
        "time": [1_791_649_860 + i * 0 for i in range(n)],      # eski (yopiq)
        "open": [4200.1] * n,
        "high": [4201.0] * n,
        "low": [4199.0] * n,
        "close": [4200.5] * n,
        "vol": [10] * n,
    }}


@pytest.mark.asyncio
async def test_ticker_prefers_index_price():
    gr = GoldRest()
    gr._client = _StubClient({"/api/v1/contract/ticker": {
        "success": True, "code": 0, "data": {
            "symbol": "XAU_USDT", "lastPrice": 4207.77,
            "indexPrice": 4204.48, "fairPrice": 4207.54,
            "lower24Price": 1, "high24Price": 2, "volume24": 1,
            "amount24": 1, "riseFallRate": 0.0,
        }}})
    t = await gr.get_ticker_24h("XAUUSDT")
    assert t["price"] == 4204.48, f"ticker: {t}"
    lp = await gr.get_last_price("XAUUSDT")
    assert lp == 4204.48


@pytest.mark.asyncio
async def test_ticker_fallback_to_last_price():
    gr = GoldRest()
    gr._client = _StubClient({"/api/v1/contract/ticker": {
        "success": True, "code": 0, "data": {
            "symbol": "XAU_USDT", "lastPrice": 4207.77,
            "indexPrice": 0, "fairPrice": 0,
            "lower24Price": 1, "high24Price": 2, "volume24": 1,
            "amount24": 1, "riseFallRate": 0.0,
        }}})
    t = await gr.get_ticker_24h("XAUUSDT")
    assert t["price"] == 4207.77


@pytest.mark.asyncio
async def test_klines_use_index_price_first():
    gr = GoldRest()
    paidx = _kl_payload(3)
    pperp = {"success": True, "data": {
        "time": [1_791_649_860], "open": [9999.0], "high": [9999.0],
        "low": [9999.0], "close": [9999.0], "vol": [1]}}
    gr._client = _StubClient({
        "/api/v1/contract/kline/index_price": paidx,
        "/api/v1/contract/kline/": pperp,
    })
    df = await gr.get_klines("XAUUSDT", "1m", limit=5)
    assert not df.empty
    url0 = gr._client.calls[0]
    assert "index_price" in url0, f"index_price birinchi emas: {url0}"
    assert float(df["close"].iloc[0]) == 4200.5


@pytest.mark.asyncio
async def test_klines_fallback_to_perp_when_index_empty():
    gr = GoldRest()
    gr._client = _StubClient({
        "/api/v1/contract/kline/index_price": {"success": True, "data": {}},
        # faqat umumiy kline ishlaydi — diqqat: tartib! 'index_price' ichida
        # '/kline/' ham bor — stub exact-match qilishi kerak; bu yerda index
        # bo'sh payload qaytaradi
    })
    # stub: kalit nomini aniqroq berish uchun keyingi marta qat'iy match:
    class _C:
        def __init__(self):
            self.calls = []
        async def get(self, url, params=None):
            self.calls.append(url)
            if "index_price" in url:
                return _Resp({"success": True, "data": {}})
            return _Resp(_kl_payload(2))
        async def aclose(self):
            return None
    c = _C()
    gr._client = c
    df = await gr.get_klines("XAUUSDT", "1m", limit=5)
    assert not df.empty
    assert "index_price" in c.calls[0]
    assert "index_price" not in c.calls[1], f"ikkinchi so'rov perp bo'lsin: {c.calls}"


@pytest.mark.asyncio
async def test_index_and_perp_independence():
    """Kalitgacha: joriy MEXC javobida lastPrice vs indexPrice farqi bor
    (jonli rate-limit/so'rovga tayanmaydigan ruxsati yo'q — faqat parse
    logikasi)."""
    d = {"lastPrice": 4207.77, "indexPrice": 4204.48}
    px = float(d.get("indexPrice") or d.get("lastPrice") or 0.0)
    assert px == 4204.48
    assert abs(4207.77 - 4204.48) > 3.0  # perp premiyasi — realtekshiruvdan


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
