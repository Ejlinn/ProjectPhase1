# Phase 2 changes and update notes

This file lists what was added, what data it uses, and which libraries it depends on.
PHASE2_PROGRESS.md has the longer write-up from the first Phase 2 pass.

## What was added

**First Phase 2 pass**
- Descriptive statistics service and `/api/analytics/*` routes (mean, median, sample variance, standard deviation, quartiles, min/max, counts of missing and zero values).
- Missing values are stored as empty, not zero. Blank or defaulted upload fields are recorded in a `data_flags` column.
- CO₂ models: a mean baseline, Ridge regression, and a Random Forest. Models are compared on held-out facilities. The selected model is saved to `models_saved/co2_predictor.joblib`, and each run is logged in the `model_runs` table.
- Interactive dashboard at `/dashboard` with filters, KPI tiles, time series, top emitters, a heat-vs-CO₂ scatter with a fit line, TRACI impact totals, and PNG export.
- TRACI integration: 907.18474 kg per short ton. Acidification uses the SO₂ factor and NOₓ factor separately.
- Safer startup: the app no longer drops tables on start. `services/db_migrations.py` only adds missing columns.
- `setup.bat` and `run_app.bat` split out, plus tests (`tests/`).
- Tutorial (Intro.js) steps added for the dashboard and TRACI card.

**This update (CAMPD data expansion)**
- `scripts/fetch_campd_hourly.py` pulls hourly emissions from the EPA CAMPD API for KY, OH, WV, IN, PA, and TX, for every month of 2024 and 2025. Each state and month is requested separately.
- Hourly rows are rolled up to one row per unit per day. This gives 732 reporting days in the time series, instead of the two periods we had before.
- Result: dataset #3 with 702,436 daily unit records. No months were skipped.
- Connection drops are retried (up to 4 attempts per request).
- The model is retrained on the full set. Random Forest now uses 100 trees, each trained on a 20% sample, to keep training under a few minutes.
- `gross_load` is stored for the CAMPD rows. It is not a model feature yet.
- Tests added for the unit conversion and the hourly-to-daily roll-up (`tests/test_fetch.py`). 32 tests pass.

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

- The `/api/ml/metrics` response includes every test-set prediction, about 8 MB. This slows the dashboard. It should be trimmed to a sample.
- The Random Forest uses a 20% sample per tree. That was chosen for speed, and it is a limitation to state in the write-up.
- The model is evaluated across facilities, not over time. It is not a forecast.
- `operating_time` is not in any export we use, so it is not a feature.
