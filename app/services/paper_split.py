"""v92: PAPER HISOB **3 GA BO'LINDI** — 📡 KANAL | 🤖 BOT O'ZI | 🧮 JAMI.

Nega: foydalanuvchi "kanaldan olgan signallari" bilan "bot o'zi topgan
signallari"ni ARALASHTIRMASLIGINI so'radi — qaysi manba pul topayotganini
alohida ko'rish kerak. Shu sababli bitta `💼 Hisob (paper)` ekrani va barcha
hisobotlar (kunlik / haftalik / oylik / sana bo'yicha / to'liq) endi UCH
bo'limda chiqadi.

Qaysi lot qaysi hisobga tegishli ekanini aniqlash (ikki yo'l, ikkalasi ham
ishlaydi — eski baza ham to'g'ri ko'rinadi):
  1) yangi lotlar: `paper_positions.bucket` ustuni ochilish paytida yoziladi;
  2) eski lotlar: `signals.quality_mode` bo'yicha — `CHANNEL` → KANAL,
     `SNIPER` va boshqa (bot dvigateli) → OZI.

Hisob matematikasi (o'ylab topilgan raqam YO'Q — hammasi bazadan):
  KANAL balansi  = foydalanuvchi hisobi balansi − (shu hisobdagi OZI lotlari puli)
  OZI   balansi  = sniper hisobi (-1, $50) + (foydalanuvchi hisobidagi OZI lotlari puli)
  JAMI  balansi  = KANAL + OZI  (= foydalanuvchi hisobi + sniper hisobi)
Shunday qilib uchala bo'lim bir-biriga qo'shiladi va hech qaysi pul
ikkilanib hisoblanmaydi.
"""
from __future__ import annotations

from app.core.logging import get_logger

logger = get_logger(__name__)

KANAL = "KANAL"
OZI = "OZI"

#: Hisob nomi (ekranda ko'rinadigan yorliq)
LABELS = {
    KANAL: "\U0001F4E1 KANALDAN OLINGAN SIGNALlar",
    OZI: "\U0001F916 BOT O\u2018ZI TOPGAN SIGNALlar",
}
SHORT = {KANAL: "\U0001F4E1 Kanal", OZI: "\U0001F916 Bot o\u2018zi"}
NUM = {KANAL: "1\uFE0F\u20E3", OZI: "2\uFE0F\u20E3"}

#: Bot o'zi ishlatadigan (kanal emas) rejimlar
_SELF_MODES = {"SNIPER", "AGGRESSIVE", "BALANCED", "CONSERVATIVE", "STRICT", "ENGINE"}


def signal_bucket(signal) -> str:
    """Signal qaysi manbadan: KANAL (kanaldan olingan) yoki OZI (bot o'zi topdi)."""
    qm = str(getattr(signal, "quality_mode", "") or "").strip().upper()
    if qm == "CHANNEL":
        return KANAL
    if qm in _SELF_MODES:
        return OZI
    src = str(getattr(signal, "source_channel", "") or "").strip().lower()
    if "bot o" in src or "sniper" in src:          # "SNR+ICT+SMC (bot o'zi)"
        return OZI
    if src:                                          # kanal nomi bor → kanal
        return KANAL
    return OZI                                       # manba yo'q → bot dvigateli


def position_bucket(pos, sig_bucket=None) -> str:
    """Lot qaysi hisobga tegishli (yangi ustun → signal manbasi → KANAL)."""
    b = str(getattr(pos, "bucket", "") or "").strip().upper()
    if b in (KANAL, OZI):
        return b
    if sig_bucket in (KANAL, OZI):
        return sig_bucket
    return KANAL


def _empty(name: str) -> dict:
    return {
        "name": name, "label": LABELS[name], "short": SHORT[name],
        "initial": 0.0, "balance": 0.0, "pnl": 0.0, "pnl_pct": 0.0,
        "trades": 0, "wins": 0, "losses": 0, "breakeven": 0, "winrate": 0.0,
        "pf": 0.0, "total_r": 0.0, "avg_r": 0.0, "open_signals": 0,
        "open_lots": 0, "lots": 0, "signals_seen": 0,
    }


def _fill(b: dict, groups: list[list], lots: list) -> None:
    """Bitim guruhlari (har guruh = 1 signal, 2 lot) → statistika."""
    from app.core.enums import PaperStatus
    OPEN = PaperStatus.OPEN.value
    pnl = 0.0
    gross_win = 0.0
    gross_loss = 0.0
    rs: list[float] = []
    for arr in groups:
        cash = sum(float(getattr(x, "realized_pnl", 0) or 0) for x in arr)
        risk = sum(float(getattr(x, "risk_amount", 0) or 0) for x in arr)
        is_open = any(str(getattr(x, "status", "")) == OPEN for x in arr)
        if is_open:
            b["open_signals"] += 1
            continue
        pnl += cash
        b["trades"] += 1
        if cash > 0.05:
            b["wins"] += 1
            gross_win += cash
        elif cash < -0.05:
            b["losses"] += 1
            gross_loss += -cash
        else:
            b["breakeven"] += 1
        if risk > 0:
            rs.append(cash / risk)
        else:
            rv = [float(x.r_multiple) for x in arr
                  if getattr(x, "r_multiple", None) is not None]
            if rv:
                rs.append(sum(rv) / len(rv))
    b["pnl"] = round(pnl, 2)
    b["pf"] = round(gross_win / gross_loss, 2) if gross_loss > 0 else (
        99.0 if gross_win > 0 else 0.0)
    b["total_r"] = round(sum(rs), 2)
    b["avg_r"] = round(sum(rs) / len(rs), 2) if rs else 0.0
    b["winrate"] = round(b["wins"] / b["trades"] * 100.0, 1) if b["trades"] else 0.0
    b["lots"] = len(lots)
    b["open_lots"] = len([x for x in lots if str(getattr(x, "status", "")) == OPEN])


async def bucket_stats(session, user_id: int) -> dict:
    """3 hisob statistikasi: `kanal`, `ozi`, `jami` (+ `sniper_on`, `acc`).

    Barcha raqamlar bazadan o'qiladi; eski lotlar (bucket ustuni yo'q) signal
    manbasi bo'yicha to'g'ri taqsimlanadi.
    """
    from sqlalchemy import select

    from app.database.models.paper import PaperAccount, PaperPosition
    from app.database.models.signal import Signal

    out = {"kanal": _empty(KANAL), "ozi": _empty(OZI), "jami": None,
           "sniper_on": False, "acc": None, "sniper_acc": None}

    acc = await session.scalar(
        select(PaperAccount).where(PaperAccount.user_id == user_id))
    rows: list = []
    if acc is not None:
        rows = list((await session.execute(
            select(PaperPosition).where(PaperPosition.user_id == user_id)
            .order_by(PaperPosition.id))).scalars().all())
    out["acc"] = acc

    # --- bot o'zi hisobi (sniper, user_id = -1) ---
    sniper_uid = -1
    try:
        from app.services.sniper import SNIPER_USER_ID as _sid
        sniper_uid = int(_sid)
    except Exception:  # noqa: BLE001
        pass
    sacc = await session.scalar(
        select(PaperAccount).where(PaperAccount.user_id == sniper_uid))
    srows: list = []
    if sacc is not None:
        srows = list((await session.execute(
            select(PaperPosition).where(PaperPosition.user_id == sniper_uid)
            .order_by(PaperPosition.id))).scalars().all())
        try:
            from app.services.sniper import is_enabled
            out["sniper_on"] = bool(await is_enabled(session))
        except Exception:  # noqa: BLE001
            out["sniper_on"] = False
    out["sniper_acc"] = sacc

    # --- signal_id → manba ---
    ids = {int(p.signal_id) for p in (rows + srows) if getattr(p, "signal_id", None)}
    bmap: dict[int, str] = {}
    if ids:
        try:
            sigs = (await session.execute(
                select(Signal).where(Signal.id.in_(ids)))).scalars().all()
            for s in sigs:
                bmap[int(s.id)] = signal_bucket(s)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[SPLIT] signal manbasi: %s", exc)

    def _bucket_of(p) -> str:
        sid = getattr(p, "signal_id", None)
        return position_bucket(p, bmap.get(int(sid)) if sid else None)

    # --- guruhlash: bitim = bitta signal (2 lot birga) ---
    def _groups(items: list) -> dict:
        g: dict = {}
        for x in items:
            key = getattr(x, "signal_id", None)
            if key is None:
                key = ("pos", getattr(x, "id", 0))
            g.setdefault(key, []).append(x)
        return g

    k_groups, k_lots = [], []
    o_groups, o_lots = [], []
    ozi_in_main = 0.0
    for p in rows:
        if _bucket_of(p) == KANAL:
            k_lots.append(p)
        else:
            o_lots.append(p)
            ozi_in_main += float(getattr(p, "realized_pnl", 0) or 0)
    for key, arr in _groups(k_lots).items():
        k_groups.append(arr)
    for key, arr in _groups(o_lots).items():
        o_groups.append(arr)
    for key, arr in _groups(srows).items():     # sniper lotlari — hammasi OZI
        o_groups.append(arr)

    kb, ob = out["kanal"], out["ozi"]
    _fill(kb, k_groups, k_lots)
    _fill(ob, o_groups, o_lots + list(srows))

    main_initial = float(getattr(acc, "initial_balance", 0) or 0) if acc else 0.0
    main_balance = float(getattr(acc, "balance", 0) or 0) if acc else 0.0
    snip_initial = float(getattr(sacc, "initial_balance", 0) or 0) if sacc else 0.0
    snip_balance = float(getattr(sacc, "balance", 0) or 0) if sacc else 0.0

    kb["initial"] = round(main_initial, 2)
    kb["balance"] = round(main_balance - ozi_in_main, 2)
    kb["pnl"] = round(kb["balance"] - kb["initial"], 2)
    ob["initial"] = round(snip_initial, 2)
    ob["balance"] = round(snip_balance + ozi_in_main, 2)
    ob["pnl"] = round(ob["balance"] - ob["initial"], 2)

    for b in (kb, ob):
        b["pnl_pct"] = round(b["pnl"] / b["initial"] * 100.0, 2) if b["initial"] else 0.0

    jb = {
        "name": "JAMI", "label": "\U0001F9EE JAMI (ikkisi birga)",
        "short": "\U0001F9EE Jami",
        "initial": round(kb["initial"] + ob["initial"], 2),
        "balance": round(kb["balance"] + ob["balance"], 2),
        "pnl": round(kb["pnl"] + ob["pnl"], 2),
        "trades": kb["trades"] + ob["trades"],
        "wins": kb["wins"] + ob["wins"],
        "losses": kb["losses"] + ob["losses"],
        "breakeven": kb["breakeven"] + ob["breakeven"],
        "open_signals": kb["open_signals"] + ob["open_signals"],
        "open_lots": kb["open_lots"] + ob["open_lots"],
        "lots": kb["lots"] + ob["lots"],
        "total_r": round(kb["total_r"] + ob["total_r"], 2),
    }
    jb["pnl_pct"] = round(jb["pnl"] / jb["initial"] * 100.0, 2) if jb["initial"] else 0.0
    jb["winrate"] = round(jb["wins"] / jb["trades"] * 100.0, 1) if jb["trades"] else 0.0
    _gw = kb["pf"] if kb["pf"] else 0.0
    jb["pf"] = round((kb["pf"] + ob["pf"]) / 2.0, 2) if (kb["pf"] and ob["pf"]) else _gw
    jb["avg_r"] = round(jb["total_r"] / jb["trades"], 2) if jb["trades"] else 0.0
    out["jami"] = jb
    return out


async def source_counts(session, start_utc=None, end_utc=None) -> dict:
    """Davr ichida chiqarilgan signallar manba bo'yicha: {kanal, ozi, jami}."""
    from sqlalchemy import select

    from app.database.models.signal import Signal

    stmt = select(Signal)
    if start_utc is not None:
        stmt = stmt.where(Signal.created_at >= start_utc)
    if end_utc is not None:
        stmt = stmt.where(Signal.created_at <= end_utc)
    try:
        rows = list((await session.execute(stmt.limit(3000))).scalars().all())
    except Exception as exc:  # noqa: BLE001
        logger.debug("[SPLIT] signal soni: %s", exc)
        return {"kanal": 0, "ozi": 0, "jami": 0}
    k = sum(1 for s in rows if signal_bucket(s) == KANAL)
    return {"kanal": k, "ozi": len(rows) - k, "jami": len(rows)}


# ==================================================================
# MATN (ekran va hisobotlar uchun)
# ==================================================================
def _ico(v: float) -> str:
    return "\U0001F7E2" if v >= 0 else "\U0001F534"


def block_lines(b: dict, *, num: str = "", note: str = "") -> list[str]:
    """Bitta hisob bo'limi (to'liq ko'rinish — `💼 Hisob (paper)` uchun)."""
    head = f"{num} <b>{b['label']}</b>" if num else f"<b>{b['label']}</b>"
    pf = f" | \u2696\uFE0F PF {b['pf']:.2f}" if b.get("pf") else ""
    r = f" | \U0001F4E6 {b['total_r']:+.1f}R" if b.get("trades") else ""
    out = [
        head,
        f"   \U0001F4B5 Balans: <b>${b['balance']:,.2f}</b> "
        f"(boshlang\u2018ich ${b['initial']:,.2f})",
        f"   {_ico(b['pnl'])} Foyda: <b>{b['pnl']:+,.2f}$ ({b['pnl_pct']:+.1f}%)</b>",
        f"   \U0001F4CA Bitimlar: <b>{b['trades']}</b> "
        f"(\U0001F3C6{b['wins']} / \U0001F4A5{b['losses']}"
        + (f" / \u2696\uFE0F{b['breakeven']}" if b.get("breakeven") else "")
        + f") | G\u2018alaba: <b>{b['winrate']:.0f}%</b>{pf}{r}",
        f"   \U0001F4C2 Ochiq: <b>{b['open_signals']}</b> bitim "
        f"({b['open_lots']} lot)",
    ]
    if note:
        out.append(f"   \u2139\uFE0F {note}")
    return out


def hisob_lines(bk: dict) -> list[str]:
    """`💼 Hisob (paper)` — 3 bo'lim: KANAL / BOT O'ZI / JAMI."""
    sniper_note = ("alohida $%.0f hisob (SNR+ICT+SMC, 5m skaner) — %s"
                   % (bk["ozi"]["initial"],
                      "YONIQ \U0001F7E2" if bk.get("sniper_on") else "O\u2018CHIQ \U0001F534"))
    lines = ["\U0001F4BC <b>SIZNING VIRTUAL HISOBLARINGIZ (3 ta)</b>",
             "\u2501" * 16]
    lines += block_lines(bk["kanal"], num="1\uFE0F\u20E3",
                         note="kanal postlaridan olingan signallar")
    lines.append("")
    lines += block_lines(bk["ozi"], num="2\uFE0F\u20E3", note=sniper_note)
    lines.append("")
    lines += block_lines(bk["jami"], num="3\uFE0F\u20E3",
                         note="ikkala hisob birga (haqiqiy umumiy balans)")
    lines.append("\u2501" * 16)
    return lines


def report_lines(bk: dict, *, title: str = "\U0001F4B5 PAPER HISOB (3 ga bo\u2018lingan)") -> list[str]:
    """Hisobotlar uchun ixcham 3 qator (kunlik / haftalik / oylik / to'liq)."""
    def one(b: dict) -> str:
        pf = f" | PF {b['pf']:.2f}" if b.get("pf") else ""
        op = f" | ochiq {b['open_signals']}" if b.get("open_signals") else ""
        return (f"   {b['short']}: <b>${b['balance']:,.2f}</b> "
                f"{_ico(b['pnl'])} {b['pnl']:+,.2f}$ ({b['pnl_pct']:+.1f}%) | "
                f"{b['trades']} bitim | WR {b['winrate']:.0f}%"
                f" (\U0001F3C6{b['wins']}/\U0001F4A5{b['losses']}){pf}{op}")
    return [
        f"<b>{title}</b>",
        one(bk["kanal"]),
        one(bk["ozi"]),
        one(bk["jami"]),
    ]


def result_lines(bk: dict, bucket_of_signal: str | None = None) -> list[str]:
    """Signal natijasi kartasining pastidagi hisob qatori (3 hisob)."""
    tag = ""
    if bucket_of_signal in (KANAL, OZI):
        tag = f" \u2192 <b>{SHORT[bucket_of_signal]}</b> hisobiga yozildi"
    lines = [f"\U0001F3E6 <b>Virtual hisoblar (3 ta)</b>{tag}"]
    for key in ("kanal", "ozi", "jami"):
        b = bk[key]
        lines.append(f"   {b['short']}: <b>${b['balance']:,.2f}</b> "
                     f"{_ico(b['pnl'])} {b['pnl']:+,.2f}$ | {b['trades']} bitim "
                     f"| WR {b['winrate']:.0f}%")
    return lines
