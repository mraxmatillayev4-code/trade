# 🚀 Trading Signal Telegram Bot

Kripto bozori uchun **faqat analitik signal** beruvchi Telegram bot.

Bot 5 ta mustaqil strategiyani real vaqtga yaqin rejimda ishlatadi, strategiyalar
bir-birini tasdiqlagandagina BUY/SELL signalini yaratadi, Telegram orqali yuboradi,
signal natijasini kuzatadi va barcha statistikani saqlaydi.

> ⚠️ **MUHIM OGOHLANTIRISH:**
> Bot avtomatik order ochmaydi, pulingizni boshqarmaydi, leverage ishlatmaydi.
> Hech bir tizim signallarga 80–90% aniqlikni **kafolatlay olmaydi** — bozor oldindan
> aytib bo‘lmaydi. Bot signallari faqat tahliliy ma'lumot; qaror va mas'uliyat
> butunlay sizniki. Kam, lekin ko‘p tasdiqli signal berish uchun filtrlar ataylab
> qattiq qilingan.

---

## 📋 Imkoniyatlar

- **10 strategiya:** EMA+RSI+MACD, Supertrend+EMA, VWAP+RSI, Breakout+Volume,
  RSI Divergence, Squeeze Breakout, Ichimoku Cloud, Price Action (sham shakllari),
  Stochastic %K/%D, OBV hajm oqimi
- Coin nomlari bozordagi aniq ko'rinishda: `SOLUSDT` → **SOL/USDT (Solana)**
- Har bir strategiyada **asosiy shartlar + qo'shimcha sifat filtrlari** (kuchaytirilgan tahlil)
- **Bozor rejimi:** TRENDING / RANGING / HIGH_VOLATILITY / LOW_VOLATILITY
- **Multi-timeframe tasdig‘i:** 4H → asosiy trend, 1H → tasdiq, 15m → kirish, 5m → qo‘shimcha
- **Anti-repaint:** signal faqat sham **yopilgandan keyin** hisoblanadi
- **Weighted scoring** + 3 sifat rejimi: Aggressive / Balanced / Conservative
- **Risk:** ATR asosida SL, TP1=1R / TP2=2R / TP3=3R
- **Paper trading:** virtual $10,000 bilan natija kuzatuvi (haqiqiy pul yo‘q)
- **Backtest + Walk-forward** (live bilan bir xil mantiq, look-ahead bias yo‘q)
- **Deduplikatsiya:** bir xil signal qayta yuborilmaydi (DB-level constraint)
- Signal lifecycle: CREATED → ACTIVE → TP1/TP2/TP3/SL/EXPIRED
- Statistika: win rate, profit factor, drawdown, avg R, eng yaxshi strategiya/coin/TF
- Binance REST + WebSocket (avto-reconnect, eksponensial backoff, endpoint fallback)
- FastAPI: REST endpointlar + TradingView webhook (HMAC imzo bilan)
- To‘liq **o‘zbek tilidagi** interfeys

---

## 🏗 Loyiha tuzilmasi

```text
trading_signal_bot/
├── app/
│   ├── main.py                  # Kirish nuqtasi (all | bot | api)
│   ├── core/                    # Config, logging, enums, xavfsizlik, redis
│   ├── database/
│   │   ├── models/              # SQLAlchemy modellar (14 jadval)
│   │   ├── session.py, base.py, seed.py, crud.py
│   ├── market/                  # Binance REST, WebSocket, candle manager
│   ├── indicators/              # EMA, RSI, MACD, ATR, ADX, Supertrend,
│   │                            #   VWAP, Bollinger, pivotlar, divergensiya
│   ├── strategies/              # 5 ta strategiya (umumiy interfeys)
│   ├── engine/                  # signal_engine, scoring, risk,
│   │                            #   market_regime, mtf, dedup, lifecycle
│   ├── backtest/                # engine, metrics, walk_forward
│   ├── paper_trading/           # virtual pozitsiyalar
│   ├── services/                # pipeline, tracker, statistics, explanation
│   ├── notifications/           # Telegram formatlash va yuborish
│   ├── bot/                     # aiogram 3.x handlerlar, keyboardlar
│   └── api/                     # FastAPI server + webhook
├── tests/                       # pytest (39+ test)
├── migrations/                  # Alembic
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## 🛠 O‘rnatish (lokal)

### 1. Talablar
- Python **3.12+**
- PostgreSQL 16 (yoki testlar uchun SQLite — qo‘shimcha sozlashsiz ishlaydi)
- Redis 7 (ixtiyoriy — ishlamasa xotira cache'ga o‘tadi)

### 2. Repozitoriy va kutubxonalar
```bash
cd trading_signal_bot
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. `.env` sozlash
```bash
cp .env.example .env
```
`.env` ichida quyidagilarni to‘ldiring:

```env
BOT_TOKEN=123456:ABC...        # @BotFather dan
ADMIN_IDS=123456789            # sizning Telegram ID (@userinfobot dan biling)
DATABASE_URL=postgresql+asyncpg://trader:trader_pass@localhost:5432/trading_bot
REDIS_URL=redis://localhost:6379/0
```

Binance public market data uchun **API kalit shart emas** (limiting past bo‘ladi xolos).

### 4. PostgreSQL
```bash
# Docker bilan (eng oson):
docker compose up -d postgres redis

# Yoki lokal:
createdb trading_bot
```

### 5. Migratsiya
```bash
alembic upgrade head
```
(Jadvallar birinchi ishga tushganda ham avtomatik yaratiladi.)

### 6. Ishga tushirish
```bash
# Hammasi bitta jarayonda (bot + API + scheduler + WebSocket):
python -m app.main all

 # Faqat bot (production):
python -m app.main bot

# Faqat API:
python -m app.main api
```

---

## 🚀 Render (free tier) deploy

Loyihada `render.yaml` blueprint mavjud — eng oson yo'l:

1. Kodni GitHub'ga yuklang.
2. [render.com](https://render.com) → **New → Blueprint** → repozitoriyni tanlang.
3. Avtomatik yaratiladi:
   - **Web service** (Docker, bot + API + scheduler bitta jarayonda)
   - **PostgreSQL** (free tier)
4. Environment variables ni to'ldiring:
   - `BOT_TOKEN` — @BotFather dan
   - `ADMIN_IDS` — sizning Telegram ID
   - `DATABASE_URL` — blueprint avtomatik ulaydi (qo'lda kiritmang)
   - `REDIS_URL` — free tier'da **bo'sh qoldiring** (Redis'siz, xotira cache bilan ishlaydi)

> 📌 Eslatma: free web service 15 daqiqa harakatsizlikdan keyin "uxlaydi".
> Buni oldini olish uchun quyidagi UptimeRobot sozlanadi.

### 📟 UptimeRobot (botni uyg'oq tutish)

1. [uptimerobot.com](https://uptimerobot.com) → bepul hisob.
2. **Add New Monitor**:
   - Type: **HTTP(s)**
   - URL: `https://SIZNING-RENDER-URL.onrender.com/health`
   - Interval: **5 daqiqa**
3. `/health` endpoint har 5 daqiqada tekshiriladi → servis uxlamaydi,
   WebSocket va signal tahlili uzluksiz ishlaydi.

### ⚠️ Render free tier cheklovlari
- Oyiga 750 soat limit (bitta servis bilan yetadi)
- Vaqti-vaqti bilan restart — barcha signallar **PostgreSQL'da saqlanadi**, yo'qolmaydi

## 🐳 Docker deployment

```bash
cp .env.example .env   # qiymatlarni to'ldiring
docker compose up -d --build
```

Servislar:
- `postgres` — ma'lumotlar bazasi (health check bilan)
- `redis` — cache
- `bot` — Telegram polling + scheduler + WebSocket + signal engine
- `api` — FastAPI, `http://localhost:8000`

---

## ✅ Testlar

```bash
pytest -v
```

Testlar SQLite'da ishlaydi (`DATABASE_URL` env orqali o‘zgartirish mumkin):
- indikatorlar (EMA, RSI, MACD, ATR, ADX, Supertrend, pivotlar repaint yo‘qligi)
- strategiyalar (trendda BUY/SELL, range'da NEUTRAL)
- scoring (teng ovoz → NO SIGNAL, MTF qarshi → conservative blok)
- risk hisobi (SL/TP, R multiple)
- lifecycle (TP1→TP2→TP3, SL birinchi tekshiriladi, expiry)
- dedup (bir xil signal rad, qarshi yo‘nalish ruxsat)
- backtest (metrikalar, walk-forward, look-ahead tekshiruvi)

---

## 🧪 Backtesting

Bot menyusi orqali: **🧪 Backtest → coin → timeframe → davr → strategiya**.
Natija: tranzaksiyalar soni, win rate, profit factor, avg R, max drawdown,
strategiyalar kesimidagi ko‘rsatkichlar. **Walk-forward** tugmasi orqali
barqarorlik (stability) tekshiriladi.

Muhim qoidalar (loyihada hisobga olingan):
- parametrlar ko‘r-ko‘rona optimizatsiya qilinmaydi (overfitting oldini olish);
- kam tranzaksiya qiladigan strategiya "eng yaxshi" deb ko‘rsatilmaydi;
- win rate bilan birga PF, expectancy, drawdown, avg R birga baholanadi.

---

## ⚙️ Strategiya sozlamalari (`.env`)

| Parametr | Default | Tavsif |
|---|---|---|
| `QUALITY_MODE` | `BALANCED` | AGGRESSIVE (6.0+) / BALANCED (7.0+) / CONSERVATIVE (8.5+) |
| `ATR_SL_MULTIPLIER` | `1.5` | SL = entry ∓ ATR×mult |
| `TP1_R / TP2_R / TP3_R` | `1/2/3` | Take profit R darajalari |
| `RISK_PERCENT` | `1.0` | Paper trading riski (har signalda %) |
| `WEIGHT_EMA/SUPERTREND/VWAP/BREAKOUT/DIVERGENCE` | 1.2/1.2/0.9/1.1/1.0 | Strategiya vaznlari |
| `SIGNAL_COOLDOWN_MINUTES` | `60` | Bir xil signal uchun kutish |
| `SIGNAL_EXPIRY_CANDLES` | `100` | Signal necha shamdan keyin tugaydi |
| `MULTI_TIMEFRAME_ENABLED` | `true` | Yuqori TF tasdig'i |
| `VOLUME_MULTIPLIER` | `1.5` | Breakout hajm filtri |
| `SYMBOLS / TIMEFRAMES` | 9 coin / 5 TF | Kuzatuv ro'yxati |

---

## 📡 REST API

| Endpoint | Tavsif |
|---|---|
| `GET /health` | Tizim holati |
| `GET /api/signals` | So‘nggi signallar (`?direction=BUY`, `?limit=`) |
| `GET /api/signals/{id}` | Bitta signal + strategiya tasdiqlari |
| `GET /api/statistics` | Umumiy statistika |
| `GET /api/strategies` | Strategiyalar kesimidagi stat |
| `GET /api/market/{symbol}` | 24 soatlik ticker |
| `POST /api/backtest` | Backtest tarixi |
| `GET /api/backtest/{id}` | Backtest natijasi |
| `POST /webhook/tradingview` | TradingView webhook (HMAC imzo majburiy) |

Webhook signallari **avtomatik ishonchli qabul qilinmaydi** — bot o‘z dvigateli
bilan qayta tahlil qilib, tasdiqlangandagina qabul qiladi.

---

## 🔄 Ma'lumot oqimi

```
REAL MARKET DATA (Binance WS/REST)
       ↓
CANDLE CLOSE (faqat yopilgan sham)
       ↓
DATA QUALITY (gap, narx, hajm)
       ↓
INDIKATORLAR (EMA/RSI/MACD/ATR/ADX/ST/VWAP/BB)
       ↓
5 STRATEGIYA (har biri kuchaytirilgan filtrlar bilan)
       ↓
MARKET REGIME → strategiya vaznlari moslashadi
       ↓
MULTI-TIMEFRAME FILTER (1H/4H trend)
       ↓
WEIGHTED SCORING (0–10)
       ↓
RISK: ATR → SL, 1R/2R/3R → TP
       ↓
VALIDATION (threshold + dedup + cooldown)
       ↓
DATABASE (PostgreSQL)
       ↓
TELEGRAM (o'zbekcha signal)
       ↓
PAPER TRADING (virtual)
       ↓
LIFECYCLE TRACKING (TP/SL) → STATISTIKA
```

---

## 🔒 Xavfsizlik

- Barcha sirlar `.env` da, kodda yo‘q; `.env` `.gitignore` da
- Webhook HMAC-SHA256 imzo + timestamp tekshiruvi
- SQLAlchemy ORM — SQL injection himoyasi
- DB-level partial unique index — bir vaqtda bitta ochiq signal

---

## ⚠️ Mas'uliyat rad etilishi

Ushbu bot ta'lim va tahliliy maqsadlarda taqdim etiladi. Kripto savdosi yuqori
xavfli va kapitalingizni yo‘qotishingiz mumkin. Bot signallariga asoslangan
har qanday savdo qarori uchun javobgarlik faqat sizda.
