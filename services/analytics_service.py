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

import numpy as np
import pandas as pd
from sqlalchemy import func, text

from impact import SHORT_TON_KG, calculate_impacts
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


def load_frame(filters=None):
    """Load the filtered records as a pandas DataFrame with one row per FacilityRecord."""
    columns = [
        FacilityRecord.id, FacilityRecord.dataset_id, FacilityRecord.facility_id,
        FacilityRecord.facility_name, FacilityRecord.state, FacilityRecord.unit_id,
        FacilityRecord.primary_fuel, FacilityRecord.co2_mass, FacilityRecord.so2_mass,
        FacilityRecord.nox_mass, FacilityRecord.heat_input, FacilityRecord.gross_load,
        FacilityRecord.record_date, FacilityRecord.data_flags,
    ]
    rows = _filtered_query(filters or {}).with_entities(*columns).all()
    frame = pd.DataFrame(rows, columns=[c.key for c in columns])
    if frame.empty:
        return frame
    frame["year"] = frame["record_date"].astype(str).str[:4]
    for field in STAT_FIELDS:
        frame[field] = pd.to_numeric(frame[field], errors="coerce")
    return frame


def describe_values(values):
    """Descriptive statistics for one numeric column. Returns a JSON-safe dict."""
    series = pd.to_numeric(pd.Series(list(values), dtype="object"), errors="coerce")
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
    result["median"] = _finite(valid.median())
    result["min"] = _finite(valid.min())
    result["max"] = _finite(valid.max())
    q1 = valid.quantile(0.25)
    q3 = valid.quantile(0.75)
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


def grouped_statistics(frame, by, field="co2_mass"):
    """Per-group count, mean, sum, and sample std dev of one field. `by` is a column name."""
    if frame.empty:
        return []
    groups = []
    for key, part in frame.groupby(by, dropna=False):
        values = part[field].dropna()
        n = int(values.shape[0])
        groups.append({
            "group": "" if pd.isna(key) else str(key),
            "record_count": int(part.shape[0]),
            "valid_count": n,
            "mean": _finite(values.mean()) if n else None,
            "sum": _finite(values.sum()) if n else None,
            "std_dev": _finite(values.std(ddof=1)) if n >= 2 else None,
        })
    groups.sort(key=lambda g: (g["sum"] is None, -(g["sum"] or 0)))
    return groups


def data_quality(frame):
    """Summarise missing and filled-in values so the dashboard can show caveats."""
    total = int(frame.shape[0])
    if total == 0:
        return {"total_records": 0, "flagged_records": 0, "legacy_all_zero_records": 0, "notes": []}
    flagged = int(frame["data_flags"].notna().sum())
    all_zero = int(((frame["co2_mass"] == 0) & (frame["so2_mass"] == 0)
                    & (frame["nox_mass"] == 0) & (frame["heat_input"] == 0)).sum())
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
    records = _filtered_query(filters or {}).all()
    result = calculate_impacts(records, db.engine)
    result["short_ton_to_kg"] = SHORT_TON_KG
    return result


def summary(filters):
    frame = load_frame(filters)
    return {
        "filters": filters,
        "statistics": descriptive_statistics(frame),
        "grouped": {
            "by_state": grouped_statistics(frame, "state"),
            "by_fuel": grouped_statistics(frame, "primary_fuel"),
            "by_year": grouped_statistics(frame, "year"),
            "by_facility": grouped_statistics(frame, "facility_id")[:25],
        },
        "data_quality": data_quality(frame),
        "traci": traci_summary(frame, filters),
    }


def emissions_over_time(filters):
    """Totals per reporting period (the record_date value). Only shows a trend when
    there is more than one period."""
    frame = load_frame(filters)
    if frame.empty:
        return {"periods": [], "trend_available": False,
                "message": "No records match these filters."}
    grouped = frame.groupby("record_date").agg(
        co2=("co2_mass", "sum"), so2=("so2_mass", "sum"), nox=("nox_mass", "sum"),
        facilities=("facility_id", "nunique"), records=("id", "count"),
    ).reset_index().sort_values("record_date")
    periods = [
        {"period": row.record_date, "co2": _finite(row.co2), "so2": _finite(row.so2),
         "nox": _finite(row.nox), "facilities": int(row.facilities), "records": int(row.records)}
        for row in grouped.itertuples()
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
    frame = load_frame(filters)
    if frame.empty:
        return {"metric": metric, "items": [], "warnings": [], "message": "No records match these filters."}

    key = "facility_id" if group_by == "facility" else "state"
    warnings = []
    if metric in ("co2_mass", "so2_mass", "nox_mass"):
        sums = frame.groupby(key)[metric].sum(min_count=1)
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
            so2 = frame.groupby(key)["so2_mass"].sum(min_count=1).fillna(0)
            nox = frame.groupby(key)["nox_mass"].sum(min_count=1).fillna(0)
            sums = (so2 * so2_factor + nox * nox_factor) * SHORT_TON_KG
        else:
            factor = factors.get(substance, {}).get(column)
            if factor is None:
                warnings.append(f"Missing {column} factor for {substance}; this ranking is empty.")
                return {"metric": metric, "items": [], "warnings": warnings, "message": None}
            sums = frame.groupby(key)[mass].sum(min_count=1) * SHORT_TON_KG * factor
    names = frame.groupby(key)["facility_name"].first() if group_by == "facility" else None
    items = []
    for group_value, total in sums.dropna().sort_values(ascending=False).head(limit).items():
        label = str(group_value)
        if names is not None and group_value in names.index and pd.notna(names.loc[group_value]):
            label = f"{names.loc[group_value]} ({group_value})"
        items.append({"label": label, "key": str(group_value), "value": _finite(total)})
    return {"metric": metric, "label": TOP_METRICS[metric]["label"],
            "unit": TOP_METRICS[metric]["unit"], "items": items, "warnings": warnings, "message": None}


def heat_vs_co2(filters, limit=2000):
    """Heat input against CO₂ for rows where both are real numbers. Gross load is not in the data yet."""
    frame = load_frame(filters)
    if frame.empty:
        return {"x_label": "Heat input (mmBtu)", "points": [], "trendline": None,
                "message": "No records match these filters."}
    part = frame.dropna(subset=["heat_input", "co2_mass"])
    part = part[part["heat_input"] > 0]
    points = [{"x": _finite(x), "y": _finite(y), "facility": str(f)}
              for x, y, f in zip(part["heat_input"], part["co2_mass"], part["facility_id"])][:limit]
    trendline = None
    if len(part) >= 2 and part["heat_input"].nunique() >= 2:
        slope, intercept = np.polyfit(part["heat_input"].astype(float), part["co2_mass"].astype(float), 1)
        xs = [float(part["heat_input"].min()), float(part["heat_input"].max())]
        trendline = {"slope": _finite(slope), "intercept": _finite(intercept),
                     "x": xs, "y": [_finite(slope * x + intercept) for x in xs]}
    message = None if points else "Not enough heat input and CO₂ pairs for this selection."
    return {"x_label": "Heat input (mmBtu)", "y_label": "CO₂ mass (short tons)",
            "points": points, "trendline": trendline, "message": message,
            "note": "Gross load is not in the EPA export used here, so heat input is the activity measure."}


def filter_options():
    """Values for the dashboard dropdowns, taken from what is actually in the database."""
    years = sorted({y for (y,) in db.session.query(func.substr(FacilityRecord.record_date, 1, 4)).distinct()
                    if y})
    states = sorted({s for (s,) in db.session.query(FacilityRecord.state).distinct() if s})
    fuels = sorted({f for (f,) in db.session.query(FacilityRecord.primary_fuel).distinct() if f})
    datasets = [{"id": d.id, "label": f"#{d.id} {d.filename}"}
                for d in UploadedDataset.query.order_by(UploadedDataset.id).all()]
    facilities = [{"id": fid, "name": name or fid} for fid, name in
                  db.session.query(FacilityRecord.facility_id, func.max(FacilityRecord.facility_name))
                  .group_by(FacilityRecord.facility_id).order_by(FacilityRecord.facility_id).all()]
    return {"years": years, "states": states, "fuels": fuels, "datasets": datasets, "facilities": facilities}
