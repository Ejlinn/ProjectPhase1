import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fetch_campd_hourly as fetch  # noqa: E402


def _hour(hour, **fields):
    base = dict(stateCode="KY", facilityId=1353, facilityName="Test Plant", unitId="1",
                date="2024-06-01", hour=hour, primaryFuelInfo="Coal")
    base.update(fields)
    return base


def test_hourly_rows_roll_up_to_one_daily_row():
    rows = [
        _hour(0, co2Mass=2.0, so2Mass=1000.0, noxMass=500.0, heatInput=20.0, grossLoad=100.0),
        _hour(1, co2Mass=3.0, so2Mass=1000.0, noxMass=500.0, heatInput=30.0, grossLoad=120.0),
    ]
    days = fetch.roll_up(rows)
    assert len(days) == 1
    entry = next(iter(days.values()))
    assert entry["hours"] == 2
    assert entry["co2"] == pytest.approx(5.0)
    assert entry["heat"] == pytest.approx(50.0)


def test_pounds_become_short_tons_and_missing_is_flagged():
    days = fetch.roll_up([_hour(0, co2Mass=4.0, so2Mass=4000.0, noxMass=2000.0)])
    (state, facility, unit, day), entry = next(iter(days.items()))
    (record,) = fetch.build_records(days, dataset_id=9)
    assert record.co2_mass == pytest.approx(4.0)        # already short tons, unchanged
    assert record.so2_mass == pytest.approx(2.0)        # 4000 lb / 2000 = 2 short tons
    assert record.nox_mass == pytest.approx(1.0)        # 2000 lb / 2000 = 1 short ton
    assert record.heat_input is None                    # not reported, stays empty
    assert "missing:heat_input" in record.data_flags
    assert "aggregated:daily_sum_of_hours" in record.data_flags


def test_month_range_handles_leap_february():
    assert fetch.month_range(2024, 2) == ("2024-02-01", "2024-02-29")
    assert fetch.month_range(2025, 2) == ("2025-02-01", "2025-02-28")
