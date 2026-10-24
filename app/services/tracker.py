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
    """v80: kuchli momentum bormi (app.engine.momentum bahosi)."""
    try:
        from app.engine import momentum
        return momentum.is_strong(df, buy)
    except Exception:  # noqa: BLE001
        return False


def _sl_reason(p) -> str:
    """v80: lot qanday yopilgani — +4R qulf bo'lsa «TP4»."""
    if int(getattr(p, "stage", 0) or 0) == 13:
        return "TP4"
    if getattr(p, "sl_moved_to_be", False):
        return "BE"
    return "SL"


def _be_sl_target(signal) -> float:
    """v125 (USER QOIDASI): TP1 tekkanda Lot2 ning yangi stopi — <b>TP1</b>
    (ilgari BE = kirish narxi edi; user "TP1 ga ko'chirilishi kerak" dedi).
    Xavfsizlik: TP1 yo'q/noto'g'ri bo'lsa — kirish narxi (BE) qaytariladi."""
    entry = float(getattr(signal, "entry", 0.0) or 0.0)
    tp1 = 0.0
    try:
        from app.engine.risk import norm_safe_targets as _NST125
        tp1 = float(_NST125(signal)[0] or 0.0)
    except Exception:  # noqa: BLE001
        tp1 = float(getattr(signal, "tp1", 0.0) or 0.0)
    if tp1 <= 0 or entry <= 0:
        return entry
    d = str(getattr(signal, "direction", "") or "").upper()
    # BUY: TP1 kirishdan YUQORI bo'lishi; SELL: PAST bo'lishi kerak.
    if (d == "BUY" and tp1 > entry) or (d == "SELL" and tp1 < entry):
        return tp1
    return entry


def _is_runner(p) -> bool:
    return int(getattr(p, "stage", 0) or 0) >= 10


class SignalTracker:
    def __init__(self, paper_engine: PaperEngine, settings: Settings) -> None:
        self._paper = paper_engine
        self._settings = settings
        # v81: signal bo'yicha oxirgi tekshirilgan sham vaqti — o'tkazib
        # yuborilgan shamlarni ham hisobga olish uchun (xatolik manbai edi).
        self._last_bar: dict[int, object] = {}
        # v81: jonli (tick) tekshiruvlar soni — diagnostika uchun
        self.live_checks = 0

    def _bars_to_check(self, signal, df: pd.DataFrame) -> list[int]:
        """Oxirgi tekshiruvdan keyingi yopiq shamlarning POZITSIYALARI.

        v81: bot qayta ishga tushsa yoki sham oqimi uzilsa, o'tkazib
        yuborilgan shamlardagi SL/TP ham hisobga olinadi (ilgari yo'qolardi).
        """
        try:
            n = len(df)
            if n == 0:
                return []
            if "open_time" not in df.columns:
                return [n - 1]
            last_seen = self._last_bar.get(int(signal.id))
            if last_seen is None:
                return [n - 1]
            pos = []
            for i in range(n):
                try:
                    if df.iloc[i]["open_time"] > last_seen:
                        pos.append(i)
                except Exception:  # noqa: BLE001
                    continue
            if not pos:
                return []
            return pos[-240:]     # cheksiz catch-up bo'lmasin
        except Exception:  # noqa: BLE001
            return [len(df) - 1]

    def _mark_bar(self, signal, df: pd.DataFrame) -> None:
        try:
            if "open_time" in df.columns and len(df):
                self._last_bar[int(signal.id)] = df.iloc[-1]["open_time"]
                if len(self._last_bar) > 800:
                    self._last_bar.clear()
        except Exception:  # noqa: BLE001
            pass

    async def update_for_candle(self, session: AsyncSession, signal: Signal,
                                df: pd.DataFrame, notifier=None) -> None:
        """Yopiq sham(lar) bo'yicha kuzatish — v81: o'tkazib yuborilgan
        shamlarni ham tartib bilan tekshiradi (SL/TP o'tib ketmaydi)."""
        try:
            pos = self._bars_to_check(signal, df)
            if not pos:
                return
            for i in pos:
                # momentum uchun oldingi shamlar ham beriladi (v80 qoidasi),
                # SL/TP tekshiruvi esa AYNAN shu shamning high/low bo'yicha.
                win = df.iloc[max(0, i - 40): i + 1]
                await self._process(session, signal, win, notifier)
                try:
                    await session.refresh(signal)
                except Exception:  # noqa: BLE001
                    pass
                if not bool(getattr(signal, "is_active", True)):
                    break
            self._mark_bar(signal, df)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Tracker xatosi signal #%s: %s", signal.id, exc)

    async def live_tick(self, session: AsyncSession, signal: Signal, price: float,
                        df: pd.DataFrame | None = None, notifier=None) -> bool:
        """v81: JONLI narx bo'yicha tekshiruv (sham yopilishini kutmaysiz).

        Narx SL yoki TP darajasidan o'tsa — shu yerda yopiladi (broker kabi).
        Momentum qarori uchun yaqin shamlardan foydalanadi.
        """
        try:
            px = float(price or 0)
            if px <= 0:
                return False
            base = None
            if df is not None and len(df):
                base = df.tail(30).copy()
            if base is None or len(base) == 0:
                import pandas as _pd
                base = _pd.DataFrame(
                    [{"open": px, "high": px, "low": px, "close": px, "volume": 0.0}]
                )
            else:
                r = base.iloc[-1].to_dict()
                r["high"] = max(float(r.get("high", px)), px)
                r["low"] = min(float(r.get("low", px)), px)
                r["close"] = px
                base.iloc[-1] = r
            self.live_checks += 1
            await self._process(session, signal, base, notifier)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("[TRACKER] jonli tekshiruv #%s: %s",
                           getattr(signal, "id", "?"), exc)
            return False

    # ================= v84: KIRISH NUQTASI (kutish / bekor) =================
    async def entry_tick(self, session: AsyncSession, signal: Signal, price: float,
                         notifier=None) -> str:
        """Kutayotgan signalni tekshiradi: narx zonaga keldi → ochadi,
        muddat tugadi → BEKOR qiladi (savdo ochilmaydi).

        Qaytaradi: "filled" | "expired" | "wait" | "skip"
        """
        from app.engine import entry as EN
        from app.services import entry_settings as ES
        if not EN.is_waiting(signal):
            return "skip"
        px = float(price or 0)
        # muddat tugagan bo'lsa narx bor-yo'qligidan qat'i nazar BEKOR qilamiz
        _exp = getattr(signal, "entry_expires_at", None)
        if _exp is None:
            try:
                vals0 = await ES.load(session)
                _exp = EN.deadline(int(vals0.get(ES.K_WAIT, 60) or 60),
                                   now=(getattr(signal, "created_at", None)
                                        or datetime.now(timezone.utc)))
            except Exception:  # noqa: BLE001
                _exp = None
        if EN.expired(_exp) and px <= 0:
            _expired_now = True
        else:
            _expired_now = False
        d = str(signal.direction or "")
        buy = d.upper() == "BUY"
        lo = float(signal.entry_low or 0)
        hi = float(signal.entry_high or 0)
        # v122: "qaytish rejimi" (SIGNAL_UND) — narx SL tomondan zona
        # ICHIGA qaytishini kutmokda; logika teskari zona tekshiruvi bilan.
        _und122 = str(getattr(signal, "entry_mode", "") or "") == "SIGNAL_UND"
        if _und122:
            ok, fill = EN.zone_hit_reverse(d, lo, hi, px)
        else:
            ok, fill = EN.zone_hit(d, lo, hi, px)
        if not ok and _expired_now:
            ok, fill = False, 0.0
        if ok:
            fill = float(fill)
            before = float(signal.entry or 0)
            signal.entry = round(fill, 2)
            signal.entry_low = signal.entry_high = round(fill, 2)
            # v99: zona fill dan keyin darajalarni YANGI kirishga tekshiramiz
            from app.engine.sizing import resanitize_levels as _RS99
            _rs = _RS99(d, float(signal.entry), signal.sl, signal.tp1,
                        signal.tp2, signal.tp3, signal.entry_tps_src,
                        signal.symbol)
            if not _rs["ok"]:
                signal.entry_status = "CANCELLED"
                signal.status = SignalStatus.CANCELLED.value
                signal.is_active = False
                signal.close_reason = ("RAD: " + _rs["why"])[:96]
                signal.closed_at = datetime.now(timezone.utc)
                await session.commit()
                logger.warning("[TRACKER] #%s v99 RAD (zona fill): %s",
                               signal.id, _rs["why"])
                # v124 (USER): RAD bekor ham JIM O'TMAYDI — karta "KUTILMOQDA"
                # deb sobit qolmasligi uchun aniq xabar yuboramiz.
                if notifier:
                    try:
                        _bd = "BUY" if buy else "SELL"
                        await notifier.send_event(
                            f"\u274C <b>№{signal.id} {signal.symbol} {_bd}</b> — "
                            f"kirish BEKOR qilindi:\n"
                            f"   {_rs['why'][:70]}\n"
                            f"   (narx zona dan o'tib ketgan / SL teskari bo'lib "
                            f"qolgan — quvish yo'q)")
                    except Exception as _exc_r:  # noqa: BLE001
                        logger.warning("[TRACKER] #%s RAD bekor xabari: %s",
                                       signal.id, _exc_r)
                return "cancelled"
            signal.sl = float(_rs["sl"])
            signal.tp1 = float(_rs["tp1"])
            signal.tp2 = float(_rs["tp2"])
            signal.tp3 = float(_rs["tp3"])
            signal.entry_tps_src = _rs["tps_src"]
            signal.entry_status = "FILLED"
            signal.entry_note = (f"{signal.entry_note or ''} \u00B7 kirdi "
                                 f"{fill:,.2f}").strip()[:96]
            # v109: TP lar resanitize'da AQlli qayta hisoblandi (R345 → 3R/4R/5R,
            # kanal TP lari saqlanadi). R345 da tps_extra ham yangilanadi.
            try:
                if str(getattr(signal, "entry_tps_src", "") or "") == "R345":
                    import json as _j109
                    signal.tps_extra = _j109.dumps(
                        [float(signal.tp1), float(signal.tp2), float(signal.tp3)])
            except Exception:  # noqa: BLE001
                pass
            await session.commit()
            logger.info("[TRACKER] #%s KIRDI %.2f (reja %.2f)", signal.id, fill, before)
            # pozitsiyalar endi ochiladi (har bir hisobga alohida, risk % bo'yicha)
            n_open = 0
            try:
                from app.services.channel_inbox import _users_for_signal
                users = await _users_for_signal(session, self._settings)
                n_open = await self._paper.open_for_signal(session, signal, users)
            except Exception as exc:  # noqa: BLE001
                logger.error("[TRACKER] kirishda ochish: %s", exc)
            if notifier:
                try:
                    _d = "BUY" if buy else "SELL"
                    from app.engine.risk import last_tp_of_signal as _LTB
                    _ltb = float(_LTB(signal) or signal.tp1 or 0)
                    _pct = float(ES.cached().get(ES.K_WAIT, 60))
                    await notifier.send_event(
                        f"\u2705 <b>KIRDI: {signal.symbol} {_d}</b> @ "
                        f"<b>{format_price(signal.entry)}</b>\n"
                        f"   Zona: {format_price(lo)} \u2013 {format_price(hi)} "
                        f"({signal.entry_note or ''})\n"
                        f"   \U0001F6D1 Stop {format_price(signal.sl)} \u00B7 "
                        f"Oxirgi TP {format_price(_ltb)} ({int(_pct)} daq kutildi)")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[TRACKER] kirish xabari: %s", exc)
            return "filled"
        # narx hali kelmadi — muddatni tekshiramiz
        if px <= 0 and not _expired_now:
            return "wait"
        if _expired_now or EN.expired(_exp):
            try:
                vals = await ES.load(session)
                wait_min = int(vals.get(ES.K_WAIT, 60) or 60)
            except Exception:  # noqa: BLE001
                wait_min = 60
            signal.entry_status = "CANCELLED"
            signal.status = SignalStatus.CANCELLED.value
            signal.is_active = False
            signal.close_reason = EN.CANCEL_TEXT
            signal.closed_at = datetime.now(timezone.utc)
            if not signal.entry_skip:
                if _und122:
                    signal.entry_skip = ("kun oxiri — zona qaytmadi "
                                         f"({lo:,.2f}-{hi:,.2f}) (v122)")[:160]
                else:
                    signal.entry_skip = (f"narx {wait_min} daqiqada zonaga "
                                         f"kelmadi ({lo:,.2f}-{hi:,.2f})")[:160]
            await session.commit()
            logger.info("[TRACKER] #%s KIRISH BO'LMADI (muddat %s daq)", signal.id, wait_min)
            # v124 (USER): karta chiqarilgan WAIT signalining bekor qilinishi
            # JIM O'TMAS. v94 "karta yuborilmaydi" qoidasi faqat foydalanuvchi
            # HECH KO'RMAGAN bekorlar uchun edi; karta ko'rsatilgan signal
            # eski kartani sobit "KUTILMOQDA" holatida qoldirib yo'q bo'lardi.
            if notifier:
                try:
                    _bd = "BUY" if buy else "SELL"
                    if _und122:
                        _mud = "Toshkent kuni oxiri"
                    else:
                        _mud = f"{wait_min} daqiqa"
                    await notifier.send_event(
                        f"\u23F0 <b>№{signal.id} {signal.symbol} {_bd}</b> — "
                        f"kirish BEKOR qilindi:\n"
                        f"   {_mud} ichida narx zona "
                        f"{format_price(lo)}\u2013{format_price(hi)} ga kelmadi.\n"
                        f"   \u26A0\uFE0F TELEGRAMDAGI ESKI 'KUTISH' KARTASI "
                        f"ENDI AMALDA EMAS \u2014 yangilash texnik imkonsiz, "
                        f"bu xabar bekorlik dalilidir.")
                except Exception as _exc_b:  # noqa: BLE001
                    logger.warning("[TRACKER] #%s bekor xabari: %s", signal.id, _exc_b)
            return "expired"
        return "wait"

    async def _fill(self, session, pos, price: float, *,
                    count_trade: bool = True, reason: str = "") -> None:
        await self._paper.apply_fill(
            session, pos, price, portion=0.0, is_final=True,
            exit_price_for_remaining=price, count_trade=count_trade, reason=reason,
        )
        # v125: REAL brokerda ham yopish — natarj (SL/TP/TP1/TP2) sabablarini
        # broker o'zi bajaradi (SL/TP ochishda yozilgan); faqat "VAQT TUGADI /
        # RAD / BEKOR" kabi vaqt/xato yopilishlarini biz yuboramiz.
        # (Ilgari bu umuman yo'q edi — real pozitsiya oxirgacha qolib ketardi!)
        try:
            _r = str(reason or "")
            native = _r[:4] in ("TP1_", "TP2_") or _r in ("SL", "BE", "TP4")
            if _r and not native:
                from app.services import broker as _brkf
                _cfgf = await _brkf.load_cfg(session)
                if _brkf.is_ready(_cfgf) and _brkf.owner_id(_cfgf) == int(pos.user_id or 0):
                    _tagf = "Lot1" if int(getattr(pos, "stage", 0) or 0) < 10 else "Lot2"
                    await _brkf.enqueue(
                        session, "CLOSE", symbol=pos.symbol, side=pos.direction,
                        lot=round(float(pos.qty_total or 0) / 100.0, 2),
                        signal_id=int(getattr(pos, "signal_id", 0) or 0),
                        price=float(price or 0.0), comment="SINO " + _tagf)
                    logger.info("[BRK] auto-yopish navbatga #%s %s", pos.signal_id, _tagf)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[BRK] auto-yopish enqueue: %s", exc)

    @staticmethod
    def _px(bar, level: float, buy: bool, kind: str) -> float:
        """v81: GAP himoyasi.

        Sham darajadan nariga ochilib ketgan bo'lsa, buyurtma darajada emas,
        shamning OCHILISH narxida bajariladi (real brokerdagidek).
        """
        try:
            op = float(bar["open"])
        except Exception:  # noqa: BLE001
            return float(level)
        lv = float(level)
        # v82: TP — LIMIT buyurtma: har doim AYNAN TP narxida bajariladi
        # (narx nariga sakrasa ham ortiqcha foyda yozilmaydi — brokerdagidek).
        # SL — bozor buyurtmasi: gap bo'lsa ochilish narxida (zarar ko'proq).
        if kind == "sl":
            if buy and op < lv:
                return op
            if (not buy) and op > lv:
                return op
        return lv

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
                _hadp = False
                try:
                    _hadp = bool(await self._paper.any_positions(
                        session, signal.id))
                except Exception:  # noqa: BLE001
                    _hadp = True
                if notifier and _hadp:
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
                # v84: kutayotgan (WAIT) signalni muddat bo'yicha entry_tick yopadi
                try:
                    from app.engine import entry as _EN5
                    if _EN5.is_waiting(sig):
                        continue
                except Exception:  # noqa: BLE001
                    pass
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

        # v99: DARAJALAR HIMOYASI — SL kirishning teskari tomonida bo'lsa
        # (eski/nosog'lom signal), pozitsiyalarni kirish narxida yopamiz
        # (0 R, hisob ifloslanmaydi) va signalni BEKOR qilamiz.
        try:
            from app.engine.sizing import levels_side_ok as _LSO99
            if not _LSO99(signal.direction, signal.entry, signal.sl):
                for p in list(positions):
                    try:
                        await self._fill(session, p, float(signal.entry),
                                         reason="RAD_DARAJA")
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("[TRACKER] rad fill: %s", exc)
                signal.status = SignalStatus.CANCELLED.value
                signal.is_active = False
                signal.close_reason = "RAD: darajalar kirishga mos emas (v99)"
                signal.closed_at = datetime.now(timezone.utc)
                await session.commit()
                logger.warning("[TRACKER] #%s v99 RAD (tick): SL teskari "
                               "tomonda (entry=%.2f sl=%.2f)", signal.id,
                               float(signal.entry or 0), float(signal.sl or 0))
                return
        except Exception as exc:  # noqa: BLE001
            logger.warning("[TRACKER] v99 side guard: %s", exc)

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

        # v109: +4R/+5R zinapoyasi olib tashlandi — 2 lot oxirgi TP da yopiladi

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
                    await self._fill(session, p, self._px(last, sl, buy, "sl"),
                                     count_trade=not counted,
                                     reason=_sl_reason(p))
                    counted = True
                    sl_closed.append(p)
                except Exception as exc:  # noqa: BLE001
                    logger.error("[TRACKER] SL fill: %s", exc)
            else:
                still.append(p)

        if sl_closed and notifier:
            locked = [p for p in sl_closed if int(getattr(p, "stage", 0) or 0) == 13]
            be_only = all(getattr(p, "sl_moved_to_be", False) for p in sl_closed) and not locked
            word = ("−1R STOP" if not be_only and not locked
                    else ("🔒 +4R qulfda yopildi (momentum so'ndi)" if locked
                          else "🔒 TP1 stopda yopildi (foyda qulflangan)"))
            no = f"№{signal.signal_no} " if getattr(signal, "signal_no", None) else ""
            await notifier.send_event(
                f"🛑 <b>{no}{signal.symbol}</b> — {word} ({len(sl_closed)} lot) "
                f"@ {format_price(sl_closed[0].sl)}"
                + ("  · Lot 2 shartiga muvofiq: 4R dan past bo'lmadi." if locked else "")
            )

        positions = still
        if not positions:
            locked = [p for p in sl_closed if int(getattr(p, "stage", 0) or 0) == 13]
            be = any(getattr(p, "sl_moved_to_be", False) for p in sl_closed)
            if not be:
                signal.status = SignalStatus.SL_HIT.value
            elif locked:
                signal.status = SignalStatus.TP4_HIT.value       # v80: 4R qulf
            await self._finish_signal(
                session, signal, notifier,
                # v125: SL TP1 ga surilgan bo'lsa — yopilish narxi ham TP1 (+1R),
                # original SL emas. Bu yordamchi holda eski "breakeven"dan faqat
                # yaqqol foydaga o'zgaradi.
                exit_price=float(sl_closed[0].sl) if be else float(signal.sl),
                r_hint=None if locked else (1.0 if be else -1.0),
            )
            return

        # 2) TP1 himoya — v125 (USER QOIDASI SL→TP1): TP1 teganda qolgan lot
        #    (Lot2) stopi TP1 ga sudraladi — foyda UNTILEng +1R dan pasaymaydi.
        #    (v116 da BE — kirish narxiga surilardi; user endi aniq TP1 ni so'radi.)
        if any(p.stage in (0, 10) for p in positions) and hit_above(float(signal.tp1)):
            _sl125 = _be_sl_target(signal)
            for p in positions:
                if p.stage in (0, 10):
                    p.sl = _sl125
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
                _word125 = ("TP1 da qulflangan" if _sl125 != float(signal.entry)
                            else "kirishda (himoya)")
                await notifier.send_event(
                    f"🔒 <b>{no}{signal.symbol}</b> — <b>TP1 tegndi</b>: Lot 2 stopi "
                    f"{_word125} — foyda {format_price(_sl125)} dan pastga tushmaydi."
                )
            logger.info("[TRACKER] #%s TP1 himoya — Lot2 SL = %.2f", signal.id, _sl125)
            # v125: REAL broker uchun ham — Lot2 stopini TP1 ga o'zgartirish (MODIFY)
            try:
                from app.services import broker as _brk125
                _cfg125 = await _brk125.load_cfg(session)
                if _brk125.is_ready(_cfg125) and _sl125 != float(signal.entry):
                    await _brk125.enqueue(
                        session, "MODIFY", symbol=str(getattr(signal, "symbol", "") or ""),
                        side=str(getattr(signal, "direction", "") or "BUY"),
                        sl=float(_sl125), comment="SINO Lot2",
                        signal_id=int(getattr(signal, "id", 0) or 0))
                    logger.info("[BRK] #%s Lot2 MODIFY navbatga (SL=%.2f)",
                                signal.id, _sl125)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[BRK] MODIFY yuborish: %s", exc)

        # 3) v116 NORM-SAFE foyda rejimi (YANGI USER QOIDASI — v109 bekor):
        #    Lot 1 — TP1 da yopiladi (normal foyda qulflanadi, mikro emas);
        #    Lot 2 — TP2 da (yagona TP bo'lsa — o'sha TP da);
        #    TP1 da ikkala lot stopi kirishga suriladi (BE, xavfsiz — yuqorida).
        #    "Juda kam foydada ham yopmasin, hirs bilan oxirigacha ham emas" —
        #    o'rtacha maqsad ~100 pip/kun uchun barqaror sxema.
        _t1_116, _t2_116 = 0.0, 0.0
        try:
            from app.engine.risk import norm_safe_targets as _NST116
            _t1_116, _t2_116 = _NST116(signal)
        except Exception:  # noqa: BLE001
            _t1_116 = float(getattr(signal, "tp1", 0.0) or 0.0)
            _t2_116 = float(getattr(signal, "tp2", 0.0) or 0.0) or _t1_116
        if positions and _t1_116 > 0 and hit_above(_t1_116):
            lot1 = [p for p in positions
                    if int(getattr(p, "stage", 0) or 0) < 10]
            if lot1:
                _px1 = self._px(last, _t1_116, buy, "tp")
                first = True
                for p in lot1:
                    try:
                        await self._fill(session, p, _px1, count_trade=first,
                                         reason="TP1_NORM")
                        first = False
                    except Exception as exc:  # noqa: BLE001
                        logger.error("[TRACKER] TP1 norm fill: %s", exc)
                positions = [p for p in positions if p not in lot1]
                if str(signal.status) not in (
                    SignalStatus.TP2_HIT.value, SignalStatus.TP3_HIT.value,
                    SignalStatus.TP4_HIT.value,
                ):
                    signal.status = SignalStatus.TP1_HIT.value
                await session.commit()
                no = (f"№{signal.signal_no} "
                      if getattr(signal, "signal_no", None) else "")
                if notifier:
                    await notifier.send_event(
                        f"\U0001F3AF <b>{no}{signal.symbol}</b> — <b>Lot 1 TP1 da "
                        f"yopildi</b> @ {format_price(_t1_116)}."
                        + (" Lot 2 davom etadi — stop kirishda (xavfsiz)."
                           if positions else "")
                    )
                logger.info("[TRACKER] #%s Lot1 TP1 NORM %.2f (%d lot)",
                            signal.id, _t1_116, len(lot1))
                if not positions:
                    await self._finish_signal(session, signal, notifier,
                                              exit_price=_t1_116)
                    return
        if positions and _t2_116 > 0 and hit_above(_t2_116):
            _px2 = self._px(last, _t2_116, buy, "tp")
            for p in positions:
                try:
                    await self._fill(session, p, _px2, count_trade=False,
                                     reason="TP2_SAFE")
                except Exception as exc:  # noqa: BLE001
                    logger.error("[TRACKER] TP2 safe fill: %s", exc)
            signal.status = (SignalStatus.TP2_HIT.value if _t2_116 != _t1_116
                             else SignalStatus.TP1_HIT.value)
            await session.commit()
            no = (f"№{signal.signal_no} "
                  if getattr(signal, "signal_no", None) else "")
            if notifier:
                await notifier.send_event(
                    f"\U0001F3C1 <b>{no}{signal.symbol}</b> — <b>Lot 2 TP2 da "
                    f"yopildi</b> @ {format_price(_t2_116)}. "
                    "Signal yakunlandi (NORM-SAFE)."
                )
            logger.info("[TRACKER] #%s Lot2 TP2 SAFE %.2f", signal.id, _t2_116)
            await self._finish_signal(session, signal, notifier,
                                      exit_price=_t2_116)
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
        # v103: SAVDO OCHILMAGAN bo'lsa NATIJA kartasi YUBORILMAYDI
        # (bekor/rad/muddat kartalari userga spam qilmasligi kerak).
        _had = False
        try:
            _had = bool(await self._paper.any_positions(session, signal.id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[TRACKER] v103 positions: %s", exc)
            _had = True
        _rs0 = str(reason or "")
        _silent = (not _had) and (
            str(result or "").upper() in ("CANCELLED", "BREAKEVEN")
            or _rs0.startswith("BEKOR") or _rs0.startswith("RAD")
            or _rs0.startswith("VAQT"))
        if notifier and not _silent:
            try:
                await session.refresh(signal)
                await notifier.send_result(signal)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[TRACKER] result: %s", exc)
        elif notifier and _silent:
            logger.info("[TRACKER] v103 #%s karta yo'q (savdo ochilmagan, "
                        "sabab: %s)", signal.id, _rs0[:40])
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
