"""v76: «SINO AI tayyor» xabari — TO'G'RI versiya bilan va FAQAT BIR MARTA.

Muammo (foydalanuvchi shikoyati): har restart/deploy da eski «tayyor (v72)»
xabari qayta-qayta kelardi. Yechim:
  * matn endi local_ai.__version__ dan olinadi — hech qachon eskirib qolmaydi;
  * har bir versiya uchun FAQAT BIR MARTA yuboriladi (bazada eslab qolinadi).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select

from app.database.models.system import SystemLog

COMPONENT = "boot"


def version() -> str:
    """Masalan: 'SINO-LAI-76'."""
    from app.services import local_ai
    return str(getattr(local_ai, "__version__", "SINO-LAI-?"))


def label() -> str:
    """'SINO-LAI-76' -> 'v76'. Raqam bo'lmasa — versiyaning o'zi."""
    ver = version()
    tail = ver.rsplit("-", 1)[-1]
    return f"v{tail}" if tail.isdigit() else ver


def build_text(cmds: list[str] | None = None) -> str:
    """Tayyor xabari: qisqa, faqat amaldagi imkoniyatlar (v76 kontrakti)."""
    lines = [
        f"\u2705 <b>SINO AI tayyor ({label()})</b>",
        "\u2022 \U0001F50E <b>Jonli kuzatuv</b> \u2014 pastdagi asosiy tugma: "
        "lotlarni qo'lda yopish ham shu yerda.",
        "\u2022 \U0001F3E6 <b>Broker</b>: /broker \u2014 MT5 (avval DEMO, keyin REAL).",
        "\u2022 \U0001F4E6 <b>Lot hajmi</b>: /lot \u2014 necha lotdan ochilishini "
        "O\u2019ZINGIZ belgilaysiz (risk foizi YO\u2019Q).",
        "\u2022 \U0001F3AF <b>Sniper (oltin)</b>: /sniper \u2014 SNR+ICT+SMC "
        "skaneri, alohida 50$ hisob (tugma bilan yoqiladi/o\u2019chiriladi).",

        "\u2022 \u26A1 <b>KANAL = ZONA KUTILADI (v95)</b>: kanal signaliga "
        "BOT STRATEGIYASI QO\u2018LLANMAYDI. Zona/narx AYTILGAN bo\u2018lsa "
        "\u2014 shu zona kutiladi (\u00ABKIRISH KUTILMOQDA\u00BB), narx "
        "eskirgan/uzoq bo\u2018lsa kirilmaydi (quvish yo\u2018q). Zona "
        "aytilMAGAN bo\u2018lsa \u2014 darhol bozor narxida. "
        "\u00ABKIRISH BO\u2018LMADI\u00BB / \u00ABSAVDO OCHILMADI\u00BB "
        "kartalari yuborilmaydi. Karta IKKI XIL: \U0001F4E1 KANAL (tekshiruvsiz) "
        "va \U0001F916 BOT O\u2018ZI (SNR+ICT+SMC, M1).\n"
        "\u2022 \U0001F5BC <b>RASM/OCR SIGNAL EMAS (v95)</b>: kanal rasmi yoki "
        "OCR matni signal BERMAYDI \u2014 faqat haqiqiy MATN signal manbasi. "
        "SL/TP aytilmagan bo\u2018lsa: SL 10 pip, TP1 40 pip, TP2 50 pip; "
        "Lot1 TP1 da yopiladi, Lot2 TP2 ga, bormasa 40\u201350 pip orasida "
        "(pol = TP1). SL teskari tomonda bo\u2018lsa signal RAD etiladi "
        "(hisobga yozilmaydi).\n"
        "\u2022 \U0001F510 <b>ACCESS (v97)</b>: admin menyudagi \u00AB\U0001F510 Access (ro\u2018yxat)\u00BB tugmasi orqali ID qo\u2018shadi/o\u2018chiradi (buyruq bilan ham: /access add ID signal N \u2014 yoki \u2014 /access add ID kun N). Har ID ga limit BITTA turda: <b>nechta signal</b> YOKI <b>necha kun</b> \u2014 ikkalasi bir vaqtda emas. Kun limiti FAQAT signal berilgan kunlarni ayiradi (signal bo\u2018lmagan kun hisobdan ketmaydi). Limit tugasa signal to\u2018xtaydi.\n"
        "\u2022 \U0001F465 <b>ODAMLAR SONI</b> va \U0001F4E2 <b>HAMMAGA XABAR</b> \u2014 yangi tugmalar: botga nechta odam kirganini ko\u2018rsatadi va ro\u2018yxatdagi barchaga bir bosishda xabar yuboradi (tasdiqlash bilan).\n"
        "\u2022 \U0001F4E1 <b>KANAL PARSE v107</b>: 5 kanal dumpi bilan tekshirildi - GOLD KING nuqtali format 16/16, gold_signals ENTER/STOP LOSS/TAKE PROFIT, anabel Goal/Target/Safe Stop Loss, lanafx Entry/SL - hammasi oqiladi. TP pip bilan yozilgan kanallar (TP1: 50 pip) endi narxga ogirildi (XAUUSD pip = 0.1). Natija postlari (TP HIT, PIPS PROFIT, Done) signal EMAS.\n"
        "\u2022 \U0001F9DF <b>ZOMBI HIMOYASI (v106)</b>: signal nofaol bolsa ham ochiq qolgan lotlar va 48 soatdan eski ochiq lotlar AVTOMATIK bozor narxida yopiladi \u2014 3 kunlik ochiq bitim endi imkonsiz. Sniper narx ESKIRGAN bolsa (feed o\u2018lgan) bozordan kirmaydi. GOLD KING kabi nuqtali formatlar (BUYY.NOW.4422, TP\u00b9 4426, SLL 4412) lokal o\u2018qiladi. /aitest endi xato SABABIni (HTTP kod) va kalit prefiksini ko\u2018rsatadi.\n"
        "\u2022 \U0001F517 <b>AI ZANJIR (v104)</b>: signal o\u2018qish va /ai endi ZANJIR bilan ishlaydi: <b>GROQ</b> (mutlaqo bepul kalit, env GROQ_API_KEY) \u2192 <b>GEMINI</b> \u2192 LOKAL parser \u2014 biri ishlamasa ikkinchisi davom etadi. Yangi <b>/aitest</b> buyrug\u2018i zanjirni JONLI tekshiradi (kalit, javob, tezlik, namuna signal) va VERSIYAni ko\u2018rsatadi \u2014 deploy yangilanganmi shundan bilasiz.\n"
        "\u2022 \U0001F6D1 <b>KARTA TOZALIGI (v103)</b>: savdo ochilmagan signal uchun NATIJA kartasi YUBORILMAYDI (bekor/rad/muddat \u2014 faqat log). /ai endi DOIM javob beradi: Gemini cheklanganda ham lokal holat xulosasi chiqadi; ishlaydigan model avtomatik tanlanadi (gemini-flash-latest).\n"
        "\u2022 \U0001F916 <b>GEMINI AI (v102)</b>: lokal parser o\u2018qiy olmagan postni Gemini Flash o\u2018qiydi (user kaliti, tekin) — signal bitta ham qolib ketmaydi. Adminda <b>/ai</b> buyrug\u2018i va \u00AB\U0001F916 AI suhbat\u00BB tugmasi: bot holati, ko\u2018rayotgan narsalari va muammolar haqida jonli javob.\n"
        "\u2022 \U0001F9E9 <b>SIGNAL O\u2018QISH (v101)</b>: bo\u2018lib yozilgan signal yig\u2018iladi (\u00ABSell now\u00BB + \u00AB69-73\u00BB + \u00AB76sl\u00BB = bitta signal, 60 soniya buffer); scalp formatlar o\u2018qiladi (\u00AB15-12 buy sl 25pip Tp1 23\u00BB, TP pipsda, \u2705 belgili); symbol yozilmagan signal jonli narxlar bo\u2018yicha topiladi (1075 juftlik, MEXC public); o\u2018z savdosi haqidagi post (\u00ABfull kirdim/sell\u00BB) signal EMAS. Bitta ham signal qolib ketmaydi.\n"
        "\u2022 \U0001F30A <b>BOZOR DARAJALARI (v100)</b>: kanal SL/TP aytmagan bo\u2018lsa, endi bot bozorning o\u2018zini tekshiradi \u2014 SL oxirgi 50 shamning swing nuqtasi ortida (yoki 1.5\u00D7ATR), TP lar riskning 2R/3R/4R karralari. Bozor ma\u2018lumoti bo\u2018lmasa eski 10/40/50 pip qoidasi saqlanadi. Kartada manba ko\u2018rsatiladi: (kanal) / (bozor ATR) / (standart).\n"
        "\u2022 \U0001F6E1 <b>DARAJALAR HIMOYASI (v99)</b>: entry almashganda (bozor/fill) SL va TP lar YANGI kirishga qayta tekshiriladi \u2014 SL teskari tomonda qolsa signal RAD etiladi (karta yuborilmaydi, hisobga yozilmaydi). Eski/nosog\u2018lom darajali ochiq signal topilsa \u2014 pozitsiyalar kirish narxida yopilib, signal bekor qilinadi. Endi \u00ABfaqat zararsiz\u00BB yopilish va g\u2018alati 1R/TP xatolari takrorlanmaydi.\n"
        "\u2022 \U0001F4EC <b>SIGNAL YETKAZISH (v98)</b>: ADMIN signalni DOIM oladi \u2014 bitta ham qolmaydi, karta hozirgidek to\u2018liq. Rad etilgan signallar hech kimga bormaydi. Ro\u2018yxatdagi userlarga ODDIY karta: BUY/SELL, coin, timeframe, kirish, SL, TP1..TP5. Har /start bosgan user (bazaga BIR marta yoziladi) har 2 kunda 1 BEPUL signal + natijasini oladi.\n"
        "\u2022 \U0001F4CA <b>USER HISOBI</b>: ro\u2018yxatdagi userda admin tugmalari KO\u2018RINMAYDI \u2014 faqat \u00ABMening hisobim\u00BB (limiti, nechta signal olgani, nechtasi g\u2018alaba, jami foyda pip) va \u00ABAdmin bilan bog\u2018lanish\u00BB.\n"
        "\u2022 \U0001F4E2 <b>BROADCAST KUCHAYDI</b>: matn, rasm, video, fayl \u2014 bitta bosishda hammaga; matnli xabarga inline tugma (havola) qo\u2018shiladi.\n"
        "\u2022 \U0001F916 <b>SNIPER KUCHAYTIRILDI (v94)</b>: endi bozordan "
        "kiradi (zona kutish yo\u2018q), faqat London (06-10) va Nyu-York "
        "(12-16 UTC) seansida skan qiladi, impuls >= 0.7 ATR. Halol backtest: "
        "15 setup, g\u2018alaba 93.3%, +3.9R (oldingi 41 setup, 80.5%, +2.2R).\n"
        "\u2022 \U0001F9E0 <b>KUCHLI O\u2018QISH (v93)</b>: signal bo\u2018lib "
        "yozilsa ham yig\u2018iladi \u2014 \u00AB04-00\u00BB keyin \u00ABBuy\u00BB, "
        "\u00ABBuy scalp 47-44\u00BB keyin \u00AB37sl\u00BB. Darajalar tartibi "
        "yo\u2018nalishni bildiradi: o\u2018suvchi (92-94) = SELL, kamayuvchi "
        "(56-50) = BUY. \u00ABBUYING NOW\u00BB kabi shakllar ham o\u2018qiladi. "
        "Natija (\u00ABkirdim\u00BB, \u00AB65pip ciqdi\u00BB), \u00ABdoliv\u00BB, "
        "\u00ABdamni oling\u00BB, ertangi reja va savollar \u2014 signal EMAS.\n"
        "\u2022 \U0001F3AF <b>SNIPER: HTF \u2192 M1 (v93)</b>: bot 1d / 4h / 1h ni "
        "kuzatadi, bitta tahlilni <b>M1</b> da qiladi va savdoni ham M1 da ochadi. "
        "Eski xato tuzatildi (shu sababli bot o\u2018zi hech signal bermagan edi). "
        "<b>/skan</b> \u2014 hozir tekshiradi va nima ko\u2018rganini yozadi.\n"
        "\u2022 \U0001F510 <b>AKKAUNT CHIQIB KETMAYDI (v93)</b>: versiya "
        "yangilanganda ikki nusxa bir sessiyani ishlatib, Telegram uni o\u2018chirar "
        "edi. Endi qulf bor \u2014 faqat bitta nusxa ulanadi, ikkinchisi kutadi.\n"
        "\u2022 \U0001F4BC <b>HISOB 3 GA BO\u2018LINDI (v92)</b>: "
        "\U0001F4E1 <b>1) Kanaldan olingan</b> signallar, \U0001F916 <b>2) Bot o\u2018zi "
        "topgan</b> signallar (SNR+ICT+SMC) va \U0001F9EE <b>3) Jami</b> \u2014 "
        "har birining o\u2018z balansi, foydasi, bitimlari, g\u2018alaba % va PF i. "
        "Shu uch bo\u2018lim <b>\U0001F4BC Hisob (paper)</b>, /natija, /Stat va "
        "BARCHA hisobotlarda (kunlik / haftalik / oylik / sana bo\u2018yicha / "
        "to\u2018liq) ko\u2018rinadi.\n"
        "\u2022 \U0001F3AF <b>FAQAT HAQIQIY SIGNAL (v91)</b>: kanalning haqiqiy tili "
        "o'qiladi \u2014 \u00ABSell now\u00BB, \u00AB84-86 sel\u00BB, "
        "\u00AB94.6sl\u00BB, \u00ABsl 30pip\u00BB, \u00ABTp1 50pip\u00BB, "
        "\u00AB86gac\u00BB, qalin unicode. Natija ro'yxati (1.Buy 40pip\u2026), "
        "shartli reja (\u00AB\u2026 yoplsa yana buy\u00BB), fikr/tahlil va suhbat "
        "SIGNAL EMAS \u2014 sababi bilan yoziladi (statistikada ko'rinadi).\n"
        "\u2022 \U0001F6E1 <b>Barqarorlik (v90)</b>: baza uzilsa ham bot va /health "
        "ishlaydi; fon vazifalari yiqilsa o'zi qayta tiklanadi; bot/API o'zi tugab "
        "qolsa nazoratchi qayta ishga tushiradi; /100 MATN fayli 2 daqiqa ichida "
        "keladi (rasm matni keyin, fon rejimida).",
        "\u2022 \U0001F5C2 <b>/100</b> \u2014 BITTA kanaldan oxirgi <b>100</b> xabar, "
        "IKKI BOSQICHDA: 1) matn fayli darhol \u2192 2) rasm ichidagi yozuv (OCR) "
        "qo'shilgan fayl (matn + [RASM MATNI]). Holat har 10 s da yangilanadi "
        "(bot jim qolmaydi).\n"
        "\u2022 \U0001F680 <b>/500</b> (yoki /matn) \u2014 FAQAT MATNLI oxirgi 500 "
        "xabar, TEZ: rasm/video o'qilmaydi (bir necha sekund).\n"
        "   \u2022 <b>/100fayl</b> \u2014 bazadagi xabarlar fayli DARHOL (OCR kutmasdan)\n"
        "   \u2022 <b>/100stat</b> \u2014 bazada nechta xabar bor (kanal bo'yicha)\n"
        "   \u2022 <b>/100 @kanal</b> yoki tugma \u2014 kanal tanlash; /100ocr \u2014 "
        "qolgan rasmlarni o'qish.",
        "\u2022 \U0001F4BE <b>Baza</b>: /DB \u2014 SQL fayl (Supabase/Neon) + "
        "har 48 soatda avto-zaxira (23:00).",
        "\u2022 \U0001F5D1 <b>Kanal o'chirish</b> \u2014 bir bosishda o'chadi "
        "(\u21A9\uFE0F Qaytarish bor).",
        "\u2022 <b>Faqat HAQIQIY signallar</b> o'qiladi: matnda ANIQ narx "
        "(masalan 4394.37 yoki 4290-4295 zona) bo'lishi shart.",
        "\u2022 Signal EMAS: dars/kurs/vebinar postlari, tahlil-so'rov, rasm "
        "skrinshotlari, \u00ABbuy now\u00BB kabi darajasiz chaqiruvlar "
        "(narx yozilmagan), natija/maqtov postlari va kontekstdan olingan raqamlar.",
        "\u2022 SIGNAL kartasi QISQA; manba, lotlar va foyda hisobi \u00AB\u2753 Nega bu "
        "signal?\u00BB sahifasida.",
        "\u2022 Natija (WIN/LOSE) kartasi ham qisqa \u2014 to'liq tafsilot \u00AB\U0001F4D6 To'liq "
        "tafsilot\u00BB tugmasida.",
        "\u2022 \U0001F4E6 <b>LOT QO\u2019LDA</b>: hajm BITTA umumiy sozlama \u2014 "
        "<b>/lot</b> (risk foizi YO\u2019Q). Kanal signallari ham, sniper ham shu "
        "lotdan ochiladi (2 lot: Lot1 + Lot2).",
        "\u2022 TP har doim AYNAN TP narxida, SL esa bozor narxida (gap bo'lsa) \u2014 "
        "brokerdagidek.",
        "\u2022 Eski/kechikkan signal (narx kirishdan uzoq) ochilmaydi \u2014 yolg'on "
        "natija yozilmasin.",
        "\u2022 Akkaunt va kanallar ZAXIRADA: /zaxira \u2014 zaxira fayli buyruq "
        "berilganda, startupda va <b>har 24 soatda shu chatga avtomatik</b> yuboriladi.",
        "\u2022 Baza almashib ketsa ham: faylni botga yuboring \u2014 akkaunt va kanallar "
        "o'zi tiklanadi (qayta ulash shart emas).",
        "\u2022 O'tgan signallar haqidagi maqtov/natija postlari SIGNAL EMAS.",
        "\u2022 Bozor kuzatuvi aniq: sham yetib kelmasa yoki narx to'xtasa \u2014 "
        "darhol ogohlantirish keladi.",
        "\u2022 <b>Lot 2</b>: +4R da qulf \u2014 momentum kuchli bo'lsa +5R, "
        "so'nsa +4R da yopiladi (foyda 4R dan past bo'lmaydi).",
        "\u2022 Zarar ham, FOYDA ham aniq ko'rsatiladi (dollar hisobida) "
        "(har lot: risk + maqsadga yetsa qancha).",
        "\u2022 Bir xil xabar takror ishlanmaydi (xabar xotirasi).",
        "\u2022 \U0001F3AF <b>KIRISH NUQTASI</b>: savdo faqat narx hisoblangan "
        "zonaga KELGANDA ochiladi. Signal kirishni aytgan bo'lsa \u2014 bot "
        "hisoblamaydi (o'sha zona), aytilmagan bo'lsa \u2014 bot bozor holatidan "
        "(5m/15m tayanch, EMA, diapazon) o'zi hisoblaydi. Sozlash: /kirish.",
        "\u2022 \u23F3 Narx zonaga kelmasa \u2014 signal BEKOR: savdo umuman "
        "ochilmaydi (0$ zarar). Narx orqasidan quvish YO'Q.",
        "\u2022 \U0001F6D1 Stop loss HAR DOIM qoladi (signal bersa o'sha, "
        "bermasa bot tuzilmadan hisoblaydi).",
        "\u2022 \U0001F6E1 SL dan keyin darhol qarama-qarshi tomonga o'tish "
        "to'siladi (flip-flop himoyasi, /kirish da sozlanadi).",
        "\u2022 \u2757 Tanlangan lot balansga sig\u2019masa \u2014 savdo ochilmaydi "
        "(\u00ABbalans yetmaydi\u00BB sababi bilan).",
        "\u2022 \U0001F5C4 <b>Baza ishlamasa</b> \u2014 xato spam bo'lmaydi: sabab "
        "va nima qilish kerakligi bir marta aytiladi (\u00ABbaza manzili "
        "topilmayapti (DNS) \u2014 Render bepul baza 30 kunda o'chadi\u00BB).",
        "\u2022 \U0001F4E5 Baza uzilganda kelgan kanal xabarlari <b>navbatga</b> "
        "yoziladi va baza qaytishi bilan o'zi qayta ishlanadi \u2014 signal "
        "yo'qolmaydi.",
        "\u2022 \U0001F50E Baza holatini ko'rish: \U0001F4CA Kanallar \u2192 "
        "Holat yoki /100test (birinchi qator \u2014 baza holati).",
        "\u2022 \U0001F6E1 <b>Baza umuman ishlamasa ham bot TO\u2019XTAMAYDI</b> "
        "(v87): bot va /health ishlab turadi, xato sababi va manzil bo\u2019yicha "
        "aniq maslahat bir marta yuboriladi.",
    ]
    if cmds:
        lines.append(f"Commandlar ({len(cmds)} ta): " + " ".join("/" + c for c in cmds))
    return "\n".join(lines)


async def last_version(session) -> str | None:
    """Oxirgi e'lon qilingan versiya (bazadan)."""
    res = await session.execute(
        select(SystemLog).where(SystemLog.component == COMPONENT)
        .order_by(SystemLog.id.desc()).limit(1)
    )
    row = res.scalars().first()
    if row is None:
        return None
    try:
        return (json.loads(row.message or "") or {}).get("version")
    except Exception:  # noqa: BLE001
        return (row.message or "").strip() or None


async def should_announce(session, ver: str | None = None) -> bool:
    """Shu versiya hali e'lon qilinmaganmi? (bir marta yuborish qoidasi)"""
    return (await last_version(session)) != (ver or version())


async def mark(session, ver: str | None = None) -> None:
    """E'lon qilingan versiyani yozib qo'yamiz."""
    ver = ver or version()
    session.add(SystemLog(
        level="INFO", component=COMPONENT,
        message=json.dumps({"version": ver,
                            "at": datetime.now(timezone.utc).isoformat()},
                           ensure_ascii=False),
    ))
    await session.commit()
