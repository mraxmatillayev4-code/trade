"""News & Economic Calendar Filter — Block signals around high-impact events."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import TYPE_CHECKING

import httpx

from app.core.config import Settings
from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.core.enums import Direction

logger = get_logger(__name__)

CACHE_DIR = "cache/news"
CACHE_FILE = os.path.join(CACHE_DIR, "economic_calendar.json")
CACHE_TTL_HOURS = 6

NEWS_API_URL = "https://api.tradingeconomics.com/calendar"
CRYPTO_NEWS_URL = "https://api.coingecko.com/api/v3/events"

HIGH_IMPACT_KEYWORDS = [
    "FOMC", "FED", "FEDERAL RESERVE", "INTEREST RATE", "CPI", "INFLATION",
    "NFP", "NON-FARM PAYROLL", "UNEMPLOYMENT", "GDP", "RETAIL SALES",
    "PMI", "ISM", "CONSUMER CONFIDENCE", "JOLTS", "PCE",
    "ECB", "BOE", "BOJ", "BOC", "RBA", "RBA",
    "CRUDE OIL", "NATURAL GAS", "OPEC",
]

CRYPTO_HIGH_IMPACT = [
    "FOMC", "CPI", "FED", "INTEREST RATE", "ETF", "SEC", "REGULATION",
    "HALVING", "FORK", "UPGRADE", "MAINNET", "LAUNCH",
]

FUNDING_TIMES_UTC = [0, 8, 16]


class EventImpact(Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


@dataclass
class EconomicEvent:
    timestamp: datetime
    currency: str
    event: str
    impact: EventImpact
    actual: str | None
    forecast: str | None
    previous: str | None


@dataclass
class NewsFilterResult:
    allowed: bool
    reason: str
    nearest_event: EconomicEvent | None
    minutes_to_event: int | None
    funding_nearby: bool
    funding_minutes: int | None


_calendar_cache: list[EconomicEvent] | None = None
_cache_timestamp: datetime | None = None


def _load_cache() -> list[EconomicEvent] | None:
    global _calendar_cache, _cache_timestamp
    if _calendar_cache is not None and _cache_timestamp:
        if (datetime.now(timezone.utc) - _cache_timestamp).total_seconds() < CACHE_TTL_HOURS * 3600:
            return _calendar_cache

    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                data = json.load(f)
            _calendar_cache = [
                EconomicEvent(
                    timestamp=datetime.fromisoformat(e["timestamp"]).replace(tzinfo=timezone.utc),
                    currency=e["currency"],
                    event=e["event"],
                    impact=EventImpact(e["impact"]),
                    actual=e.get("actual"),
                    forecast=e.get("forecast"),
                    previous=e.get("previous"),
                )
                for e in data
            ]
            _cache_timestamp = datetime.fromisoformat(data[0]["cached_at"]).replace(tzinfo=timezone.utc)
            return _calendar_cache
        except Exception as exc:
            logger.warning(f"Failed to load news cache: {exc}")

    return None


def _save_cache(events: list[EconomicEvent]) -> None:
    global _calendar_cache, _cache_timestamp
    os.makedirs(CACHE_DIR, exist_ok=True)
    _calendar_cache = events
    _cache_timestamp = datetime.now(timezone.utc)
    try:
        data = {
            "cached_at": _cache_timestamp.isoformat(),
            "events": [
                {
                    "timestamp": e.timestamp.isoformat(),
                    "currency": e.currency,
                    "event": e.event,
                    "impact": e.impact.value,
                    "actual": e.actual,
                    "forecast": e.forecast,
                    "previous": e.previous,
                }
                for e in events
            ],
        }
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f)
    except Exception as exc:
        logger.warning(f"Failed to save news cache: {exc}")


async def fetch_economic_calendar(api_key: str | None = None) -> list[EconomicEvent]:
    """Fetch economic calendar from TradingEconomics or fallback."""
    if not api_key:
        logger.warning("No TradingEconomics API key, using fallback calendar")
        return get_fallback_calendar()

    try:
        url = f"{NEWS_API_URL}?c={api_key}&format=json"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        events = []
        for item in data:
            try:
                dt = datetime.fromisoformat(item["Date"]).replace(tzinfo=timezone.utc)
                impact_str = item.get("Importance", "Low").upper()
                if impact_str == "HIGH":
                    impact = EventImpact.HIGH
                elif impact_str == "MEDIUM":
                    impact = EventImpact.MEDIUM
                else:
                    impact = EventImpact.LOW

                events.append(EconomicEvent(
                    timestamp=dt,
                    currency=item.get("Country", "USD"),
                    event=item.get("Event", ""),
                    impact=impact,
                    actual=item.get("Actual"),
                    forecast=item.get("Forecast"),
                    previous=item.get("Previous"),
                ))
            except Exception:
                continue

        _save_cache(events)
        return events

    except Exception as exc:
        logger.warning(f"Failed to fetch economic calendar: {exc}")
        return get_fallback_calendar()


def get_fallback_calendar() -> list[EconomicEvent]:
    """Generate fallback calendar with known recurring events."""
    events = []
    now = datetime.now(timezone.utc)

    for week_offset in range(8):
        base = now + timedelta(weeks=week_offset)
        base = base.replace(hour=12, minute=30, second=0, microsecond=0)

        events.append(EconomicEvent(
            timestamp=base + timedelta(days=2),  # Wednesday
            currency="USD",
            event="FOMC Minutes / Fed Speakers",
            impact=EventImpact.HIGH,
            actual=None, forecast=None, previous=None,
        ))

        events.append(EconomicEvent(
            timestamp=base + timedelta(days=4),  # Friday
            currency="USD",
            event="Non-Farm Payrolls (Monthly)",
            impact=EventImpact.HIGH,
            actual=None, forecast=None, previous=None,
        ))

        for day in range(7):
            dt = base + timedelta(days=day)
            if dt.weekday() == 0:
                events.append(EconomicEvent(
                    timestamp=dt.replace(hour=14, minute=30),
                    currency="USD",
                    event="ISM Manufacturing PMI",
                    impact=EventImpact.MEDIUM,
                    actual=None, forecast=None, previous=None,
                ))

    return events


async def get_cached_calendar() -> list[EconomicEvent]:
    """Get calendar from cache or fetch fresh."""
    cached = _load_cache()
    if cached:
        return cached
    return await fetch_economic_calendar()


def check_funding_proximity(symbol: str, now: datetime | None = None) -> tuple[bool, int | None]:
    """Check if we're near a funding rate timestamp (8h intervals)."""
    now = now or datetime.now(timezone.utc)
    for funding_hour in FUNDING_TIMES_UTC:
        funding_time = now.replace(hour=funding_hour, minute=0, second=0, microsecond=0)
        if funding_time < now:
            funding_time += timedelta(hours=8)
        diff_minutes = int((funding_time - now).total_seconds() / 60)
        if diff_minutes <= 30:
            return True, diff_minutes
    return False, None


def is_high_impact_event(event: str, is_crypto: bool = False) -> bool:
    """Check if event name contains high-impact keywords."""
    event_upper = event.upper()
    keywords = CRYPTO_HIGH_IMPACT if is_crypto else HIGH_IMPACT_KEYWORDS
    return any(kw in event_upper for kw in keywords)


def get_nearest_event(
    symbol: str,
    events: list[EconomicEvent],
    now: datetime | None = None,
    window_hours: int = 24,
) -> tuple[EconomicEvent | None, int | None]:
    """Find nearest high/medium impact event for symbol's currency."""
    now = now or datetime.now(timezone.utc)
    window_end = now + timedelta(hours=window_hours)

    base_currency = symbol.replace("USDT", "").replace("USD", "")
    if base_currency in ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "LINK", "DOT", "AVAX"):
        relevant_currencies = ["USD", "US", "GLOBAL", "CRYPTO"]
    else:
        relevant_currencies = [base_currency, "USD", "US", "GLOBAL"]

    nearest = None
    min_minutes = None

    for event in events:
        if event.timestamp < now or event.timestamp > window_end:
            continue
        if event.currency not in relevant_currencies and event.currency != "GLOBAL":
            continue
        if event.impact not in (EventImpact.HIGH, EventImpact.MEDIUM):
            continue
        if not is_high_impact_event(event.event, base_currency in ("BTC", "ETH", "SOL", "BNB", "XRP")):
            continue

        minutes = int((event.timestamp - now).total_seconds() / 60)
        if min_minutes is None or minutes < min_minutes:
            min_minutes = minutes
            nearest = event

    return nearest, min_minutes


async def check_news_filter(
    symbol: str,
    timeframe: str,
    settings: Settings,
    now: datetime | None = None,
) -> NewsFilterResult:
    """
    Main entry point: check if signal should be blocked due to news/events.
    Returns NewsFilterResult with decision and details.
    """
    now = now or datetime.now(timezone.utc)

    if not getattr(settings, "news_filter_enabled", True):
        return NewsFilterResult(
            allowed=True, reason="News filter disabled",
            nearest_event=None, minutes_to_event=None,
            funding_nearby=False, funding_minutes=None,
        )

    events = await get_cached_calendar()

    nearest_event, minutes_to_event = get_nearest_event(symbol, events, now)

    high_impact_window = getattr(settings, "news_high_impact_window_min", 60)
    medium_impact_window = getattr(settings, "news_medium_impact_window_min", 30)

    if nearest_event:
        if nearest_event.impact == EventImpact.HIGH and minutes_to_event <= high_impact_window:
            return NewsFilterResult(
                allowed=False,
                reason=f"HIGH IMPACT EVENT: {nearest_event.event} in {minutes_to_event} min",
                nearest_event=nearest_event,
                minutes_to_event=minutes_to_event,
                funding_nearby=False,
                funding_minutes=None,
            )
        elif nearest_event.impact == EventImpact.MEDIUM and minutes_to_event <= medium_impact_window:
            return NewsFilterResult(
                allowed=False,
                reason=f"MEDIUM IMPACT EVENT: {nearest_event.event} in {minutes_to_event} min",
                nearest_event=nearest_event,
                minutes_to_event=minutes_to_event,
                funding_nearby=False,
                funding_minutes=None,
            )

    funding_nearby, funding_minutes = check_funding_proximity(symbol, now)
    funding_window = getattr(settings, "funding_rate_window_min", 15)

    if funding_nearby and funding_minutes is not None and funding_minutes <= funding_window:
        return NewsFilterResult(
            allowed=False,
            reason=f"FUNDING RATE in {funding_minutes} min",
            nearest_event=None,
            minutes_to_event=None,
            funding_nearby=True,
            funding_minutes=funding_minutes,
        )

    return NewsFilterResult(
        allowed=True,
        reason="No blocking events",
        nearest_event=nearest_event,
        minutes_to_event=minutes_to_event,
        funding_nearby=funding_nearby,
        funding_minutes=funding_minutes,
    )


def get_news_summary(symbol: str, events: list[EconomicEvent], hours: int = 48) -> list[str]:
    """Get human-readable summary of upcoming events."""
    now = datetime.now(timezone.utc)
    window_end = now + timedelta(hours=hours)

    base_currency = symbol.replace("USDT", "").replace("USD", "")
    relevant = ["USD", "US", "GLOBAL"]
    if base_currency not in ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "LINK", "DOT", "AVAX"):
        relevant.append(base_currency)

    lines = []
    for event in events:
        if event.timestamp < now or event.timestamp > window_end:
            continue
        if event.currency not in relevant:
            continue
        if event.impact == EventImpact.LOW:
            continue

        minutes = int((event.timestamp - now).total_seconds() / 60)
        hours_away = minutes // 60
        mins_away = minutes % 60

        impact_emoji = "🔴" if event.impact == EventImpact.HIGH else "🟡"
        time_str = f"{hours_away}h {mins_away}m" if hours_away > 0 else f"{mins_away}m"
        lines.append(f"{impact_emoji} {event.event} ({event.currency}) in {time_str}")

    return lines[:10]