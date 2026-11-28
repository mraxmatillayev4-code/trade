# -*- coding: utf-8 -*-
"""v102: Gemini AI — signal o'qishning IKKINCHI KO'ZI va admin suhbati.

User bergan kalit (Gemini Flash, tekin). Lokal parser o'qiy olmagan
xabarni Gemini o'qiydi (JSON sxema bo'yicha); admin bot holatini
so'rasa — kontekst bilan javob beradi.

Xavfsizlik (v105): kalit FAQAT env (GEMINI_API_KEY) -> settings; koddagi zaxira OLIB TASHLANGAN.
Limit: soatiga ko'pi bilan 30 ta extract chaqiruvi (tekin tarif).
"""
from __future__ import annotations

import json
import re
import time

import httpx

# v105: kalit KOD ICHIDA saqlanmaydi — GitHub Push Protection (GH013) sirlarni
# push qildirmaydi. Kalit FAQAT env/settings dan: Render -> GEMINI_API_KEY.
# Kalit bo'lmasa Gemini qadami sessiz o'tadi (zanjir Groq/lokal bilan davom).
_FALLBACK_KEY = ""

# v103: 1.5-flash va 2.0-flash Google tomonidan O'CHIRILGAN (404) —
# birinchi ishlaydigan model: gemini-flash-latest.
_MODELS = ("gemini-flash-latest", "gemini-2.5-flash-lite",
           "gemini-1.5-flash", "gemini-2.0-flash")
_GOOD_MODEL: dict = {"name": ""}
_LAST_ERR: dict = {}   # v106: /aitest diagnostikasi
_URL = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"

_CAP_H = 30           # soatiga extract limiti
_cap: dict = {"t": 0.0, "n": 0}

_CAND = re.compile(r"(buy|sell|sel|sot|long|short|zona|zone|sl|stop|tp\s*\d|"
                   r"\d{1,7}[.,]\d{1,7}\s*-\s*\d{1,7}[.,]\d{1,7}|\d+\s*pip)",
                   re.I)


def get_key() -> str:
    import os
    k = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not k:
        try:
            from app.core.config import get_settings
            k = (get_settings().gemini_api_key or "").strip()
        except Exception:  # noqa: BLE001
            k = ""
    return k or _FALLBACK_KEY


def looks_candidate(text: str) -> bool:
    """Gemini ga yuborishga arziydimi (raqam/yo'nalish izi bor)."""
    t = text or ""
    return bool(_CAND.search(t)) and 3 <= len(t) <= 1500


async def _call(prompt: str, *, system: str = "", json_mode: bool = False,
                history: list | None = None, temperature: float = 0.0) -> str | None:
    key = get_key()
    if not key:
        return None
    body: dict = {"contents": []}
    if system:
        body["system_instruction"] = {"parts": [{"text": system}]}
    for h in (history or []):
        role = "user" if h.get("role") == "user" else "model"
        body["contents"].append({"role": role,
                                  "parts": [{"text": str(h.get("text") or "")}]})
    body["contents"].append({"role": "user", "parts": [{"text": prompt}]})
    body["generationConfig"] = {"temperature": temperature}
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    models = (_GOOD_MODEL["name"],) + _MODELS if _GOOD_MODEL["name"] else _MODELS
    async with httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=10.0)) as cl:
        for m in dict.fromkeys(models):
            if not m:
                continue
            try:
                r = await cl.post(
                    _URL.format(m=m),
                    headers={"x-goog-api-key": key,
                             "Content-Type": "application/json"},
                    json=body,
                )
                if r.status_code != 200:
                    _LAST_ERR["gemini"] = f"HTTP {r.status_code}"
                    continue
                data = r.json()
                parts = (data.get("candidates") or [{}])[0].get("content", {}) \
                    .get("parts") or []
                txt = "".join(pt.get("text") or "" for pt in parts)
                if txt.strip():
                    _GOOD_MODEL["name"] = m
                    return txt
            except Exception as exc:  # noqa: BLE001
                _LAST_ERR["gemini"] = f"{type(exc).__name__}"
                continue
    _LAST_ERR.setdefault("gemini", "javob bo'sh")
    return None


def _parse_extract(raw: str) -> dict | None:
    """Gemini JSON javobini tekshiradi: SIGNAL bo'lsa dict, aks holda None."""
    try:
        d = json.loads(raw)
    except Exception:  # noqa: BLE001
        m = re.search(r"\{.*\}", raw or "", re.S)
        if not m:
            return None
        try:
            d = json.loads(m.group(0))
        except Exception:  # noqa: BLE001
            return None
    if str(d.get("verdict") or "").upper() != "SIGNAL":
        return None
    direction = str(d.get("direction") or "").upper()
    if direction not in ("BUY", "SELL"):
        return None
    entry = d.get("entry")
    zlo, zhi = d.get("zone_low"), d.get("zone_high")
    try:
        entry = float(entry) if entry not in (None, "") else None
        zlo = float(zlo) if zlo not in (None, "") else None
        zhi = float(zhi) if zhi not in (None, "") else None
    except (TypeError, ValueError):
        return None
    if entry is None and (zlo is None or zhi is None):
        return None
    def _f(v):
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None
    tps = [_f(x) for x in (d.get("tps") or [])]
    tps = [x for x in tps if x]
    return {
        "verdict": "SIGNAL", "direction": direction,
        "symbol": str(d.get("symbol") or "XAUUSDT").upper() or "XAUUSDT",
        "entry": entry, "sl": _f(d.get("sl")),
        "sl_pips": _f(d.get("sl_pips")),
        "tps": tps, "tps_pips": [_f(x) for x in (d.get("tps_pips") or []) if _f(x)],
        "zone": (zlo, zhi) if (zlo and zhi) else None,
        "src": "GEMINI",
    }


_EXTRACT_SYS = (
    "Sen trading signal ajratib oluvchi yordamchisan. Telegram kanal postini "
    "olasan. Agar bu HAQIQIY savdo signali bolsa (yo'nalish VA kirish/zona VA "
    "SL yoki TP bor), faqat JSON qaytar: "
    '{"verdict":"SIGNAL","direction":"BUY|SELL","symbol":"XAUUSDT", '
    '"entry":4139.5,"zone_low":4139.0,"zone_high":4140.0,"sl":4137.9,'
    '"sl_pips":8,"tps":[4151.5],"tps_pips":[60,200]}. '
    "Pips yozilgan bolsa tps_pips/sl_pips ga yoz, narx bolsa entry/sl/tps ga. "
    "Suhbat, sharh, natija, reklama bolsa: "
    '{"verdict":"EMAS","reason":"..."}. Boshqa hech narsa yozma.')


async def extract_signal(text: str) -> dict | None:
    """Lokal parser o'qiy olmagan postni Gemini o'qiydi."""
    now = time.time()
    if now - _cap["t"] > 3600:
        _cap["t"] = now
        _cap["n"] = 0
    if _cap["n"] >= _CAP_H:
        return None
    if not looks_candidate(text):
        return None
    _cap["n"] += 1
    for _try in range(2):          # v102: limit/timeout bo'lsa bir marta qayta
        raw = await _call((text or "")[:1500], system=_EXTRACT_SYS,
                          json_mode=True)
        got = _parse_extract(raw or "")
        if got:
            return got
        if raw:
            return None          # javob bor, lekin SIGNAL emas
    return None


_CHAT_SYS = (
    "Sen SINO trading botining ichki yordamchisan (Gemini Flash). "
    "Admin senga bot haqida so'raydi: qanday ishlayapti, nima ko'ryapti, "
    "muammolar. Javobing qisqa, aniq, o'zbek tilida, texnik terminlarni "
    "oddiy tushuntir. Quyidagi HOZIRGI HOLAT ma'lumotidan foydalan:")


async def chat(history: list, user_text: str, context: str) -> str | None:
    for _try in range(2):          # v103: limit/timeout bo'lsa qayta urinish
        got = await _call((user_text or "")[:2000],
                          system=_CHAT_SYS + "\n" + (context or "noma'lum"),
                          history=history, temperature=0.4)
        if got:
            return got
    return None
