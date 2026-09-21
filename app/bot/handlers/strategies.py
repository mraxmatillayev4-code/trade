"""Strategiyalar menyusi."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards as kb
from app.database.session import async_session_factory
from app.services.statistics import strategy_statistics

router = Router(name="strategies")

DESC = {
    "ema_trend": "EMA50/EMA200 trendi + RSI + MACD. Trend yo'nalishidagi signallar.",
    "supertrend": "Supertrend chizig'i + EMA200 tasdig'i. Aniq trend o'zgarishlari.",
    "vwap": "VWAP + RSI. Intraday (5m/15m/30m) qisqa muddatli harakatlar.",
    "breakout": "Support/Resistance buzilishi + hajm + ATR filtri. Kuchli harakatlar.",
    "divergence": "RSI divergensiyasi. Narx va momentum kelishmovchiligi (burilishlar).",
}


async def build_strategies_text() -> str:
    async with async_session_factory() as session:
        stats = await strategy_statistics(session)
    lines = ["📚 <b>STRATEGIYALAR</b>", "━━━━━━━━━━━━━━━━"]
    for s in stats:
        icon = "🟢" if s["is_active"] else "⚪"
        lines.append(
            f"{icon} <b>{s['display_name']}</b> (weight {s['weight']})\n"
            f"   <i>{DESC.get(s['name'], '')}</i>\n"
            f"   Signallar: {s['total']} | Win rate: {s['win_rate']:.1f}% | "
            f"PF: {s['profit_factor']:.2f} | Avg R: {s['avg_r']:+.2f}\n"
        )
    lines.append("━━━━━━━━━━━━━━━━")
    lines.append("Signal kamida 2–3 strategiya bir yo'nalishni tasdiqlaganda beriladi.")
    return "\n".join(lines)


@router.callback_query(F.data == "menu:strategies")
async def show_strategies(callback: CallbackQuery) -> None:
    text = await build_strategies_text()
    await callback.message.edit_text(
        text, parse_mode="HTML"
    )
    await callback.answer()


@router.message(F.text == "📚 Strategiyalar")
async def show_strategies_message(message: Message) -> None:
    from app.core.access import is_admin
    if not is_admin(message.from_user.id if message.from_user else None):
        await message.answer("📚 Strategiyalar — faqat admin.")
        return
    text = await build_strategies_text()
    await message.answer(text, parse_mode="HTML")
