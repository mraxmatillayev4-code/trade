"""SINO mahalliy AI — API kalitsiz.

Inson kabi fikrlaydi:
  • yangi signalga OVOZ beradi (trend, struktura, pullback, hajm, S/R)
  • yopilgan bitimlardan XATO/FOYDANI o'rganadi (vazn + veto, recency)
  • 2R dan keyin momentum kuchli bo'lsa 3R ga qoldiradi
Hech qanday tashqi API / kalit yo'q.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock

import pandas as pd

from app.core.enums import Direction, MarketRegime
from app.core.logging import get_logger
from app.indicators.bundle import IndicatorBundle
from app.strategies.base import StrategyResult

logger = get_logger(__name__)

_MIN_SAMPLE_WEIGHT = 8
_MIN_SAMPLE_VETO = 10
_LOCK = Lock()


@dataclass
class _Bucket:
    n: int = 0
    wins: int = 0
    losses: int = 0
    sum_r: float = 0.0
    last_results: list[str] = field(default_factory=list)  # "W"/"L"/"B"

    @property
    def wr(self) -> float:
        d = self.wins + self.losses
        return (self.wins / d) if d else 0.5

    @property
    def avg_r(self) -> float:
        return (self.sum_r / self.n) if self.n else 0.0

    @property
    def decided(self) -> int:
        return self.wins + self.losses


def _recency_wr(b: _Bucket) -> float:
    """Oxirgi natijalar og'irroq — yangi xato tezroq seziladi."""
    recent = b.last_results[-8:]
    if not recent:
        return b.wr
    wsum = 0.0
    w = 0.0
    for i, tag in enumerate(recent):
        wt = 1.0 + i * 0.18
        w += wt
        if tag == "W":
            wsum += wt
        elif tag == "B":
            wsum += 0.45 * wt
    return (wsum / w) if w else 0.5


def _hour_bucket(hour: int | None) -> str:
    if hour is None:
        return "unk"
    if 7 <= hour <= 10:
        return "london"
    if 13 <= hour <= 17:
        return "ny"
    if hour <= 5:
        return "asia_dead"
    return "other"


class SinoBrain:
    """Bitta jarayon ichida yashaydigan o'rganuvchi miya."""

    def __init__(self) -> None:
        self._strat: dict[str, _Bucket] = defaultdict(_Bucket)
        self._combo: dict[str, _Bucket] = defaultdict(_Bucket)  # symbol|tf|dir
        self._regime: dict[str, _Bucket] = defaultdict(_Bucket)  # regime|dir
        self._hour: dict[str, _Bucket] = defaultdict(_Bucket)    # bucket|dir
        self._tf: dict[str, _Bucket] = defaultdict(_Bucket)      # tf|dir
        self._notes: list[str] = []
        self.last_comment: str = ""
        self.last_vote: str = "NEUTRAL"
        self.last_fired: list[str] = []
        self._fired_by_combo: dict[str, list[str]] = {}

    # ---------- o'rganish (xato + foyda) ----------
    def learn(self, *, symbol: str, timeframe: str, direction: str,
              regime: str, voter_names: list[str], r: float, result: str,
              hour: int | None = None) -> str:
        """Yopilgan signaldan xulosa. Qaytaradi: o'zbekcha qisqa xulosa."""
        tag = "W" if r > 0.05 else ("L" if r < -0.05 else "B")
        combo = self._ck(symbol, timeframe, direction)
        self._bump(self._combo[combo], r, tag)
        self._bump(self._regime[f"{(regime or '').upper()}|{(direction or '').upper()}"], r, tag)
        self._bump(self._tf[f"{(timeframe or '').lower()}|{(direction or '').upper()}"], r, tag)
        self._bump(self._hour[f"{_hour_bucket(hour)}|{(direction or '').upper()}"], r, tag)
        for name in voter_names:
            self._bump(self._strat[name], r, tag)

        note = self._make_note(symbol, timeframe, direction, r, result, voter_names)
        self._notes.append(note)
        if len(self._notes) > 40:
            self._notes = self._notes[-40:]
        try:
            from app.engine.knowledge import get_knowledge
            fired = self._fired_by_combo.get(self._ck(symbol, timeframe, direction), [])
            extra = get_knowledge().credit(fired, r)
            if extra:
                note = note + " | " + extra[0]
                self._notes.extend(extra)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AI-WEB] credit xato: %s", exc)
        logger.info("[AI] o'rgandi: %s", note)
        return note

    @staticmethod
    def _bump(b: _Bucket, r: float, tag: str) -> None:
        b.n += 1
        b.sum_r += r
        if tag == "W":
            b.wins += 1
        elif tag == "L":
            b.losses += 1
        b.last_results.append(tag)
        if len(b.last_results) > 12:
            b.last_results = b.last_results[-12:]

    def _make_note(self, symbol: str, tf: str, direction: str,
                   r: float, result: str, voters: list[str]) -> str:
        if r < -0.05:
            weak = []
            for n in voters:
                b = self._strat[n]
                if b.n >= 5 and (_recency_wr(b) < 0.42 or b.wr < 0.42):
                    weak.append(n)
            extra = f" Zaif ovozlar: {', '.join(weak)}." if weak else ""
            return (
                f"XATO: {symbol} {tf} {direction} {r:+.2f}R ({result})."
                f"{extra} Keyingi safar shu kombo vazni kamaytiriladi."
            )
        if r > 0.05:
            return (
                f"FOYDA: {symbol} {tf} {direction} {r:+.2f}R. "
                f"Tasdiqlaganlar ({', '.join(voters[:4])}) vazni oshiriladi."
            )
        return f"BE: {symbol} {tf} {direction} {r:+.2f}R — dars: stop himoyasi ishladi."

    # ---------- vazn (strategiyani 'tuzatish') ----------
    def strategy_weight(self, name: str, symbol: str | None = None,
                        timeframe: str | None = None,
                        direction: str | None = None) -> float:
        """1.0 = o'zgarmagan. <1 zaif, >1 kuchli. Kod o'chmaydi — faqat vazn."""
        b = self._strat.get(name)
        w = 1.0
        if b and b.n >= _MIN_SAMPLE_WEIGHT:
            wr = _recency_wr(b)
            avg = b.avg_r
            if wr < 0.32 or avg < -0.20:
                w = 0.28  # deyarli ovozsiz — oxirgi xatolar og'ir
            elif wr < 0.40 or avg < 0:
                w = 0.55
            elif wr > 0.58 and avg > 0.20:
                w = 1.35
            elif wr > 0.50 and avg > 0:
                w = 1.15
        if symbol and timeframe and direction:
            c = self._combo.get(self._ck(symbol, timeframe, direction))
            if c and c.n >= _MIN_SAMPLE_WEIGHT and _recency_wr(c) < 0.36:
                w *= 0.65
        return w

    def should_veto(self, symbol: str, timeframe: str, direction: str) -> str:
        """Yetarli tanlanma + doimiy zarar — signalni to'xtat. Bo'sh xotira = veto yo'q."""
        c = self._combo.get(self._ck(symbol, timeframe, direction))
        if c is None:
            return ""
        rwr = _recency_wr(c)
        if c.n >= _MIN_SAMPLE_VETO and rwr < 0.30 and c.avg_r < 0:
            return (
                f"AI veto: {symbol} {timeframe} {direction} so'nggi {c.n} ta "
                f"bitimda WR {rwr*100:.0f}% / {c.avg_r:+.2f}R — xatolardan o'rganildi"
            )
        recent = c.last_results[-5:]
        if len(recent) >= 5 and all(x == "L" for x in recent):
            return f"AI veto: {symbol} {timeframe} {direction} oxirgi 5 ta bitim zarar"
        return ""

    # ---------- inson kabi ovoz ----------
    def vote(self, df: pd.DataFrame, bundle: IndicatorBundle,
             peer_results: list[StrategyResult], timeframe: str,
             symbol: str | None, regime: MarketRegime) -> StrategyResult:
        """Trend + struktura + pullback + hajm + S/R + tarix — odam treyder kabi."""
        checks: list[tuple[str, bool]] = []
        self.last_comment = "AI: yetarli tarix yo'q"
        self.last_vote = "NEUTRAL"
        if len(df) < 30:
            return self._neutral("AI: yetarli tarix yo'q", checks)

        def _f(series, i: int = -1, default: float = 0.0) -> float:
            try:
                v = float(series.iloc[i])
                return default if v != v else v  # NaN
            except Exception:  # noqa: BLE001
                return default

        c = float(bundle.last_close)
        o = _f(bundle.open_)
        h = _f(bundle.high)
        l = _f(bundle.low)
        atr = bundle.last_atr or 1e-9
        ema20 = _f(bundle.ema20)
        ema50 = _f(bundle.ema50)
        ema200 = _f(bundle.ema200)
        rsi = _f(bundle.rsi, default=50.0)
        macd_h = _f(bundle.macd_hist)
        macd_hp = _f(bundle.macd_hist, -2, macd_h)
        st_dir = _f(bundle.supertrend_dir)
        mom = _f(bundle.momentum_slope)
        vwap = _f(bundle.vwap, default=c)
        vol = _f(bundle.volume)
        vol_ma = _f(bundle.vol_ma, default=1.0) or 1.0
        stoch_k = _f(bundle.stoch_k, default=50.0)
        stoch_d = _f(bundle.stoch_d, default=50.0)
        obv = _f(bundle.obv)
        obv_ma = _f(bundle.obv_ma)
        green = c >= o
        body = abs(c - o)
        rng = max(h - l, 1e-12)
        close_pos = (c - l) / rng  # 1 = yuqori soya, 0 = past

        buy_p = sum(1 for r in peer_results if r.signal == Direction.BUY)
        sell_p = sum(1 for r in peer_results if r.signal == Direction.SELL)

        # Struktura: so'nggi 10 vs oldingi 10
        hh = hl = lh = ll = False
        if len(bundle.high) >= 20:
            h1 = float(bundle.high.iloc[-10:].max())
            h0 = float(bundle.high.iloc[-20:-10].max())
            l1 = float(bundle.low.iloc[-10:].min())
            l0 = float(bundle.low.iloc[-20:-10].min())
            hh, hl = h1 > h0, l1 > l0
            lh, ll = h1 < h0, l1 < l0

        stretched_up = c > ema20 + 1.35 * atr
        stretched_dn = c < ema20 - 1.35 * atr
        near_ema20_up = (not stretched_up) and c >= ema20 - 0.35 * atr
        near_ema20_dn = (not stretched_dn) and c <= ema20 + 0.35 * atr

        support = bundle.support
        resistance = bundle.resistance
        room_up = ((resistance - c) / atr) if resistance else 9.0
        room_dn = ((c - support) / atr) if support else 9.0

        patterns = bundle.candle_patterns or {}
        bull_pat = bool(patterns.get("bullish_engulfing") or patterns.get("hammer"))
        bear_pat = bool(patterns.get("bearish_engulfing") or patterns.get("shooting_star"))

        squeeze_now = False
        squeeze_release = False
        try:
            sq = bundle.squeeze
            squeeze_now = bool(sq.iloc[-1])
            squeeze_release = bool(sq.iloc[-6:-1].any()) and (not squeeze_now)
        except Exception:  # noqa: BLE001
            pass

        bw_exp = False
        try:
            bw = bundle.bb_width
            if len(bw) >= 4:
                bw_exp = float(bw.iloc[-1]) > float(bw.iloc[-4])
        except Exception:  # noqa: BLE001
            pass

        hour = None
        try:
            ot = pd.Timestamp(df.iloc[-1]["open_time"])
            if ot.tzinfo is None:
                ot = ot.tz_localize("UTC")
            hour = int(ot.tz_convert("UTC").hour)
        except Exception:  # noqa: BLE001
            hour = None

        buy_pts = 0.0
        sell_pts = 0.0

        def add(label: str, buy_ok: bool, sell_ok: bool, w: float = 1.0) -> None:
            nonlocal buy_pts, sell_pts
            if buy_ok and not sell_ok:
                buy_pts += w
                checks.append((f"AI BUY: {label}", True))
            elif sell_ok and not buy_ok:
                sell_pts += w
                checks.append((f"AI SELL: {label}", True))
            elif buy_ok and sell_ok:
                checks.append((f"AI: {label} (ikkala tomon)", False))
            else:
                checks.append((f"AI: {label} yo'q", False))

        add("HTF trend (EMA50/200)",
            ema50 > ema200 and c > ema50,
            ema50 < ema200 and c < ema50, 1.4)
        add("EMA50 qiyalik",
            bundle.ema50_slope > 0, bundle.ema50_slope < 0, 0.9)
        add("Supertrend yo'nalishi", st_dir > 0, st_dir < 0, 1.25)
        add("Struktura HH/HL vs LH/LL", hh and hl, lh and ll, 1.3)
        add("Momentum (MACD hist + slope)",
            macd_h >= macd_hp and mom > 0, macd_h <= macd_hp and mom < 0, 1.2)
        add("RSI sog'lom zona",
            40 <= rsi <= 68, 32 <= rsi <= 60, 0.9)
        add("Narxni quvlamaydi (EMA20 yaqin)",
            near_ema20_up, near_ema20_dn, 1.35)
        add("VWAP tomoni",
            c >= vwap and c <= vwap + 1.3 * atr,
            c <= vwap and c >= vwap - 1.3 * atr, 0.85)
        add("Hajm tasdig'i",
            vol >= vol_ma * 0.95 and green,
            vol >= vol_ma * 0.95 and (not green), 1.0)
        add("Yopilish kuchi (sham)",
            close_pos >= 0.62 and green, close_pos <= 0.38 and (not green), 0.8)
        add("S/R xona (≥1 ATR maqsadga)",
            room_up >= 1.0, room_dn >= 1.0, 1.15)
        add("Stochastic yo'nalish",
            stoch_k >= stoch_d and stoch_k < 82,
            stoch_k <= stoch_d and stoch_k > 18, 0.7)
        add("OBV oqimi",
            obv >= obv_ma, obv <= obv_ma, 0.7)
        add("Squeeze chiqishi / kengayish",
            (squeeze_release or bw_exp) and green,
            (squeeze_release or bw_exp) and (not green), 0.85)
        add("Sham shakli (engulf/hammer)", bull_pat, bear_pat, 0.95)
        add("Boshqa strategiyalar ko'pchiligi",
            buy_p > sell_p and buy_p >= 2,
            sell_p > buy_p and sell_p >= 2, 1.25)

        # Ekstremum: odam treyder overbought/oversold da quvlamaydi
        if rsi >= 72:
            buy_pts = max(0.0, buy_pts - 2.4)
            checks.append(("AI: RSI haddan oshgan — BUY ni quvlamaydi", False))
        if rsi <= 28:
            sell_pts = max(0.0, sell_pts - 2.4)
            checks.append(("AI: RSI haddan tushgan — SELL ni quvlamaydi", False))

        # Rejim: trendda davom, range da ekstremumdan qaytish
        if regime == MarketRegime.TRENDING:
            add("Rejim TREND davomi",
                ema50 > ema200 and c > ema20,
                ema50 < ema200 and c < ema20, 0.9)
        elif regime == MarketRegime.RANGING:
            add("Rejim RANGE (chetdan qaytish)",
                rsi < 42 and c <= ema20, rsi > 58 and c >= ema20, 0.9)
        elif regime == MarketRegime.HIGH_VOLATILITY:
            # yuqori volatillikda quvlamaslik muhimroq
            if stretched_up:
                buy_pts = max(0.0, buy_pts - 1.2)
                checks.append(("AI: yuqori volatillikda yuqoriga quvlamaslik", False))
            if stretched_dn:
                sell_pts = max(0.0, sell_pts - 1.2)
                checks.append(("AI: yuqori volatillikda pastga quvlamaslik", False))

        # Tarix darsi (kombo + rejim + soat)
        if symbol:
            cb = self._combo.get(self._ck(symbol, timeframe, "BUY"))
            cs = self._combo.get(self._ck(symbol, timeframe, "SELL"))
            if cb and cb.n >= 6 and _recency_wr(cb) >= 0.52:
                buy_pts += 1.0
                checks.append(("AI: bu juftlikda BUY tarixi yaxshi", True))
            if cs and cs.n >= 6 and _recency_wr(cs) >= 0.52:
                sell_pts += 1.0
                checks.append(("AI: bu juftlikda SELL tarixi yaxshi", True))
            if cb and cb.n >= 6 and _recency_wr(cb) < 0.36:
                buy_pts = max(0.0, buy_pts - 2.2)
                checks.append(("AI: BUY tarixi yomon — xatodan dars", False))
            if cs and cs.n >= 6 and _recency_wr(cs) < 0.36:
                sell_pts = max(0.0, sell_pts - 2.2)
                checks.append(("AI: SELL tarixi yomon — xatodan dars", False))

        rb = self._regime.get(f"{regime.value}|BUY")
        rs = self._regime.get(f"{regime.value}|SELL")
        if rb and rb.n >= 8 and _recency_wr(rb) < 0.38:
            buy_pts = max(0.0, buy_pts - 1.0)
            checks.append((f"AI: {regime.value} da BUY zaif", False))
        if rs and rs.n >= 8 and _recency_wr(rs) < 0.38:
            sell_pts = max(0.0, sell_pts - 1.0)
            checks.append((f"AI: {regime.value} da SELL zaif", False))

        hb = _hour_bucket(hour)
        if hb == "asia_dead":
            # o'lik soat — sifat uchun biroz ehtiyot
            buy_pts *= 0.92
            sell_pts *= 0.92
            checks.append(("AI: o'lik sessiya — ehtiyot", False))

        # Internet darslari (bloklangan dars qo'llanmaydi)
        self.last_fired = []
        try:
            from app.engine.knowledge import get_knowledge
            from app.engine.market_hours import is_traditional
            snap = {
                "timeframe": timeframe,
                "stretched_up": stretched_up, "stretched_dn": stretched_dn,
                "near_ema20_up": near_ema20_up, "near_ema20_dn": near_ema20_dn,
                "rsi_ob": rsi >= 72, "rsi_os": rsi <= 28,
                "htf_buy": ema50 > ema200 and c > ema50,
                "htf_sell": ema50 < ema200 and c < ema50,
                "vol_buy": vol >= vol_ma * 0.95 and green,
                "vol_sell": vol >= vol_ma * 0.95 and (not green),
                "no_room_up": room_up < 1.0, "no_room_dn": room_dn < 1.0,
                "asia_dead": hb == "asia_dead",
                "traditional": bool(symbol and is_traditional(symbol)),
                "squeeze_rel": squeeze_release,
                "green": green,
                "mtf_against": False,
            }
            adj = get_knowledge().apply(snap)
            buy_pts += adj.buy
            sell_pts += adj.sell
            self.last_fired = adj.fired
            for n in adj.notes[:4]:
                checks.append((f"AI-WEB: {n}", True))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AI-WEB] apply xato: %s", exc)

        indicators = {
            "AI_buy_ball": round(buy_pts, 2),
            "AI_sell_ball": round(sell_pts, 2),
            "RSI": round(rsi, 1),
            "peer_BUY": buy_p,
            "peer_SELL": sell_p,
            "room_up_ATR": round(room_up, 2),
            "room_dn_ATR": round(room_dn, 2),
        }

        # Aniq ustunlik: kamida ~4.6 ball va 0.9 farq
        edge = 0.9
        if buy_pts >= 4.6 and buy_pts >= sell_pts + edge:
            extra = max(0.0, buy_pts - 4.6)
            comment = (
                f"BUY {buy_pts:.1f} vs SELL {sell_pts:.1f} • "
                f"{buy_p} strategiya ovozi • RSI {rsi:.0f}"
            )
            self.last_comment = comment
            self.last_vote = "BUY"
            if symbol:
                self._fired_by_combo[self._ck(symbol, timeframe, "BUY")] = list(self.last_fired)
            return StrategyResult(
                name="brain",
                display_name="SINO AI",
                signal=Direction.BUY,
                score=round(min(9.6, 7.2 + extra * 0.35), 2),
                confidence=round(min(96.0, 72 + extra * 5), 1),
                reason=f"AI BUY: {comment}",
                indicators=indicators,
                checks=checks,
            )
        if sell_pts >= 4.6 and sell_pts >= buy_pts + edge:
            extra = max(0.0, sell_pts - 4.6)
            comment = (
                f"SELL {sell_pts:.1f} vs BUY {buy_pts:.1f} • "
                f"{sell_p} strategiya ovozi • RSI {rsi:.0f}"
            )
            self.last_comment = comment
            self.last_vote = "SELL"
            return StrategyResult(
                name="brain",
                display_name="SINO AI",
                signal=Direction.SELL,
                score=round(min(9.6, 7.2 + extra * 0.35), 2),
                confidence=round(min(96.0, 72 + extra * 5), 1),
                reason=f"AI SELL: {comment}",
                indicators=indicators,
                checks=checks,
            )
        self.last_comment = f"NEYTRAL: BUY {buy_pts:.1f} / SELL {sell_pts:.1f} (4.6 kerak)"
        self.last_vote = "NEUTRAL"
        return self._neutral(f"AI NEUTRAL: {self.last_comment}", checks, indicators)

    def _neutral(self, reason: str, checks: list, indicators: dict | None = None) -> StrategyResult:
        return StrategyResult(
            name="brain",
            display_name="SINO AI",
            signal=Direction.NEUTRAL,
            score=0.0,
            confidence=0.0,
            reason=reason,
            indicators=indicators or {},
            checks=checks,
        )

    # ---------- 2R → 3R ----------
    def should_run_3r(self, df: pd.DataFrame, direction: str) -> bool:
        """2R tegdi. Momentum hali kuchlimi? Ha bo'lsa 50% ni 3R ga qoldiramiz."""
        if df is None or len(df) < 8:
            return False
        try:
            from app.core.config import get_settings
            from app.indicators.bundle import compute_bundle
            b = compute_bundle(df, get_settings())
            c = float(b.last_close)
            rsi = float(b.rsi.iloc[-1])
            mom = float(b.momentum_slope.iloc[-1]) if b.momentum_slope is not None else 0.0
            st = float(b.supertrend_dir.iloc[-1]) if b.supertrend_dir is not None else 0.0
            vol = float(b.volume.iloc[-1])
            vol_ma = float(b.vol_ma.iloc[-1]) or 1.0
            ema20 = float(b.ema20.iloc[-1])
            atr = b.last_atr or 1e-9
            macd_h = float(b.macd_hist.iloc[-1])
            closes = df["close"].astype(float)
            hh = bool(closes.iloc[-1] >= closes.iloc[-3:].max())
            ll = bool(closes.iloc[-1] <= closes.iloc[-3:].min())
            pts = 0
            if direction == "BUY":
                pts += int(mom > 0)
                pts += int(st > 0)
                pts += int(rsi < 76)
                pts += int(hh)
                pts += int(vol >= vol_ma * 0.85)
                pts += int(macd_h > 0)
                pts += int(c > ema20 - 0.2 * atr)  # trend uzilmagan
            else:
                pts += int(mom < 0)
                pts += int(st < 0)
                pts += int(rsi > 24)
                pts += int(ll)
                pts += int(vol >= vol_ma * 0.85)
                pts += int(macd_h < 0)
                pts += int(c < ema20 + 0.2 * atr)
            ok = pts >= 4
            logger.info("[AI] 3R qaror %s: %d/7 → %s", direction, pts, ok)
            return ok
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AI] 3R tekshiruvi xato: %s", exc)
            return False

    def latest_notes(self, n: int = 3) -> list[str]:
        return self._notes[-n:]

    def lesson_block(self, limit: int = 4) -> str:
        """Hisobotga: so'nggi xatolar va qaysi strategiya zaif."""
        lines = ["🧠 <b>AI DARSLAR (xatolardan)</b>"]
        weak = []
        strong = []
        for name, b in self._strat.items():
            if b.n >= 5:
                wr = _recency_wr(b)
                if wr < 0.42:
                    weak.append((wr, name, b.n, b.avg_r))
                elif wr > 0.55 and b.avg_r > 0:
                    strong.append((wr, name, b.n, b.avg_r))
        weak.sort()
        strong.sort(reverse=True)
        if weak:
            for wr, name, n, avg in weak[:5]:
                lines.append(f"  🔴 {name}: WR {wr*100:.0f}% ({n} ta, {avg:+.2f}R) — vazn tushirilgan")
        else:
            lines.append("  ✅ Hali yetarli zarar namunasi yo'q — o'rganish davom etadi.")
        for wr, name, n, avg in strong[:3]:
            lines.append(f"  🟢 {name}: WR {wr*100:.0f}% ({n} ta, {avg:+.2f}R) — vazn oshirilgan")
        for note in self._notes[-limit:]:
            icon = "💥" if note.startswith("XATO") else ("🏆" if note.startswith("FOYDA") else "🔵")
            lines.append(f"  {icon} {note}")
        try:
            from app.engine.knowledge import get_knowledge
            lines.append(get_knowledge().summary(6))
        except Exception:
            pass
        return "\n".join(lines)

    async def hydrate_from_db(self, session) -> int:
        """Render qayta ochilganda yopilgan signallardan xotirani qayta tiklaydi."""
        from sqlalchemy import select
        from app.database.models.signal import Signal, SignalConfirmation
        stmt = (
            select(Signal)
            .where(Signal.is_active.is_(False), Signal.r_multiple.isnot(None))
            .order_by(Signal.closed_at.asc())
            .limit(800)
        )
        rows = list((await session.execute(stmt)).scalars().all())
        if not rows:
            logger.info("[AI] bazada yopilgan signal yo'q — xotira bo'sh")
            return 0
        ids = [s.id for s in rows]
        confs = list((await session.execute(
            select(SignalConfirmation).where(SignalConfirmation.signal_id.in_(ids))
        )).scalars().all())
        by_sig: dict[int, list[str]] = {}
        dir_by = {s.id: s.direction for s in rows}
        for c in confs:
            if c.direction != dir_by.get(c.signal_id):
                continue
            by_sig.setdefault(c.signal_id, []).append(c.strategy_name)
        n = 0
        for s in rows:
            r = float(s.r_multiple or 0)
            result = "WIN" if r > 0.05 else ("LOSS" if r < -0.05 else "BE")
            hour = None
            try:
                dt = s.closed_at or s.created_at
                if dt is not None:
                    if dt.tzinfo is None:
                        hour = dt.hour
                    else:
                        hour = dt.utctimetuple().tm_hour
            except Exception:  # noqa: BLE001
                hour = None
            self.learn(
                symbol=s.symbol, timeframe=s.timeframe, direction=s.direction,
                regime=s.regime or "", voter_names=by_sig.get(s.id, []),
                r=r, result=result, hour=hour,
            )
            n += 1
        logger.info("[AI] xotira tiklandi: %d ta yopilgan signaldan o'rgandi", n)
        return n

    @staticmethod
    def _ck(symbol: str, tf: str, direction: str) -> str:
        return f"{(symbol or '').upper()}|{(tf or '').lower()}|{(direction or '').upper()}"


_BRAIN: SinoBrain | None = None


def get_brain() -> SinoBrain:
    global _BRAIN
    with _LOCK:
        if _BRAIN is None:
            _BRAIN = SinoBrain()
        return _BRAIN
