"""Rasm/skrinshotdagi yozuvni o'qish (Tesseract). Yo'q bo'lsa — bo'sh qator.

v48: tezlashtirildi — katta rasm 1600px ga kichraytiriladi, keraksiz OCR urinishlar o'tkaziladi.
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
_WIN_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    r"C:\Users\Public\Tesseract-OCR\tesseract.exe",
)


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
            for idx, cfg in enumerate(("--psm 6", "--psm 11", "--psm 4")):
                try:
                    t = pytesseract.image_to_string(gray, lang="eng", config=cfg) or ""
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
        blob = "\n".join(texts)
        if blob:
            logger.info("[CH-OCR] %d belgi o'qildi", len(blob))
        return blob[:4000]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CH-OCR] rasm: %s", exc)
        return ""
