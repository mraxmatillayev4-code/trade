"""v84: KIRISH NUQTASI dvigateli (entry engine).

Foydalanuvchi talabi (so'zma-so'z mazmuni):
    «Kirish nuqtasini aniqlaydigan bozor holatiga qarab: agar signalda kirish
     nuqtasi aytilgan bo'lsa hisoblamaydi (o'sha ishlatiladi), aytilmagan bo'lsa
     bot o'zi hisoblaydi. Bu minusni yo'qotishga va minimum shotda ham foyda
     qilishga yordam beradi. Stop loss OLIB TASHLANMAYDI.»

QOIDALAR (o'zgarmas):
 1) Signal kirish zonasini aytgan bo'lsa — AYNAN o'sha zona ishlatiladi
    (bot o'zgartirmaydi), lekin narx o'sha zonaga kelmaguncha savdo OCHILMAYDI.
 2) Kirish aytilmagan bo'lsa — bot bozor holatidan (ATR, swing, EMA, diapazon
    o'rtasi) kirish zonasini HISOBLAYDI. Narx zonaga kelganda kiradi.
 3) Narx orqasidan QUVISH YO'Q: narx zonadan o'tib ketgan bo'lsa savdo
    ochilmaydi — kutish muddati tugasa signal BEKOR qilinadi (0$ zarar).
 4) SL hech qachon olib tashlanmaydi: signal SL bersa o'sha qoladi, bermasa
    bot tuzilma (swing) bo'yicha SL hisoblaydi.
 5) Har bir hisob uchun risk % dan oshadigan bo'lsa (0.01 lot bilan ham)
    savdo ochilmaydi — «balans yetmaydi» sababi bilan.

Modul toza funksiyalardan iborat: DataFrame va sonlar kiradi, reja chiqadi —
shu sababli testlarda haqiqiy bazasiz tekshiriladi.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------- sozlamalar
WAIT_CHOICES = (15, 30, 60, 120)          # kutish muddati (daqiqa)
DEFAULT_WAIT = 30
COOLDOWN_CHOICES = (0, 15, 30, 60)        # qarama-qarshi tomonga o'tish tanaffusi
DEFAULT_COOLDOWN = 15

PULL_MIN_ATR = 0.35        # hisoblangan kirish narxdan kamida shu qadar orqada
PULL_MAX_ATR = 2.50        # ko'pi bilan shu qadar uzoq (kutish real bo'lsin)
ZONE_ATR = 0.20            # zona yarim kengligi (ATR ulushi)
MIN_SL_ROOM_ATR = 0.50     # kirishdan SL gacha kamida shu masofa (shovqin emasin)
MIN_ROOM_ABS = 0.20        # mutlaq minimal masofa ($, oltin)
MIN_ZONE_HALF = 0.02       # zona juda tor bo'lmasin ($)
ATR_FALLBACK_PCT = 0.0015  # sham bo'lmasa: narxning 0.15% i

CANCEL_TEXT = "KIRISH YO'Q"


def _f(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _up(s) -> str:
    return str(s or "").strip().upper()


# ------------------------------------------------------------------ yordamchi
def atr(df, n: int = 14) -> float:
    """O'rtacha haqiqiy diapazon (shamlar bo'yicha)."""
    try:
        if df is None or len(df) < 3:
            return 0.0
        tail = df.tail(max(3, n + 1))
        highs = [float(x) for x in tail["high"].tolist()]
        lows = [float(x) for x in tail["low"].tolist()]
        closes = [float(x) for x in tail["close"].tolist()]
        vals: list[float] = []
        for i in range(1, len(highs)):
            tr = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i - 1]),
                     abs(lows[i] - closes[i - 1]))
            vals.append(tr)
        if not vals:
            return 0.0
        return sum(vals[-n:]) / float(len(vals[-n:]))
    except Exception:  # noqa: BLE001
        return 0.0


def swing_low(df, n: int = 20) -> float:
    try:
        if df is None or len(df) < 2:
            return 0.0
        return float(df["low"].tail(n).min())
    except Exception:  # noqa: BLE001
        return 0.0


def swing_high(df, n: int = 20) -> float:
    try:
        if df is None or len(df) < 2:
            return 0.0
        return float(df["high"].tail(n).max())
    except Exception:  # noqa: BLE001
        return 0.0


def range_mid(df, n: int = 40) -> float:
    try:
        if df is None or len(df) < 2:
            return 0.0
        tail = df.tail(n)
        hi = float(tail["high"].max())
        lo = float(tail["low"].min())
        if hi <= lo:
            return 0.0
        return (hi + lo) / 2.0
    except Exception:  # noqa: BLE001
        return 0.0


def ema(values, n: int = 20) -> float:
    try:
        vals = [float(v) for v in list(values)]
        if not vals:
            return 0.0
        k = 2.0 / (n + 1.0)
        e = vals[0]
        for v in vals[1:]:
            e = v * k + e * (1.0 - k)
        return float(e)
    except Exception:  # noqa: BLE001
        return 0.0


def _ema_from_df(df, n: int = 20) -> float:
    try:
        return ema(df["close"].tail(max(n * 3, 40)).tolist(), n)
    except Exception:  # noqa: BLE001
        return 0.0


def _atr_of(df, ref: float) -> float:
    a = atr(df, 14)
    if a > 0:
        return a
    if ref > 0:
        return max(ref * ATR_FALLBACK_PCT, 0.05)
    return 0.0


# ---------------------------------------------------------------------- reja
@dataclass
class Plan:
    """Kirish rejasi."""
    ok: bool = False
    mode: str = ""            # SIGNAL (kanal aytgan) | COMPUTED (bot hisobladi)
    low: float = 0.0
    high: float = 0.0
    level: float = 0.0
    note: str = ""            # manba izohi (kartada ko'rinadi)
    why: str = ""             # ok=False bo'lsa sabab
    fill_now: bool = False    # narx hozir zonada — darhol kiradi
    ref: float = 0.0
    atr_value: float = 0.0
    candidates: list = field(default_factory=list)

    @property
    def zone_text(self) -> str:
        return f"{self.level:,.2f}"


def _mk(mode: str, low: float, high: float, note: str, ref: float,
        a: float, direction: str, given: bool = True) -> Plan:
    lo, hi = (low, high) if low <= high else (high, low)
    lvl = (lo + hi) / 2.0
    p = Plan(ok=True, mode=mode, low=lo, high=hi, level=lvl, note=note,
             ref=ref, atr_value=round(a, 4))
    ok, fill = zone_hit(direction, lo, hi, ref)
    p.fill_now = bool(ok)
    p._fill = fill  # type: ignore[attr-defined]
    return p


def zone_hit(direction: str, low: float, high: float, price: float) -> tuple[bool, float]:
    """Narx zonaga kirdimi? (ok, bajarilish narxi).

    BUY: narx zonaning YUQORI chegarasidan pastga tushsa — kiradi (arzon narx).
    SELL: narx zonaning PASTKI chegarasidan yuqoriga chiqsa — kiradi.
    Ya'ni narx yomonroq (orqada qolgan) bo'lsa hech qachon kirilmaydi.
    """
    d = _up(direction)
    px = _f(price)
    lo, hi = _f(low), _f(high)
    if px <= 0 or lo <= 0 or hi <= 0:
        return False, 0.0
    if lo > hi:
        lo, hi = hi, lo
    if d == "BUY":
        if px <= hi:
            return True, px
        return False, 0.0
    if d == "SELL":
        if px >= lo:
            return True, px
        return False, 0.0
    return False, 0.0


def _candidates(direction: str, ref: float, a: float,
                df5, df15) -> list[tuple[float, str]]:
    """Bozor holatidan kirish nuqtalari (narx, nom)."""
    out: list[tuple[float, str]] = []
    d = _up(direction)
    if d == "BUY":
        s8 = swing_low(df5, 8)
        if s8 > 0:
            out.append((s8 + 0.15 * a, "5m yaqin past (8 sham)"))
        s20 = swing_low(df5, 20)
        if s20 > 0:
            out.append((s20 + 0.20 * a, "5m tayanch (20 sham)"))
        e5 = _ema_from_df(df5, 20)
        if e5 > 0:
            out.append((e5, "5m EMA20"))
        e15 = _ema_from_df(df15, 20)
        if e15 > 0:
            out.append((e15, "15m EMA20"))
        m = range_mid(df5, 40)
        if m > 0:
            out.append((m, "diapazon o'rtasi (40 sham)"))
    elif d == "SELL":
        r8 = swing_high(df5, 8)
        if r8 > 0:
            out.append((r8 - 0.15 * a, "5m yaqin cho'qqi (8 sham)"))
        r20 = swing_high(df5, 20)
        if r20 > 0:
            out.append((r20 - 0.20 * a, "5m qarshilik (20 sham)"))
        e5 = _ema_from_df(df5, 20)
        if e5 > 0:
            out.append((e5, "5m EMA20"))
        e15 = _ema_from_df(df15, 20)
        if e15 > 0:
            out.append((e15, "15m EMA20"))
        m = range_mid(df5, 40)
        if m > 0:
            out.append((m, "diapazon o'rtasi (40 sham)"))
    # takrorlarni olib tashlaymiz (narx bo'yicha)
    seen: list[tuple[float, str]] = []
    for px, nm in out:
        if all(abs(px - q) > 1e-6 for q, _ in seen):
            seen.append((px, nm))
    return seen


def build_plan(direction: str, ref: float, sl: float | None = None,
               given_low: float | None = None, given_high: float | None = None,
               df5=None, df15=None) -> Plan:
    """Asosiy funksiya: kirish rejasi.

    given_low/given_high — signalda YOZILGAN kirish zonasi (bo'lsa ishlatiladi).
    """
    d = _up(direction)
    r = _f(ref)
    s = _f(sl)
    a = _atr_of(df5, r)
    if r <= 0:
        return Plan(ok=False, why="narx ma'lum emas — kirish hisoblanmadi")
    if d not in ("BUY", "SELL"):
        return Plan(ok=False, why="yo'nalish yo'q — kirish hisoblanmadi")

    gl, gh = _f(given_low), _f(given_high)
    if gl > 0 and gh > 0:
        # --- 1) SIGNAL aytgan zona: hisoblanmaydi, AYNAN o'sha ishlatiladi ---
        lo, hi = (gl, gh) if gl <= gh else (gh, gl)
        if s > 0:
            if d == "BUY" and s >= lo:
                return Plan(ok=False, why=("kanal rejasi mos emas: SL kirish "
                                           "zonasidan past emas"))
            if d == "SELL" and s <= hi:
                return Plan(ok=False, why=("kanal rejasi mos emas: SL kirish "
                                           "zonasidan yuqori emas"))
        p = _mk("SIGNAL", lo, hi, "kanal aytgan zona", r, a, d)
        return p

    if gl > 0 or gh > 0:
        # bitta narx aytilgan — kichik zona qilib olamiz (hisoblanmaydi)
        p0 = gl if gl > 0 else gh
        half = max(0.10 * a, MIN_ZONE_HALF)
        if s > 0:
            if d == "BUY" and s >= (p0 - half):
                return Plan(ok=False, why="kanal rejasi mos emas: SL kirishdan past emas")
            if d == "SELL" and s <= (p0 + half):
                return Plan(ok=False, why="kanal rejasi mos emas: SL kirishdan yuqori emas")
        return _mk("SIGNAL", p0 - half, p0 + half, "kanal aytgan narx", r, a, d)

    # --- 2) Kirish aytilmagan: bozor holatidan HISOBLAYMIZ ---
    cands = _candidates(d, r, a, df5, df15)
    back_min = max(PULL_MIN_ATR * a, MIN_ROOM_ABS)
    back_max = max(PULL_MAX_ATR * a, back_min * 2.0)
    room = max(MIN_SL_ROOM_ATR * a, MIN_ROOM_ABS)
    ok_c: list[tuple[float, str]] = []
    for px, nm in cands:
        dist = (r - px) if d == "BUY" else (px - r)
        if dist < back_min or dist > back_max:
            continue                      # juda yaqin yoki juda uzoq
        if s > 0:
            room_now = (px - s) if d == "BUY" else (s - px)
            if room_now < room:
                continue                  # SL juda yaqin — shovqin yeb qo'yadi
        ok_c.append((px, nm))
    if ok_c:
        # narxga ENG YAQIN mos daraja (tez to'ladi, quvish yo'q)
        ok_c.sort(key=lambda t: (abs(t[0] - r), t[0]), reverse=(d == "SELL"))
        p = _plan_zone(d, ok_c[0][0], r, s, a, f"bot hisobladi: {ok_c[0][1]}")
        p.candidates = [[round(q, 2), nm] for q, nm in cands[:5]]
        return p

    # --- 3) ZAXIRA: tuzilma topilmadi — kichik orqaga qaytishni kutamiz ---
    # (bozordan quvib kirmaymiz; narx kelmasa signal bekor — 0$ zarar)
    if s > 0:
        if d == "BUY" and s >= r - MIN_ROOM_ABS:
            return Plan(ok=False, why=("kanal rejasi mos emas: BUY uchun SL "
                                       "narxdan pastda emas"))
        if d == "SELL" and s <= r + MIN_ROOM_ABS:
            return Plan(ok=False, why=("kanal rejasi mos emas: SELL uchun SL "
                                       "narxdan yuqorida emas"))
    _why = "mos tuzilma topilmadi" if cands else "shamlar yo'q"
    lvl = (r - back_min) if d == "BUY" else (r + back_min)
    if s > 0:
        lvl = (max(lvl, s + room) if d == "BUY" else min(lvl, s - room))
    return _plan_zone(d, lvl, r, s, a,
                      f"bot hisobladi: kichik orqaga qaytish ({_why})")


def _plan_zone(direction: str, level: float, ref: float, sl: float, a: float,
               note: str) -> Plan:
    """Daraja atrofida zona yasaydi; SL bilan to'qnashmasligini ta'minlaydi."""
    d = _up(direction)
    half = max(ZONE_ATR * a, MIN_ZONE_HALF)
    lo, hi = level - half, level + half
    if sl > 0:
        _pad = max(0.05 * a, 0.02)
        if d == "BUY":
            lo = max(lo, sl + _pad)
        elif d == "SELL":
            hi = min(hi, sl - _pad)
    if lo >= hi:
        lo, hi = level - MIN_ZONE_HALF, level + MIN_ZONE_HALF
    return _mk("COMPUTED", lo, hi, note, ref, a, d)


# ----------------------------------------------------------------- risk/hajm
def min_lot_risk(entry: float, sl: float, contract: float = 100.0,
                 min_lot: float = 0.01) -> float:
    """0.01 lot (eng kichik hajm) bilan SL urilsa yo'qoladigan pul ($)."""
    d = abs(_f(entry) - _f(sl))
    return round(d * max(1.0, _f(contract, 100.0)) * _f(min_lot, 0.01), 2)


def balance_gate(balance: float, risk_percent: float, entry: float, sl: float,
                 contract: float = 100.0, min_lot: float = 0.01) -> dict:
    """(ok, kerak, budjet, matn) — 0.01 lot bilan ham risk sig'adimi?"""
    b = max(0.0, _f(balance))
    p = _f(risk_percent, 0.5) or 0.5
    budget = round(b * p / 100.0, 2)
    need = min_lot_risk(entry, sl, contract, min_lot)
    ok = bool(need > 0 and need <= budget + 1e-9)
    txt = ""
    if need > 0 and not ok:
        need_bal = (need / (p / 100.0)) if p > 0 else need
        _pct_need = (need / b * 100.0) if b > 0 else 0.0
        txt = (f"0.01 lot bilan risk {need:,.2f}$ > {budget:,.2f}$ "
               f"({p:.2f}% x {b:,.2f}$) — balans yetmaydi")
        if b > 0:
            txt += (f". Sig'ishi uchun: balans {need_bal:,.2f}$ yoki risk "
                    f"{_pct_need:.2f}% kerak")
    return {"ok": ok, "need": need, "budget": budget, "text": txt,
            "risk_percent": p, "balance": b}


def min_balance_for(entry: float, sl: float, risk_percent: float = 0.5,
                    contract: float = 100.0, min_lot: float = 0.01) -> float:
    """0.01 lot bilan shu signalga qancha balans kerak ($)."""
    p = _f(risk_percent, 0.5) or 0.5
    return round(min_lot_risk(entry, sl, contract, min_lot) / (p / 100.0), 2)


def r_map(direction: str, entry: float, sl: float) -> dict:
    """+3R / +4R / +5R narxlari (v80/v82 qoidalari)."""
    from app.engine.risk import r_price
    d = _up(direction) or "BUY"
    e, s = _f(entry), _f(sl)
    return {n: float(r_price(d, e, s, n)) for n in (1, 2, 3, 4, 5)}


# ------------------------------------------------------------------- vaqtlar
def deadline(minutes: int, now: datetime | None = None) -> datetime:
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return base + timedelta(minutes=max(1, int(minutes or DEFAULT_WAIT)))


def expired(expires_at, now: datetime | None = None) -> bool:
    if expires_at is None:
        return False
    cur = now or datetime.now(timezone.utc)
    try:
        exp = expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if cur.tzinfo is None:
            cur = cur.replace(tzinfo=timezone.utc)
        return cur >= exp
    except Exception:  # noqa: BLE001
        return False


def minutes_left(expires_at, now: datetime | None = None) -> int:
    if expires_at is None:
        return 0
    cur = now or datetime.now(timezone.utc)
    try:
        exp = expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if cur.tzinfo is None:
            cur = cur.replace(tzinfo=timezone.utc)
        return max(0, int((exp - cur).total_seconds() // 60))
    except Exception:  # noqa: BLE001
        return 0


# ------------------------------------------------------------- signal holati
def state_of(signal) -> str:
    """'WAIT' | 'FILLED' | 'CANCELLED' | 'NONE' — signalning kirish holati."""
    st = _up(getattr(signal, "entry_status", "") or "")
    if st in ("WAIT", "FILLED", "CANCELLED"):
        return st
    return "NONE"


def is_waiting(signal) -> bool:
    return state_of(signal) == "WAIT"


def fill_price(direction: str, low: float, high: float, price: float) -> float:
    """Zonaga kirganda qaysi narxda bajariladi (real broker kabi: bozor narxi)."""
    ok, px = zone_hit(direction, low, high, price)
    return round(px, 2) if ok else 0.0


def plan_lines(signal) -> list[str]:
    """Karta uchun kirish rejasi qatorlari (qisqa, tushunarli)."""
    mode = _up(getattr(signal, "entry_mode", "") or "")
    st = state_of(signal)
    note = str(getattr(signal, "entry_note", "") or "")
    lo = _f(getattr(signal, "entry_low", 0.0))
    hi = _f(getattr(signal, "entry_high", 0.0))
    if not mode:
        return []
    if mode == "SIGNAL":
        src = "kanal aytgan"
    elif mode == "MARKET":
        src = "bozor narxi"
    else:
        src = "bot hisobladi"
    head = ""
    if st == "WAIT":
        head = "\u23F3 <b>KIRISH KUTILMOQDA</b>"
    elif st == "FILLED":
        head = "\u2705 <b>KIRISH BAJARILDI</b>"
    elif st == "CANCELLED":
        head = "\u274C <b>KIRISH BO'LMADI</b>"
    lines = [head, f"   Zona: <b>{lo:,.2f} \u2013 {hi:,.2f}</b> ({src})"]
    if note:
        lines.append(f"   \U0001F9E0 {note}")
    if st == "WAIT":
        ml = minutes_left(getattr(signal, "entry_expires_at", None))
        if ml:
            lines.append(f"   \u23F0 Kutish: {ml} daqiqa qoldi")
        lines.append("   <i>Narx zonaga kelmasa \u2014 savdo OCHILMAYDI "
                     "(quvish yo'q).</i>")
    return lines
