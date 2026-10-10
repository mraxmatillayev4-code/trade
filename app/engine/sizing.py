"""v82: RISK va MONEY MANAGEMENT — lot balansga qarab ochiladi.

Qoida (foydalanuvchi talabi):
    [ESKI — v86 dan BERI ISHLATILMAYDI, faqat tarix uchun qoldi]
    Eski formula: lot hajmi balansning 0.5% (yoki 1% / 2%) riskidan
    hisoblanardi. Endi hajm QO'LDA tanlanadi (app/services/lot_settings.py,
    umumiy sozlama `paper_lot`).
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
    # v84: minimal hajm majburiy bo'lsa HAQIQIY risk (budjetdan katta bo'ladi)
    real_risk = round(qty * d, 2)
    return {
        "real_risk": real_risk,
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
    if s["min_used"]:
        # v84: 0.01 lotdan kichigi yo'q — HAQIQIY zarar budjetdan katta bo'ladi
        return (
            f"\U0001F3AF <b>Risk: {s['risk_pct']:.2f}%</b> = "
            f"<b>{s['risk_money']:,.2f}$</b> \u00B7 hajm "
            f"<b>{s['half_lot']:,.2f} + {s['half_lot']:,.2f} lot</b> "
            f"(jami {s['lot']:,.2f} lot){extra}\n"
            f"      \u2757 SL urilsa haqiqiy zarar: "
            f"<b>\u2212{s['real_risk']:,.2f}$</b> \u2014 budjetdan katta "
            f"(0.01 lotdan kichigi yo'q)"
        )
    return (
        f"\U0001F3AF <b>Risk: {s['risk_pct']:.2f}%</b> = "
        f"<b>{s['risk_money']:,.2f}$</b> \u00B7 hajm "
        f"<b>{s['half_lot']:,.2f} + {s['half_lot']:,.2f} lot</b> "
        f"(jami {s['lot']:,.2f} lot){extra}\n"
        f"      SL urilsa: <b>\u2212{s['risk_money']:,.2f}$</b> "
        f"(balans {max(0.0, _f(balance)):,.2f}$)"
    )


def label(pct: float) -> str:
    """«0.5%» ko'rinishi (eski, ishlatilmaydi)."""
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

def size_fixed(per_lot: float, risk_distance: float,
               contract: float = CONTRACT_OZ) -> dict:
    """v86: FOYDALANUVCHI TANLAGAN hajm (risk foizidan EMAS).

    `per_lot` — HAR BIR lot hajmi (bot 2 lot ochadi: Lot1 + Lot2).
    Qaytaradigan kalitlar `size_for` bilan bir xil (engine o'zgarmasin).
    """
    c = max(1.0, _f(contract, CONTRACT_OZ) or CONTRACT_OZ)
    d = max(0.0, _f(risk_distance))
    l = round(max(MIN_LOT, _f(per_lot, MIN_LOT)), 2)
    lots_total = round(l * 2.0, 2)
    qty = lots_total * c
    return {
        "real_risk": round(qty * d, 2),
        "lot": lots_total,
        "half_lot": l,
        "per_lot": l,
        "qty_oz": round(qty, 4),
        "half_qty": round(l * c, 4),
        "risk_pct": 0.0,
        "risk_money": round(qty * d, 2),
        "half_risk": round(l * c * d, 2),
        "capped": False,
        "min_used": False,
        "fixed": True,
    }


def fixed_line(per_lot: float, entry: float, sl: float,
               balance: float = 0.0) -> str:
    """Karta uchun qator: qo'lda tanlangan hajm + SL urilsa qancha pul."""
    from app.services import lot_settings as _LS
    return _LS.line(per_lot, entry=entry, sl=sl, balance=balance or None)


# ------------------------------------------------------------- v95: pip
def pip_size(symbol: str) -> float:
    """1 pip narxi: oltin 0.1$, JPY 0.01, qolganlar 0.0001."""
    sym = (symbol or "").upper()
    if "XAU" in sym or "GOLD" in sym:
        return 0.1
    if "JPY" in sym:
        return 0.01
    return 0.0001


def sanitize_channel_levels(direction: str, entry: float | None,
                            sl: float | None, tps: list | None,
                            symbol: str) -> dict:
    """v95 KANAL darajalari (user qoidasi):

    * SL aytilmagan/nosog'lom -> 10 pip; SL teskari tomonda -> reject.
    * TP aytilmagan/nosog'lom -> TP1 40 pip, TP2 50 pip.
    * tp3 = TP1 (Lot1 TP1 da yopiladi), Lot2 poli = TP1 -> 40..50 pip oralig'i.
    Qaytaradi: dict(ok, why, entry, sl, tp1, tp2, tp3, tps_src)
    """
    d = (direction or "").upper()
    buy = d == "BUY"
    pip = pip_size(symbol)
    e = float(entry or 0)
    if e <= 0:
        return {"ok": False, "why": "kirish narxi yo'q"}
    sl_ok = None
    if sl and float(sl) > 0 and abs(e - float(sl)) > 1e-9:
        cand = float(sl)
        if (buy and cand < e) or ((not buy) and cand > e):
            sl_ok = cand
        else:
            return {"ok": False, "why": f"SL teskari tomonda ({cand:,.2f})"}
    sl_def = 10.0 * pip
    if sl_ok is None:
        sl_ok = (e - sl_def) if buy else (e + sl_def)
    else:
        dist = abs(e - sl_ok)
        if dist > 300.0 * pip or dist < 0.5 * pip:
            sl_ok = (e - sl_def) if buy else (e + sl_def)
    good = []
    for t in (tps or []):
        try:
            t = float(t)
        except (TypeError, ValueError):
            continue
        if t <= 0:
            continue
        if (buy and t > e) or ((not buy) and t < e):
            if abs(t - e) <= 600.0 * pip:
                good.append(t)
    good = sorted(good, reverse=not buy)[:3]
    tp1_def = 40.0 * pip
    tp2_def = 50.0 * pip
    if good:
        tp1 = good[0]
        tp2 = good[1] if len(good) > 1 else ((e + tp2_def) if buy else (e - tp2_def))
        src = "CHANNEL"
    else:
        tp1 = (e + tp1_def) if buy else (e - tp1_def)
        tp2 = (e + tp2_def) if buy else (e - tp2_def)
        src = "DEFAULT"
    return {"ok": True, "why": "", "entry": e, "sl": float(sl_ok),
            "tp1": float(tp1), "tp2": float(tp2), "tp3": float(tp1),
            "tps_src": src}

# ------------------------------------------------------------- v99: RE-SANITIZE
def levels_side_ok(direction: str, entry: float, sl: float) -> bool:
    """v99: SL kirishning to'g'ri tomonidami? (BUY: sl<entry, SELL: sl>entry)."""
    try:
        e = float(entry or 0.0)
        s = float(sl or 0.0)
        if e <= 0 or s <= 0 or abs(e - s) < 1e-9:
            return False
        d = str(direction or "").upper()
        if d == "BUY":
            return s < e
        if d == "SELL":
            return s > e
        return False
    except Exception:  # noqa: BLE001
        return False


def resanitize_levels(direction: str, entry: float, sl: float,
                      tp1: float, tp2: float, tp3: float,
                      tps_src: str, symbol: str) -> dict:
    """v99: entry ALMASHGANDA (bozor/fill) darajalarni YANGI kirishga
    qayta moslashtirish.

    * SL yangi kirishning teskari tomonida qolsa -> ok=False (signal RAD);
    * SL masofasi nosog'lom (>300 pip yoki <0.5 pip) -> default 10 pip;
    * TP lar teskari tomonda yoki >600 pip bo'lsa -> default 40/50 pip.
    Kanalning SOG'LOM TP lari tegilmaydi (user qoidasi).
    """
    e = float(entry or 0.0)
    if e <= 0:
        return {"ok": False, "why": "kirish narxi yo'q"}
    if not levels_side_ok(direction, e, sl):
        try:
            txt = f"{float(sl or 0.0):,.2f}"
        except Exception:  # noqa: BLE001
            txt = str(sl)
        return {"ok": False,
                "why": f"SL yangi kirishning teskari tomonida ({txt})"}
    pip = pip_size(symbol)
    buy = str(direction or "").upper() == "BUY"
    s = float(sl)
    dist = abs(e - s)
    if dist > 300.0 * pip or dist < 0.5 * pip:
        s = (e - 10.0 * pip) if buy else (e + 10.0 * pip)

    def tp_ok(t: float) -> bool:
        t = float(t or 0.0)
        if t <= 0:
            return False
        if not ((t > e) if buy else (t < e)):
            return False
        return abs(t - e) <= 600.0 * pip

    src = str(tps_src or "").upper()
    t1, t2, t3 = float(tp1 or 0.0), float(tp2 or 0.0), float(tp3 or 0.0)
    if src == "CHANNEL" and not tp_ok(t1):
        src = "DEFAULT"
    if src != "CHANNEL" or t1 <= 0:
        t1 = (e + 40.0 * pip) if buy else (e - 40.0 * pip)
        t2 = (e + 50.0 * pip) if buy else (e - 50.0 * pip)
        t3 = t1
        src = "DEFAULT"
    else:
        if not tp_ok(t2):
            t2 = (e + 50.0 * pip) if buy else (e - 50.0 * pip)
        if not (float(t3 or 0.0) > 0 and ((t3 > e) if buy else (t3 < e))):
            t3 = t1
    return {"ok": True, "why": "", "sl": s, "tp1": t1, "tp2": t2, "tp3": t3,
            "tps_src": src}
