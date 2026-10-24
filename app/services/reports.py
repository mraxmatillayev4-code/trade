"""Kunlik / haftalik / oylik hamda TANLANGAN sana bo'yicha signal hisobotlari.

MUHIM: davrlar taqvim (kalendar) bo'yicha hisoblanadi — foydalanuvchi
mahalliy vaqti (O'zbekiston, UTC+5) bilan:
  • kunlik  = bugun 00:00 dan hozirgacha (rolling 24 soat EMAS);
  • haftalik = shu hafta dushanba 00:00 dan;
  • oylik   = shu oy 1-kuni 00:00 dan;
  • sana    = kiritilgan kunning 00:00 dan 23:59 gacha.
Signal.created_at UTC saqlanadi; bu yerda mahalliy chegara UTC ga o'girilib filtrlanadi.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.symbols import full_label
from app.database.models.signal import Signal, SignalConfirmation
from app.core.logging import get_logger
from app.database.models.paper import PaperAccount
from app.services.paper_split import signal_bucket

logger = get_logger(__name__)


# O'zbekiston mahalliy vaqti (UTC+5)
LOCAL_TZ = timezone(timedelta(hours=5))

PERIODS = {
    "daily":   ("KUNLIK HISOBOT", "📅"),
    "weekly":  ("HAFTALIK HISOBOT", "🗓"),
    "monthly": ("OYLIK HISOBOT", "📆"),
}


def _local_start_of_period(period: str, today_local: date) -> datetime:
    """Tanlangan davrning mahalliy boshlanish payti (tz-aware)."""
    if period == "daily":
        start_d = today_local
    elif period == "weekly":
        # Dushanba = hafta boshi
        start_d = today_local - timedelta(days=today_local.weekday())
    elif period == "monthly":
        start_d = today_local.replace(day=1)
    else:
        start_d = today_local
    return datetime(start_d.year, start_d.month, start_d.day, 0, 0, 0, tzinfo=LOCAL_TZ)


def _period_bounds(period: str, target_date: date | None = None) -> tuple[datetime, datetime, str]:
    """(boshlanish_utc, tugash_utc, davr_yorlig'i) — taqvim bo'yicha."""
    now_local = datetime.now(LOCAL_TZ)
    today_local = target_date or now_local.date()

    start_local = _local_start_of_period(period, today_local)
    end_local = datetime.combine(today_local, datetime.max.time(), tzinfo=LOCAL_TZ)

    # O'tmishdagi davr uchun oxirini hozir bilan cheklamaymiz (to'liq kun ko'rinadi).
    label = today_local.strftime("%d.%m.%Y")
    if period == "daily" and target_date is None:
        # Bugungi kun — hozirgi paytgacha
        end_local = now_local
        label = "bugun"
    elif period == "weekly":
        label = f"{start_local.date().strftime('%d.%m.%Y')} → {today_local.strftime('%d.%m.%Y')}"
    elif period == "monthly":
        label = today_local.strftime("%m.%Y")

    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc), label


def completed_period_targets(now: datetime) -> dict:
    """v114: avto-hisobot uchun TUGAGAN davr sanalari (bo'sh-hisobot tuzatishi).

    Hisobot mahalliy yarim tundan so'ng yuborilganda "bugun/hafta/oy" hali
    bo'sh bo'lardi — endi avto-hisobot har doim TUGAGAN davrni yig'adi:
      * daily   -> kecha (to'liq tugagan kun)
      * weekly  -> oxirgi tugagan yakshanba (hafta Dushanba..Yakshanba)
      * monthly -> o'tgan oyning oxirgi kuni
    `now` tzsiz bo'lsa UTC deb hisoblanadi.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    today = now.astimezone(LOCAL_TZ).date()
    back = (today.weekday() + 1) % 7 or 7
    last_sunday = today - timedelta(days=back)
    prev_month_last = today.replace(day=1) - timedelta(days=1)
    return {"daily": today - timedelta(days=1),
            "weekly": last_sunday,
            "monthly": prev_month_last}


def parse_date_input(text: str) -> date | None:
    """Foydalanuvchi kiritgan sanani tushunish: YYYY-MM-DD, DD.MM.YYYY, DD/MM/YYYY."""
    text = (text or "").strip()
    fmts = ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y.%m.%d")
    for fmt in fmts:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _select_signals(signals: list[Signal], start_utc: datetime, end_utc: datetime) -> tuple[list, list]:
    created = [
        s for s in signals
        if s.created_at is not None and start_utc <= _as_utc(s.created_at) <= end_utc
    ]
    closed = [s for s in created if not s.is_active and s.r_multiple is not None]
    return created, closed


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _pips_of(s) -> float:
    """v109: yopilgan signal foyda/zarari (pip) — close_price dan."""
    try:
        from app.notifications.telegram import signal_pips as _sp
        pr, _w = _sp(s)
        return float(pr or 0.0)
    except Exception:  # noqa: BLE001
        return 0.0


async def _read_block(session: AsyncSession, start_utc: datetime, end_utc: datetime,
                      created: list[Signal] | None = None) -> list[str]:
    """Har hisobotda: ko'rilgan xabar / SIGNAL / EMAS (0 bo'lsa ham)."""
    from app.core.logging import get_logger
    log = get_logger(__name__)
    day_from = start_utc.astimezone(LOCAL_TZ).strftime("%Y-%m-%d")
    day_to = end_utc.astimezone(LOCAL_TZ).strftime("%Y-%m-%d")
    seen = sig_n = emas = 0
    by_stats: dict = {}
    chans: list = []
    try:
        from app.services.channel_store import (
            display_name, list_channels, read_stats_for_days, stats_for_channel,
        )
        reads = await read_stats_for_days(session, day_from, day_to)
        seen = int(reads.get("seen") or 0)
        sig_n = int(reads.get("signal") or 0)
        emas = int(reads.get("emas") or 0)
        by_stats = reads.get("by") or {}
        chans = await list_channels(session)
    except Exception as exc:  # noqa: BLE001
        log.warning("[REPORT] kanal stats: %s", exc)

    watch = ""
    try:
        from app.services.channel_watcher import get_status
        st = get_status() or {}
        acc = st.get("account") or ""
        auth = "✅" if st.get("authorized") else "❌"
        poll = (st.get("last_poll") or "—")[:19]
        watch = (
            f"🔎 Kuzatuv: {auth} {acc or 'akkaunt yoq'}  |  "
            f"poll {poll}  |  live 👁 {int(st.get('seen') or 0)} "
            f"✅ {int(st.get('signals') or 0)}"
        )
        err = st.get("last_error") or ""
        if err:
            watch += f"\n⚠️ {err[:120]}"
    except Exception:  # noqa: BLE001
        watch = ""
    lines = [
        "━━━━━━━━━━━━━━━━",
        "📡 <b>KANAL XABARLARI</b>",
        f"👁 Ko'rilgan: <b>{seen}</b>",
        f"✅ SIGNAL: <b>{sig_n}</b>   ➖ EMAS: <b>{emas}</b>",
    ]
    if watch:
        lines.append(watch)
    if chans:
        created = created or []
        ids = [s.id for s in created]
        by_ch: dict[str, list] = {}
        if ids:
            try:
                confs = list((await session.execute(
                    select(SignalConfirmation).where(SignalConfirmation.signal_id.in_(ids))
                )).scalars().all())
                sig_by = {s.id: s for s in created}
                for c in confs:
                    if not (c.strategy_name or "").startswith("ch:"):
                        continue
                    sig = sig_by.get(c.signal_id)
                    if sig is not None:
                        by_ch.setdefault(c.strategy_name, []).append(sig)
            except Exception:  # noqa: BLE001
                pass
        from app.services.channel_store import display_name, stat_key
        for ch in chans:
            sk = stat_key(ch.get("username"), ch.get("chat_id"))
            st = by_stats.get(sk) or {}
            group = by_ch.get(sk, [])
            closed_c = [s for s in group if not s.is_active and s.r_multiple is not None]
            w = sum(1 for s in closed_c if (s.r_multiple or 0) > 0.05)
            lines.append(
                f"  • {display_name(ch)}: 👁 {int(st.get('seen') or 0)}  "
                f"✅ {int(st.get('signal') or 0)}  ➖ {int(st.get('emas') or 0)}"
                + (f"  | 🏆 {w}" if closed_c else "")
            )
    elif by_stats:
        for sk, st in by_stats.items():
            name = (st or {}).get("name") or sk
            lines.append(
                f"  • {name}: 👁 {int((st or {}).get('seen') or 0)}  "
                f"✅ {int((st or {}).get('signal') or 0)}  "
                f"➖ {int((st or {}).get('emas') or 0)}"
            )
    else:
        lines.append("  <i>Hali kanal xabari o'qilmagan.</i>")
    return lines


async def _channel_lines(session: AsyncSession, created: list[Signal]) -> list[str]:
    now = datetime.now(LOCAL_TZ)
    start = datetime(now.year, now.month, now.day, tzinfo=LOCAL_TZ).astimezone(timezone.utc)
    return await _read_block(session, start, now.astimezone(timezone.utc), created)


def _source_split(created: list, closed: list) -> dict:
    """v92: signal manbasi bo'yicha (KANAL / OZI) qisqa xulosa."""
    try:
        from app.services.paper_split import signal_bucket
    except Exception:  # noqa: BLE001
        return {"line": ""}
    k = [s for s in created if signal_bucket(s) == "KANAL"]
    o = [s for s in created if signal_bucket(s) == "OZI"]
    kc = [s for s in closed if signal_bucket(s) == "KANAL"]
    oc = [s for s in closed if signal_bucket(s) == "OZI"]
    kw = sum(1 for s in kc if (s.r_multiple or 0) > 0.05)
    ow = sum(1 for s in oc if (s.r_multiple or 0) > 0.05)
    kr = sum(s.r_multiple or 0 for s in kc)
    orr = sum(s.r_multiple or 0 for s in oc)
    def _wr(w, n):
        return f" WR {w / n * 100:.0f}%" if n else ""
    return {"line": (f"   📡 Kanal: <b>{len(k)}</b> ({len(kc)} yopilgan{_wr(kw, len(kc))}"
                     f" | {kr:+.1f}R)  |  🤖 Bot o‘zi: <b>{len(o)}</b> "
                     f"({len(oc)} yopilgan{_wr(ow, len(oc))} | {orr:+.1f}R)"),
            "kanal": len(k), "ozi": len(o)}


async def _paper_3(session, user_id, acc, *, full: bool = False,
                   since=None, until=None) -> list[str]:
    """v109 (TALAB): YAGONA HISOB — KANAL / O'ZI bo'linishi olib tashlandi.

    Davr davomidagi real $ natija (yopilgan lotlarning realized_pnl yig'indisi)
    + joriy balans. since/until — UTC davr chegaralari (None = hammasi).
    """
    pnl = None
    try:
        from sqlalchemy import func as _fn
        from app.database.models.paper import PaperPosition
        stmt = select(_fn.sum(PaperPosition.realized_pnl)).where(
            PaperPosition.status == "CLOSED")
        if user_id is not None:
            stmt = stmt.where(PaperPosition.user_id == user_id)
        if since is not None:
            stmt = stmt.where(PaperPosition.closed_at >= since)
        if until is not None:
            stmt = stmt.where(PaperPosition.closed_at <= until)
        pnl = await session.scalar(stmt)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[REPORT] paper pnl: %s", exc)
    bal_txt = ""
    try:
        _acc = acc
        if _acc is None and user_id is not None:
            _acc = await session.scalar(
                select(PaperAccount).where(PaperAccount.user_id == user_id))
        if _acc is not None:
            bal_txt = f"  \u00B7  hisob <b>${float(_acc.balance or 0):,.2f}</b>"
    except Exception:  # noqa: BLE001
        pass
    if pnl is None:
        return ["\U0001F4B0 Natija: —" + bal_txt]
    return [f"\U0001F4B0 Jami natija: <b>{float(pnl or 0.0):+,.2f}$</b>{bal_txt}"]


async def build_report(
    session: AsyncSession,
    period: str,
    user_id: int | None = None,
    target_date: date | None = None,
) -> str:
    # v114: sarlavha har doim davrga mos. Avto-hisobot endi TUGAGAN davr uchun
    # ham shu nom bilan keladi (qaysi kun/hafta/oyligi "Davr" qatorida yoziladi).
    title, icon = PERIODS.get(period, PERIODS["daily"])

    start_utc, end_utc, label = _period_bounds(period, target_date)

    stmt = (
        select(Signal)
        .where(Signal.created_at >= start_utc, Signal.created_at <= end_utc)
        .order_by(Signal.created_at.desc())
        .limit(2000)
    )
    signals = list((await session.execute(stmt)).scalars().all())
    created, closed = _select_signals(signals, start_utc, end_utc)


    # ============ v109 (TALAB): IXCHAM HISOBOT — barcha davr bir xil bo'lagida.
    # Faqat: signal soni, win rate, +pip/-pip jami, $ natija. To'liq tafsilot
    # — «📄 To'liq tafsilot» tugmasi orqali (build_full_report).
    wins = [s for s in closed if (s.r_multiple or 0) > 0.05]
    losses = [s for s in closed if (s.r_multiple or 0) < -0.05]
    wr = (len(wins) / len(closed) * 100) if closed else 0.0
    buys = sum(1 for s in created if s.direction == "BUY")
    sells = len(created) - buys

    _pp = [_pips_of(s) for s in closed]
    _win_pips = sum(x for x in _pp if x > 0)
    _loss_pips = sum(-x for x in _pp if x < 0)
    _net_pips = sum(_pp)

    lines = [
        f"{icon} <b>{title}</b>",
        f"📆 Davr: <b>{label}</b>",
        "━━━━━━━━━━━━━━━━",
        f"📨 Signallar: <b>{len(created)}</b>  (🟢 {buys} · 🔴 {sells})",
        f"🎯 Win rate: <b>{len(wins)}/{len(closed)}</b> — {wr:.0f}%",
        f"📊 Pipslar: <b>+{_win_pips:,.0f}</b> / −{_loss_pips:,.0f}  "
        f"(jami <b>{_net_pips:+,.0f}</b>)",
    ]
    lines += await _paper_3(session, user_id, None, since=start_utc, until=end_utc)
    if not created:
        lines += ["ℹ️ Bu davrda signal yuborilmagan."]
    return "\n".join(lines)


async def report_on_demand(
    session: AsyncSession,
    period: str,
    user_id: int | None = None,
    target_date: date | None = None,
) -> str:
    return await build_report(session, period, user_id=user_id, target_date=target_date)


# ============================================================
# TO'LIQ (BATAFSIL) HISOBOT — har coin / TF / yo'nalish / strategiya
# ============================================================
def _group_stats(signals: list) -> tuple[list[str], int, int, float, float]:
    """Yopilgan signallar ro'yxati uchun (n, g'olib, zarar, jamiR, PF) qaytaradi."""
    closed = [s for s in signals if not s.is_active and s.r_multiple is not None]
    wins = [s for s in closed if (s.r_multiple or 0) > 0.05]
    losses = [s for s in closed if (s.r_multiple or 0) < -0.05]
    gp = sum(s.r_multiple for s in wins)
    gl = abs(sum(s.r_multiple for s in losses))
    pf = (gp / gl) if gl else (99.0 if gp else 0.0)
    return closed, len(wins), len(losses), sum(s.r_multiple or 0 for s in closed), pf


def _mini_line(name: str, created: list, closed: list) -> str:
    n_all = len(created)
    n_cl = len(closed)
    if n_cl == 0:
        # v123: bekor qilingan signallarni "hali yopilmagan"dan ajratamiz —
        # aks holda CANCELLED (kirish ochilmagan) ham "ochiq"dek ko'rinardi.
        def _bekor123(s) -> bool:
            es = str(getattr(s, "entry_status", "") or "").upper()
            st = str(getattr(s, "status", "") or "").upper()
            cr = str(getattr(s, "close_reason", "") or "").strip()
            return (es == "CANCELLED") or (st == "CANCELLED") or bool(cr)

        n_bekor = sum(1 for s in created if _bekor123(s) and not s.is_active)
        if n_bekor:
            n_ochiq = n_all - n_bekor
            if n_ochiq == 0:
                return (f"  • {name}: {n_all} ta signal "
                        f"(barchasi bekor — kirish ochilmagan)")
            return (f"  • {name}: {n_all} ta signal "
                    f"({n_bekor} ta bekor, {n_ochiq} ta hali ochiq)")
        return f"  • {name}: {n_all} ta signal (hali yopilmagan)"
    wins = sum(1 for s in closed if (s.r_multiple or 0) > 0.05)
    losses = sum(1 for s in closed if (s.r_multiple or 0) < -0.05)
    be = n_cl - wins - losses
    tot = sum(s.r_multiple or 0 for s in closed)
    gp = sum(s.r_multiple for s in closed if (s.r_multiple or 0) > 0.05)
    gl = abs(sum(s.r_multiple for s in closed if (s.r_multiple or 0) < -0.05))
    wr = wins / n_cl * 100
    pf = (gp / gl) if gl else 0.0
    icon = "🟢" if pf >= 1.3 else ("🟡" if pf >= 1.0 else "🔴")
    return (f"  {icon} {name}: {n_cl} yopilgan — WR {wr:.0f}% "
            f"(🏆{wins} 💥{losses} 🔵{be}) | PF {pf:.2f} | {tot:+.1f}R")


async def build_full_report(session, period: str, user_id=None, target_date=None) -> str:
    """Juda batafsil hisobot: umumiy + har coin + har TF + yo'nalish + strategiya + paper."""
    start_utc, end_utc, label = _period_bounds(period, target_date)
    stmt = (
        select(Signal)
        .where(Signal.created_at >= start_utc, Signal.created_at <= end_utc)
        .order_by(Signal.created_at.desc())
        .limit(3000)
    )
    signals = list((await session.execute(stmt)).scalars().all())
    created = [s for s in signals if start_utc <= _as_utc(s.created_at) <= end_utc]
    closed = [s for s in created if not s.is_active and s.r_multiple is not None]

    wins = [s for s in closed if (s.r_multiple or 0) > 0.05]
    losses = [s for s in closed if (s.r_multiple or 0) < -0.05]
    be = len(closed) - len(wins) - len(losses)
    total_r = sum(s.r_multiple or 0 for s in closed)
    gp = sum(s.r_multiple for s in wins)
    gl = abs(sum(s.r_multiple for s in losses))
    pf = (gp / gl) if gl else (99.0 if gp else 0.0)
    wr = (len(wins) / len(closed) * 100) if closed else 0.0
    avg_r = (total_r / len(closed)) if closed else 0.0
    buys = sum(1 for s in created if s.direction == "BUY")
    sells = len(created) - buys

    L: list[str] = []
    L.append(f"📊 <b>TO'LIQ HISOBOT</b>")
    L.append(f"📆 Davr: <b>{label}</b>")
    L += await _read_block(session, start_utc, end_utc, created)
    L.append("━" * 20)
    L.append("<b>📦 UMUMIY</b>")
    L.append(f"📨 Yangi signallar: <b>{len(created)}</b>  (🟢BUY {buys} | 🔴SELL {sells})")
    L.append(f"✅ Yopilgan: <b>{len(closed)}</b>  (🏆 {len(wins)} | 💥 {len(losses)} | 🔵 {be})")
    L.append(f"⏳ Hali ochiq: {len(created) - len(closed)}")
    L.append(f"🎯 Win rate: <b>{wr:.1f}%</b>")
    L.append(f"⚖️ Profit Factor: <b>{pf:.2f}</b>")
    L.append(f"📊 O'rtacha: {avg_r:+.2f}R | 📦 Jami: <b>{total_r:+.2f}R</b>")
    if closed:
        ncl = len(closed)
        hit1 = sum(1 for s in closed if (s.r_multiple or 0) >= 0.9
                   or s.status in ("TP1_HIT", "TP2_HIT", "TP3_HIT", "TP4_HIT", "TP5_HIT"))
        hit2 = sum(1 for s in closed if (s.r_multiple or 0) >= 1.9
                   or s.status in ("TP2_HIT", "TP3_HIT", "TP4_HIT", "TP5_HIT"))
        hit3 = sum(1 for s in closed if (s.r_multiple or 0) >= 2.4
                   or s.status in ("TP3_HIT", "TP4_HIT", "TP5_HIT"))
        hit4 = sum(1 for s in closed if (s.r_multiple or 0) >= 3.9
                   or s.status in ("TP4_HIT", "TP5_HIT"))
        hit5 = sum(1 for s in closed if (s.r_multiple or 0) >= 4.9
                   or s.status == "TP5_HIT")
        L.append("📐 <b>1R / 2R / 3R / 4R / 5R yetish</b>")
        L.append(f"  ✅ +1R: {hit1}/{ncl} ({hit1/ncl*100:.0f}%)")
        L.append(f"  🎯 +2R: {hit2}/{ncl} ({hit2/ncl*100:.0f}%)")
        L.append(f"  🏁 +3R: {hit3}/{ncl} ({hit3/ncl*100:.0f}%)")
        L.append(f"  🚀 +4R: {hit4}/{ncl} ({hit4/ncl*100:.0f}%)")
        L.append(f"  💎 +5R: {hit5}/{ncl} ({hit5/ncl*100:.0f}%)")

    # ---- Har coin bo'yicha ----
    L.append("━" * 20)
    L.append("<b>🥇 INSTRUMENTLAR BO'YICHA</b>")
    syms = sorted({s.symbol for s in created})
    for sym in syms:
        cs = [s for s in created if s.symbol == sym]
        cd = [s for s in closed if s.symbol == sym]
        L.append(_mini_line(full_label(sym), cs, cd))
    if not syms:
        L.append("  ℹ️ Bu davrda signal yo'q.")

    # ---- Har timeframe bo'yicha ----
    L.append("━" * 20)
    L.append("<b>⏱ TIMEFRAME BO'YICHA</b>")
    tfs = sorted({s.timeframe for s in created})
    for tf in tfs:
        ct = [s for s in created if s.timeframe == tf]
        cd = [s for s in closed if s.timeframe == tf]
        L.append(_mini_line(tf.upper(), ct, cd))

    # ---- Yo'nalish bo'yicha ----
    L.append("━" * 20)
    L.append("<b>↕️ YO'NALISH BO'YICHA</b>")
    for dirn, nm in (("BUY", "🟢 BUY (long)"), ("SELL", "🔴 SELL (short)")):
        cd = [s for s in closed if s.direction == dirn]
        ct = [s for s in created if s.direction == dirn]
        L.append(_mini_line(nm, ct, cd))

    # ---- Bozor rejimi bo'yicha ----
    regimes = sorted({(s.regime or "—") for s in created if s.regime})
    if regimes:
        L.append("━" * 20)
        L.append("<b>🌦 BOZOR REJIMI BO'YICHA</b>")
        for rg in regimes:
            ct = [s for s in created if (s.regime or "—") == rg]
            cd = [s for s in closed if (s.regime or "—") == rg]
            L.append(_mini_line(rg, ct, cd))

    # ---- Strategiyalar bo'yicha (confirmations) ----
    L.append("━" * 20)
    L.append("<b>📡 KANALLAR / MANBA</b>")
    # signal_id -> yopiq R
    r_by_sig = {s.id: (s.r_multiple or 0.0, not s.is_active) for s in created}
    dir_by_sig = {s.id: s.direction for s in created}
    strat_stat: dict[str, list[float]] = {}
    if closed:
        ids = [s.id for s in closed]
        confs = (await session.execute(
            select(SignalConfirmation).where(SignalConfirmation.signal_id.in_(ids))
        )).scalars().all()
        for c in confs:
            # faqat signal yo'nalishini tasdiqlagan ovozlar
            if c.direction != dir_by_sig.get(c.signal_id):
                continue
            rval = r_by_sig.get(c.signal_id)
            if rval is None:
                continue
            strat_stat.setdefault(c.strategy_name, []).append(rval[0] if isinstance(rval, tuple) else rval)
    rows = []
    for name, rs in strat_stat.items():
        rs = [x for x in rs if x is not None]
        if not rs:
            continue
        w = sum(1 for x in rs if x > 0.05)
        tot = sum(rs)
        gp = sum(x for x in rs if x > 0.05)
        gl = abs(sum(x for x in rs if x < -0.05))
        pf2 = (gp / gl) if gl else 0.0
        rows.append((pf2, name, len(rs), w / len(rs) * 100, tot))
    rows.sort(reverse=True)
    for pf2, name, n, wrv, tot in rows:
        icon = "🟢" if pf2 >= 1.3 else ("🟡" if pf2 >= 1.0 else "🔴")
        L.append(f"  {icon} {name}: {n} ta — WR {wrv:.0f}% | PF {pf2:.2f} | {tot:+.1f}R")
    if not rows:
        L.append("  ℹ️ Yopilgan signal strategiyalari hali yo'q.")

    L += await _channel_lines(session, created)

    # ---- 🧾 HAR SIGNAL P/L (v109 TALAB): pips va $ birga ----
    L.append("━" * 20)
    L.append("<b>🧾 HAR SIGNAL P/L</b>")
    _money: dict[int, float] = {}
    if closed:
        try:
            from sqlalchemy import func as _fn
            from app.database.models.paper import PaperPosition as _PP
            _rows = (await session.execute(
                select(_PP.signal_id, _fn.sum(_PP.realized_pnl))
                .where(_PP.signal_id.in_([s.id for s in closed]))
                .group_by(_PP.signal_id))).all()
            _money = {int(r[0]): float(r[1] or 0.0) for r in _rows}
        except Exception as exc:  # noqa: BLE001
            logger.debug("[REPORT] har signal $: %s", exc)
    for s in closed[:25]:
        r = float(s.r_multiple or 0)
        emo = "🏆" if r > 0.05 else ("🔵" if abs(r) <= 0.05 else "💥")
        no_txt = f" №{s.signal_no}" if getattr(s, "signal_no", None) else ""
        m = _money.get(int(s.id))
        m_txt = f" · {m:+,.2f}$" if m is not None else ""
        L.append(f"  {emo}{no_txt} {full_label(s.symbol)} {s.direction} "
                 f"{_pips_of(s):+,.0f}p{m_txt} ({r:+.1f}R)")
    if not closed:
        L.append("  ℹ️ Bu davrda yopilgan signal yo'q.")

    # ---- Paper (foydalanuvchi shaxsiy hisobi) ----
    if user_id is not None:
        acc = await session.scalar(select(PaperAccount).where(PaperAccount.user_id == user_id))
        L.append("━" * 20)
        L += await _paper_3(session, user_id, acc, since=start_utc, until=end_utc)
        L.append("<b>💵 QOG'OZ HISOB (sizning — umumiy sozlamalar)</b>")
        if acc:
            pnl = acc.balance - acc.initial_balance
            pnl_pct = (pnl / acc.initial_balance * 100) if acc.initial_balance else 0
            tr, wn, ls = int(acc.total_trades or 0), int(acc.total_wins or 0), 0
            try:
                from app.paper_trading.engine import PaperEngine
                st = await PaperEngine().trade_stats(session, user_id)
                tr, wn, ls = int(st["trades"]), int(st["wins"]), int(st["losses"])
            except Exception as exc:  # noqa: BLE001
                ls = max(0, tr - wn)
                logger.debug("[REPORT] trade_stats: %s", exc)
            losses_acc = ls if ls else max(0, tr - wn)
            awr = (wn / tr * 100) if tr else 0
            L.append(f"💵 Balans: <b>${acc.balance:,.2f}</b> / boshlang'ich ${acc.initial_balance:,.2f}")
            L.append(f"📈 Foyda: <b>{pnl:+,.2f}$ ({pnl_pct:+.1f}%)</b>")
            L.append(f"📊 Bitimlar: {tr} (🏆{wn} / 💥{losses_acc}) WR {awr:.0f}%")
            L.append(f"🤖 Avto-trade: {'YOQILGAN ✅' if acc.auto_trade_enabled else 'o\'chiq ❌'}")
            if acc.paused_by_circuit:
                L.append("⛔️ Himoya: 3 ketma-ket zarar — avto-trade PAUZA qilingan!")
            else:
                L.append(f"🔁 Ketma-ket zarar: {acc.consecutive_losses}/3")
        else:
            L.append("  ℹ️ Hisob hali ochilmagan.")

    L.append("━" * 20)
    L.append("<i>Bu tahliliy statistika — moliyaviy tavsiya emas.</i>")
    return "\n".join(L)
