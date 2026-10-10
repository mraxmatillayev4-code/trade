"""Strategiyalar uchun umumiy interfeys."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd

from app.core.serialize import to_jsonable

from app.core.config import Settings
from app.core.enums import Direction
from app.indicators.bundle import IndicatorBundle


@dataclass
class StrategyResult:
    name: str
    display_name: str
    signal: Direction
    score: float            # 0-10
    confidence: float       # 0-100
    reason: str
    indicators: dict = field(default_factory=dict)
    checks: list[tuple[str, bool]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "signal": self.signal.value,
            "score": round(self.score, 2),
            "confidence": round(self.confidence, 1),
            "reason": self.reason,
            "checks": [{"label": c, "passed": p} for c, p in self.checks],
            "indicators": self.indicators,
        }


class BaseStrategy(ABC):
    key: str = "base"
    display_name: str = "Base"
    intraday_only: bool = False

    @abstractmethod
    def analyze(self, df: pd.DataFrame, bundle: IndicatorBundle,
                settings: Settings, timeframe: str) -> StrategyResult:
        ...

    # ---- Yordamchi metodlar ----
    def _neutral(self, reason: str, checks: list[tuple[str, bool]],
                 indicators: dict, partial_score: float = 0.0) -> StrategyResult:
        return StrategyResult(
            name=self.key,
            display_name=self.display_name,
            signal=Direction.NEUTRAL,
            score=round(min(10.0, partial_score), 2),
            confidence=round(min(100.0, partial_score * 10.0), 1),
            reason=reason,
            indicators=to_jsonable(indicators) if indicators else {},
            checks=checks,
        )

    def _result(self, direction: Direction, core_points: float, core_max: float,
                extra_count: int, reason: str,
                checks: list[tuple[str, bool]], indicators: dict) -> StrategyResult:
        """
        Signal faqat BARCHA asosiy (core) shartlar bajarilganda BUY/SELL bo'ladi.

        Score shkalasi (0-10): to'liq core shartlarning o'zi ~7 ball (kuchli, ammo
        "kech emas" kirish); har bajarilgan QO'SHIMCHA sifat tasdig'i +0.6 (maks +2.4).
        Shunday qilib oddiy signal ~7.0, ko'p tasdiqli signal ~8.5-9.4 gacha chiqadi.
        """
        base = 7.0
        bonus = min(2.4, extra_count * 0.6)
        score = min(9.6, base + bonus)
        return StrategyResult(
            name=self.key,
            display_name=self.display_name,
            signal=direction,
            score=round(score, 2),
            confidence=round(min(99.0, score * 10.0), 1),
            reason=reason,
            indicators=to_jsonable(indicators) if indicators else {},
            checks=checks,
        )

    def _tf_allowed(self, timeframe: str) -> bool:
        if not self.intraday_only:
            return True
        return timeframe in ("5m", "15m", "30m")
