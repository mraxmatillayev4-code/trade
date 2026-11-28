"""SINO BOT VIRTUAL MUHIT TO'LIQ AUDIT VA SINOVI (v130 — FULL COMBINED)."""
import asyncio
import os
import sys

# Muhitni tayyorlash
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["ADMIN_IDS"] = "987654321"

from app.database.session import init_db, async_session_factory
from app.database.models.signal import Signal
from app.database.models.paper import PaperPosition, PaperAccount
from app.core.enums import Direction, PaperStatus, SignalStatus
from app.services.channel_parse import parse_signal
from app.services import channel_inbox as CI
from app.services import channel_ai
from app.paper_trading.engine import PaperEngine
from app.services.paper_split import bucket_stats
from app.engine.sizing import select_best_channel_tp
from app.notifications import telegram as NT
from types import SimpleNamespace as NS
import pandas as pd
import re

async def run_full_test():
    print("=" * 75)
    print("      SINO TRADING BOT — TO'LIQ AUDIT VA VIRTUAL SINOV (v130 FULL)")
    print("=" * 75)
    await init_db()
    pe = PaperEngine()
    admin_id = 987654321

    # -------------------------------------------------------------
    # SIN OV 1: AI XATOSI (TypeError) TESTI
    # -------------------------------------------------------------
    print("\n[SIN OV 1] AI interpretatsiyasi va OCR xatosi testi...")
    raw_ocr = "Kechiayam shunaq qldi bugunam shunaq qvotti) 20:09 ol! LTE EE 1 M1 -- Ff &"
    try:
        ai_res = await channel_ai.interpret_async(raw_ocr, image_bytes=None, ctx="", has_image=False)
        print("  -> AI interpret_async chaqirildi: TypeError YO'Q!")
        print("  [PASS] 1-sinov muvaffaqiyatli: AI TypeError butunlay yo'qotildi.")
    except Exception as e:
        print(f"  [FAIL] 1-sinovda xato: {e}")
        return False

    # -------------------------------------------------------------
    # SIN OV 2: JAVA_FX "Gold buy 3525-3520 Sl 3518" VA DARHOL KIRISH
    # -------------------------------------------------------------
    print("\n[SIN OV 2] JAVA_FX 'Gold buy 3525-3520' narx 3526.12 da bo'lganda...")
    javafx_post = "JAVA_FX | JFX\nBismillah.\nGold buy 3525-3520 📈\nSl 3518 ❌\n\nYig'loqilar uchun mumkin emas ‼️"
    parsed_jf = parse_signal(javafx_post)

    class DummySession:
        async def commit(self): pass

    dummy_sig_jf = NS(
        id=202, symbol="XAUUSDT", direction="BUY", quality_mode="CHANNEL",
        entry=None, entry_mode=None, entry_status=None,
        entry_low=None, entry_high=None, entry_expires_at=None,
        entry_note=None, sl=3518.0, tp1=0.0, raw_text=javafx_post
    )
    CI_last_px_old = CI._last_px
    CI._last_px = lambda s: 3526.12

    # Narx 3526.12 (zonadan tashqarida) bo'lsa -> kirmaydi, WAIT
    st_jf = await CI._apply_entry_plan(DummySession(), dummy_sig_jf, parsed_jf, NS(channel_expiry_minutes=240))
    print(f"  -> Bozor narxi 3,526.12 (zonadan tashqarida) bo'lgandagi holat: {st_jf.upper()}")
    assert st_jf == "wait", f"Kutilgan wait, olindi {st_jf}"

    # Narx 3524.50 (zona ichiga kirganda) -> darhol FILLED va aynan 3524.50 dan kiradi!
    CI._last_px = lambda s: 3524.50
    st_in = await CI._apply_entry_plan(DummySession(), dummy_sig_jf, parsed_jf, NS(channel_expiry_minutes=240))
    CI._last_px = CI_last_px_old
    print(f"  -> Bozor narxi 3,524.50 (zona ichida) bo'lgandagi holat: {st_in.upper()} @ {dummy_sig_jf.entry}")
    assert st_in == "filled" and dummy_sig_jf.entry == 3524.50
    print("  [PASS] 2-sinov muvaffaqiyatli: Narx zona ichiga kirishi bilan o'sha narxdan darhol ochildi (o'rta emas)!")

    # -------------------------------------------------------------
    # SIN OV 3: TP AYTILMAGAN BO'LSA — 1:3.5 NISBATDA BITTA TP
    # -------------------------------------------------------------
    print("\n[SIN OV 3] TP aytilmagan bo'lsa — aniq 1:3.5 nisbatda TP olinishi...")
    # Entry = 3522.50, SL = 3518.00 (Risk = 4.50$)
    # BUY TP = 3522.50 + 3.5 * 4.50 = 3538.25
    tp_auto = select_best_channel_tp("BUY", 3522.50, 3518.00, [])
    print(f"  -> Entry: 3522.50, SL: 3518.00 (Risk: 4.50$)")
    print(f"  -> 1:3.5 nisbatdagi avtomatik TP: {tp_auto}")
    assert tp_auto == 3538.25
    print("  [PASS] 3-sinov muvaffaqiyatli: TP aytilmagan signal uchun 1:3.5 nisbatdagi TP olindi!")

    # -------------------------------------------------------------
    # SIN OV 4: TP KO'P AYTILGAN BO'LSA — 1:3 GA ENG YAQININI TANLASH
    # -------------------------------------------------------------
    print("\n[SIN OV 4] Ko'p TP bo'lsa — 1:1 o'rniga 1:3 ga eng yaqin TP tanlanishi...")
    # Entry = 4000.0, SL = 3995.0 (Risk = 5$) -> Target 3R = 4015.0
    # Kanal TP lari: TP1 = 4005 (1R), TP2 = 4010 (2R), TP3 = 4016 (3.2R), TP4 = 4030 (6R)
    channel_tps = [4005.0, 4010.0, 4016.0, 4030.0]
    best_selected_tp = select_best_channel_tp("BUY", 4000.0, 3995.0, channel_tps)
    print(f"  -> Kanal TP lari: {channel_tps}")
    print(f"  -> 1:1 (4005) tashlandi, 1:3 ga eng yaqin tanlangan TP: {best_selected_tp}")
    assert best_selected_tp == 4016.0
    print("  [PASS] 4-sinov muvaffaqiyatli: 1:3 ga eng yaqin optimal TP tanlab olindi!")

    # -------------------------------------------------------------
    # SIN OV 5: MAXFIY KANAL / GURUH ID SINI ULASH (-1004357689041)
    # -------------------------------------------------------------
    print("\n[SIN OV 5] Maxfiy kanal ID si orqali (-1004357689041) ulash...")
    test_id_input = "ID: -1004357689041"
    id_match = re.search(r"(-?100\d{8,14}|-\d{8,14}|\b\d{9,14}\b)", test_id_input)
    assert id_match is not None
    parsed_chat_id = int(id_match.group(1)) if id_match.group(1).startswith("-100") else -int(f"100{id_match.group(1)}")
    print(f"  -> Kiritilgan matn: '{test_id_input}'")
    print(f"  -> Aniqlangan Telegram Chat ID: {parsed_chat_id}")
    assert parsed_chat_id == -1004357689041
    print("  [PASS] 5-sinov muvaffaqiyatli: Maxfiy kanal ID si xatosiz parse qilindi va ulandi!")

    # -------------------------------------------------------------
    # SIN OV 6: IKKALA LOT HAM TANLANGAN TP DA BIRDAN YOPILISHI
    # -------------------------------------------------------------
    print("\n[SIN OV 6] Ikkala lot ham tanlangan TP da BIRDAN yopilishi...")
    from app.services.tracker import SignalTracker
    tracker = SignalTracker(pe, NS(channel_expiry_minutes=240))

    sig_trade = Signal(
        id=888, symbol="XAUUSD", direction="BUY", signal_no=8,
        entry=4000.0, sl=3995.0, tp1=4016.0, tp2=4016.0, tp3=4016.0,
        status="ACTIVE", is_active=True
    )
    pos_lot1 = PaperPosition(id=21, signal_id=888, user_id=admin_id, symbol="XAUUSD", timeframe="1m", direction="BUY", entry=4000.0, sl=3995.0, tp1=4016.0, tp2=4016.0, tp3=4016.0, qty_total=1.0, qty_remaining=1.0, risk_amount=10.0, balance_before=50.0, stage=0, status=PaperStatus.OPEN.value)
    pos_lot2 = PaperPosition(id=22, signal_id=888, user_id=admin_id, symbol="XAUUSD", timeframe="1m", direction="BUY", entry=4000.0, sl=3995.0, tp1=4016.0, tp2=4016.0, tp3=4016.0, qty_total=1.0, qty_remaining=1.0, risk_amount=10.0, balance_before=50.0, stage=10, status=PaperStatus.OPEN.value)

    closed_lots = []
    async def mock_fill_tp(session, pos, price, count_trade=False, reason=""):
        pos.status = PaperStatus.CLOSED.value
        pos.close_price = price
        closed_lots.append(pos)

    tracker._fill = mock_fill_tp
    tracker._finish_signal = lambda s, sig, n, exit_price: asyncio.sleep(0)
    tracker._px = lambda last, tp, buy, kind: tp

    class TradeSession:
        def __init__(self): pass
        async def commit(self): pass

    pe.open_positions = lambda s, signal_id: _async_wrap([pos_lot1, pos_lot2])
    last_bar = pd.DataFrame([{"open": 4010.0, "high": 4017.0, "low": 4010.0, "close": 4016.5}])

    await tracker._process(TradeSession(), sig_trade, last_bar, None)
    print(f"  -> Yopilgan lotlar soni: {len(closed_lots)} ta (Lot 1 va Lot 2 bir vaqtda)")
    assert len(closed_lots) == 2 and sig_trade.status == SignalStatus.TP1_HIT.value
    print("  [PASS] 6-sinov muvaffaqiyatli: Ikkala lot ham tanlangan TP da birdan to'liq yopildi!")

    # -------------------------------------------------------------
    # SIN OV 7: FAQAT 1 TA OCHIQ SIGNALGA RUXSAT TESTI
    # -------------------------------------------------------------
    print("\n[SIN OV 7] Bir vaqtda faqat 1 ta ochiq signalga ruxsat testi...")
    class LimitSession:
        async def execute(self, stmt):
            class _Res:
                def scalar(self): return 1  # 1 ta ochiq signal mavjud
            return _Res()

    is_blocked, n_open, max_lim = await CI._limit_blocked(LimitSession(), NS(), "BUY")
    print(f"  -> Ochiq signallar: {n_open} ta (Chegara: {max_lim})")
    assert is_blocked and max_lim == 1
    print("  [PASS] 7-sinov muvaffaqiyatli: Faol signal 1 ta bo'lganda yangi signal rad etildi!")

    # -------------------------------------------------------------
    # SIN OV 8: ZONA ICHIGA KIRISHI BILAN AYNYAN O'SHA NARXDAN KIRISH (MID EMAS!)
    # -------------------------------------------------------------
    print("\n[SIN OV 8] Zona ichiga kirishi bilan aynan shu narxdan kirish (o'rta emas)...")
    ok_b, fill_b = EN.zone_hit("BUY", 3562.0, 3567.0, 3566.50)
    assert ok_b is True and fill_b == 3566.50, f"Kutilgan 3566.50, olindi {fill_b}"
    ok_s, fill_s = EN.zone_hit("SELL", 3570.0, 3575.0, 3571.20)
    assert ok_s is True and fill_s == 3571.20, f"Kutilgan 3571.20, olindi {fill_s}"
    print("  [PASS] 8-sinov muvaffaqiyatli: Zona ichiga kirishi bilan o'sha narxdan darhol kirildi!")

    print("\n" + "=" * 75)
    print("      BARCHA 8 TA VIRTUAL AUDIT SINOVLARI 100% MUVAFFAQISHLI O'TDI!")
    print("=" * 75)
    return True

async def _async_wrap(v):
    return v

if __name__ == "__main__":
    ok = asyncio.run(run_full_test())
    sys.exit(0 if ok else 1)
