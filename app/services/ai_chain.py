# -*- coding: utf-8 -*-
"""v104: AI ZANJIR — GROQ (bepul) -> GEMINI (user kaliti) -> LOKAL parser.

Biri ishlamasa ikkinchisi davom etadi:
1) GROQ  — mutlaqo bepul (console.groq.com kaliti, env GROQ_API_KEY yoki
   settings.ai_api_key). Kalit bo'lmasa bu qadam SESSIZ o'tkazib yuboriladi.
2) GEMINI — v102/v103 dagi gemini_ai (user kaliti, flash-latest kaskad).
3) LOKAL — channel_parse/local_ai (kalit shart emas; chaqiruvchi oqimda
   zanjirdan OLDIN ishlaydi, shuning uchun bu modul faqat 1-2 qadamlar).

/aitest buyrug'i shu zanjirni JONLI tekshiradi: kalit bor/yo'q, javob,
tezlik, model va namuna signalni kim o'qigani ko'rinadi — deploy
yangilanganmi shundan ham bilib olinadi.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time

import httpx

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Bepul tarif (2026): llama-3.3-70b-versatile 30 RPM / 1000 kun,
# gpt-oss-120b 30 RPM / 1000 kun, llama-3.1-8b-instant 30 RPM / 14400 kun.
# Tartib: kuchlisi birinchi, limiti kengasi zaxira.
_GROQ_MODELS = ("llama-3.3-70b-versatile", "openai/gpt-oss-120b",
                "llama-3.1-8b-instant", "groq/compound-mini")
_GOOD_GROQ: dict = {"name": ""}

_CAP_G_H = 60          # soatiga groq extract limiti (bepul tarif himoyasi)
_cap_g: dict = {"t": 0.0, "n": 0}
_LAST_ERR: dict = {}   # v106: oxirgi xato sababi (/aitest diagnostikasi)


def _mask_key(k: str) -> str:
    k = (k or "").strip()
    if not k:
        return "yo'q"
    return f"{k[:6]}...({len(k)} belgi)"


async def _ping(fn, prompt: str, **kw):
    raw = None
    for _i in range(2):
        raw = await fn(prompt, **kw)
        if raw:
            return raw
        await asyncio.sleep(2)
    return raw


def groq_key() -> str:
    """GROQ_API_KEY env -> settings.ai_api_key (AI_API_KEY env) tartibida."""
    k = (os.environ.get("GROQ_API_KEY") or "").strip()
    if not k:
        try:
            from app.core.config import get_settings
            k = (get_settings().ai_api_key or "").strip()
        except Exception:  # noqa: BLE001
            k = ""
    return k


def groq_url() -> str:
    try:
        from app.core.config import get_settings
        u = (get_settings().ai_api_url or "").strip()
        if u:
            return u
    except Exception:  # noqa: BLE001
        pass
    return _GROQ_URL


def looks_candidate(text: str) -> bool:
    """gemini_ai dagi filtr (raqam/yo'nalish izi) — zanjir uchun umumiy."""
    from app.services import gemini_ai
    return gemini_ai.looks_candidate(text or "")


async def _groq_call(prompt: str, *, system: str = "", json_mode: bool = False,
                     history: list | None = None, temperature: float = 0.0,
                     max_tokens: int = 900) -> str | None:
    """OpenAI-mos chaqiruv (Groq). Kalit yo'q/xato bo'lsa None."""
    key = groq_key()
    if not key:
        return None
    msgs: list = []
    if system:
        msgs.append({"role": "system", "content": system})
    for h in (history or []):
        role = "user" if h.get("role") == "user" else "assistant"
        msgs.append({"role": role, "content": str(h.get("text") or "")})
    msgs.append({"role": "user", "content": prompt})
    models = (_GOOD_GROQ["name"],) + _GROQ_MODELS if _GOOD_GROQ["name"] \
        else _GROQ_MODELS
    async with httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=10.0)) as cl:
        for m in dict.fromkeys(models):
            if not m:
                continue
            body: dict = {"model": m, "messages": msgs,
                          "temperature": temperature, "max_tokens": max_tokens}
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            try:
                r = await cl.post(
                    groq_url(),
                    headers={"Authorization": f"Bearer {key}",
                             "Content-Type": "application/json"},
                    json=body,
                )
                if r.status_code != 200:
                    _LAST_ERR["groq"] = f"HTTP {r.status_code}"
                    continue
                txt = (((r.json().get("choices") or [{}])[0]
                        .get("message") or {}).get("content") or "")
                if txt.strip():
                    _GOOD_GROQ["name"] = m
                    return txt
            except Exception as exc:  # noqa: BLE001
                _LAST_ERR["groq"] = f"{type(exc).__name__}"
                continue
    _LAST_ERR.setdefault("groq", "javob bo'sh")
    return None


def _verdict_answered(raw: str) -> bool:
    """Javobda aniq verdict (SIGNAL/EMAS) bormi — Groq ISHLADIMI shuni biladi."""
    try:
        d = json.loads(raw)
    except Exception:  # noqa: BLE001
        m = re.search(r"\{.*\}", raw or "", re.S)
        if not m:
            return False
        try:
            d = json.loads(m.group(0))
        except Exception:  # noqa: BLE001
            return False
    return str(d.get("verdict") or "").upper() in ("SIGNAL", "EMAS")


async def extract_signal(text: str) -> dict | None:
    """Zanjir: GROQ extract -> GEMINI extract -> None (lokal oldin ishlagan)."""
    from app.services import gemini_ai
    if not looks_candidate(text or ""):
        return None
    # 1) GROQ (kalit bo'lsa)
    if groq_key():
        now = time.time()
        if now - _cap_g["t"] > 3600:
            _cap_g["t"] = now
            _cap_g["n"] = 0
        if _cap_g["n"] < _CAP_G_H:
            _cap_g["n"] += 1
            for _try in range(2):      # limit/timeout bo'lsa bir marta qayta
                raw = await _groq_call((text or "")[:1500],
                                       system=gemini_ai._EXTRACT_SYS,
                                       json_mode=True)
                got = gemini_ai._parse_extract(raw or "")
                if got:
                    got["src"] = "GROQ"
                    return got
                if raw and _verdict_answered(raw):
                    return None        # Groq aniq EMAS dedi — ishonamiz
                if raw:
                    continue           # javob shilqim — qayta/keyingi provider
    # 2) GEMINI
    got = await gemini_ai.extract_signal(text or "")
    if got:
        got.setdefault("src", "GEMINI")
    return got


async def chat(history: list, user_text: str, context: str) -> str | None:
    """Zanjir: GROQ suhbat -> GEMINI suhbat -> None (lokal fallback common.da)."""
    from app.services import gemini_ai
    if groq_key():
        sys_g = gemini_ai._CHAT_SYS.replace(" (Gemini Flash)", "")
        got = await _groq_call((user_text or "")[:2000],
                               system=sys_g + "\n" + (context or "noma'lum"),
                               history=history, temperature=0.4)
        if got:
            return got
    return await gemini_ai.chat(history, user_text, context)


async def aitest() -> str:
    """/aitest hisoboti: har provider JONLI tekshiriladi (kalit, javob, tezlik)."""
    from app.services import gemini_ai
    try:
        from app.services import local_ai
        ver = local_ai.__version__
    except Exception:  # noqa: BLE001
        ver = "?"
    L: list = [f"🧪 AI TEST — {ver}", "🔗 Zanjir: GROQ → GEMINI → LOKAL"]
    # 1) GROQ
    gk = groq_key()
    if gk:
        t0 = time.time()
        raw = await _ping(_groq_call, "Faqat bitta so'z yoz: OK",
                          temperature=0.0, max_tokens=8)
        dt = time.time() - t0
        if raw:
            L.append(f"✅ GROQ: javob berdi ({dt:.1f}s, model "
                     f"{_GOOD_GROQ.get('name') or '?'}) — {raw.strip()[:30]}")
        else:
            L.append(f"❌ GROQ: kalit {_mask_key(gk)}, javob yo'q — sabab: "
                     f"{_LAST_ERR.get('groq', 'noma-lum')} (limit/tarmoq/model)")
    else:
        L.append("⚪ GROQ: kalit yo'q (env GROQ_API_KEY) — o'tkazib yuborildi")
    # 2) GEMINI
    mk = gemini_ai.get_key()
    if mk:
        t0 = time.time()
        raw = await _ping(gemini_ai._call, "Faqat bitta so'z yoz: OK",
                          temperature=0.0)
        dt = time.time() - t0
        if raw:
            L.append(f"✅ GEMINI: javob berdi ({dt:.1f}s, model "
                     f"{gemini_ai._GOOD_MODEL.get('name') or '?'}) — "
                     f"{raw.strip()[:30]}")
        else:
            L.append(f"❌ GEMINI: kalit {_mask_key(mk)}, javob yo'q — sabab: "
                     f"{gemini_ai._LAST_ERR.get('gemini', 'noma-lum')} "
                     f"(limit/tarmoq/model)")
    else:
        L.append("❌ GEMINI: kalit yo'q (Render env: GEMINI_API_KEY)")
    # 3) Namuna signalni zanjir o'qiy oladimi
    sample = "XAUUSDT BUY zona 4139-4140 SL 4137.9 TP1 4151.5"
    got = await extract_signal(sample)
    if got:
        L.append(f"✅ SIGNAL TEST: {got.get('src')} o'qidi — "
                 f"{got.get('direction')} {got.get('symbol')} "
                 f"entry={got.get('entry')} sl={got.get('sl')}")
    else:
        L.append("❌ SIGNAL TEST: zanjir namuna signalni o'qiy olmadi")
    L.append("🧠 LOKAL parser: doim ishlaydi (kalit shart emas)")
    if not groq_key():
        L.append("💡 Groq bepul kalit: console.groq.com → API Keys → "
                 "Render env: GROQ_API_KEY")
    return "\n".join(L)
