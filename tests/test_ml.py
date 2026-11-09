import math

import pytest

from services import ml_service
from tests.conftest import add_records


def _training_rows():
    rows = []
    # 12 facilities, 4 rows each. CO2 follows heat input closely, so the models have signal.
    for f in range(12):
        for k in range(4):
            heat = 100.0 * (f + 1) + 25.0 * k
            fuel = "Coal" if f % 2 == 0 else "Natural Gas"
            co2 = 0.4 * heat + (5.0 if fuel == "Coal" else -5.0)
            rows.append(dict(facility_id=str(f), facility_name=f"Plant {f}", state="KY",
                             primary_fuel=fuel, co2_mass=co2, so2_mass=0.01, nox_mass=0.01,
                             heat_input=heat, record_date="2024-06-01"))
    return rows


def test_train_compares_models_and_saves_artifact(app, clean_db, tmp_path, monkeypatch):
    monkeypatch.setattr(ml_service, "MODEL_PATH", tmp_path / "co2_predictor.joblib")
    add_records(_training_rows())
    with app.app_context():
        result = ml_service.train(save=True)
    assert result["selected_model"] in ml_service.MODEL_NAMES
    assert (tmp_path / "co2_predictor.joblib").exists()
    assert set(result["metrics"]) == set(ml_service.MODEL_NAMES)
    # facilities are held out whole, so the two sides add up to all 12 facilities
    assert result["train_facilities"] + result["test_facilities"] == 12
    assert result["features"] == ["heat_input", "primary_fuel"]
    for scores in result["metrics"].values():
        assert math.isfinite(scores["test"]["mae"])
        assert math.isfinite(scores["test"]["rmse"])


def test_ridge_beats_mean_baseline_on_linear_signal(app, clean_db, tmp_path, monkeypatch):
    monkeypatch.setattr(ml_service, "MODEL_PATH", tmp_path / "m.joblib")
    add_records(_training_rows())
    with app.app_context():
        result = ml_service.train(save=False)
    baseline = result["metrics"]["Baseline (mean)"]["test"]["rmse"]
    assert result["metrics"]["Ridge Regression"]["test"]["rmse"] < baseline


def test_saved_model_loads_and_predicts(app, clean_db, tmp_path, monkeypatch):
    path = tmp_path / "co2.joblib"
    monkeypatch.setattr(ml_service, "MODEL_PATH", path)
    add_records(_training_rows())
    with app.app_context():
        ml_service.train(save=True)
        out = ml_service.predict([{"heat_input": 1000.0, "primary_fuel": "Coal"}],
                                 artifact=ml_service.load_artifact(path))
    assert len(out["predictions"]) == 1
    assert out["predictions"][0] == pytest.approx(0.4 * 1000.0 + 5.0, rel=0.3)
    assert out["warnings"] == []


def test_missing_heat_input_gives_null_prediction(app, clean_db, tmp_path, monkeypatch):
    path = tmp_path / "co2.joblib"
    monkeypatch.setattr(ml_service, "MODEL_PATH", path)
    add_records(_training_rows())
    with app.app_context():
        ml_service.train(save=True)
        out = ml_service.predict([{"heat_input": None, "primary_fuel": "Coal"}],
                                 artifact=ml_service.load_artifact(path))
    assert out["predictions"] == [None]
    assert any("heat_input missing" in w for w in out["warnings"])


def test_missing_fuel_is_filled_with_warning(app, clean_db, tmp_path, monkeypatch):
    path = tmp_path / "co2.joblib"
    monkeypatch.setattr(ml_service, "MODEL_PATH", path)
    add_records(_training_rows())
    with app.app_context():
        ml_service.train(save=True)
        out = ml_service.predict([{"heat_input": 500.0, "primary_fuel": None}],
                                 artifact=ml_service.load_artifact(path))
    assert out["predictions"][0] is not None
    assert any("primary_fuel missing" in w for w in out["warnings"])


def test_too_few_rows_is_reported_not_invented(app, clean_db, tmp_path, monkeypatch):
    monkeypatch.setattr(ml_service, "MODEL_PATH", tmp_path / "x.joblib")
    add_records(_training_rows()[:3])
    with app.app_context():
        with pytest.raises(ValueError, match="need at least 10"):
            ml_service.train(save=False)


def test_missing_artifact_raises_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="train_model.py"):
        ml_service.load_artifact(tmp_path / "nothing_here.joblib")


def test_ml_metrics_endpoint_reports_latest_run(app, client, clean_db, tmp_path, monkeypatch):
    monkeypatch.setattr(ml_service, "MODEL_PATH", tmp_path / "m.joblib")
    add_records(_training_rows())
    with app.app_context():
        ml_service.train(save=True)
    body = client.get("/api/ml/metrics").get_json()
    assert body["available"] is True
    assert body["split_method"].startswith("GroupShuffleSplit")
    assert body["features"] == ["heat_input", "primary_fuel"]
    assert len(body["predictions"]) == body["test_rows"]
