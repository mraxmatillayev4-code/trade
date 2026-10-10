"""v86: OLTIN (XAUUSD) SNIPER MODULI — SNR + ICT + SMC.

Algoritm: `app/engine/sniper.py` (sof matematika, backtestda ham shu ishlaydi).
Bu modul esa uni BOTGA ulaydi:

  * `/sniper` tugmasi/komandasi bilan YOQILADI yoki O'CHIRILADI;
  * v93: KATTA TIMEFRAME (1d / 4h / 1h) KUZATILADI, keyin BITTA tahlil
    M1 da qilinadi va savdo ham M1 da ochiladi (oldingi 5m rejim eskirgan);
  * yoqilganda har 60 sekundda XAUUSD M1 shamlarini skanerlaydi;
  * setup topilsa SIGNAL yasaydi (lot, SL, TP1/TP2 tayyor) va kartani yuboradi;
  * signal ALOHIDA $50 hisobda ochiladi (user_id = -1 «sniper» hisobi),
    boshqa signallar/allarka aralashmaydi.

Setup shartlari (hammasi birga bo'lishi shart):
  1) 1h yo'nalishi aniq (EMA50 vs EMA200 + narx tomoni);
  2) narx SNR darajasidan supurib o'tib qaytgan (ICT stop hunt);
  3) supurishdan keyin kuchli impuls (displacement);
  4) FVG yoki Order Block zonasi bor -> KIRISH ZONASI;
  5) ball >= 6.0; SL/TP narxda hisoblanadi.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.core.logging import get_logger

logger = get_logger(__name__)

SNIPER_USER_ID = -1                 # $50 hisob (Telegram id'lar musbat)
SNIPER_BALANCE = 50.0
K_ENABLED = "sniper_enabled"
SYMBOL = "XAUUSDT"
# v93: KATTA TF larda KUZATILADI -> BITTA tahlil M1 da -> SAVDO M1 da
TF = "1m"                           # savdo timeframi (signal shu TF da yoziladi)
HTF_FRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")   # kuzatiladigan ramzalar
HTF_LIMIT = {"1m": 400, "5m": 300, "15m": 250, "1h": 300, "4h": 300, "1d": 200}
DATA_TTL_S = 45.0                   # ma'lumot keshi (sekund) — API ni ortiqcha urmaymiz
SCAN_SECONDS = 60
# v93/v94: M1 MEZONLARI — halol backtest (2026-10-03..05, 32 soat, kelajak
# ma'lumotisiz, BOZOR narxida kirish bilan):
#   zona-kutish rejasi (v93)   -> 41 setup WR 80.5%  +2.2R   (kirishlar ko'pi
#                                 bajarilmadi — "KIRISH BO'LMADI" kartalari)
#   +impuls 0.7 ATR            -> 39 setup WR 82.1%  +3.9R
#   +killzone (London/NY)      -> 15 setup WR 93.3%  +3.9R   <- v94 TANLANDI
#   (ball 6.5/7.0/7.5 da bir xil — demak halqalar filtr sifatida ishlaydi)
M1_SCORE_MIN = 7.0          # M1 setup uchun minimal ball
M1_DISP_MIN = 0.7           # v94: impuls sham tanasi >= 0.7 ATR (kuchsiz impuls = yo'q)
M1_KILLZONE = True          # v94: faqat London/NY seansida (oltin shunda yuradi)
COOLDOWN_S = 900            # ikki sniper signal orasida kamida 15 daqiqa
DAILY_MAX = 8               # bir kunda ko'pi bilan shuncha sniper signal
_CACHE = {"on": None}
_LAST_SIG_TS = {"t": None}
_DATA: dict = {"ts": 0.0, "frames": {}, "err": ""}
# v93: OXIRGI SKAN DIAGNOSTIKASI — /sniper da "nega signal yo'q" ko'rinadi
LAST: dict = {"ts": None, "scans": 0, "signals": 0, "bias": "", "bias_txt": "",
              "price": None, "why": "", "frames": "", "err": "", "best_score": 0.0,
              "htf_levels": 0, "m1_candles": 0}


# ----------------------------- sozlamalar -----------------------------
async def is_enabled(session) -> bool:
    if _CACHE["on"] is not None:
        return bool(_CACHE["on"])
    return await refresh(session)


async def refresh(session) -> bool:
    v = True
    try:
        from sqlalchemy import select
        from app.database.models.app_setting import AppSetting
        row = await session.scalar(
            select(AppSetting).where(AppSetting.key == K_ENABLED)
        )
        if row is not None and (row.value or "").strip() != "":
            v = (row.value or "").strip().lower() in ("1", "true", "on", "ha", "yoniq")
    except Exception as exc:  # noqa: BLE001
        logger.debug("[SNIPER] holat: %s", exc)
    _CACHE["on"] = v
    return v


async def set_enabled(session, on: bool) -> bool:
    v = bool(on)
    try:
        from sqlalchemy import select
        from app.database.models.app_setting import AppSetting
        row = await session.scalar(
            select(AppSetting).where(AppSetting.key == K_ENABLED)
        )
        if row is None:
            session.add(AppSetting(key=K_ENABLED, value="1" if v else "0"))
        else:
            row.value = "1" if v else "0"
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[SNIPER] saqlash: %s", exc)
    _CACHE["on"] = v
    return v


# ----------------------------- $50 hisob -----------------------------
async def ensure_account(session, *, reset: bool = False):
    """Sniper uchun alohida $50 virtual hisob (user_id=-1)."""
    from sqlalchemy import select
    from app.database.models.paper import PaperAccount
    acc = await session.scalar(
        select(PaperAccount).where(PaperAccount.user_id == SNIPER_USER_ID)
    )
    if acc is None:
        acc = PaperAccount(user_id=SNIPER_USER_ID, name="sniper",
                           initial_balance=SNIPER_BALANCE, balance=SNIPER_BALANCE,
                           auto_trade_enabled=True)
        session.add(acc)
        await session.commit()
        await session.refresh(acc)
        logger.info("[SNIPER] $50 hisob yaratildi")
    elif reset:
        acc.balance = SNIPER_BALANCE
        acc.initial_balance = SNIPER_BALANCE
        acc.total_realized_pnl = 0.0
        await session.commit()
    return acc


async def account_stats(session) -> dict:
    from sqlalchemy import func, select
    from app.core.enums import PaperStatus
    from app.database.models.paper import PaperPosition
    acc = await ensure_account(session)
    rows = (await session.execute(
        select(PaperPosition).where(PaperPosition.user_id == SNIPER_USER_ID)
    )).scalars().all()
    closed = [p for p in rows if p.status == PaperStatus.CLOSED.value]
    openp = [p for p in rows if p.status == PaperStatus.OPEN.value]
    wins = sum(1 for p in closed if float(p.realized_pnl or 0) > 0)
    losses = sum(1 for p in closed if float(p.realized_pnl or 0) < 0)
    pnl = float(acc.balance or 0) - float(acc.initial_balance or 0)
    wr = (wins / len(closed) * 100.0) if closed else 0.0
    pf_num = sum(float(p.realized_pnl or 0) for p in closed if float(p.realized_pnl or 0) > 0)
    pf_den = -sum(float(p.realized_pnl or 0) for p in closed if float(p.realized_pnl or 0) < 0)
    return {
        "balance": float(acc.balance or 0), "initial": float(acc.initial_balance or 0),
        "pnl": round(pnl, 2), "trades": len(closed), "open": len(openp),
        "wins": wins, "losses": losses, "wr": round(wr, 1),
        "pf": round(pf_num / pf_den, 2) if pf_den > 0 else None,
        "on": await is_enabled(session),
    }


# ----------------------------- ma'lumot (HTF + M1) -----------------------------
async def fetch_frames(app=None) -> dict:
    """v93: OLTIN shamlarini O'ZI oladi (1m/5m/15m/1h/4h/1d).

    Nega o'zi: bot sozlamasidagi `timeframes` ro'yxatida 1m bo'lmasligi mumkin
    (standart "5m,15m,1h,4h") — shunda sniper umuman ishlamas edi. Endi u o'z
    ma'lumotini MEXC REST dan oladi va 45 sekund keshlaydi.
    """
    import time as _t
    now = _t.time()
    if _DATA["frames"] and (now - float(_DATA["ts"] or 0)) < DATA_TTL_S:
        return dict(_DATA["frames"])
    frames: dict = {}
    err = ""
    rest = None
    try:
        from app.market.gold_rest import GoldRest
        rest = GoldRest()
        for tf in HTF_FRAMES:
            try:
                df = await rest.get_klines(SYMBOL, tf, int(HTF_LIMIT.get(tf, 300)))
                if df is not None and len(df):
                    frames[tf] = df
            except Exception as exc:  # noqa: BLE001
                err = f"{tf}: {type(exc).__name__}: {exc}"
                logger.warning("[SNIPER] %s sham olinmadi: %s", tf, exc)
    except Exception as exc:  # noqa: BLE001
        err = f"rest: {type(exc).__name__}: {exc}"
        logger.warning("[SNIPER] REST: %s", exc)
    finally:
        if rest is not None:
            try:
                await rest.close()
            except Exception:  # noqa: BLE001
                pass
    # zaxira: bot keshida bor ramkalarni ham olamiz (1m bo'lmasa ham 5m/1h ishlaydi)
    if app is not None:
        try:
            for tf in HTF_FRAMES:
                if tf in frames:
                    continue
                df = app.candles.get_df(SYMBOL, tf)
                if df is not None and len(df):
                    frames[tf] = df
        except Exception as exc:  # noqa: BLE001
            logger.debug("[SNIPER] kesh zaxira: %s", exc)
    if frames:
        _DATA["ts"] = now
        _DATA["frames"] = frames
        _DATA["err"] = err
    return frames


async def scan_once(app) -> int:
    """Bitta skan: setup topilsa signal yasaydi. Nechta signal yaratildi."""
    from datetime import datetime, timezone as _tz
    from app.services import lot_settings as _LS
    from app.engine import sniper as SN
    session = None
    LAST["ts"] = datetime.now(_tz.utc)
    LAST["scans"] = int(LAST.get("scans") or 0) + 1
    try:
        from app.database.session import async_session_factory
        async with async_session_factory() as session:
            if not await is_enabled(session):
                LAST["why"] = "sniper o'chirilgan (yoniq tugmasini bosing)"
                return 0
            frames = await fetch_frames(app)
            d1m = frames.get("1m")
            d5m = frames.get("5m")
            d15m = frames.get("15m")
            d1h = frames.get("1h")
            d4h = frames.get("4h")
            d1d = frames.get("1d")
            LAST["frames"] = ", ".join(f"{k}:{len(v)}" for k, v in frames.items()) or "yo'q"
            LAST["err"] = str(_DATA.get("err") or "")
            if d1m is None or len(d1m) < SN.WARMUP + 5:
                LAST["why"] = ("1m sham yetarli emas ("
                               f"{0 if d1m is None else len(d1m)}/{SN.WARMUP + 5})"
                               + (f" — xato: {LAST['err']}" if LAST["err"] else ""))
                logger.warning("[SNIPER] %s", LAST["why"])
                return 0
            LAST["m1_candles"] = int(len(d1m))
            try:
                LAST["price"] = round(float(d1m["close"].iloc[-1]), 2)
            except Exception:  # noqa: BLE001
                LAST["price"] = None
            # --- KATTA TF KUZATUVI (1d / 4h / 1h) ---
            bias, bias_txt, agree = SN.htf_bias_multi(d1h, d4h, d1d)
            LAST["bias"] = bias
            LAST["bias_txt"] = bias_txt
            LAST["htf_levels"] = len(SN.htf_levels(d1h, d4h))
            if bias == "NONE":
                LAST["why"] = f"HTF yo'nalish aniq emas ({bias_txt}) — M1 da savdo qilmaymiz"
                return 0
            if SN.htf_opposite(d4h, bias):
                LAST["why"] = "4h yo'nalishi 1h ga qarama-qarshi — HTF filtri to'sdi"
                return 0
            # --- v93: COOLDOWN va KUNLIK LIMIT (hisobni charchatmaslik uchun) ---
            import time as _time
            from datetime import timezone as _tz2
            _now = datetime.now(_tz2.utc)
            _last_ts = _LAST_SIG_TS.get("t")
            if _last_ts is None:
                try:
                    from sqlalchemy import select
                    from app.database.models.signal import Signal as _Sig
                    _row = (await session.execute(
                        select(_Sig).where(_Sig.quality_mode == "SNIPER")
                        .order_by(_Sig.created_at.desc()).limit(1))).scalars().first()
                    if _row is not None and _row.created_at is not None:
                        _last_ts = _row.created_at
                        if _last_ts.tzinfo is None:
                            _last_ts = _last_ts.replace(tzinfo=_tz2.utc)
                        _LAST_SIG_TS["t"] = _last_ts
                except Exception:  # noqa: BLE001
                    _last_ts = None
            if _last_ts is not None:
                _ago = (_now - _last_ts).total_seconds()
                if _ago < COOLDOWN_S:
                    LAST["why"] = (f"oxirgi sniper signaldan {int(_ago // 60)} daqiqa "
                                   f"o'tdi — {int(COOLDOWN_S // 60)} daqiqa kutamiz")
                    return 0
            try:
                from sqlalchemy import func as _fn, select as _sel
                from app.database.models.signal import Signal as _Sig2
                _day0 = _now.replace(hour=0, minute=0, second=0, microsecond=0)
                _today = int((await session.execute(
                    _sel(_fn.count(_Sig2.id)).where(_Sig2.quality_mode == "SNIPER",
                                                    _Sig2.created_at >= _day0)
                )).scalar() or 0)
                if _today >= DAILY_MAX:
                    LAST["why"] = (f"bugun {_today} ta sniper signal berildi "
                                   f"(kunlik chegara {DAILY_MAX}) — ertaga davom")
                    return 0
            except Exception:  # noqa: BLE001
                pass
            # v94: SEANS — oltin London/NY da yuradi; boshqa vaqtda skan behuda
            if M1_KILLZONE and not SN.in_killzone(d1m[SN.time_col(d1m)].iloc[-1]):
                LAST["why"] = ("seans tashqarisida — oltin asosan London "
                               "(06-10 UTC) va Nyu-York (12-16 UTC) soatlarida "
                               "yuradi; shu paytda skan qilinmaydi")
                return 0
            # --- BITTA TAHLIL M1 DA ---
            setup = SN.analyze_m1(d1m, d5m, d15m, d1h, d4h, d1d,
                                  score_min=M1_SCORE_MIN, disp_min=M1_DISP_MIN,
                                  killzone=M1_KILLZONE)
            if setup is None:
                LAST["why"] = (f"HTF {bias} ({agree}/3 mos), lekin M1 da setup yo'q: "
                               "supurish + impuls + FVG/OB birga topilmadi "
                               f"yoki ball {M1_SCORE_MIN:.1f} dan past")
                return 0
            LAST["best_score"] = float(setup.score)
            LAST["why"] = f"SETUP TOPILDI: {setup.mode} ball {setup.score:.1f}"
            # v106: NARX ESKIRGAN bo'lsa bozordan kirish YO'Q (feed o'lib
            # qolganida eskigan narxga savdo ochilmasin — "kuzatuv xatosi")
            try:
                import datetime as _dt6
                _ts = SN.time_col(d1m).iloc[-1]
                if _ts.tzinfo is None:
                    _ts = _ts.replace(tzinfo=_dt6.timezone.utc)
                _age = (_dt6.datetime.now(_dt6.timezone.utc) - _ts).total_seconds()
                if _age > 600:
                    LAST["why"] = (f"setup bor, lekin narx eskirgan "
                                   f"({int(_age // 60)} daqiqa) — feed tekshiruvi, "
                                   f"bozordan kirish BEKOR (v106)")
                    logger.warning("[SNIPER] v106 eskirgan narx: %s daqiqa",
                                   int(_age // 60))
                    return 0
            except Exception as exc:  # noqa: BLE001
                logger.info("[SNIPER] v106 freshness: %s", exc)
            _px = LAST.get("price") or float(d1m["close"].iloc[-1])
            sig = await _make_signal(session, setup, px=float(_px))
            if sig is None:
                LAST["why"] = ("setup bor, lekin shu yo'nalishda OCHIQ sniper signali "
                               "allaqachon mavjud — takror ochilmadi")
                return 0
            LAST["signals"] = int(LAST.get("signals") or 0) + 1
            try:
                from datetime import timezone as _tz3
                _LAST_SIG_TS["t"] = datetime.now(_tz3.utc)
            except Exception:  # noqa: BLE001
                pass
            LAST["why"] = (f"SIGNAL #{sig.id} {setup.direction} M1 da ochildi "
                           f"(ball {setup.score:.1f})")
            lot = await _LS.get(session, None)   # v86: UMUMIY lot (hammasi uchun bitta)
            from app.paper_trading.engine import PaperEngine
            opened = await PaperEngine().open_for_signal(session, sig, [SNIPER_USER_ID])
            logger.info("[SNIPER] SIGNAL #%s %s ball=%.1f lot=%.2f ochildi=%d (%s)",
                        sig.id, setup.direction, setup.score, lot, opened, setup.mode)
            # v93: karta yuborilishi — app bo'lmasa ham (/skan buyrug'i shunday)
            try:
                _notifier = getattr(app, "notifier", None) if app is not None else None
                if _notifier is None:
                    from app.services import channel_inbox as _ci
                    _notifier = getattr(_ci, "_notifier", None)
                if _notifier is not None:
                    await _notifier.send_signal(sig)
                else:
                    logger.warning("[SNIPER] notifier topilmadi — karta yuborilmadi")
            except Exception as exc:  # noqa: BLE001
                logger.warning("[SNIPER] karta yuborilmadi: %s", exc)
            return 1
    except Exception as exc:  # noqa: BLE001
        LAST["err"] = f"{type(exc).__name__}: {exc}"
        LAST["why"] = "skan xatosi: " + LAST["err"]
        logger.warning("[SNIPER] skan: %s", exc)
        return 0


async def force_scan(app=None) -> dict:
    """v93: `/skan` — darhol bitta skan qiladi va natijasini qaytaradi.

    Foydalanuvchi "bot o'zi signal qildimi?" deb taxmin qilib o'tirmasligi uchun:
    nima ko'rilgani va nega signal bo'lmagani aniq yoziladi.
    """
    before = int(LAST.get("scans") or 0)
    made = 0
    try:
        made = await scan_once(app)
    except Exception as exc:  # noqa: BLE001
        LAST["err"] = f"{type(exc).__name__}: {exc}"
    if int(LAST.get("scans") or 0) == before:      # skan umuman ishlamadi
        LAST["why"] = LAST.get("why") or "skan ishlamadi"
    return {"made": int(made or 0), "diag": diag_lines(), "last": dict(LAST)}


async def _make_signal(session, setup, px: float | None = None):
    """Setup ma'lumotidan Signal yasaydi (takrorlanishni tekshirib).

    v94: kirish = BOZOR NARXI (darhol). Zona kutish o'rniga trigger to'liq
    bo'lgan paytda bozordan kiriladi — shunda "KIRISH BO'LMADI" holati
    umuman qolmaydi va natijalar real bo'ladi.
    """
    from sqlalchemy import select
    from app.core.enums import Direction
    from app.database.models.signal import Signal
    d = Direction.BUY if setup.direction == "BUY" else Direction.SELL
    act = (await session.execute(
        select(Signal).where(Signal.is_active.is_(True),
                             Signal.quality_mode == "SNIPER")
    )).scalars().all()
    for old in act:
        # bir xil yo'nalishda ochiq sniper signal bo'lsa — yangisini ochmaymiz
        if str(old.direction).upper() == setup.direction and old.symbol == SYMBOL:
            logger.info("[SNIPER] ochiq signal bor (#%s) — yangi setup o'tkazib yuborildi",
                        old.id)
            return None
    n = int((await session.execute(
        select(Signal).where(Signal.quality_mode == "SNIPER")
    )).scalars().all().__len__())
    sig = Signal(
        symbol=SYMBOL, timeframe=TF, direction=d.value, status="CREATED",
        is_active=True, score=float(setup.score) * 10.0, confidence=float(setup.score),
        win_probability=0.0, signal_no=n + 1, strength="STRONG",
        quality_mode="SNIPER",
        entry=float(px or setup.entry), sl=setup.sl, tp1=setup.tp1,
        tp2=setup.tp2, tp3=setup.tp2,
        entry_low=float(px or setup.entry), entry_high=float(px or setup.entry),
        atr_value=setup.atr, entry_mode="MARKET", entry_status="FILLED",
        entry_note=(f"SNIPER {setup.mode} ball {setup.score:.1f} — "
                    f"bozordan kirildi ({float(px or setup.entry):,.2f})")[:96],
        source_channel="SNR+ICT+SMC (bot o'zi)", source_username="sniper",
        explanation=("SNR+ICT+SMC SNIPER (oltin): " + setup.reason + " | " +
                     " · ".join(setup.parts)),
        checks_json="[]",
    )
    # v94: TP larni BOZOR kirishiga moslaymiz (setup R nisbatlari saqlanadi).
    # Aks holda zona o'rtasidan hisoblangan TP bozor narxida noto'g'ri R berardi.
    try:
        _e0 = float(setup.entry); _pxf = float(px or setup.entry)
        _slf = float(setup.sl)
        _r0 = abs(_e0 - _slf)
        _rn = abs(_pxf - _slf)
        if _r0 > 0 and _rn > 0 and abs(_pxf - _e0) > 1e-9:
            _sgn = 1.0 if setup.direction == "BUY" else -1.0
            for attr, tv in (("tp1", setup.tp1), ("tp2", setup.tp2), ("tp3", setup.tp2)):
                _rr = abs(float(tv) - _e0) / _r0
                setattr(sig, attr, round(_pxf + _sgn * _rr * _rn, 2))
    except Exception as exc:  # noqa: BLE001
        logger.debug("[SNIPER] TP moslash: %s", exc)
    session.add(sig)
    await session.commit()
    await session.refresh(sig)
    return sig


async def loop(app) -> None:
    """Fon vazifasi: har 60 sekundda skanerlaydi."""
    await asyncio.sleep(25)
    while True:
        try:
            await scan_once(app)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[SNIPER] sikl: %s", exc)
        await asyncio.sleep(SCAN_SECONDS)


def diag_lines() -> list[str]:
    """v93: OXIRGI SKAN — bot nima ko'rdi va NEGA signal berdi/bermadi."""
    from app.core.timeuz import format_tashkent
    ts = LAST.get("ts")
    when = format_tashkent(ts) if ts else "hali skan bo'lmagan"
    bias = LAST.get("bias") or "-"
    bias_txt = LAST.get("bias_txt") or ""
    px = LAST.get("price")
    out = [
        "\u23F1 <b>Oxirgi skan:</b> " + str(when)
        + f" \u00b7 jami {int(LAST.get('scans') or 0)} skan"
        + f" \u00b7 {int(LAST.get('signals') or 0)} signal",
        f"\U0001F50D Kuzatuv: <b>1d / 4h / 1h</b> \u2192 tahlil va savdo <b>M1</b> da",
        f"\U0001F9ED HTF yo'nalish: <b>{bias}</b>" + (f" ({bias_txt})" if bias_txt else ""),
    ]
    if px:
        out.append(f"\U0001F4B0 Oltin narxi: <b>{float(px):,.2f}</b> \u00b7 "
                   f"M1 sham: {int(LAST.get('m1_candles') or 0)} \u00b7 "
                   f"HTF daraja: {int(LAST.get('htf_levels') or 0)}")
    why = str(LAST.get("why") or "")
    if why:
        out.append(f"\u2139\uFE0F Natija: {why}")
    frames = str(LAST.get("frames") or "")
    if frames:
        out.append(f"\U0001F4CA Ma'lumot: {frames}")
    err = str(LAST.get("err") or "")
    if err:
        out.append(f"\u26A0\uFE0F Ma'lumot xatosi: {err[:120]}")
    return out


def status_line(st: dict) -> str:
    """`/sniper` uchun holat matni (o'zbekcha, aniq raqamlar bilan)."""
    pnl = st["pnl"]
    icon = "\U0001F7E2" if pnl >= 0 else "\U0001F534"
    on = st.get("on")
    return (
        "\U0001F3AF <b>SNR + ICT + SMC SNIPER (OLTIN)</b>\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"Holat: <b>{'YONIQ' if on else 'O\u2018CHIQ'}</b> \u00b7 juftlik "
        f"<b>XAUUSD (oltin)</b> \u00b7 5m skaner\n"
        f"\U0001F4B0 Alohida hisob: <b>{st['balance']:,.2f}$</b> "
        f"(boshlang'ich {st['initial']:,.0f}$)\n"
        f"{icon} Natija: <b>{pnl:+,.2f}$</b> \u00b7 bitimlar {st['trades']} "
        f"(ochiq {st['open']})\n"
        f"\U0001F3C6 G'alaba: <b>{st['wr']:.0f}%</b> "
        f"({st['wins']} yutuq / {st['losses']} zarar)"
        + (f" \u00b7 PF {st['pf']:.2f}" if st.get("pf") else "")
        + "\n\u2139\uFE0F Bu \u2014 <b>2-hisob</b> (bot o\u2018zi topgan signallar). "
        "Uchala hisob (\U0001F4E1 kanal / \U0001F916 bot o\u2018zi / \U0001F9EE jami) "
        "<b>\U0001F4BC Hisob (paper)</b> va hisobotlarda birga ko\u2018rinadi."
        + "\n\n" + "\n".join(diag_lines())
        + "\n\n<i>Signal: 1d/4h/1h yo'nalishi kuzatiladi \u2192 M1 da supurish + "
        "impuls + FVG/Order Block \u2192 kirish zonasi, SL va TP1/TP2 avtomatik "
        "(savdo M1 da).</i>"
    )
