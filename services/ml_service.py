"""CO₂ prediction models: a mean baseline, Ridge regression, and a random forest.

How the evaluation works (also explained on the dashboard):
1. Keep only rows with a real CO₂ value and a positive heat input.
2. Split the rows by facility (GroupShuffleSplit). A facility is either all in
   training or all in testing, so one plant cannot leak into both.
3. Choose the model with 5-fold GroupKFold cross-validation on the TRAINING rows only.
4. Refit the chosen model on all training rows and score it once on the test rows.

The EPA export in this project covers a single short window (June 2024 plus a 2025
annual pull), so a chronological split is not meaningful. This is an exploratory
evaluation, not a forecast.
"""

import json
import math
import os
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold, GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from models import ModelRun, db
from services.analytics_service import load_frame

BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_PATH = Path(os.environ.get("EPA_MODEL_PATH", BASE_DIR / "models_saved" / "co2_predictor.joblib"))
RANDOM_SEED = 42
TARGET = "co2_mass"
TARGET_UNITS = "short tons CO₂ per reporting record"
SPLIT_METHOD = ("GroupShuffleSplit by facility_id (test 25%, seed 42); "
                "model selection by 5-fold GroupKFold on training rows only. "
                "Exploratory evaluation, not temporal forecasting.")
MODEL_NAMES = ["Baseline (mean)", "Ridge Regression", "Random Forest"]

# Features we would like to use. gross_load and operating_time are not in the
# current EPA export, so they are reported as unavailable instead of being invented.
NUMERIC_CANDIDATES = ["heat_input"]
CATEGORICAL_CANDIDATES = ["primary_fuel", "state"]
UNAVAILABLE_FEATURES = {
    "gross_load": "Not present in the EPA export used for this project.",
    "operating_time": "Not present in the EPA export used for this project.",
}


def _json_safe(value):
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def eligible_rows(frame):
    """Rows usable for training: real CO₂ and heat input, positive heat input, known fuel."""
    part = frame.dropna(subset=[TARGET, "heat_input", "facility_id"])
    part = part[part["heat_input"] > 0]
    part = part[part["primary_fuel"].notna()]
    return part.reset_index(drop=True)


def choose_features(frame):
    """Use a predictor only when it is present and actually varies in the data.
    A constant column (for example state = KY for every row) adds nothing, so it is dropped."""
    numeric = [c for c in NUMERIC_CANDIDATES if frame[c].notna().any() and frame[c].nunique() > 1]
    categorical = [c for c in CATEGORICAL_CANDIDATES if frame[c].notna().any() and frame[c].nunique() > 1]
    dropped = [c for c in NUMERIC_CANDIDATES + CATEGORICAL_CANDIDATES
               if c not in numeric and c not in categorical]
    return numeric, categorical, dropped


def _preprocessor(numeric, categorical, scale):
    num_steps = [("impute", SimpleImputer(strategy="median"))]
    if scale:
        num_steps.append(("scale", StandardScaler()))
    transformers = []
    if numeric:
        transformers.append(("num", Pipeline(num_steps), numeric))
    if categorical:
        transformers.append(("cat", Pipeline([
            ("impute", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ]), categorical))
    return ColumnTransformer(transformers)


def build_models(numeric, categorical):
    """The three candidate pipelines. Preprocessing lives inside each pipeline, so it is
    only ever fitted on the rows passed to fit()."""
    return {
        "Baseline (mean)": Pipeline([
            ("prep", _preprocessor(numeric, categorical, scale=False)),
            ("model", DummyRegressor(strategy="mean")),
        ]),
        "Ridge Regression": Pipeline([
            ("prep", _preprocessor(numeric, categorical, scale=True)),
            ("model", Ridge(alpha=1.0)),
        ]),
        "Random Forest": Pipeline([
            ("prep", _preprocessor(numeric, categorical, scale=False)),
            ("model", RandomForestRegressor(n_estimators=200, max_depth=8, min_samples_leaf=3,
                                            random_state=RANDOM_SEED, n_jobs=1)),
        ]),
    }


def regression_metrics(y_true, y_pred):
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    n = len(y_true)
    r2 = None
    # R² is undefined with fewer than two rows or when the actual values never change
    if n >= 2 and np.var(y_true) > 0:
        r2 = float(r2_score(y_true, y_pred))
    return {
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(math.sqrt(mean_squared_error(y_true, y_pred))),
        "r2": r2,
        "n": int(n),
    }


def _cross_validate(name, pipeline, X, y, groups):
    n_groups = len(set(groups))
    n_splits = min(5, n_groups)
    if n_splits < 2:
        return None
    rmses, maes = [], []
    for train_idx, val_idx in GroupKFold(n_splits=n_splits).split(X, y, groups):
        model = _clone(pipeline)
        model.fit(X.iloc[train_idx], y.iloc[train_idx])
        pred = model.predict(X.iloc[val_idx])
        scores = regression_metrics(y.iloc[val_idx], pred)
        rmses.append(scores["rmse"])
        maes.append(scores["mae"])
    return {"cv_folds": n_splits, "cv_rmse_mean": float(np.mean(rmses)),
            "cv_rmse_std": float(np.std(rmses)), "cv_mae_mean": float(np.mean(maes))}


def _clone(pipeline):
    from sklearn.base import clone
    return clone(pipeline)


def train(frame=None, save=True):
    """Train, compare, and save the CO₂ predictor. Returns a result dict.

    Raises ValueError with a clear message if there is not enough data."""
    if frame is None:
        frame = load_frame({})
    rows = eligible_rows(frame)
    if len(rows) < 10:
        raise ValueError(f"Only {len(rows)} eligible rows (need at least 10). "
                         "Each row needs CO₂, a positive heat input, and a fuel type.")

    numeric, categorical, dropped = choose_features(rows)
    if not numeric and not categorical:
        raise ValueError("No usable predictors: heat_input and primary_fuel are constant or empty.")
    feature_names = numeric + categorical
    X = rows[feature_names]
    y = rows[TARGET].astype(float)
    groups = rows["facility_id"].astype(str)

    splitter = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=RANDOM_SEED)
    train_idx, test_idx = next(splitter.split(X, y, groups))
    if len(set(groups.iloc[test_idx])) < 1 or len(test_idx) < 2:
        raise ValueError("Test split is too small. Upload more facilities before training.")

    X_train, y_train, g_train = X.iloc[train_idx], y.iloc[train_idx], groups.iloc[train_idx]
    X_test, y_test = X.iloc[test_idx], y.iloc[test_idx]

    candidates = build_models(numeric, categorical)
    results = {}
    for name, pipeline in candidates.items():
        cv = _cross_validate(name, pipeline, X_train, y_train, g_train)
        fitted = _clone(pipeline).fit(X_train, y_train)
        test_pred = fitted.predict(X_test)
        results[name] = {
            "test": regression_metrics(y_test, test_pred),
            "validation": cv,
            "_fitted": fitted,
            "_test_pred": test_pred,
        }

    # Selection uses cross-validation RMSE only, never the test rows
    def selection_key(name):
        cv = results[name]["validation"]
        return cv["cv_rmse_mean"] if cv else float("inf")

    selected = min(MODEL_NAMES, key=selection_key)
    chosen = results[selected]
    test_pred = chosen["_test_pred"]
    trained_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    notes = []
    for feature, reason in UNAVAILABLE_FEATURES.items():
        notes.append(f"{feature}: {reason}")
    for feature in dropped:
        notes.append(f"{feature}: skipped because it is empty or constant in the training data.")
    if len(set(groups)) < 5:
        notes.append("Fewer than 5 facilities are eligible, so cross-validation uses fewer folds.")

    metrics_public = {name: {"test": r["test"], "validation": r["validation"]} for name, r in results.items()}
    predictions = [{"facility_id": str(g), "actual": float(a), "predicted": float(p)}
                   for g, a, p in zip(groups.iloc[test_idx], y_test, test_pred)]

    artifact = None
    if save:
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"pipeline": chosen["_fitted"], "features": feature_names,
                     "selected_model": selected, "target": TARGET, "trained_at": trained_at},
                    MODEL_PATH)
        artifact = str(MODEL_PATH)

    run = ModelRun(
        trained_at=trained_at, selected_model=selected, target=TARGET, target_units=TARGET_UNITS,
        split_method=SPLIT_METHOD, train_rows=int(len(train_idx)), test_rows=int(len(test_idx)),
        feature_names=json.dumps(feature_names), metrics_json=json.dumps(_json_safe(metrics_public)),
        predictions_json=json.dumps(_json_safe(predictions)), notes=" ".join(notes),
        artifact_path=artifact,
    )
    db.session.add(run)
    db.session.commit()

    return {
        "run_id": run.id, "selected_model": selected, "trained_at": trained_at,
        "train_rows": int(len(train_idx)), "test_rows": int(len(test_idx)),
        "train_facilities": int(g_train.nunique()), "test_facilities": int(groups.iloc[test_idx].nunique()),
        "features": feature_names, "split_method": SPLIT_METHOD, "target": TARGET,
        "target_units": TARGET_UNITS, "metrics": metrics_public, "artifact_path": artifact,
        "notes": notes,
    }


def load_artifact(path=None):
    """Load the saved pipeline. Raises FileNotFoundError if training has not been run."""
    path = Path(path) if path else MODEL_PATH
    if not path.exists():
        raise FileNotFoundError(f"No saved model at {path}. Run `python train_model.py` first.")
    return joblib.load(path)


def predict(records, artifact=None):
    """Predict CO₂ for a list of dicts with heat_input and primary_fuel (and state if used).

    Missing heat_input gives a null prediction, because heat input is the main driver and
    a made-up value would be misleading. Other missing predictors are filled with the
    training median or most common value, and a warning is returned for each row."""
    artifact = artifact or load_artifact()
    features = artifact["features"]
    rows = []
    warnings = []
    for i, record in enumerate(records):
        row = {f: record.get(f) for f in features}
        rows.append(row)
        for feature in features:
            if row[feature] is None or (isinstance(row[feature], float) and math.isnan(row[feature])):
                if feature == "heat_input":
                    warnings.append(f"row {i}: heat_input missing, no prediction made")
                else:
                    warnings.append(f"row {i}: {feature} missing, filled from training data")
    frame = pd.DataFrame(rows, columns=features)
    predictions = [None] * len(rows)
    usable = frame["heat_input"].notna() if "heat_input" in frame else pd.Series([True] * len(rows))
    if usable.any():
        values = artifact["pipeline"].predict(frame[usable.values])
        iterator = iter(values)
        predictions = [float(next(iterator)) if ok else None for ok in usable.values]
    return {"predictions": predictions, "units": TARGET_UNITS, "warnings": warnings,
            "model": artifact.get("selected_model")}


def latest_metrics():
    """The most recent saved training run as a dict, or None."""
    run = ModelRun.query.order_by(ModelRun.id.desc()).first()
    if run is None:
        return None
    return {
        "run_id": run.id, "trained_at": run.trained_at, "selected_model": run.selected_model,
        "target": run.target, "target_units": run.target_units, "split_method": run.split_method,
        "train_rows": run.train_rows, "test_rows": run.test_rows,
        "features": json.loads(run.feature_names),
        "metrics": json.loads(run.metrics_json),
        "predictions": json.loads(run.predictions_json) if run.predictions_json else [],
        "notes": run.notes or "", "artifact_path": run.artifact_path,
    }
