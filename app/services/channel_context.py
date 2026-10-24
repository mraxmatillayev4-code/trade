"""Bir kanalning ketma-ket xabarlarini bir signalga yig'ish.

Misollar:
  1) rasm / GOLD SELL
  2) SL 4310  TP 4270  TP2 4250

  yoki albom (grouped) + tagidagi izoh.
Yangi DB jadval yo'q — faqat xotira (4 daqiqa).
"""
from __future__ import annotations

import time

WINDOW_SEC = 240.0
MAX_KEEP = 8

_buf: dict[str, list[dict]] = {}


def chan_key(username: str | None, chat_id: int | None) -> str:
    u = (username or "").lstrip("@").lower()
    if u:
        return f"@{u}"
    return f"id:{int(chat_id or 0)}"


def remember(
    key: str,
    *,
    text: str = "",
    msg_id: int = 0,
    grouped_id=None,
    reply_to: int | None = None,
) -> list[dict]:
    now = time.time()
    rec = {
        "ts": now,
        "mid": int(msg_id or 0),
        "text": (text or "").strip(),
        "gid": grouped_id,
        "reply": int(reply_to) if reply_to else None,
    }
    arr = [x for x in (_buf.get(key) or []) if now - float(x.get("ts") or 0) <= WINDOW_SEC]
    if rec["mid"]:
        arr = [x for x in arr if int(x.get("mid") or 0) != rec["mid"]]
    arr.append(rec)
    arr = arr[-MAX_KEEP:]
    _buf[key] = arr
    return arr


def stitch(
    arr: list[dict],
    *,
    msg_id: int = 0,
    grouped_id=None,
    reply_to: int | None = None,
) -> list[dict]:
    if not arr:
        return []
    arr = sorted(arr, key=lambda x: (int(x.get("mid") or 0), float(x.get("ts") or 0)))
    if grouped_id:
        g = [x for x in arr if x.get("gid") is not None and x.get("gid") == grouped_id]
        if g:
            last_ts = float(g[-1].get("ts") or 0)
            extra = [
                x for x in arr
                if x not in g and abs(float(x.get("ts") or 0) - last_ts) <= 90
            ]
            out = g + extra
            out.sort(key=lambda x: (int(x.get("mid") or 0), float(x.get("ts") or 0)))
            return out[-MAX_KEEP:]
    if reply_to:
        want = {int(reply_to), int(msg_id or 0)}
        rel = [
            x for x in arr
            if int(x.get("mid") or 0) in want or x.get("reply") == int(reply_to)
        ]
        if rel:
            return rel
    return arr[-MAX_KEEP:]


def combined_text(arr: list[dict]) -> str:
    parts: list[str] = []
    for x in arr:
        t = (x.get("text") or "").strip()
        if t and t not in parts:
            parts.append(t)
    return "\n".join(parts)
