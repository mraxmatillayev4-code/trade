from aiogram import Router

from app.bot.handlers import (
    backtest,
    broker,
    channels,
    common,
    dbadmin,
    market,
    paper,
    persist,
    reports,
    settings,
    signals,
    stats,
    strategies,
)


def get_main_router() -> Router:
    router = Router()
    router.include_router(common.router)
    router.include_router(channels.router)
    router.include_router(broker.router)
    router.include_router(dbadmin.router)
    router.include_router(signals.router)
    router.include_router(market.router)
    router.include_router(strategies.router)
    router.include_router(stats.router)
    router.include_router(backtest.router)
    router.include_router(paper.router)
    router.include_router(persist.router)
    router.include_router(reports.router)
    router.include_router(settings.router)
    return router
