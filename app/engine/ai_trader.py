"""SINO AI treyder — yagona signal manbai (strategiya ovozi YO'Q).

Sodda, kuchli qoidalar: trend + momentum + pullback.
Darvoza/min_voters/whitelist yo'q — AI o'zi kuchlisini tanlaydi.
Barcha coin va barcha timeframe bir xil ko'riladi.
"""
from __future__ import annotations

import pandas as pd

from app.core.enums import Direction, MarketRegime, MTFAlignment, SignalStrength
from app.core.logging import get_logger
from app.engine.scoring import EngineDecision
from app.indicators.bundle import IndicatorBundle
from app.strategies.base import StrategyResult

logger = get_logger(__name__)


def _f(series, i: int = -1, default: float = 0.0) -> float:
    try:
        v = float(series.iloc[i])
        return default if v != v else v
    except Exception:  # noqa: BLE001
        return default


def decide(df: pd.DataFrame, bundle: IndicatorBundle, timeframe: str,
           symbol: str | None, regime: MarketRegime,
           mtf: MTFAlignment = MTFAlignment.NONE) -> EngineDecision:
    """Bozorni AI tahlil qiladi va BUY/SELL/NEUTRAL qaytaradi."""
    checks: list[tuple[str, bool]] = []
    if df is None or len(df) < 40:
        return _none(regime, mtf, "AI: yetarli sham yo'q", checks)

    c = float(bundle.last_close)
    o = _f(bundle.open_)
    atr = bundle.last_atr or max(c * 0.002, 1e-9)
    ema20 = _f(bundle.ema20, default=c)
    ema50 = _f(bundle.ema50, default=c)
    ema200 = _f(bundle.ema200, default=ema50)
    rsi = _f(bundle.rsi, default=50.0)
    macd_h = _f(bundle.macd_hist)
    macd_hp = _f(bundle.macd_hist, -2, macd_h)
    st = _f(bundle.supertrend_dir)
    mom = _f(bundle.momentum_slope)
    vol = _f(bundle.volume, default=1.0)
    vol_ma = _f(bundle.vol_ma, default=1.0) or 1.0
    green = c >= o

    buy = 0.0
    sell = 0.0

    def add(label: str, b_ok: bool, s_ok: bool, w: float = 1.0) -> None:
        nonlocal buy, sell
        if b_ok and not s_ok:
            buy += w
            checks.append((f"AI: {label}", True))
        elif s_ok and not b_ok:
            sell += w
            checks.append((f"AI: {label}", True))
        else:
            checks.append((f"AI: {label} yo'q", False))

    # 1) Trend (EMA200 bo'lmasa EMA50)
    up = (ema50 >= ema200 and c > ema50) or (ema200 == ema50 and c > ema50)
    dn = (ema50 <= ema200 and c < ema50) or (ema200 == ema50 and c < ema50)
    add("Trend", up, dn, 1.2)

    # 2) Supertrend
    add("Supertrend", st > 0, st < 0, 1.1)

    # 3) Momentum
    add("Momentum", macd_h >= macd_hp or mom > 0, macd_h <= macd_hp or mom < 0, 1.0)

    # 4) Sham yo'nalishi
    add("Sham", green, (not green), 0.7)

    # 5) RSI ekstremumga quvlamaslik — lekin signalni o'ldirmaydi
    if rsi >= 78:
        buy -= 0.8
        checks.append(("AI: RSI yuqori — BUY ehtiyot", False))
    elif rsi <= 22:
        sell -= 0.8
        checks.append(("AI: RSI past — SELL ehtiyot", False))
    else:
        add("RSI ishchi zona", 35 <= rsi <= 68, 32 <= rsi <= 65, 0.6)

    # 6) Pullback (quvlamaslik) — bonus, shart emas
    stretched_up = c > ema20 + 1.8 * atr
    stretched_dn = c < ema20 - 1.8 * atr
    if stretched_up:
        buy -= 0.6
        checks.append(("AI: narx uzoq (quvlamaslik)", False))
    elif stretched_dn:
        sell -= 0.6
        checks.append(("AI: narx uzoq (quvlamaslik)", False))
    else:
        add("EMA20 yaqin", c >= ema20 - 0.4 * atr, c <= ema20 + 0.4 * atr, 0.5)

    if vol >= vol_ma * 0.8:
        if green:
            buy += 0.3
        else:
            sell += 0.3
        checks.append(("AI: hajm OK", True))

    # Tarix: faqat og'ir zarar seriyasi — yumshoq
    if symbol:
        try:
            from app.engine.brain import get_brain
            veto = get_brain().should_veto(symbol, timeframe, "BUY" if buy > sell else "SELL")
            if veto and buy > sell:
                buy -= 1.0
                checks.append(("AI: bu juftlikda BUY tarixi yomon", False))
            elif veto:
                sell -= 1.0
                checks.append(("AI: bu juftlikda SELL tarixi yomon", False))
        except Exception:  # noqa: BLE001
            pass

    # MTF — faqat bonus, HECH QACHON blok emas
    if mtf == MTFAlignment.ALIGNED:
        if buy > sell:
            buy += 0.4
        elif sell > buy:
            sell += 0.4
        checks.append(("AI: yuqori TF qo'llab-quvvatlaydi", True))
    elif mtf == MTFAlignment.AGAINST:
        checks.append(("AI: yuqori TF qarshi (blok emas)", False))

    edge = 0.35
    need = 1.6
    direction = Direction.NEUTRAL
    pts = 0.0
    if buy >= need and buy >= sell + edge:
        direction = Direction.BUY
        pts = buy
    elif sell >= need and sell >= buy + edge:
        direction = Direction.SELL
        pts = sell

    if direction == Direction.NEUTRAL:
        logger.info("[AI] %s %s NEUTRAL buy=%.1f sell=%.1f", symbol, timeframe, buy, sell)
        return _none(regime, mtf, f"AI kutmoqda (BUY {buy:.1f} / SELL {sell:.1f})", checks)

    extra = max(0.0, pts - need)
    score = round(min(9.5, 6.2 + extra * 0.55), 2)
    conf = round(min(95.0, 62 + extra * 8), 1)
    reason = (
        f"AI {direction.value}: {pts:.1f} ball • {timeframe} • "
        f"RSI {rsi:.0f} • trend {'yuqori' if up else ('past' if dn else 'neytral')}"
    )
    try:
        from app.engine.brain import get_brain
        get_brain().last_comment = reason
        get_brain().last_vote = direction.value
    except Exception:  # noqa: BLE001
        pass

    res = StrategyResult(
        name="brain", display_name="SINO AI", signal=direction,
        score=score, confidence=conf, reason=reason, checks=checks,
        indicators={"buy": round(buy, 2), "sell": round(sell, 2), "RSI": round(rsi, 1)},
    )
    strength = (
        SignalStrength.STRONG if score >= 8.5 else
        SignalStrength.GOOD if score >= 7 else SignalStrength.WEAK
    )
    logger.info("[AI] %s %s %s score=%.1f (%s)", symbol, timeframe, direction.value, score, reason)
    return EngineDecision(
        direction=direction, score=score, confidence=conf, strength=strength,
        buy_power=round(buy, 2), sell_power=round(sell, 2),
        buy_voters=1 if direction == Direction.BUY else 0,
        sell_voters=1 if direction == Direction.SELL else 0,
        regime=regime, mtf=mtf, mtf_votes=[],
        results=[res], checks=checks,
        passes_threshold=True, block_reason="",
    )


def _none(regime, mtf, reason, checks) -> EngineDecision:
    res = StrategyResult(
        name="brain", display_name="SINO AI", signal=Direction.NEUTRAL,
        score=0, confidence=0, reason=reason, checks=checks,
    )
    return EngineDecision(
        direction=Direction.NEUTRAL, score=0, confidence=0,
        strength=SignalStrength.NO_TRADE,
        buy_power=0, sell_power=0, buy_voters=0, sell_voters=0,
        regime=regime, mtf=mtf, mtf_votes=[],
        results=[res], checks=checks,
        passes_threshold=False, block_reason=reason,
    )
