"""ML-based Market Regime Detection using Hidden Markov Model (HMM)."""
from __future__ import annotations

import json
import os
import pickle
import warnings
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from app.core.enums import MarketRegime
from app.core.logging import get_logger
from app.indicators.bundle import IndicatorBundle

if TYPE_CHECKING:
    from app.core.config import Settings

logger = get_logger(__name__)

warnings.filterwarnings("ignore", category=UserWarning)

MODEL_DIR = "models/regime"
MODEL_PATH = os.path.join(MODEL_DIR, "hmm_regime_model.pkl")
SCALER_PATH = os.path.join(MODEL_DIR, "hmm_scaler.pkl")
META_PATH = os.path.join(MODEL_DIR, "hmm_meta.json")

N_REGIMES = 4
REGIME_MAP = {
    0: MarketRegime.TRENDING,
    1: MarketRegime.RANGING,
    2: MarketRegime.HIGH_VOLATILITY,
    3: MarketRegime.LOW_VOLATILITY,
}

FEATURE_COLUMNS = [
    "returns",
    "log_volume",
    "atr_pct",
    "adx_norm",
    "ema_separation",
    "hurst",
    "vol_of_vol",
    "rsi",
    "bb_width",
    "volume_trend",
]

_min_train_samples = 500
_retrain_interval_hours = 24

_last_trained: dict[str, datetime] = {}
_models: dict[str, tuple] = {}


def _prepare_features(df: pd.DataFrame, bundle: IndicatorBundle | None = None) -> np.ndarray:
    """Prepare feature matrix for HMM."""
    features = pd.DataFrame(index=df.index)

    features["returns"] = df["close"].pct_change()
    features["log_volume"] = np.log(df["volume"] + 1)
    features["log_volume"] = (features["log_volume"] - features["log_volume"].rolling(50).mean()) / (features["log_volume"].rolling(50).std() + 1e-8)

    if bundle:
        atr_pct = bundle.atr / bundle.close * 100
        features["atr_pct"] = atr_pct
        features["adx_norm"] = bundle.adx / 50.0
        ema_sep = abs(bundle.ema50 - bundle.ema200) / bundle.close * 100
        features["ema_separation"] = ema_sep

        close_series = bundle.close
        lags = range(2, min(20, len(close_series) // 2))
        hurst_vals = []
        for i in range(len(close_series)):
            if i < 20:
                hurst_vals.append(0.5)
                continue
            sub = close_series.iloc[max(0, i-100):i+1]
            if len(sub) < 20:
                hurst_vals.append(0.5)
                continue
            try:
                tau = []
                for lag in range(2, min(20, len(sub) // 2)):
                    diff = sub.diff(lag).dropna()
                    if len(diff) > 0:
                        tau.append(np.sqrt(np.std(diff)))
                if len(tau) >= 5 and max(tau) > 0:
                    poly = np.polyfit(np.log(list(range(2, 2 + len(tau)))), np.log(tau), 1)
                    hurst_vals.append(float(poly[0]))
                else:
                    hurst_vals.append(0.5)
            except Exception:
                hurst_vals.append(0.5)
        features["hurst"] = hurst_vals

        atr_returns = bundle.atr.pct_change().dropna()
        vol_of_vol = atr_returns.rolling(50).std() / (atr_returns.rolling(50).mean() + 1e-8)
        features["vol_of_vol"] = vol_of_vol.reindex(df.index).fillna(1.0)

        delta = bundle.close.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = -delta.where(delta < 0, 0).rolling(14).mean()
        rs = gain / (loss + 1e-8)
        features["rsi"] = 100 - (100 / (1 + rs))
        features["rsi"] = features["rsi"] / 100.0

        bb_width = (bundle.bb_upper - bundle.bb_lower) / bundle.bb_mid
        features["bb_width"] = bb_width.fillna(0)

        features["volume_trend"] = df["volume"].rolling(20).apply(
            lambda x: np.polyfit(range(len(x)), x, 1)[0] if len(x) == 20 else 0
        ) / (df["volume"].rolling(20).mean() + 1e-8)

    features = features.fillna(method="ffill").fillna(0)
    return features[FEATURE_COLUMNS].values


def _get_or_create_model(symbol: str, timeframe: str) -> tuple:
    """Get cached model or create new one."""
    key = f"{symbol}_{timeframe}"

    if key in _models:
        model, scaler, meta = _models[key]
        last_train = _last_trained.get(key)
        if last_train and (datetime.now(timezone.utc) - last_train).total_seconds() < _retrain_interval_hours * 3600:
            return model, scaler, meta

    if os.path.exists(MODEL_PATH.replace(".pkl", f"_{key}.pkl")):
        try:
            with open(MODEL_PATH.replace(".pkl", f"_{key}.pkl"), "rb") as f:
                model = pickle.load(f)
            with open(SCALER_PATH.replace(".pkl", f"_{key}.pkl"), "rb") as f:
                scaler = pickle.load(f)
            with open(META_PATH.replace(".json", f"_{key}.json"), "r") as f:
                meta = json.load(f)
            _models[key] = (model, scaler, meta)
            _last_trained[key] = datetime.fromisoformat(meta["trained_at"])
            logger.info(f"Loaded HMM model for {key}")
            return model, scaler, meta
        except Exception as exc:
            logger.warning(f"Failed to load model for {key}: {exc}")

    from hmmlearn import hmm
    from sklearn.preprocessing import StandardScaler

    model = hmm.GaussianHMM(
        n_components=N_REGIMES,
        covariance_type="full",
        n_iter=100,
        random_state=42,
        init_params="stmc",
    )
    scaler = StandardScaler()
    meta = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_samples": 0,
        "symbol": symbol,
        "timeframe": timeframe,
        "transition_matrix": None,
        "means": None,
        "covars": None,
    }
    _models[key] = (model, scaler, meta)
    return model, scaler, meta


def _save_model(symbol: str, timeframe: str, model, scaler, meta: dict) -> None:
    """Save model to disk."""
    os.makedirs(MODEL_DIR, exist_ok=True)
    key = f"{symbol}_{timeframe}"

    try:
        with open(MODEL_PATH.replace(".pkl", f"_{key}.pkl"), "wb") as f:
            pickle.dump(model, f)
        with open(SCALER_PATH.replace(".pkl", f"_{key}.pkl"), "wb") as f:
            pickle.dump(scaler, f)
        meta["trained_at"] = datetime.now(timezone.utc).isoformat()
        with open(META_PATH.replace(".json", f"_{key}.json"), "w") as f:
            json.dump(meta, f)
        _last_trained[key] = datetime.now(timezone.utc)
        logger.info(f"Saved HMM model for {key}")
    except Exception as exc:
        logger.warning(f"Failed to save model for {key}: {exc}")


def train_regime_model(
    df: pd.DataFrame,
    bundle: IndicatorBundle,
    symbol: str,
    timeframe: str,
    force: bool = False,
) -> bool:
    """Train or update HMM regime model."""
    key = f"{symbol}_{timeframe}"

    if not force:
        last_train = _last_trained.get(key)
        if last_train and (datetime.now(timezone.utc) - last_train).total_seconds() < _retrain_interval_hours * 3600:
            return False

    try:
        features = _prepare_features(df, bundle)
        features = features[~np.isnan(features).any(axis=1)]
        features = features[~np.isinf(features).any(axis=1)]

        if len(features) < _min_train_samples:
            logger.warning(f"Insufficient data for HMM training {key}: {len(features)} < {_min_train_samples}")
            return False

        model, scaler, meta = _get_or_create_model(symbol, timeframe)

        scaled_features = scaler.fit_transform(features)
        model.fit(scaled_features)

        meta["n_samples"] = len(features)
        meta["transition_matrix"] = model.transmat_.tolist()
        meta["means"] = model.means_.tolist()
        meta["covars"] = [c.tolist() for c in model.covars_]

        _save_model(symbol, timeframe, model, scaler, meta)
        logger.info(f"HMM model trained for {key} with {len(features)} samples")
        return True

    except Exception as exc:
        logger.error(f"HMM training failed for {key}: {exc}")
        return False


def predict_regime(
    df: pd.DataFrame,
    bundle: IndicatorBundle,
    symbol: str,
    timeframe: str,
) -> tuple[MarketRegime, dict[int, float], dict]:
    """
    Predict current regime using HMM.
    Returns: (regime, state_probabilities, metadata)
    """
    key = f"{symbol}_{timeframe}"

    try:
        model, scaler, meta = _get_or_create_model(symbol, timeframe)

        features = _prepare_features(df, bundle)
        if len(features) == 0:
            return MarketRegime.RANGING, {i: 0.25 for i in range(N_REGIMES)}, {"error": "No features"}

        last_features = features[-1:].reshape(1, -1)
        scaled = scaler.transform(last_features)

        if not hasattr(model, "transmat_"):
            return MarketRegime.RANGING, {i: 0.25 for i in range(N_REGIMES)}, {"error": "Model not trained"}

        log_prob, posteriors = model.score_samples(scaled)
        state_probs = posteriors[0]

        predicted_state = int(np.argmax(state_probs))
        regime = REGIME_MAP.get(predicted_state, MarketRegime.RANGING)

        trans_matrix = model.transmat_
        next_state_probs = trans_matrix[predicted_state]

        metadata = {
            "predicted_state": predicted_state,
            "state_probabilities": {i: float(p) for i, p in enumerate(state_probs)},
            "next_state_probabilities": {REGIME_MAP[i]: float(p) for i, p in enumerate(next_state_probs)},
            "log_likelihood": float(log_prob),
            "transition_matrix": trans_matrix.tolist(),
            "regime_means": model.means_.tolist(),
            "model_trained": meta.get("n_samples", 0) > 0,
        }

        return regime, {i: float(p) for i, p in enumerate(state_probs)}, metadata

    except Exception as exc:
        logger.warning(f"HMM prediction failed for {key}: {exc}")
        return MarketRegime.RANGING, {i: 0.25 for i in range(N_REGIMES)}, {"error": str(exc)}


def get_regime_transition_probability(
    current_regime: MarketRegime,
    target_regime: MarketRegime,
    symbol: str,
    timeframe: str,
) -> float:
    """Get probability of transitioning from current to target regime."""
    key = f"{symbol}_{timeframe}"
    try:
        _, _, meta = _get_or_create_model(symbol, timeframe)
        trans_matrix = meta.get("transition_matrix")
        if not trans_matrix:
            return 0.25

        current_idx = list(REGIME_MAP.values()).index(current_regime)
        target_idx = list(REGIME_MAP.values()).index(target_regime)
        return float(trans_matrix[current_idx][target_idx])
    except Exception:
        return 0.25


def get_regime_persistence(regime: MarketRegime, symbol: str, timeframe: str) -> float:
    """Get probability of staying in current regime."""
    return get_regime_transition_probability(regime, regime, symbol, timeframe)


def should_retrain(symbol: str, timeframe: str, new_samples: int) -> bool:
    """Check if model should be retrained based on new data."""
    key = f"{symbol}_{timeframe}"
    last_train = _last_trained.get(key)
    if not last_train:
        return True
    hours_since = (datetime.now(timezone.utc) - last_train).total_seconds() / 3600
    return hours_since >= _retrain_interval_hours or new_samples >= 1000


async def auto_retrain_if_needed(
    df: pd.DataFrame,
    bundle: IndicatorBundle,
    symbol: str,
    timeframe: str,
    new_candles_count: int = 1,
) -> bool:
    """Automatically retrain model if conditions are met."""
    if should_retrain(symbol, timeframe, new_candles_count):
        return train_regime_model(df, bundle, symbol, timeframe, force=True)
    return False