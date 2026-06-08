"""
Train LightGBM on resolved markets once you have labels in Postgres.

Usage (after collecting historical data):
  python -m ml.train
"""

from pathlib import Path

import numpy as np

MODEL_OUT = Path(__file__).parent / "models" / "lightgbm_model.txt"


def main() -> None:
    print("Training requires resolved market labels in the database.")
    print("Implement label export from markets.resolution_outcome, then re-run.")
    print(f"Model will be saved to: {MODEL_OUT}")

    # Placeholder: synthetic demo to verify pipeline wiring
    try:
        import lightgbm as lgb
    except ImportError:
        print("lightgbm not installed")
        return

    X = np.random.rand(200, 9).astype(np.float32)
    y = (X[:, -1] > 0).astype(int)
    train_data = lgb.Dataset(X, label=y)
    params = {
        "objective": "binary",
        "metric": "auc",
        "verbosity": -1,
        "num_leaves": 15,
    }
    model = lgb.train(params, train_data, num_boost_round=50)
    MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(MODEL_OUT))
    print(f"Demo model saved to {MODEL_OUT}")


if __name__ == "__main__":
    main()
