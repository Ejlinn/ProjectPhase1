"""CO₂ prediction models for the dashboard.

What the model does
-------------------
It forecasts one unit's CO₂ for one day using only what was known before that day: the unit's
CO₂ and heat input yesterday, the same day last week, and the average of the previous 7 days,
plus the day of the week, the month and the fuel. Using past values of the target as inputs is
called an autoregressive model, and it is there because yesterday's CO₂ clearly affects today's.

The same day's heat input is deliberately NOT an input. CAMPD calculates CO₂ from heat input, so a
model that is given it just undoes that calculation and scores almost perfectly without
forecasting anything. That version is reported as a reference row so the difference is visible.

State is NOT an input. Instead one model is trained per state (python train_model.py --state KY),
and the same code runs for every state.

How it is checked
-----------------
* Data: the daily per-unit CAMPD rows. Older hourly or annual uploads are a different
  granularity, so they are left out of the model.
* Split: by date. Training uses the earlier 80% of days and testing uses the latest 20%,
  so the model is always scored on days that come after everything it learned from.
* Model choice: 3 expanding-window folds inside the training days only. The test days
  are scored once at the end.
* Candidates: yesterday's value as a baseline (no learning), Ridge regression (linear),
  Random Forest (tree, non-linear) and gradient boosting (boosted trees, non-linear).
  A Ridge model that is also given the same day's heat input is reported as a reference.
"""

import json
import math
import os
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, RegressorMixin, clone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sqlalchemy import func

from models import FacilityRecord, ModelRun, db

BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_PATH = Path(os.environ.get("EPA_MODEL_PATH", BASE_DIR / "models_saved" / "co2_predictor.joblib"))
RANDOM_SEED = 42
DEFAULT_STATE = "KY"
TARGET = "co2_mass"
TARGET_UNITS = "short tons CO₂ per unit per day"
TEST_FRACTION = 0.2
CV_FOLDS = 3
MIN_ROWS = 50
MAX_PREDICTIONS_STORED = 3000
MAX_PREDICTIONS_SHOWN = 2000

PERSISTENCE = "Yesterday's CO₂ (baseline)"
RIDGE = "Ridge (linear)"
FOREST = "Random Forest (tree)"
BOOSTING = "Gradient Boosting (tree)"
RIDGE_SAME_DAY = "Ridge + same-day heat input (reference)"
MODEL_NAMES = [PERSISTENCE, RIDGE, FOREST, BOOSTING]
LEARNED_MODELS = [RIDGE, FOREST, BOOSTING]  # these use the inputs, so they can answer what-if questions

HISTORY_FEATURES = ["co2_lag1", "co2_lag7", "co2_roll7", "heat_lag1", "heat_roll7"]
NUMERIC_FEATURES = HISTORY_FEATURES + ["day_of_week", "month"]
CATEGORICAL_FEATURES = ["primary_fuel"]
ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
SAME_DAY_NUMERIC = NUMERIC_FEATURES + ["heat_input"]  # used only by the reference model

SPLIT_METHOD = ("Time split: the earliest 80% of days train the models and the latest 20% test them. "
                "Model choice uses 3 expanding-window folds inside the training days only.")


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


# ---------- data ----------

def load_daily_rows(state, since=None):
    """Daily per-unit rows for one state. Hourly uploads (they carry an hour) and annual totals
    (a four-digit date) are a different granularity, so they are not used here."""
    f = FacilityRecord
    query = (db.session.query(f.facility_id, f.unit_id, f.record_date, f.primary_fuel, f.co2_mass, f.heat_input)
             .filter(f.state == state, f.record_hour.is_(None), func.length(f.record_date) == 10))
    if since:
        query = query.filter(f.record_date >= since)
    return pd.read_sql(query.statement, db.engine)


def prepare_rows(raw):
    """Add the history features. Everything is built from days BEFORE the row's own date,
    so no row can see its own answer.

    Lags are matched by calendar date, so a missing day gives a missing lag, not a shifted one."""
    columns = ["facility_id", "unit_id", "record_date", "primary_fuel", "co2_mass", "heat_input"]
    df = raw[columns].copy()
    df["date"] = pd.to_datetime(df["record_date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df["unit_key"] = df["facility_id"].astype(str) + "-" + df["unit_id"].astype(str)
    for column in ("co2_mass", "heat_input"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = (df.drop_duplicates(["unit_key", "date"], keep="last")
            .sort_values(["unit_key", "date"]).reset_index(drop=True))

    # (source column, lag in days, new column)
    for source, days, name in (("co2_mass", 1, "co2_lag1"), ("co2_mass", 7, "co2_lag7"), ("heat_input", 1, "heat_lag1")):
        shifted = (df[["unit_key", "date", source]].assign(date=df["date"] + pd.Timedelta(days=days))
                   .rename(columns={source: name}))
        df = df.merge(shifted, on=["unit_key", "date"], how="left")

    # mean of the previous 7 calendar days (closed="left" leaves out the row's own day)
    for source, name in (("co2_mass", "co2_roll7"), ("heat_input", "heat_roll7")):
        rolled = (df.groupby("unit_key").rolling("7D", on="date", closed="left", min_periods=1)[source]
                  .mean().rename(name).reset_index())
        df = df.merge(rolled, on=["unit_key", "date"], how="left")

    df["day_of_week"] = df["date"].dt.day_of_week
    df["month"] = df["date"].dt.month
    return _missing_as_nan(df)


def _missing_as_nan(frame):
    """scikit-learn's imputers only treat NaN as missing in text columns, not Python None."""
    frame = frame.copy()
    for column in CATEGORICAL_FEATURES:
        if column in frame:
            frame[column] = frame[column].astype(object).where(frame[column].notna(), np.nan)
    return frame


def eligible_rows(rows):
    """Rows a model can learn from: a real CO₂ value and positive heat input for the day, and CO₂ and
    heat input for the day before. Every model is scored on these same rows so the comparison is fair."""
    part = rows.dropna(subset=[TARGET, "heat_input", "co2_lag1", "heat_lag1"])
    part = part[(part["heat_input"] > 0) & (part[TARGET] >= 0) & (part["heat_lag1"] > 0)]
    return part.reset_index(drop=True)


def build_dataset(state):
    return prepare_rows(load_daily_rows(state))


# ---------- models ----------

class YesterdayBaseline(BaseEstimator, RegressorMixin):
    """No learning: predict today's CO₂ as yesterday's CO₂. Any real model should beat this."""

    def fit(self, X, y=None):
        return self

    def predict(self, X):
        return np.asarray(X["co2_lag1"], dtype=float)


def _preprocessor(numeric, categorical, scale):
    steps = [("impute", SimpleImputer(strategy="median"))]
    if scale:
        steps.append(("scale", StandardScaler()))
    transformers = [("num", Pipeline(steps), numeric)]
    if categorical:
        transformers.append(("cat", Pipeline([
            ("impute", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]), categorical))
    return ColumnTransformer(transformers)


def build_models(categorical):
    """The candidate pipelines. Preprocessing is inside each pipeline, so it is only ever
    fitted on the rows passed to fit()."""
    return {
        PERSISTENCE: YesterdayBaseline(),
        RIDGE: Pipeline([
            ("prep", _preprocessor(NUMERIC_FEATURES, categorical, scale=True)),
            ("model", Ridge(alpha=1.0)),
        ]),
        FOREST: Pipeline([
            ("prep", _preprocessor(NUMERIC_FEATURES, categorical, scale=False)),
            ("model", RandomForestRegressor(n_estimators=120, max_depth=14, min_samples_leaf=5,
                                            max_samples=0.3, random_state=RANDOM_SEED, n_jobs=-1)),
        ]),
        BOOSTING: Pipeline([
            ("prep", _preprocessor(NUMERIC_FEATURES, categorical, scale=False)),
            ("model", HistGradientBoostingRegressor(max_iter=250, learning_rate=0.08,
                                                    random_state=RANDOM_SEED)),
        ]),
    }


def build_reference_model(categorical):
    """Ridge that is also given the same day's heat input. Not a forecast: CO₂ is calculated from
    heat input, so this scores almost perfectly. It is shown only to explain why that input is left out."""
    return Pipeline([
        ("prep", _preprocessor(SAME_DAY_NUMERIC, categorical, scale=True)),
        ("model", Ridge(alpha=1.0)),
    ])


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


def split_by_date(rows, test_fraction=TEST_FRACTION):
    """Earlier days train, the latest days test. Returns (train, test, cutoff date)."""
    dates = np.sort(rows["date"].unique())
    if len(dates) < 10:
        raise ValueError(f"Only {len(dates)} different days of data (need at least 10 to split by date).")
    cutoff = dates[int(len(dates) * (1 - test_fraction))]
    train = rows[rows["date"] < cutoff]
    test = rows[rows["date"] >= cutoff]
    if len(train) < MIN_ROWS // 2 or len(test) < 2:
        raise ValueError("The date split left too few rows on one side. Load more days before training.")
    return train, test, pd.Timestamp(cutoff)


def _cross_validate(pipeline, train, features):
    """Expanding-window validation: each fold trains on earlier days and checks the next block of days."""
    dates = np.sort(train["date"].unique())
    edges = [dates[min(int(len(dates) * p), len(dates) - 1)] for p in np.linspace(0.5, 1.0, CV_FOLDS + 1)[:-1]]
    edges.append(dates[-1] + np.timedelta64(1, "D"))
    rmses, maes = [], []
    for start, end in zip(edges[:-1], edges[1:]):
        fit_part = train[train["date"] < start]
        check_part = train[(train["date"] >= start) & (train["date"] < end)]
        if len(fit_part) < 5 or len(check_part) < 2:
            continue
        model = clone(pipeline).fit(fit_part[features], fit_part[TARGET])
        scores = regression_metrics(check_part[TARGET], model.predict(check_part[features]))
        rmses.append(scores["rmse"])
        maes.append(scores["mae"])
    if not rmses:
        return None
    return {"cv_folds": len(rmses), "cv_rmse_mean": float(np.mean(rmses)),
            "cv_rmse_std": float(np.std(rmses)), "cv_mae_mean": float(np.mean(maes))}


def artifact_path(state):
    """Where one state's model is saved, next to MODEL_PATH (for example co2_predictor_KY.joblib)."""
    return MODEL_PATH.with_name(f"{MODEL_PATH.stem}_{state}{MODEL_PATH.suffix}")


def train(state, rows=None, save=True):
    """Train and compare the models for one state, save the best ones, and log the run.

    `rows` is optional: pass the output of prepare_rows() to skip the database read.
    Raises ValueError with a plain message when there is not enough data."""
    state = (state or "").strip().upper()
    if not state:
        raise ValueError("Pick a state to train for, for example --state KY.")
    prepared = prepare_rows(load_daily_rows(state)) if rows is None else rows
    usable = eligible_rows(prepared)
    if len(usable) < MIN_ROWS:
        raise ValueError(f"{state}: only {len(usable)} usable unit-days (need at least {MIN_ROWS}). "
                         "Each row needs CO₂ and heat input for the day and for the day before.")

    categorical = CATEGORICAL_FEATURES if usable["primary_fuel"].notna().any() else []
    features = NUMERIC_FEATURES + categorical
    train_rows, test_rows, cutoff = split_by_date(usable)

    candidates = build_models(categorical)
    results = {}
    for name, pipeline in candidates.items():
        cv = _cross_validate(pipeline, train_rows, features)
        fitted = clone(pipeline).fit(train_rows[features], train_rows[TARGET])
        test_pred = fitted.predict(test_rows[features])
        results[name] = {"test": regression_metrics(test_rows[TARGET], test_pred), "validation": cv,
                         "_fitted": fitted, "_test_pred": test_pred}

    # reference only: the same linear model plus the same day's heat input (not a real forecast)
    reference_features = SAME_DAY_NUMERIC + categorical
    reference = build_reference_model(categorical).fit(train_rows[reference_features], train_rows[TARGET])
    reference_scores = regression_metrics(test_rows[TARGET], reference.predict(test_rows[reference_features]))

    def cv_score(name):
        cv = results[name]["validation"]
        return cv["cv_rmse_mean"] if cv else float("inf")

    # choice uses cross-validation only, never the test days
    selected = min(MODEL_NAMES, key=cv_score)
    # the baseline only copies yesterday's value, so it cannot answer what-if questions about the other inputs
    sensitivity_model = min(LEARNED_MODELS, key=cv_score)
    chosen_pred = results[selected]["_test_pred"]
    trained_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    metrics_public = {name: {"test": r["test"], "validation": r["validation"]} for name, r in results.items()}
    metrics_public[RIDGE_SAME_DAY] = {"test": reference_scores, "validation": None}

    test_view = test_rows.assign(predicted=chosen_pred)
    step = max(1, len(test_view) // MAX_PREDICTIONS_STORED)
    sample = test_view.iloc[::step]
    predictions = [{"facility_id": str(r.facility_id), "unit_id": str(r.unit_id), "date": r.record_date,
                    "actual": float(r.co2_mass), "predicted": float(r.predicted)}
                   for r in sample.itertuples()]
    daily = (test_view.groupby("record_date")
             .agg(actual=(TARGET, "sum"), predicted=("predicted", "sum"), units=(TARGET, "count"))
             .reset_index().sort_values("record_date"))
    daily_series = [{"date": r.record_date, "actual": float(r.actual), "predicted": float(r.predicted),
                     "units": int(r.units)} for r in daily.itertuples()]

    notes = [
        f"State is not a model input. This model was trained only on {state} units; run the same code for another state.",
        f"{len(usable)} of {len(prepared)} daily rows were usable. Days with no CO₂ reported (the unit was not running) "
        "are left out, not counted as zero, and a row also needs CO₂ and heat input from the day before.",
        "The same day's heat input is not an input, because CAMPD calculates CO₂ from it. See the reference row.",
        "gross_load is stored for the CAMPD rows but is not used as a model input yet.",
    ]
    if results[selected]["validation"] is None:
        notes.append("There were too few training days for cross-validation, so the model choice is not reliable.")

    extra = {
        "state": state, "cutoff_date": str(cutoff.date()),
        "train_dates": [str(train_rows["date"].min().date()), str(train_rows["date"].max().date())],
        "test_dates": [str(test_rows["date"].min().date()), str(test_rows["date"].max().date())],
        "sensitivity_model": sensitivity_model, "daily": daily_series,
        "usable_rows": int(len(usable)), "all_rows": int(len(prepared)),
        "train_facilities": int(train_rows["facility_id"].nunique()),
        "test_facilities": int(test_rows["facility_id"].nunique()),
    }

    artifact_file = None
    if save:
        path = artifact_path(state)
        path.parent.mkdir(parents=True, exist_ok=True)
        keep = set(MODEL_NAMES)  # all four, so the what-if tool can compare the linear and tree models
        joblib.dump({
            "state": state, "features": features, "target": TARGET, "trained_at": trained_at,
            "selected_model": selected, "sensitivity_model": sensitivity_model,
            "models": {name: results[name]["_fitted"] for name in keep},
            # what the model saw while training, so the what-if tool can warn about values outside it
            "feature_ranges": {c: [float(train_rows[c].min()), float(train_rows[c].max())] for c in NUMERIC_FEATURES},
            "cutoff_date": extra["cutoff_date"],
        }, path, compress=3)
        artifact_file = str(path)

    run = ModelRun(
        trained_at=trained_at, selected_model=selected, target=TARGET, target_units=TARGET_UNITS,
        split_method=SPLIT_METHOD, train_rows=int(len(train_rows)), test_rows=int(len(test_rows)),
        feature_names=json.dumps(features), metrics_json=json.dumps(_json_safe(metrics_public)),
        predictions_json=json.dumps(_json_safe(predictions)), notes=" ".join(notes),
        artifact_path=artifact_file, state=state, extra_json=json.dumps(_json_safe(extra)),
    )
    db.session.add(run)
    db.session.commit()

    return {
        "run_id": run.id, "state": state, "selected_model": selected, "sensitivity_model": sensitivity_model,
        "trained_at": trained_at, "train_rows": int(len(train_rows)), "test_rows": int(len(test_rows)),
        "train_facilities": extra["train_facilities"], "test_facilities": extra["test_facilities"],
        "train_dates": extra["train_dates"], "test_dates": extra["test_dates"],
        "features": features, "split_method": SPLIT_METHOD, "target": TARGET, "target_units": TARGET_UNITS,
        "metrics": metrics_public, "artifact_path": artifact_file, "notes": notes,
    }


# ---------- using a saved model ----------

def load_artifact(path=None, state=None):
    """Load a saved model file. Raises FileNotFoundError if training has not been run for that state."""
    if path is None:
        if not state:
            raise FileNotFoundError("Pick a state first. Models are trained per state with `python train_model.py --state KY`.")
        path = artifact_path(state.strip().upper())
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No saved model at {path}. Run `python train_model.py` first.")
    return joblib.load(path)


def _is_missing(value):
    return value is None or (isinstance(value, float) and math.isnan(value))


def _features_from_record(record):
    """One input record to the model's feature dict. A `date` fills in day_of_week and month."""
    row = {name: record.get(name) for name in ALL_FEATURES}
    when = record.get("date")
    if when and (_is_missing(row["day_of_week"]) or _is_missing(row["month"])):
        stamp = pd.to_datetime(when, errors="coerce")
        if pd.notna(stamp):
            row["day_of_week"] = row["day_of_week"] if not _is_missing(row["day_of_week"]) else int(stamp.day_of_week)
            row["month"] = row["month"] if not _is_missing(row["month"]) else int(stamp.month)
    return row


def predict(records, state=None, artifact=None, model_name=None):
    """Forecast CO₂ for a list of dicts with co2_lag1, co2_lag7, co2_roll7, heat_lag1, heat_roll7,
    primary_fuel, and either day_of_week and month or a date.

    A missing yesterday's CO₂ (or yesterday's heat input, for the learned models) gives a null
    prediction, because those drive the result and a made-up value would be misleading. Other
    missing inputs are filled from the training data and a warning is returned for each."""
    artifact = artifact or load_artifact(state=state)
    name = model_name or artifact["selected_model"]
    if name not in artifact["models"]:
        raise ValueError(f"Model '{name}' is not in the saved file. Available: {', '.join(artifact['models'])}")
    pipeline = artifact["models"][name]
    features = artifact["features"]

    rows, warnings, usable = [], [], []
    for i, record in enumerate(records):
        row = _features_from_record(record)
        rows.append(row)
        ok = True
        required = ["co2_lag1"] if name == PERSISTENCE else ["co2_lag1", "heat_lag1"]
        for needed in required:
            if _is_missing(row[needed]):
                warnings.append(f"row {i}: {needed} missing, no prediction made")
                ok = False
        if ok:
            for feature in features:
                if _is_missing(row[feature]) and feature not in required:
                    warnings.append(f"row {i}: {feature} missing, filled from training data")
        usable.append(ok)

    frame = _missing_as_nan(pd.DataFrame(rows, columns=ALL_FEATURES))[features]
    predictions = [None] * len(rows)
    mask = np.array(usable, dtype=bool)
    if mask.any():
        values = iter(pipeline.predict(frame[mask]))
        predictions = [float(next(values)) if ok else None for ok in usable]
    return {"predictions": predictions, "units": TARGET_UNITS, "warnings": warnings,
            "model": name, "state": artifact.get("state")}


def trained_states():
    """States that have at least one finished training run."""
    rows = db.session.query(ModelRun.state).filter(ModelRun.state.isnot(None)).distinct().all()
    return sorted(s for (s,) in rows if s)


def latest_metrics(state=None):
    """The most recent training run (for one state, or the newest overall) as a dict, or None."""
    query = ModelRun.query.filter(ModelRun.state.isnot(None))
    if state:
        query = query.filter(ModelRun.state == state.strip().upper())
    elif query.filter(ModelRun.state == DEFAULT_STATE).first() is not None:
        query = query.filter(ModelRun.state == DEFAULT_STATE)  # open on Kentucky when no state is asked for
    run = query.order_by(ModelRun.id.desc()).first()
    if run is None:
        return None
    all_predictions = json.loads(run.predictions_json) if run.predictions_json else []
    # the charts only need a sample, so the response stays small
    step = max(1, len(all_predictions) // MAX_PREDICTIONS_SHOWN)
    extra = json.loads(run.extra_json) if run.extra_json else {}
    return {
        "run_id": run.id, "state": run.state, "trained_at": run.trained_at,
        "selected_model": run.selected_model, "sensitivity_model": extra.get("sensitivity_model"),
        "target": run.target, "target_units": run.target_units, "split_method": run.split_method,
        "train_rows": run.train_rows, "test_rows": run.test_rows,
        "features": json.loads(run.feature_names), "metrics": json.loads(run.metrics_json),
        "predictions": all_predictions[::step], "predictions_total": len(all_predictions),
        "daily": extra.get("daily", []), "train_dates": extra.get("train_dates"),
        "test_dates": extra.get("test_dates"), "train_facilities": extra.get("train_facilities"),
        "test_facilities": extra.get("test_facilities"),
        "notes": run.notes or "", "artifact_path": run.artifact_path,
        "states_trained": trained_states(),
    }
