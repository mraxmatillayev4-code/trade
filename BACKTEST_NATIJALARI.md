# Backtest natijalari — 2026-08-28 yakuniy (mukammallashtirilgan strategiyalar)

**Sinov sharti:** 9 ta coin × 4 timeframe, har birida 500 ta yopilgan sham, faqat yopilgan sham signallari (repaint yo'q), jonli bot bilan bir xil kod yo'li (10 strategiya, 7 darvoza, MTF filtri, trailing stop).

## ⚙️ Bu bosqichda kiritilgan takomillashtirishlar

| # | Yaxshilanish | Nima beradi |
|---|---|---|
| 1 | **Trailing stop (foydani qulflash)** | TP2 olingach, SL TP1 darajasiga ko'chadi → stop bo'lsa ham ~+1.33R foyda qulflanadi (ilgari TP2 dan keyin narx qaytib kelsa, yutuq yo'qolib ketardi). |
| 2 | **Backtest'ga MTF filtri ulandi** | Ilgari backtest yuqori timeframe trend filtrini hisobga olmas edi — endi jonli bot kabi ishlaydi. |
| 3 | **Over-extension filtri** | Narx EMA50 dan 3 ATR dan uzoqqa cho'zilgan "kechikkan" kirishlar sifatdan tushiriladi (bonus shart). |
| 4 | **Timeframe sifat darvozalari** | 5m/15m/30m kamida 3 strategiya ovozi; conviction 5m ≥ 6.2. |
| 5 | **30m standart ro'yxatdan olindi** | Backtest'da PF 0.66–0.69 (tuzilmaviy zaif, ko'p kechikkan BUY). Majburlab sozlash overfitting bo'lardi; `.env` da qaytarib yoqish mumkin. |

## 📊 Timeframe bo'yicha yakuniy natija

| Timeframe | Bitim | Yutuq | WinRate | O'rtacha R | Jami R | **PF** | Maks. DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| 5m  | 150 | 72 | 48.0% | +0.03 | +4.8R  | **1.06** | 12.7R |
| 15m | 136 | 74 | 54.4% | +0.06 | +8.3R  | **1.13** | 9.3R  |
| 1h  | 159 | 91 | 57.2% | +0.27 | +43.0R | **1.63** ⭐ | 10.7R |
| 4h  | 155 | 80 | 51.6% | +0.11 | +16.8R | **1.22** | 9.3R  |
| **JAMI** | **600** | **317** | **52.8%** | **+0.12** | **+73.0R** | **1.26** | **12.3R** |

✅ **4 timeframe'ning hammasi foydali.** Taqqoslash: mukammallashtirishdan oldin jami PF 1.18 / +57.2R / DD 26.0R edi → hozir **PF 1.26 / +73.0R / DD 12.3R** (foyda +28% oshdi, drawdown ikki baravar qisqardi).

## 🪙 Coin bo'yicha

| Coin | Bitim | WinRate | O'rtacha R | PF | Jami R |
|---|---:|---:|---:|---:|---:|
| Solana     | 74 | 60.8% | +0.31 | **1.79** ⭐ | +22.8R ✅ |
| Chainlink  | 71 | 63.4% | +0.28 | **1.76** ⭐ | +19.7R ✅ |
| Dogecoin   | 48 | 56.2% | +0.26 | **1.59** | +12.3R ✅ |
| Bitcoin    | 64 | 50.0% | +0.12 | 1.23 | +7.5R ✅ |
| BNB        | 72 | 52.8% | +0.10 | 1.22 | +7.5R ✅ |
| Ethereum   | 69 | 53.6% | +0.08 | 1.17 | +5.6R ✅ |
| XRP        | 71 | 47.9% | +0.08 | 1.14 | +5.3R ✅ |
| Cardano    | 72 | 45.8% | −0.03 | 0.94 | −2.3R ❌ |
| Avalanche  | 59 | 44.1% | −0.09 | 0.84 | −5.3R ❌ |

9 ta coindan 7 tasi foydali. Eng kuchlilar: **Solana, Chainlink, Dogecoin**. Eng zaiflar shu davr uchun Avalanche va Cardano (signallar jonli botda qat'iyroq filtrdan o'tadi, bot esa analitik tavsiya beradi — pul xavfi yo'q).

## ✅ Sinovlar
- `pytest` — **49 passed** (barcha strategiya va modul testlari).

## ⚠️ Halol ogohlantirish
- PF 1.26 = har 1 R risk uchun o'rtacha 1.26 R foyda — bu **realistik** natija; hech qanday strategiya 90% yutishni kafolatlamaydi.
- Natija oxirgi ~500 sham davriga tegishli; bozor rejimi o'zgarganda natija farq qilishi mumkin.
- Bot **analitik signal** beradi (order, leverage, pul yo'q) — barcha xavf foydalanuvchining o'z qarorida.
- 30m ni `.env` da qaytarib qo'shsangiz (`TIMEFRAMES=5m,15m,30m,1h,4h`), u ham ishlaydi, lekin tarixiy sinovda foyda keltirmagan.
