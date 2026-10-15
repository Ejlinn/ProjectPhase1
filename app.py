import os
import json
import re
import time
from typing import Any, cast
from dotenv import load_dotenv
load_dotenv()
import requests
import importlib
from google import genai
from google.genai import types

try:
    pd = importlib.import_module("pandas")
except ImportError:
    pd = None
from datetime import datetime
from flask import Flask, render_template, request, flash, redirect, url_for
from models import db, FacilityRecord, UploadedDataset

app = Flask(__name__)
app.secret_key = "super_secret_capstone_key"

# SQLite configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///epa_data.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# Automatically create or update the database tables on startup
from sqlalchemy import inspect, text

with app.app_context():
    db.create_all()
    inspector = inspect(db.engine)
    if inspector.has_table("facility_records"):
        columns = [col["name"] for col in inspector.get_columns("facility_records")]
        if "dataset_id" not in columns or "record_hour" not in columns:
            db.drop_all()
            db.create_all()


# Primary model first, then fallbacks if it is overloaded (503) or rate limited (429).
# Override the primary with GEMINI_MODEL in .env.
GEMINI_MODELS = [
    os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"),
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
VALID_STATES = set(US_STATES)
# Longest names first so "west virginia" is tried before "virginia"
STATE_NAMES = dict(sorted(((n.lower(), c) for c, n in US_STATES.items()),
                          key=lambda kv: -len(kv[0])))


@app.context_processor
def inject_helpers():
    """Template helpers: the state list, and url_with() to rebuild the current URL with changes
    (used for sort links and pagination so filters are never lost)."""
    def url_with(**overrides):
        args = {k: v for k, v in request.args.items() if v != ""}
        for key, value in overrides.items():
            if value is None:
                args.pop(key, None)
            else:
                args[key] = value
        return url_for("index", **cast(Any, args))
    return {"us_states": US_STATES, "url_with": url_with}


def _to_number(text):
    """Turn '50k', '50,000', '1.5 million' into a float. Returns None if unparseable."""
    if text is None:
        return None
    s = str(text).lower().replace(",", "").strip()
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(k|thousand|m|million|b|billion)?", s)
    if not m:
        return None
    value = float(m.group(1))
    mult = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6,
            "b": 1e9, "billion": 1e9}.get(m.group(2), 1)
    return value * mult


def parse_with_gemini(natural_query):
    """Ask Gemini for filters. Retries and falls back across models on 503/429.
    Returns (filters_dict, model_used) or raises the last error."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured.")

    client = genai.Client(api_key=api_key)
    prompt = f"""
You convert a user's question about an EPA power-plant emissions database into search filters.
User query: "{natural_query}"

Return ONLY a JSON object with exactly these keys:
  "state": two-letter US state postal code (e.g. KY, TX, OH) or "" if not specified
  "fuel": one of "Coal", "Pipeline Natural Gas", "Diesel Oil", or "" if not specified
  "min_co2": minimum CO2 in short tons as a plain number string (e.g. "50000"), or ""
  "facility_query": a facility name or ID mentioned by the user, or ""
Interpret vague words like "high" or "large" CO2 as "500000". "natural gas" means "Pipeline Natural Gas".
"""
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=0,
    )

    last_error = None
    for model in GEMINI_MODELS:
        for attempt in range(2):  # 1 retry per model
            try:
                response = client.models.generate_content(
                    model=model, contents=prompt, config=config
                )
                raw = (response.text or "").strip()
                raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
                return json.loads(raw), model
            except Exception as exc:
                last_error = exc
                msg = str(exc)
                transient = any(code in msg for code in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED"))
                if not transient:
                    # Bad key, bad model name, or malformed JSON: no point retrying this model
                    break
                time.sleep(1.5 * (attempt + 1))
    if last_error is not None:
        raise last_error
    raise RuntimeError("No Gemini models are configured")


def parse_with_rules(natural_query):
    """Offline keyword parser used only when Gemini is unreachable."""
    q = natural_query.lower()
    filters = {"state": "", "fuel": "", "min_co2": "", "facility_query": ""}

    for name, code in STATE_NAMES.items():
        if re.search(rf"\b{re.escape(name)}\b", q):
            filters["state"] = code
            break
    if not filters["state"]:
        # Only accept ALL-CAPS codes (KY, TX) so words like "in", "or", "me" aren't mistaken for states
        for token in re.findall(r"\b[A-Z]{2}\b", natural_query):
            if token in VALID_STATES:
                filters["state"] = token
                break

    if "coal" in q:
        filters["fuel"] = "Coal"
    elif "gas" in q:
        filters["fuel"] = "Pipeline Natural Gas"
    elif "diesel" in q or " oil" in q:
        filters["fuel"] = "Diesel Oil"

    m = re.search(
        r"(?:over|above|greater than|more than|exceeding|at least|>)\s*([\d.,]+\s*(?:k|thousand|million|m)?)",
        q,
    )
    if m:
        num = _to_number(m.group(1))
        if num:
            filters["min_co2"] = str(int(num))
    elif re.search(r"\b(high|large|big)\b", q):
        filters["min_co2"] = "500000"

    return filters


def clean_filters(raw):
    """Validate whatever the AI (or fallback parser) returned before it touches the DB."""
    raw = raw if isinstance(raw, dict) else {}
    state = str(raw.get("state", "") or "").strip().upper()
    fuel = str(raw.get("fuel", "") or "").strip()
    facility = str(raw.get("facility_query", "") or "").strip()
    min_co2 = _to_number(raw.get("min_co2"))
    return {
        "state": state if state in VALID_STATES else "",
        "fuel": fuel,
        "min_co2": min_co2,
        "facility_query": facility,
    }


def build_facility_rows(db_rows):
    facilities = []
    for r in db_rows:
        date_str = r.record_date or "N/A"
        hour_str = f" {r.record_hour:02d}:00" if r.record_hour is not None else ""
        facilities.append({
            "id": r.facility_id,
            "name": r.facility_name,
            "state": r.state,
            "date_time": f"{date_str}{hour_str}",
            "fuel": r.primary_fuel or "N/A",
            "co2": f"{r.co2_mass:,.2f}" if r.co2_mass else "0.00",
        })
    return facilities


@app.route("/semantic_search", methods=["GET", "POST"])
def semantic_search():
    natural_query = request.args.get("prompt", "").strip()
    if not natural_query:
        flash("Type a question for the AI search first.", "warning")
        return redirect(url_for("index"))

    # 1) Translate the sentence into filters (AI first, rules as a safety net)
    try:
        raw_filters, model_used = parse_with_gemini(natural_query)
        source = f"Gemini ({model_used})"
    except Exception as exc:
        app.logger.warning("Gemini semantic search failed: %s", exc)
        raw_filters = parse_with_rules(natural_query)
        source = "keyword fallback"
        flash("The AI service is busy right now, so a basic keyword parser was used instead. "
              "Try again in a minute for full AI interpretation.", "warning")

    f = clean_filters(raw_filters)

    # 2) Hand the filters to the normal results page so sorting, pagination and CSV export all work
    params = {"ai_prompt": natural_query}
    if f["state"]:
        params["state"] = f["state"]
    if f["fuel"]:
        params["fuel"] = f["fuel"]
    if f["min_co2"] is not None:
        params["pollutant_type"] = "co2"
        params["min_emissions"] = str(int(f["min_co2"]))
    if f["facility_query"]:
        params["facility_query"] = f["facility_query"]

    # 3) Tell the user how their sentence was interpreted
    applied = [
        f"State = {f['state']}" if f["state"] else None,
        f"Fuel = {f['fuel']}" if f["fuel"] else None,
        f"CO₂ ≥ {f['min_co2']:,.0f} tons" if f["min_co2"] is not None else None,
        f"Facility contains '{f['facility_query']}'" if f["facility_query"] else None,
    ]
    applied = [a for a in applied if a] or ["no filters recognized (showing everything)"]
    flash(f"Interpreted via {source}: " + "; ".join(applied), "info")

    return redirect(url_for("index", **params))  # type: ignore[arg-type]


SORT_COLUMNS = {
    "id": FacilityRecord.facility_id,
    "name": FacilityRecord.facility_name,
    "state": FacilityRecord.state,
    "date": FacilityRecord.record_date,
    "fuel": FacilityRecord.primary_fuel,
    "co2": FacilityRecord.co2_mass,
}
POLLUTANT_COLUMNS = {
    "co2": FacilityRecord.co2_mass,
    "so2": FacilityRecord.so2_mass,
    "nox": FacilityRecord.nox_mass,
}
PER_PAGE = 25


def _float_or_none(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def apply_filters(query, args):
    """Single source of truth for every search filter. Used by the results page AND the CSV export,
    so an export always matches what is on screen."""
    state = args.get("state", "").strip().upper()
    fuel = args.get("fuel", "").strip()
    year = args.get("year", "").strip()
    unit_id = args.get("unit_id", "").strip()
    facility_query = args.get("facility_query", "").strip()
    start_date = args.get("start_date", "").strip()
    end_date = args.get("end_date", "").strip()
    start_hour = args.get("start_hour", "").strip()
    end_hour = args.get("end_hour", "").strip()
    pollutant_col = POLLUTANT_COLUMNS.get(args.get("pollutant_type", "co2").strip(), FacilityRecord.co2_mass)
    min_emissions = _float_or_none(args.get("min_emissions", ""))
    max_emissions = _float_or_none(args.get("max_emissions", ""))

    if state:
        query = query.filter(FacilityRecord.state == state)
    if fuel:
        query = query.filter(FacilityRecord.primary_fuel.ilike(f"%{fuel}%"))
    if year.isdigit():
        query = query.filter(FacilityRecord.record_date.like(f"{year}%"))
    if unit_id:
        query = query.filter(FacilityRecord.unit_id.ilike(f"%{unit_id}%"))
    if start_date:
        query = query.filter(FacilityRecord.record_date >= start_date)
    if end_date:
        query = query.filter(FacilityRecord.record_date <= end_date)
    if start_hour.isdigit():
        query = query.filter(FacilityRecord.record_hour >= int(start_hour))
    if end_hour.isdigit():
        query = query.filter(FacilityRecord.record_hour <= int(end_hour))
    if min_emissions is not None:
        query = query.filter(pollutant_col >= min_emissions)
    if max_emissions is not None:
        query = query.filter(pollutant_col <= max_emissions)
    if facility_query:
        query = query.filter(
            (FacilityRecord.facility_name.ilike(f"%{facility_query}%")) |
            (FacilityRecord.facility_id.ilike(f"%{facility_query}%"))
        )
    return query


@app.route("/")
def index():
    args = request.args
    query = apply_filters(FacilityRecord.query, args)

    # Server-side sorting (so it works across ALL pages, not just the visible one)
    sort = args.get("sort", "")
    sort_dir = "desc" if args.get("dir") == "desc" else "asc"
    if sort in SORT_COLUMNS:
        col = SORT_COLUMNS[sort]
        query = query.order_by(col.desc() if sort_dir == "desc" else col.asc(), FacilityRecord.id)
    else:
        sort = ""
        query = query.order_by(FacilityRecord.id)

    page = args.get("page", 1, type=int)
    pagination = query.paginate(page=page, per_page=PER_PAGE, error_out=False)

    # Reporting years present in the database, for the Year dropdown
    years = sorted(
        {y for (y,) in db.session.query(db.func.substr(FacilityRecord.record_date, 1, 4)).distinct()
         if y and y.isdigit()},
        reverse=True,
    )

    return render_template(
        "search.html",
        facilities=build_facility_rows(pagination.items),
        pagination=pagination,
        sort=sort,
        sort_dir=sort_dir,
        years=years,
        filters=args.to_dict(),
        semantic_prompt=args.get("ai_prompt", ""),
    )


@app.route("/upload", methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        if pd is None:
            flash("CSV uploads require pandas. Install it with 'pip install pandas'.", "danger")
            return redirect(request.url)

        if 'campd_file' not in request.files:
            flash("No file part found in the submission.", "danger")
            return redirect(request.url)
            
        file = request.files['campd_file']
        if file.filename == '':
            flash("No file selected. Please select a .csv file.", "warning")
            return redirect(request.url)

        if file and file.filename and file.filename.lower().endswith('.csv'):
            try:
                # Reset file stream pointer to the beginning
                file.stream.seek(0)
                df = pd.read_csv(file.stream)

                if df.empty:
                    flash("The uploaded CSV file is empty.", "warning")
                    return redirect(request.url)

                # Clean column headers (strip whitespace)
                df.columns = [str(col).strip() for col in df.columns]
                cols_lower = {col.lower(): col for col in df.columns}

                def find_col(keywords):
                    for kw in keywords:
                        for col_l, original_col in cols_lower.items():
                            if kw in col_l:
                                return original_col
                    return None

                # Flexible column matching across all CAMPD formats
                col_fac_id = find_col(['facility id', 'orispl', 'plant id'])
                col_fac_name = find_col(['facility name', 'plant name'])
                col_state = find_col(['state'])
                col_unit = find_col(['unit id', 'generator', 'boiler'])
                col_fuel = find_col(['primary fuel', 'fuel type', 'fuel'])
                col_co2 = find_col(['co2', 'carbon dioxide'])
                col_so2 = find_col(['so2', 'sulfur dioxide'])
                col_nox = find_col(['nox', 'nitrogen oxides', 'no x'])
                col_heat = find_col(['heat input'])
                col_date = find_col(['date', 'year'])
                col_hour = find_col(['hour'])

                note_text = request.form.get('dataset_note', '').strip()
                timestamp_str = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
                
                new_dataset = UploadedDataset()
                new_dataset.filename = file.filename
                new_dataset.notes = note_text or "No description provided"
                new_dataset.upload_time = timestamp_str
                new_dataset.row_count = len(df)
                db.session.add(new_dataset)
                db.session.flush()

                records = []
                for _, row in df.iterrows():
                    # Fallback defaults if columns are missing
                    fac_id = str(row[col_fac_id]).split('.')[0] if col_fac_id and pd.notna(row[col_fac_id]) else "1353"
                    fac_name = str(row[col_fac_name]) if col_fac_name and pd.notna(row[col_fac_name]) else "Generating Facility"
                    st = str(row[col_state]) if col_state and pd.notna(row[col_state]) else "KY"
                    unit = str(row[col_unit]) if col_unit and pd.notna(row[col_unit]) else "1"
                    fuel = str(row[col_fuel]) if col_fuel and pd.notna(row[col_fuel]) else "Coal"

                    def parse_num(val):
                        try:
                            # Remove commas if numbers are formatted as strings like "8,450,120"
                            if isinstance(val, str):
                                val = val.replace(',', '')
                            return float(val) if pd is not None and pd.notna(val) else 0.0
                        except (ValueError, TypeError):
                            return 0.0

                    co2 = parse_num(row[col_co2]) if col_co2 else 0.0
                    so2 = parse_num(row[col_so2]) if col_so2 else 0.0
                    nox = parse_num(row[col_nox]) if col_nox else 0.0
                    heat = parse_num(row[col_heat]) if col_heat else 0.0

                    rec_date = "2024"
                    if col_date and pd.notna(row[col_date]):
                        rec_date = str(row[col_date]).strip()

                    rec_hour = None
                    if col_hour and pd.notna(row[col_hour]):
                        try:
                            hr_val = int(float(row[col_hour]))
                            if 0 <= hr_val <= 23:
                                rec_hour = hr_val
                        except (ValueError, TypeError):
                            pass

                    record = FacilityRecord()
                    record.facility_name = fac_name
                    record.state = st
                    record.co2_mass = co2
                    record.so2_mass = so2
                    record.nox_mass = nox
                    record.heat_input = heat
                    record.facility_id = fac_id
                    record.unit_id = unit
                    record.primary_fuel = fuel
                    record.record_date = rec_date
                    record.record_hour = rec_hour
                    record.dataset_id = new_dataset.id
                    records.append(record)

                if not records:
                    db.session.rollback()
                    flash("Parsed 0 valid facility records from the CSV. Please check column headers.", "danger")
                    return redirect(request.url)

                db.session.bulk_save_objects(records)
                db.session.commit()

                flash(f"Successfully ingested {len(records)} records into SQLite!", "success")
                return redirect(url_for('index'))

            except Exception as e:
                db.session.rollback()
                flash(f"Error parsing file: {str(e)}", "danger")
                return redirect(request.url)
        else:
            flash("Invalid format. Please upload a .csv file.", "warning")
            return redirect(request.url)

    datasets = UploadedDataset.query.order_by(UploadedDataset.id.desc()).all()
    return render_template("upload.html", datasets=datasets)

@app.route("/delete_dataset/<int:dataset_id>", methods=['POST'])
def delete_dataset(dataset_id):
    dataset = UploadedDataset.query.get_or_404(dataset_id)
    
    # Delete all emission records tied to this specific upload
    FacilityRecord.query.filter_by(dataset_id=dataset_id).delete()
    
    # Delete the dataset log itself
    db.session.delete(dataset)
    db.session.commit()
    
    flash(f"Deleted dataset '{dataset.filename}' and its records from SQLite.", "info")
    return redirect(url_for('upload'))


@app.route("/facility/<facility_id>")
def detail(facility_id):
    records = FacilityRecord.query.filter_by(facility_id=facility_id).all()
    
    mock_units = []
    fac_name = "Facility View"
    fac_state = ""
    
    if records:
        fac_name = records[0].facility_name
        fac_state = records[0].state
        for r in records:
            date_str = r.record_date or "N/A"
            hour_str = f" {r.record_hour:02d}:00" if r.record_hour is not None else ""
            mock_units.append({
                "id": r.unit_id or "General",
                "date_time": f"{date_str}{hour_str}",
                "type": "Boiler / Turbine",
                "fuel": r.primary_fuel or "N/A",
                "control": "Standard Monitors",
                "hours": f"{r.co2_mass:,.2f} tons CO₂"
            })
            
    return render_template("detail.html", facility_id=facility_id, facility_name=fac_name, state=fac_state, units=mock_units)

import csv
import io
from flask import Response

@app.route("/export")
def export():
    # Same filters as the results page, so the download matches what the user is looking at
    records = apply_filters(FacilityRecord.query, request.args).order_by(FacilityRecord.id).all()
    
    # Create an in-memory text buffer
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write the CSV column headers
    writer.writerow([
        "Facility ID", "Facility Name", "State", "Unit ID", 
        "Primary Fuel", "CO2 Mass (Tons)", "SO2 Mass (Tons)", 
        "NOx Mass (Tons)", "Heat Input (mmBtu)", "Date", "Hour"
    ])
    
    # Write the rows from the database
    for r in records:
        writer.writerow([
            r.facility_id, r.facility_name, r.state, r.unit_id,
            r.primary_fuel, r.co2_mass, r.so2_mass, r.nox_mass, r.heat_input,
            r.record_date, r.record_hour
        ])
    
    output.seek(0)
    
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=epa_emissions_export.csv"}
    )

@app.route("/fetch_live_api", methods=['POST'])
def fetch_live_api():
    state_code = request.form.get("state", "KY").strip().upper()
    if state_code not in VALID_STATES:
        state_code = "KY"
    year = request.form.get("year", "2024").strip()
    if not (year.isdigit() and 1995 <= int(year) <= datetime.now().year):
        year = "2024"
    api_url = ("https://api.epa.gov/easey/streaming-services/emissions/apportioned/annual"
               f"?year={year}&stateCode={state_code}")
    
    # EPA key comes from the server-side .env file (never hardcode it)
    EPA_API_KEY = os.environ.get("EPA_API_KEY")
    if not EPA_API_KEY:
        flash("EPA_API_KEY is not configured in .env.", "danger")
        return redirect(url_for("upload"))

    headers = {
        "x-api-key": EPA_API_KEY,
        "Accept": "application/json"
    }
    
    try:
        response = requests.get(api_url, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            
            timestamp_str = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
            
            # Safe property assignment to avoid constructor warnings
            new_dataset = UploadedDataset()
            new_dataset.filename = f"EPA_Live_API_Stream_{state_code}_{year}.json"
            new_dataset.notes = "Fetched live from EPA CAMPD REST API"
            new_dataset.upload_time = timestamp_str
            new_dataset.row_count = len(data)
            
            db.session.add(new_dataset)
            db.session.flush()
            
            records = []
            for item in data:
                record = FacilityRecord()
                record.facility_name = item.get('facilityName', 'Unknown Facility')
                record.state = item.get('stateCode', state_code)
                record.co2_mass = float(item.get('co2Mass', 0.0) or 0.0)
                record.so2_mass = float(item.get('so2Mass', 0.0) or 0.0)
                record.nox_mass = float(item.get('noxMass', 0.0) or 0.0)
                record.heat_input = float(item.get('heatInput', 0.0) or 0.0)
                record.facility_id = str(item.get('facilityId', '1353'))
                record.unit_id = str(item.get('unitId', '1'))
                record.primary_fuel = item.get('fuelType', 'Coal')
                record.record_date = str(item.get('year', '2024'))
                record.dataset_id = new_dataset.id
                records.append(record)
                
            db.session.bulk_save_objects(records)
            db.session.commit()
            flash(f"Successfully pulled {len(records)} records from the live EPA API.", "success")
        else:
            flash(f"Failed to reach EPA API. Status code: {response.status_code}", "danger")
    except Exception as e:
        db.session.rollback()
        flash(f"API connection error: {str(e)}", "danger")
        
    return redirect(url_for('upload'))

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)