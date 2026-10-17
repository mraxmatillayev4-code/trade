"""
G'alaba ehtimoli (win probability) — tarixda shu ko'rinishdagi signallar
qancha yutgani asosida foiz hisoblaydi. O'xshashlik: yo'nalish + score bandi.
Tarix yetmasa, strategiya sifati (conviction) bo'yicha asosiy taxmin beriladi.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.signal import Signal


def _band(score: float) -> float:
    return float(int(score))  # butun ball bandi: 5, 6, 7, ...


def estimate_from_score(score: float) -> float:
    """Tarix yo'q bo'lganda soddalashgan baza taxmin (kalibrlangan)."""
    # 5.0 → ~52%, 7.0 → ~62%, 9.0+ → ~75%
    base = 52.0 + (score - 5.0) * 5.5
    return round(max(45.0, min(80.0, base)), 1)


async def win_probability(session: AsyncSession, score: float,
                          direction: str, mtf: str = "") -> float:
    band = _band(score)
    low, high = band - 0.5, band + 1.5

    # 1) Aniq band: yo'nalish + yaqin score
    stmt = select(Signal).where(
        Signal.is_active.is_(False),
        Signal.r_multiple.is_not(None),
        Signal.direction == direction,
        Signal.score >= low,
        Signal.score < high,
    )
    same = list((await session.execute(stmt)).scalars().all())

    if len(same) >= 5:
        wins = sum(1 for s in same if (s.r_multiple or 0) > 0.05)
        return round(wins / len(same) * 100, 1)

    # 2) Kengroq tarix: barcha yopilgan signallar bo'yicha
    stmt2 = select(Signal).where(
        Signal.is_active.is_(False),
        Signal.r_multiple.is_not(None),
    )
    all_closed = list((await session.execute(stmt2)).scalars().all())
    if len(all_closed) < 5:
        return estimate_from_score(score)

    wins_all = sum(1 for s in all_closed if (s.r_multiple or 0) > 0.05)
    base_rate = wins_all / len(all_closed) * 100

    # Score'ga qarab ±9% sozlash
    adjusted = base_rate + (score - 6.0) * 4.5
    # MTF tasdiqlasa +3%
    if mtf == "ALIGNED":
        adjusted += 3.0
    elif mtf == "AGAINST":
        adjusted -= 4.0
    return round(max(40.0, min(85.0, adjusted)), 1)
