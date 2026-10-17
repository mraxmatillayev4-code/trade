"""Signal tushuntirish matnini yaratadi (Why? tugmasi uchun)."""
from __future__ import annotations

from app.core.enums import MarketRegime
from app.core.serialize import dumps as _dumps_json
from app.engine.market_regime import REGIME_UZ
from app.engine.scoring import EngineDecision


def build_explanation(symbol: str, timeframe: str, decision: EngineDecision) -> str:
    lines = [
        f"<b>📝 NIMA UCHUN SIGNAL?</b>",
        f"<b>{symbol}</b> • {timeframe.upper()} • {decision.direction.value}",
        "━━━━━━━━━━━━━━━━",
        f"📈 Bozor rejimi: {REGIME_UZ.get(decision.regime, decision.regime.value)}",
        f"🔗 Multi-timeframe: {decision.mtf.value}",
    ]
    try:
        from app.engine.brain import get_brain
        br = get_brain()
        if br.last_comment:
            lines += ["", f"🧠 <b>SINO AI:</b> {br.last_comment}"]
    except Exception:  # noqa: BLE001
        pass
    if decision.mtf_votes:
        for tf, d in decision.mtf_votes:
            lines.append(f"   • {tf.upper()} → {d}")
    lines.append("━━━━━━━━━━━━━━━━")
    lines.append("<b>Strategiya tafsilotlari:</b>")
    for r in decision.results:
        icon = {"BUY": "🟢", "SELL": "🔴", "NEUTRAL": "⚪"}[r.signal.value]
        lines.append(f"{icon} <b>{r.display_name}</b>: {r.score:.1f}/10")
        for key, val in r.indicators.items():
            if val is not None:
                lines.append(f"   • {key}: {val}")
        lines.append(f"   <i>{r.reason}</i>")
    lines.append("━━━━━━━━━━━━━━━━")
    lines.append(
        f"Yakuniy ball: <b>{decision.score:.2f}/10</b> • "
        f"ishonch: {decision.confidence:.0f}% • {decision.strength.value}"
    )
    lines.append("⚠️ Faqat tahliliy ma'lumot — moliyaviy tavsiya emas.")
    return "\n".join(lines)


def build_checks_json(decision: EngineDecision) -> str:
    """Telegram kartasidagi tasdiq qatorlari uchun JSON."""
    data = [
        {"label": label, "passed": passed, "source": "ai"}
        for label, passed in decision.checks
    ]
    return _dumps_json(data)
