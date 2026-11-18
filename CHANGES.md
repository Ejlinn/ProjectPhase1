# Phase 2 changes and update notes

This file lists what was added, what data it uses, and which libraries it depends on.
PHASE2_PROGRESS.md has the longer write-up from the first Phase 2 pass.

## What was added

**First Phase 2 pass**
- Descriptive statistics service and `/api/analytics/*` routes (mean, median, sample variance, standard deviation, quartiles, min/max, counts of missing and zero values).
- Missing values are stored as empty, not zero. Blank or defaulted upload fields are recorded in a `data_flags` column.
- CO₂ models: a mean baseline, Ridge regression, and a Random Forest, compared on held-out facilities, with each run logged in the `model_runs` table. *(Replaced in the second update below: state is no longer an input, the models are autoregressive, and the split is by date.)*
- Interactive dashboard at `/dashboard` with filters, KPI tiles, time series, top emitters, a heat-vs-CO₂ scatter with a fit line, TRACI impact totals, and PNG export.
- TRACI integration: 907.18474 kg per short ton. Acidification uses the SO₂ factor and NOₓ factor separately.
- Safer startup: the app no longer drops tables on start. `services/db_migrations.py` only adds missing columns.
- `setup.bat` and `run_app.bat` split out, plus tests (`tests/`).
- Tutorial (Intro.js) steps added for the dashboard and TRACI card.

**Second update (more data, faster dashboard, new model design, what-if tool)**

*More data*
- `scripts/fetch_campd_hourly.py` pulls hourly emissions from the EPA CAMPD API for KY, OH, WV, IN, PA, and TX, for every month of 2024 and 2025, and rolls them up to one row per unit per day.
- Result: dataset #3 with 702,436 daily unit records. The time series now has 732 reporting days instead of two periods.
- Connection drops are retried (up to 4 attempts per request). `gross_load` is stored too.

*Speed* (the Data Analytics page took 40+ seconds and startup about 50 seconds with the full data)
- Chart and summary numbers are now computed by the database (SQL sums and group-bys) instead of loading every record into Python on each request.
- One covering index (`ix_records_dashboard`) is created at startup, so the dashboard reads a narrow index instead of the whole wide table. It is skipped with a message if the database is locked.
- Quartiles use a cached frame of just the five numeric columns, and the filter dropdowns are cached until the data changes.
- scikit-learn and the Gemini library load only when used. The model-results response is a 2,000-point sample (it was 8 MB).
- Measured on the full data: startup 6.5 s to 1.3 s; dashboard first load about 8 s, down from 40+ s; one state and year about 0.6 s.

*Model redesign, from the professor's feedback*
- **State is no longer a model input.** One model is trained per state (`python train_model.py --state KY`, or no flag for all six), and the same code runs for every state.
- **Autoregressive inputs.** Each unit's CO₂ and heat input from yesterday, the same day last week, and the average of the previous 7 days, plus day of week, month, and fuel. Lags are matched by calendar date, so a missing day gives a missing lag.
- **Linear and non-linear models:** Ridge regression (linear), Random Forest, and gradient boosting (tree-based, non-linear), compared against a baseline that just copies yesterday's value.
- **Split by time, not by plant.** The earliest 80% of days train the models and the latest 20% test them. Model choice uses 3 expanding-window folds inside the training days only.
- **Why same-day heat input is not an input.** CAMPD calculates CO₂ from heat input, so a model given it scores R² of 0.99+ without forecasting anything. That version is shown as a labelled reference row so the difference is visible.
- Only the daily CAMPD rows are used for training. The older hourly and annual uploads are a different granularity.

*What-if sensitivity (dashboard section D)*
- Pick a state (and optionally a facility), pick an input, and move the bar from -50% to +50%. The input changes by that percent, the forecast is recalculated, and the page shows the new forecast, the change in tons and percent, and the sensitivity (percent change in the forecast per 1% change in the input).
- A curve shows the forecast across the whole range, and a bar chart moves every input by +/-10% on its own so they can be compared.
- It starts from a typical recent unit-day (median of the last 30 days) and changes one input at a time with everything else held fixed. Warnings appear when a value goes outside the range the model trained on.
- Endpoints: `GET /api/sensitivity`, `GET /api/sensitivity/options`, `POST /api/ml/predict` (now takes a state).

*Tests:* 54 pass, including checks on the lag features, the date split, that state is not a feature, that the history models beat copying yesterday on a controlled series, and the what-if behavior.

## Model results (test = latest 20% of days, 2025-08-08 to 2025-12-31)

| State | Yesterday baseline RMSE | Ridge (linear) | Random Forest | Gradient Boosting | Best test R² | Same-day-heat reference R² |
|---|---|---|---|---|---|---|
| KY | 1,047 | 978 | **888** | 889 | 0.943 | 0.998 |
| IN | 1,456 | 1,399 | **1,316** | 1,344 | 0.910 | 0.997 |
| OH | 1,180 | 1,137 | **1,064** | 1,094 | 0.938 | 0.997 |
| PA | 948 | 916 | 852 | **846** | 0.882 | 0.989 |
| TX | 925 | 850 | **830** | 835 | 0.938 | 0.995 |
| WV | 2,283 | 2,155 | **1,971** | 1,986 | 0.926 | 1.000 |

RMSE is in short tons of CO₂ per unit per day (lower is better). Random Forest had the lowest validation error in every state. The history-based models beat copying yesterday by roughly 8 to 15 percent in error, which is a modest gain, not a dramatic one.

## Data sources and how they are used

| Dataset | Source | Granularity | Notes |
|---|---|---|---|
| #1 | Hand-downloaded CSV, KY, June 1–3 2024 | Hourly | Overlaps dataset #3 for those three days in KY. Kept on purpose. |
| #2 | Live API, annual endpoint, KY 2025 | Annual totals | Only 89 rows. Shows up as a yearly total, not a daily value. Kept on purpose. |
| #3 | CAMPD hourly API, six states, 2024–2025 | Daily per unit | 702,436 rows. Main dataset for the time series. |

**Known overlap:** The KY days from dataset #1 are also in dataset #3. Those three days are counted twice in KY totals. The group keeps both datasets, so the dashboard shows this. Filter by dataset in the dashboard to see only one source.

**Known mismatch:** Dataset #2 is annual totals. It will look like a spike on the time series because it sits on a single date. Treat its points as yearly, not daily.

## Unit conversions

- `co2Mass`: CAMPD reports short tons. Used as-is.
- `so2Mass` and `noxMass`: CAMPD hourly fields are in pounds. Divided by 2,000 to get short tons.
- `heatInput`: summed per day, in mmBtu.
- `grossLoad`: summed per day. This is hourly MW added up, so the daily value is in MWh.

**Assumption to confirm:** The pound-to-ton conversion for SO₂ and NOₓ was checked against the sample values, not against the official CAMPD data dictionary. Look at the CAMPD field definitions before presenting SO₂ or NOₓ numbers as final.

## Libraries

Versions are the ones pinned in `requirements.txt`. Licenses are from the projects' own documentation as we understand them; please check before the final write-up.

| Library | Version | Used for | License |
|---|---|---|---|
| Flask | 3.1.3 | Web app and routes | BSD-3-Clause |
| Flask-SQLAlchemy | 3.1.1 | Database models | BSD-3-Clause |
| SQLAlchemy | 2.0.52 | Database layer | MIT |
| Jinja2 | 3.1.6 | HTML templates | BSD-3-Clause |
| Werkzeug | 3.1.8 | Flask web toolkit | BSD-3-Clause |
| pandas | 3.1.0 | Data frames and grouping | BSD-3-Clause |
| NumPy | 2.4.4 | Numeric work, trend fit | BSD-3-Clause |
| SciPy | 1.17.1 | Installed as a scikit-learn dependency | BSD-3-Clause |
| scikit-learn | 1.9.1 | Models, splits, metrics | BSD-3-Clause |
| joblib | 1.6.0 | Saving the trained model | BSD-3-Clause |
| openpyxl | 3.1.5 | Excel import | MIT |
| requests | 2.34.2 | CAMPD API calls | Apache-2.0 |
| python-dotenv | 1.2.4 | Reads `.env` (API keys) | BSD-3-Clause |
| google-genai | 2.29.0 | Existing Gemini feature | Apache-2.0 |
| pytest | 9.2.0 (dev) | Tests | MIT |
| Plotly.js | 2.35.2 (CDN) | Dashboard charts and PNG export | MIT |
| Bootstrap | 5.3.3 (CDN) | Page layout | MIT |
| Intro.js | 7.2.0 (CDN) | Tutorial overlay | **AGPL-3.0** |
| Google Fonts | CDN | Alfa Slab One, Atkinson Hyperlegible | SIL OFL |

**Intro.js note:** Intro.js is AGPL-3.0. That is fine for a class project. If the project is ever shared publicly or run as a network service, the AGPL terms apply, and the source must be available to users. Mention this in the write-up.

## Known limitations

- The forecast is for one unit on one day, using that unit's own history. Days when a unit was idle (no CO₂ reported) are left out, not counted as zero, so the model says nothing about restarts after an idle stretch.
- Only about half of the daily rows are usable for training (CO₂ and heat input present for the day and the day before).
- The model is trained on 2024 to mid-2025 and tested on the following months. That is one test period, so results could change with a different split.
- The what-if tool changes one input at a time and holds the others fixed. In real operation yesterday's heat input and CO₂ move together, which is why the first option changes both.
- Tree models respond in steps and cannot extrapolate beyond what they saw, so their what-if curve is uneven. The Ridge option shows a straight line.
- The saved model files (`models_saved/`, about 4 MB per state) are not in git. Run `python train_model.py` on each machine.
- `operating_time` is not in any export we use, and `gross_load` is stored but not used as an input.
