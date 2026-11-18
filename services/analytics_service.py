"""Descriptive statistics and chart data for the Data Analytics dashboard.

Everything here reads FacilityRecord rows, applies the optional filters, and returns
plain dictionaries that can go straight into jsonify().

Conventions used throughout:
* Variance and standard deviation are SAMPLE statistics (divide by n - 1).
  They are null when fewer than two valid values exist.
* Quartiles use linear interpolation (pandas' default, same as NumPy's default).
* Missing means NULL in the database. Zero is a real value unless the record's
  data_flags say a field was filled in.
"""

import math
import threading
import time

import numpy as np
import pandas as pd
from sqlalchemy import case, func, text

from impact import SHORT_TON_KG, aggregate_impacts
from models import FacilityRecord, UploadedDataset, db

# Numeric fields we describe. gross_load is only included when it has real values.
STAT_FIELDS = {
    "co2_mass": {"label": "CO₂ mass", "unit": "short tons"},
    "so2_mass": {"label": "SO₂ mass", "unit": "short tons"},
    "nox_mass": {"label": "NOₓ mass", "unit": "short tons"},
    "heat_input": {"label": "Heat input", "unit": "mmBtu"},
    "gross_load": {"label": "Gross load", "unit": "MWh"},
}

# Metrics the top-emitter chart can rank by. The TRACI ones are impact equivalents,
# not masses, so their units differ.
TOP_METRICS = {
    "co2_mass": {"label": "CO₂ mass", "unit": "short tons"},
    "so2_mass": {"label": "SO₂ mass", "unit": "short tons"},
    "nox_mass": {"label": "NOₓ mass", "unit": "short tons"},
    "global_climate_kg_co2_eq": {"label": "TRACI global warming", "unit": "kg CO₂ eq"},
    "acidification_kg_so2_eq": {"label": "TRACI acidification", "unit": "kg SO₂ eq"},
}


def _finite(value):
    """Return a float if it is finite, otherwise None (JSON cannot hold NaN or inf)."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse_filters(args):
    """Read the shared filter query parameters. Raises ValueError for a bad year or dataset."""
    filters = {
        "state": (args.get("state") or "").strip().upper() or None,
        "fuel": (args.get("fuel") or "").strip() or None,
        "year": (args.get("year") or "").strip() or None,
        "dataset_id": None,
        "facility_id": (args.get("facility_id") or "").strip() or None,
    }
    if filters["year"] is not None and not (filters["year"].isdigit() and len(filters["year"]) == 4):
        raise ValueError("year must be a four-digit value such as 2024")
    if args.get("dataset_id"):
        try:
            filters["dataset_id"] = int(args.get("dataset_id"))
        except ValueError as exc:
            raise ValueError("dataset_id must be an integer") from exc
    return filters


def _filtered_query(filters):
    query = FacilityRecord.query
    if filters.get("state"):
        query = query.filter(FacilityRecord.state == filters["state"])
    if filters.get("fuel"):
        query = query.filter(FacilityRecord.primary_fuel == filters["fuel"])
    if filters.get("year"):
        # record_date is stored as text ("2024-06-01" or "2025"), so the year is the first four characters
        query = query.filter(func.substr(FacilityRecord.record_date, 1, 4) == filters["year"])
    if filters.get("dataset_id") is not None:
        query = query.filter(FacilityRecord.dataset_id == filters["dataset_id"])
    if filters.get("facility_id"):
        query = query.filter(FacilityRecord.facility_id == filters["facility_id"])
    return query


FRAME_CACHE_SECONDS = 120
_frame_cache = {"key": None, "frame": None, "loaded_at": 0.0}
_frame_lock = threading.Lock()


def _data_version():
    """Cheap fingerprint of the records table, so the cache clears after an upload or import."""
    # count and newest id catch uploads; the sums catch edited or replaced rows (ids can be reused after a delete)
    count, newest, co2, so2, heat = db.session.query(
        func.count(FacilityRecord.id), func.max(FacilityRecord.id),
        func.sum(FacilityRecord.co2_mass), func.sum(FacilityRecord.so2_mass),
        func.sum(FacilityRecord.heat_input),
    ).one()
    return (int(count or 0), int(newest or 0), co2, so2, heat)


def load_frame(filters=None):
    """Load the filtered records as a DataFrame. The last result is kept, because the
    dashboard asks for several endpoints with the same filters in a row."""
    filters = filters or {}
    key = (tuple(sorted((k, str(v)) for k, v in filters.items())), _data_version())
    # the dashboard fires several requests at once; the lock makes the others wait for one load
    with _frame_lock:
        fresh = time.time() - _frame_cache["loaded_at"] < FRAME_CACHE_SECONDS
        if fresh and _frame_cache["key"] == key:
            return _frame_cache["frame"]
        frame = _read_frame(filters)
        _frame_cache.update(key=key, frame=frame, loaded_at=time.time())
        return frame


def _read_frame(filters):
    """Read the filtered records as a pandas DataFrame with one row per FacilityRecord."""
    columns = [
        FacilityRecord.id, FacilityRecord.dataset_id, FacilityRecord.facility_id,
        FacilityRecord.facility_name, FacilityRecord.state, FacilityRecord.unit_id,
        FacilityRecord.primary_fuel, FacilityRecord.co2_mass, FacilityRecord.so2_mass,
        FacilityRecord.nox_mass, FacilityRecord.heat_input, FacilityRecord.gross_load,
        FacilityRecord.record_date, FacilityRecord.data_flags,
    ]
    # read_sql goes straight from SQLite into DataFrame columns; building ORM objects per row was the slow part
    statement = _filtered_query(filters or {}).with_entities(*columns).statement
    frame = pd.read_sql(statement, db.engine)
    if frame.empty:
        return frame
    frame["year"] = frame["record_date"].astype(str).str[:4]
    for field in STAT_FIELDS:
        frame[field] = pd.to_numeric(frame[field], errors="coerce")
    return frame


def describe_values(values):
    """Descriptive statistics for one numeric column. Returns a JSON-safe dict."""
    series = values if isinstance(values, pd.Series) else pd.Series(values, dtype="object")
    series = pd.to_numeric(series, errors="coerce")
    total = int(series.shape[0])
    valid = series.dropna().astype(float)
    n = int(valid.shape[0])

    result = {
        "total_count": total,
        "valid_count": n,
        "missing_count": total - n,
        "zero_count": int((valid == 0).sum()) if n else 0,
        "sum": None, "mean": None, "median": None, "variance": None, "std_dev": None,
        "min": None, "max": None, "q1": None, "q3": None, "iqr": None,
    }
    if n == 0:
        return result

    result["sum"] = _finite(valid.sum())
    result["mean"] = _finite(valid.mean())
    result["min"] = _finite(valid.min())
    result["max"] = _finite(valid.max())
    # one pass for all three quartiles (linear interpolation, same as pandas' default)
    q1, median, q3 = np.quantile(valid.to_numpy(), [0.25, 0.5, 0.75])
    result["median"] = _finite(median)
    result["q1"] = _finite(q1)
    result["q3"] = _finite(q3)
    result["iqr"] = _finite(q3 - q1)
    if n >= 2:
        # ddof=1: sample variance (n - 1 in the denominator)
        result["variance"] = _finite(valid.var(ddof=1))
        result["std_dev"] = _finite(valid.std(ddof=1))
    return result


def descriptive_statistics(frame):
    """Stats for every numeric field. gross_load is left out when it has no real values."""
    stats = {}
    for field, meta in STAT_FIELDS.items():
        if field == "gross_load" and (frame.empty or frame["gross_load"].dropna().empty):
            continue
        entry = describe_values(frame[field].tolist() if not frame.empty else [])
        entry.update({"label": meta["label"], "unit": meta["unit"], "variance_unit": f"({meta['unit']})²"})
        stats[field] = entry
    return stats


_numeric_cache = {"key": None, "frame": None, "loaded_at": 0.0}


def _numeric_frame(filters):
    """Just the five numeric columns, for quartiles and medians. Strings were most of the load
    time, and everything that groups by text now runs in SQL instead."""
    filters = filters or {}
    key = (tuple(sorted((k, str(v)) for k, v in filters.items())), _data_version())
    with _frame_lock:
        if time.time() - _numeric_cache["loaded_at"] < FRAME_CACHE_SECONDS and _numeric_cache["key"] == key:
            return _numeric_cache["frame"]
        columns = [getattr(FacilityRecord, name) for name in STAT_FIELDS]
        statement = _filtered_query(filters).with_entities(*columns).statement
        frame = pd.read_sql(statement, db.engine)
        for field in STAT_FIELDS:
            frame[field] = pd.to_numeric(frame[field], errors="coerce")
        _numeric_cache.update(key=key, frame=frame, loaded_at=time.time())
        return frame


def group_totals(filters, shift=0.0, field="co2_mass"):
    """One database scan that returns additive totals for every (state, fuel, facility, year).

    Counts and sums can be added together, so each breakdown on the dashboard (by state, by
    fuel, by year, by facility) is made from this one small table instead of scanning 700k
    rows four more times. `shift` is subtracted before squaring, which keeps the n - 1
    standard deviation formula accurate when the values are large."""
    f = FacilityRecord
    column = getattr(f, field)
    shifted = column - shift
    year = func.substr(f.record_date, 1, 4)
    rows = (_filtered_query(filters).with_entities(
                f.state, f.primary_fuel, f.facility_id, year,
                func.count(), func.count(column), func.sum(column),
                func.sum(shifted), func.sum(shifted * shifted))
            .group_by(f.state, f.primary_fuel, f.facility_id, year).all())
    return pd.DataFrame(rows, columns=["state", "primary_fuel", "facility_id", "year", "n", "v", "s", "s1", "s2"])


def grouped_statistics(totals, by):
    """Per-group count, mean, sum and sample std dev of CO₂, built from group_totals()."""
    if totals.empty:
        return []
    parts = totals.groupby(by, dropna=False)[["n", "v", "s", "s1", "s2"]].sum(min_count=1)
    groups = []
    for key, row in parts.iterrows():
        valid = int(row["v"] or 0)
        std = None
        if valid >= 2:
            variance = (row["s2"] - row["s1"] * row["s1"] / valid) / (valid - 1)
            std = _finite(math.sqrt(max(variance, 0.0)))
        groups.append({
            "group": "" if pd.isna(key) else str(key),
            "record_count": int(row["n"]),
            "valid_count": valid,
            "mean": _finite(row["s"] / valid) if valid else None,
            "sum": _finite(row["s"]) if valid else None,
            "std_dev": std,
        })
    groups.sort(key=lambda g: (g["sum"] is None, -(g["sum"] or 0)))
    return groups


def data_quality(filters):
    """Summarise missing and filled-in values so the dashboard can show caveats."""
    f = FacilityRecord
    all_zero_test = case(
        ((f.co2_mass == 0) & (f.so2_mass == 0) & (f.nox_mass == 0) & (f.heat_input == 0), 1), else_=0)
    total, flagged, all_zero = _filtered_query(filters).with_entities(
        func.count(), func.count(f.data_flags), func.sum(all_zero_test)).one()
    total, flagged, all_zero = int(total or 0), int(flagged or 0), int(all_zero or 0)
    if total == 0:
        return {"total_records": 0, "flagged_records": 0, "legacy_all_zero_records": 0, "notes": []}
    notes = []
    if all_zero:
        notes.append(
            f"{all_zero} records have zero for CO₂, SO₂, NOₓ and heat input. Older uploads "
            "replaced missing numbers with 0, so these may be gaps, not measured zeros."
        )
    if flagged == 0:
        notes.append("No upload flags are stored for these records. They were loaded before flagging was added.")
    return {
        "total_records": total,
        "flagged_records": flagged,
        "legacy_all_zero_records": all_zero,
        "notes": notes,
    }


def _load_factors():
    """Read the TRACI factors table. Returns (factors dict, warnings list)."""
    try:
        rows = db.session.execute(text("SELECT * FROM traci_factors")).mappings().all()
    except Exception:
        return {}, ["TRACI factors have not been imported."]
    return {row["substance_name"]: dict(row) for row in rows}, []


def traci_summary(frame, filters=None):
    """Environmental impact totals for the filtered records, using the TRACI factors.
    Uses the same calculation as the facility impact endpoint."""
    result = aggregate_impacts(_filtered_query(filters or {}), db.engine)
    result["short_ton_to_kg"] = SHORT_TON_KG
    return result


def summary(filters):
    frame = _numeric_frame(filters)
    co2_mean = frame["co2_mass"].mean() if not frame.empty else 0.0
    totals = group_totals(filters, shift=0.0 if pd.isna(co2_mean) else float(co2_mean))
    return {
        "filters": filters,
        "statistics": descriptive_statistics(frame),
        "grouped": {
            "by_state": grouped_statistics(totals, "state"),
            "by_fuel": grouped_statistics(totals, "primary_fuel"),
            "by_year": grouped_statistics(totals, "year"),
            "by_facility": grouped_statistics(totals, "facility_id")[:25],
        },
        "data_quality": data_quality(filters),
        "traci": traci_summary(frame, filters),
    }


def emissions_over_time(filters):
    """Totals per reporting period (the record_date value). Only shows a trend when
    there is more than one period."""
    f = FacilityRecord
    # coalesce keeps the old behaviour: a period with nothing reported sums to 0
    rows = (_filtered_query(filters).filter(f.record_date.isnot(None))
            .with_entities(f.record_date, func.coalesce(func.sum(f.co2_mass), 0.0),
                           func.coalesce(func.sum(f.so2_mass), 0.0),
                           func.coalesce(func.sum(f.nox_mass), 0.0),
                           func.count(func.distinct(f.facility_id)), func.count())
            .group_by(f.record_date).order_by(f.record_date).all())
    if not rows:
        return {"periods": [], "trend_available": False,
                "message": "No records match these filters."}
    periods = [
        {"period": day, "co2": _finite(co2), "so2": _finite(so2), "nox": _finite(nox),
         "facilities": int(facilities), "records": int(records)}
        for day, co2, so2, nox, facilities, records in rows
    ]
    trend = len(periods) > 1
    message = None if trend else (
        "Only one reporting period is in the current selection, so a historical trend is not available."
    )
    return {"periods": periods, "trend_available": trend, "message": message}


def top_emitters(filters, metric="co2_mass", limit=10, group_by="facility"):
    """Rank facilities or states by one metric. TRACI metrics are computed from the factors table."""
    if metric not in TOP_METRICS:
        raise ValueError(f"metric must be one of {', '.join(TOP_METRICS)}")
    if group_by not in ("facility", "state"):
        raise ValueError("group_by must be 'facility' or 'state'")
    f = FacilityRecord
    key_column = f.facility_id if group_by == "facility" else f.state
    rows = (_filtered_query(filters).filter(key_column.isnot(None))
            .with_entities(key_column, func.sum(f.co2_mass), func.sum(f.so2_mass), func.sum(f.nox_mass))
            .group_by(key_column).all())
    if not rows:
        return {"metric": metric, "items": [], "warnings": [], "message": "No records match these filters."}
    # one total per group; a group with nothing reported stays missing instead of becoming 0
    per_group = pd.DataFrame(rows, columns=["key", "co2_mass", "so2_mass", "nox_mass"]).set_index("key")

    warnings = []
    if metric in ("co2_mass", "so2_mass", "nox_mass"):
        sums = per_group[metric]
    else:
        factors, factor_warnings = _load_factors()
        warnings.extend(factor_warnings)
        if metric == "global_climate_kg_co2_eq":
            substance, column, mass = "CARBON DIOXIDE", "global_climate_kg_co2_eq_per_kg", "co2_mass"
        else:
            # NOx and SO2 both map to the acidification factors, same as impact.py
            substance, column, mass = "SULFUR DIOXIDE", "acidification_kg_so2_eq_per_kg", "so2_mass"
        if metric == "acidification_kg_so2_eq":
            # SO2 and NOx both count toward acidification, each with its own factor (same as impact.py)
            so2_factor = factors.get("SULFUR DIOXIDE", {}).get("acidification_kg_so2_eq_per_kg")
            nox_factor = factors.get("NITROGEN OXIDES", {}).get("acidification_kg_so2_eq_per_kg")
            if so2_factor is None or nox_factor is None:
                warnings.append("Missing acidification factor for SO₂ or NOₓ; this ranking is empty.")
                return {"metric": metric, "items": [], "warnings": warnings, "message": None}
            so2 = per_group["so2_mass"].fillna(0)
            nox = per_group["nox_mass"].fillna(0)
            sums = (so2 * so2_factor + nox * nox_factor) * SHORT_TON_KG
        else:
            factor = factors.get(substance, {}).get(column)
            if factor is None:
                warnings.append(f"Missing {column} factor for {substance}; this ranking is empty.")
                return {"metric": metric, "items": [], "warnings": warnings, "message": None}
            sums = per_group[mass] * SHORT_TON_KG * factor
    top = sums.dropna().sort_values(ascending=False).head(limit)
    names = {}
    if group_by == "facility" and len(top):
        names = dict(db.session.query(f.facility_id, func.max(f.facility_name))
                     .filter(f.facility_id.in_(list(top.index))).group_by(f.facility_id).all())
    items = []
    for group_value, total in top.items():
        label = str(group_value)
        if names.get(group_value):
            label = f"{names[group_value]} ({group_value})"
        items.append({"label": label, "key": str(group_value), "value": _finite(total)})
    return {"metric": metric, "label": TOP_METRICS[metric]["label"],
            "unit": TOP_METRICS[metric]["unit"], "items": items, "warnings": warnings, "message": None}


def heat_vs_co2(filters, limit=2000):
    """Heat input against CO₂ for rows where both are real numbers. Gross load is not in the data yet."""
    f = FacilityRecord
    pairs = _filtered_query(filters).filter(f.heat_input.isnot(None), f.co2_mass.isnot(None), f.heat_input > 0)
    n, mean_x, mean_y, min_x, max_x = pairs.with_entities(
        func.count(), func.avg(f.heat_input), func.avg(f.co2_mass),
        func.min(f.heat_input), func.max(f.heat_input)).one()
    n = int(n or 0)
    if n == 0:
        return {"x_label": "Heat input (mmBtu)", "y_label": "CO₂ mass (short tons)", "points": [],
                "trendline": None, "message": "Not enough heat input and CO₂ pairs for this selection."}

    # an evenly spaced sample of the rows, so the chart is not just the first 2000 records
    step = max(1, n // limit)
    sample = (pairs.filter(f.id % step == 0).order_by(f.id).limit(limit)
              .with_entities(f.heat_input, f.co2_mass, f.facility_id).all())
    points = [{"x": _finite(x), "y": _finite(y), "facility": str(fid)} for x, y, fid in sample]

    trendline = None
    if n >= 2 and min_x != max_x:
        # least squares line from sums of deviations, using all pairs (not just the sample)
        dx, dy = f.heat_input - mean_x, f.co2_mass - mean_y
        sxy, sxx = pairs.with_entities(func.sum(dx * dy), func.sum(dx * dx)).one()
        slope = sxy / sxx
        intercept = mean_y - slope * mean_x
        xs = [float(min_x), float(max_x)]
        trendline = {"slope": _finite(slope), "intercept": _finite(intercept),
                     "x": xs, "y": [_finite(slope * x + intercept) for x in xs]}
    return {"x_label": "Heat input (mmBtu)", "y_label": "CO₂ mass (short tons)",
            "points": points, "trendline": trendline, "message": None,
            "note": "Heat input is the activity measure. The line is fitted on every record; the dots are an evenly spaced sample."}


_options_cache = {"key": None, "value": None}


def filter_options():
    """Values for the dashboard dropdowns, taken from what is actually in the database.
    Kept until the records or datasets change, since building the list scans every row."""
    key = (_data_version(), UploadedDataset.query.count())
    if _options_cache["key"] == key:
        return _options_cache["value"]
    f = FacilityRecord
    year = func.substr(f.record_date, 1, 4)
    combos = db.session.query(f.state, f.primary_fuel, year).group_by(f.state, f.primary_fuel, year).all()
    years = sorted({y for _, _, y in combos if y})
    states = sorted({s for s, _, _ in combos if s})
    fuels = sorted({fuel for _, fuel, _ in combos if fuel})
    datasets = [{"id": d.id, "label": f"#{d.id} {d.filename}"}
                for d in UploadedDataset.query.order_by(UploadedDataset.id).all()]
    facilities = [{"id": fid, "name": name or fid} for fid, name in
                  db.session.query(f.facility_id, func.max(f.facility_name))
                  .group_by(f.facility_id).order_by(f.facility_id).all()]
    value = {"years": years, "states": states, "fuels": fuels, "datasets": datasets, "facilities": facilities}
    _options_cache.update(key=key, value=value)
    return value
