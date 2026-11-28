"""Backtest menyusi — tarixiy sinov va walk-forward."""
from __future__ import annotations

from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards as kb
from app.core.config import get_settings
from app.core.enums import HIGHER_TIMEFRAMES
from app.database.models.backtest import Backtest
from app.database.session import async_session_factory
from app.market.binance_rest import BinanceRest
from app.backtest.engine import run_backtest
from app.backtest.walk_forward import run_walk_forward

router = Router(name="backtest")

PERIOD_CANDLES = {"7d": 700, "30d": 900, "90d": 1000}
STRATEGY_UZ = {
    "ALL": "Barcha strategiyalar",
    "ema_trend": "EMA + RSI + MACD",
    "supertrend": "Supertrend + EMA",
    "vwap": "VWAP + RSI",
    "breakout": "Breakout + Volume",
    "divergence": "RSI Divergence",
    "squeeze": "Squeeze Breakout",
    "ichimoku": "Ichimoku Cloud",
    "price_action": "Price Action (sham shakllari)",
    "stochastic": "Stochastic %K/%D",
    "obv": "OBV hajm oqimi",
}


@router.callback_query(F.data == "menu:backtest")
async def backtest_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "🧪 <b>BACKTEST</b>\n"
        "Tarixiy ma'lumotlarda strategiyalarni sinab ko'ramiz.\n"
        "Avval coin tanlang 👇",
        reply_markup=kb.symbols_kb("bt:sym", "menu:main"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(F.text == "🧪 Backtest")
async def backtest_menu_message(message: Message) -> None:
    await message.answer(
        "🧪 <b>BACKTEST</b>\n"
        "Tarixiy ma'lumotlarda strategiyalarni sinab ko'ramiz.\n"
        "Avval coin tanlang 👇",
        reply_markup=kb.symbols_kb("bt:sym", "menu:main"),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("bt:sym:"))
async def bt_symbol(callback: CallbackQuery) -> None:
    symbol = callback.data.split(":")[-1]
    await callback.message.edit_text(
        f"⏱ {symbol} — timeframe tanlang:",
        reply_markup=kb.timeframe_kb("bt:tf", symbol),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("bt:tf:"))
async def bt_tf(callback: CallbackQuery) -> None:
    _, _, symbol, tf = callback.data.split(":")
    await callback.message.edit_text(
        f"📅 {symbol} {tf.upper()} — davrni tanlang:",
        reply_markup=kb.backtest_period_kb(symbol, tf),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("bt:period:"))
async def bt_period(callback: CallbackQuery) -> None:
    _, _, symbol, tf, period = callback.data.split(":")
    await callback.message.edit_text(
        "🎯 Strategiyani tanlang (yoki walk-forward):",
        reply_markup=kb.backtest_strategy_kb(symbol, tf, period),
        parse_mode="HTML",
    )
    await callback.answer()


async def _fetch_data(symbol: str, tf: str, period: str):
    settings = get_settings()
    rest = BinanceRest(settings)
    try:
        limit = PERIOD_CANDLES.get(period, 700)
        df = await rest.get_klines(symbol, tf, limit)
        higher = {}
        for htf in HIGHER_TIMEFRAMES.get(tf, []):
            higher[htf] = await rest.get_klines(symbol, htf, limit)
    finally:
        await rest.close()
    expected_open = df.iloc[-1]["open_time"]
    # Oxirgi (ochiq) shamni olib tashlaymiz
    from app.market.candle_manager import CandleManager
    boundary = CandleManager._expected_open_time(tf)
    df = df[df["open_time"] < boundary].copy()
    higher = {k: v[v["open_time"] < boundary].copy() for k, v in higher.items()}
    return df, higher


def _format_metrics(m: dict, symbol: str, tf: str, period: str,
                    strategy: str, candles: int) -> str:
    return (
        f"🧪 <b>BACKTEST NATIJASI</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💰 {symbol} • {tf.upper()} • {period}\n"
        f"🎯 Strategiya: <b>{STRATEGY_UZ.get(strategy, strategy)}</b>\n"
        f"📊 Shamlar: {candles}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🔢 Jami bitimlar: <b>{m['total_trades']}</b>\n"
        f"✅ Yutuq: {m['wins']}  |  ❌ Zarar: {m['losses']}  |  ➖ {m['breakeven']}\n"
        f"🎯 Win rate: <b>{m['win_rate']:.2f}%</b>\n"
        f"💪 Profit factor: <b>{m['profit_factor']:.2f}</b>\n"
        f"📊 Avg R: <b>{m['avg_r']:+.2f}</b>\n"
        f"📉 Maks drawdown: {m['max_drawdown_r']:.2f}R\n"
        f"💵 O'rtacha daromad: {m['avg_return_pct']:+.2f}%\n"
        f"📦 Jami R: {m['total_r']:+.2f}R\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"<i>⚠️ Tarixiy natija kelajakni kafolatlamaydi.\n"
        f"Kam bitimli strategiyani 'eng yaxshi' deb hisoblamang.</i>"
    )


@router.callback_query(F.data.startswith("bt:run:"))
async def bt_run(callback: CallbackQuery) -> None:
    _, _, symbol, tf, period, strategy = callback.data.split(":")
    await callback.message.edit_text("⏳ Hisoblanmoqda... (bir necha soniya)", parse_mode="HTML")
    settings = get_settings()
    df, higher = await _fetch_data(symbol, tf, period)

    metrics = run_backtest(
        df, tf, settings, higher_dfs=higher,
        strategy_filter=strategy, symbol=symbol,
    )

    # DB ga saqlash
    import json
    async with async_session_factory() as session:
        session.add(Backtest(
            symbol=symbol, timeframe=tf, period=period,
            strategy=strategy, candles_count=len(df),
            quality_mode=settings.quality_mode.value,
            metrics_json=json.dumps({k: v for k, v in metrics.items() if k != "trades"}),
            completed_at=datetime.now(timezone.utc),
        ))
        await session.commit()

    per_strat = metrics.pop("per_strategy", {})
    trades = metrics.pop("trades", [])
    text = _format_metrics(metrics, symbol, tf, period, strategy, len(df))
    if per_strat and strategy == "ALL":
        text += "\n\n<b>Strategiyalar kesimida:</b>"
        for name, pm in per_strat.items():
            text += (f"\n• {STRATEGY_UZ.get(name, name)}: {pm['trades']} bitim, "
                     f"WR {pm['win_rate']:.1f}%, avgR {pm['avg_r']:+.2f}")
    await callback.message.edit_text(
        text, reply_markup=kb.back_to_menu(), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("bt:wf:"))
async def bt_walk_forward(callback: CallbackQuery) -> None:
    _, _, symbol, tf, period, strategy = callback.data.split(":")
    await callback.message.edit_text("🧬 Walk-forward hisoblanmoqda...", parse_mode="HTML")
    settings = get_settings()
    df, higher = await _fetch_data(symbol, tf, period)
    wf = run_walk_forward(df, tf, settings, higher_dfs=higher,
                          folds=5, strategy_filter=strategy, symbol=symbol)
    lines = [
        f"🧬 <b>WALK-FORWARD TEST</b>",
        "━━━━━━━━━━━━━━━━",
        f"💰 {symbol} • {tf.upper()} • {period}",
        f"━━━━━━━━━━━━━━━━",
        f"Barqarorlik: <b>{wf['stability_pct']:.0f}%</b> "
        f"({wf['positive_folds']}/{wf['folds_count']} oyna ijobiy)",
        f"O'rtacha win rate: {wf['avg_win_rate']:.1f}%",
        f"O'rtacha R: {wf['avg_r']:+.2f}",
        f"Holati: {'✅ BARQAROR' if wf['stable'] else '⚠️ BARQAROR EMAS'}",
        "━━━━━━━━━━━━━━━━",
        "<b>Oynalar bo'yicha:</b>",
    ]
    for f_ in wf["folds"]:
        ico = "🟢" if f_["avg_r"] > 0 else "🔴"
        lines.append(
            f"{ico} Oyna {f_['fold']}: {f_['total_trades']} bitim, "
            f"WR {f_['win_rate']:.1f}%, avgR {f_['avg_r']:+.2f}, PF {f_['profit_factor']:.2f}"
        )
    lines.append("━━━━━━━━━━━━━━━━")
    lines.append("<i>Parametrlar optimizatsiya qilinmaydi — overfitting oldini olinadi.</i>")
    await callback.message.edit_text(
        "\n".join(lines), reply_markup=kb.back_to_menu(), parse_mode="HTML"
    )
    await callback.answer()
