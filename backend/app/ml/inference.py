from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import structlog

log = structlog.get_logger(__name__)

MODEL_PATH = Path(__file__).resolve().parents[3] / "ml" / "models" / "lightgbm_model.txt"


@dataclass
class MLPrediction:
    fair_probability: float
    confidence: float
    ml_score: float


class MLInferenceService:
    """
    LightGBM inference when a trained model exists.
    Falls back to heuristic probability from market microstructure for paper mode.
    """

    def __init__(self) -> None:
        self._model = None
        self._load_model()

    def _load_model(self) -> None:
        if MODEL_PATH.exists():
            try:
                import lightgbm as lgb

                self._model = lgb.Booster(model_file=str(MODEL_PATH))
                log.info("ml_model_loaded", path=str(MODEL_PATH))
            except Exception as e:
                log.warning("ml_model_load_failed", error=str(e))

    def predict(self, features: dict[str, Any], market_probability: float | None) -> MLPrediction:
        mp = market_probability if market_probability is not None else 0.5

        if self._model is not None:
            vector = self._features_to_vector(features)
            prob = float(self._model.predict(vector.reshape(1, -1))[0])
            prob = float(np.clip(prob, 0.01, 0.99))
            confidence = abs(prob - 0.5) * 2
            return MLPrediction(fair_probability=prob, confidence=confidence, ml_score=confidence)

        return self._heuristic_predict(features, mp)

    def _heuristic_predict(self, features: dict[str, Any], market_prob: float) -> MLPrediction:
        """Placeholder until trained on historical resolutions."""
        adjustment = 0.0
        imb = features.get("book_imbalance")
        mom = features.get("momentum_5snap")

        if imb is not None:
            adjustment += 0.02 * float(imb)
        if mom is not None:
            adjustment += 0.5 * float(mom)

        fair = float(np.clip(market_prob + adjustment, 0.05, 0.95))
        confidence = min(0.85, 0.5 + abs(fair - market_prob))
        return MLPrediction(
            fair_probability=fair,
            confidence=confidence,
            ml_score=confidence * abs(fair - market_prob),
        )

    @staticmethod
    def _features_to_vector(features: dict[str, Any]) -> np.ndarray:
        keys = [
            "best_bid",
            "best_ask",
            "mid_price",
            "spread",
            "spread_pct",
            "bid_depth",
            "ask_depth",
            "book_imbalance",
            "momentum_5snap",
        ]
        return np.array([float(features.get(k) or 0) for k in keys], dtype=np.float32)
