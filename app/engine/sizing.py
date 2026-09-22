"""v82: RISK va MONEY MANAGEMENT — lot balansga qarab ochiladi.

Qoida (foydalanuvchi talabi):
    Lot hajmi BALANSning 0.5% (yoki 1% / 2%) riskidan hisoblanadi:
        risk_pul = balans x risk_% / 100
        hajm(oz) = risk_pul / stop_masofasi
        lot      = hajm(oz) / 100        (1 lot XAU = 100 oz)

Ya'ni SL urilsa yo'qoladigan pul AYNAN 0.5% (yoki 1%) bo'ladi — brokerdagidek.
Hajm 2 ta lotga teng bo'linadi: Lot1 (+3R) va Lot2 (+4R/+5R).

Fiks (1.00 lot) hajm QAYTARILMADI — endi hajm balansga bog'liq, faqat yuqori
chegara bor (xavfsizlik uchun `max_lot`, standart 1.00 lot).
"""
from __future__ import annotations

CONTRACT_OZ = 100.0          # 1 lot XAUUSD = 100 untsiya
LOT_STEP = 0.01              # minimal qadam (brokerdagi kabi)
MIN_LOT = 0.01               # bitta lot uchun minimal hajm
RISK_CHOICES = (0.5, 1.0, 2.0)
DEFAULT_RISK = 0.5


def _f(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def clean_risk(v) -> float:
    """Risk foizini ruxsat etilgan qiymatga keltiradi (0.5 / 1 / 2)."""
    x = _f(v, DEFAULT_RISK)
    for c in RISK_CHOICES:
        if abs(x - c) < 0.001:
            return c
    if x <= 0:
        return DEFAULT_RISK
    return min(5.0, max(0.1, round(x, 2)))


def risk_money(balance: float, risk_percent: float) -> float:
    """Shu signal uchun maksimal zarar (dollar)."""
    b = max(0.0, _f(balance))
    p = clean_risk(risk_percent)
    return b * p / 100.0


def risk_distance_of(entry: float, sl: float) -> float:
    return abs(_f(entry) - _f(sl))


def total_lot_for_risk(balance: float, risk_percent: float, risk_distance: float,
                       contract: float = CONTRACT_OZ,
                       max_lot: float = 1.0) -> float:
    """Riskdan kelib chiqqan JAMI hajm (lot)."""
    d = max(0.0, _f(risk_distance))
    c = max(1.0, _f(contract, CONTRACT_OZ) or CONTRACT_OZ)
    if d <= 0:
        return 0.0
    money = risk_money(balance, risk_percent)
    lots = money / (d * c)
    # brokerdagi qadam (0.01 lot)
    lots = round(lots / LOT_STEP) * LOT_STEP
    # ikki lot bor — eng kami 0.01 + 0.01
    lots = max(MIN_LOT * 2, lots)
    cap = _f(max_lot, 1.0) or 1.0
    if cap > 0:
        lots = min(cap, lots)
    return round(lots, 2)


def size_for(balance: float, risk_percent: float, risk_distance: float,
             contract: float = CONTRACT_OZ, max_lot: float = 1.0) -> dict:
    """To'liq hisob: jami va har bir lot uchun hajm, risk, kutilgan foyda.

    Qaytaradi: {lot, half_lot, qty_oz, half_qty, risk_pct, risk_money,
                half_risk, capped, min_used}
    """
    p = clean_risk(risk_percent)
    c = max(1.0, _f(contract, CONTRACT_OZ) or CONTRACT_OZ)
    d = max(0.0, _f(risk_distance))
    money = risk_money(balance, p)
    lot = total_lot_for_risk(balance, p, d, c, max_lot)
    half = round(lot / 2.0, 2)
    if half < MIN_LOT:
        half = MIN_LOT
    half2 = round(lot - half, 2)
    if half2 < MIN_LOT:
        half2 = MIN_LOT
        lot = round(half + half2, 2)
    half_qty = half * c
    qty = half_qty * 2.0
    return {
        "lot": round(lot, 2),
        "half_lot": round(half, 2),
        "qty_oz": round(qty, 4),
        "half_qty": round(half_qty, 4),
        "risk_pct": p,
        "risk_money": round(money, 2),
        "half_risk": round(half_qty * d, 2),
        "capped": bool(money > 0 and lot >= (_f(max_lot, 1.0) or 1.0) - 1e-9),
        "min_used": bool(money / (d * c) < MIN_LOT * 2) if d > 0 else False,
    }


def split_amount(qty_oz: float, risk_distance: float, contract: float = CONTRACT_OZ) -> dict:
    """Qo'lda kiritilgan hajm uchun risk/foyda (hisob-hisob uchun)."""
    q = max(0.0, _f(qty_oz))
    d = max(0.0, _f(risk_distance))
    c = max(1.0, _f(contract, CONTRACT_OZ) or CONTRACT_OZ)
    return {
        "qty_oz": q, "lot": round(q / c, 2), "risk_money": round(q * d, 2),
        "half_qty": round(q / 2.0, 4), "half_risk": round(q * d / 2.0, 2),
    }


def risk_line(balance: float, risk_percent: float, entry: float, sl: float,
              contract: float = CONTRACT_OZ, max_lot: float = 1.0) -> str:
    """Signal kartasi uchun qator: risk % va hajm."""
    d = risk_distance_of(entry, sl)
    s = size_for(balance, risk_percent, d, contract, max_lot)
    if s["lot"] <= 0:
        return ""
    extra = ""
    if s["capped"]:
        extra = " (yuqori chegara)"
    elif s["min_used"]:
        extra = " (minimal hajm)"
    return (
        f"\U0001F3AF <b>Risk: {s['risk_pct']:.2f}%</b> = "
        f"<b>{s['risk_money']:,.2f}$</b> \u00B7 hajm "
        f"<b>{s['half_lot']:,.2f} + {s['half_lot']:,.2f} lot</b> "
        f"(jami {s['lot']:,.2f} lot){extra}\n"
        f"      SL urilsa: <b>\u2212{s['risk_money']:,.2f}$</b> "
        f"(balans {max(0.0, _f(balance)):,.2f}$)"
    )


def label(pct: float) -> str:
    """«0.5%» ko'rinishi."""
    p = clean_risk(pct)
    return f"{p:g}%"


# ==================== v82: ESKIRGAN SIGNAL HIMOYASI ====================
# Kanal narxi (XAU/USD) bilan bozor narxi (XAUUSDT) farq qilib ketsa yoki signal
# kechikib kelsa — real brokerda ham bunday narxda kirib bo'lmaydi. Shuning uchun
# ochishdan oldin tekshiriladi.
MAX_DRIFT_R = 1.0        # kirish darajasidan shu R dan uzoq bo'lsa — ochilmaydi
MAX_DRIFT_PCT = 0.15     # yoki narxning 0.15% idan uzoq bo'lsa


def entry_drift_ok(entry: float, sl: float, price, direction: str = "") -> tuple[bool, str]:
    """(ok, sabab). price None bo'lsa — tekshirilmaydi (True)."""
    e = _f(entry)
    try:
        px = float(price) if price is not None else 0.0
    except (TypeError, ValueError):
        px = 0.0
    if e <= 0 or px <= 0:
        return True, ""
    d = risk_distance_of(e, sl)
    diff = abs(px - e)
    limit = max(d * MAX_DRIFT_R, e * MAX_DRIFT_PCT / 100.0) if d > 0 else e * MAX_DRIFT_PCT / 100.0
    if diff <= limit:
        return True, ""
    d_txt = f"{diff / d:.1f}R" if d > 0 else f"{diff:,.2f}$"
    return False, (f"bozor narxi {px:,.2f} kirish darajasidan {d_txt} uzoqda "
                   f"(kanal: {e:,.2f}) — eski/kechikkan signal")


def r_sane(r: float, limit: float = 6.0) -> bool:
    """R qiymati ishonchli oraliqdami (29R kabi xatolar ko'rinmasin)."""
    try:
        return abs(float(r)) <= limit
    except (TypeError, ValueError):
        return False
