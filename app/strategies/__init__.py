"""Strategiyalar paketi.

FAOL (ovoz beradigan) 5 ta yuqori sifatli strategiya — ACTIVE_STRATEGIES:
  1. Trend Pullback (EMA)        — trend ichida qaytishdan kirish
  2. Supertrend Retest           — trend chizig'iga qayta tegish
  3. Squeeze Breakout            — siqilishdan impuls chiqishi
  4. SMC (Sweep + FVG)           — likvidlik sweep + reversal
  5. VWAP Mean-Reversion         — range bozorda haddan oshishdan qaytish

Eski 12 strategiya kodi SAQLANADI (LEGACY_STRATEGIES) va import bo'lib turadi,
lekin tahlilda ishtirok etmaydi (ovoz bermaydi).
"""
from app.strategies.base import BaseStrategy, StrategyResult
# --- Faol strategiyalar ---
from app.strategies.ema_pullback import EmaPullbackStrategy
from app.strategies.supertrend_pullback import SupertrendPullbackStrategy
from app.strategies.trend_momentum import TrendMomentumStrategy
from app.strategies.squeeze_breakout import SqueezeBreakoutStrategy
from app.strategies.smart_money import SmartMoneyStrategy
from app.strategies.vwap_reversion import VwapReversionStrategy  # kodi saqlanadi (nofaol)
# --- Mean-reversion (forex/range bozor uchun) ---
from app.strategies.bb_reversion import BollingerReversionStrategy
from app.strategies.rsi_reversion import RsiReversionStrategy
# --- Eski (kodi saqlanadi, ishlamaydi) ---
from app.strategies.breakout import BreakoutVolumeStrategy
from app.strategies.cvd import CvdDivergenceStrategy
from app.strategies.divergence import RsiDivergenceStrategy
from app.strategies.ema_rsi_macd import EmaRsiMacdStrategy
from app.strategies.ichimoku import IchimokuStrategy
from app.strategies.obv import ObvVolumeFlowStrategy
from app.strategies.price_action import PriceActionStrategy
from app.strategies.squeeze import SqueezeBreakoutStrategy as _LegacySqueeze
from app.strategies.stochastic import StochasticStrategy
from app.strategies.supertrend_strat import SupertrendEmaStrategy
from app.strategies.vwap_rsi import VwapRsiStrategy
from app.strategies.wavetrend import WaveTrendStrategy

# Faol 5 lik — dvigatel shularni ishga tushiradi
ACTIVE_STRATEGIES: list[BaseStrategy] = [
    EmaPullbackStrategy(),
    SupertrendPullbackStrategy(),
    TrendMomentumStrategy(),
    SqueezeBreakoutStrategy(),
    SmartMoneyStrategy(),
]

# Eski 12 lik — faqat kod saqlanishi uchun (ishlatilmaydi)
LEGACY_STRATEGIES: list[BaseStrategy] = [
    EmaRsiMacdStrategy(),
    SupertrendEmaStrategy(),
    VwapRsiStrategy(),
    BreakoutVolumeStrategy(),
    RsiDivergenceStrategy(),
    _LegacySqueeze(),
    IchimokuStrategy(),
    PriceActionStrategy(),
    StochasticStrategy(),
    ObvVolumeFlowStrategy(),
    SmartMoneyStrategy(),
    CvdDivergenceStrategy(),
]

# Dvigatel uchun asosiy nom saqlandi (signal_engine ALL_STRATEGIES ni import qiladi)
ALL_STRATEGIES: list[BaseStrategy] = ACTIVE_STRATEGIES

# Barcha mavjud strategiya namunalari (yangi + legacy + mean-reversion) — key bo'yicha.
# Registry (har coin to'plami) shu lug'atdan tanlaydi.
ALL_POOL: list[BaseStrategy] = (
    list(ACTIVE_STRATEGIES)
    + list(LEGACY_STRATEGIES)
    + [BollingerReversionStrategy(), RsiReversionStrategy(), WaveTrendStrategy()]
)
STRATEGY_BY_KEY: dict[str, BaseStrategy] = {}
for _s in ALL_POOL:
    STRATEGY_BY_KEY.setdefault(_s.key, _s)


def strategies_for(symbol: str, timeframe: str) -> list[BaseStrategy]:
    """Asbob/timeframe uchun backtest-tanlangan strategiya ro'yxati."""
    from app.strategies.registry import strategy_keys_for
    keys = strategy_keys_for(symbol, timeframe)
    return [STRATEGY_BY_KEY[k] for k in keys if k in STRATEGY_BY_KEY]


__all__ = [
    "BaseStrategy",
    "StrategyResult",
    "ALL_STRATEGIES",
    "ACTIVE_STRATEGIES",
    "LEGACY_STRATEGIES",
    "ALL_POOL",
    "STRATEGY_BY_KEY",
    "strategies_for",
    "EmaPullbackStrategy",
    "SupertrendPullbackStrategy",
    "TrendMomentumStrategy",
    "SqueezeBreakoutStrategy",
    "SmartMoneyStrategy",
    "VwapReversionStrategy",
]
