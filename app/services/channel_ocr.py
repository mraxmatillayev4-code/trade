"""Rasm/skrinshotdagi yozuvni o'qish (Tesseract). Yo'q bo'lsa — bo'sh qator."""
from __future__ import annotations

import io

from app.core.logging import get_logger

logger = get_logger(__name__)


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
        gray = ImageOps.grayscale(img)
        gray = ImageEnhance.Contrast(gray).enhance(2.0)
        gray = gray.filter(ImageFilter.SHARPEN)
        texts: list[str] = []
        try:
            import pytesseract
            for cfg in ("--psm 6", "--psm 11", "--psm 4"):
                try:
                    t = pytesseract.image_to_string(gray, lang="eng", config=cfg) or ""
                except Exception:  # noqa: BLE001
                    t = pytesseract.image_to_string(gray, config=cfg) or ""
                t = " ".join(t.split())
                if t and t not in texts:
                    texts.append(t)
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
