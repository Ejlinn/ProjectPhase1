# epaData Explorer

A Flask and SQLite web application for ingesting, querying, inspecting, and exporting power sector emissions records collected through EPA Clean Air Markets Division (CAMPD) programs.

## Features

- **Multi-Parameter Search & Filter (`/`)**\
  Search facility emissions records by state, primary fuel, calendar date range, pollutant thresholds, facility name, or ORISPL facility ID.

- **Dataset Ingestion (`/upload`)**\
  Upload raw CAMPD `.csv` files with dynamic column matching and automated ingestion into SQLite using Pandas.

- **CSV Export (`/export`)**\
  Generate and download structured CSV files containing records that match the current database query.

- **Facility Details (`/facility/<id>`)**\
  View facility information, location, regulatory context, and unit-level emissions data.

- **Interactive Guided Tutorial**\
  Use the **Start Tutorial** option in the navigation bar to walk through the application's major controls and features.

- **Contextual Tooltips**\
  Hover over search controls, date fields, table actions, and file inputs to view additional guidance.

## Tech Stack

- **Backend:** Python 3.11, Flask
- **Database:** SQLite
- **ORM:** Flask-SQLAlchemy
- **Data Processing:** Pandas
- **Frontend:** Jinja2, Bootstrap 5, Intro.js

## Project Structure

```text
├── app.py                  # Flask routes, filtering, CSV ingestion, and export
├── models.py               # SQLAlchemy database models
├── requirements.txt        # Python package dependencies
├── README.md               # Project documentation
├── run_app.bat             # Windows startup script
├── run_app.sh              # macOS/Linux startup script
└── templates/
    ├── base.html           # Main layout, navigation, tutorial, and tooltips
    ├── search.html         # Search filters, results table, and export controls
    ├── upload.html         # CSV upload and validation interface
    └── detail.html         # Facility and unit-level details
```

## Database Schema

The SQLite database stores CAMPD unit-level records in the `facility_records` table.

| Column Name     | Type        | Description                                              |
| :-------------- | :---------- | :------------------------------------------------------- |
| `id`            | Integer     | Primary key                                              |
| `facility_id`   | String(50)  | EPA ORISPL facility identifier                           |
| `facility_name` | String(255) | Name of the generating station                           |
| `state`         | String(10)  | Two-letter state postal code                             |
| `unit_id`       | String(50)  | Boiler or smokestack unit ID                             |
| `primary_fuel`  | String(100) | Primary fuel burned, such as coal, natural gas, or oil   |
| `co2_mass`      | Float       | Carbon dioxide emissions in short tons                   |
| `so2_mass`      | Float       | Sulfur dioxide emissions in short tons                   |
| `nox_mass`      | Float       | Nitrogen oxides emissions in short tons                  |
| `heat_input`    | Float       | Total heat input in mmBtu                                |
| `record_date`   | String(20)  | Operating date or collection year from CAMPD source data |

## Installation & Setup

### 1. Open the Project

Open a terminal in the project root directory:

```bash
cd "CS396 EPA Project"
```

### 2. Quickstart

The project includes scripts that create the virtual environment, install dependencies, and launch the application.

#### Windows

Double-click `run_app.bat` or run:

```bat
run_app.bat
```

#### macOS / Linux

Run:

```bash
chmod +x run_app.sh
./run_app.sh
```

### 3. Manual Setup

Create and activate a virtual environment.

#### Windows

```bat
python -m venv venv
venv\Scripts\activate
```

#### macOS / Linux

```bash
python3 -m venv venv
source venv/bin/activate
```

Install the required packages:

```bash
pip install -r requirements.txt
```

Start the application:

```bash
python app.py
```

The application will be available at:

`http://127.0.0.1:5000/`

> **Windows Debugging Note:** When running the application through VS Code or the Windows terminal, configure `app.run(debug=True, use_reloader=False)` to prevent socket descriptor collisions caused by process restarts.

## Usage Guide

### System Tour

Select **Start Tutorial** in the top navigation bar to launch the interactive walkthrough.

### Uploading Data

1. Navigate to `/upload`.
2. Select a `.csv` file downloaded from the EPA CAMPD portal.
3. Select **Validate & Ingest File**.
4. The application matches the available columns and loads the records into the SQLite database.

### Filtering Records

Use the search page to filter records by:

- State
- Primary fuel
- Start and end dates
- CO₂ threshold
- SO₂ threshold
- NOₓ threshold
- Facility name
- ORISPL facility ID

Select **Apply Filters** to update the results.

### Inspecting Facilities

Select **Details** next to a record to view facility information and unit-level emissions data.

### Exporting Data

Select **Export CSV** in the results header to download the records matching the current query.

## Data Source

The application is designed to work with emissions data obtained from the U.S. Environmental Protection Agency's Clean Air Markets Division (CAMPD) data portal.
