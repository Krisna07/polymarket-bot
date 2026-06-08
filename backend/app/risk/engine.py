from dataclasses import dataclass

from backend.app.config import Settings
from backend.app.ml.inference import MLPrediction


@dataclass
class TradeSignal:
    fair_probability: float
    market_probability: float
    edge: float
    confidence: float
    position_size: float
    ml_score: float
    approved: bool
    rejection_reason: str | None = None


class RiskEngine:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def evaluate(
        self,
        prediction: MLPrediction,
        market_probability: float,
        current_exposure_pct: float = 0.0,
    ) -> TradeSignal:
        edge = prediction.fair_probability - market_probability
        position_size = self._quarter_kelly(
            p=prediction.fair_probability,
            market_price=market_probability,
        )

        position_size = min(position_size, self._settings.max_position_pct)
        remaining = self._settings.max_total_exposure_pct - current_exposure_pct
        position_size = min(position_size, max(0.0, remaining))

        approved = True
        reason = None

        if abs(edge) < self._settings.min_edge:
            approved = False
            reason = f"edge {edge:.3f} below min {self._settings.min_edge}"
        elif prediction.confidence < self._settings.min_confidence:
            approved = False
            reason = f"confidence {prediction.confidence:.2f} below min"
        elif position_size <= 0:
            approved = False
            reason = "position size zero (exposure cap)"
        elif current_exposure_pct >= self._settings.max_total_exposure_pct:
            approved = False
            reason = "total exposure cap reached"

        return TradeSignal(
            fair_probability=prediction.fair_probability,
            market_probability=market_probability,
            edge=edge,
            confidence=prediction.confidence,
            position_size=position_size if approved else 0.0,
            ml_score=prediction.ml_score,
            approved=approved,
            rejection_reason=reason,
        )

    def _quarter_kelly(self, p: float, market_price: float) -> float:
        """Binary contract Kelly with quarter sizing. market_price = cost per share."""
        if market_price <= 0 or market_price >= 1:
            return 0.0
        b = (1.0 / market_price) - 1.0
        q = 1.0 - p
        if b <= 0:
            return 0.0
        full_kelly = (b * p - q) / b
        sized = self._settings.kelly_fraction * max(0.0, full_kelly)
        return sized
