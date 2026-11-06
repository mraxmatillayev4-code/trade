"""Paper trading — har bir FOYDALANUVCHI uchun alohida virtual pul.

- Signallar umumiy (bozor bitta), lekin har kimning balansi/bitimlari/avto-trade'i alohida.
- 3 ketma-ket zarar → faqat O'SHA foydalanuvchining avto-trade'i pauzaga tushadi
  (signallar va hisobotlar barchaga davom etadi).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import Direction, PaperStatus
from app.core.logging import get_logger
from app.database.models.paper import PaperAccount, PaperPosition
from app.database.models.signal import Signal
from app.engine.risk import lot_position_size, money_for_move

logger = get_logger(__name__)

DEFAULT_BALANCE = 10_000.0


class PaperEngine:
    def __init__(self) -> None:
        self._settings = get_settings()

    # ---------- Hisob ----------
    async def get_account(self, session: AsyncSession, user_id: int) -> PaperAccount:
        acc = await session.scalar(
            select(PaperAccount).where(PaperAccount.user_id == user_id)
        )
        if acc is None:
            acc = PaperAccount(
                user_id=user_id,
                name="main",
                initial_balance=self._settings.paper_initial_balance or DEFAULT_BALANCE,
                balance=self._settings.paper_initial_balance or DEFAULT_BALANCE,
                auto_trade_enabled=True,
            )
            session.add(acc)
            await session.commit()
            await session.refresh(acc)
        return acc

    async def open_positions(self, session: AsyncSession, user_id: int | None = None,
                             symbol: str | None = None,
                             signal_id: int | None = None) -> list[PaperPosition]:
        stmt = select(PaperPosition).where(
            PaperPosition.status == PaperStatus.OPEN.value
        ).order_by(PaperPosition.opened_at.desc())
        if user_id is not None:
            stmt = stmt.where(PaperPosition.user_id == user_id)
        if symbol:
            stmt = stmt.where(PaperPosition.symbol == symbol)
        if signal_id is not None:
            stmt = stmt.where(PaperPosition.signal_id == signal_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def recent_closed(self, session: AsyncSession, user_id: int,
                            limit: int = 10) -> list[PaperPosition]:
        stmt = (
            select(PaperPosition)
            .where(PaperPosition.status == PaperStatus.CLOSED.value,
                   PaperPosition.user_id == user_id)
            .order_by(PaperPosition.closed_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    # ---------- Signalga bitim ochish (avto-trade yoqilgan har bir user uchun) ----------
    async def open_for_signal(self, session: AsyncSession, signal: Signal,
                              user_ids: list[int]) -> int:
        """Har signal: riskka qarab 2 ta lot. Lot1=+3R, Lot2=+4R/+5R."""
        from app.engine.risk import r_price
        opened = 0
        for uid in user_ids:
            acc = await self.get_account(session, uid)
            if not acc.auto_trade_enabled:
                logger.info("[PAPER] user %s avto-trade o'chiq", uid)
                continue
            is_ch = (getattr(signal, "quality_mode") or "").upper() == "CHANNEL"
            if acc.paused_by_circuit and not is_ch:
                logger.info("[PAPER] user %s pauza (3 zarar)", uid)
                continue
            # Yangi signal eski ochiq lotlarni YOPMAYDI
            try:
                risk_distance = abs(float(signal.entry or 0) - float(signal.sl or 0))
                if risk_distance <= 0:
                    logger.warning("[PAPER] risk 0 — #%s", signal.id)
                    continue
                # v68: HAJM fikslangan (terminaldagi kabi): 1 lot = 100 oz.
                # Pul = narx farqi x hajm; SL urilsa shu pul yo'qoladi.
                _lot = float(getattr(self._settings, "lot_size", 1.0) or 1.0)
                _ctr = float(getattr(self._settings, "contract_size", 100.0) or 100.0)
                qty, risk_amount = lot_position_size(risk_distance, _lot, _ctr)
                if qty <= 0:
                    continue
                half_q = qty / 2.0
                half_r = risk_amount / 2.0
                tp4 = r_price(signal.direction, float(signal.entry), float(signal.sl), 4)
                tp5 = r_price(signal.direction, float(signal.entry), float(signal.sl), 5)
                common = dict(
                    user_id=uid, signal_id=signal.id,
                    symbol=signal.symbol, timeframe=signal.timeframe,
                    direction=signal.direction, status=PaperStatus.OPEN.value,
                    entry=signal.entry, sl=signal.sl, tp1=signal.tp1,
                    qty_total=half_q, qty_remaining=half_q, risk_amount=half_r,
                    realized_pnl=0.0, balance_before=acc.balance,
                )
                # Lot 1 — +3R da yopiladi (stage 0..2)
                session.add(PaperPosition(
                    **common, tp2=signal.tp2, tp3=signal.tp3, stage=0,
                ))
                # Lot 2 — +4R / +5R (stage 10+)
                session.add(PaperPosition(
                    **common, tp2=tp4, tp3=tp5, stage=10,
                ))
                opened += 2
                logger.info(
                    "[PAPER] user %s 2 lot #%s hajm=%.2f+%.2f lot "
                    "(1 lot = %.0f oz; SL gacha %.2f$)",
                    uid, signal.id, half_q / _ctr, half_q / _ctr, _ctr, risk_amount)
            except Exception as exc:  # noqa: BLE001
                logger.error("[PAPER] user %s uchun bitim ochilmadi: %s", uid, exc)
        if opened:
            await session.commit()
            logger.info("[PAPER] signal #%s uchun %d ta lot ochildi", signal.id, opened)
            # v74: broker ulangan bo'lsa — ochish buyruqlari navbatga
            try:
                await self._broker_open(session, signal, user_ids)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[BRK] ochishni yuborish: %s", exc)
        return opened

    async def _broker_open(self, session: AsyncSession, signal, user_ids) -> None:
        """Broker egasi bo'lgan foydalanuvchi uchun ochish buyruqlarini qo'yadi."""
        from app.services import broker as brk
        cfg = await brk.load_cfg(session)
        if not brk.is_ready(cfg):
            return
        owner = brk.owner_id(cfg)
        if not owner or owner not in [int(u) for u in (user_ids or [])]:
            return
        lots = await self.open_positions(session, user_id=owner, signal_id=signal.id)
        if not lots:
            return
        for pos in lots:
            tag = "Lot1" if int(getattr(pos, "stage", 0) or 0) < 10 else "Lot2"
            await brk.enqueue(
                session, "OPEN", symbol=pos.symbol, side=pos.direction,
                lot=round(float(pos.qty_total or 0) / 100.0, 2),
                sl=float(pos.sl or 0.0), tp=float(pos.tp3 or 0.0),
                signal_id=int(signal.id), comment=("SINO " + tag),
            )

    # ---------- Yopilish (bir user pozitsiyasi) ----------
    async def _open_lots_left(self, session: AsyncSession, pos: PaperPosition) -> int:
        """Shu SIGNAL bo'yicha ochiq qolgan lotlar (o'zidan tashqari) — v63."""
        from sqlalchemy import func

        stmt = select(func.count(PaperPosition.id)).where(
            PaperPosition.user_id == pos.user_id,
            PaperPosition.status == PaperStatus.OPEN.value,
            PaperPosition.id != pos.id,
        )
        if getattr(pos, "signal_id", None):
            stmt = stmt.where(PaperPosition.signal_id == pos.signal_id)
        else:
            stmt = stmt.where(PaperPosition.symbol == pos.symbol)
        return int((await session.execute(stmt)).scalar() or 0)

    async def trade_stats(self, session: AsyncSession, user_id: int) -> dict:
        """v63: statistika DB dan hosil qilinadi (saqlangan hisoblagich xato bo'lsa ham to'g'ri).

        Bitim = bitta SIGNAL (2 lot birga). G'alaba = bitim puli +0.05$ dan katta.
        """
        rows = list((await session.execute(
            select(PaperPosition).where(PaperPosition.user_id == user_id)
            .order_by(PaperPosition.id)
        )).scalars().all())
        groups: dict = {}
        for x in rows:
            key = getattr(x, "signal_id", None)
            if key is None:
                key = ("pos", x.id)
            groups.setdefault(key, []).append(x)
        trades = wins = losses = be = 0
        open_cnt = 0
        pnl = 0.0
        for arr in groups.values():
            cash = sum(float(getattr(x, "realized_pnl", 0) or 0) for x in arr)
            pnl += cash
            if any(str(getattr(x, "status", "")) == PaperStatus.OPEN.value for x in arr):
                open_cnt += 1
                continue
            trades += 1
            if cash > 0.05:
                wins += 1
            elif cash < -0.05:
                losses += 1
            else:
                be += 1
        return {
            "trades": trades, "wins": wins, "losses": losses, "breakeven": be,
            "winrate": (wins / trades * 100.0) if trades else 0.0,
            "open_signals": open_cnt, "open_lots": len([x for x in rows
                                                        if str(getattr(x, "status", "")) == PaperStatus.OPEN.value]),
            "pnl": round(pnl, 4), "groups": len(groups),
        }

    # ================= v74: QO'LDA YOPISH (inson omili) =================
    async def manual_close(self, session: AsyncSession, *, user_id: int,
                           signal_id: int | None = None, price: float | None = None,
                           reason: str = "QO'LDA") -> dict:
        """Foydalanuvchi o'zi yopadi (masalan hammasi foydada — foydani oladi).

        Har bir ochiq lot JORIY narxda yopiladi; shu signalda ochiq lot qolmasa
        signal ham yakunlanadi. Pul/balans apply_fill orqali hisoblanadi.
        Qaytaradi: {closed, money, price, symbols, r_avg, broker}
        """
        from app.services import live_state

        opens = await self.open_positions(session, user_id=user_id)
        if signal_id is not None:
            opens = [p for p in opens if int(p.signal_id or 0) == int(signal_id)]
        if not opens:
            return {"closed": 0, "money": 0.0, "price": price, "items": []}
        prices: dict = {}
        items: list[dict] = []
        money_total = 0.0
        for pos in opens:
            px = price
            if not px:
                try:
                    px = await live_state.get_price(pos.symbol)
                except Exception:  # noqa: BLE001
                    px = None
            if not px:
                px = float(pos.entry or 0.0)   # narx yo'q — kirish narxida (0 R)
            px = float(px)
            before = float(pos.realized_pnl or 0.0)
            try:
                await self.apply_fill(session, pos, px, portion=0.0, is_final=True,
                                      exit_price_for_remaining=px, reason=reason)
            except Exception as exc:  # noqa: BLE001
                logger.error("[PAPER] qo'lda yopish xatosi #%s: %s", pos.id, exc)
                continue
            money = float(pos.realized_pnl or 0.0) - before
            money_total += money
            prices[pos.symbol] = px
            items.append({"pos_id": int(pos.id), "symbol": pos.symbol,
                          "direction": pos.direction, "lot": float(pos.qty_total or 0) / 100.0,
                          "money": round(money, 2), "price": px,
                          "r": float(pos.r_multiple or 0.0)})
            # v74: brokerda ham yopilsin (agar broker ulangan bo'lsa)
            try:
                await self._broker_close(session, user_id, pos, px)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[BRK] yopishni yuborish: %s", exc)
        # signal yakuni
        sig_ids = {int(p.signal_id) for p in opens if p.signal_id}
        for sid in sig_ids:
            try:
                await self.finish_signal_if_done(session, sid, reason=reason)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[PAPER] signal yakuni: %s", exc)
        r_avg = 0.0
        if items:
            r_avg = sum(float(i.get("r") or 0.0) for i in items) / len(items)
        logger.info("[PAPER] user %s qo'lda yopdi: %d lot, %+.2f$",
                    user_id, len(items), money_total)
        return {"closed": len(items), "money": round(money_total, 2),
                "price": prices.get(opens[0].symbol) if opens else price,
                "prices": prices, "items": items, "r_avg": round(r_avg, 3)}

    async def finish_signal_if_done(self, session: AsyncSession, signal_id: int,
                                    reason: str = "QO'LDA") -> bool:
        """Signalda ochiq lot qolmagan bo'lsa — natijani yozib yakunlaydi."""
        from app.core.enums import SignalStatus
        from app.database.models.signal import Signal
        from app.services.tracker import classify_result

        left = await self.open_positions(session, signal_id=signal_id)
        if left:
            return False
        sig = await session.scalar(select(Signal).where(Signal.id == int(signal_id)))
        if sig is None:
            return False
        info = await self.signal_pnl(session, signal_id)
        r = float(info.get("r_avg") or 0.0)
        sig.is_active = False
        sig.result = classify_result(r)
        sig.r_multiple = round(r, 3)
        sig.status = (SignalStatus.TP3_HIT.value if r > 0.05
                      else SignalStatus.SL_HIT.value if r < -0.05
                      else SignalStatus.EXPIRED.value)
        sig.close_reason = str(reason)[:24]
        sig.close_price = float(info.get("avg_exit") or sig.close_price or 0.0) or None
        sig.closed_at = datetime.now(timezone.utc)
        await session.commit()
        return True

    async def _broker_close(self, session: AsyncSession, user_id: int,
                            pos: PaperPosition, price: float) -> None:
        """Broker ulangan bo'lsa — yopish buyrug'ini navbatga qo'yadi."""
        from app.services import broker as brk
        cfg = await brk.load_cfg(session)
        if not brk.is_ready(cfg) or brk.owner_id(cfg) != int(user_id or 0):
            return
        await brk.enqueue(session, "CLOSE", symbol=pos.symbol, side=pos.direction,
                          lot=round(float(pos.qty_total or 0) / 100.0, 2),
                          signal_id=int(pos.signal_id or 0), price=float(price or 0.0),
                          comment="SINO qolda yopish")

    async def apply_fill(self, session: AsyncSession, pos: PaperPosition,
                         fill_price: float, portion: float, is_final: bool,
                         exit_price_for_remaining: float | None = None,
                         count_trade: bool = True, reason: str = "") -> float:
        """`count_trade` — eski parametr (moslik uchun qoldi); hisob endi oxirgi lot qoidasi."""
        acc = await self.get_account(session, pos.user_id)
        pnl = 0.0

        if portion > 0:
            close_qty = min(pos.qty_total * portion, pos.qty_remaining)
            if pos.direction == Direction.BUY.value:
                pnl += (fill_price - pos.entry) * close_qty
            else:
                pnl += (pos.entry - fill_price) * close_qty
            pos.qty_remaining -= close_qty
            pos.realized_pnl += pnl
            acc.balance += pnl
            acc.total_realized_pnl += pnl

        if is_final:
            if pos.qty_remaining > 0 and exit_price_for_remaining is not None:
                if pos.direction == Direction.BUY.value:
                    pnl_left = (exit_price_for_remaining - pos.entry) * pos.qty_remaining
                else:
                    pnl_left = (pos.entry - exit_price_for_remaining) * pos.qty_remaining
                pos.realized_pnl += pnl_left
                acc.balance += pnl_left
                acc.total_realized_pnl += pnl_left
                pos.qty_remaining = 0.0
            pos.status = PaperStatus.CLOSED.value
            pos.close_price = exit_price_for_remaining or fill_price
            pos.closed_at = datetime.now(timezone.utc)
            pos.balance_after = acc.balance
            if reason:
                try:
                    pos.close_reason = str(reason)[:24]
                except Exception:  # noqa: BLE001
                    pass
            if pos.risk_amount > 0:
                pos.r_multiple = round(pos.realized_pnl / pos.risk_amount, 3)

            # ---- v63: bitim SIGNAL bo'yicha BIR MARTA sanaladi ----
            # Ilgari faqat `count_trade` bayrog'iga bog'liq edi; ba'zi yopilish yo'llarida
            # (TP4/TP5, muddat, flip) hisoblagich umuman oshmay qolardi — "Bitimlar: 0".
            # Endi qoida oddiy: shu signalning OXIRGI ochiq loti yopilganda 1 marta sanaladi.
            try:
                left = await self._open_lots_left(session, pos)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[PAPER] ochiq lotlar sanovi: %s", exc)
                left = 0
            if left == 0:
                acc.total_trades += 1
                r = pos.r_multiple if pos.r_multiple is not None else 0.0
                if r > 0.05:
                    acc.total_wins += 1
                    acc.consecutive_losses = 0
                    acc.paused_by_circuit = False
                elif r < -0.05:
                    acc.consecutive_losses += 1
                    if acc.consecutive_losses >= 3:
                        acc.paused_by_circuit = True
                        logger.warning(
                            "[PAPER] user %s: %d ketma-ket zarar — avto-trade PAUZA "
                            "(signallar davom etadi).", pos.user_id, acc.consecutive_losses
                        )

        await session.commit()
        return pnl

    # ---------- Hisob xulosasi (karta va hisobotlar uchun) ----------
    async def account_summary(self, session: AsyncSession, user_id: int) -> dict:
        """Balans, jami foyda/zarar, g'alaba %, ochiq bitimlar soni."""
        acc = await self.get_account(session, user_id)
        opens = await self.open_positions(session, user_id=user_id)
        pnl = float(acc.balance or 0) - float(acc.initial_balance or 0)
        pct = (pnl / float(acc.initial_balance) * 100.0) if acc.initial_balance else 0.0
        trades = int(acc.total_trades or 0)
        wins = int(acc.total_wins or 0)
        open_signals = 0
        try:
            st = await self.trade_stats(session, user_id)
            trades, wins = int(st["trades"]), int(st["wins"])
            open_signals = int(st["open_signals"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("[PAPER] trade_stats: %s", exc)
        return {
            "balance": float(acc.balance or 0),
            "initial": float(acc.initial_balance or 0),
            "pnl": pnl, "pnl_pct": pct,
            "trades": trades, "wins": wins,
            "winrate": (wins / trades * 100.0) if trades else 0.0,
            "open_count": len(opens),
            "open_signals": open_signals or len(opens),
            "losses": max(0, trades - wins),
            "consecutive_losses": int(acc.consecutive_losses or 0),
            "paused": bool(acc.paused_by_circuit),
            "auto_trade": bool(acc.auto_trade_enabled),
        }

    async def signal_pnl(self, session: AsyncSession, signal_id: int,
                         mark_price: float | None = None) -> dict:
        """Bitta signal bo'yicha: lotlar, ochiq/yopiq, jami $ va o'rtacha R.
        mark_price berilsa — ochiq lotlar shu narxda baholanadi."""
        rows = list((await session.execute(
            select(PaperPosition).where(PaperPosition.signal_id == signal_id)
        )).scalars().all())
        realized = 0.0
        unreal = 0.0
        risk_total = 0.0
        open_qty = 0.0
        exit_num = 0.0
        exit_qty = 0.0
        for pos in rows:
            realized += float(pos.realized_pnl or 0.0)
            risk_total += float(pos.risk_amount or 0.0)
            if str(pos.status) == PaperStatus.CLOSED.value and pos.close_price:
                q = float(pos.qty_total or 0.0)
                exit_num += float(pos.close_price) * q
                exit_qty += q
            if str(pos.status) == PaperStatus.OPEN.value and pos.qty_remaining > 0:
                open_qty += float(pos.qty_remaining)
                if mark_price is not None:
                    d = 1.0 if pos.direction == Direction.BUY.value else -1.0
                    unreal += (float(mark_price) - float(pos.entry)) * d * float(pos.qty_remaining)
        total = realized + unreal
        r_avg = (total / risk_total) if risk_total > 0 else 0.0
        return {
            "lots": len(rows), "realized": realized, "unrealized": unreal,
            "total_pnl": total, "r_avg": r_avg, "open_qty": open_qty,
            "risk_total": risk_total,
            # yopilgan lotlarning o'rtacha chiqish narxi (lot hajmiga qarab)
            "avg_exit": (exit_num / exit_qty) if exit_qty > 0 else None,
        }

    # ---------- Boshqaruv ----------
    async def set_balance(self, session: AsyncSession, user_id: int,
                          amount: float) -> PaperAccount:
        acc = await self.get_account(session, user_id)
        acc.balance = amount
        acc.initial_balance = amount
        acc.total_realized_pnl = 0.0
        acc.consecutive_losses = 0
        acc.paused_by_circuit = False
        await session.commit()
        await session.refresh(acc)
        return acc

    async def toggle_auto_trade(self, session: AsyncSession,
                                user_id: int) -> tuple[bool, PaperAccount]:
        acc = await self.get_account(session, user_id)
        if acc.auto_trade_enabled:
            acc.auto_trade_enabled = False
        else:
            acc.auto_trade_enabled = True
            acc.consecutive_losses = 0
            acc.paused_by_circuit = False
        await session.commit()
        await session.refresh(acc)
        return acc.auto_trade_enabled, acc
