"""v80: MOMENTUM — Lot 2 ni +4R da yopish yoki +5R gacha olib borish qarori.

Qoida (foydalanuvchi talabi): **Lot 2 +4R yoki +5R da yopiladi — momentumga qarab.**

  * +4R ga yetganda momentum KUCHLI bo'lsa -> +5R kutiladi,
    stop +4R ga QULFLANADI (foyda 4R dan pastga tushmaydi);
  * momentum SO'NGAN bo'lsa -> darhol +4R da yopiladi;
  * kutib turganda momentum so'nsa ham +4R da yopiladi.

Momentum bahosi 0..1 (oxirgi 3-5 yopilgan sham): yo'nalish monotonligi, yangi
yuqori/past, tana kattaligi, qarama-qarshi shamlar yo'qligi va tezlik.
"""
from __future__ import annotations

import pandas as pd

STRONG = 0.60          # shundan yuqori — +5R ga yuboriladi
WEAK = 0.35            # shundan past — momentum yo'q


def _vals(df: pd.DataFrame, col: str, n: int = 6) -> list[float]:
    try:
        s = df[col].astype(float).tail(n)
        return [float(x) for x in s.tolist()]
    except Exception:  # noqa: BLE001
        return []


def score(df: pd.DataFrame, buy: bool) -> float:
    """0..1 momentum bahosi (yopilgan shamlar bo'yicha)."""
    c = _vals(df, "close")
    if len(c) < 3:
        return 0.0
    h = _vals(df, "high")
    low = _vals(df, "low")
    o = _vals(df, "open")
    pts = 0.0
    tot = 0.0

    def add(ok: bool, w: float) -> None:
        nonlocal pts, tot
        tot += w
        if ok:
            pts += w

    # 1) oxirgi 2 sham yo'nalishda (kuchli qo'shni)
    add((c[-1] > c[-2]) if buy else (c[-1] < c[-2]), 1.0)
    # 2) oxirgi 3 sham monoton
    add((c[-1] > c[-2] > c[-3]) if buy else (c[-1] < c[-2] < c[-3]), 1.0)
    # 3) yangi yuqori/past (oxirgi 5 sham ichida eng ekstremal)
    if len(h) >= 4 and len(low) >= 4:
        add((h[-1] >= max(h[-4:])) if buy else (low[-1] <= min(low[-4:])), 1.2)
    # 4) tana yo'nalishda va o'rtachadan katta emas (charchoq belgisi emas)
    if len(o) >= 3:
        body = c[-1] - o[-1]
        bodies = [abs(c[i] - o[i]) for i in range(len(o))]
        avg = (sum(bodies[:-1]) / max(1, len(bodies) - 1)) or 0.0
        add((body > 0) if buy else (body < 0), 0.8)
        if avg > 0:
            add(abs(body) >= avg * 0.6, 0.4)
    # 5) oxirgi 3 shamda qarama-qarshi yopilish yo'q
    opp = 0
    for i in range(max(1, len(c) - 3), len(c)):
        ok_dir = (c[i] > c[i - 1]) if buy else (c[i] < c[i - 1])
        if not ok_dir:
            opp += 1
    add(opp <= 1, 1.0)
    # 6) tezlik: oxirgi 3 shamda narx stop masofasining 20% idan ko'p yurgan
    try:
        move = abs(c[-1] - c[-3])
        rng = abs(c[-1] - c[-3]) / max(1e-9, abs(c[-1])) if c[-1] else 0.0
        add(move > 0 and rng > 0.0005, 0.6)
    except Exception:  # noqa: BLE001
        pass

    return round(pts / tot, 3) if tot else 0.0


def is_strong(df: pd.DataFrame, buy: bool) -> bool:
    return score(df, buy) >= STRONG


def label(sc: float) -> str:
    if sc >= STRONG:
        return "kuchli"
    if sc >= WEAK:
        return "o'rtacha"
    return "so'ndi"


def decide(df: pd.DataFrame, buy: bool) -> tuple[bool, float, str]:
    """(5R ga yuborilsinmi?, baho, so'z) — Lot 2 +4R dagi qaror."""
    sc = score(df, buy)
    return (sc >= STRONG), sc, label(sc)
