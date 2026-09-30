import os
import importlib
try:
    pd = importlib.import_module("pandas")
except ImportError:
    pd = None
from flask import Flask, render_template, request, flash, redirect, url_for
from models import db, FacilityRecord

app = Flask(__name__)
app.secret_key = "super_secret_capstone_key"

# SQLite configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///epa_data.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# Automatically create the database tables on startup
with app.app_context():
    db.create_all()


@app.route("/")
def index():
    # Read search parameters from request.args (GET request)
    state_filter = request.args.get('state', '').strip()
    fuel_filter = request.args.get('fuel', '').strip()
    facility_query = request.args.get('facility_query', '').strip()

    # New calendar and pollutant variables
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
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
        facilities.append({
            "id": r.facility_id,
            "name": r.facility_name,
            "state": r.state,
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
                # Read the CSV with pandas
                df = pd.read_csv(file.stream)

                # Clean column headers (strip whitespace and uppercase)
                df.columns = [str(col).strip() for col in df.columns]

                # Locate target columns dynamically across CAMPD formats
                col_fac_id = next((c for c in df.columns if 'Facility ID' in c or 'ORISPL' in c), None)
                col_fac_name = next((c for c in df.columns if 'Facility Name' in c), None)
                col_state = next((c for c in df.columns if 'State' in c), None)
                col_date = next((c for c in df.columns if 'Date' in c or 'Year' in c), None)
                col_unit = next((c for c in df.columns if 'Unit ID' in c), None)
                col_fuel = next((c for c in df.columns if 'Fuel' in c), None)
                col_co2 = next((c for c in df.columns if 'CO2' in c and ('tons' in c.lower() or 'short tons' in c.lower() or 'mass' in c.lower())), None)
                col_so2 = next((c for c in df.columns if 'SO2' in c and ('tons' in c.lower() or 'mass' in c.lower())), None)
                col_nox = next((c for c in df.columns if 'NOx' in c and ('tons' in c.lower() or 'mass' in c.lower())), None)
                col_heat = next((c for c in df.columns if 'Heat Input' in c), None)

                # Clear previous entries to display newly uploaded dataset
                FacilityRecord.query.delete()

                records = []
                for _, row in df.iterrows():
                    fac_id = str(row[col_fac_id]).split('.')[0] if col_fac_id and pd.notna(row[col_fac_id]) else "Unknown"
                    fac_name = str(row[col_fac_name]) if col_fac_name and pd.notna(row[col_fac_name]) else "Unknown Facility"
                    st = str(row[col_state]) if col_state and pd.notna(row[col_state]) else ""
                    rec_date = str(row[col_date]).strip() if col_date and pd.notna(row[col_date]) else "Unknown Date"
                    unit = str(row[col_unit]) if col_unit and pd.notna(row[col_unit]) else ""
                    fuel = str(row[col_fuel]) if col_fuel and pd.notna(row[col_fuel]) else "Unknown"

                    def parse_num(val):
                        try:
                            return float(val) if pd is not None and pd.notna(val) else 0.0
                        except (ValueError, TypeError):
                            return 0.0

                    co2 = parse_num(row[col_co2]) if col_co2 else 0.0
                    so2 = parse_num(row[col_so2]) if col_so2 else 0.0
                    nox = parse_num(row[col_nox]) if col_nox else 0.0
                    heat = parse_num(row[col_heat]) if col_heat else 0.0

                    record = FacilityRecord()
                    record.facility_name = fac_name
                    record.state = st
                    record.co2_mass = co2
                    record.nox_mass = nox
                    record.heat_input = heat
                    record.record_date = rec_date
                    # Assign fields after construction for model compatibility.
                    record.facility_id = fac_id
                    record.unit_id = unit
                    record.primary_fuel = fuel
                    records.append(record)

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

    return render_template("upload.html")


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
            mock_units.append({
                "id": r.unit_id or "General",
                "type": "Boiler / Turbine",
                "fuel": r.primary_fuel or "N/A",
                "control": "Standard Monitors",
                "hours": f"{r.co2_mass:,.0f} tons CO₂"
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