"""Statistika menyusi."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards as kb
from app.core.symbols import full_label
from app.database.session import async_session_factory
from app.services.statistics import overall_statistics

router = Router(name="stats")


async def build_stats_text(user_id: int | None = None) -> str:
    async with async_session_factory() as session:
        s = await overall_statistics(session)
        # v92: MANBA BO'YICHA (kanaldan olgani / bot o'zi topgani) + 3 hisob
        extra = ""
        try:
            from app.services import paper_split as PS
            sc = await PS.source_counts(session)
            extra += (
                "\n━━━━━━━━━━━━━━━━\n"
                f"<b>📡 MANBA BO‘YICHA</b>\n"
                f"   📡 Kanaldan olingan: <b>{sc['kanal']}</b> signal\n"
                f"   🤖 Bot o‘zi topgan: <b>{sc['ozi']}</b> signal\n"
            )
            if user_id is not None:
                bk = await PS.bucket_stats(session, user_id)
                extra += "\n" + "\n".join(PS.report_lines(bk)) + "\n"
        except Exception:  # noqa: BLE001
            pass

    return (
        "📈 <b>STATISTIKA</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        f"📨 Jami signallar: <b>{s['total_signals']}</b>\n"
        f"✅ Yutuq: {s['wins']}\n"
        f"❌ Zarar: {s['losses']}\n"
        f"➖ Zararsiz: {s['breakeven']}\n"
        "━━━━━━━━━━━━━━━━\n"
        f"🎯 Win rate: <b>{s['win_rate']:.2f}%</b>\n"
        f"📊 Avg R: <b>{s['avg_r']:+.2f}</b>\n"
        f"💪 Profit factor: <b>{s['profit_factor']:.2f}</b>\n"
        f"📉 Maks drawdown: {s['max_drawdown_r']:.2f}R\n"
        f"💵 O'rtacha daromad: {s['avg_return_pct']:+.2f}%\n"
        f"📦 Jami R: {s['total_r']:+.2f}R\n"
        "━━━━━━━━━━━━━━━━\n"
        f"🏆 Eng yaxshi strategiya: <b>{s['best_strategy']}</b>\n"
        f"⏱ Eng yaxshi timeframe: <b>{str(s['best_timeframe']).upper()}</b>\n"
        f"💰 Eng yaxshi coin: <b>{full_label(str(s['best_symbol'])) if s['best_symbol'] != '—' else '—'}</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        "<i>Natijalar virtual paper trading asosida.</i>"
    ) + extra


@router.callback_query(F.data == "menu:stats")
async def show_stats(callback: CallbackQuery) -> None:
    text = await build_stats_text(callback.from_user.id if callback.from_user else None)
    await callback.message.edit_text(
        text, parse_mode="HTML"
    )
    await callback.answer()


@router.message(F.text == "📈 Statistika")
async def show_stats_message(message: Message) -> None:
    text = await build_stats_text(message.from_user.id if message.from_user else None)
    await message.answer(text, parse_mode="HTML")
