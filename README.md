# epaData Explorer (Phase 1)

A Flask and SQLite web application designed to ingest, query, inspect, and export power sector emissions records collected under EPA Clean Air Markets Division (CAMPD) programs[cite: 1, 2, 8].

---

## Features

* **Multi-Parameter Search & Filter (`/`)**: Query facility emissions records by state, primary fuel category, calendar date periods (start and end date), multi-pollutant threshold levels (CO₂, SO₂, or NOₓ in tons), or direct keyword search by facility name and ORISPL ID.
* **Dataset Ingestion Pipeline (`/upload`)**: File submission portal supporting raw CAMPD `.csv` spreadsheets with dynamic column matching and automated ingestion directly into SQLite via pandas.
* **CSV Export Utility (`/export`)**: Direct streaming endpoint generating clean, structured CSV downloads of database records matching current user queries.
* **Facility Details View (`/facility/<id>`)**: Drill-down inspection screen displaying plant identifiers, location, regulatory program context, and unit-by-unit smokestack emissions breakdowns[cite: 2, 15].
* **Interactive Guided Tutorial**: Step-by-step Intro.js walkthrough initiated from the navigation bar, structured with background click protection so users can follow the workflow without accidental exits[cite: 2].
* **Contextual Tooltips**: Bootstrap hover tooltips attached across all search controls, calendar inputs, table actions, and file inputs to assist navigation[cite: 2].

---

## Tech Stack

* **Backend**: Python 3.11, Flask
* **Database & ORM**: SQLite, Flask-SQLAlchemy[cite: 8, 15]
* **Data Processing**: Pandas
* **Front End**: Jinja2 Templates, Bootstrap 5, Intro.js[cite: 2]

---

## Project Structure

```text
├── app.py                  # Flask routing, query filtering, CSV ingestion, and export endpoint
├── models.py               # SQLAlchemy schema definitions for FacilityRecord
├── requirements.txt        # Package dependencies
├── README.md               # Setup and architecture documentation
├── run_app.bat             # Automated Windows launch and virtual environment setup script
├── run_app.sh              # Automated Unix/macOS launch script
└── templates/
    ├── base.html           # Master layout containing navigation, Intro.js scripts, and tooltips
    ├── search.html         # Filter controls, calendar selectors, results table, and export button
    ├── upload.html         # Ingestion form with validation alerts[cite: 4]
    └── detail.html         # Plant metadata and monitored unit breakdowns[cite: 2]
