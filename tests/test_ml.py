import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from services import ml_service
from tests.conftest import add_records


def _daily_rows(state="KY", facilities=4, days=100, seed=3):
    """Made-up daily unit data where today's heat input drifts back toward a plant level.
    CO₂ is 0.1 x heat input, like the real data. Yesterday's value is a useful but imperfect guide."""
    rng = np.random.default_rng(seed)
    start = date(2024, 1, 1)
    rows = []
    for f in range(facilities):
        level = 200.0 * (f + 1)
        heat = level
        for d in range(days):
            heat = max(level + 0.7 * (heat - level) + rng.normal(0, 0.1 * level), 1.0)
            rows.append(dict(
                facility_id=str(f), facility_name=f"Plant {f}", state=state, unit_id="1",
                primary_fuel="Coal" if f % 2 == 0 else "Natural Gas",
                co2_mass=0.1 * heat, so2_mass=None, nox_mass=None, heat_input=heat,
                record_date=(start + timedelta(days=d)).isoformat()))
    return rows


@pytest.fixture()
def trained(app, clean_db, tmp_path, monkeypatch):
    monkeypatch.setattr(ml_service, "MODEL_PATH", tmp_path / "co2_predictor.joblib")
    add_records(_daily_rows())
    with app.app_context():
        result = ml_service.train("KY", save=True)
    return result


# ---------- history features ----------

def test_lags_match_calendar_days_and_gaps_stay_missing():
    raw = pd.DataFrame({
        "facility_id": ["1"] * 4, "unit_id": ["a"] * 4, "primary_fuel": ["Coal"] * 4,
        "record_date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-10"],
        "co2_mass": [10.0, 20.0, 30.0, 40.0], "heat_input": [100.0, 200.0, 300.0, 400.0],
    })
    rows = ml_service.prepare_rows(raw)
    assert rows.loc[1, "co2_lag1"] == 10.0 and rows.loc[2, "co2_lag1"] == 20.0
    assert math.isnan(rows.loc[0, "co2_lag1"])
    assert math.isnan(rows.loc[3, "co2_lag1"])      # Jan 9 is missing, so no lag, not a shifted value
    assert rows.loc[3, "co2_lag7"] == 30.0           # Jan 3 is exactly 7 days before Jan 10
    assert rows.loc[2, "heat_lag1"] == 200.0
    # the 7-day average only uses earlier days, never the row's own day
    assert math.isnan(rows.loc[0, "co2_roll7"])
    assert rows.loc[1, "co2_roll7"] == 10.0
    assert rows.loc[2, "co2_roll7"] == pytest.approx(15.0)


def test_each_unit_gets_its_own_history():
    raw = pd.DataFrame({
        "facility_id": ["1", "1", "2", "2"], "unit_id": ["a", "a", "a", "a"], "primary_fuel": ["Coal"] * 4,
        "record_date": ["2024-01-01", "2024-01-02"] * 2,
        "co2_mass": [10.0, 20.0, 1000.0, 2000.0], "heat_input": [1.0, 2.0, 100.0, 200.0],
    })
    rows = ml_service.prepare_rows(raw).set_index(["facility_id", "record_date"])
    assert rows.loc[("1", "2024-01-02"), "co2_lag1"] == 10.0
    assert rows.loc[("2", "2024-01-02"), "co2_lag1"] == 1000.0


def test_idle_days_and_rows_without_history_are_not_used():
    raw = pd.DataFrame({
        "facility_id": ["1"] * 5, "unit_id": ["a"] * 5, "primary_fuel": ["Coal"] * 5,
        "record_date": [f"2024-01-0{d}" for d in range(1, 6)],
        "co2_mass": [10.0, 20.0, None, 40.0, 50.0], "heat_input": [100.0, 200.0, None, 400.0, 500.0],
    })
    usable = ml_service.eligible_rows(ml_service.prepare_rows(raw))
    # Jan 1 has no yesterday, Jan 3 was idle (not zero), Jan 4 follows an idle day
    assert list(usable["record_date"]) == ["2024-01-02", "2024-01-05"]


def test_split_puts_every_test_day_after_every_training_day(app):
    rows = ml_service.eligible_rows(ml_service.prepare_rows(pd.DataFrame(_daily_rows())))
    train_rows, test_rows, cutoff = ml_service.split_by_date(rows)
    assert train_rows["date"].max() < test_rows["date"].min()
    assert test_rows["date"].min() == cutoff
    assert len(test_rows) == pytest.approx(0.2 * len(rows), rel=0.1)


def test_yesterday_baseline_returns_yesterday():
    frame = pd.DataFrame({"co2_lag1": [5.0, 7.0]})
    assert list(ml_service.YesterdayBaseline().fit(frame).predict(frame)) == [5.0, 7.0]


# ---------- training ----------

def test_train_compares_linear_and_tree_models_without_state(trained, tmp_path):
    assert set(trained["metrics"]) == set(ml_service.MODEL_NAMES) | {ml_service.RIDGE_SAME_DAY}
    assert "state" not in trained["features"]
    assert "heat_input" not in trained["features"]          # same-day heat input is not a forecast input
    assert {"co2_lag1", "co2_lag7", "co2_roll7"} <= set(trained["features"])
    assert (tmp_path / "co2_predictor_KY.joblib").exists()   # one file per state
    for scores in trained["metrics"].values():
        assert math.isfinite(scores["test"]["mae"]) and math.isfinite(scores["test"]["rmse"])
    assert trained["train_dates"][1] < trained["test_dates"][0]


def test_history_models_beat_copying_yesterday(trained):
    baseline = trained["metrics"][ml_service.PERSISTENCE]["test"]["rmse"]
    assert trained["metrics"][ml_service.RIDGE]["test"]["rmse"] < baseline


def test_same_day_heat_reference_is_nearly_exact(trained):
    # CO₂ is computed from heat input, so the reference scores far better than any forecast
    reference = trained["metrics"][ml_service.RIDGE_SAME_DAY]["test"]["rmse"]
    assert reference < trained["metrics"][ml_service.RIDGE]["test"]["rmse"]


def test_model_choice_comes_from_validation_not_test(trained):
    best = min(ml_service.MODEL_NAMES, key=lambda n: trained["metrics"][n]["validation"]["cv_rmse_mean"])
    assert trained["selected_model"] == best
    assert trained["sensitivity_model"] in ml_service.LEARNED_MODELS


def test_each_state_trains_on_its_own_rows(app, clean_db, tmp_path, monkeypatch):
    monkeypatch.setattr(ml_service, "MODEL_PATH", tmp_path / "m.joblib")
    add_records(_daily_rows("KY") + _daily_rows("OH", seed=9))
    with app.app_context():
        ky = ml_service.train("KY", save=True)
        oh = ml_service.train("OH", save=True)
    assert ky["train_rows"] + ky["test_rows"] == oh["train_rows"] + oh["test_rows"]
    assert (tmp_path / "m_KY.joblib").exists() and (tmp_path / "m_OH.joblib").exists()
    with app.app_context():
        assert ml_service.trained_states() == ["KY", "OH"]


def test_hourly_and_annual_rows_are_not_used_for_training(app, clean_db, tmp_path, monkeypatch):
    monkeypatch.setattr(ml_service, "MODEL_PATH", tmp_path / "m.joblib")
    add_records(_daily_rows(facilities=1, days=40))
    add_records([dict(facility_id="9", facility_name="Hourly", state="KY", unit_id="1", primary_fuel="Coal",
                      co2_mass=5.0, heat_input=50.0, record_date="2024-02-01", record_hour=3),
                 dict(facility_id="9", facility_name="Annual", state="KY", unit_id="1", primary_fuel="Coal",
                      co2_mass=5.0, heat_input=50.0, record_date="2025")])
    with app.app_context():
        raw = ml_service.load_daily_rows("KY")
    assert set(raw["facility_id"]) == {"0"}


def test_too_few_rows_is_reported_not_invented(app, clean_db, tmp_path, monkeypatch):
    monkeypatch.setattr(ml_service, "MODEL_PATH", tmp_path / "x.joblib")
    add_records(_daily_rows(facilities=1, days=12))
    with app.app_context():
        with pytest.raises(ValueError, match="need at least"):
            ml_service.train("KY", save=False)


def test_state_is_required(app):
    with app.app_context():
        with pytest.raises(ValueError, match="Pick a state"):
            ml_service.train("", save=False)


# ---------- using a saved model ----------

RECORD = {"co2_lag1": 60.0, "co2_lag7": 58.0, "co2_roll7": 59.0, "heat_lag1": 600.0, "heat_roll7": 590.0,
          "primary_fuel": "Coal", "date": "2024-04-10"}


def test_saved_model_predicts_close_to_the_pattern(app, trained):
    with app.app_context():
        out = ml_service.predict([RECORD], state="KY", model_name=ml_service.RIDGE)
    assert out["warnings"] == []
    assert out["predictions"][0] == pytest.approx(60.0, rel=0.25)


def test_missing_yesterday_gives_no_prediction(app, trained):
    with app.app_context():
        out = ml_service.predict([dict(RECORD, co2_lag1=None)], state="KY")
    assert out["predictions"] == [None]
    assert any("co2_lag1 missing" in w for w in out["warnings"])


def test_missing_optional_input_is_filled_with_a_warning(app, trained):
    with app.app_context():
        out = ml_service.predict([dict(RECORD, co2_lag7=None)], state="KY")
    assert out["predictions"][0] is not None
    assert any("co2_lag7 missing" in w for w in out["warnings"])


def test_missing_artifact_raises_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="train_model.py"):
        ml_service.load_artifact(tmp_path / "nothing_here.joblib")
    with pytest.raises(FileNotFoundError, match="Pick a state"):
        ml_service.load_artifact()


def test_metrics_endpoint_reports_the_state_run(client, trained):
    body = client.get("/api/ml/metrics?state=KY").get_json()
    assert body["available"] is True and body["state"] == "KY"
    assert "state" not in body["features"]
    assert body["split_method"].startswith("Time split")
    assert body["states_trained"] == ["KY"]
    assert body["daily"] and body["predictions"]
    assert len(body["predictions"]) <= ml_service.MAX_PREDICTIONS_SHOWN


def test_metrics_endpoint_for_untrained_state(client, trained):
    body = client.get("/api/ml/metrics?state=TX").get_json()
    assert body["available"] is False
    assert "--state TX" in body["reason"]
    assert body["states_trained"] == ["KY"]


def test_predict_endpoint(client, trained):
    ok = client.post("/api/ml/predict", json={"state": "KY", "records": [RECORD]})
    assert ok.status_code == 200 and ok.get_json()["predictions"][0] is not None
    assert client.post("/api/ml/predict", json={"records": [RECORD]}).status_code == 400
    assert client.post("/api/ml/predict", json={"state": "TX", "records": [RECORD]}).status_code == 409
