"""Multi-timeframe tasdiq: yuqori timeframe trendi signalni qo'llab-quvvatlaydimi?"""
from __future__ import annotations

import pandas as pd

from app.core.config import Settings
from app.core.enums import Direction, HIGHER_TIMEFRAMES, MTFAlignment
from app.indicators.bundle import compute_bundle


def higher_timeframe_trend(df: pd.DataFrame, settings: Settings) -> Direction:
    """Bitta yuqori timeframe trendi: EMA50/EMA200 + narx joylashuvi."""
    if df is None or len(df) < 50:
        return Direction.NEUTRAL
    b = compute_bundle(df, settings)
    c = b.last_close
    ema50 = float(b.ema50.iloc[-1])
    ema200 = float(b.ema200.iloc[-1])
    if ema50 > ema200 and c > ema50:
        return Direction.BUY
    if ema50 < ema200 and c < ema50:
        return Direction.SELL
    return Direction.NEUTRAL


def collect_mtf_votes(symbol: str, timeframe: str,
                      get_df, settings: Settings) -> list[tuple[str, Direction]]:
    """
    get_df(symbol, tf) -> pd.DataFrame | None  (candle manager beradi)
    """
    votes: list[tuple[str, Direction]] = []
    for htf in HIGHER_TIMEFRAMES.get(timeframe, []):
        df = get_df(symbol, htf)
        if df is None or len(df) < 50:
            continue
        votes.append((htf, higher_timeframe_trend(df, settings)))
    return votes


def alignment(votes: list[tuple[str, Direction]], direction: Direction) -> MTFAlignment:
    """Yuqori timeframe ovozlari — KO'PCHILIK (majority) asosida.

    - ALIGNED : real (neytral emas) ovozlarning YARMI yoki ko'pi bizning yo'nalishda
    - AGAINST : real ovozlarning YARMI dan ko'pi QARSHI (aniq kontr-trend)
    - NONE    : real ovoz yo'q (yuqori TF noaniq/neytral)
    Bu bitta HTF qarshi bo'lib, qolganlari tasdiqlagan holatni noto'g'ri bloklashni yo'qotadi.
    """
    real = [v for _, v in votes if v != Direction.NEUTRAL]
    if not real:
        return MTFAlignment.NONE
    agree = sum(1 for v in real if v == direction)
    oppose = len(real) - agree
    if agree >= oppose:
        # teng bo'lsa ham (1-1) kontra deb hisoblamaymiz — tasdiq ustun yoki teng
        return MTFAlignment.ALIGNED if agree > oppose else MTFAlignment.MIXED
    return MTFAlignment.AGAINST
