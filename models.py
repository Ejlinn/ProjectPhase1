# Import the SQLAlchemy tool from the Flask library
from flask_sqlalchemy import SQLAlchemy

# Create a database object that we will use to build our tables
db = SQLAlchemy()

class UploadedDataset(db.Model):
    __tablename__ = 'uploaded_datasets'
    
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    notes = db.Column(db.String(500))
    upload_time = db.Column(db.String(50), nullable=False)
    row_count = db.Column(db.Integer, default=0)

class FacilityRecord(db.Model):
    __tablename__ = 'facility_records'
    
    id = db.Column(db.Integer, primary_key=True)
    dataset_id = db.Column(db.Integer, db.ForeignKey('uploaded_datasets.id'), nullable=True)
    facility_id = db.Column(db.String(50), nullable=False)
    facility_name = db.Column(db.String(255))
    state = db.Column(db.String(10))
    unit_id = db.Column(db.String(50))
    primary_fuel = db.Column(db.String(100))
    # No default=0.0 here: a missing value must be stored as NULL, not silently as zero.
    co2_mass = db.Column(db.Float, nullable=True)
    so2_mass = db.Column(db.Float, nullable=True)
    nox_mass = db.Column(db.Float, nullable=True)
    heat_input = db.Column(db.Float, nullable=True)
    record_date = db.Column(db.String(20))
    record_hour = db.Column(db.Integer, nullable=True)
    # Added in Phase 2. The EPA exports we have so far do not include gross load,
    # so this stays empty unless a future file provides it.
    gross_load = db.Column(db.Float, nullable=True)
    # Notes on which values were missing or filled with a default during upload,
    # e.g. "missing:co2_mass;defaulted:state". Legacy rows have no flags.
    data_flags = db.Column(db.String(255), nullable=True)


class ModelRun(db.Model):
    """One row per training run of the CO2 predictor. Metrics live here so the
    dashboard can show them without retraining."""
    __tablename__ = 'model_runs'

    id = db.Column(db.Integer, primary_key=True)
    trained_at = db.Column(db.String(30), nullable=False)
    selected_model = db.Column(db.String(60), nullable=False)
    target = db.Column(db.String(60), nullable=False)
    target_units = db.Column(db.String(60), nullable=False)
    split_method = db.Column(db.String(255), nullable=False)
    train_rows = db.Column(db.Integer, nullable=False)
    test_rows = db.Column(db.Integer, nullable=False)
    feature_names = db.Column(db.Text, nullable=False)   # JSON list
    metrics_json = db.Column(db.Text, nullable=False)    # JSON: per-model test and CV metrics
    predictions_json = db.Column(db.Text, nullable=True)  # JSON: actual vs predicted on test rows
    notes = db.Column(db.Text, nullable=True)
    artifact_path = db.Column(db.String(255), nullable=True)