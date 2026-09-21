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
