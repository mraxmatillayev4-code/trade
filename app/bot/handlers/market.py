"""Bozor bo'limi — barcha kuzatilayotgan instrumentlarning qisqa ko'rinishi (matn)."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from app.core.config import get_settings
from app.core.symbols import full_label
from app.engine.market_regime import REGIME_UZ, detect_regime
from app.indicators.bundle import compute_bundle
from app.market.binance_rest import BinanceRest
from app.market.candle_manager import CandleManager
from app.market.gold_rest import GoldRest, needs_mexc

router = Router(name="market")


async def _compact(symbol: str, tf: str = "1h") -> str | None:
    settings = get_settings()
    rest = GoldRest() if needs_mexc(symbol) else BinanceRest(settings)
    chg = ""
    try:
        df = await rest.get_klines(symbol, tf, 200)
        if df is None or len(df) < 60:
            return None
        try:
            ticker = await rest.get_ticker_24h(symbol)
            if ticker:
                chg = f" ({ticker['price_change_pct']:+.2f}%)"
        except Exception:  # noqa: BLE001
            pass
    finally:
        await rest.close()

    expected = CandleManager._expected_open_time(tf)
    df = df[df["open_time"] < expected].copy()

    b = compute_bundle(df, settings)
    regime = detect_regime(b)
    rsi_v = float(b.rsi.iloc[-1])
    trend = "🟢 Ko'tarilish" if float(b.ema50.iloc[-1]) > float(b.ema200.iloc[-1]) else "🔴 Tushish"
    price = b.last_close
    return (
        f"<b>{full_label(symbol)}</b> • {tf.upper()}\n"
        f"💰 {price:,.4f} {chg}\n"
        f"📈 {trend} | 🎛 {REGIME_UZ.get(regime, regime.value)} | RSI {rsi_v:.0f}"
    )


@router.message(F.text == "📊 Bozor")
async def market_overview(message: Message) -> None:
    settings = get_settings()
    await message.answer("📊 Bozor tahlil qilinmoqda... (4 instrument, 1H)")
    blocks: list[str] = ["📊 <b>BOZOR HOLATI</b> (1H)", "━━━━━━━━━━━━━━━━"]
    for symbol in settings.symbol_list:
        try:
            block = await _compact(symbol, "1h")
            blocks.append(block if block else f"⚠️ {symbol}: ma'lumot yo'q")
        except Exception as exc:  # noqa: BLE001
            blocks.append(f"⚠️ {symbol}: {exc}")
        blocks.append("")
    blocks.append("Signal chiqsa, u to'liq tafsiloti bilan alohida yuboriladi.")
    await message.answer("\n".join(blocks), parse_mode="HTML")
