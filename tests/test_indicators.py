import pytest

from services import analytics_service as analytics
from tests.conftest import add_records


def _rec(fid, date, co2, load, heat=None, so2=None, nox=None, state="KY"):
    return dict(facility_id=fid, facility_name=f"Plant {fid}", state=state, primary_fuel="Coal",
                co2_mass=co2, so2_mass=so2, nox_mass=nox, heat_input=heat, gross_load=load, record_date=date)


def test_intensity_and_heat_rate_by_year(app, clean_db):
    add_records([
        _rec("1", "2024-01-01", co2=10.0, load=20.0, heat=200.0, so2=0.01, nox=0.02),
        _rec("2", "2024-01-02", co2=30.0, load=20.0, heat=400.0, so2=0.03, nox=0.02),
        _rec("1", "2025-01-01", co2=20.0, load=50.0, heat=500.0),
    ])
    with app.app_context():
        result = analytics.derived_indicators({})
    y2024, y2025 = result["by_year"]
    assert y2024["co2_intensity"] == pytest.approx(40.0 / 40.0)
    assert y2024["heat_rate"] == pytest.approx(600.0 / 40.0)
    # short tons x 2000 = pounds per MWh
    assert y2024["so2_intensity"] == pytest.approx(0.04 * 2000 / 40.0)
    assert y2025["co2_intensity"] == pytest.approx(20.0 / 50.0)
    # year-over-year change of total CO2: 40 -> 20
    assert y2025["co2_total_change"] == pytest.approx(-20.0)
    assert y2025["co2_total_change_pct"] == pytest.approx(-50.0)
    assert "co2_total_change" not in y2024


def test_zero_or_missing_load_gives_missing_ratio_not_zero(app, clean_db):
    add_records([
        _rec("1", "2024-01-01", co2=10.0, load=0.0, heat=100.0),
        _rec("2", "2024-01-02", co2=10.0, load=None, heat=100.0),
    ])
    with app.app_context():
        row = analytics.derived_indicators({})["by_year"][0]
    assert row["co2_intensity"] is None
    assert row["heat_rate"] is None
    assert row["so2_intensity"] is None


def test_missing_emission_is_left_out_of_its_ratio(app, clean_db):
    add_records([
        _rec("1", "2024-01-01", co2=10.0, load=10.0, so2=None),
        _rec("2", "2024-01-01", co2=10.0, load=30.0, so2=0.02),
    ])
    with app.app_context():
        row = analytics.derived_indicators({})["by_year"][0]
    # SO2 intensity uses only the record that has SO2: 0.02 t * 2000 / 30 MWh
    assert row["so2_intensity"] == pytest.approx(40.0 / 30.0)
    assert row["co2_intensity"] == pytest.approx(20.0 / 40.0)


def test_distribution_histogram_boxes_and_correlation(app, clean_db):
    add_records([_rec(str(i), "2024-01-01", co2=float(i + 1), load=float(2 * (i + 1)), heat=float(10 * (i + 1)),
                      state="KY" if i % 2 else "OH") for i in range(20)])
    with app.app_context():
        result = analytics.distribution({})
    assert sum(result["histogram"]["counts"]) == 20
    assert {b["group"] for b in result["boxes"]} == {"KY", "OH"}
    for box in result["boxes"]:
        assert box["low"] <= box["q1"] <= box["median"] <= box["q3"] <= box["high"]
    corr = result["correlation"]
    i, j = corr["fields"].index("co2_mass"), corr["fields"].index("heat_input")
    assert corr["matrix"][i][j] == pytest.approx(1.0)


def test_indicator_and_distribution_endpoints(client, clean_db):
    add_records([_rec("1", "2024-01-01", co2=5.0, load=10.0, heat=50.0),
                 _rec("2", "2024-01-02", co2=7.0, load=10.0, heat=70.0)])
    assert client.get("/api/analytics/indicators?state=KY").status_code == 200
    assert client.get("/api/analytics/distribution").status_code == 200
    assert client.get("/api/analytics/indicators?year=bad").status_code == 400
