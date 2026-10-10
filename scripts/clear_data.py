"""Clear all runtime data from PostgreSQL database, keep schema and users."""
import asyncio
from sqlalchemy import text
from app.database.session import engine
from app.database.base import Base
from app.core.config import get_settings


async def clear_data():
    settings = get_settings()
    print(f"Connecting to: {settings.database_url_async}")

    # Tables to clear (runtime data) - keep users and user_settings
    tables_to_clear = [
        "signal_confirmations",
        "signals",
        "candles",
        "paper_positions",
        "paper_accounts",
        "strategy_stats",
        "backtests",
        "system_logs",
    ]

    async with engine.begin() as conn:
        # Disable foreign key checks temporarily (PostgreSQL)
        await conn.execute(text("SET session_replication_role = 'replica'"))

        for table in tables_to_clear:
            try:
                result = await conn.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))
                print(f"Cleared {table}")
            except Exception as e:
                print(f"Skipped {table}: {e}")

        # Re-enable foreign key checks
        await conn.execute(text("SET session_replication_role = 'origin'"))

    print("Done! All runtime data cleared.")


if __name__ == "__main__":
    asyncio.run(clear_data())