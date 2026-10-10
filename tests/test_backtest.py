"""Backtest engine testlari — look-ahead yo'qligi va metrikalar."""
import asyncio
import math

from app.backtest.engine import run_backtest_sync as run_backtest
from app.backtest.metrics import compute_metrics, max_drawdown_r
from app.backtest.walk_forward import run_walk_forward


def test_backtest_runs_and_metrics(uptrend_df, settings):
    metrics = run_backtest(uptrend_df, "15m", settings, symbol="TESTUSDT")
    assert metrics["total_trades"] >= 0
    assert 0 <= metrics["win_rate"] <= 100
    assert metrics["profit_factor"] >= 0
    # Metrikalar izchil
    assert metrics["wins"] + metrics["losses"] + metrics["breakeven"] == metrics["total_trades"]


def test_backtest_downtrend(downtrend_df, settings):
    metrics = run_backtest(downtrend_df, "15m", settings, symbol="TESTUSDT")
    assert metrics["total_trades"] >= 0


def test_metrics_empty():
    m = compute_metrics([])
    assert m["total_trades"] == 0
    assert m["win_rate"] == 0.0


def test_metrics_win_rate():
    trades = [
        {"r": 2.0, "pnl_pct": 3.0, "direction": "BUY", "strategies": ["ema_trend"]},
        {"r": -1.0, "pnl_pct": -1.5, "direction": "BUY", "strategies": ["ema_trend"]},
        {"r": 1.0, "pnl_pct": 1.5, "direction": "BUY", "strategies": ["ema_trend"]},
    ]
    m = compute_metrics(trades)
    assert m["total_trades"] == 3
    assert m["wins"] == 2
    assert m["losses"] == 1
    assert math.isclose(m["win_rate"], 66.67, abs_tol=0.1)
    assert math.isclose(m["profit_factor"], 3.0)  # (2+1)/1


def test_max_drawdown():
    assert max_drawdown_r([1, 1, -1, -1, 1]) == 2.0
    assert max_drawdown_r([1, 1, 1]) == 0.0


def test_walk_forward_structure(uptrend_df, settings):
    wf = run_walk_forward(uptrend_df, "15m", settings, folds=4, symbol="TESTUSDT")
    assert wf["folds_count"] == 4
    assert len(wf["folds"]) == 4
    assert 0 <= wf["stability_pct"] <= 100


def test_no_lookahead_same_result_prefix(uptrend_df, settings):
    """
    Anti look-ahead: [0:N] oynadagi oxirgi signalning yo'nalishi
    faqat [0:N] ma'lumotga bog'liq bo'lishi kerak (kengaytirilganda
    o'tmishdagi signallar o'zgarmaydi).
    """
    n = len(uptrend_df)
    m1 = run_backtest(uptrend_df.iloc[: n - 50].copy(), "15m", settings, symbol="T")
    m2 = run_backtest(uptrend_df.copy(), "15m", settings, symbol="T")
    # Birinchi (n-50) oynadagi tranzaksiyalar kengaytmada ham bo'lishi kerak
    early_entries = {(t["index"], round(t["entry"], 6)) for t in m1["trades"]}
    later_entries = {(t["index"], round(t["entry"], 6)) for t in m2["trades"]}
    # Hech bo'lmaganda dastlabki signallar saqlanib qoladi
    if early_entries:
        overlap = early_entries & later_entries
        assert len(overlap) >= len(early_entries) - 1
