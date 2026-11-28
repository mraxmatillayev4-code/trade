"""Rasm/skrinshotdagi yozuvni o'qish (Tesseract). Yo'q bo'lsa — bo'sh qator.

v48: tezlashtirildi — katta rasm 1600px ga kichraytiriladi, keraksiz OCR urinishlar o'tkaziladi.
v88: TILLAR — `eng+rus` (kanallar o'zbek lotin va rus tilida yozadi). Rus tili
     o'rnatilmagan bo'lsa avtomatik faqat `eng` ga tushadi. `OCR_LANG` env bilan
     o'zgartirish mumkin (masalan `OCR_LANG=eng+rus+uzb`). Har o'qish natijasi
     tozalanadi (takroriy bo'sh joy, faqat-belgi qatorlar olib tashlanadi).
"""
from __future__ import annotations

import io
import os
import shutil
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger(__name__)

_TESS_DONE = False
_TESS_EXE = ""
_LANG_OK = ""
_WIN_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    r"C:\Users\Public\Tesseract-OCR\tesseract.exe",
)


def available() -> bool:
    """v89: tesseract o'rnatilganmi (bot hisobotida ko'rsatish uchun)."""
    try:
        import pytesseract
        _setup_cmd(pytesseract)
        pytesseract.get_tesseract_version()
        return True
    except Exception:  # noqa: BLE001
        return False


def _langs(pytesseract) -> str:
    """v88: ishlaydigan til birikmasini topadi va eslab qoladi (`eng+rus` -> `eng`)."""
    global _LANG_OK
    if _LANG_OK:
        return _LANG_OK
    want = (os.environ.get("OCR_LANG") or "eng+rus").strip() or "eng"
    for cand in (want, "eng"):
        try:
            pytesseract.get_tesseract_version()
            got = pytesseract.get_languages(config="") or []
            need = [x for x in cand.split("+") if x]
            if need and all(n in got for n in need):
                _LANG_OK = cand
                logger.info("[CH-OCR] tillar: %s (mavjud: %s)", _LANG_OK, ",".join(sorted(got))[:80])
                return _LANG_OK
        except Exception as exc:  # noqa: BLE001
            logger.info("[CH-OCR] til tekshiruvi (%s): %s", cand, exc)
    _LANG_OK = "eng"
    return _LANG_OK


def _clean(text: str) -> str:
    """v88: OCR matnini tozalaydi — keraksiz belgilar qatorlari olib tashlanadi."""
    out: list[str] = []
    for raw in str(text or "").splitlines():
        s = " ".join(str(raw).split())
        if not s:
            continue
        alnum = sum(1 for c in s if c.isalnum())
        if alnum < 2:                       # faqat chiziq/emoji qatorlari
            continue
        out.append(s)
    return "\n".join(out)


def _setup_cmd(pytesseract) -> None:
    """Tesseract binari qayerdaligini topib pytesseract ga ko'rsatadi.

    Windows'da pytesseract o'zi topa olmaydi -> TESSERACT_CMD env yoki standart yo'l.
    """
    global _TESS_DONE, _TESS_EXE
    if _TESS_DONE:
        return
    _TESS_DONE = True
    try:
        env = (os.environ.get("TESSERACT_CMD") or "").strip().strip('"')
        if env and Path(env).exists():
            pytesseract.pytesseract.tesseract_cmd = env
            _TESS_EXE = env
            logger.info("[CH-OCR] tesseract (env TESSERACT_CMD): %s", env)
            return
        for p in _WIN_PATHS:
            if Path(p).exists():
                pytesseract.pytesseract.tesseract_cmd = p
                _TESS_EXE = p
                logger.info("[CH-OCR] tesseract topildi: %s", p)
                return
        w = shutil.which("tesseract")
        if w:
            _TESS_EXE = w
            logger.info("[CH-OCR] tesseract PATH ichida: %s", w)
            return
        logger.warning(
            "[CH-OCR] tesseract o'rnatilmagan - rasm/skrinshot o'qilmaydi. "
            "Windows: winget install -e --id UB-Mannheim.TesseractOCR"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH-OCR] tesseract sozlash: %s", exc)


def ocr_image(data: bytes | None) -> str:
    if not data:
        return ""
    try:
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps
        img = Image.open(io.BytesIO(data))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        w, h = img.size
        if w < 1000:
            scale = max(2, int(1100 / max(w, 1)))
            img = img.resize((w * scale, h * scale))
        elif w > 1600:
            img = img.resize((1600, max(1, int(h * 1600 / w))))
        gray = ImageOps.grayscale(img)
        gray = ImageEnhance.Contrast(gray).enhance(2.0)
        gray = gray.filter(ImageFilter.SHARPEN)
        texts: list[str] = []
        try:
            import pytesseract
            _setup_cmd(pytesseract)
            # v48: tez rejim — birinchi urinish yetarli bo'lsa qolganini o'tkazamiz
            lang = _langs(pytesseract)
            for idx, cfg in enumerate(("--psm 6", "--psm 11", "--psm 4")):
                try:
                    t = pytesseract.image_to_string(gray, lang=lang, config=cfg) or ""
                except Exception:  # noqa: BLE001
                    try:
                        t = pytesseract.image_to_string(gray, config=cfg) or ""
                    except Exception:  # noqa: BLE001
                        t = ""
                t = " ".join(t.split())
                if t and t not in texts:
                    texts.append(t)
                if idx == 0 and len(t) >= 60:
                    break
        except Exception as exc:  # noqa: BLE001
            logger.info("[CH-OCR] tesseract yo'q/xato: %s", exc)
            return ""
        blob = _clean("\n".join(texts))
        if blob:
            logger.info("[CH-OCR] %d belgi o'qildi", len(blob))
        return blob[:4000]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH-OCR] rasm: %s", exc)
        return ""
