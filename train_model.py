"""Train and save the CO₂ predictors, one model per state.

Usage:
    python train_model.py              train every state that has enough daily data
    python train_model.py --state KY   train one state

Each run rebuilds models_saved/co2_predictor_<STATE>.joblib and adds a row to the model_runs
table. The web app only loads the saved files; it never trains on startup.
"""

import argparse
import sys

from sqlalchemy import func

from app import app
from models import FacilityRecord, db
from services import ml_service


def states_with_daily_data():
    f = FacilityRecord
    rows = (db.session.query(f.state).filter(f.record_hour.is_(None), func.length(f.record_date) == 10,
                                             f.state.isnot(None))
            .group_by(f.state).order_by(f.state).all())
    return [s for (s,) in rows]


def print_result(result):
    print(f"\n=== {result['state']} ===")
    print(f"  Train: {result['train_rows']} unit-days, {result['train_dates'][0]} to {result['train_dates'][1]} "
          f"({result['train_facilities']} facilities)")
    print(f"  Test:  {result['test_rows']} unit-days, {result['test_dates'][0]} to {result['test_dates'][1]} "
          f"({result['test_facilities']} facilities)")
    print(f"  Inputs: {', '.join(result['features'])}  (state is not an input)")
    print(f"  Target: {result['target']} ({result['target_units']})")
    for name, scores in result["metrics"].items():
        test = scores["test"]
        r2 = "n/a" if test["r2"] is None else f"{test['r2']:.3f}"
        cv = scores["validation"]
        cv_text = f"  CV RMSE={cv['cv_rmse_mean']:.1f}" if cv else ""
        print(f"  {name:<32} MAE={test['mae']:.1f}  RMSE={test['rmse']:.1f}  R2={r2}{cv_text}")
    print(f"  Selected (lowest CV RMSE): {result['selected_model']}")
    print(f"  Used for what-if sensitivity: {result['sensitivity_model']}")
    print(f"  Saved to: {result['artifact_path']}")


def main():
    # Windows consoles default to cp1252, which cannot print the subscript characters in the units
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Train the per-state CO₂ models.")
    parser.add_argument("--state", help="two-letter state code, for example KY. Default: every state with daily data.")
    args = parser.parse_args()

    failures = 0
    with app.app_context():
        states = [args.state.upper()] if args.state else states_with_daily_data()
        if not states:
            print("No daily per-unit data found. Run scripts/fetch_campd_hourly.py first.")
            return 1
        for state in states:
            try:
                print_result(ml_service.train(state, save=True))
            except ValueError as exc:
                failures += 1
                print(f"\n{state}: training skipped. {exc}")
    return 1 if failures == len(states) else 0


if __name__ == "__main__":
    sys.exit(main())
