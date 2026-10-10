#!/usr/bin/env python3
"""kanal_test.py — kanal xabarini offline sinash (botga tegilmaydi).

NIMA QILADI
    Bitta yoki bir nechta xabar matnini `parse_signal` / `is_close_message` /
    `channel_ai` orqali o'tkazib, bot AYNAN nima qilishini ko'rsatadi:
        SIGNAL  → karta yuboriladi + paper trade ochiladi
        CLOSE   → eski bitim yopiladi (EMAS deb sanaladi)
        EMAS    → hech narsa qilinmaydi (hisobotda ➖ bo'ladi)

NEGA KERAK
    Hisobotda "SIGNAL: 0  EMAS: 264" bo'lsa, sabab shu asbob bilan topiladi:
    qaysi xabar o'qilmayapti va nega.

ISHLATISH (loyiha papkasida, .venv yoqilgan holda)
    python kanal_test.py                        # interaktiv: matn yopishtirasiz
    python kanal_test.py "XAUUSD BUY 4415-4411 SL 4405 TP 4430"
    python kanal_test.py --file xabarlar.txt    # har bir xabar --- bilan ajratilgan
    python kanal_test.py --ocr rasm.png         # rasm uchun OCR sinovi (Tesseract kerak)
    python kanal_test.py --check                # tizim tekshiruvi (OCR bor-yo'qligi va h.k.)

Chiqqan matnni admin/men bilan bo'lishing — o'sha formatlar uchun parser
naqshlarini (pattern) aniqlab beraman.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# loyiha ildizini sys.path ga qo'shamiz (boshqa papkadan chaqirilsa ham ishlashi uchun)
ROOT = Path(__file__).resolve().parent
for cand in (ROOT, ROOT.parent):
    if (cand / "app" / "services" / "channel_parse.py").exists():
        sys.path.insert(0, str(cand))
        break

FAIL = 0


def _imports():
    from app.services.channel_parse import is_close_message, parse_signal  # noqa: PLC0415
    ai = None
    try:
        from app.services import channel_ai  # noqa: PLC0415
        ai = channel_ai
    except Exception as exc:  # noqa: BLE001
        print(f"(!) channel_ai yuklanmadi ({exc}) — faqat parser sinaladi\n")
    return parse_signal, is_close_message, ai


def verdict(text: str, parse_signal, is_close_message, ai) -> str:
    """Bot `channel_inbox._run` mantig'i bilan bir xil qaror."""
    p = parse_signal(text)
    closing = is_close_message(text)
    line = []
    if p:
        line.append("SIGNAL")
        det = f"{p.direction} {p.symbol} tf={p.timeframe} entry={p.entry} sl={p.sl} tp={p.tp}"
    else:
        if closing:
            line.append("CLOSE ")
            det = "yopish xabari deb topildi → eski bitim yopiladi, hisobotda EMAS"
        else:
            line.append("EMAS  ")
            det = "hech narsa qilinmaydi (hisobotda ➖ oshadi)"
    ai_txt = ""
    if ai is not None:
        try:
            got = ai.interpret(text, None)
        except Exception as exc:  # noqa: BLE001
            got = None
            ai_txt = f"  [AI xato: {exc}]"
        if got is not None and p is None:
            ai_txt = f"  [AI bo'lsa: SIGNAL {got.direction} {got.symbol} — lekin AI ULANMAGAN]"
    return f"{line[0]} | {det}{ai_txt}"


def one(text: str, ps, icm, ai) -> None:
    global FAIL
    text = (text or "").rstrip()
    if not text.strip():
        return
    print("=" * 78)
    print("XABAR:")
    for ln in text.split("\n")[:12]:
        print("   |", ln)
    print("-" * 78)
    print("NATIJA:", verdict(text, ps, icm, ai))
    if ps(text) is None:
        FAIL += 1
    print()


def check() -> None:
    print("=== TIZIM TEKSHIRUVI ===")
    try:
        from PIL import Image  # noqa: F401, PLC0415
        print("Pillow            : bor ✅")
    except Exception:  # noqa: BLE001
        print("Pillow            : YO'Q ❌  →  pip install pillow")
    try:
        import pytesseract  # noqa: PLC0415
        print("pytesseract (py)  : bor ✅")
        try:
            v = pytesseract.get_tesseract_version()
            print(f"Tesseract (binary): bor ✅  ({v})")
        except Exception as exc:  # noqa: BLE001
            print("Tesseract (binary): YO'Q ❌  ← RASM SIGNALLARI O'QILMAYDI!")
            print(f"   xato: {exc}")
            print("   Windows: https://github.com/UB-Mannheim/tesseract/wiki dan o'rnating,")
            print("   yoki:  winget install UB-Mannheim.TesseractOCR")
            print('   keyin .env ga:  TESSERACT_CMD=C:\\Program Files\\Tesseract-OCR\\tesseract.exe')
    except Exception:  # noqa: BLE001
        print("pytesseract (py)  : YO'Q ❌  →  pip install pytesseract")
    from app.services.channel_parse import parse_signal  # noqa: PLC0415
    print("channel_parse     : bor ✅")
    try:
        import pathlib  # noqa: PLC0415

        from app.services import channel_ai  # noqa: PLC0415
        inbox_py = pathlib.Path(channel_ai.__file__).with_name("channel_inbox.py")
        src = inbox_py.read_text(encoding="utf-8", errors="replace") if inbox_py.exists() else ""
        if "interpret_async" in src:
            print("channel_ai        : bor va ULANGAN ✅ (channel_inbox._run ichida)")
        else:
            print("channel_ai        : bor (lekin bot uni CHAQIRMAYDI — o'lik kod)")
    except Exception as exc:  # noqa: BLE001
        print(f"channel_ai        : yuklanmadi ({exc})")
    print()
    print("Namuna (parser ishlashini tasdiqlash):")
    one("XAUUSD BUY 4415-4411\nSL 4405\nTP 4430", parse_signal, lambda t: False, None)


def main() -> None:
    ap = argparse.ArgumentParser(description="Kanal xabarini offline sinash")
    ap.add_argument("text", nargs="?", help="xabar matni (iqtibos ichida)")
    ap.add_argument("--file", help="har bir xabar '---' qatori bilan ajratilgan fayl")
    ap.add_argument("--ocr", help="rasm fayli (OCR sinovi)")
    ap.add_argument("--check", action="store_true", help="tizim tekshiruvi")
    args = ap.parse_args()

    if args.check:
        check()
        return

    ps, icm, ai = _imports()

    if args.ocr:
        from app.services.channel_ocr import ocr_image  # noqa: PLC0415
        data = Path(args.ocr).read_bytes()
        got = ocr_image(data) or ""
        print(f"RASM: {args.ocr}  ({len(data)} bayt)")
        print("-" * 78)
        print("OCR natijasi:" if got else "OCR BO'SH QAYTARDI — Tesseract o'rnatilmagan yoki rasm o'qilmadi!")
        print(got[:1500])
        print("-" * 78)
        if got:
            one(got, ps, icm, ai)
        return

    if args.file:
        raw = Path(args.file).read_text(encoding="utf-8", errors="replace")
        for chunk in raw.split("\n---"):
            one(chunk.strip(), ps, icm, ai)
        print(f"XULOSA: {FAIL} ta xabar EMAS (yuqoriga qarang)")
        return

    if args.text:
        one(args.text, ps, icm, ai)
        return

    print("Xabar matnini yopishtiring (tugatish: bo'sh qator + Enter yoki Ctrl+C).")
    print("Botga kelgan xabarni nusxalab qo'ying — matni qanday bo'lsa shundayligicha.")
    print()
    buf: list[str] = []
    while True:
        try:
            line = input()
        except (EOFError, KeyboardInterrupt):
            break
        if not line.strip():
            if buf:
                one("\n".join(buf), ps, icm, ai)
                buf = []
            else:
                break
            continue
        buf.append(line)
    if buf:
        one("\n".join(buf), ps, icm, ai)


if __name__ == "__main__":
    main()
