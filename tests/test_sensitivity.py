import pytest

from services import ml_service, sensitivity_service
from tests.conftest import add_records
from tests.test_ml import _daily_rows


@pytest.fixture()
def ready(app, clean_db, tmp_path, monkeypatch):
    """A trained KY model and its data, with the baseline cache emptied."""
    monkeypatch.setattr(ml_service, "MODEL_PATH", tmp_path / "co2_predictor.joblib")
    sensitivity_service._baseline_cache.clear()
    add_records(_daily_rows())
    with app.app_context():
        ml_service.train("KY", save=True)
    yield
    sensitivity_service._baseline_cache.clear()


def run(app, **kwargs):
    with app.app_context():
        return sensitivity_service.sensitivity("KY", **kwargs)


def test_no_change_gives_no_difference(app, ready):
    result = run(app, change_pct=0)
    assert result["scenario"]["prediction"] == pytest.approx(result["baseline"]["prediction"])
    assert result["scenario"]["change"] == pytest.approx(0.0)


def test_raising_yesterdays_level_raises_a_linear_forecast(app, ready):
    result = run(app, input_key="level", change_pct=20, model_name=ml_service.RIDGE)
    assert result["scenario"]["prediction"] > result["baseline"]["prediction"]
    assert result["scenario"]["change_pct"] > 0
    assert result["sensitivity"]["per_one_percent"] > 0


def test_linear_curve_is_a_straight_line(app, ready):
    curve = run(app, model_name=ml_service.RIDGE)["curve"]
    steps = [b - a for a, b in zip(curve["prediction"], curve["prediction"][1:])]
    assert max(steps) - min(steps) == pytest.approx(0.0, abs=1e-6 * abs(curve["prediction"][0]) + 1e-6)
    assert curve["change_pct"][0] == -50 and curve["change_pct"][-1] == 50


def test_change_is_percent_of_baseline(app, ready):
    result = run(app, change_pct=10, model_name=ml_service.RIDGE)
    base, new = result["baseline"]["prediction"], result["scenario"]["prediction"]
    assert result["scenario"]["change_pct"] == pytest.approx((new - base) / base * 100)


def test_comparison_lists_every_input_largest_first(app, ready):
    rows = run(app, model_name=ml_service.RIDGE)["tornado"]["rows"]
    assert {r["key"] for r in rows} == set(sensitivity_service.INPUTS)
    sizes = [r["size"] for r in rows]
    assert sizes == sorted(sizes, reverse=True)


def test_values_outside_the_training_range_are_flagged(app, ready):
    result = run(app, input_key="co2_lag1", change_pct=200, model_name=ml_service.RIDGE)
    assert any("outside" in w for w in result["warnings"])


def test_one_facility_can_be_chosen(app, ready):
    everyone = run(app)["baseline"]["inputs"]["co2_lag1"]
    plant_three = run(app, facility_id="3")["baseline"]["inputs"]["co2_lag1"]
    assert plant_three > everyone  # plant 3 has the highest level in the made-up data


def test_bad_requests_are_rejected(app, ready):
    with pytest.raises(ValueError, match="input must be"):
        run(app, input_key="state")
    with pytest.raises(ValueError, match="between"):
        run(app, change_pct=500)
    with pytest.raises(ValueError, match="cannot show sensitivity"):
        run(app, model_name=ml_service.PERSISTENCE)
    with pytest.raises(ValueError, match="No usable recent unit-days"):
        run(app, facility_id="nope")


def test_sensitivity_endpoint(client, ready):
    body = client.get("/api/sensitivity?state=KY&change_pct=20&model=Ridge%20(linear)").get_json()
    assert body["model"] == ml_service.RIDGE
    assert body["scenario"]["change"] > 0
    assert client.get("/api/sensitivity").status_code == 400
    assert client.get("/api/sensitivity?state=KY&change_pct=abc").status_code == 400
    assert client.get("/api/sensitivity?state=TX&change_pct=5").status_code == 409


def test_options_endpoint_lists_inputs_facilities_and_models(client, ready):
    body = client.get("/api/sensitivity/options?state=KY").get_json()
    assert {i["key"] for i in body["inputs"]} == set(sensitivity_service.INPUTS)
    assert [f["id"] for f in body["facilities"]] == ["0", "1", "2", "3"]
    assert set(body["models"]) == set(ml_service.LEARNED_MODELS)
    assert body["default_model"] in ml_service.LEARNED_MODELS
