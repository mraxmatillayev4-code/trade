"""v115 /kanalstat: kanal pip-statistikasi (jonli yig'iladi).

Har kanal xabari kelganda classify qilinadi va append-only JSONL faylga
yoziladi (data/chan_stats.jsonl). MUHIM: kanal o'z tarixidan xabarni
O'CHIRSA ham (BEK FXX SL signallarini o'chiradi!) — bizning yozuv qoladi,
shuning uchun statistika marketingdan haqiqiyroq bo'ladi.

Hodisalar:
  signal — (buy|sell) now / zona berilgan xabar
  claim  — kanalning "+NNpips" da'vosi (tekshirilmaydi, kanalniki!)
  sl     — stop/"slni surdm" yozuvi

summary(days) — har kanal: faol kunlar, da'vo pips jami, o'rtacha kunlik,
stoplar soni, taxminiy sof natija (stop = -60 pip taxminiy).
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "data", "chan_stats.jsonl")

_CLAIM_RX = re.compile(r"\b(\d{1,4})\s*pips?\b", re.I)
_SL_RX = re.compile(r"(^\s*sl\s*$|slni surd|stop qilindi|stop qlindi"
                    r"|\bsl\s+urildi)", re.I)
_SIGNAL_RX = re.compile(r"\b(buy|sell)\s+now+w?\b", re.I)

# taxminiy: bitta stop urilganda o'rtacha yo'qotish (BEK FXX SL 5-7 $ = 50-70p)
AVG_STOP_PIPS = 60.0


def classify(text: str | None) -> list[tuple[str, int]]:
    """Xabarni hodisalarga ajratadi: [(kind, pips), ...]."""
    t = (text or "").strip()
    if not t:
        return []
    out: list[tuple[str, int]] = []
    if _SIGNAL_RX.search(t) and not _CLAIM_RX.search(t):
        out.append(("signal", 0))
    m = _CLAIM_RX.search(t)
    if m:
        try:
            out.append(("claim", int(m.group(1))))
        except (TypeError, ValueError):
            pass
    if _SL_RX.search(t) and not m:
        out.append(("sl", 0))
    return out


def record(ch_key: str, ch_title: str, text: str | None,
           dt: datetime | None = None, path: str | None = None) -> int:
    """Hodisalarni JSONL ga qo'shadi. Yozilgan hodisalar sonini qaytaradi."""
    events = classify(text)
    if not events:
        return 0
    dt = dt or datetime.now(timezone.utc)
    p = path or _PATH
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            for kind, pips in events:
                f.write(json.dumps({
                    "ts": dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "d": dt.strftime("%Y-%m-%d"),
                    "ch": str(ch_key or "")[:64],
                    "title": str(ch_title or ch_key or "")[:80],
                    "kind": kind, "pips": int(pips),
                }, ensure_ascii=False) + "\n")
        return len(events)
    except OSError:
        return 0


def summary(days: int = 30, path: str | None = None,
            today: date | None = None) -> dict:
    """Oxirgi `days` kun uchun har kanal bo'yicha yig'indi.

    Qaytaradi: {ch_key: {title, days_active, signals, claims_total,
    claims_n, sl, avg_per_day, net_est_per_day}}
    """
    p = path or _PATH
    today = today or datetime.now(timezone.utc).date()
    start = today - timedelta(days=max(1, int(days)) - 1)
    agg: dict = defaultdict(lambda: {
        "title": "", "days": set(), "signals": 0,
        "claims_total": 0, "claims_n": 0, "sl": 0,
    })
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                d = e.get("d") or ""
                try:
                    dd = datetime.strptime(d, "%Y-%m-%d").date()
                except ValueError:
                    continue
                if dd < start or dd > today:
                    continue
                ch = str(e.get("ch") or "?")
                a = agg[ch]
                a["title"] = str(e.get("title") or ch)
                a["days"].add(d)
                kind = e.get("kind")
                if kind == "signal":
                    a["signals"] += 1
                elif kind == "claim":
                    a["claims_total"] += int(e.get("pips") or 0)
                    a["claims_n"] += 1
                elif kind == "sl":
                    a["sl"] += 1
    except OSError:
        pass
    out: dict = {}
    for ch, a in agg.items():
        n_days = len(a["days"]) or 1
        avg = a["claims_total"] / n_days
        net = (a["claims_total"] - a["sl"] * AVG_STOP_PIPS) / n_days
        out[ch] = {
            "title": a["title"] or ch,
            "days_active": len(a["days"]),
            "signals": a["signals"],
            "claims_total": a["claims_total"],
            "claims_n": a["claims_n"],
            "sl": a["sl"],
            "avg_per_day": avg,
            "net_est_per_day": net,
        }
    return out


def render(days: int = 30, path: str | None = None) -> str:
    """/kanalstat uchun tayyor matn (HTML)."""
    s = summary(days, path=path)
    if not s:
        return ("📊 <b>Kanal statistikasi</b>\n\n"
                "Hali ma'lumot yo'q — yig'ish v115 dan boshlanadi. "
                "Bir necha kun ishlagach real rasm ko'rinadi.")
    rows = []
    for ch, a in sorted(s.items(), key=lambda kv: -kv[1]["claims_total"]):
        rows.append(
            f"📡 <b>{a['title'] or ch}</b>\n"
            f"   faol kun: {a['days_active']} | signal: {a['signals']} ta\n"
            f"   da'vo: +{a['claims_total']} pip ({a['claims_n']} marta), "
            f"o'rtacha {a['avg_per_day']:+.0f} pip/kun\n"
            f"   stop: {a['sl']} ta → sof taxmin "
            f"{a['net_est_per_day']:+.0f} pip/kun"
        )
    return ("📊 <b>Kanal statistikasi</b> (oxirgi "
            f"{days} kun)\n\n" + "\n\n".join(rows) +
            "\n\n<i>Da'volar kanalniki — bot tekshirmaydi. Lekin kanal "
            "SL xabarini o'chirib tashlasa ham bizda saqlanib qoladi, "
            "shuning uchun stoplar soni haqiqiy. Sof taxmin: stop = "
            f"-{int(AVG_STOP_PIPS)} pip.</i>")
