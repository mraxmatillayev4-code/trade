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
from app.database.models.paper import PaperAccount

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


async def build_report(
    session: AsyncSession,
    period: str,
    user_id: int | None = None,
    target_date: date | None = None,
) -> str:
    if target_date is not None:
        title, icon = "SANA BO'YICHA HISOBOT", "🔎"
    else:
        title, icon = PERIODS[period]

    start_utc, end_utc, label = _period_bounds(period, target_date)

    stmt = (
        select(Signal)
        .where(Signal.created_at >= start_utc, Signal.created_at <= end_utc)
        .order_by(Signal.created_at.desc())
        .limit(2000)
    )
    signals = list((await session.execute(stmt)).scalars().all())
    created, closed = _select_signals(signals, start_utc, end_utc)

    wins = [s for s in closed if (s.r_multiple or 0) > 0.05]
    losses = [s for s in closed if (s.r_multiple or 0) < -0.05]
    be = len(closed) - len(wins) - len(losses)
    total_r = sum(s.r_multiple or 0 for s in closed)
    avg_r = (total_r / len(closed)) if closed else 0.0
    wr = (len(wins) / len(closed) * 100) if closed else 0.0

    buys = sum(1 for s in created if s.direction == "BUY")
    sells = len(created) - buys

    by_symbol: dict[str, int] = {}
    by_tf: dict[str, int] = {}
    for s in created:
        by_symbol[s.symbol] = by_symbol.get(s.symbol, 0) + 1
        by_tf[s.timeframe] = by_tf.get(s.timeframe, 0) + 1
    top_symbol_raw = max(by_symbol, key=by_symbol.get) if by_symbol else "—"
    top_symbol = full_label(top_symbol_raw) if top_symbol_raw != "—" else "—"
    top_tf = str(max(by_tf, key=by_tf.get)).upper() if by_tf else "—"

    acc = None
    if user_id is not None:
        acc = await session.scalar(
            select(PaperAccount).where(PaperAccount.user_id == user_id)
        )

    lines = [
        f"{icon} <b>{title}</b>",
        f"📆 Davr: <b>{label}</b>",
    ]
    lines += await _read_block(session, start_utc, end_utc, created)
    lines += [
        "━━━━━━━━━━━━━━━━",
        f"📨 Chiqarilgan signallar: <b>{len(created)}</b>",
        f"   🟢 BUY: {buys}  |  🔴 SELL: {sells}",
        f"✅ Yopilgan (baholangan): {len(closed)}",
        f"   🏆 Yutuq: {len(wins)}  |  💥 Zarar: {len(losses)}  |  🔵 Zararsiz: {be}",
        "━━━━━━━━━━━━━━━━",
        f"🎯 Win rate: <b>{wr:.1f}%</b>",
        f"📊 O'rtacha R: <b>{avg_r:+.2f}R</b>",
        f"📦 Jami natija: <b>{total_r:+.2f}R</b>",
        f"🏅 Eng faol: <b>{top_symbol}</b>  •  ⏱ {str(top_tf).upper()}",
    ]
    if not created:
        lines += [
            "━━━━━━━━━━━━━━━━",
            "ℹ️ Bu davrda foydalanuvchilarga signal yuborilmagan.",
        ]
    if acc:
        pnl = acc.balance - acc.initial_balance
        lines += [
            "━━━━━━━━━━━━━━━━",
            f"💵 Paper balans: <b>${acc.balance:,.2f}</b> ({pnl:+,.2f}$)",
        ]
    lines += [
        "━━━━━━━━━━━━━━━━",
        "<i>Bu tahliliy statistika — moliyaviy tavsiya emas.</i>",
    ]
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

    # ---- So'nggi bitimlar ----
    L.append("━" * 20)
    L.append("<b>🕒 SO'NGGI 8 BAHOLANGAN SIGNAL</b>")
    for s in closed[:8]:
        r = s.r_multiple or 0
        emo = "🏆" if r > 0.05 else ("🔵" if abs(r) <= 0.05 else "💥")
        L.append(f"  {emo} {full_label(s.symbol)} {s.timeframe.upper()} {s.direction} "
                 f"→ {r:+.1f}R (2 lot o'rtachasi)")

    # ---- Paper (foydalanuvchi shaxsiy hisobi) ----
    if user_id is not None:
        acc = await session.scalar(select(PaperAccount).where(PaperAccount.user_id == user_id))
        L.append("━" * 20)
        L.append("<b>💵 QOG'OZ HISOB (sizning)</b>")
        if acc:
            pnl = acc.balance - acc.initial_balance
            pnl_pct = (pnl / acc.initial_balance * 100) if acc.initial_balance else 0
            losses_acc = acc.total_trades - acc.total_wins
            awr = (acc.total_wins / acc.total_trades * 100) if acc.total_trades else 0
            L.append(f"💵 Balans: <b>${acc.balance:,.2f}</b> / boshlang'ich ${acc.initial_balance:,.2f}")
            L.append(f"📈 Foyda: <b>{pnl:+,.2f}$ ({pnl_pct:+.1f}%)</b>")
            L.append(f"📊 Bitimlar: {acc.total_trades} (🏆{acc.total_wins} / 💥{losses_acc}) WR {awr:.0f}%")
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
