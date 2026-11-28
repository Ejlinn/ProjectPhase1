"""What-if sensitivity for the CO₂ forecast.

The question this answers: if one input to the forecast were a bit higher or lower, how much
would the forecast CO₂ change?

How it works:
1. Build a typical unit-day for a state (or one facility): the median of each input over the
   most recent 30 days of data, with the most common fuel.
2. Forecast CO₂ for that typical day. This is the baseline.
3. Scale one input (for example yesterday's heat input) up or down by a percentage and forecast again.
4. Report the change. "Sensitivity" is the percent change in the forecast for a 1% change in the input.

Only the chosen input moves. Everything else stays at its typical value, so this is a
one-at-a-time sensitivity check on the model, not a prediction of what a plant would do.
"""

import re
import time
from datetime import timedelta

import pandas as pd
from sqlalchemy import func

from models import FacilityRecord, db
from services import ml_service

# What can be moved with the slider. "columns" lists the model inputs that change together.
INPUTS = {
    "level": {
        "label": "Yesterday's operating level (heat input and CO₂ together)",
        "short": "Yesterday's level (both)",
        "columns": ["co2_lag1", "heat_lag1"],
    },
    "co2_lag1": {"label": "Yesterday's CO₂ only", "short": "Yesterday's CO₂", "columns": ["co2_lag1"]},
    "heat_lag1": {"label": "Yesterday's heat input only", "short": "Yesterday's heat input", "columns": ["heat_lag1"]},
    "co2_roll7": {"label": "Average CO₂ of the previous 7 days", "short": "7-day average CO₂", "columns": ["co2_roll7"]},
    "heat_roll7": {"label": "Average heat input of the previous 7 days", "short": "7-day average heat", "columns": ["heat_roll7"]},
    "co2_lag7": {"label": "CO₂ on the same day last week", "short": "CO₂ one week ago", "columns": ["co2_lag7"]},
}
DEFAULT_INPUT = "level"
CURVE_STEPS = list(range(-50, 51, 5))
TORNADO_STEP = 10
RECENT_DAYS = 30
MIN_CHANGE, MAX_CHANGE = -90.0, 200.0
BASELINE_CACHE_SECONDS = 300

_baseline_cache = {}

# Named scenarios, each compared with the baseline. "changes" maps a model input to a percent change.
SCENARIOS = [
    {"key": "load_up_10", "label": "Operating level +10%",
     "description": "Yesterday's heat input and CO₂ both 10% higher.",
     "changes": {"co2_lag1": 10, "heat_lag1": 10}},
    {"key": "heat_down_5", "label": "Heat input −5%",
     "description": "Yesterday's heat input and the 7-day average heat input 5% lower.",
     "changes": {"heat_lag1": -5, "heat_roll7": -5}},
    {"key": "busy_week", "label": "Busy week +20%",
     "description": "The whole past week ran 20% higher: yesterday, last week, and both 7-day averages.",
     "changes": {"co2_lag1": 20, "heat_lag1": 20, "co2_lag7": 20, "co2_roll7": 20, "heat_roll7": 20}},
    {"key": "high_efficiency", "label": "High efficiency (combined)",
     "description": "Same output with 5% less fuel: heat input −5% and CO₂ −5% for yesterday and the 7-day averages.",
     "changes": {"heat_lag1": -5, "heat_roll7": -5, "co2_lag1": -5, "co2_roll7": -5}},
    {"key": "fuel_switch", "label": "Fuel switched",
     "description": "Same history, but the unit is labelled with a different primary fuel (natural gas, or coal if it already burns gas).",
     "changes": {}, "fuel": True},
]


def facilities_for_state(state):
    """Facilities that have daily records in this state, for the dropdown."""
    f = FacilityRecord
    rows = (db.session.query(f.facility_id, func.max(f.facility_name))
            .filter(f.state == state, f.record_hour.is_(None), func.length(f.record_date) == 10)
            .group_by(f.facility_id).order_by(f.facility_id).all())
    return [{"id": fid, "name": name or fid} for fid, name in rows]


def options(state=None):
    result = {"inputs": [{"key": key, "label": item["label"]} for key, item in INPUTS.items()],
              "default_input": DEFAULT_INPUT, "min_change": -50, "max_change": 50}
    if state:
        result["facilities"] = facilities_for_state(state)
        try:
            artifact = ml_service.load_artifact(state=state)
            result["models"] = [name for name in ml_service.LEARNED_MODELS if name in artifact["models"]]
            result["default_model"] = artifact.get("sensitivity_model") or artifact["selected_model"]
        except FileNotFoundError:
            result["models"], result["default_model"] = [], None
    return result


def baseline_scenario(state, facility_id=None):
    """The typical recent unit-day for a state or facility: inputs, the date being forecast, and how many unit-days it comes from."""
    f = FacilityRecord
    latest = (db.session.query(func.max(f.record_date))
              .filter(f.state == state, f.record_hour.is_(None), func.length(f.record_date) == 10).scalar())
    if not latest:
        raise ValueError(f"No daily records for {state}.")
    key = (state, facility_id, latest)
    cached = _baseline_cache.get(key)
    if cached and time.time() - cached["at"] < BASELINE_CACHE_SECONDS:
        return cached["value"]

    last_day = pd.Timestamp(latest)
    # 7 extra days at the start so the lag and 7-day features exist for the first recent day
    raw = ml_service.load_daily_rows(state, since=str((last_day - timedelta(days=RECENT_DAYS + 7)).date()))
    if facility_id:
        raw = raw[raw["facility_id"].astype(str) == str(facility_id)]
    rows = ml_service.eligible_rows(ml_service.prepare_rows(raw))
    recent = rows[rows["date"] >= last_day - timedelta(days=RECENT_DAYS - 1)]
    if recent.empty:
        where = f"facility {facility_id} in {state}" if facility_id else state
        raise ValueError(f"No usable recent unit-days for {where}. A day needs CO₂ and heat input for itself and the day before.")

    forecast_day = last_day + timedelta(days=1)
    inputs = {name: float(recent[name].median()) for name in ml_service.HISTORY_FEATURES}
    fuels = recent["primary_fuel"].dropna()
    inputs["primary_fuel"] = fuels.mode().iloc[0] if not fuels.empty else None
    inputs["day_of_week"] = int(forecast_day.day_of_week)
    inputs["month"] = int(forecast_day.month)
    value = {"inputs": inputs, "forecast_for": str(forecast_day.date()), "unit_days": int(len(recent)),
             "from": str(recent["date"].min().date()), "to": str(last_day.date())}
    _baseline_cache[key] = {"at": time.time(), "value": value}
    return value


def _scaled(inputs, columns, change_pct):
    record = dict(inputs)
    for column in columns:
        record[column] = inputs[column] * (1 + change_pct / 100.0)
    return record


def sensitivity(state, facility_id=None, input_key=DEFAULT_INPUT, change_pct=0.0, model_name=None):
    """Run the what-if. Returns a dict that can go straight to jsonify()."""
    if input_key not in INPUTS:
        raise ValueError(f"input must be one of {', '.join(INPUTS)}")
    change_pct = float(change_pct)
    if not (MIN_CHANGE <= change_pct <= MAX_CHANGE):
        raise ValueError(f"change_pct must be between {MIN_CHANGE:.0f} and {MAX_CHANGE:.0f}")

    artifact = ml_service.load_artifact(state=state)
    model = model_name or artifact.get("sensitivity_model") or artifact["selected_model"]
    if model not in ml_service.LEARNED_MODELS:
        raise ValueError(f"model must be one of {', '.join(ml_service.LEARNED_MODELS)}. "
                         "The yesterday baseline only copies one input, so it cannot show sensitivity.")
    base = baseline_scenario(state, facility_id)
    inputs = base["inputs"]
    columns = INPUTS[input_key]["columns"]

    # one batch: baseline, the chosen change, the curve, the +/-1% pair for the slope, and the comparison of every input
    records, tags = [dict(inputs)], [("baseline",)]
    records.append(_scaled(inputs, columns, change_pct)); tags.append(("scenario",))
    for step in CURVE_STEPS:
        records.append(_scaled(inputs, columns, step)); tags.append(("curve", step))
    records.append(_scaled(inputs, columns, -1.0)); tags.append(("minus1",))
    records.append(_scaled(inputs, columns, 1.0)); tags.append(("plus1",))
    for key, item in INPUTS.items():
        for sign in (-1, 1):
            records.append(_scaled(inputs, item["columns"], sign * TORNADO_STEP)); tags.append(("tornado", key, sign))
    scenario_records = {}
    for scenario in SCENARIOS:
        record = dict(inputs)
        for column, pct in scenario["changes"].items():
            record[column] = inputs[column] * (1 + pct / 100.0)
        if scenario.get("fuel"):
            gas = "Natural Gas" in str(inputs.get("primary_fuel") or "")
            record["primary_fuel"] = "Coal" if gas else "Pipeline Natural Gas"
        scenario_records[scenario["key"]] = record
        records.append(record); tags.append(("named", scenario["key"]))

    result = ml_service.predict(records, artifact=artifact, model_name=model)
    values = dict(zip([t for t in tags], result["predictions"]))
    baseline_pred = values[("baseline",)]
    scenario_pred = values[("scenario",)]
    # the same input record is forecast about 35 times, so drop the repeated "row N:" messages
    warnings = list(dict.fromkeys(re.sub(r"^row \d+: ", "", w) for w in result["warnings"]))

    def pct_of_baseline(value):
        if value is None or baseline_pred is None or baseline_pred <= 0:
            return None
        return (value - baseline_pred) / baseline_pred * 100.0

    elasticity = None
    if baseline_pred and baseline_pred > 0 and values[("minus1",)] is not None and values[("plus1",)] is not None:
        # percent change in the forecast per 1% change in the input, from a small step either side
        elasticity = (values[("plus1",)] - values[("minus1",)]) / baseline_pred / 0.02

    ranges = artifact.get("feature_ranges", {})
    for column in columns:
        low, high = ranges.get(column, [None, None])
        scaled = inputs[column] * (1 + change_pct / 100.0)
        if low is not None and not (low <= scaled <= high):
            warnings.append(f"{column} = {scaled:,.0f} is outside the {low:,.0f} to {high:,.0f} range the model trained on, "
                            "so this forecast is less reliable.")
    if change_pct != 0 and scenario_pred is not None and scenario_pred == baseline_pred:
        warnings.append("The forecast did not move. Tree models only change when an input crosses a split point they learned.")
    if baseline_pred is not None and baseline_pred <= 0:
        warnings.append("The baseline forecast is zero or negative, so percent changes are not shown.")

    tornado = []
    for key, item in INPUTS.items():
        down = pct_of_baseline(values[("tornado", key, -1)])
        up = pct_of_baseline(values[("tornado", key, 1)])
        tornado.append({"key": key, "label": item["short"], "down_pct": down, "up_pct": up,
                        "size": max(abs(down or 0), abs(up or 0))})
    tornado.sort(key=lambda row: -row["size"])

    def outside_range(record):
        """Names of inputs in this record that fall outside what the model trained on."""
        names = []
        for column in ml_service.HISTORY_FEATURES:
            low, high = ranges.get(column, [None, None])
            if low is not None and record.get(column) is not None and not (low <= record[column] <= high):
                names.append(column)
        return names

    scenarios = [{"key": "baseline", "label": "Baseline", "description": "Typical recent unit-day, nothing changed.",
                  "prediction": baseline_pred, "change": 0.0 if baseline_pred is not None else None,
                  "change_pct": 0.0 if baseline_pred else None, "outside_range": [], "changes": {}}]
    for scenario in SCENARIOS:
        value = values[("named", scenario["key"])]
        record = scenario_records[scenario["key"]]
        changes = dict(scenario["changes"])
        if scenario.get("fuel"):
            changes["primary_fuel"] = f"{inputs.get('primary_fuel')} → {record['primary_fuel']}"
        scenarios.append({
            "key": scenario["key"], "label": scenario["label"], "description": scenario["description"],
            "prediction": value,
            "change": None if value is None or baseline_pred is None else value - baseline_pred,
            "change_pct": pct_of_baseline(value), "outside_range": outside_range(record), "changes": changes,
        })

    curve_outside = [bool(outside_range(_scaled(inputs, columns, step))) for step in CURVE_STEPS]

    return {
        "state": state, "facility_id": facility_id, "model": model, "units": ml_service.TARGET_UNITS,
        "input": {"key": input_key, "label": INPUTS[input_key]["label"], "columns": columns},
        "change_pct": change_pct,
        "baseline": {"inputs": inputs, "forecast_for": base["forecast_for"], "prediction": baseline_pred,
                     "based_on": f"median of {base['unit_days']} unit-days, {base['from']} to {base['to']}"},
        "scenario": {
            "inputs": {c: inputs[c] * (1 + change_pct / 100.0) for c in columns},
            "prediction": scenario_pred,
            "change": None if scenario_pred is None or baseline_pred is None else scenario_pred - baseline_pred,
            "change_pct": pct_of_baseline(scenario_pred),
        },
        "sensitivity": {
            "per_one_percent": elasticity,
            "meaning": "Percent change in forecast CO₂ for a 1% change in this input, with every other input held fixed.",
        },
        "curve": {"change_pct": CURVE_STEPS, "prediction": [values[("curve", s)] for s in CURVE_STEPS],
                  "outside_range": curve_outside,
                  "input_values": {c: [inputs[c] * (1 + s / 100.0) for s in CURVE_STEPS] for c in columns}},
        "tornado": {"step_pct": TORNADO_STEP, "rows": tornado},
        "scenarios": scenarios,
        "warnings": warnings,
    }
