"""Download hourly CAMPD emissions from the EPA API and load daily totals per unit.

Usage (from the project folder, with the venv active):
    python scripts/fetch_campd_hourly.py

Needs EPA_API_KEY in .env. Each state is requested one month at a time. The hourly
rows are rolled up to one row per unit per day, so the time series has many real
reporting periods instead of two.

Unit conversions (CAMPD hourly fields):
    co2Mass  short tons         -> kept as short tons
    so2Mass  pounds             -> divided by 2000 to get short tons
    noxMass  pounds             -> divided by 2000 to get short tons
    heatInput mmBtu             -> summed per day
    grossLoad MW (hourly)       -> summed per day, so the daily value is MWh
"""

import calendar
import os
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))
load_dotenv(PROJECT_DIR / ".env")

from app import app  # noqa: E402  (creates tables, applies the safe schema check)
from models import FacilityRecord, UploadedDataset, db  # noqa: E402

API_URL = "https://api.epa.gov/easey/streaming-services/emissions/apportioned/hourly"
STATES = ["KY", "OH", "WV", "IN", "PA", "TX"]
MONTHS = [(y, m) for y in (2024, 2025) for m in range(1, 13)]
LBS_PER_SHORT_TON = 2000.0
DATASET_NAME = "CAMPD hourly API, daily totals per unit, KY/OH/WV/IN/PA/TX, 2024-2025"


def month_range(year, month):
    last_day = calendar.monthrange(year, month)[1]
    return f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last_day:02d}"


def fetch_month(session, state, year, month, api_key):
    begin, end = month_range(year, month)
    params = {"beginDate": begin, "endDate": end, "stateCode": state}
    for attempt in range(4):
        try:
            response = session.get(API_URL, params=params, headers={"x-api-key": api_key}, timeout=120)
            if response.status_code == 200:
                return response.json()
            if response.status_code not in (429, 500, 502, 503):
                raise RuntimeError(f"{state} {begin}: HTTP {response.status_code} {response.text[:150]}")
        except requests.RequestException as exc:
            # dropped connections happen on big months; retry the same request
            if attempt == 3:
                raise RuntimeError(f"{state} {begin}: connection failed ({exc.__class__.__name__})")
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"{state} {begin}: failed after retries")


def roll_up(rows):
    """Sum hourly rows into one entry per (state, facility, unit, date)."""
    days = {}
    for row in rows:
        key = (row.get("stateCode"), str(row.get("facilityId")), str(row.get("unitId")), row.get("date"))
        entry = days.get(key)
        if entry is None:
            entry = {
                "facility_name": row.get("facilityName"),
                "fuels": defaultdict(int),
                "co2": None, "so2_lbs": None, "nox_lbs": None, "heat": None, "gross_mwh": None,
                "hours": 0,
            }
            days[key] = entry
        entry["hours"] += 1
        fuel = row.get("primaryFuelInfo")
        if fuel:
            entry["fuels"][fuel] += 1
        for field, target in (("co2Mass", "co2"), ("so2Mass", "so2_lbs"), ("noxMass", "nox_lbs"),
                              ("heatInput", "heat"), ("grossLoad", "gross_mwh")):
            value = row.get(field)
            if value is not None:
                entry[target] = (entry[target] or 0.0) + float(value)
    return days


def build_records(state_days, dataset_id):
    records = []
    for (state, facility_id, unit_id, day), entry in state_days.items():
        flags = []
        co2 = entry["co2"]
        so2 = entry["so2_lbs"] / LBS_PER_SHORT_TON if entry["so2_lbs"] is not None else None
        nox = entry["nox_lbs"] / LBS_PER_SHORT_TON if entry["nox_lbs"] is not None else None
        heat = entry["heat"]
        if co2 is None:
            flags.append("missing:co2_mass")
        if so2 is None:
            flags.append("missing:so2_mass")
        if nox is None:
            flags.append("missing:nox_mass")
        if heat is None:
            flags.append("missing:heat_input")
        if entry["gross_mwh"] is None:
            flags.append("missing:gross_load")
        flags.append("aggregated:daily_sum_of_hours")
        fuel = max(entry["fuels"], key=entry["fuels"].get) if entry["fuels"] else None
        records.append(FacilityRecord(
            dataset_id=dataset_id,
            facility_id=facility_id,
            facility_name=entry["facility_name"],
            state=state,
            unit_id=unit_id,
            primary_fuel=fuel,
            co2_mass=co2,
            so2_mass=so2,
            nox_mass=nox,
            heat_input=heat,
            gross_load=entry["gross_mwh"],
            record_date=day,
            record_hour=None,
            data_flags=";".join(flags),
        ))
    return records


def main():
    api_key = os.environ.get("EPA_API_KEY")
    if not api_key:
        print("EPA_API_KEY is missing from .env")
        return 1

    session = requests.Session()
    all_days = {}
    failures = []
    start = time.time()
    for state in STATES:
        for year, month in MONTHS:
            label = f"{state} {year}-{month:02d}"
            try:
                rows = fetch_month(session, state, year, month, api_key)
            except RuntimeError as exc:
                failures.append(str(exc))
                print(f"  skipped {label}: {exc}")
                continue
            if not rows:
                print(f"  {label}: no rows")
                continue
            all_days.update(roll_up(rows))
            print(f"  {label}: {len(rows)} hourly rows")
    print(f"Fetched in {round(time.time() - start)} s; {len(all_days)} unit-days.")

    with app.app_context():
        dataset = UploadedDataset(
            filename="campd_hourly_api",
            notes=DATASET_NAME,
            upload_time=date.today().isoformat(),
            row_count=len(all_days),
        )
        db.session.add(dataset)
        db.session.flush()
        records = build_records(all_days, dataset.id)
        db.session.bulk_save_objects(records)
        db.session.commit()
        print(f"Saved dataset #{dataset.id} with {len(records)} daily unit records.")

    if failures:
        print(f"{len(failures)} requests failed; those months are missing from this dataset.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
