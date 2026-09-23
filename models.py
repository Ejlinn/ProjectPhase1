# Import the SQLAlchemy tool from the Flask library
from flask_sqlalchemy import SQLAlchemy

# Create a database object that we will use to build our tables
db = SQLAlchemy()

# Define a new blueprint class called Facility which represents a database table
class Facility(db.Model):
    # Name the actual table 'facilities' inside the database
    __tablename__ = 'facilities'
    
    # Create a column for an ID number that acts as the primary unique key.
    id = db.Column(db.Integer, primary_key=True)
    
    # Create a column for the EPA facility ID as a short string of text
    epa_facility_id = db.Column(db.String(50), nullable=False)
    
    # Create a column for the full name of the facility
    facility_name = db.Column(db.String(200))
    
    # Create a column for the state abbreviation using a two-letter string
    state = db.Column(db.String(2))