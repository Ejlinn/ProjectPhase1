"""Train and save the CO₂ predictor.

Usage:
    python train_model.py

This rebuilds models_saved/co2_predictor.joblib and adds a row to the model_runs table.
The web app only loads the saved file; it never trains on startup.
"""

import json
import sys

from app import app
from services import ml_service


def main():
    # Windows consoles default to cp1252, which cannot print the subscript characters in the units
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    with app.app_context():
        try:
            result = ml_service.train(save=True)
        except ValueError as exc:
            print(f"Training skipped: {exc}")
            return 1

    print("Model comparison (test set = held-out facilities)")
    print(f"  Train rows: {result['train_rows']} ({result['train_facilities']} facilities)")
    print(f"  Test rows:  {result['test_rows']} ({result['test_facilities']} facilities)")
    print(f"  Features:   {', '.join(result['features'])}")
    print(f"  Target:     {result['target']} ({result['target_units']})")
    print(f"  Split:      {result['split_method']}")
    for name, scores in result["metrics"].items():
        test = scores["test"]
        r2 = "n/a" if test["r2"] is None else f"{test['r2']:.3f}"
        print(f"  {name:<18} MAE={test['mae']:.2f}  RMSE={test['rmse']:.2f}  R2={r2}")
    print(f"Selected model (lowest CV RMSE): {result['selected_model']}")
    print(f"Saved to: {result['artifact_path']}")
    for note in result["notes"]:
        print(f"Note: {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
