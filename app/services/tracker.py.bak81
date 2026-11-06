"""2 lot: Lot1 +3R da yopiladi, Lot2 +4R (momentum bo'lsa +5R).

Zarar −1R (ikkala lot). Admin aytmasa ham bozor kuzatiladi.
v50: + har bir yopilishda SABAB yoziladi (TP1/TP3/TP5/SL/VAQT TUGADI/BEKOR)
     + muddat tugasa (kanal M1: 4 soat) pozitsiya bozor narxida yopiladi va
       natija kartasi yuboriladi — signal abadiy ochiq qolmaydi.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import SignalStatus
from app.core.logging import get_logger
from app.database import crud
from app.database.models.signal import Signal
from app.database.models.stats import StrategyStat
from app.engine.risk import format_price, r_price
from app.paper_trading.engine import PaperEngine

logger = get_logger(__name__)


_REASON_BY_STATUS = {
    "SL_HIT": "SL", "TP1_HIT": "BE (himoya)", "TP2_HIT": "TP2",
    "TP3_HIT": "TP3", "TP4_HIT": "TP4", "TP5_HIT": "TP5",
    "EXPIRED": "VAQT TUGADI", "CANCELLED": "BEKOR",
}


def classify_result(r: float) -> str:
    if r > 0.05:
        return "WIN"
    if r < -0.05:
        return "LOSS"
    return "BREAKEVEN"


def _momentum_ok(df: pd.DataFrame, buy: bool) -> bool:
    try:
        if df is None or len(df) < 4:
            return False
        c = df["close"].astype(float)
        last, prev, older = float(c.iloc[-1]), float(c.iloc[-2]), float(c.iloc[-3])
        if buy:
            return last >= prev and last > older
        return last <= prev and last < older
    except Exception:  # noqa: BLE001
        return False


def _is_runner(p) -> bool:
    return int(getattr(p, "stage", 0) or 0) >= 10


class SignalTracker:
    def __init__(self, paper_engine: PaperEngine, settings: Settings) -> None:
        self._paper = paper_engine
        self._settings = settings

    async def update_for_candle(self, session: AsyncSession, signal: Signal,
                                df: pd.DataFrame, notifier=None) -> None:
        try:
            await self._process(session, signal, df, notifier)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Tracker xatosi signal #%s: %s", signal.id, exc)

    async def _fill(self, session, pos, price: float, *,
                    count_trade: bool = True, reason: str = "") -> None:
        await self._paper.apply_fill(
            session, pos, price, portion=0.0, is_final=True,
            exit_price_for_remaining=price, count_trade=count_trade, reason=reason,
        )

    # ---------- Muddat (M1 signallar abadiy ochiq qolmasin) ----------
    def expiry_minutes(self, signal) -> int:
        try:
            return int(self._settings.expiry_minutes_for(
                str(signal.timeframe or "1m"),
                str(getattr(signal, "quality_mode", "") or ""),
            ))
        except Exception:  # noqa: BLE001
            return 240

    async def expire_signal(self, session: AsyncSession, signal: Signal,
                            price: float, notifier=None) -> bool:
        """Muddati tugagan signalni bozor narxida yopadi + natija kartasi."""
        try:
            positions = await self._paper.open_positions(session, signal_id=signal.id)
            for i, p in enumerate(positions):
                try:
                    await self._fill(session, p, price, count_trade=(i == 0),
                                     reason="VAQT TUGADI")
                except Exception as exc:  # noqa: BLE001
                    logger.error("[TRACKER] expiry fill: %s", exc)
            stats = await self._paper.signal_pnl(session, signal.id, mark_price=price)
            r = float(stats.get("r_avg") or 0.0)
            # muddat bo'yicha kichik natija "g'alaba" deb hisoblanmaydi (halol statistika)
            if abs(r) < 0.5:
                r = round(r, 3)
            signal.status = SignalStatus.EXPIRED.value
            await session.commit()
            if notifier:
                no = f"№{signal.signal_no} " if getattr(signal, "signal_no", None) else ""
                await notifier.send_event(
                    f"\u23F3 <b>{no}{signal.symbol}</b> — <b>muddat tugadi</b> "
                    f"({self.expiry_minutes(signal)} daqiqa). Yopilish: {format_price(price)} · "
                    f"{r:+.2f}R · {stats.get('total_pnl', 0.0):+,.2f}$"
                )
            if abs(r) < 0.5:
                signal.status = SignalStatus.EXPIRED.value
                await session.commit()
                await crud.close_signal(
                    session, signal, status=SignalStatus.EXPIRED,
                    result="BREAKEVEN", r_multiple=r,
                    pnl_percent=0.0, close_price=price, reason="VAQT TUGADI",
                )
                if notifier:
                    try:
                        await session.refresh(signal)
                        await notifier.send_result(signal)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("[TRACKER] muddat kartasi: %s", exc)
                logger.info("[TRACKER] #%s muddat tugadi (zararsiz) R=%.2f", signal.id, r)
                return True
            await self._finish_signal(
                session, signal, notifier, exit_price=price, r_hint=r,
                reason="VAQT TUGADI",
            )
            logger.info("[TRACKER] #%s muddat tugadi → yopildi R=%.2f", signal.id, r)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.exception("[TRACKER] expiry xatosi #%s: %s", getattr(signal, "id", "?"), exc)
            return False

    async def sweep_expired(self, session: AsyncSession, symbol: str | None = None,
                            notifier=None, price_lookup=None) -> int:
        """Muddati o'tgan barcha ochiq signallarni yopadi (soat mexanizmi)."""
        from app.database import crud
        closed = 0
        try:
            syms = [symbol] if symbol else None
            opens = []
            if syms:
                opens = await crud.get_active_signals(session, syms[0])
            else:
                opens = list((await session.execute(
                    select(Signal).where(Signal.is_active.is_(True))
                )).scalars().all())
            now = datetime.now(timezone.utc)
            for sig in opens:
                created = sig.created_at
                if created is None:
                    continue
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                age = (now - created).total_seconds() / 60.0
                if age < self.expiry_minutes(sig):
                    continue
                price = None
                if price_lookup is not None:
                    try:
                        price = await price_lookup(sig.symbol)
                    except Exception:  # noqa: BLE001
                        price = None
                if not price:
                    price = float(sig.close_price or sig.entry or 0.0) or None
                if not price:
                    continue
                if await self.expire_signal(session, sig, float(price), notifier):
                    closed += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("[TRACKER] sweep xatosi: %s", exc)
        return closed

    async def _process(self, session: AsyncSession, signal: Signal,
                       df: pd.DataFrame, notifier) -> None:
        if df is None or len(df) < 1:
            return
        last = df.iloc[-1]
        high = float(last["high"])
        low = float(last["low"])
        buy = str(signal.direction).upper() == "BUY"
        positions = await self._paper.open_positions(session, signal_id=signal.id)

        # 0) MUDDAT: kanal M1 signali belgilangan daqiqadan keyin yopiladi
        created = getattr(signal, "created_at", None)
        if created is not None:
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_min = (datetime.now(timezone.utc) - created).total_seconds() / 60.0
            if age_min >= self.expiry_minutes(signal):
                await self.expire_signal(session, signal, float(last["close"]), notifier)
                return

        if not positions:
            if signal.is_active:
                # paper yo'q — signalni ham yopamiz emas, kutyapmiz
                pass
            return

        tp4 = r_price(signal.direction, float(signal.entry), float(signal.sl), 4)
        tp5 = r_price(signal.direction, float(signal.entry), float(signal.sl), 5)

        def hit_above(level: float) -> bool:
            return (high >= level) if buy else (low <= level)

        def hit_below(level: float) -> bool:
            return (low <= level) if buy else (high >= level)

        # 1) SL — har lot o'z stopida (BE dan keyin kirish)
        sl_closed = []
        still = []
        counted = False
        for p in positions:
            sl = float(p.sl or signal.sl)
            if hit_below(sl):
                try:
                    await self._fill(session, p, sl, count_trade=not counted,
                                     reason=("BE" if getattr(p, "sl_moved_to_be", False) else "SL"))
                    counted = True
                    sl_closed.append(p)
                except Exception as exc:  # noqa: BLE001
                    logger.error("[TRACKER] SL fill: %s", exc)
            else:
                still.append(p)

        if sl_closed and notifier:
            r_sl = -1.0 if not any(getattr(p, "sl_moved_to_be", False) for p in sl_closed) else 0.0
            word = "−1R STOP" if r_sl < 0 else "breakeven"
            no = f"№{signal.signal_no} " if getattr(signal, "signal_no", None) else ""
            await notifier.send_event(
                f"🛑 <b>{no}{signal.symbol}</b> — {word} ({len(sl_closed)} lot) @ {format_price(sl_closed[0].sl)}"
            )

        positions = still
        if not positions:
            be = any(getattr(p, "sl_moved_to_be", False) for p in sl_closed)
            if not be:
                signal.status = SignalStatus.SL_HIT.value
            await self._finish_signal(
                session, signal, notifier,
                exit_price=float(signal.sl),
                r_hint=(0.0 if be else -1.0),
            )
            return

        # 2) +1R himoya — ikkala lot
        if any(p.stage in (0, 10) for p in positions) and hit_above(float(signal.tp1)):
            for p in positions:
                if p.stage in (0, 10):
                    p.sl = signal.entry
                    p.sl_moved_to_be = True
                    p.stage = 1 if p.stage < 10 else 11
            if str(signal.status) not in (
                SignalStatus.TP1_HIT.value, SignalStatus.TP2_HIT.value,
                SignalStatus.TP3_HIT.value, SignalStatus.TP4_HIT.value,
            ):
                signal.status = SignalStatus.TP1_HIT.value
            await session.commit()
            if notifier:
                no = f"№{signal.signal_no} " if getattr(signal, "signal_no", None) else ""
                await notifier.send_event(
                    f"🔒 <b>{no}{signal.symbol}</b> — +1R himoya (2 lot). Stop kirishda."
                )
            logger.info("[TRACKER] #%s TP1 BE 2 lot", signal.id)

        # 3) Lot1 +3R da to'liq yopiladi
        lot1 = [p for p in positions if not _is_runner(p)]
        lot2 = [p for p in positions if _is_runner(p)]
        if lot1 and hit_above(float(signal.tp3)):
            for i, p in enumerate(lot1):
                try:
                    await self._fill(session, p, float(signal.tp3), count_trade=(i == 0),
                                     reason="TP3")
                except Exception as exc:  # noqa: BLE001
                    logger.error("[TRACKER] lot1 3R: %s", exc)
            signal.status = SignalStatus.TP3_HIT.value
            for p in lot2:
                p.sl = signal.tp1
                p.sl_moved_to_be = True
                if p.stage < 12:
                    p.stage = 12
            await session.commit()
            if notifier:
                no = f"№{signal.signal_no} " if getattr(signal, "signal_no", None) else ""
                await notifier.send_event(
                    f"🏁 <b>{no}{signal.symbol}</b> — <b>Lot1 +3R yopildi</b> @ {format_price(signal.tp3)}. "
                    f"Lot2 +4R/+5R ga qoldi. Stop +1R."
                )
            logger.info("[TRACKER] #%s lot1 +3R, lot2 runner", signal.id)
            positions = await self._paper.open_positions(session, signal_id=signal.id)
            lot2 = [p for p in positions if _is_runner(p)]
            if not positions:
                await self._finish_signal(session, signal, notifier, exit_price=float(signal.tp3))
                return

        # 4) Lot2 +4R / +5R
        if not lot2:
            if not await self._paper.open_positions(session, signal_id=signal.id):
                await self._finish_signal(session, signal, notifier, exit_price=float(signal.tp3))
            return

        mom = _momentum_ok(df, buy)
        hit4 = hit_above(tp4)
        hit5 = hit_above(tp5)

        if hit5:
            for i, p in enumerate(lot2):
                # Lot2 uchun bitim QAYTA sanalmaydi — Lot1 yopilganda sanalgan
                try:
                    await self._fill(session, p, tp5, count_trade=False, reason="TP5")
                except Exception as exc:  # noqa: BLE001
                    logger.error("[TRACKER] lot2 5R: %s", exc)
            signal.status = SignalStatus.TP5_HIT.value
            await session.commit()
            if notifier:
                no = f"№{signal.signal_no} " if getattr(signal, "signal_no", None) else ""
                await notifier.send_event(
                    f"💎 <b>{no}{signal.symbol}</b> — <b>Lot2 +5R yopildi</b> @ {format_price(tp5)}."
                )
            await self._finish_signal(session, signal, notifier, exit_price=tp5, r_hint=4.0)
            return

        if hit4:
            if mom:
                for p in lot2:
                    p.sl = float(signal.tp3)
                    p.sl_moved_to_be = True
                    p.stage = 13
                signal.status = SignalStatus.TP4_HIT.value
                await session.commit()
                if notifier:
                    no = f"№{signal.signal_no} " if getattr(signal, "signal_no", None) else ""
                    await notifier.send_event(
                        f"🚀 <b>{no}{signal.symbol}</b> — Lot2 +4R. Momentum bor — +5R kutiladi. Stop +3R."
                    )
                logger.info("[TRACKER] #%s lot2 +4R → 5R", signal.id)
                return
            for i, p in enumerate(lot2):
                try:
                    await self._fill(session, p, tp4, count_trade=False, reason="TP4")
                except Exception as exc:  # noqa: BLE001
                    logger.error("[TRACKER] lot2 4R: %s", exc)
            signal.status = SignalStatus.TP4_HIT.value
            await session.commit()
            if notifier:
                await notifier.send_event(
                    f"🚀 <b>{signal.symbol}</b> — <b>Lot2 +4R yopildi</b> @ {format_price(tp4)}."
                )
            await self._finish_signal(session, signal, notifier, exit_price=tp4, r_hint=3.5)
            return

    async def _finish_signal(self, session, signal, notifier, *,
                             exit_price: float, r_hint: float | None = None,
                             reason: str = "") -> None:
        left = await self._paper.open_positions(session, signal_id=signal.id)
        if left:
            return
        if signal.r_multiple is not None and not signal.is_active:
            return
        # HAQIQIY natija: yopilgan lotlardan hisoblanadi (taxmin emas).
        # Aks holda karta "ZARARSIZ +0.00R" deb yozib, pul esa +300$ ko'rsatardi.
        r = None
        try:
            info = await self._paper.signal_pnl(session, signal.id)
            if info.get("lots"):
                r = float(info.get("r_avg") or 0.0)
                avg_exit = info.get("avg_exit")
                if avg_exit:
                    exit_price = float(avg_exit)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[TRACKER] natija hisobi: %s", exc)
        if r is None:
            r = r_hint
        if r is None:
            st = str(signal.status or "")
            r = {"TP5_HIT": 4.0, "TP4_HIT": 3.5, "TP3_HIT": 3.0, "SL_HIT": -1.0,
                 "EXPIRED": 0.0}.get(st, 0.0)
        result = classify_result(r)
        try:
            status = SignalStatus(signal.status)
        except Exception:  # noqa: BLE001
            status = SignalStatus.TP3_HIT if (r or 0) > 0 else SignalStatus.SL_HIT
        if status in (
            SignalStatus.CREATED, SignalStatus.ACTIVE,
            SignalStatus.TP1_HIT, SignalStatus.TP2_HIT,
        ):
            status = SignalStatus.TP3_HIT if (r or 0) > 0 else SignalStatus.SL_HIT
        # Narx bo'yicha % — kirishdan HAQIQIY chiqish narxigacha
        pnl_pct = 0.0
        try:
            if exit_price and signal.entry:
                diff = float(exit_price) - float(signal.entry)
                if str(signal.direction).upper() == "SELL":
                    diff = -diff
                pnl_pct = round(diff / float(signal.entry) * 100, 3)
            else:
                risk_frac = abs(signal.entry - signal.sl) / signal.entry if signal.entry else 0.0
                pnl_pct = round(r * risk_frac * 100, 3)
        except Exception:  # noqa: BLE001
            pnl_pct = 0.0
        await crud.close_signal(
            session, signal, status=status, result=result,
            r_multiple=r, pnl_percent=pnl_pct, close_price=exit_price,
            reason=(reason or _REASON_BY_STATUS.get(str(signal.status or ""), "")),
        )
        await self._update_strategy_stats(session, signal, r)
        if notifier:
            try:
                await session.refresh(signal)
                await notifier.send_result(signal)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[TRACKER] result: %s", exc)
        logger.info("[TRACKER] #%s signal yopildi %s R=%.2f", signal.id, result, r)

    async def _update_strategy_stats(self, session: AsyncSession, signal: Signal,
                                     r: float) -> None:
        confirmations = await crud.get_confirmations(session, signal.id)
        voters = [c for c in confirmations if c.direction == signal.direction]
        if not voters:
            return
        for c in voters:
            stat = await session.scalar(
                select(StrategyStat).where(StrategyStat.strategy_name == c.strategy_name)
            )
            if stat is None:
                stat = StrategyStat(
                    strategy_name=c.strategy_name[:40],
                    display_name=(c.reason or c.strategy_name)[:80],
                    is_active=True, weight=1.0,
                )
                session.add(stat)
                await session.flush()
            stat.total_signals += 1
            stat.sum_r += r
            if r > 0.05:
                stat.wins += 1
                stat.gross_profit_r += r
            elif r < -0.05:
                stat.losses += 1
                stat.gross_loss_r += r
            else:
                stat.breakeven += 1
        await session.commit()

    async def cancel_opposite(self, session: AsyncSession, signal: Signal,
                              close_price: float) -> None:
        skip_id = getattr(signal, "id", None)
        opens = await crud.get_active_signals(session, signal.symbol)
        for opp in opens:
            if skip_id and opp.id == skip_id:
                continue
            if (opp.quality_mode or "").upper() != "CHANNEL":
                continue
            for i, pos in enumerate(await self._paper.open_positions(session, signal_id=opp.id)):
                try:
                    await self._fill(session, pos, close_price, count_trade=(i == 0),
                                     reason="BEKOR (yangi signal)")
                except Exception as exc:  # noqa: BLE001
                    logger.error("[TRACKER] flip: %s", exc)
            await crud.close_signal(
                session, opp, status=SignalStatus.CANCELLED,
                result="CANCELLED", r_multiple=0.0,
                pnl_percent=0.0, close_price=close_price,
                reason="BEKOR (yangi signal)",
            )
            logger.info("[TRACKER] #%s yopildi (yangi signal)", opp.id)
