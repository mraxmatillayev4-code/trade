"""Ko'p strategiyali yig'ma scoring va signal qarori."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.core.config import Settings
from app.core.enums import (
    ALL_STRATEGY_KEYS,
    Direction,
    MarketRegime,
    MTFAlignment,
    QualityMode,
    SignalStrength,
)
from app.strategies.base import StrategyResult

# Bozor rejimiga qarab strategiya vaznini moslashtirish
REGIME_WEIGHT_MULT: dict[MarketRegime, dict[str, float]] = {
    MarketRegime.TRENDING: {
        "ema_trend": 1.15, "supertrend": 1.15, "vwap": 0.9,
        "breakout": 1.0, "divergence": 0.75,
        "squeeze": 1.1, "ichimoku": 1.2,
        "price_action": 1.05, "stochastic": 0.85, "obv": 1.0,
        "wavetrend": 0.95, "squeeze_breakout": 1.1,
        "ema_pullback": 1.1, "supertrend_pullback": 1.15, "trend_momentum": 1.1,
        "smart_money": 1.05, "brain": 1.25,
    },
    MarketRegime.RANGING: {
        "ema_trend": 0.6, "supertrend": 0.6, "vwap": 1.05,
        "breakout": 0.7, "divergence": 1.15,
        "squeeze": 1.2, "ichimoku": 0.65,
        "price_action": 1.0, "stochastic": 1.2, "obv": 0.85,
        "wavetrend": 1.25, "squeeze_breakout": 1.15,
        "ema_pullback": 0.7, "supertrend_pullback": 0.7, "trend_momentum": 0.75,
        "smart_money": 1.2, "brain": 1.2,
    },
    MarketRegime.HIGH_VOLATILITY: {
        "ema_trend": 0.9, "supertrend": 0.9, "vwap": 0.9,
        "breakout": 1.15, "divergence": 1.0,
        "squeeze": 0.95, "ichimoku": 0.95,
        "price_action": 1.05, "stochastic": 0.9, "obv": 1.1,
        "wavetrend": 1.05, "squeeze_breakout": 1.1,
        "ema_pullback": 0.9, "supertrend_pullback": 0.9, "trend_momentum": 0.95,
        "smart_money": 1.1, "brain": 1.1,
    },
    MarketRegime.LOW_VOLATILITY: {
        "ema_trend": 0.85, "supertrend": 0.85, "vwap": 0.95,
        "breakout": 0.55, "divergence": 0.9,
        "squeeze": 1.15, "ichimoku": 0.9,
        "price_action": 0.95, "stochastic": 0.9, "obv": 0.9,
        "wavetrend": 1.2, "squeeze_breakout": 1.15,
        "ema_pullback": 0.85, "supertrend_pullback": 0.85, "trend_momentum": 0.9,
        "smart_money": 1.0, "brain": 1.15,
    },
}

# Minimal tasdiqlovchi strategiyalar soni — foydalanuvchi qoidasi:
# 12 strategiyadan kamida 3-4 tasi bir xil yo'nalishni bersa signal chiqadi.
MIN_VOTERS = {
    QualityMode.AGGRESSIVE: 3,
    QualityMode.BALANCED: 3,
    QualityMode.CONSERVATIVE: 4,
}

# Minimal ishonch (conviction) darajasi — strategiyalarning o'rtacha sifati
MIN_CONVICTION = {
    QualityMode.AGGRESSIVE: 5.8,
    QualityMode.BALANCED: 6.2,
    QualityMode.CONSERVATIVE: 7.0,
}

# Timeframe bo'yicha ball tuzatish: past (shovqinli) TF qattiqroq, yuqori TF ishonchliroq
TF_SCORE_ADJUST = {
    "5m": -0.35,
    "15m": -0.10,
    "30m": -0.05,
    "1h": 0.15,
    "4h": 0.25,
}

# Timeframe bo'yicha minimal tasdiqlovchi strategiyalar soni
# (asosiy qoida 3-4 ovoz; past TF ham shu chegarada baholanadi)
TF_MIN_VOTERS = {
    "5m": 3,
    "15m": 3,
    "30m": 3,
    "1h": 3,
    "4h": 3,
}

# Timeframe bo'yicha minimal conviction (strategiyalarning o'rtacha sifati)
TF_MIN_CONVICTION = {
    "5m": 6.8,
    "15m": 6.5,
    "30m": 6.3,
    "1h": 6.0,
    "4h": 6.0,
}

# Bu timeframe'lar yuqori timeframe trendi aynan TASDIQLAGANDAGINA signal beradi
# (kechikkan kontr-harakatli kirishlarni kesadi).
TF_MTF_REQUIRED = {"30m": True}

# Professional konfluentlik: strategiyalar guruhlari
TREND_STRATS = {"ema_trend", "supertrend", "ichimoku", "breakout"}
REVERSION_STRATS = {
    "vwap", "divergence", "stochastic", "squeeze", "obv", "price_action",
    "smart_money", "cvd",
}

# Faol savdo sessiyalari (kill zones), UTC soat:
# London ochilishi ~07-10 UTC, Nyu-York ochilishi ~13-17 UTC
# (Toshkent UTC+5: London ~12-15, NY ~18-22). O'lik tungi soatlar kesiladi.
def _in_killzone(utc_hour: int) -> bool:
    return (7 <= utc_hour <= 10) or (13 <= utc_hour <= 17)


@dataclass
class EngineDecision:
    direction: Direction
    score: float
    confidence: float
    strength: SignalStrength
    buy_power: float
    sell_power: float
    buy_voters: int
    sell_voters: int
    regime: MarketRegime
    mtf: MTFAlignment
    mtf_votes: list[tuple[str, str]]
    results: list[StrategyResult] = field(default_factory=list)
    checks: list[tuple[str, bool]] = field(default_factory=list)
    passes_threshold: bool = False
    block_reason: str = ""


def _strength(score: float) -> SignalStrength:
    if score < 5:
        return SignalStrength.NO_TRADE
    if score < 7:
        return SignalStrength.WEAK
    if score < 9:
        return SignalStrength.GOOD
    return SignalStrength.STRONG


def aggregate(results: list[StrategyResult], regime: MarketRegime,
              mtf: MTFAlignment, mtf_votes: list[tuple[str, Direction]],
              settings: Settings, timeframe: str,
              active_keys: set[str] | None = None,
              candle_time: datetime | None = None,
              symbol: str | None = None) -> EngineDecision:
    weights = settings.strategy_weights
    regime_mult = REGIME_WEIGHT_MULT.get(regime, {})

    buy_power = 0.0
    sell_power = 0.0
    total_w = 0.0
    buy_voters = 0
    sell_voters = 0

    for r in results:
        if active_keys and r.name not in active_keys:
            continue
        w = weights.get(r.name, 1.0) * regime_mult.get(r.name, 1.0)
        try:
            from app.engine.brain import get_brain
            w *= get_brain().strategy_weight(r.name, symbol, timeframe)
        except Exception:  # noqa: BLE001
            pass
        total_w += w
        if r.signal == Direction.BUY:
            buy_power += w * r.score
            buy_voters += 1
        elif r.signal == Direction.SELL:
            sell_power += w * r.score
            sell_voters += 1

    direction = Direction.NEUTRAL
    # Spec: BUY va SELL strategiyalar SONI teng bo'lsa → NO SIGNAL
    if buy_voters > 0 and buy_voters == sell_voters:
        direction = Direction.NEUTRAL
    elif buy_power == 0 and sell_power == 0:
        direction = Direction.NEUTRAL
    elif buy_power > sell_power:
        direction = Direction.BUY
    elif sell_power > buy_power:
        direction = Direction.SELL
    else:
        direction = Direction.NEUTRAL

    checks: list[tuple[str, bool]] = []
    score = 0.0
    confidence = 0.0
    block_reason = ""

    if direction != Direction.NEUTRAL:
        power = buy_power if direction == Direction.BUY else sell_power
        voters = buy_voters if direction == Direction.BUY else sell_voters
        opposite_voters = sell_voters if direction == Direction.BUY else buy_voters
        def _w(name: str) -> float:
            base = weights.get(name, 1.0) * regime_mult.get(name, 1.0)
            try:
                from app.engine.brain import get_brain
                return base * get_brain().strategy_weight(name, symbol, timeframe)
            except Exception:  # noqa: BLE001
                return base
        voter_w = sum(_w(r.name) for r in results if r.signal == direction)

        conviction = power / voter_w if voter_w > 0 else 0.0       # 0-10
        dominance = abs(buy_power - sell_power) / total_w if total_w > 0 else 0.0  # 0-10
        n_active = buy_voters + sell_voters
        agreement = voters / n_active if n_active else 0.0

        # Professional konfluentlik: signal yo'nalishida ovoz bergan strategiyalar guruhi
        dir_results = [r for r in results if r.signal == direction]
        trend_voters = sum(1 for r in dir_results if r.name in TREND_STRATS)
        reversion_voters = sum(1 for r in dir_results if r.name in REVERSION_STRATS)

        # Score shkalasi: asosiy — strategiyalarning ishonch darajasi (conviction)
        score = conviction
        score += min(1.5, dominance * 1.2)          # konsensus ustunligi
        score += (agreement - 0.7) * 1.5            # bir ovozdanlik
        # Ko'p strategiya tasdiqlasa ishonch oshadi (10 dan pastda qoladi)
        score += min(1.2, (voters - 1) * 0.35)

        # Rejim bonusi/jarimasi
        if regime == MarketRegime.TRENDING:
            score += 0.3
        if regime == MarketRegime.HIGH_VOLATILITY:
            score -= 0.3

        # Multi-timeframe tasdig'i
        if settings.multi_timeframe_enabled:
            if mtf == MTFAlignment.ALIGNED:
                score += 0.9
                checks.append(("Yuqori timeframe trendi tasdiqlaydi ✅", True))
            elif mtf == MTFAlignment.AGAINST:
                score -= 1.3
                checks.append(("Yuqori timeframe trendi qarshi ⚠️", False))
            else:
                checks.append(("Yuqori timeframe neytral", True))

        # Timeframe tuzatishi: 5m shovqinli — jarima, 1h/4h — bonus
        tf_adj = TF_SCORE_ADJUST.get(timeframe, 0.0)
        if tf_adj != 0.0:
            score += tf_adj

        # Qarshi ovozlar uchun jarima
        if opposite_voters > 0:
            score -= 0.5 * opposite_voters

        # SINO AI: inson-miya rozi bo'lsa bonus, qarshi bo'lsa jarima (bloklamaydi)
        brain = next((r for r in results if r.name == "brain"), None)
        if brain is not None:
            if brain.signal == direction:
                score += 0.55
                checks.append(("🧠 SINO AI yo'nalishni tasdiqladi", True))
            elif brain.signal != Direction.NEUTRAL:
                score -= 0.85
                checks.append(("🧠 SINO AI qarshi ovoz", False))

        score = round(max(0.0, min(10.0, score)), 2)
        confidence = round(min(99.0, score * 10.0), 1)

        # ---------- PROFESSIONAL DARVOZALAR ----------
        # Asosiy qoida: 3-4 strategiya bir xil yo'nalishni tasdiqlasa signal.
        # Qattiq sifat shartlari (qarshi aks-trend, past ishonch) saqlanadi.
        mode = settings.quality_mode
        min_voters = MIN_VOTERS[mode]
        # Har asbob uchun alohida minimal ovoz (shovqinli forex qattiqroq)
        if symbol:
            try:
                from app.strategies.registry import min_voters_for
                min_voters = max(min_voters, min_voters_for(symbol, timeframe))
            except Exception:  # noqa: BLE001
                pass
        min_conv = MIN_CONVICTION[mode]

        if voters < min_voters:
            block_reason = f"Tasdiqlovchi strategiyalar yetarli emas ({voters}/{min_voters})"
        elif mtf == MTFAlignment.AGAINST and timeframe == "5m" and voters < 4:
            # Faqat 5m da qattiq MTF bloki; 15m/1h/4h da jarima (-1.3) yetarli
            block_reason = "5m yuqori timeframe ga qarshi — kontr-harakat bloklandi"
        elif conviction < min_conv:
            block_reason = f"Strategiyalar ishonchi past (conviction {conviction:.1f}/{min_conv:.1f})"
        elif score < settings.min_score():
            block_reason = (
                f"Umumiy signal kuchi past (score {score:.1f}/{settings.min_score():.1f})"
            )
        elif confidence < 58:
            block_reason = f"Ishonch darajasi past ({confidence:.0f}% < 58%)"
        elif getattr(settings, "killzone_filter", True) and candle_time is not None:
            hour = candle_time.astimezone(timezone.utc).hour if candle_time.tzinfo else candle_time.hour
            weak_setup = voters < 4 and score < 8.2
            crypto = False
            if symbol:
                try:
                    from app.engine.market_hours import is_traditional
                    crypto = not is_traditional(symbol)
                except Exception:  # noqa: BLE001
                    crypto = False
            # 15m asosiy foydali uya — killzone faqat 5m shovqinni kesadi
            if (not crypto) and timeframe == "5m" and not _in_killzone(hour) and weak_setup:
                block_reason = f"{timeframe} 3-ovoz signal faol sessiyadan tashqarida (London/NY kutilmoqda)"

        # Conservative rejim: biroz qattiqroq (4 ovoz + yuqori ball)
        if not block_reason and mode == QualityMode.CONSERVATIVE:
            if voters < 4:
                block_reason = "Conservative: kamida 4 strategiya tasdig'i kerak"
            elif score < 8.0:
                block_reason = "Conservative: score 8.0 dan yuqori bo'lishi shart"

    threshold = settings.min_score()
    passes = (
        direction != Direction.NEUTRAL
        and score >= threshold
        and not block_reason
    )

    # Yig'ma tasdiq qatori (signal kartasi uchun)
    for r in results:
        mark = "✅" if r.signal == direction and direction != Direction.NEUTRAL else (
            "❌" if r.signal != Direction.NEUTRAL else "➖"
        )
        checks.append((f"{r.display_name} {mark}", r.signal == direction))

    return EngineDecision(
        direction=direction,
        score=score,
        confidence=confidence,
        strength=_strength(score),
        buy_power=round(buy_power, 2),
        sell_power=round(sell_power, 2),
        buy_voters=buy_voters,
        sell_voters=sell_voters,
        regime=regime,
        mtf=mtf,
        mtf_votes=[(tf, d.value) for tf, d in mtf_votes],
        results=results,
        checks=checks,
        passes_threshold=passes,
        block_reason=block_reason,
    )
