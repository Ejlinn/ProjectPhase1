# epaData Explorer (Phase 1)

A Flask and SQLite web application designed to query, inspect, and ingest power sector emissions records collected under EPA Clean Air Markets Division (CAMPD) programs.

---

## Features

* **Emissions Search & Filter Grid (`/`)**: Query facilities by state, primary fuel category, minimum CO₂ emission thresholds, or direct facility name and EPA ORISPL ID.
* **Dataset Ingestion (`/upload`)**: Manual file submission portal accepting CAMPD raw `.csv` and `.xlsx` files with validation warnings and status flash notifications.
* **Facility Details (`/facility/<id>`)**: Drill-down inspection view showing facility coordinates, regulatory program status, and individual monitored generating units (smokestacks).
* **Interactive Walkthrough**: Built-in Intro.js tutorial accessible from the top navigation bar to guide users sequentially through filtering, uploading, and data inspection.
* **Contextual Tooltips**: Bootstrap hover tooltips on inputs, buttons, and navigation elements explaining system controls and expected data formats.

---

## Tech Stack

* **Backend**: Python, Flask
* **Database & ORM**: SQLite, Flask-SQLAlchemy
* **Data Processing**: Pandas
* **Front End**: Jinja2 Templates, Bootstrap 5, Intro.js

---

## Project Structure

```text
├── app.py                  # Application routing, form processing, and session management
├── models.py               # SQLAlchemy database schema and table definitions
├── requirements.txt        # Python package dependencies
├── README.md               # Documentation and execution instructions
└── templates/
    ├── base.html           # Master layout with navigation, Intro.js scripts, and tooltips
    ├── search.html         # Data grid, filter sidebar, and CSV export control
    ├── upload.html         # Dataset submission form and flash alert handling
    └── detail.html         # Facility metadata card and unit breakdown table
