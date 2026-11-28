"""v75: /DB — bazani Supabase/Neon (PostgreSQL) ga ko'chirish uchun SQL dump.

Nega kerak: Render'ning BEPUL PostgreSQL bazasi 30 kunda o'chadi (14 kun grace),
keyin ma'lumotlar bilan o'chib ketadi. Bu modul butun bazani (jadvallar + yozuvlar)
oddiy SQL faylga yozadi — uni Supabase SQL Editor'iga qo'yish yoki
`psql "<URL>" -f fayl.sql` bilan yangi bazaga tiklash mumkin.

Fayl PostgreSQL uchun yoziladi (Supabase ham, Neon ham PostgreSQL).
"""
from __future__ import annotations

import datetime as dt
import decimal
import gzip
import json
import uuid

from sqlalchemy import BigInteger, Integer, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.core.timeuz import format_tashkent
from app.database import models as _models  # noqa: F401  (barcha jadvallar ro'yxatga tushsin)
from app.database.base import Base
from app.database.session import async_session_factory

CHUNK_ROWS = 200          # har INSERT ichida nechta yozuv
GZIP_OVER = 40 * 1024 * 1024   # shundan katta bo'lsa gzip qilib yuboramiz


def _q(name: str) -> str:
    """Postgres identifikatori: "signals"."""
    return '"' + str(name).replace('"', '""') + '"'


def _lit(v) -> str:
    """SQL literal (Postgres). Xavfsiz escaping bilan."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            return "NULL"
        return repr(v)
    if isinstance(v, decimal.Decimal):
        return str(v)
    if isinstance(v, dt.datetime):
        txt = v.isoformat(sep=" ")
        return f"'{txt}'::timestamptz" if v.tzinfo else f"'{txt}'"
    if isinstance(v, dt.date):
        return f"'{v.isoformat()}'::date"
    if isinstance(v, dt.time):
        return f"'{v.isoformat()}'::time"
    if isinstance(v, (bytes, bytearray, memoryview)):
        return "E'\\\\x" + bytes(v).hex() + "'::bytea"
    if isinstance(v, (dict, list, tuple)):
        return "'" + json.dumps(v, ensure_ascii=False).replace("'", "''") + "'::jsonb"
    if isinstance(v, uuid.UUID):
        return f"'{v}'::uuid"
    return "'" + str(v).replace("'", "''") + "'"


def _int_pk(tbl) -> str | None:
    """Bitta ustunli butun-sonli PK (setval uchun nomzod)."""
    pks = list(tbl.primary_key.columns)
    if len(pks) != 1:
        return None
    col = pks[0]
    if isinstance(col.type, (Integer, BigInteger)):
        return col.name
    return None


def _ddl(tbl) -> str:
    ddl = str(CreateTable(tbl).compile(dialect=postgresql.dialect()))
    return ddl.rstrip().rstrip(";") + ";"


def _indexes(tbl) -> list[str]:
    out = []
    for idx in tbl.indexes:
        try:
            txt = str(CreateIndex(idx, if_not_exists=True).compile(dialect=postgresql.dialect()))
        except Exception:  # noqa: BLE001
            txt = str(CreateIndex(idx).compile(dialect=postgresql.dialect())).replace(
                "CREATE INDEX", "CREATE INDEX IF NOT EXISTS", 1)
        out.append(txt.rstrip().rstrip(";") + ";")
    return out


async def build() -> tuple[str, bytes, dict]:
    """(fayl nomi, baytlar, statistika) qaytaradi."""
    tables = list(Base.metadata.sorted_tables)
    head: list[str] = []
    body: list[str] = []
    idx_sql: list[str] = []
    seq_pairs: list[tuple[str, str]] = []
    stats: dict = {"tables": 0, "rows": 0, "per_table": {}}

    head.append("-- ============================================================")
    head.append("-- SINO AI — BAZA DUMPI (v75)")
    head.append(f"-- Sana: {format_tashkent(dt.datetime.now(dt.timezone.utc))}")
    head.append("-- Manba: Render PostgreSQL  ->  Maqsad: Supabase / Neon (PostgreSQL)")
    head.append("--")
    head.append("-- SUPABASE: SQL Editor -> New query -> shu faylni qo'yib RUN.")
    head.append("-- NEON:     psql \"<DATABASE_URL>\" -f <shu fayl>")
    head.append("-- ============================================================")
    head.append("")
    head.append("SET client_encoding = 'UTF8';")
    head.append("SET standard_conforming_strings = on;")
    head.append("BEGIN;")

    # 1) Eski jadvallarni tozalash (qayta import qilinsa ham ishlaydi)
    for tbl in reversed(tables):
        body.append(f"DROP TABLE IF EXISTS {_q(tbl.name)} CASCADE;")
    body.append("")

    async with async_session_factory() as session:
        conn = await session.connection()
        for tbl in tables:
            body.append(f"-- ---------- {tbl.name} ----------")
            body.append(_ddl(tbl))
            idx_sql.extend(_indexes(tbl))
            pk = _int_pk(tbl)
            if pk:
                seq_pairs.append((tbl.name, pk))

            # v75: tiplashtirilgan select — SQLAlchemy qiymatlarni to'g'ri Python
            # turiga o'giradi (bool -> True/False, jsonb -> dict, numeric -> Decimal)
            res = await conn.execute(select(tbl))
            cols = [str(k) for k in res.keys()]
            rows = res.fetchall()
            stats["tables"] += 1
            stats["rows"] += len(rows)
            stats["per_table"][tbl.name] = len(rows)
            col_sql = ", ".join(_q(c) for c in cols)
            for start in range(0, len(rows), CHUNK_ROWS):
                chunk = rows[start:start + CHUNK_ROWS]
                vals = ",\n  ".join(
                    "(" + ", ".join(_lit(r[i]) for i in range(len(cols))) + ")"
                    for r in chunk
                )
                body.append(f"INSERT INTO {_q(tbl.name)} ({col_sql}) VALUES\n  {vals};")
            body.append("")

    # 2) Ketma-ketlikni (SERIAL) to'g'rilash — yangi yozuvlar ID'ni davom ettirsin
    if seq_pairs:
        pairs = ",\n    ".join(f"('{t}'::text, '{c}'::text)" for t, c in seq_pairs)
        body.append("-- SERIAL/ketma-ketliklarni tiklash (aks holda yangi ID'lar to'qnashadi)")
        body.append("DO $$")
        body.append("DECLARE r record; s text;")
        body.append("BEGIN")
        body.append("  FOR r IN SELECT * FROM (VALUES")
        body.append(f"    {pairs}")
        body.append("  ) AS v(tbl, col) LOOP")
        body.append("    s := pg_get_serial_sequence(r.tbl, r.col);")
        body.append("    IF s IS NOT NULL THEN")
        body.append("      EXECUTE format('SELECT setval(%L, GREATEST(COALESCE("
                    "(SELECT MAX(%I) FROM %I), 1), 1))', s, r.col, r.tbl);")
        body.append("    END IF;")
        body.append("  END LOOP;")
        body.append("END $$;")
        body.append("")

    # 3) Indekslar — ma'lumot yozilgandan keyin (tezroq import)
    if idx_sql:
        body.append("-- ---------- INDEKSLAR ----------")
        body.extend(idx_sql)
        body.append("")

    body.append("COMMIT;")
    body.append(f"-- Tayyor: {stats['tables']} jadval, {stats['rows']} yozuv.")

    sql_text = "\n".join(head + body) + "\n"
    data = sql_text.encode("utf-8")
    name = "sino_db_" + dt.datetime.now().strftime("%Y%m%d_%H%M") + ".sql"
    if len(data) > GZIP_OVER:
        data = gzip.compress(data, 6)
        name += ".gz"
    stats["bytes"] = len(data)
    stats["name"] = name
    return name, data, stats


async def restore_sql(data: bytes) -> tuple[bool, str, dict]:
    """v128-DB: Botga yuborilgan SQL dump (.sql yoki .sql.gz) faylini bazaga tiklaydi.

    Render yoki VPS da baza yangilanganda, /db orqali olingan sino_db_*.sql
    faylini botga tashlashning o'zi yetarli — bot bazani to'liq tiklaydi.
    """
    if not data:
        return False, "❌ Fayl bo'sh.", {}

    # 1) Gzip siqilgan bo'lsa — ochamiz
    if len(data) >= 2 and data[:2] == b"\x1f\x8b":
        try:
            data = gzip.decompress(data)
        except Exception as exc:  # noqa: BLE001
            return False, f"❌ Gzip fayl ochilmadi: {type(exc).__name__}", {}

    try:
        sql_text = data.decode("utf-8")
    except UnicodeDecodeError:
        sql_text = data.decode("latin-1", errors="replace")

    s_clean = sql_text.strip()
    if not s_clean:
        return False, "❌ SQL fayl bo'sh.", {}

    low = s_clean.lower()
    if not any(k in low for k in ("create table", "insert into", "sino ai")):
        return False, "❌ Bu SINO AI baza dumpi emas (SQL jadvallar topilmadi).", {}

    from app.core.logging import get_logger
    from app.database.session import engine

    _log = get_logger(__name__)

    try:
        async with engine.connect() as conn:
            raw = await conn.get_raw_connection()
            driver = getattr(raw, "driver_connection", None)
            if driver is not None and hasattr(driver, "executescript"):
                await driver.executescript(sql_text)
            elif driver is not None and hasattr(driver, "execute"):
                await driver.execute(sql_text)
            else:
                def _sync_run(sc):
                    c = getattr(sc, "connection", sc)
                    if hasattr(c, "executescript"):
                        c.executescript(sql_text)
                    else:
                        sc.exec_driver_sql(sql_text)

                await conn.run_sync(_sync_run)
    except Exception as exc:  # noqa: BLE001
        _log.exception("[DBDUMP] restore_sql xato: %s", exc)
        return False, f"❌ Baza tiklashda xato: {type(exc).__name__}: {str(exc)[:160]}", {}

    table_count = low.count("create table")
    insert_count = low.count("insert into")
    stats = {
        "bytes": len(data),
        "tables": table_count,
        "inserts": insert_count,
    }
    msg = (
        "✅ <b>BAZA MUVAFFAQIYATLI TIKLANDI!</b>\n\n"
        f"📊 Jadvallar: <b>{table_count}</b> ta · INSERT bloklari: <b>{insert_count}</b> ta\n"
        f"💾 Tiklangan hajm: <b>{len(data) / 1024:.1f} KB</b>\n\n"
        "🔄 Akkaunt, kanallar va signallar bazaga qaytarildi.\n"
        "Kuzatuvchi (channel watcher) qayta ishga tushirildi."
    )
    return True, msg, stats

