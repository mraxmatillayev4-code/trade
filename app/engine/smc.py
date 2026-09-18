"""Smart Money Concepts (SMC) — FVG, Order Blocks, Liquidity Sweeps, BOS/CHoCH."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from app.core.enums import Direction

if TYPE_CHECKING:
    from app.indicators.bundle import IndicatorBundle


class StructureType(Enum):
    BOS = "BOS"
    CHOCH = "CHoCH"


class OrderBlockType(Enum):
    BULLISH = "BULLISH_OB"
    BEARISH = "BEARISH_OB"


class FVGType(Enum):
    BULLISH = "BULLISH_FVG"
    BEARISH = "BEARISH_FVG"


class LiquidityType(Enum):
    BUY_SIDE = "BUY_SIDE_LIQUIDITY"
    SELL_SIDE = "SELL_SIDE_LIQUIDITY"


@dataclass
class FairValueGap:
    type: FVGType
    top: float
    bottom: float
    mid: float
    timestamp: int
    index: int
    mitigated: bool = False
    mitigation_index: int | None = None


@dataclass
class OrderBlock:
    type: OrderBlockType
    top: float
    bottom: float
    mid: float
    timestamp: int
    index: int
    volume: float
    strength: float
    mitigated: bool = False
    mitigation_index: int | None = None


@dataclass
class LiquidityLevel:
    type: LiquidityType
    price: float
    timestamp: int
    index: int
    strength: float
    swept: bool = False
    sweep_index: int | None = None


@dataclass
class StructureBreak:
    type: StructureType
    direction: Direction
    break_price: float
    timestamp: int
    index: int
    confirmed: bool = False


@dataclass
class SMCResult:
    fvgs: list[FairValueGap]
    order_blocks: list[OrderBlock]
    liquidity_levels: list[LiquidityLevel]
    structure_breaks: list[StructureBreak]
    current_bias: Direction
    confluence_score: float
    structure_score: float
    details: list[str]


def detect_fvgs(df: pd.DataFrame, lookback: int = 50) -> list[FairValueGap]:
    """
    Detect Fair Value Gaps (imbalances).
    Bullish FVG: candle[n-2].low > candle[n].high
    Bearish FVG: candle[n-2].high < candle[n].low
    """
    fvgs = []
    data = df.tail(lookback).reset_index(drop=True)

    for i in range(2, len(data)):
        c0 = data.iloc[i - 2]
        c1 = data.iloc[i - 1]
        c2 = data.iloc[i]

        if c0['low'] > c2['high']:
            fvgs.append(FairValueGap(
                type=FVGType.BULLISH,
                top=float(c0['low']),
                bottom=float(c2['high']),
                mid=float((c0['low'] + c2['high']) / 2),
                timestamp=int(c1['open_time']),
                index=i - 1,
            ))
        elif c0['high'] < c2['low']:
            fvgs.append(FairValueGap(
                type=FVGType.BEARISH,
                top=float(c2['low']),
                bottom=float(c0['high']),
                mid=float((c0['high'] + c2['low']) / 2),
                timestamp=int(c1['open_time']),
                index=i - 1,
            ))

    return fvgs


def detect_order_blocks(df: pd.DataFrame, lookback: int = 50, min_volume_mult: float = 1.5) -> list[OrderBlock]:
    """
    Detect Order Blocks (institutional candles).
    Bullish OB: Last down candle before a strong up move (BOS/CHoCH).
    Bearish OB: Last up candle before a strong down move.
    """
    obs = []
    data = df.tail(lookback).reset_index(drop=True)
    vol_ma = data['volume'].rolling(20).mean()

    for i in range(2, len(data) - 1):
        c0 = data.iloc[i - 1]
        c1 = data.iloc[i]
        c2 = data.iloc[i + 1]

        vol_ratio = c1['volume'] / vol_ma.iloc[i] if vol_ma.iloc[i] > 0 else 1

        if vol_ratio < min_volume_mult:
            continue

        if c0['close'] < c0['open'] and c2['close'] > c2['open'] and c2['close'] > c1['high']:
            obs.append(OrderBlock(
                type=OrderBlockType.BULLISH,
                top=float(c1['high']),
                bottom=float(c1['low']),
                mid=float((c1['high'] + c1['low']) / 2),
                timestamp=int(c1['open_time']),
                index=i,
                volume=float(c1['volume']),
                strength=vol_ratio,
            ))

        elif c0['close'] > c0['open'] and c2['close'] < c2['open'] and c2['close'] < c1['low']:
            obs.append(OrderBlock(
                type=OrderBlockType.BEARISH,
                top=float(c1['high']),
                bottom=float(c1['low']),
                mid=float((c1['high'] + c1['low']) / 2),
                timestamp=int(c1['open_time']),
                index=i,
                volume=float(c1['volume']),
                strength=vol_ratio,
            ))

    return obs


def detect_liquidity_levels(df: pd.DataFrame, lookback: int = 100, min_touches: int = 2) -> list[LiquidityLevel]:
    """
    Detect Liquidity Levels (equal highs/lows, swing highs/lows).
    Buy-side liquidity = swing highs (stops above).
    Sell-side liquidity = swing lows (stops below).
    """
    levels = []
    data = df.tail(lookback).reset_index(drop=True)

    highs = data['high'].values
    lows = data['low'].values
    times = data['open_time'].values

    swing_highs = []
    swing_lows = []

    for i in range(2, len(data) - 2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            swing_highs.append((i, highs[i], times[i]))
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            swing_lows.append((i, lows[i], times[i]))

    for idx, price, ts in swing_highs:
        touches = sum(1 for _, p, _ in swing_highs if abs(p - price) / price < 0.001)
        if touches >= min_touches:
            levels.append(LiquidityLevel(
                type=LiquidityType.BUY_SIDE,
                price=float(price),
                timestamp=int(ts),
                index=idx,
                strength=float(touches),
            ))

    for idx, price, ts in swing_lows:
        touches = sum(1 for _, p, _ in swing_lows if abs(p - price) / price < 0.001)
        if touches >= min_touches:
            levels.append(LiquidityLevel(
                type=LiquidityType.SELL_SIDE,
                price=float(price),
                timestamp=int(ts),
                index=idx,
                strength=float(touches),
            ))

    return levels


def detect_structure_breaks(df: pd.DataFrame, lookback: int = 50) -> list[StructureBreak]:
    """
    Detect Break of Structure (BOS) and Change of Character (CHoCH).
    BOS: Price breaks previous swing high/low in trend direction.
    CHoCH: Price breaks swing in opposite direction (trend reversal).
    """
    breaks = []
    data = df.tail(lookback).reset_index(drop=True)

    highs = data['high'].values
    lows = data['low'].values
    closes = data['close'].values
    times = data['open_time'].values

    swing_highs = []
    swing_lows = []

    for i in range(2, len(data) - 2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            swing_highs.append((i, highs[i]))
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            swing_lows.append((i, lows[i]))

    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        for i in range(2, len(data)):
            price = closes[i]
            ts = times[i]

            if swing_highs:
                last_high_idx, last_high = swing_highs[-1]
                prev_high_idx, prev_high = swing_highs[-2] if len(swing_highs) > 1 else (None, None)

                if price > last_high and i > last_high_idx:
                    is_choch = prev_high is not None and last_high < prev_high
                    breaks.append(StructureBreak(
                        type=StructureType.CHOCH if is_choch else StructureType.BOS,
                        direction=Direction.BUY,
                        break_price=float(price),
                        timestamp=int(ts),
                        index=i,
                        confirmed=not is_choch,
                    ))

            if swing_lows:
                last_low_idx, last_low = swing_lows[-1]
                prev_low_idx, prev_low = swing_lows[-2] if len(swing_lows) > 1 else (None, None)

                if price < last_low and i > last_low_idx:
                    is_choch = prev_low is not None and last_low > prev_low
                    breaks.append(StructureBreak(
                        type=StructureType.CHOCH if is_choch else StructureType.BOS,
                        direction=Direction.SELL,
                        break_price=float(price),
                        timestamp=int(ts),
                        index=i,
                        confirmed=not is_choch,
                    ))

    return breaks


def check_fvg_mitigation(fvgs: list[FairValueGap], current_price: float, current_index: int) -> list[FairValueGap]:
    """Check if FVGs have been mitigated (price entered the gap)."""
    for fvg in fvgs:
        if fvg.mitigated:
            continue
        if fvg.type == FVGType.BULLISH and current_price <= fvg.top and current_price >= fvg.bottom:
            fvg.mitigated = True
            fvg.mitigation_index = current_index
        elif fvg.type == FVGType.BEARISH and current_price >= fvg.bottom and current_price <= fvg.top:
            fvg.mitigated = True
            fvg.mitigation_index = current_index
    return fvgs


def check_ob_mitigation(obs: list[OrderBlock], current_price: float, current_index: int) -> list[OrderBlock]:
    """Check if Order Blocks have been mitigated."""
    for ob in obs:
        if ob.mitigated:
            continue
        if ob.type == OrderBlockType.BULLISH and current_price <= ob.top and current_price >= ob.bottom:
            ob.mitigated = True
            ob.mitigation_index = current_index
        elif ob.type == OrderBlockType.BEARISH and current_price >= ob.bottom and current_price <= ob.top:
            ob.mitigated = True
            ob.mitigation_index = current_index
    return obs


def check_liquidity_sweep(levels: list[LiquidityLevel], current_high: float, current_low: float, current_index: int) -> list[LiquidityLevel]:
    """Check if liquidity levels have been swept."""
    for level in levels:
        if level.swept:
            continue
        if level.type == LiquidityType.BUY_SIDE and current_high >= level.price:
            level.swept = True
            level.sweep_index = current_index
        elif level.type == LiquidityType.SELL_SIDE and current_low <= level.price:
            level.swept = True
            level.sweep_index = current_index
    return levels


def compute_smc_confluence(
    fvgs: list[FairValueGap],
    obs: list[OrderBlock],
    levels: list[LiquidityLevel],
    breaks: list[StructureBreak],
    current_price: float,
    direction: Direction,
) -> tuple[float, float, list[str]]:
    """
    Compute SMC confluence and structure scores.
    Returns: (confluence_score, structure_score, details)
    """
    confluence = 0.0
    structure = 0.0
    details = []

    active_fvgs = [f for f in fvgs if not f.mitigated]
    active_obs = [ob for ob in obs if not ob.mitigated]
    unswept_levels = [l for l in levels if not l.swept]

    if direction == Direction.BUY:
        bullish_fvgs = [f for f in active_fvgs if f.type == FVGType.BULLISH]
        bullish_obs = [ob for ob in active_obs if ob.type == OrderBlockType.BULLISH]
        buy_liq = [l for l in unswept_levels if l.type == LiquidityType.BUY_SIDE]
        sell_liq = [l for l in unswept_levels if l.type == LiquidityType.SELL_SIDE]

        for fvg in bullish_fvgs:
            if fvg.bottom <= current_price <= fvg.top:
                confluence += 15
                details.append(f"✅ Price inside bullish FVG ({fvg.bottom:.4f}-{fvg.top:.4f})")
            elif current_price > fvg.top:
                confluence += 8
                details.append(f"✅ Price above bullish FVG")

        for ob in bullish_obs:
            if ob.bottom <= current_price <= ob.top:
                confluence += 20
                details.append(f"🏦 Price at bullish Order Block ({ob.bottom:.4f}-{ob.top:.4f})")
            elif current_price > ob.top:
                confluence += 10
                details.append(f"✅ Price above bullish Order Block")

        if sell_liq:
            nearest_sell = min(sell_liq, key=lambda x: abs(x.price - current_price))
            dist_pct = abs(nearest_sell.price - current_price) / current_price * 100
            if dist_pct < 1.0:
                confluence -= 10
                details.append(f"⚠️ Near sell-side liquidity ({dist_pct:.2f}%)")

        buy_breaks = [b for b in breaks if b.direction == Direction.BUY and b.confirmed]
        if buy_breaks:
            structure += 20 * len(buy_breaks)
            details.append(f"📈 {len(buy_breaks)} confirmed BOS/CHoCH bullish")

    else:
        bearish_fvgs = [f for f in active_fvgs if f.type == FVGType.BEARISH]
        bearish_obs = [ob for ob in active_obs if ob.type == OrderBlockType.BEARISH]
        buy_liq = [l for l in unswept_levels if l.type == LiquidityType.BUY_SIDE]
        sell_liq = [l for l in unswept_levels if l.type == LiquidityType.SELL_SIDE]

        for fvg in bearish_fvgs:
            if fvg.bottom <= current_price <= fvg.top:
                confluence += 15
                details.append(f"✅ Price inside bearish FVG ({fvg.bottom:.4f}-{fvg.top:.4f})")
            elif current_price < fvg.bottom:
                confluence += 8
                details.append(f"✅ Price below bearish FVG")

        for ob in bearish_obs:
            if ob.bottom <= current_price <= ob.top:
                confluence += 20
                details.append(f"🏦 Price at bearish Order Block ({ob.bottom:.4f}-{ob.top:.4f})")
            elif current_price < ob.bottom:
                confluence += 10
                details.append(f"✅ Price below bearish Order Block")

        if buy_liq:
            nearest_buy = min(buy_liq, key=lambda x: abs(x.price - current_price))
            dist_pct = abs(nearest_buy.price - current_price) / current_price * 100
            if dist_pct < 1.0:
                confluence -= 10
                details.append(f"⚠️ Near buy-side liquidity ({dist_pct:.2f}%)")

        sell_breaks = [b for b in breaks if b.direction == Direction.SELL and b.confirmed]
        if sell_breaks:
            structure += 20 * len(sell_breaks)
            details.append(f"📉 {len(sell_breaks)} confirmed BOS/CHoCH bearish")

    confluence = max(0.0, min(100.0, confluence))
    structure = max(0.0, min(100.0, structure))

    return confluence, structure, details


def analyze_smc(
    df: pd.DataFrame,
    current_price: float,
    direction: Direction,
    lookback: int = 100,
) -> SMCResult:
    """Main SMC analysis function — detects all SMC elements and computes scores."""
    fvgs = detect_fvgs(df, lookback)
    obs = detect_order_blocks(df, lookback)
    levels = detect_liquidity_levels(df, lookback)
    breaks = detect_structure_breaks(df, lookback)

    current_idx = len(df) - 1
    fvgs = check_fvg_mitigation(fvgs, current_price, current_idx)
    obs = check_ob_mitigation(obs, current_price, current_idx)
    levels = check_liquidity_sweep(levels, df['high'].iloc[-1], df['low'].iloc[-1], current_idx)

    confluence, structure, details = compute_smc_confluence(fvgs, obs, levels, breaks, current_price, direction)

    if breaks:
        last_break = breaks[-1]
        bias = last_break.direction
    else:
        bias = direction

    return SMCResult(
        fvgs=fvgs,
        order_blocks=obs,
        liquidity_levels=levels,
        structure_breaks=breaks,
        current_bias=bias,
        confluence_score=round(confluence, 1),
        structure_score=round(structure, 1),
        details=details,
    )