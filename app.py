import os
import importlib
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


@app.route("/")
def index():
    # Read search parameters from request.args (GET request)
    state_filter = request.args.get('state', '').strip()
    fuel_filter = request.args.get('fuel', '').strip()
    facility_query = request.args.get('facility_query', '').strip()

    # New calendar, time, and pollutant variables
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    start_hour = request.args.get('start_hour', '').strip()
    end_hour = request.args.get('end_hour', '').strip()
    pollutant_type = request.args.get('pollutant_type', 'co2').strip()
    min_emissions = request.args.get('min_emissions', '').strip()
    

    # Query the SQLite database
    query = FacilityRecord.query

    if state_filter:
        query = query.filter(FacilityRecord.state == state_filter)
    if fuel_filter:
        query = query.filter(FacilityRecord.primary_fuel.ilike(f"%{fuel_filter}%"))
    if start_date:
        query = query.filter(FacilityRecord.record_date >= start_date)
    if end_date:
        query = query.filter(FacilityRecord.record_date <= end_date)
    if start_hour:
        try:
            query = query.filter(FacilityRecord.record_hour >= int(start_hour))
        except ValueError:
            pass
    if end_hour:
        try:
            query = query.filter(FacilityRecord.record_hour <= int(end_hour))
        except ValueError:
            pass

    if min_emissions:
        try:
            threshold = float(min_emissions)
            if pollutant_type == 'co2':
                query = query.filter(FacilityRecord.co2_mass >= threshold)
            elif pollutant_type == 'so2':
                query = query.filter(FacilityRecord.so2_mass >= threshold)
            elif pollutant_type == 'nox':
                query = query.filter(FacilityRecord.nox_mass >= threshold)
        except ValueError:
            pass
    if facility_query:
        query = query.filter(
            (FacilityRecord.facility_name.ilike(f"%{facility_query}%")) |
            (FacilityRecord.facility_id.ilike(f"%{facility_query}%"))
        )

    db_rows = query.all()

    # Convert database rows to the dictionary format expected by search.html
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
            "co2": f"{r.co2_mass:,.2f}" if r.co2_mass else "0.00"
        })
    return render_template("search.html", facilities=facilities)


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
    # Query all records currently in SQLite
    records = FacilityRecord.query.all()
    
    # Create an in-memory text buffer
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write the CSV column headers
    writer.writerow([
        "Facility ID", "Facility Name", "State", "Unit ID", 
        "Primary Fuel", "CO2 Mass (Tons)", "SO2 Mass (Tons)", 
        "NOx Mass (Tons)", "Heat Input (mmBtu)"
    ])
    
    # Write the rows from the database
    for r in records:
        writer.writerow([
            r.facility_id, r.facility_name, r.state, r.unit_id,
            r.primary_fuel, r.co2_mass, r.so2_mass, r.nox_mass, r.heat_input
        ])
    
    output.seek(0)
    
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=epa_emissions_export.csv"}
    )

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)