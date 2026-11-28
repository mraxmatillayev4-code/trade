"""Signal uchun tushuntiruvchi grafik (matplotlib) — entry/SL/TP belgilanadi."""
from __future__ import annotations

import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from app.core.timeuz import TASHKENT


def _fp(p: float) -> str:
    """Narxni o'qiladigan formatda (ilmiy formatsiz)."""
    if p >= 100:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:,.4f}"
    return f"{p:.6f}"


def render_signal_chart(df: pd.DataFrame, direction: str, entry: float,
                        sl: float, tp1: float, tp2: float, tp3: float,
                        symbol: str, timeframe: str, score: float,
                        candles: int = 70) -> bytes:
    data = df.tail(candles).copy().reset_index(drop=True)
    # Grafik o'qi TOSHKENT vaqti bilan (shamlar UTC da saqlanadi)
    x = (pd.to_datetime(data["open_time"], utc=True)
         .dt.tz_convert(TASHKENT).dt.tz_localize(None))

    fig, ax = plt.subplots(figsize=(11, 6.5), dpi=110)
    fig.patch.set_facecolor("#0f1420")
    ax.set_facecolor("#0f1420")

    up = data["close"] >= data["open"]
    # Shamlar (soddalashtirilgan chiziq + rangli marker)
    for i, (xi, o, h, l, c) in enumerate(zip(x, data["open"], data["high"],
                                             data["low"], data["close"])):
        color = "#22c55e" if c >= o else "#ef4444"
        ax.vlines(xi, l, h, color=color, linewidth=0.8, alpha=0.8)
        ax.vlines(xi, min(o, c), max(o, c), color=color, linewidth=2.6, alpha=0.9)

    # EMA50 / EMA200 (agar DataFrame'da hisoblangan bo'lmasa — o'tkazib yuboriladi)
    if "ema50" in data:
        ax.plot(x, data["ema50"], color="#f59e0b", linewidth=1.4, label="EMA50", alpha=0.9)
    if "ema200" in data:
        ax.plot(x, data["ema200"], color="#3b82f6", linewidth=1.4, label="EMA200", alpha=0.9)

    # Darajalar (ENTRY uchun alohida yorliq qo'yilmaydi — annotatsiya bor)
    levels = [
        ("-1R SL", sl, "#ef4444", "--", 2.0),
        ("+1R", tp1, "#22c55e", ":", 1.8),
        ("+2R", tp2, "#22c55e", ":", 1.8),
        ("+3R", tp3, "#4ade80", ":", 2.2),
    ]
    ax.axhline(entry, color="#facc15", linestyle="-", linewidth=2.2, alpha=0.85)
    for name, price, color, ls, lw in levels:
        ax.axhline(price, color=color, linestyle=ls, linewidth=lw, alpha=0.85)
        ax.text(x.iloc[-1], price, f" {name} {_fp(price)}", color=color,
                fontsize=9, va="center", fontweight="bold")

    # Y-axis: shamlar va darajalarni birga ko'rsatish uchun chegara
    price_min = float(data["low"].min())
    price_max = float(data["high"].max())
    lvl_min = min(sl, entry, tp1, tp2, tp3)
    lvl_max = max(sl, entry, tp1, tp2, tp3)
    lo = min(price_min, lvl_min)
    hi = max(price_max, lvl_max)
    pad = (hi - lo) * 0.06 + 1e-9
    ax.set_ylim(lo - pad, hi + pad)

    # Kirish nuqtasi strelka (yorliq bilan ustma-ust tushmasligi uchun biroz chetga)
    label = "BUY ENTRY" if direction == "BUY" else "SELL ENTRY"
    label_color = "#22c55e" if direction == "BUY" else "#ef4444"
    text_y = entry + (hi - lo) * (0.05 if direction == "BUY" else -0.05)
    ax.annotate(
        f"{label} @ {_fp(entry)}",
        xy=(x.iloc[-1], entry), xytext=(x.iloc[-14], text_y),
        color=label_color, fontsize=11, fontweight="bold",
        arrowprops=dict(arrowstyle="->", color="#facc15", lw=2),
    )

    title_color = "#22c55e" if direction == "BUY" else "#ef4444"
    ax.set_title(
        f"{symbol}  •  {timeframe.upper()}  •  {direction} SIGNAL  •  Score {score:.1f}/10",
        color=title_color, fontsize=14, fontweight="bold", pad=12,
    )
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m %H:%M"))
    ax.tick_params(colors="#94a3b8", labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#1e293b")
    ax.grid(True, alpha=0.12, color="#94a3b8")
    ax.legend(loc="upper left", facecolor="#1e293b", edgecolor="#334155",
              labelcolor="#e2e8f0", fontsize=9)

    fig.autofmt_xdate()
    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()
