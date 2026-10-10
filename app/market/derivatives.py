"""Derivativlar (fyuchers) ma'lumoti: Funding Rate + Open Interest (OI).

Narx signali "kechikkan/tiqilib qolgan" yoki yo'qligini aniqlaydi:
- Funding juda musbat (>+0.05%/8s) → hamma LONG, long kechikkan.
- Funding juda manfiy (<-0.04%)        → hamma SHORT, short kechikkan.
- Narx ko'tarilib OI tushsa → short-squeeze (mo'rt harakat), trend emas.

Asosiy manba: MEXC Fyuchers (contract.mexc.com) — kalitsiz, BARCHA juftliklar
(kripto va oltin XAU_USDT) uchun ishlaydi, geo-cheklov yo'q.
Xato/ma'lumot yo'q bo'lsa → None (fail-open: filtr shunchaki ishlamaydi).
"""
from __future__ import annotations

import time

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

# Funding chegaralari (8 soatlik stavka, kasr: 0.0005 = 0.05%)
FUNDING_EXTREME_POS = 0.0005
FUNDING_EXTREME_NEG = -0.0004

_CACHE: dict[str, tuple[float, dict]] = {}
_TTL = 300.0  # 5 daqiqa kesh
_BASE = "https://contract.mexc.com"


def to_mexc(symbol: str) -> str:
    """BTCUSDT → BTC_USDT, XAUUSDT → XAU_USDT."""
    s = symbol.upper()
    for q in ("USDT", "USDC", "BUSD"):
        if s.endswith(q) and len(s) > len(q):
            return f"{s[:-len(q)]}_{q}"
    return s


class DerivativesClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=7.0))

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict | None = None):
        try:
            r = await self._client.get(f"{_BASE}{path}", params=params)
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[DERIV] %s ishlamadi: %s", path, exc)
            return None

    async def get_state(self, symbol: str, force: bool = False) -> dict | None:
        sym = symbol.upper()
        now = time.time()
        if not force and sym in _CACHE and now - _CACHE[sym][0] < _TTL:
            return _CACHE[sym][1]

        mx = to_mexc(sym)
        # Funding (aniq endpoint)
        funding = None
        fr = await self._get(f"/api/v1/contract/funding_rate/{mx}")
        if fr and fr.get("success") and fr.get("data"):
            try:
                funding = float(fr["data"]["fundingRate"])
            except (KeyError, TypeError, ValueError):
                funding = None

        # Ticker: joriy OI (holdVol), 24s narx o'zgarishi
        oi_now = price_chg = None
        tk = await self._get("/api/v1/contract/ticker", {"symbol": mx})
        if tk and tk.get("success") and tk.get("data"):
            x = tk["data"]
            try:
                oi_now = float(x.get("holdVol", 0)) or None
                price_chg = float(x.get("riseFallRate", 0)) * 100.0
                if funding is None:
                    funding = float(x.get("fundingRate", 0))
            except (TypeError, ValueError):
                pass

        # OI qisqa trend: ticker keshdagi oldingi qiymat bilan solishtiriladi
        oi_change = None
        if sym in _CACHE:
            prev = _CACHE[sym][1]
            if prev.get("oi_now") and oi_now:
                oi_change = (oi_now - prev["oi_now"]) / prev["oi_now"] * 100.0

        if funding is None and oi_now is None:
            return None
        state = {
            "funding": funding if funding is not None else 0.0,
            "oi_change_pct": oi_change,
            "price_change_pct": price_chg,
            "oi_now": oi_now,
            "source": "MEXC",
        }
        _CACHE[sym] = (now, state)
        return state

    # ---------- Signal darvozasi ----------
    async def check(self, symbol: str, direction: str) -> tuple[bool, str]:
        """(ruxsat, sabab). direction: 'BUY' | 'SELL'. Fail-open."""
        st = await self.get_state(symbol)
        if st is None:
            return True, "derivativ ma'lumot yo'q (tekshirilmadi)"

        funding = st.get("funding")
        oi_chg = st.get("oi_change_pct")
        pc = st.get("price_change_pct") or 0.0

        # 1) Olomon tiqilib qolgan tomonga signal — KECHIKKAN
        if direction == "BUY" and funding is not None and funding > FUNDING_EXTREME_POS:
            return False, (f"Funding juda musbat ({funding*100:.3f}%) — longlar tiqilib "
                           "qolgan (kechikkan long bloklandi)")
        if direction == "SELL" and funding is not None and funding < FUNDING_EXTREME_NEG:
            return False, (f"Funding juda manfiy ({funding*100:.3f}%) — shortlar tiqilib "
                           "qolgan (kechikkan short bloklandi)")

        # 2) Squeeze (mo'rt harakat): narx ketayotgan tomonga OI tushsa
        if oi_chg is not None and oi_chg < -3.0:
            if direction == "BUY" and pc >= 0:
                return False, (f"Narx ko'tarilmoqda-yu OI {oi_chg:.1f}% tushdi — "
                               "short-squeeze, mo'rt (long bloklandi)")
            if direction == "SELL" and pc <= 0:
                return False, (f"Narx tushmoqda-yu OI {oi_chg:.1f}% tushdi — "
                               "long-squeeze, mo'rt (short bloklandi)")

        return True, f"derivativ tasdiq OK (MEXC, funding {funding*100:.3f}%)"
