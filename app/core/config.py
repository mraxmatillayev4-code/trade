"""Markaziy konfiguratsiya — barcha parametrlar .env orqali boshqariladi."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.enums import QualityMode


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Telegram ---
    bot_token: str = ""
    admin_ids: str = ""
    # Foydalanuvchi Telegram akkaunti (kanallarni admin'siz o'qish). my.telegram.org
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_session: str = ""

    # --- Database / cache ---
    database_url: str = "postgresql+asyncpg://trader:trader_pass@localhost:5432/trading_bot"
    redis_url: str = "redis://localhost:6379/0"

    # --- Binance ---
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_base_url: str = "https://api.binance.com"
    binance_ws_url: str = "wss://stream.binance.com:9443/ws"

    # --- Kuzatuv ro'yxati (forex + oltin + kumush + neft + bitcoin) ---
    # EURUSDT=EUR/USD, XAUUSDT=Oltin, SILVERUSDT=Kumush(XAG), USOILUSDT=Neft(WTI), BTCUSDT
    symbols: str = "EURUSDT,BTCUSDT,XAUUSDT,SILVERUSDT,USOILUSDT,UKOILUSDT"
    # 30m backtest'da zaif chiqdi — standart kuzatuvdan olib tashlandi (xohlasangiz qo'shing)
    timeframes: str = "5m,15m,1h,4h"

    # --- Signal sifati ---
    # Rejim AGGRESSIVE, lekin scoring dagi JUDA QATTIQ darvozalar barcha rejimda ishlaydi
    quality_mode: QualityMode = QualityMode.AGGRESSIVE
    score_aggressive: float = 6.0
    score_balanced: float = 6.8
    score_conservative: float = 8.0

    # --- Indikatorlar ---
    rsi_period: int = 14
    ema_fast: int = 50
    ema_slow: int = 200
    ema_mid: int = 20
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    adx_period: int = 14
    atr_period: int = 14
    supertrend_period: int = 10
    supertrend_multiplier: float = 3.0
    vwap_window: int = 20
    volume_multiplier: float = 1.5

    # --- Faol strategiyalar (faqat shu 5 tasi ovoz beradi; qolganlari kodi turadi, ishlamaydi) ---
    # 3 trend-davom strategiyasi (pullback/retest/momentum) pullback tiklanishida bir ovoz beradi;
    # squeeze (breakout) va SMC (sweep reversal) yuqori sifatli alohida kirishlar.
    active_strategies: str = (
        "ema_pullback,supertrend_pullback,trend_momentum,"
        "squeeze_breakout,smart_money"
    )

    # --- Strategiya vaznlari ---
    weight_ema: float = 1.2
    weight_supertrend: float = 1.2
    weight_vwap: float = 1.0
    weight_breakout: float = 1.1
    weight_divergence: float = 1.0
    weight_squeeze: float = 1.2
    weight_ichimoku: float = 1.2
    weight_price_action: float = 1.0
    weight_stochastic: float = 0.8
    weight_obv: float = 0.9
    weight_smart_money: float = 1.3   # SMC konfluentlik — eng yuqori vazn
    weight_cvd: float = 0.9
    # Yangi 5 likdagi strategiyalar uchun vazn (mavjud keylarga mos)
    weight_ema_pullback: float = 1.2
    weight_supertrend_pullback: float = 1.2
    weight_trend_momentum: float = 1.1
    weight_brain: float = 1.45   # SINO AI — inson-ovozi, eng yuqori vaznlardan
    weight_vwap_reversion: float = 1.0
    weight_bb_reversion: float = 1.1
    weight_rsi_reversion: float = 1.0
    killzone_filter: bool = False     # AI o'zi tanlaydi — sessiya bloki yo'q

    # --- Signal hajmi / hisobot ---
    daily_signal_target: int = 24
    daily_signal_max: int = 36      # kuniga 20-30 maqsad, yuqori chegara 36
    chart_candles: int = 70
    report_time_utc: int = 19  # UTC+5 (Toshkent) yarim tuniga mos

    # --- Risk ---
    atr_sl_multiplier: float = 1.5
    tp1_r: float = 1.0
    tp2_r: float = 2.0
    tp3_r: float = 3.0
    # v82: risk/money management — hajm balansning shu foizidan hisoblanadi
    risk_percent: float = 0.5
    # === v68: HAJM (lot) va pul hisobi — terminaldagi kabi ===
    lot_size: float = 1.0                 # v82: hajm uchun YUQORI chegara (max lot)
    contract_size: float = 100.0          # 1 lot XAU = 100 oz (pul = narx farqi x 100 x lot)
    paper_initial_balance: float = 10_000.0

    # --- Signal qoidalari ---
    # Cooldown qisqa: ko'p signal chiqishiga to'sqinlik qilmaydi (pastki chegara ~10,
    # yuqori chegara YO'Q — 30-50 ta bo'lsa ham yuborilaveradi).
    signal_cooldown_minutes: int = 15
    signal_expiry_candles: int = 36

    # --- Kanal signallari (asosan 1m OLTIN) ---
    channel_timeframe: str = "1m"        # kanal signali yozilmagan bo'lsa shu TF
    channel_use_post_tp: bool = True     # kanal o'zi yozgan TP larni ishlatish
    channel_expiry_minutes: int = 240    # M1 signal shu daqiqada yopilmasa: muddat tugadi
    max_active_signals: int = 3           # v67: BIR YO'NALISH uchun maks. faol signal
    #   Bir vaqtda faqat BITTA yo'nalish ishlaydi: qarama-qarshi yo'nalish signali
    #   olinmaydi (real savdoda 2 SELL + 1 BUY birga o'ynalmaydi).
    expiry_sweep_seconds: int = 300      # muddat tekshiruvi davri (sekund)
    # v56: kanal yangi ulanganda TARIX o'qilmaydi (0 = umuman o'qilmasin).
    # 2 qilsangiz — oxirgi 2 ta eski xabar o'qiladi (odatda kerak emas).
    channel_catchup_count: int = 0
    multi_timeframe_enabled: bool = True
    store_candles: bool = True
    # Ixtiyoriy tashqi AI (Groq/OpenAI mos). Bo'sh = faqat mahalliy AI.
    ai_api_key: str = ""
    ai_api_url: str = "https://api.groq.com/openai/v1/chat/completions"
    ai_api_model: str = "llama-3.1-8b-instant"

    # --- Market data ---
    history_candles: int = 500
    rest_poll_seconds: int = 15
    ws_enabled: bool = True

    # --- Webhook ---
    webhook_secret: str = ""

    # --- Boshqa ---
    log_level: str = "INFO"
    maintenance_mode: bool = False
    default_timezone: str = "UTC+5"

    @field_validator("symbols", "timeframes", "admin_ids", mode="before")
    @classmethod
    def _strip_and_clean(cls, v: object) -> str:
        if isinstance(v, (list, tuple)):
            return ",".join(str(x).strip() for x in v if str(x).strip())
        return str(v).strip()

    # ---- Qulaylik xossalari ----
    @property
    def database_url_async(self) -> str:
        """Render/Heroku `postgresql://` yoki `postgres://` ni asyncpg'ga moslaydi."""
        url = self.database_url
        for prefix in ("postgresql+asyncpg://", "postgresql+psycopg2://",
                       "postgresql://", "postgres://"):
            if url.startswith(prefix) and prefix != "postgresql+asyncpg://":
                return "postgresql+asyncpg://" + url[len(prefix):]
        return url

    @property
    def admin_id_list(self) -> list[int]:
        return [int(x) for x in self.admin_ids.split(",") if x.strip().isdigit()]

    @property
    def symbol_list(self) -> list[str]:
        # OLTIN har doim kuzatiladi (kanallar asosan oltin beradi)
        syms = [s.strip().upper() for s in self.symbols.split(",") if s.strip()]
        if "XAUUSDT" not in syms:
            syms.insert(0, "XAUUSDT")
        return syms

    @property
    def timeframe_list(self) -> list[str]:
        return [t.strip().lower() for t in self.timeframes.split(",") if t.strip()]

    @property
    def watch_timeframe_list(self) -> list[str]:
        """Kanal M1 signallari uchun 1m ham doim kuzatiladi."""
        tfs = list(self.timeframe_list)
        if "1m" not in tfs:
            tfs = ["1m"] + tfs
        return tfs

    def expiry_minutes_for(self, timeframe: str, quality_mode: str = "") -> int:
        """Signal muddati (daqiqa). Kanal M1 signallari uchun alohida sozlama."""
        tf = (timeframe or "1m").lower()
        if (quality_mode or "").upper() == "CHANNEL":
            return max(5, int(self.channel_expiry_minutes))
        per_tf = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
                  "1h": 60, "4h": 240, "1d": 1440}.get(tf, 15)
        return max(10, per_tf * max(1, int(self.signal_expiry_candles)))

    @property
    def active_strategy_keys(self) -> list[str]:
        """Faqat shu strategiyalar ishlaydi/ovoz beradi (qolganlari kodi turadi, lekin neytral)."""
        return [s.strip() for s in self.active_strategies.split(",") if s.strip()]

    @property
    def strategy_weights(self) -> dict[str, float]:
        return {
            # faol (yangi 5 lik)
            "ema_pullback": self.weight_ema_pullback,
            "supertrend_pullback": self.weight_supertrend_pullback,
            "trend_momentum": self.weight_trend_momentum,
            "squeeze_breakout": self.weight_squeeze,
            "smart_money": self.weight_smart_money,
            "vwap_reversion": self.weight_vwap_reversion,
            "bb_reversion": self.weight_bb_reversion,
            "rsi_reversion": self.weight_rsi_reversion,
            # nofaol (kodi saqlanadi, vazn kerak bo'lsa)
            "ema_trend": self.weight_ema,
            "supertrend": self.weight_supertrend,
            "vwap": self.weight_vwap,
            "breakout": self.weight_breakout,
            "divergence": self.weight_divergence,
            "squeeze": self.weight_squeeze,
            "ichimoku": self.weight_ichimoku,
            "price_action": self.weight_price_action,
            "stochastic": self.weight_stochastic,
            "obv": self.weight_obv,
            "cvd": self.weight_cvd,
            "wavetrend": 1.2,
            "squeeze_breakout": self.weight_squeeze,
            "brain": self.weight_brain,
        }

    def min_score(self, mode: QualityMode | None = None) -> float:
        mode = mode or self.quality_mode
        return {
            QualityMode.AGGRESSIVE: self.score_aggressive,
            QualityMode.BALANCED: self.score_balanced,
            QualityMode.CONSERVATIVE: self.score_conservative,
        }[mode]

    @property
    def min_candles(self) -> int:
        """Indikatorlar (EMA200 + pivot tasdig'i) uchun kerakli minimal shamlar."""
        return self.ema_slow + 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
