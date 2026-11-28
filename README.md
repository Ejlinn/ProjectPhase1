# epaData Explorer

A Flask and SQLite web application for ingesting, querying, inspecting, and exporting power sector emissions records collected through EPA Clean Air Markets Division (CAMPD) programs, featuring live API integration and Gemini-powered semantic search.

## Features

- **Multi-Parameter Search & Filter (`/`)**  
  Search facility emissions records by state, primary fuel, calendar date range, specific hours, pollutant thresholds, facility name, or ORISPL facility ID.

- **AI Semantic Search (`/semantic_search`)**  
  Enter natural language prompts (e.g., "Find coal plants in Kentucky emitting over 50k tons of CO2") to have Gemini dynamically translate user intent into database filters.

- **Dataset Ingestion & Management (`/upload`)**  
  Upload raw CAMPD `.csv` files with dynamic column matching, view dataset upload history (including timestamps and row counts), and delete specific datasets.

- **Live EPA API Integration (`/fetch_live_api`)**  
  Fetch current power sector emissions records directly from the live EPA CAMPD web service using secure API key headers.

- **Interactive Table Sorting**  
  Click any column header to toggle between ascending, descending, and neutral sorting with dynamic arrow indicators.

- **CSV Export (`/export`)**  
  Generate and download structured CSV files containing records that match the current database query.

- **Facility Details (`/facility/<id>`)**  
  View facility information, location, regulatory context, and unit-level emissions data.

- **Interactive Guided Tutorial & Tooltips**  
  Use the **Start Tutorial** option in the navigation bar to walk through application controls, supported by contextual Bootstrap tooltips.

### Phase 2: Data Analytics (`/dashboard`)

- **Descriptive statistics:** count, missing, mean, median, sample variance and standard deviation, min/max, quartiles, IQR, grouped by state, fuel, year, and facility.
- **Derived indicators:** CO₂/SO₂/NOₓ intensity per MWh, heat rate, and year-over-year change. Undefined ratios stay missing, never zero.
- **Charts (Plotly):** emissions over time, top emitters, heat input vs. CO₂ with a fit line, intensity by state, CO₂ histogram and box plot, correlation heat map. Every chart exports to PNG.
- **TRACI 2.2 impacts:** global warming (kg CO₂ eq) and acidification (kg SO₂ eq) from CAMPD masses (1 short ton = 907.18474 kg).
- **CO₂ forecast models:** one model per state; yesterday's-value baseline vs. Ridge, Random Forest, and Gradient Boosting, using each unit's own history; chronological train/test split.
- **What-if sensitivity and scenarios:** move one input with a slider, see the sensitivity curve, an input comparison, and named scenarios against the baseline, with warnings outside the training range.
- **Exports:** JSON downloads of every result with metadata (filters, units, definitions, model and training dates). Filters are kept in the URL.

See `CHANGES.md` for methods, results by state, data sources, library licenses, and limitations.

## Tech Stack

- **Backend:** Python 3.11, Flask
- **Database:** SQLite
- **ORM:** Flask-SQLAlchemy
- **Data Processing:** Pandas
- **AI / LLM:** Google GenAI SDK (Gemini)
- **Frontend:** Jinja2, Bootstrap 5, Intro.js

## Project Structure

```text
├── app.py                  # Flask routes, filtering, CSV ingestion, API streaming, and export
├── models.py               # SQLAlchemy database models (FacilityRecord & UploadedDataset)
├── requirements.txt        # Python package dependencies
├── README.md               # Project documentation
├── run_app.bat             # Windows startup script
├── run_app.sh              # macOS/Linux startup script
└── templates/
    ├── base.html           # Main layout, navigation, tutorial, and tooltips
    ├── search.html         # Search filters, AI prompt bar, sortable results table, and export controls
    ├── upload.html         # CSV upload, dataset history log, and live API trigger
    └── detail.html         # Facility and unit-level details with timestamp breakdowns
```

## Database Schema

The SQLite database stores records across two core tables:

### 1. `uploaded_datasets`

| Column Name     | Type        | Description                                              |
| :-------------- | :---------- | :------------------------------------------------------- |
| `id`            | Integer     | Primary key                                              |
| `filename`      | String(255) | Name of the uploaded file or API stream                  |
| `notes`         | String(500) | Optional description or upload notes                     |
| `upload_time`   | String(50)  | Formatted timestamp of when it was added                 |
| `row_count`     | Integer     | Total records imported                                   |

### 2. `facility_records`

| Column Name     | Type        | Description                                              |
| :-------------- | :---------- | :------------------------------------------------------- |
| `id`            | Integer     | Primary key                                              |
| `dataset_id`    | Integer     | Foreign key linked to `uploaded_datasets.id`             |
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
| `record_hour`   | Integer     | Operating hour (0–23) if available                       |

## Installation & Setup

### 1. Open the Project

Open a terminal in the project root directory:

```bash
cd "CS396 EPA Project"
```

### 2. Quickstart (Windows)

1. Copy `.env.example` to `.env` and add your EPA API key (free from https://api.data.gov/signup/). The Gemini key is optional.
2. Run `setup.bat` once. It creates `venv`, installs packages, loads the TRACI factors, and trains the models if data is present.
3. Load the multi-state daily data (about 2 hours, needs the API key), then train the models:

   ```bat
   venv\Scripts\python.exe scripts\fetch_campd_hourly.py
   venv\Scripts\python.exe train_model.py
   ```

4. Start the app with `run_app.bat` and open http://127.0.0.1:5000/dashboard.

Run the tests with `venv\Scripts\python.exe -m pytest -q`. Tests use a temporary database, never `instance/epa_data.db`.

The database (`instance/`) and trained models (`models_saved/`) are not in git; each machine builds its own.

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

### 1. System Tour
Select **Start Tutorial** in the top navigation bar to launch the interactive walkthrough.

### 2. Uploading & Managing Data
- **Manual CSV Upload:** Navigate to `/upload`, select a `.csv` file, and click **Validate & Ingest File**.
- **Live API Integration:** Click **Fetch Live Data from EPA API** on the upload page to stream records directly from the EPA CAMPD web service.
- **Dataset History:** View all imported datasets with timestamps, row counts, and delete specific datasets as needed.

### 3. Filtering & AI Semantic Search
- **AI Natural Language Search:** Type queries like "Find coal plants in KY over 50k tons" in the semantic search box and click **Ask AI**.
- **Standard Filters:** Set states, primary fuels, calendar date ranges, operating hours, and pollutant thresholds, then click **Apply Filters**.

### 4. Sorting & Exporting
- Click any table header ($\updownarrow$) to cycle through ascending, descending, and neutral sorting.
- Select **Export CSV** in the results header to download records matching the current query.

## Data Source
Emissions data is obtained from the U.S. Environmental Protection Agency's Clean Air Markets Division (CAMPD) data portal and public streaming APIs.
