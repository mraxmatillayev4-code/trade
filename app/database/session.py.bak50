"""Async database sessiyasi."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.logging import get_logger
from app.database.base import Base

logger = get_logger(__name__)

# Ishga tushishda logda ko'rinadigan versiya belgisi (to'g'ri kod deploy bo'lganini tekshirish uchun)
DB_INIT_VERSION = "SCHEMA-V6-20260902"

_settings = get_settings()

engine = create_async_engine(
    _settings.database_url_async,
    echo=False,
    pool_pre_ping=True,
    future=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


def _is_numeric(col) -> bool:
    exp = type(col.type).__name__.upper()
    return ("FLOAT" in exp or "NUMERIC" in exp or "DECIMAL" in exp
            or "INT" in exp or "BOOLEAN" in exp)


async def _schema_matches(conn) -> bool:
    """Har bir jadval ustunlarini va TIPLARINI joriy modellar bilan solishtiradi."""
    from sqlalchemy import text

    for table in Base.metadata.sorted_tables:
        res = await conn.execute(
            text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=:tn"
            ),
            {"tn": table.name},
        )
        actual = {r[0]: (r[1] or "").lower() for r in res.fetchall()}
        if not actual:
            logger.warning("[%s] jadval yo'q -> toza yaratiladi", table.name)
            return False

        # signals jadvalining real tiplarini logga yozamiz (debug uchun)
        if table.name == "signals":
            logger.info("[DB-CHECK] signals ustunlari: %s", actual)

        for col in table.columns:
            if col.name not in actual:
                logger.warning("[%s] %s ustuni yo'q", table.name, col.name)
                return False
            act = actual[col.name]
            model_t = type(col.type).__name__.upper()
            if _is_numeric(col) and ("char" in act or "text" in act):
                logger.warning(
                    "[%s] %s: modelda %s, bazada %s -> sxema begona",
                    table.name, col.name, type(col.type).__name__, act,
                )
                return False
            # Telegram user_id lar 2^31 dan katta bo'lishi mumkin -> bigint shart
            if "BIGINT" in model_t and act != "bigint":
                logger.warning(
                    "[%s] %s: modelda BigInteger, bazada %s -> toza qayta yaratiladi",
                    table.name, col.name, act,
                )
                return False
            if model_t == "INTEGER" and act not in ("integer", "smallint", "bigint"):
                logger.warning(
                    "[%s] %s: modelda Integer, bazada %s -> sxema begona",
                    table.name, col.name, act,
                )
                return False
    return True


async def init_db() -> None:
    """Jadvallarni yaratadi; begona/eski sxema aniqlansa butunlay toza qayta yaratadi."""
    from app.database import models  # noqa: F401  (modellar metadata'ga yuklanadi)

    logger.info("===== DB INIT %s =====", DB_INIT_VERSION)

    async with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            ok = await _schema_matches(conn)
            if not ok:
                logger.warning(
                    "Eski/begona DB sxemasi aniqlandi -> barcha jadvallar toza qayta yaratilmoqda"
                )
                await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
            logger.info("PostgreSQL jadvallar tayyor (%s)",
                        "mavjud sxema to'g'ri" if ok else "toza yaratildi")
        else:
            await conn.run_sync(Base.metadata.create_all)
            logger.info("SQLite jadvallar tayyor")

    logger.info("Database jadvallar tayyor")


async def get_session() -> AsyncSession:  # type: ignore[misc]
    """FastAPI dependency."""
    async with async_session_factory() as session:
        yield session
