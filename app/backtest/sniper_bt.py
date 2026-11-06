"""SNR+ICT+SMC (OLTIN) — BACKTEST (v86).

Xuddi jonli botdagidek yuradi:
  setup topiladi -> kirish zonasi LIMIT kutadi (muddat: TTL sham)
  -> narx zonaga kelsa QO'SHIMCHA SHARTLARSIZ ochiladi (quvish yo'q)
  -> 2 lot: Lot1 = TP1, Lot2 = TP2; TP1 urilgach Lot2 ning SL = kirish
  -> muddat tugasa bozor narxida yopiladi.

Konservativ qoidalar (real natijaga yaqin bo'lishi uchun):
  * bitta shamda SL ham, TP ham urilsa — **SL birinchi** hisoblanadi;
  * kirish zonasi to'ldirilganda narx yomonroq tomondan olinadi (zone_hi/zone_lo);
  * spread/slip har lot uchun ayriladi (standart 0.20$ + 0.05$).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.engine import sniper as SN

LOT = 0.01                     # har bir lot (2 lot = 2 x 0.01)
CONTRACT = 100.0               # 1 lot XAUUSD = 100 untsiya -> 0.01 lot: 1$ = 1$
ENTRY_TTL_BARS = 6             # 30 daqiqa (5m shamlar)
MAX_HOLD_BARS = 96             # 8 soat
SPREAD_PRICE = 0.20            # ikki tomon spread (narx birligida)
SLIP_PRICE = 0.05              # bozorda yopilishdagi sirpanish
START_BALANCE = 50.0


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    d = df.set_index(pd.to_datetime(df["time"], utc=True))
    out = d.resample(rule, label="right", closed="right").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna().reset_index().rename(columns={"index": "time"})
    return out


@dataclass
class Trade:
    kind: str              # signal turi
    direction: str
    i_signal: int
    t_signal: datetime
    entry: float
    zone_lo: float
    zone_hi: float
    sl: float
    tp1: float
    tp2: float
    score: float
    atr: float
    filled: bool = False
    risk0: float = 0.0        # SIGNAL paytidagi risk (SL masofasi) — o'zgarmaydi
    i_fill: int = 0
    t_fill: datetime | None = None
    fill_price: float = 0.0
    lot1_r: float = 0.0
    lot2_r: float = 0.0
    lot1_usd: float = 0.0
    lot2_usd: float = 0.0
    close_reason: str = ""
    i_close: int = 0
    hold_bars: int = 0
    be_moved: bool = False
    why: str = ""

    @property
    def usd(self) -> float:
        return self.lot1_usd + self.lot2_usd

    @property
    def win(self) -> bool:
        return self.usd > 0


def run_backtest(d5: pd.DataFrame, d15: pd.DataFrame | None = None,
                 d1h: pd.DataFrame | None = None,
                 scan_from: int | None = None, scan_step: int = 1,
                 allow_both: bool = True, verbose: bool = False) -> dict:
    """5m ma'lumotda to'liq simulyatsiya."""
    d5 = d5.reset_index(drop=True)
    hi = d5["high"].to_numpy()
    lo = d5["low"].to_numpy()
    cl = d5["close"].to_numpy()
    tm = pd.to_datetime(d5["time"], utc=True).to_list()
    n = len(d5)
    # MUHIM: 1h/15m ma'lumotlar HAR BIR sham vaqtiga qadar kesiladi —
    # aks holda kelajakdagi shamlar bias'ga ta'sir qiladi (lookahead).
    import numpy as _np
    _t5 = _np.array([_ts.value for _ts in tm], dtype="int64")
    _cut15 = _cut1h = None
    if d15 is not None and len(d15):
        _t15 = pd.to_datetime(d15["time"], utc=True)
        _cut15 = _np.searchsorted(_np.array([x.value for x in _t15], dtype="int64"),
                                  _t5, side="right")
    if d1h is not None and len(d1h):
        _t1h = pd.to_datetime(d1h["time"], utc=True)
        _cut1h = _np.searchsorted(_np.array([x.value for x in _t1h], dtype="int64"),
                                  _t5, side="right")
    start = max(SN.WARMUP + 5, scan_from or SN.WARMUP + 5)

    trades: list[Trade] = []
    open_tr: list[Trade] = []
    pending: list[Trade] = []
    setups = 0

    for i in range(start, n):
        # 1) kutilayotganlarni tekshirish (kirish zonasi / muddat)
        for t in list(pending):
            if t.direction == "BUY":
                if lo[i] <= t.sl:                      # zona yetmasdan SL -> bekor
                    t.close_reason = "SL oldin (kirilmadi)"
                    pending.remove(t)
                    trades.append(t)
                    continue
                if lo[i] <= t.zone_hi:                 # zona to'ldirildi
                    t.filled = True
                    t.fill_price = min(t.zone_hi, hi[i]) if hi[i] >= t.zone_hi else t.zone_hi
                    t.fill_price = t.zone_hi
                    t.i_fill = i
                    t.t_fill = tm[i]
                    pending.remove(t)
                    open_tr.append(t)
                    continue
            else:
                if hi[i] >= t.sl:
                    t.close_reason = "SL oldin (kirilmadi)"
                    pending.remove(t)
                    trades.append(t)
                    continue
                if hi[i] >= t.zone_lo:
                    t.filled = True
                    t.fill_price = t.zone_lo
                    t.i_fill = i
                    t.t_fill = tm[i]
                    pending.remove(t)
                    open_tr.append(t)
                    continue
            if i - t.i_signal > ENTRY_TTL_BARS:
                t.close_reason = "KIRISH YO'Q (muddat tugadi)"
                pending.remove(t)
                trades.append(t)

        # 2) ochiq pozitsiyalarni boshqarish (risk0 — SIGNAL paytidagi risk)
        for tr in list(open_tr):
            r = float(tr.risk0) or 1e-9
            long = tr.direction == "BUY"
            hit_sl = lo[i] <= tr.sl if long else hi[i] >= tr.sl
            hit_tp1 = hi[i] >= tr.tp1 if long else lo[i] <= tr.tp1
            hit_tp2 = hi[i] >= tr.tp2 if long else lo[i] <= tr.tp2
            if hit_sl:
                # konservativ: bitta shamda SL ham, TP ham bo'lsa — SL birinchi
                tr.lot1_r = -1.0 if not tr.be_moved else abs(tr.tp1 - tr.entry) / r
                tr.lot2_r = 0.0 if tr.be_moved else -1.0
                tr.close_reason = ("SL" if not tr.be_moved
                                   else "SL (BE — Lot1 TP1da yopilgan)")
                tr.i_close, tr.hold_bars = i, i - tr.i_fill
                open_tr.remove(tr)
                trades.append(tr)
                continue
            if hit_tp1 and tr.lot1_r == 0.0:
                tr.lot1_r = abs(tr.tp1 - tr.entry) / r
                tr.sl = tr.entry              # BE
                tr.be_moved = True
            if hit_tp2:
                tr.lot2_r = abs(tr.tp2 - tr.entry) / r
                tr.close_reason = "TP2"
                tr.i_close, tr.hold_bars = i, i - tr.i_fill
                open_tr.remove(tr)
                trades.append(tr)
                continue
            if i - tr.i_fill >= MAX_HOLD_BARS:
                px = cl[i]
                mv = (px - tr.entry) if long else (tr.entry - px)
                tr.lot2_r = mv / r
                if tr.lot1_r == 0.0:
                    tr.lot1_r = tr.lot2_r
                tr.close_reason = "VAQT TUGADI"
                tr.i_close, tr.hold_bars = i, i - tr.i_fill
                open_tr.remove(tr)
                trades.append(tr)

        # 3) yangi setup
        if i % max(1, scan_step):
            continue
        if len(pending) + len(open_tr) >= (2 if allow_both else 1):
            continue
        _d15i = d15.iloc[: int(_cut15[i])] if _cut15 is not None else None
        _d1hi = d1h.iloc[: int(_cut1h[i])] if _cut1h is not None else None
        s = SN.analyze_one(d5, _d15i, _d1hi, i)
        if s is None:
            continue
        if not allow_both and any(t.direction == s.direction for t in pending + open_tr):
            continue
        if any(t.direction == s.direction for t in pending + open_tr):
            continue  # bir yo'nalishda bitta faol signal (bot qoidasi)
        setups += 1
        pending.append(Trade(kind=s.mode, direction=s.direction, i_signal=i,
                             t_signal=tm[i], entry=s.entry, zone_lo=s.zone_lo,
                             zone_hi=s.zone_hi, sl=s.sl, tp1=s.tp1, tp2=s.tp2,
                             score=s.score, atr=s.atr, why=s.reason,
                             risk0=abs(float(s.entry) - float(s.sl))))

    # oxirida ochiqlarni bozor narxida yopamiz
    for t in open_tr + pending:
        px = cl[-1]
        r = float(t.risk0) or 1e-9
        mv = (px - t.entry) if t.direction == "BUY" else (t.entry - px)
        if t.filled:
            t.lot2_r = mv / r
            if t.lot1_r == 0.0:
                t.lot1_r = t.lot2_r
            t.close_reason = t.close_reason or "OXIRI (bozor)"
        else:
            t.close_reason = "ochilmadi (test oxiri)"
        t.i_close = len(d5) - 1
        trades.append(t)

    # ---- pul natijalari (2 lot x tanlangan hajm; 0.01 lot: 1$ narx = 1$ pul) ----
    for t in trades:
        if not t.filled:
            continue
        d0 = float(t.risk0)
        cost = SPREAD_PRICE + SLIP_PRICE           # har lot uchun, narx birligida
        t.lot1_usd = t.lot1_r * d0 - cost
        t.lot2_usd = t.lot2_r * d0 - cost

    filled = [t for t in trades if t.filled]
    cancelled = [t for t in trades if not t.filled]
    lots_total = len(filled) * 2
    lot_win = sum((1 if t.lot1_r > 0 else 0) + (1 if t.lot2_r > 0 else 0) for t in filled)
    lot_loss = sum((1 if t.lot1_r < 0 else 0) + (1 if t.lot2_r < 0 else 0) for t in filled)
    gross_win = sum(v for t in filled for v in (t.lot1_usd, t.lot2_usd) if v > 0)
    gross_loss = -sum(v for t in filled for v in (t.lot1_usd, t.lot2_usd) if v < 0)
    equity = START_BALANCE
    peak = equity
    max_dd = 0.0
    curve = [equity]
    for t in filled:
        equity += t.usd
        curve.append(equity)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    def _bucket(keyfn) -> dict:
        out: dict[str, dict] = {}
        for t in filled:
            k = keyfn(t)
            b = out.setdefault(k, {"n": 0, "w": 0, "usd": 0.0, "r": 0.0})
            b["n"] += 1
            b["w"] += 1 if t.usd > 0 else 0
            b["usd"] += t.usd
            b["r"] += t.lot1_r + t.lot2_r
        for b in out.values():
            b["wr"] = round(b["w"] / b["n"] * 100, 1) if b["n"] else 0.0
            b["usd"] = round(b["usd"], 2)
            b["r"] = round(b["r"], 2)
        return out

    res = {
        "shamlar": len(d5),
        "davr": [str(tm[0]), str(tm[-1])],
        "setup_topildi": setups,
        "savdo_ochildi": len(filled),
        "kirish_bolmadi": len(cancelled),
        "kirish_bekor_sabablari": {
            k: sum(1 for t in cancelled if t.close_reason == k)
            for k in {t.close_reason for t in cancelled}
        },
        "lotlar": lots_total,
        "lot_win": lot_win,
        "lot_loss": lot_loss,
        "win_rate_lot": round(lot_win / lots_total * 100, 1) if lots_total else 0.0,
        "savdo_win": sum(1 for t in filled if t.win),
        "win_rate_savdo": round(sum(1 for t in filled if t.win) / len(filled) * 100, 1) if filled else 0.0,
        "yalpi_foyda": round(gross_win, 2),
        "yalpi_zarar": round(-gross_loss, 2),
        "sof_foyda": round(equity - START_BALANCE, 2),
        "balans_oxiri": round(equity, 2),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "kutilma_per_savdo": round((equity - START_BALANCE) / len(filled), 3) if filled else 0.0,
        "kutilma_R": round(sum(t.lot1_r + t.lot2_r for t in filled) / len(filled), 3) if filled else 0.0,
        "maks_drawdown": round(max_dd, 2),
        "ortacha_ushlab_turish_sham": round(sum(t.hold_bars for t in filled) / len(filled), 1) if filled else 0,
        "tp2_ulushi": round(sum(1 for t in filled if t.close_reason == "TP2") / len(filled) * 100, 1) if filled else 0.0,
        "sl_ulushi": round(sum(1 for t in filled if t.close_reason.startswith("SL")) / len(filled) * 100, 1) if filled else 0.0,
        "rejim_boyicha": _bucket(lambda t: t.kind),
        "yonalish_boyicha": _bucket(lambda t: t.direction),
        "soat_boyicha": _bucket(lambda t: f"{t.t_signal.hour:02d}:00"),
        "kun_boyicha": _bucket(lambda t: str(t.t_signal.date())),
        "oy_boyicha": _bucket(lambda t: t.t_signal.strftime("%Y-%m")),
        "ball_boyicha": _bucket(lambda t: ("6-7" if t.score < 7 else "7-8" if t.score < 8 else "8+")),
        "oxirgi_savdolar": [
            {"t": str(t.t_signal)[:16], "dir": t.direction, "ball": t.score,
             "kirish": t.fill_price, "sl": t.sl, "tp1": t.tp1, "tp2": t.tp2,
             "r1": round(t.lot1_r, 2), "r2": round(t.lot2_r, 2),
             "usd": round(t.usd, 2), "sabab": t.close_reason}
            for t in filled[-25:]
        ],
    }
    return res


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--d5", default="data/gold_5m.csv")
    ap.add_argument("--out", default="data/sniper_bt.json")
    ap.add_argument("--step", type=int, default=1)
    args = ap.parse_args()

    d5 = pd.read_csv(args.d5)
    d5["time"] = pd.to_datetime(d5["time"], utc=True)
    d15 = resample(d5, "15min")
    d1h = resample(d5, "1h")
    res = run_backtest(d5, d15, d1h, scan_step=args.step)
    Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items()
                      if k in ("shamlar", "davr", "setup_topildi", "savdo_ochildi",
                               "kirish_bolmadi", "win_rate_lot", "win_rate_savdo",
                               "sof_foyda", "profit_factor", "kutilma_R",
                               "maks_drawdown", "lotlar")}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
