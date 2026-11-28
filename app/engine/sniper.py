"""SNR + ICT + SMC — OLTIN (XAUUSD) SNIPER ALGORITMI (v86).

Uchta maktab birlashtirilgan:

1) **SNR** (Support/Resistance — qo'llab-quvvatlash/qarshilik):
   - 5m/15m dagi swing (fraktal) cho'qqilar klasterlanadi -> daraja;
   - daraja kuchi = necha marta tegib qaytgani (touches);
   - kunlik PDH/PDL (oldingi kun eng baland/past) va dumaloq raqamlar
     (10 ga karrali) ham daraja hisoblanadi.

2) **ICT** (Inner Circle Trader — institutsional oqim):
   - **Likvidlik supurishi** (liquidity sweep / stop hunt): narx darajadan
     sanchib o'tib (wick) yana ichkariga qaytishi — bu killer setup;
   - **FVG** (Fair Value Gap): 3 sham orasidagi bo'shliq — narx uni
     to'ldirishga qaytadi -> KIRISH NUQTASI shu yerda;
   - **Displacement**: supurishdan keyin kuchli impuls sham (tana >= 0.6 ATR);
   - HTF bias (1h) — faqat katta yo'nalish tomonida savdo.

3) **SMC** (Smart Money Concepts):
   - **Order Block**: impulsdan oldingi oxirgi qarama-qarshi sham;
   - **BOS/CHoCH**: struktura sinishi tasdiqi;
   - FVG/OB "mitigation" (to'ldirilishi) hisobga olinadi.

Chiqish: `Setup` — entry (zona), SL (supurish ekstremumi ostida/ustida),
TP1/TP2 (qarshilik darajalari yoki R bo'yicha), ball (0-10) va sabab matni.

MUHIM: hisoblash faqat O'TMISHDAGI shamlardan (`i` indeksgacha) — kelajakka
qarash (lookahead) yo'q. Shu funksiyalar ham jonli skanerda, ham backtestda
ishlatiladi.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# ----------------------------- sozlamalar -----------------------------
ATR_N = 14                 # ATR davri
SWING_L = 2                # fraktal chap shamlar
SWING_R = 2                # fraktal o'ng shamlar
CLUSTER_ATR = 0.25         # darajalarni birlashtirish masofasi (ATR ulushi)
LEVEL_TOL_ATR = 0.35       # narx darajaga "tegdi" hisoblanish masofasi
SWEEP_LOOKBACK = 24        # oxirgi nechta 5m shamda supurish qidiriladi
SWEEP_MIN_AGE = 2          # supurishdan keyin kamida shuncha sham o'tgan bo'lsin
SWEEP_MIN_ATR = 0.06       # darajadan kamida shuncha ATR nariga o'tishi kerak
DISP_MIN_ATR = 0.55        # impuls sham tanasi (ATR ulushi)
FVG_MIN_ATR = 0.10         # FVG minimal balandligi (ATR ulushi)
MIN_SL_ATR = 0.35          # SL kamida shuncha uzoq (ATR)
MAX_SL_ATR = 2.60          # SL ko'pi bilan shuncha uzoq (ATR)
BUF_ATR = 0.18             # SL uchun supurish ekstremumidan zaxira (ATR)
ZONE_ATR = 0.20            # kirish zonasining minimal balandligi (ATR)
MIN_RR1 = 0.95             # TP1 kamida shuncha R
MIN_RR2 = 1.90             # TP2 kamida shuncha R
TP1_FALLBACK_R = 1.20      # daraja topilmasa TP1 = 1.20R
TP2_FALLBACK_R = 2.20      # daraja topilmasa TP2 = 2.20R
SCORE_MIN = 6.0            # shu balldan past setup olinmaydi
WARMUP = 80                # eng kam sham soni


# ------------------------------ yordamchi ------------------------------
def atr_series(df: pd.DataFrame, n: int = ATR_N) -> pd.Series:
    """Wilder ATR (EMA emas — klassik)."""
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l).abs(), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False).mean()


def ema(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(span=n, adjust=False).mean()


def pivots(df: pd.DataFrame, left: int = SWING_L, right: int = SWING_R,
           lookback: int | None = None) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Fraktal swing cho'qqilar: (indeks, narx). Faqat tugallangan shamlar."""
    hi, lo = df["high"].to_numpy(), df["low"].to_numpy()
    n = len(df)
    start = 0 if lookback is None else max(0, n - lookback)
    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    for i in range(max(left, start), n - right):
        h = hi[i]
        if h >= max(hi[i - left:i].max(), hi[i + 1:i + 1 + right].max()):
            highs.append((i, float(h)))
        lv = lo[i]
        if lv <= min(lo[i - left:i].min(), lo[i + 1:i + 1 + right].min()):
            lows.append((i, float(lv)))
    return highs, lows


def cluster_levels(points: list[tuple[int, float]], atr_v: float) -> list[dict]:
    """Bir-biriga yaqin nuqtalarni bitta darajaga birlashtiradi."""
    if not points or atr_v <= 0:
        return []
    tol = max(CLUSTER_ATR * atr_v, 1e-9)
    out: list[dict] = []
    for idx, price in sorted(points, key=lambda p: p[1]):
        if out and abs(price - out[-1]["price"]) <= tol:
            g = out[-1]
            g["price"] = (g["price"] * g["touches"] + price) / (g["touches"] + 1)
            g["touches"] += 1
            g["last_i"] = max(g["last_i"], idx)
        else:
            out.append({"price": float(price), "touches": 1, "last_i": idx})
    return out


def snr_levels(df: pd.DataFrame, atr_v: float, lookback: int = 220) -> list[dict]:
    """SNR darajalar: swing cho'qqilar + dumaloq raqamlar (10 ga karrali)."""
    seg = df.iloc[-lookback:]
    base = max(0, len(df) - lookback)
    highs, lows = pivots(seg, lookback=None)
    highs = [(i + base, p) for i, p in highs]
    lows = [(i + base, p) for i, p in lows]
    levels = cluster_levels(highs + lows, atr_v)
    px = float(df["close"].iloc[-1])
    # dumaloq raqamlar (10 ga karrali) — atrofdagina olamiz (±6 ATR)
    if atr_v > 0:
        step = 10.0 if atr_v < 6 else 25.0
        lo_r = px - 6 * atr_v
        hi_r = px + 6 * atr_v
        r = float(np.ceil(lo_r / step) * step)
        while r <= hi_r:
            levels.append({"price": round(r, 2), "touches": 1, "last_i": len(df) - 1,
                           "round": True})
            r += step
    # takrorlarni birlashtirib, kuchlilarni oldinga
    merged: list[dict] = []
    for lv in sorted(levels, key=lambda d: d["price"]):
        if merged and abs(lv["price"] - merged[-1]["price"]) <= CLUSTER_ATR * max(atr_v, 1e-9):
            m = merged[-1]
            m["touches"] += lv["touches"]
            m["price"] = (m["price"] + lv["price"]) / 2
        else:
            merged.append(dict(lv))
    for m in merged:
        m["touches"] = int(m.get("touches", 1))
    return merged


def time_col(df: pd.DataFrame) -> str:
    """v93 XATO TUZATISH: jonli ma'lumotda ustun `open_time`, backtest/testda `time`.

    Ilgari `d["time"]` deb olinardi -> jonli shamlarda KeyError -> BUTUN sniper
    skani xato bilan to'xtardi (shu sababli bot o'zi hech qachon signal bermagan).
    """
    if df is None:
        return "time"
    try:
        cols = list(df.columns)          # Index -> list (aksi holda ValueError)
    except Exception:  # noqa: BLE001
        return "time"
    if "time" in cols:
        return "time"
    if "open_time" in cols:
        return "open_time"
    return "time"


def prev_day_levels(df_1h: pd.DataFrame) -> dict:
    """Oldingi kun PDH/PDL/PDO (kun UTC bo'yicha)."""
    if df_1h is None or len(df_1h) < 30:
        return {}
    d = df_1h.copy()
    day = pd.to_datetime(d[time_col(d)], utc=True).dt.date
    g = d.groupby(day)
    if len(g) < 2:
        return {}
    days = list(g.groups.keys())
    prev = days[-2]
    sub = d[day == prev]
    if sub.empty:
        return {}
    return {"PDH": float(sub["high"].max()), "PDL": float(sub["low"].min()),
            "PDO": float(sub["open"].iloc[0])}


def htf_bias(df_1h: pd.DataFrame) -> tuple[str, str]:
    """1h yo'nalishi: EMA50 vs EMA200 + narx pozitsiyasi."""
    if df_1h is None or len(df_1h) < 60:
        return "NONE", "1h ma'lumot kam"
    c = df_1h["close"].astype(float)
    e50 = ema(c, 50).iloc[-1]
    e200 = ema(c, 200).iloc[-1] if len(c) >= 200 else ema(c, 100).iloc[-1]
    px = float(c.iloc[-1])
    if e50 > e200 and px > e50:
        return "UP", f"1h EMA50>EMA200 va narx ustida ({e50:.1f}>{e200:.1f})"
    if e50 < e200 and px < e50:
        return "DOWN", f"1h EMA50<EMA200 va narx ostida ({e50:.1f}<{e200:.1f})"
    return "NONE", "1h noaniq (aralash)"


def find_fvg(df: pd.DataFrame, direction: str, start: int, end: int,
             atr_v: float) -> dict | None:
    """`start..end` orasida yaratilgan FVG (3 sham bo'shlig'i) — eng kattasi."""
    best = None
    n = len(df)
    lo = df["low"].to_numpy()
    hi = df["high"].to_numpy()
    for i in range(max(2, start), min(end, n - 1) + 1):
        if direction == "BUY":
            gap_lo, gap_hi = hi[i - 2], lo[i]
            if gap_hi - gap_lo >= FVG_MIN_ATR * atr_v and hi[i] > hi[i - 1]:
                # mitiatsiya: keyingi shamlar bo'shliqni to'liq to'ldirib qo'ymagan
                if lo[i + 1:i + 4].min(initial=gap_hi) <= gap_lo:
                    continue
                cand = {"lo": float(gap_lo), "hi": float(gap_hi), "i": i}
                if best is None or (cand["hi"] - cand["lo"]) > (best["hi"] - best["lo"]):
                    best = cand
        else:
            gap_hi, gap_lo = lo[i - 2], hi[i]
            if gap_hi - gap_lo >= FVG_MIN_ATR * atr_v and lo[i] < lo[i - 1]:
                if hi[i + 1:i + 4].max(initial=gap_lo) >= gap_hi:
                    continue
                cand = {"lo": float(gap_lo), "hi": float(gap_hi), "i": i}
                if best is None or (cand["hi"] - cand["lo"]) > (best["hi"] - best["lo"]):
                    best = cand
    return best


def find_ob(df: pd.DataFrame, direction: str, start: int, end: int,
            atr_v: float) -> dict | None:
    """Order Block: impulsdan oldingi oxirgi qarama-qarshi sham."""
    o = df["open"].to_numpy()
    c = df["close"].to_numpy()
    hi = df["high"].to_numpy()
    lo = df["low"].to_numpy()
    for i in range(min(end, len(df) - 2), max(1, start) - 1, -1):
        body = abs(c[i] - o[i])
        if body < DISP_MIN_ATR * atr_v:
            continue
        j = i - 1
        if j < 1:
            continue
        if direction == "BUY" and c[j] < o[j] and c[i] > o[i] and c[i] > hi[j]:
            return {"lo": float(lo[j]), "hi": float(hi[j]), "i": j}
        if direction == "SELL" and c[j] > o[j] and c[i] < o[i] and c[i] < lo[j]:
            return {"lo": float(lo[j]), "hi": float(hi[j]), "i": j}
    return None


def detect_sweeps(df: pd.DataFrame, levels: list[dict], direction: str,
                  atr_v: float, lookback: int = SWEEP_LOOKBACK) -> list[dict]:
    """Likvidlik supurishlari — YANGISIDAN eskisiga qarab ro'yxat.

    Supurish = darajadan sanchib o'tib (wick), o'sha shamning O'ZIDA yana
    ichkariga qaytish. Oxirgi 1 sham hisobga olinmaydi: undan keyin impuls va
    FVG zonasi shakllanishi kerak (SWEEP_MIN_AGE).
    """
    if not levels or atr_v <= 0 or len(df) < SWEEP_MIN_AGE + 5:
        return []
    hi = df["high"].to_numpy()
    lo = df["low"].to_numpy()
    cl = df["close"].to_numpy()
    n = len(df)
    out: list[dict] = []
    for i in range(max(1, n - 1 - lookback), n - SWEEP_MIN_AGE):
        for lv in levels:
            p = float(lv["price"])
            if direction == "BUY":
                # qo'llab-quvvatlash ostidan supurish: low < p, close > p
                if lo[i] < p - SWEEP_MIN_ATR * atr_v and cl[i] > p:
                    ext = float(lo[i])
                    if ext > lo[max(0, i - 2):i + 1].min():
                        continue
                    out.append({"level": p, "i": i, "ext": ext,
                                "touches": int(lv.get("touches", 1))})
            else:
                if hi[i] > p + SWEEP_MIN_ATR * atr_v and cl[i] < p:
                    ext = float(hi[i])
                    if ext < hi[max(0, i - 2):i + 1].max():
                        continue
                    out.append({"level": p, "i": i, "ext": ext,
                                "touches": int(lv.get("touches", 1))})
    if not out:
        return []
    # bir shamda bir nechta daraja bo'lsa — eng yaqinini (kuchlisini) olamiz
    out.sort(key=lambda c: (-c["i"], c["ext"] if direction == "BUY" else -c["ext"]))
    seen: set = set()
    res: list[dict] = []
    for c in out:
        k = (c["i"], round(float(c["level"]), 1))
        if k in seen:
            continue
        seen.add(k)
        res.append(c)
    return res


def detect_sweep(df: pd.DataFrame, levels: list[dict], direction: str,
                 atr_v: float, lookback: int = SWEEP_LOOKBACK) -> dict | None:
    """Eng YANGI supurish (eski nom — moslik uchun saqlanadi)."""
    sw = detect_sweeps(df, levels, direction, atr_v, lookback)
    return sw[0] if sw else None


def has_displacement(df: pd.DataFrame, direction: str, start: int, end: int,
                     atr_v: float, ref: float) -> int | None:
    """Supurishdan keyin kuchli impuls (displacement) bormi -> indeks."""
    o = df["open"].to_numpy()
    c = df["close"].to_numpy()
    for i in range(max(1, start), min(end, len(df) - 1) + 1):
        body = c[i] - o[i]
        if direction == "BUY" and body >= DISP_MIN_ATR * atr_v and c[i] > ref:
            return i
        if direction == "SELL" and -body >= DISP_MIN_ATR * atr_v and c[i] < ref:
            return i
    return None


@dataclass
class Setup:
    """Tayyor setup — bot shu ma'lumotdan signal yasaydi."""
    direction: str            # BUY | SELL
    entry: float              # kirish narxi (zona o'rtasi)
    zone_lo: float
    zone_hi: float
    sl: float
    tp1: float
    tp2: float
    atr: float
    score: float
    mode: str                 # SWEEP+FVG | SWEEP+OB | SWEEP
    reason: str = ""
    parts: list[str] = field(default_factory=list)

    @property
    def risk(self) -> float:
        return abs(self.entry - self.sl)

    @property
    def rr1(self) -> float:
        r = self.risk
        return abs(self.tp1 - self.entry) / r if r > 0 else 0.0

    @property
    def rr2(self) -> float:
        r = self.risk
        return abs(self.tp2 - self.entry) / r if r > 0 else 0.0


def analyze_one(d5: pd.DataFrame, d15: pd.DataFrame | None = None,
                d1h: pd.DataFrame | None = None,
                i: int | None = None,
                extra_levels: list[dict] | None = None,
                bias_force: tuple[str, str] | None = None,
                score_min: float | None = None,
                fresh_max: int | None = None,
                disp_min: float | None = None) -> Setup | None:
    """Trigger TF kesimida setup qidiradi (5m yoki v93 da M1).

    `i` — shu indeksgacha bo'lgan ma'lumot bilan (jonli: None = oxirgi sham).
    `extra_levels` — katta TF (1h/4h/1d) darajalari (likvidlik havzalari).
    `bias_force` — tayyor HTF bias (bias, izoh); `score_min` — ball chegarasi.
    """
    if d5 is None or len(d5) < WARMUP:
        return None
    end = len(d5) - 1 if i is None else int(i)
    if end < WARMUP or end >= len(d5):
        return None
    win = d5.iloc[max(0, end - 260):end + 1]
    a = atr_series(win).iloc[-1]
    if not np.isfinite(a) or a <= 0:
        return None
    atr_v = float(a)
    px = float(win["close"].iloc[-1])
    levels = snr_levels(win, atr_v)
    pd_ = prev_day_levels(d1h)
    for k, v in pd_.items():
        levels.append({"price": float(v), "touches": 2, "last_i": len(win) - 1, "day": k})
    if extra_levels:                       # v93: HTF (1h/4h/1d) darajalari
        for lv in extra_levels:
            levels.append(dict(lv))
    if bias_force:
        bias, bias_txt = str(bias_force[0]), str(bias_force[1])
    else:
        bias, bias_txt = htf_bias(d1h)
    if bias == "NONE":
        return None
    # 15m tasdiqi (ixtiyoriy): narx 15m EMA50 tomonida bo'lsin
    d15_ok = True
    if d15 is not None and len(d15) > 60:
        e50 = ema(d15["close"].astype(float), 50).iloc[-1]
        d15_ok = (px > e50) if bias == "UP" else (px < e50)

    # MUHIM: bias ('UP'/'DOWN') ni yo'nalishga ('BUY'/'SELL') o'giramiz
    direction = "BUY" if bias == "UP" else "SELL"
    if d15_ok:
        for sw in detect_sweeps(win, levels, direction, atr_v)[:8]:

            disp_i = has_displacement(win, direction, sw["i"], len(win) - 1, atr_v,
                                      sw["level"])
            if disp_i is None:
                continue
            # v94 (1): SUPURISH YANGI bo'lsin — eskisi allaqachon o'ynagan
            if fresh_max:
                if (len(win) - 1 - int(sw["i"])) > int(fresh_max):
                    continue
            # v94 (2): IMPULS KUCHLI bo'lsin — sham tanasi ATR dan katta ulushda
            if disp_min:
                _body = abs(float(win["close"].iloc[disp_i]) -
                            float(win["open"].iloc[disp_i]))
                if _body < float(disp_min) * atr_v:
                    continue
            fvg = find_fvg(win, direction, sw["i"], len(win) - 1, atr_v)
            ob = find_ob(win, direction, sw["i"], len(win) - 1, atr_v)
            if fvg is None and ob is None:
                continue
            zone = fvg if fvg is not None else ob
            mode = ("SWEEP+FVG" if fvg is not None else "SWEEP+OB")
            if fvg is not None and ob is not None:
                mode = "SWEEP+FVG+OB"
            zlo, zhi = float(zone["lo"]), float(zone["hi"])
            if zhi - zlo < ZONE_ATR * atr_v:
                mid = (zlo + zhi) / 2
                zlo, zhi = mid - ZONE_ATR * atr_v / 2, mid + ZONE_ATR * atr_v / 2
            # ICT qoidasi: narx impulsdan keyin ZONAGA QAYTISHI kerak
            # (zona supurish ekstremumi bilan hozirgi narx orasida bo'lsin)
            if direction == "BUY":
                if zhi > px + 0.15 * atr_v:      # zona narxdan yuqori -> quvish bo'lardi
                    continue
                if zlo <= sw["ext"] + 0.05 * atr_v:   # zona supurish ostida -> SL juda uzoq
                    continue
                sl = min(sw["ext"], zlo) - BUF_ATR * atr_v
                risk = (zlo + zhi) / 2 - sl
            else:
                if zlo < px - 0.15 * atr_v:
                    continue
                if zhi >= sw["ext"] - 0.05 * atr_v:
                    continue
                sl = max(sw["ext"], zhi) + BUF_ATR * atr_v
                risk = sl - (zlo + zhi) / 2
            entry = (zlo + zhi) / 2
            if risk <= 0:
                continue
            if risk < MIN_SL_ATR * atr_v or risk > MAX_SL_ATR * atr_v:
                continue
            tps = _targets(entry, risk, direction, levels, atr_v)
            if tps is None:
                continue
            tp1, tp2 = tps
            score, parts = _score(sw, disp_i, fvg, ob, bias, zhi - zlo, atr_v, risk,
                                  tp1, tp2, entry, d15_ok)
            if score < float(score_min if score_min is not None else SCORE_MIN):
                continue
            why = (f"{mode} | supurish {sw['level']:.2f} ({sw['touches']} tegish) | "
                   f"{bias_txt} | R:R 1:{abs(tp1 - entry) / risk:.1f} / "
                   f"1:{abs(tp2 - entry) / risk:.1f}")
            return Setup(direction=direction, entry=round(entry, 2),
                         zone_lo=round(zlo, 2), zone_hi=round(zhi, 2),
                         sl=round(sl, 2), tp1=round(tp1, 2), tp2=round(tp2, 2),
                         atr=round(atr_v, 2), score=round(score, 1), mode=mode,
                             reason=why, parts=parts)
    return None


def _targets(entry: float, risk: float, direction: str, levels: list[dict],
             atr_v: float) -> tuple[float, float] | None:
    """TP1/TP2 — yo'ldagi eng yaqin qarshiliklar, bo'lmasa R bo'yicha."""
    if direction == "BUY":
        above = sorted([float(l["price"]) for l in levels if float(l["price"]) > entry + 0.15 * atr_v])
        cand = above[0] if above else entry + TP1_FALLBACK_R * risk
        tp1 = max(cand, entry + MIN_RR1 * risk)
        above2 = [p for p in above if p > tp1 + 0.2 * atr_v]
        cand2 = above2[0] if above2 else entry + TP2_FALLBACK_R * risk
        tp2 = max(cand2, entry + MIN_RR2 * risk)
    else:
        below = sorted([float(l["price"]) for l in levels if float(l["price"]) < entry - 0.15 * atr_v],
                       reverse=True)
        cand = below[0] if below else entry - TP1_FALLBACK_R * risk
        tp1 = min(cand, entry - MIN_RR1 * risk)
        below2 = [p for p in below if p < tp1 - 0.2 * atr_v]
        cand2 = below2[0] if below2 else entry - TP2_FALLBACK_R * risk
        tp2 = min(cand2, entry - MIN_RR2 * risk)
    if direction == "BUY" and not (tp1 > entry and tp2 > tp1):
        return None
    if direction == "SELL" and not (tp1 < entry and tp2 < tp1):
        return None
    return float(tp1), float(tp2)


def _score(sw: dict, disp_i: int, fvg: dict | None, ob: dict | None, bias: str,
           zone_h: float, atr_v: float, risk: float, tp1: float, tp2: float,
           entry: float, d15_ok: bool) -> tuple[float, list[str]]:
    """0-10 ball: setup sifati (jonli va backtestda bir xil mezon)."""
    parts: list[str] = []
    s = 0.0
    # 1) supurish sifati (0-2.0)
    t = min(int(sw.get("touches", 1)), 4) / 4.0
    s += 2.0 * (0.55 + 0.45 * t)
    parts.append(f"supurish +{2.0 * (0.55 + 0.45 * t):.1f}")
    # 2) impuls (0-2.0)
    s += 2.0
    parts.append("impuls +2.0")
    # 3) FVG/OB (0-2.0)
    if fvg is not None and ob is not None:
        s += 2.0
        parts.append("FVG+OB +2.0")
    elif fvg is not None:
        s += 1.6
        parts.append("FVG +1.6")
    else:
        s += 1.1
        parts.append("OB +1.1")
    # 4) HTF mosligi (0-1.5)
    s += 1.5 if d15_ok else 0.9
    parts.append(("HTF mos +1.5" if d15_ok else "HTF qisman +0.9"))
    # 5) R:R (0-1.5)
    r1 = abs(tp1 - entry) / risk if risk else 0
    r2 = abs(tp2 - entry) / risk if risk else 0
    s += min(1.5, 0.5 * r1 + 0.35 * max(0.0, r2 - 1.0))
    parts.append(f"R:R +{min(1.5, 0.5 * r1 + 0.35 * max(0.0, r2 - 1.0)):.1f}")
    # 6) zona sifati (0-1.0)
    z = min(1.0, (zone_h / atr_v) / 0.6)
    s += z
    parts.append(f"zona +{z:.1f}")
    return min(s, 10.0), parts


def htf_bias_multi(d1h: pd.DataFrame | None, d4h: pd.DataFrame | None = None,
                   d1d: pd.DataFrame | None = None) -> tuple[str, str, int]:
    """v93: KATTA TIMEFRAME KUZATUVI — 1d -> 4h -> 1h bir yo'nalishda bo'lsa kuchli.

    Qaytaradi: (bias UP|DOWN|NONE, izoh, necha TF mos keldi).
    """
    b1, t1 = htf_bias(d1h)
    if b1 == "NONE":
        return "NONE", t1 or "1h yo'nalish aniq emas", 0
    agree = 1
    parts = [f"1h {b1}"]
    for df, nm in ((d4h, "4h"), (d1d, "1d")):
        if df is None or len(df) < 60:
            continue
        b, _t = htf_bias(df)
        if b == b1:
            agree += 1
            parts.append(f"{nm} mos ({b})")
        elif b != "NONE":
            parts.append(f"{nm} qarama-qarshi ({b})")
    return b1, " · ".join(parts), agree


def htf_opposite(d4h: pd.DataFrame | None, bias: str) -> bool:
    """4h aniq qarama-qarshi bo'lsa — M1 da savdo ochilmaydi (HTF filtri)."""
    if d4h is None or len(d4h) < 60 or bias not in ("UP", "DOWN"):
        return False
    b4, _ = htf_bias(d4h)
    return b4 != "NONE" and b4 != bias


def htf_levels(d1h: pd.DataFrame | None, d4h: pd.DataFrame | None = None,
               max_per_tf: int = 6) -> list[dict]:
    """Katta TF darajalari (1h/4h swing + dumaloq) — M1 uchun likvidlik havzalari."""
    out: list[dict] = []
    for df, nm in ((d4h, "4h"), (d1h, "1h")):
        if df is None or len(df) < 40:
            continue
        try:
            a = float(atr_series(df).iloc[-1])
        except Exception:  # noqa: BLE001
            continue
        if not np.isfinite(a) or a <= 0:
            continue
        try:
            lvs = snr_levels(df, a, lookback=160)
        except Exception:  # noqa: BLE001
            continue
        px = float(df["close"].iloc[-1])
        lvs = sorted(lvs, key=lambda d: abs(float(d["price"]) - px))[:max_per_tf]
        for lv in lvs:
            out.append({"price": float(lv["price"]),
                        "touches": int(lv.get("touches", 1)) + 1,
                        "last_i": 0, "day": nm})
    return out


# v94: OLTIN eng ko'p harakat qiladigan soatlar (UTC): London + Nyu-York
KILLZONES_UTC = ((6, 10), (12, 16))


def in_killzone(ts) -> bool:
    """v94: sham vaqti faol seansda (London/NY) bo'lsa True."""
    try:
        h = int(pd.Timestamp(ts).hour)
    except Exception:  # noqa: BLE001
        return True
    return any(a <= h < b for a, b in KILLZONES_UTC)


def analyze_m1(d1m: pd.DataFrame, d5m: pd.DataFrame | None = None,
               d15m: pd.DataFrame | None = None, d1h: pd.DataFrame | None = None,
               d4h: pd.DataFrame | None = None, d1d: pd.DataFrame | None = None,
               i: int | None = None, score_min: float | None = None,
               fresh_max: int | None = None, disp_min: float | None = None,
               killzone: bool = False) -> Setup | None:
    """v93 ASOSIY: KATTA TF larda kuzatib, BITTA tahlil M1 da va savdo M1 da.

    Tartib: 1d/4h/1h yo'nalishi (bias) -> HTF darajalari (likvidlik) ->
    M1 da supurish + impuls + FVG/OB -> kirish zonasi, SL, TP1/TP2 (M1 narxida).
    """
    if d1m is None or len(d1m) < WARMUP:
        return None
    bias, bias_txt, agree = htf_bias_multi(d1h, d4h, d1d)
    if bias == "NONE":
        return None
    if htf_opposite(d4h, bias):
        return None
    if killzone:
        _end = len(d1m) - 1 if i is None else int(i)
        if not in_killzone(d1m[time_col(d1m)].iloc[_end]):
            return None
    extra = htf_levels(d1h, d4h)
    trig = d15m if (d15m is not None and len(d15m) > 60) else d5m
    setup = analyze_one(d1m, trig, d1h, i=i, extra_levels=extra,
                        bias_force=(bias, bias_txt), score_min=score_min,
                        fresh_max=fresh_max, disp_min=disp_min)
    if setup is None:
        return None
    bonus = 0.4 * max(0, agree - 1)
    setup.score = round(min(10.0, float(setup.score) + bonus), 1)
    setup.parts.append(f"HTF stack {agree}/3 +{bonus:.1f}")
    setup.mode = "M1 " + str(setup.mode)
    setup.reason = f"HTF: {bias_txt} || M1: {setup.reason}"
    return setup


def analyze(d5: pd.DataFrame, d15: pd.DataFrame | None = None,
            d1h: pd.DataFrame | None = None) -> Setup | None:
    """Jonli rejim (eski 5m yo'l — zaxira): oxirgi ma'lumot bo'yicha setup."""
    return analyze_one(d5, d15, d1h, None)
