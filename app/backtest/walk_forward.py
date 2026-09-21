"""
Walk-forward test — ma'lumotni oynalarga bo'lib, har bir oynani alohida baholaydi.
Strategiyalar parametrlarni avtomatik optimizatsiya qilmaydi (overfitting oldini olish);
buning o'rniga har bir oynadagi barqarorlik (stability) tekshiriladi.
"""
from __future__ import annotations

import pandas as pd

from app.backtest.engine import run_backtest
from app.core.config import Settings


def run_walk_forward(df: pd.DataFrame, timeframe: str, settings: Settings,
                     higher_dfs: dict[str, pd.DataFrame] | None = None,
                     folds: int = 5, strategy_filter: str = "ALL",
                     symbol: str = "?") -> dict:
    higher_dfs = higher_dfs or {}
    df = df.reset_index(drop=True)
    n = len(df)
    fold_size = n // folds
    results = []

    for f in range(folds):
        test_start = f * fold_size
        test_end = n if f == folds - 1 else (f + 1) * fold_size
        # Indikatorlar uchun warmup: test boshlanishidan oldin ham ma'lumot beriladi
        warm_start = max(0, test_start - settings.min_candles - 50)
        window = df.iloc[warm_start:test_end].reset_index(drop=True)

        htf_sliced = {}
        boundary = df.iloc[test_end - 1]["close_time"]
        for tf, hdf in higher_dfs.items():
            htf_sliced[tf] = hdf[hdf["open_time"] <= boundary].reset_index(drop=True)

        metrics = run_backtest(
            window, timeframe, settings, htf_sliced,
            strategy_filter=strategy_filter, symbol=symbol,
        )
        # Faqat test davridagi tranzaksiyalar (warmup'dagilarni tashlaymiz)
        warm_len = test_start - warm_start
        test_trades = [t for t in metrics["trades"] if t["index"] >= warm_len]
        from app.backtest.metrics import compute_metrics, per_strategy_metrics
        test_metrics = compute_metrics(test_trades)
        test_metrics["per_strategy"] = per_strategy_metrics(test_trades)
        results.append({
            "fold": f + 1,
            "bars": test_end - test_start,
            **{k: v for k, v in test_metrics.items() if k != "trades"},
        })

    # Barqarorlik: nechta oyna ijobiy avg_R bergan
    positive_folds = sum(1 for r in results if r["avg_r"] > 0)
    avg_win_rate = round(sum(r["win_rate"] for r in results) / folds, 2)
    avg_r = round(sum(r["avg_r"] for r in results) / folds, 3)

    return {
        "folds": results,
        "folds_count": folds,
        "positive_folds": positive_folds,
        "stability_pct": round(positive_folds / folds * 100, 1),
        "avg_win_rate": avg_win_rate,
        "avg_r": avg_r,
        "stable": positive_folds >= max(1, folds - 1),
    }
