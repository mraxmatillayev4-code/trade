"""v91: FAQAT HAQIQIY SIGNAL — kanalning haqiqiy tili.

Bu qatlam @a_s_trade_1 kanalining 1200 ta HAQIQIY xabari (2026-09-23 .. 2026-10-01
dump) o'rganib chiqilib yozildi. Kanal signalni juda qisqa yozadi:

  * bozor signali:      "Buy now", "Sell now", "Re entry sell now", "Min risl sell now"
  * daraja bilan:       "84-86 sel", "Buy 83-80", "40-39-38 buy limit min risk 36.5sl"
  * qisqa narx tili:    "59-58-57" = 4259-4258-4257, "43.5-45.5" = 4343.5-4345.5,
                        "86gac" = 4286 gacha (gac = gacha)
  * SL yopishgan:       "94.6sl", "36.5sl", "83.2 sl", "06stop loss"
  * SL pips bilan:      "sl 30pip", "Sl50pip", "sl15pip"   (1 pip = 0.20$, korpusdan)
  * TP pips bilan:      "Tp1 50pip", "Tp2 80pip" yoki zinapoya "Tp1 80 Tp2 120 Tp3 160"
  * TP R:R bilan:       "Tp1 1:7 R:R"
  * qalin unicode:      "𝗫𝗔𝗨𝗨𝗦𝗗 𝗕𝗨𝗬 𝗭𝗢𝗡𝗘 — 𝟰𝟮𝟳𝟵–𝟰𝟮𝟳𝟴" -> NFKC bilan oddiy matnga

Va SIGNAL BO'LMAGAN narsalar (shu korpusdan): natija/ro'yxat postlari
("1.Buy 40pip | 2.Buy 70pip ...", "Full tp sell", "250pip buy | 115pip sell"),
fikr/tahlil ("... deb o'ylayman"), shartli reja ("... yoplsa yana buy",
"news bosa buy"), maslahat/dars, maqtov/suhbat, savol.

Bu modul "kam fikrlaydi": faqat qat'iy qoidalar, har rad etish SABABI bilan.
"""
from __future__ import annotations

import re
import unicodedata

# 1 pip = 0.20$ (XAU) — korpus isboti: "Sell zone 86.72-87.72 | 89.72 sl" (2.5$),
# "Tp1 80 Tp2 120 Tp3 160 Tp4 200 Tp5 250" zinapoyasi teng qadamlar (16,24,32,40,50$).
PIP_XAU = 0.20

# --------------------------------------------------------------------------- #
#  Normalizatsiya
# --------------------------------------------------------------------------- #
_CYR = str.maketrans({
    "\u0430": "a", "\u0432": "b", "\u0435": "e", "\u043a": "k", "\u043c": "m",
    "\u043d": "h", "\u043e": "o", "\u0440": "p", "\u0441": "c", "\u0442": "t",
    "\u0443": "y", "\u0445": "x", "\u0456": "i", "\u0455": "s", "\u0458": "j",
})


def norm(t: str | None) -> str:
    """Qalin unicode, tire, vergul-narx, kirill harflar -> oddiy kichik matn."""
    if not t:
        return ""
    s = unicodedata.normalize("NFKC", str(t))
    s = (s.replace("\u2013", "-").replace("\u2014", "-").replace("\u2012", "-")
          .replace("\u2015", "-").replace("\u2212", "-"))
    s = s.replace("\u2705", " ").replace("\u2714", " ").replace("\u2611", " ")
    s = re.sub(r"(\d)\s*,\s*(\d)", r"\1.\2", s)      # 4290,5 -> 4290.5
    s = s.lower().translate(_CYR)
    return s


# --------------------------------------------------------------------------- #
#  RAD ETISH (veto) — sabab kodi bilan
# --------------------------------------------------------------------------- #
_VETO: list[tuple[str, str]] = [
    # v101: o'z SAVDOSI haqida post ("full krudm sell 2000+", "buy kirdim")
    # signal EMAS — bozor yurgani emas, savdo hisobi.
    ("oz-savdosi", r"\b(?:kirdim|kirdm|krudm|kiridm|kirrm|yopdim|yopdm|ochdim|ochdm)\b"),
    ("natija-royxat", r"(?m)^\s*\d{1,2}\s*[.)]\s*(?:buy|sell|sel|sot|xarid)"),
    ("natija-post", r"\b(?:results?|natija|natijalari|hisobot|umumiy\s+(?:foyda|zarar)"
                    r"|yakunladik|yakuniy|kun\s+yakuni)\b"),
    ("tp-savdo-yopildi", r"(?:\bfull\s*tp\b|\btp\s*\d?\s*(?:done|hit|ok|oldi\w*"
                         r"|success\w*|completed|reached)\b"
                         r"|\bsuccess\w*\b|\bdone\b|\bb/u\b|\bbreak\s*even\b"
                         r"|\bsave\s*qil|\benjoy\b|\bprofit\s+taken\b|\btp\s*\d?\s*[\u2705\u2714])"),
    ("sl-urildi", r"(?:\bsl\s*(?:ogan|o'?tgan|uril|teg)|\bsl\s*ga\s*teg|\bsl\s*osa)"),
    ("yopilgan", r"\b(?:yopildi|yopilgan|yopganl\w*|yopdim|yopdm|yopmadm|yopmadim"
                 r"|yopib\s+qo'?y)\b"),
    ("goya", r"\bideas?\b"),
    ("reklama", r"\b(?:obuna|subscribe|reklama|join\s|vip|kurs|dars|vebinar|shogird"
                r"|investitsiya|invest|hamkor)\b"),
    ("fikr", r"\b(?:oylavoman|o'?ylayman|o'?ylavoman|fikrim|menimcha|kutaman|kutmi"
             r"|kutmayman|ehtimol|bilmayman|tavakkal|ishonch\s+yo'?q)\b"),
    ("maslahat", r"\b(?:savdo\s+qiling|perezaxod|maslahat|eslab\s+qoling|yodda\s+tuting"
                 r"|risk\s+qisa|qisa\s+bolad|bo'?lib\s+bo'?lmaydi)\b"),
    ("narrativ", r"\b(?:hamma|kopchilik|ko'?pchilik|ulgurmadik|berdm|berdim|krdm|ko'?rdm"
                 r"|ko'?rdim|boshqa\s+kanal|dgan|degan|esimda|gap\s+yo'?q)\b"),
    ("savol", r"\?"),
    # v93: SO'ROQ SO'ZI (vergul-ishora bo'lmasa ham) — "17-22 zona kimni esida efrdgi"
    ("savol-soz", r"\b(?:kimni|kimda|kimlar|esida|esingizda|yodida|bilasizmi|topasizmi"
                  r"|qiziqmi|qiziq\b|rozimisiz|bormi|yokmi|qani|nima\s+(?:bo'?ldi|qil)"
                  r"|necha\s+(?:kishi|odam)|qayerda|shundaymi|tog'?ri\s*mi|ha\s*mi"
                  r"|manfaatli|faydali|kerakmi|yaxshimi|qildingizmi|otdingizmi"
                  r"|\w{2,}(?:votmi|otmi|sizmi|misiz))\b"),
    # v93: O'TGAN ZAMON FE'LI — "40-45dan ful krdm", "65pip ciqdi", "tp oldiyuuu"
    ("natija-kirdim", r"\b(?:kirdim|kirdm|krdm|kirdik|kirib\s+oldim|oldim|oldiyuuu"
                      r"|oldik|oldila?r?|olishdi|ciqdi|chiqdi|chiquvdi|urdi|urdilar"
                      r"|yopib\s+qo'?ydim|qo'?ydim|yetib\s+bordim|bordim|bo'?ldim"
                      r"|tugadi|tugagan|bitgan|yurgan|otgan|urgan|qilgan|qigan"
                      r"|olindi|ochildi|yopildi|qo'?yildi|bajarildi|olingan|urildi"
                      r"|tegil|hisoblandi|yakunlandi|qaytdi|ketdi|uchib\s+ketti)\b"),
    # v93: DOLIV (qo'shimcha kirish) — bu YANGI signal emas, ochiq savdo boshqaruvi
    ("doliv", r"\b(?:doliv|do?liv\s+bn|добавка|qo'?shimcha\s+(?:kirish|lot)"
              r"|add\s+(?:position|more)|dolya)\b"),
    # v93: DAM OLISH / SAVE — savdo yopildi, signal emas ("Savechani qilib damni oling")
    ("dam-olish", r"\b(?:damni\s+ol\w*|dam\s+ol\w*|savechani|save\s*qil\w*"
                  r"|save\s+qil\w*|yopib\s+qo'?y\w*|qulf\w*|dam\s+olish)\b"),
    # v93: ERTANGI/KELASI REJA — hozirgi signal emas ("ertadan full savdo qilamz")
    ("reja-ertaga", r"\b(?:ertaga|ertadan|ertalab|tongda|keyinroq|kelgusi|ertangi"
                    r"|depo[sz]it\w*|depost\w*|nasib\w*)\b"),
    ("maqtov", r"\b(?:aka\b|jigarla|yordi|yordim|barakalla|zo'?r\b|ofi\b|dahshat"
               r"|shukr|alhamdulillah|rahmat)"),
]


# Yumshoq toifalar: matnda ANIQ daraja/SL bo'lsa, ularga qaramaymiz
# (masalan "92-94 sel 25pip sl 97.1 | Sl omaguncha risk qisa bolad" — signal!)
_SOFT = {"fikr", "maslahat", "narrativ", "maqtov"}


def veto_reason(t: str, soft_ok: bool = False) -> str | None:
    """Matn signal bo'la olmaydigan toifa bo'lsa sababini qaytaradi.

    `soft_ok=True` — matnda aniq daraja/SL bor; yumshoq toifalar (fikr,
    maslahat, narrativ, maqtov) rad etishga sabab bo'lmaydi.
    """
    s = norm(t)
    if not s:
        return "bosh"
    for code, pat in _VETO:
        if soft_ok and code in _SOFT:
            continue
        if re.search(pat, s, re.I):
            return code
    # Natija: "+150pip", "-30pip" — LEKIN "Tp1 - 50 pips" bu SIGNAL (shablon)
    for m in re.finditer(r"([-+])\s*(\d{1,4})\s*(?:pip|pips)\b", s):
        pre = s[max(0, m.start() - 14):m.start()]
        if re.search(r"(?:tp|sl|rr|stop\s*loss|stoploss|stop)\s*\d?\s*$", pre):
            continue
        return "natija-pips"
    # pip bilan hisob-kitob: 3+ pip raqami, lekin SL ham, daraja ham yo'q
    if len(re.findall(r"\d{1,4}\s*pips?\b", s)) >= 3 \
            and not re.search(r"\bsl\b|\bstop\s*loss\b|\bstoploss\b|\bstop\b"
                              r"|\d\s*sl\b", s):
        return "natija-pips"
    return None


# --------------------------------------------------------------------------- #
#  Shartlilik / bozor belgilari
# --------------------------------------------------------------------------- #
_COND = re.compile(
    r"\b(?:bosa|bo'?lsa|korsa|ko'?rsa|qaytsa|yopsa|yoplsa|yopilsa|buzsa|buzomasa"
    r"|yormaguncha|yormasa|teshsa|otsa|o'?tsa|tasdiq\s*ol\w*|kelmasa|bormasa"
    r"|yaqinlashsa|urilsa|tegsa)\b", re.I)

_NOW = re.compile(
    r"(?:\bnow\b|\bniw\b|\bnaw\b|\bhozir\b|\bmarket\w*\b|\baktiv\w*\b|\bfull\w*\b"
    r"|\bmarjin\w*\b|\bmargin\w*\b|\bmin\s+ri|\bris\w*ga\s+rozila\b|\bscalp\w*\b"
    r"|\bre\s*entry\b|\breentry\b|\befirda\b)", re.I)

# v93: SO'Z SHAKLLARI — "BUYING NOW", "selling", "seling", "buylim" ham o'qiladi
_BUY = re.compile(r"\b(?:buy(?:ing|in|s|lim|lar)?|buu+|byu\w*|long(?:ing|s)?"
                  r"|xarid|olish|olamiz|olamz|ol\w{0,3}\b|sotib\s+ol\w*)\b", re.I)
_SELL = re.compile(r"\b(?:sel(?:l(?:ing|s|im)?)?|selling|seling|sellng|sot\w*"
                   r"|short(?:ing|s)?|sotish|sotamiz|soting|qisqa)\b", re.I)

_NUM = r"\d{1,4}(?:\.\d{1,2})?"
# v93 XATO TUZATISH: raqam va unun belgisi FAQAT BIR QATORDA bo'lishi kerak.
# Ilgari `\s*` yangi qatordan ham o'tardi: "tp3 4360\nsl 4385" matnida SL=4360
# deb o'qilardi (aslida 4385) — ko'p qatorli kanallar signali shu sababli buzilardi.
_SP = r"[ \t]*"          # bo'shliq/tAB (yangi qator EMAS)
_GAC = re.compile(rf"({_NUM}){_SP}(?:gac|gacha|gach)\b", re.I)
_ZONE = re.compile(rf"(?<![\d.])({_NUM}){_SP}(?:-|to|va){_SP}({_NUM})(?:{_SP}(?:-|va){_SP}({_NUM}))?")
_SL_GLUE = re.compile(rf"(?<![\d.])({_NUM}){_SP}(?:sl|stop[ \t]*loss|stoploss|stop)\b", re.I)
_SL_PRE = re.compile(rf"\b(?:sl|stop[ \t]*loss|stoploss|stop){_SP}[:=-]?{_SP}({_NUM})", re.I)
_SL_PIPS = re.compile(
    rf"(?:\b(?:sl|stop[ \t]*loss|stoploss|stop){_SP}[:=-]?{_SP}({_NUM}){_SP}(?:pip|pips|p\b)"
    rf"|({_NUM}){_SP}(?:pip|pips){_SP}(?:sl|stop)\b)", re.I)
_TP_PIP = re.compile(rf"\btp{_SP}(\d?){_SP}[:\-]?{_SP}({_NUM}){_SP}(?:pip|pips)", re.I)
_TP_RR = re.compile(rf"\btp{_SP}(\d?){_SP}[:\-]?{_SP}(\d{{1,2}})\s*:\s*(\d{{1,2}})", re.I)
_TP_ANY = re.compile(rf"\btp{_SP}(\d?){_SP}[:\-]?{_SP}({_NUM})", re.I)
_TIME = re.compile(r"\d{1,2}:\d{2}")
_RR = re.compile(r"\b\d{1,2}\s*:\s*\d{1,2}\b")
_PCT = re.compile(r"\d{1,3}\s*%")
_PIP_CTX = re.compile(r"(?:\d\s*(?:pip|pips)\b|\b(?:pip|pips)\b|\d{1,3}\s*\.\s*\d)")


def _split_time(t: str) -> str:
    """Vaqtlar (17:30) daraja sifatida o'qilmasin."""
    return _TIME.sub(" ", t)


def _abs(v: float | None, ref: float) -> float | None:
    """Qisqa narxni («59.5», «-16») mavjud narxga qarab to'liq narxga aylantiradi.

    Masalan ref=4258, v=59.5 -> 4259.5; ref=4318, v=-16 -> 4284.
    """
    if v is None:
        return None
    v = float(v)
    if v >= 1000:
        return round(v, 4)
    base = int(round(float(ref) / 100.0)) * 100
    cand = [base - 100 + v, base + v, base + 100 + v]
    return round(min(cand, key=lambda c: abs(c - float(ref))), 4)


PLAUSIBLE_D = 80.0        # kontekst raqami jonli narxdan ko'pi bilan $80 uzoqda


def _plausible(v, ref: float | None, entry: float | None = None) -> bool:
    """v93: KONTEKST RaqAMIDAN OLINGAN narx haqiqiy bo'lishi mumkinmi?

    Misol: "Limitti omasdan uchib ketti" xabariga kontekstdan 2214 narx
    yopishib qolgandi — jonli oltin 4290 edi. Shu tekshiruv bunday
    yolg'on signallarni to'sadi. Qisqa shakl (04-00 -> 4102) ham tekshiriladi:
    avval to'liq narxga aylantirib, keyin solishtiramiz.
    """
    if v is None:
        return False
    try:
        v = float(v)
    except (TypeError, ValueError):
        return False
    if not ref:
        return True
    ref = float(ref)
    cand = [v]
    if v < 1000:
        base = int(round(ref / 100.0)) * 100
        cand = [base - 100 + v, base + v, base + 100 + v]
    if any(abs(c - ref) <= PLAUSIBLE_D for c in cand):
        return True
    if entry:
        return any(abs(c - float(entry)) <= PLAUSIBLE_D for c in cand)
    return False


def _abs_sl(v: float | None, ref: float | None, direction: str,
            entry: float | None) -> float | None:
    """v93: SL qisqa shaklini to'liq narxga aylantiradi — GEOMETRIYANI saqlab.

    Oddiy `_abs` eng yaqin variantni oladi, lekin narx o'rtada bo'lsa SL
    teskari tomonga tushib qoladi (masalan ref=4144, entry=4193 (SELL),
    sl="97.1" -> 4097.1 noto'g'ri, 4197.1 to'g'ri). Shu sababli avval eng
    yaqin, u yaramasa SL to'g'ri tomonda bo'lgan variant tanlanadi.
    """
    if v is None:
        return None
    v = float(v)
    if v >= 1000:
        return round(v, 4)
    if not ref:
        return round(v, 4)
    base = int(round(float(ref) / 100.0)) * 100
    cand = [base - 200 + v, base - 100 + v, base + v, base + 100 + v, base + 200 + v]
    nearest = min(cand, key=lambda c: abs(c - float(ref)))
    if entry is None or direction not in ("BUY", "SELL"):
        return round(nearest, 4)
    if _sign_ok(direction, float(entry), nearest):
        return round(nearest, 4)
    good = [c for c in cand if _sign_ok(direction, float(entry), c)]
    if good:
        return round(min(good, key=lambda c: abs(c - float(entry))), 4)
    return round(nearest, 4)


def _wrap(v: float, short: bool) -> float:
    """Qisqa shaklda qiymat 0..100 oralig'ida qoladi (59 + 30 -> 89)."""
    if not short:
        return v
    while v >= 100:
        v -= 100
    while v < 0:
        v += 100
    return v


def _zone(t: str) -> tuple[float | None, float | None, float | None]:
    """(past, yuqori, o'rta) — faqat HAQIQIY narx oralig'i (pips/foiz emas)."""
    s = _split_time(t)
    best = None
    for m in _ZONE.finditer(s):
        raw_vals = [x for x in m.groups() if x]
        after = s[m.end():m.end() + 8]
        if re.match(r"\s*(?:pip|pips|%)", after, re.I):
            continue                                  # "500-1000pip" -> pips
        before = s[max(0, m.start() - 8):m.start()]
        if re.search(r"(?:tp|sl|rr|stop)\s*\d?\s*[:\-]?\s*$", before, re.I):
            continue                                  # "Tp1 80-120" kabi emas
        try:
            vals = [float(x) for x in raw_vals]
        except ValueError:
            continue
        # v93: "04-00" = 4104-4100 — qisqa shaklda 0 ham yaroqli
        if max(vals) > 9999 or min(vals) < 0 or max(vals) <= 0:
            continue
        best = vals                                # eng oxirgisi ustun
    if not best:
        return None, None, None
    lo, hi = min(best), max(best)
    return lo, hi, round(sum(best) / len(best), 4)


def _zone_order(t: str) -> tuple[float, float] | None:
    """Zona darajalari YOZILGAN TARTIBDA: (birinchi, ikkinchi)."""
    s = _split_time(t)
    best = None
    for m in _ZONE.finditer(s):
        raw_vals = [x for x in m.groups() if x]
        after = s[m.end():m.end() + 8]
        if re.match(r"\s*(?:pip|pips|%)", after, re.I):
            continue                                   # "500-1000pip" — pips
        before = s[max(0, m.start() - 8):m.start()]
        if re.search(r"(?:tp|sl|rr|stop)\s*\d?\s*[:\-]?\s*$", before, re.I):
            continue
        try:
            vals = [float(x) for x in raw_vals]
        except ValueError:
            continue
        if len(vals) < 2 or max(vals) > 9999 or min(vals) < 0 or max(vals) <= 0:
            continue
        best = (vals[0], vals[1])                       # eng oxirgisi ustun
    return best


def dir_from_order(t: str) -> str:
    """v93 KORPUS QOIDASI: darajalar tartibi yo'nalishni bildiradi.

    O'SUVCHI (kichik -> katta) = SELL zonasi, KAMAYUVCHI (katta -> kichik) = BUY.
    Korpusda 23/23 tasdiqlangan: "92-94 sel", "Sell 59-61", "80-81.5", "87-91 sel"
    (o'suvchi = SELL) va "Buy 83-80", "56-50", "14-09", "40-39-38 buy", "04-00"+"Buy"
    (kamayuvchi = BUY). Shu sababli "62.5-64.5 sl 25pip" yo'nalish so'zi bo'lmasa
    ham SELL ekanini bot tushunadi.
    """
    z = _zone_order(t)
    if not z:
        return ""
    a, b = z
    if a == b:
        return ""
    return "SELL" if b > a else "BUY"


def ctx_parts(ctx: str | None) -> dict:
    """v93: KONTEKST — oldingi xabarlar (4 daqiqa oynasi) dan yetishmayotgan qism.

    Kanal egasi signalni bo'lib yozadi: "04-00" (daraja) va keyin "Buy" (yo'nalish),
    yoki "Buy scalp 47-44" va keyin "37sl". Shu sababli yo'nalish / daraja / SL
    qo'shni xabardan olinadi (eng yangisi ustun).
    """
    out = {"dir": "", "zone": None, "sl": None, "sl_pips": None, "now": False,
           "lines": 0, "tps": []}
    if not ctx:
        return out
    lines = [ln.strip() for ln in str(ctx).split("\n") if ln.strip()]
    out["lines"] = len(lines)
    for ln in reversed(lines):
        s = norm(ln)
        if not s:
            continue
        # v93 QAT'IY: kontekst faqat SIGNALGA O'XSHASH qatordan olinadi.
        # Aks holda suhbat ("YOP JGAR", "Foydani ol qoch", "Aktiv bo'ling")
        # signalga aylanib qolardi.
        if veto_reason(ln, soft_ok=True):
            continue
        if not re.search(r"\d", s) and not (_BUY.search(s) or _SELL.search(s)):
            continue
        if not out["dir"]:
            nb, ns = len(_BUY.findall(s)), len(_SELL.findall(s))
            if nb and not ns:
                out["dir"] = "BUY"
            elif ns and not nb:
                out["dir"] = "SELL"
        if out["zone"] is None:
            lo, hi, mid = _zone(s)
            if mid is not None:
                out["zone"] = (lo, hi, mid)
        if out["sl"] is None and out["sl_pips"] is None:
            v, pp = _sl(s)
            if v is not None:
                out["sl"] = v
            elif pp:
                out["sl_pips"] = pp
        if not out["now"]:
            out["now"] = bool(_NOW.search(s))
        if out["dir"] and out["zone"] is not None and (out["sl"] or out["sl_pips"]):
            break
    return out


def _sl(t: str) -> tuple[float | None, float | None]:
    """(sl qiymati, pips) — aniq narx USTUN, pips keyin (korpus: "sl 97.1")."""
    s = _split_time(t)
    for m in _SL_GLUE.finditer(s):
        after = s[m.end():m.end() + 5]
        if re.match(r"\s*(?:pip|pips)\b", after, re.I):
            continue                       # "30pip sl" — bu narx emas, pips
        return float(m.group(1)), None
    m = _SL_PRE.search(s)
    if m:
        after = s[m.end():m.end() + 5]
        if not re.match(r"\s*(?:pip|pips)\b", after, re.I):
            return float(m.group(1)), None
    m = _SL_PIPS.search(s)
    if m:
        val = m.group(1) or m.group(2)
        return None, float(val)
    return None, None


def _sign_ok(direction: str, entry: float, lvl: float) -> bool:
    """Daraja to'g'ri tomonda? (qisqa shaklda ham ishlaydi)."""
    if direction == "BUY":
        return lvl < entry
    return lvl > entry


def _tps(t: str, direction: str, entry: float | None,
         sl_dist: float | None, short: bool = False) -> tuple[list[float], list[float]]:
    """(TP narxlari — yozilganiicha, TP pipslari)."""
    s = _split_time(t)
    prices: list[float] = []
    pips: list[float] = []
    for m in _TP_PIP.finditer(s):
        pips.append(float(m.group(2)))
    if not pips:
        for m in _TP_RR.finditer(s):
            rr = float(m.group(3)) / max(1.0, float(m.group(2)))
            if sl_dist:
                pips.append(rr * sl_dist / PIP_XAU)
    if not pips:
        got = [(m.group(1), float(m.group(2))) for m in _TP_ANY.finditer(s)]
        nums = [v for _, v in got]
        if len(nums) >= 3 and max(nums) - min(nums) >= 40 and nums == sorted(nums):
            pips = nums                                # zinapoya: 80/120/160/200/250
        else:
            for _, v in got:
                # v93: 99.99 gacha = qisqa narx ("Tp1 58.5" -> 4258.5),
                # 1000 dan yuqori = TO'LIQ narx ("TP1 4370"),
                # orasi = pips ("Tp1 150" -> 150 pip = 30$).
                if v <= 99.99 or v >= 1000.0:
                    prices.append(v)
                else:
                    pips.append(v)
    return prices, pips


# --------------------------------------------------------------------------- #
#  Asosiy qaror
# --------------------------------------------------------------------------- #
def strict_verdict(text: str | None, ref: float | None = None,
                   has_image: bool = False, ctx: str | None = None) -> dict:
    """Xabar bo'yicha qat'iy qaror (v93: `ctx` = oldingi xabarlar oynasi).

    Qaytaradi: verdict (SIGNAL | KUTISH | EMAS), reason, direction, symbol,
    entry, sl, tps, tps_pips, zone, flags.
    `entry`/`sl` — matnda yozilganiicha (qisqa shakl bo'lsa shunday: 58.5);
    ularni mavjud `snap_parsed(p, live_narx)` to'g'rilab oladi.
    """
    out: dict = {"verdict": "EMAS", "reason": "bosh", "direction": "",
                 "symbol": "XAUUSDT", "entry": None, "sl": None, "tps": [],
                 "tps_pips": [], "zone": None, "src": "", "flags": []}
    raw = text or ""
    s = norm(raw)
    if not s.strip():
        return out

    lo, hi, mid = _zone(s)
    gac = _GAC.search(s)
    sl_val, sl_pips = _sl(s)
    has_lvl = (mid is not None) or (gac is not None) or (sl_val is not None) or bool(sl_pips)

    why = veto_reason(s, soft_ok=has_lvl)
    if why:
        out["reason"] = "qatiy-rad: " + why
        out["flags"].append(why)
        return out

    cond = bool(_COND.search(s))
    now = bool(_NOW.search(s))          # v93: yo'nalish topishda ham ishlatiladi
    nb, ns = len(_BUY.findall(s)), len(_SELL.findall(s))
    if nb and ns:
        out["reason"] = "aralash yonalish"
        return out
    direction = "BUY" if nb else ("SELL" if ns else "")
    ci = ctx_parts(ctx) if ctx else None
    if not direction:
        # v93 (1): yo'nalish QO'SHNI XABARDAN — faqat shu xabarning O'ZI mazmunli
        # bo'lsa (daraja yoki SL bor). "YOP JGAR", "Aktiv bo'ling" kabi suhbatlar
        # shunday qilib signalga aylanib qolishi mumkin edi.
        if ci and ci["dir"] and (mid is not None or gac is not None
                                 or sl_val is not None or bool(sl_pips)):
            direction = ci["dir"]
            out["flags"].append("yonalish-kontekstdan")
        else:
            # v93 (2): yo'nalish DARAJA TARTIBIDAN (o'suvchi=SELL, kamayuvchi=BUY),
            # lekin faqat TASDIQ bo'lsa (SL / pips / now / TP / kontekst darajasi)
            od = dir_from_order(s)
            confirm = bool(sl_val is not None or sl_pips or now or
                           (ci and (ci["zone"] is not None or ci["sl"] or
                                    ci["sl_pips"] or ci["now"])))
            if od and confirm:
                direction = od
                out["flags"].append("yonalish-daraja-tartibidan")
            elif od:
                out["reason"] = "yonalish yoq (faqat tartib, tasdiq yoq)"
                return out
    if not direction:
        out["reason"] = "yonalish yoq"
        return out
    out["direction"] = direction

    entry = None
    src = ""
    if mid is not None:
        entry, src = mid, "TEXT"
    elif gac:
        entry, src = float(gac.group(1)), "TEXT"
    elif now:
        src = "NOW"
    elif ci and ci["zone"] is not None and (nb or ns) and _plausible(ci["zone"][2], ref):
        # v93: daraja QO'SHNI XABARDAN ("04-00" dan keyin "Buy" keldi).
        # Shartlar: (a) shu xabarda yo'nalish so'zi bor, (b) daraja jonli narx
        # atrofidagina (aks holda eski/xato raqam signal bo'lib qolardi).
        lo = lo if lo is not None else ci["zone"][0]
        hi = hi if hi is not None else ci["zone"][1]
        entry, src = ci["zone"][2], "CTX"
        out["flags"].append("daraja-kontekstdan")
    # v93: "now" belgisi faqat O'Z xabarida bo'lsa ishlatiladi (kontekstdagi
    # "aktiv/full" so'zlari suhbatni signalga aylantirib qo'yardi).

    if entry is None and not now and src != "NOW":
        # v93: "37sl", "Tp1 50pip" kabi QISM xabar — yo'nalish/daraja kontekstdan
        # bo'lsa ham yangi savdo ochilmaydi (ochiq savdoni boshqarish uchun).
        if "yonalish-kontekstdan" in out["flags"] or sl_val is not None or sl_pips:
            out["reason"] = "qism (sl/tp yoki davomi) - yangi signal emas"
        else:
            out["reason"] = "narx ham, now ham yoq"
        return out

    if cond:
        out["verdict"] = "KUTISH"
        out["reason"] = "shartli reja (kutish)"
        out["entry"] = entry
        out["src"] = src
        return out

    # v91: manba narx ma'lum bo'lsa — hammasi absolyut (snap kerak emas)
    short = entry is not None and float(entry) < 1000.0
    if ref and src == "NOW":
        entry = round(float(ref), 4)
        src = "NOW-REF"
        short = False
    if ref and short:
        entry = _abs(entry, float(ref))
        lo = _abs(lo, float(ref)) if lo is not None else None
        hi = _abs(hi, float(ref)) if hi is not None else None
        sl_val = _abs_sl(sl_val, float(ref), direction, entry) if sl_val is not None else None
        short = False

    out["entry"], out["src"] = entry, src
    out["zone"] = (lo, hi) if lo is not None else None

    sl_dist = None
    if sl_val is not None and entry is not None:
        if _sign_ok(direction, entry, sl_val):
            out["sl"] = sl_val
            sl_dist = abs(entry - sl_val)
    if sl_pips and entry is not None and out["sl"] is None:
        dist = sl_pips * PIP_XAU
        out["sl"] = _wrap(entry - dist if direction == "BUY" else entry + dist, short)
        sl_dist = dist
    if sl_pips:
        out["flags"].append("sl-pips")
        sl_dist = sl_dist or sl_pips * PIP_XAU
    # v93: SL QO'SHNI XABARDAN ("Buy scalp 47-44" + keyingi "37sl")
    if out["sl"] is None and entry is not None and ci:
        if ci["sl"] is not None and _plausible(ci["sl"], ref, entry):
            _v = _abs(ci["sl"], float(ref)) if (ref and float(ci["sl"]) < 1000.0) else ci["sl"]
            if _v is not None and _sign_ok(direction, float(entry), float(_v)):
                out["sl"] = round(float(_v), 4)
                sl_dist = abs(float(entry) - float(_v))
                out["flags"].append("sl-kontekstdan")
        elif ci["sl_pips"]:
            dist = float(ci["sl_pips"]) * PIP_XAU
            out["sl"] = _wrap(float(entry) - dist if direction == "BUY"
                              else float(entry) + dist, short)
            sl_dist = dist
            out["flags"].append("sl-pips-kontekstdan")

    tp_prices, tp_pips = _tps(s, direction, entry, sl_dist, short=short)
    if entry is not None:
        for p in tp_prices:
            if _sign_ok("SELL" if direction == "BUY" else "BUY", entry, p):
                out["tps"].append(p)
        for pp in tp_pips:
            dist = pp * PIP_XAU
            if dist <= 0 or dist > 1000:
                continue
            v = entry + dist if direction == "BUY" else entry - dist
            out["tps"].append(round(_wrap(v, short), 4))
    out["tps_pips"] = tp_pips
    if out["tps"] and entry is not None:
        if short:
            sgn = 1.0 if direction == "BUY" else -1.0
            out["tps"] = sorted(set(out["tps"]),
                                key=lambda v: ((v - entry) * sgn) % 100.0)
        else:
            out["tps"] = sorted(set(out["tps"]), reverse=(direction == "SELL"))
    out["verdict"] = "SIGNAL"
    out["reason"] = ("daraja+reja" if (out["sl"] or out["tps"]) else
                     ("daraja" if entry is not None else "bozor (now)"))
    if src == "CTX":
        out["reason"] += "+kontekst"
    if "yonalish-daraja-tartibidan" in out["flags"]:
        out["reason"] += "+tartib"
    return out


def describe(v: dict) -> str:
    """Qisqa izoh (hisobot/karta uchun)."""
    parts = [str(v.get("reason") or "")]
    if v.get("entry"):
        parts.append("kirish " + str(v["entry"]))
    if v.get("sl"):
        parts.append("SL " + str(v["sl"]))
    if v.get("tps"):
        parts.append("TP " + ", ".join(str(x) for x in v["tps"][:3]))
    return " | ".join(p for p in parts if p)
