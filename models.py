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
    co2_mass = db.Column(db.Float, default=0.0)
    so2_mass = db.Column(db.Float, default=0.0)
    nox_mass = db.Column(db.Float, default=0.0)
    heat_input = db.Column(db.Float, default=0.0)
    record_date = db.Column(db.String(20))
    record_hour = db.Column(db.Integer, nullable=True)