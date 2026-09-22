"""Risk boshqaruvi — ATR asosida SL, R/R asosida TP."""
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.core.enums import Direction


@dataclass
class RiskLevels:
    entry: float
    entry_low: float
    entry_high: float
    sl: float
    tp1: float
    tp2: float
    tp3: float
    risk_distance: float


def calculate_levels(direction: Direction, entry: float, atr_value: float,
                     settings: Settings, atr_mult: float | None = None) -> RiskLevels:
    """
    BUY:  SL = entry - ATR * mult
    SELL: SL = entry + ATR * mult
    TP1/2/3 = 1R / 2R / 3R

    atr_mult berilsa — settings.atr_sl_multiplier o'rniga ishlatiladi
    (shovqinli asbob uchun kengroq stop, masalan JPY 5m).
    """
    sl_mult = atr_mult if atr_mult is not None else settings.atr_sl_multiplier
    risk_dist = atr_value * sl_mult
    zone = atr_value * 0.15  # entry zonasi ±0.15 ATR

    if direction == Direction.BUY:
        sl = entry - risk_dist
        return RiskLevels(
            entry=entry,
            entry_low=entry - zone,
            entry_high=entry + zone,
            sl=sl,
            tp1=entry + risk_dist * settings.tp1_r,
            tp2=entry + risk_dist * settings.tp2_r,
            tp3=entry + risk_dist * settings.tp3_r,
            risk_distance=risk_dist,
        )
    sl = entry + risk_dist
    return RiskLevels(
        entry=entry,
        entry_low=entry - zone,
        entry_high=entry + zone,
        sl=sl,
        tp1=entry - risk_dist * settings.tp1_r,
        tp2=entry - risk_dist * settings.tp2_r,
        tp3=entry - risk_dist * settings.tp3_r,
        risk_distance=risk_dist,
    )


def position_size(balance: float, risk_percent: float, risk_distance: float,
                  entry: float) -> tuple[float, float]:
    """Virtual pozitsiya hajmi: risk_amount / stop_distance.

    v68: ishlatilmaydi (hajm FAYS bo'yicha olinadi) — moslik uchun qoldirildi.
    """
    risk_amount = balance * risk_percent / 100.0
    if risk_distance <= 0:
        return 0.0, risk_amount
    qty = risk_amount / risk_distance
    return qty, risk_amount


# ==================== v68: HAJM (lot) va PUL hisobi ====================
CONTRACT_OZ = 100.0          # 1 lot XAUUSD = 100 untsiya
LOT_MIN = 0.01               # minimal hajm


def lot_qty(lot: float, contract: float = CONTRACT_OZ) -> float:
    """v68: hajm (lot) -> untsiya. 1.00 lot = 100 oz."""
    try:
        return max(0.0, float(lot or 0.0) * float(contract or CONTRACT_OZ))
    except (TypeError, ValueError):
        return 0.0


def money_for_move(direction, entry: float, price: float, qty: float) -> float:
    """v68: terminaldagi pul hisobi — (narx farqi) x hajm(oz).

    XAUUSD: 1.00 lot = 100 oz -> narx 1$ yursa 100$ bo'ladi.
    Terminaldagi misol: 4348.683 dan 4351.080 gacha 1.00 lot SELL = -239.70$.
    """
    try:
        e = float(entry or 0.0)
        p = float(price or 0.0)
        q = float(qty or 0.0)
    except (TypeError, ValueError):
        return 0.0
    d = str(getattr(direction, "value", direction) or "BUY").upper()
    return (p - e) * q if d == "BUY" else (e - p) * q


def money_at_r(risk_distance: float, qty: float, r: float) -> float:
    """v79: +rR darajaga yetsa olinadigan pul — ZARAR bilan bir xil formulada.

    risk = hajm(oz) x stop masofasi;  foyda(+rR) = risk x r.
    Masalan 50 oz, stop 2.397$ -> risk 119.85$; +3R da foyda 359.55$.
    """
    try:
        d = abs(float(risk_distance or 0.0))
        q = float(qty or 0.0)
        rr = float(r or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return q * d * rr


def target_money(direction, entry: float, target: float, qty: float) -> float:
    """v79: maqsadga yetsa olinadigan pul (narx farqi x hajm) — aniq hisob.

    Xuddi shu `money_for_move` ishlatiladi: SELL 4348.68 -> 4345.00, 50 oz
    = +184.15$ (soxta raqam emas, terminaldagi formula).
    """
    return money_for_move(direction, entry, target, qty)


def lot_position_size(risk_distance: float, lot: float = 1.0,
                      contract: float = CONTRACT_OZ) -> tuple[float, float]:
    """v68: hajm bo'yicha pozitsiya — (qty_oz, shu hajmdagi pul riski).

    risk_amount = hajm(oz) x stop masofasi — ya'ni SL urilsa yo'qoladigan pul.
    """
    qty = lot_qty(lot, contract)
    try:
        d = max(0.0, float(risk_distance or 0.0))
    except (TypeError, ValueError):
        d = 0.0
    return qty, qty * d


def r_multiple_for_price(direction: Direction, entry: float, sl: float,
                         price: float) -> float:
    """Narx bo'yicha R multiple (manfiy bo'lishi mumkin)."""
    risk = abs(entry - sl)
    if risk == 0:
        return 0.0
    if direction == Direction.BUY:
        return (price - entry) / risk
    return (entry - price) / risk


def format_price(p: float | None) -> str:
    if p is None:
        return "—"
    if p >= 1000:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:,.4f}"
    return f"{p:.6f}"


@dataclass
class RMap:
    """1R / 2R / 3R qaysi narxga to'g'ri kelishi."""
    risk: float
    risk_pct: float
    sl: float
    entry: float
    tp1: float
    tp2: float
    tp3: float
    sl_pct: float
    tp1_pct: float
    tp2_pct: float
    tp3_pct: float


def build_r_map(entry: float, sl: float, tp1: float, tp2: float, tp3: float) -> RMap:
    def pct(price: float) -> float:
        if not entry:
            return 0.0
        return (price - entry) / entry * 100.0

    risk = abs(entry - sl)
    return RMap(
        risk=risk,
        risk_pct=abs(pct(sl)),
        sl=sl, entry=entry, tp1=tp1, tp2=tp2, tp3=tp3,
        sl_pct=pct(sl), tp1_pct=pct(tp1), tp2_pct=pct(tp2), tp3_pct=pct(tp3),
    )


def lot_target_r(stage: int | str | None) -> float:
    """v82: lot maqsadi R da — Lot2 = +5R (yakuniy), Lot1 = +3R."""
    try:
        return 5.0 if int(stage or 0) >= 10 else 3.0
    except Exception:  # noqa: BLE001
        return 3.0


def lot_target_price(pos) -> float:
    """v82: shu LOT uchun maqsad NARXI (R asosida, tp maydonlaridan qat'i nazar)."""
    d = str(getattr(pos, "direction", "") or "").upper()
    entry = float(getattr(pos, "entry", 0) or 0)
    sl = float(getattr(pos, "sl", 0) or 0)
    if d not in ("BUY", "SELL") or entry <= 0 or sl <= 0:
        return 0.0
    return r_price(d, entry, sl, int(lot_target_r(getattr(pos, "stage", 0))))


def r_price(direction: Direction | str, entry: float, sl: float, n: int) -> float:
    """Kirish/SL dan nR narx (yangi ustun yo'q — hisoblanadi)."""
    risk = abs(entry - sl)
    if risk <= 0:
        return entry
    is_buy = direction in (Direction.BUY, "BUY")
    return entry + n * risk if is_buy else entry - n * risk


def format_r_map(entry: float, sl: float, tp1: float, tp2: float, tp3: float) -> str:
    """2 lot: Lot1 +3R, Lot2 +4R/+5R.

    v65: TP1/2/3 kanal postidan olingan bo'lsa (R ga to'g'ri kelmasa) — yorliqda
    HAQIQIY R ko'rsatiladi («+6.4R TP1 (kanal)»), aks holda «+1R HIMOYA» qoladi.
    """
    m = build_r_map(entry, sl, tp1, tp2, tp3)
    buy = entry > sl
    d = Direction.BUY if buy else Direction.SELL
    tp4 = r_price(d, entry, sl, 4)
    tp5 = r_price(d, entry, sl, 5)

    def pct(price: float) -> float:
        if not entry:
            return 0.0
        return (price - entry) / entry * 100.0

    def row(icon: str, tag: str, label: str, price: float, p: float) -> str:
        sign = "+" if p >= 0 else ""
        return (
            f"{icon} <b>{tag}</b> {label}: <b>{format_price(price)}</b>"
            f"  ({sign}{p:.2f}%)"
        )

    def std(n: int, name: str, price: float) -> tuple[str, str]:
        rv = r_multiple_for_price(d, entry, sl, price)
        if abs(rv - n) <= 0.2:
            return (f"+{n}R", name)
        return (f"+{rv:.1f}R", f"TP{n} (kanal)")

    t1_tag, t1_lbl = std(1, "HIMOYA", m.tp1)
    t2_tag, t2_lbl = std(2, "FOYDA", m.tp2)
    t3_tag, t3_lbl = std(3, "LOT 1 yopiladi", m.tp3)

    return "\n".join([
        "📐 <b>R XARITASI</b> — 2 lot (riskka qarab):",
        f"   1R masofa: <b>{format_price(m.risk)}</b>  (±{m.risk_pct:.2f}%)",
        row("🛑", "−1R", "STOP (2 lot)", m.sl, m.sl_pct),
        row("📍", " 0R", "KIRISH", m.entry, 0.0),
        row("✅", t1_tag, t1_lbl, m.tp1, m.tp1_pct),
        row("🎯", t2_tag, t2_lbl, m.tp2, m.tp2_pct),
        row("🏁", t3_tag, t3_lbl, m.tp3, m.tp3_pct),
        row("🚀", "+4R", "LOT 2", tp4, pct(tp4)),
        row("💎", "+5R", "LOT 2 (momentum)", tp5, pct(tp5)),
    ])
