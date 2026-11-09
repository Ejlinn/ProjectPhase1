import math

import pytest

from services import analytics_service as analytics
from tests.conftest import add_records


def _row(i, co2, **extra):
    base = dict(facility_id=str(100 + i), facility_name=f"Plant {i}", state="KY",
                primary_fuel="Coal", co2_mass=co2, so2_mass=0.1 * (i + 1), nox_mass=0.05 * (i + 1),
                heat_input=10.0 * (i + 1), record_date="2024-06-01")
    base.update(extra)
    return base


def test_describe_known_values():
    stats = analytics.describe_values([1, 2, 3, 4, 5])
    assert stats["valid_count"] == 5
    assert stats["mean"] == pytest.approx(3.0)
    assert stats["median"] == pytest.approx(3.0)
    # sample variance of 1..5 is 2.5 (divide by n - 1)
    assert stats["variance"] == pytest.approx(2.5)
    assert stats["std_dev"] == pytest.approx(math.sqrt(2.5))
    assert stats["q1"] == pytest.approx(2.0)
    assert stats["q3"] == pytest.approx(4.0)
    assert stats["iqr"] == pytest.approx(2.0)
    assert stats["min"] == 1 and stats["max"] == 5
    assert stats["sum"] == pytest.approx(15.0)


def test_missing_values_are_excluded_not_zeroed():
    stats = analytics.describe_values([1, 2, None, 3, float("nan")])
    assert stats["total_count"] == 5
    assert stats["valid_count"] == 3
    assert stats["missing_count"] == 2
    assert stats["mean"] == pytest.approx(2.0)


def test_single_value_gives_null_variance():
    stats = analytics.describe_values([7.0])
    assert stats["mean"] == 7.0
    assert stats["variance"] is None
    assert stats["std_dev"] is None


def test_empty_input_gives_nulls():
    stats = analytics.describe_values([None, None])
    assert stats["valid_count"] == 0
    assert stats["mean"] is None and stats["median"] is None and stats["iqr"] is None


def test_recorded_zero_is_kept_as_a_value():
    stats = analytics.describe_values([0.0, 0.0])
    assert stats["mean"] == 0.0
    assert stats["zero_count"] == 2


def test_filters_change_database_results(app, clean_db):
    add_records([
        _row(0, 10.0, state="KY", primary_fuel="Coal", record_date="2024-06-01"),
        _row(1, 20.0, state="KY", primary_fuel="Coal", record_date="2024-06-02"),
        _row(2, 30.0, state="TX", primary_fuel="Natural Gas", record_date="2025"),
    ])
    with app.app_context():
        everything = analytics.summary({})["statistics"]["co2_mass"]
        assert everything["valid_count"] == 3
        assert everything["mean"] == pytest.approx(20.0)

        kentucky = analytics.summary({"state": "KY"})["statistics"]["co2_mass"]
        assert kentucky["valid_count"] == 2
        assert kentucky["mean"] == pytest.approx(15.0)

        year_2025 = analytics.summary({"year": "2025"})["statistics"]["co2_mass"]
        assert year_2025["valid_count"] == 1
        assert year_2025["variance"] is None

        coal = analytics.summary({"fuel": "Coal"})["statistics"]["co2_mass"]
        assert coal["valid_count"] == 2


def test_grouped_stats_by_state(app, clean_db):
    add_records([_row(0, 4.0, state="KY"), _row(1, 6.0, state="KY"), _row(2, 9.0, state="OH")])
    with app.app_context():
        groups = {g["group"]: g for g in analytics.summary({})["grouped"]["by_state"]}
    assert groups["KY"]["mean"] == pytest.approx(5.0)
    assert groups["KY"]["std_dev"] == pytest.approx(math.sqrt(2.0))
    assert groups["OH"]["std_dev"] is None


def test_parse_filters_rejects_bad_year():
    with pytest.raises(ValueError):
        analytics.parse_filters({"year": "24"})


def test_timeseries_needs_two_periods_for_trend(app, clean_db):
    add_records([_row(0, 5.0, record_date="2024-06-01"), _row(1, 7.0, record_date="2024-06-01")])
    with app.app_context():
        one = analytics.emissions_over_time({})
    assert one["trend_available"] is False
    assert one["periods"][0]["co2"] == pytest.approx(12.0)

    add_records([_row(2, 3.0, record_date="2024-06-02")])
    with app.app_context():
        two = analytics.emissions_over_time({})
    assert two["trend_available"] is True
    assert [p["period"] for p in two["periods"]] == ["2024-06-01", "2024-06-02"]


def test_top_emitters_sorted_and_uses_traci_factors(app, clean_db):
    add_records([_row(0, 1.0, state="KY"), _row(1, 5.0, state="KY"), _row(2, 3.0, state="OH")])
    with app.app_context():
        result = analytics.top_emitters({}, metric="co2_mass", group_by="state")
        assert [i["key"] for i in result["items"]] == ["KY", "OH"]
        assert result["items"][0]["value"] == pytest.approx(6.0)

        gw = analytics.top_emitters({}, metric="global_climate_kg_co2_eq", group_by="state")
        # CO2 global warming factor is 1.0 in the workbook: 907.18474 kg per short ton
        assert gw["items"][0]["value"] == pytest.approx(6.0 * 907.18474)


def test_heat_vs_co2_trendline_on_exact_line(app, clean_db):
    add_records([_row(i, 0.5 * 10.0 * (i + 1) + 1.0) for i in range(4)])
    with app.app_context():
        result = analytics.heat_vs_co2({})
    assert len(result["points"]) == 4
    assert result["trendline"]["slope"] == pytest.approx(0.5)
    assert result["trendline"]["intercept"] == pytest.approx(1.0)


def test_summary_endpoint_json_is_finite(client, clean_db, app):
    add_records([_row(0, 2.0), _row(1, None)])
    response = client.get("/api/analytics/summary")
    assert response.status_code == 200
    body = response.get_json()
    co2 = body["statistics"]["co2_mass"]
    assert co2["valid_count"] == 1 and co2["missing_count"] == 1
    assert co2["variance"] is None
    assert "gross_load" not in body["statistics"]  # no real values, so not reported
    assert body["traci"]["impacts"]["global_climate_kg_co2_eq"] == pytest.approx(2.0 * 907.18474)
