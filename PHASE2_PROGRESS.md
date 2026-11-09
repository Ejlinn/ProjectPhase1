# Phase 2 progress

## What we built

**Descriptive statistics** (`services/analytics_service.py`)
- Count, valid count, missing count, mean, median, sample variance, sample standard deviation, min, max, Q1, Q3, and IQR for CO₂, SO₂, NOₓ, and heat input.
- Variance and standard deviation use n − 1. They are blank when there are fewer than two valid values.
- Grouped summaries by state, fuel, year, and facility.
- `GET /api/analytics/summary` takes `state`, `fuel`, `year`, `dataset_id`, and `facility_id`.

**CO₂ prediction** (`services/ml_service.py`, `train_model.py`)
- Compares a mean baseline, Ridge regression, and a random forest (seed 42).
- Facilities are held out whole (GroupShuffleSplit). Model choice uses 5-fold GroupKFold on the training rows only. The test rows are scored once.
- The chosen pipeline is saved to `models_saved/co2_predictor.joblib`. Metrics and test predictions go in a new `model_runs` table.
- `python train_model.py` retrains. The web app loads the saved file and never trains on startup.
- `GET /api/ml/metrics` returns the latest run. `POST /api/ml/predict` scores new rows.

**Dashboard** (`/dashboard`, `templates/dashboard.html`, `static/js/dashboard.js`)
- Section A: KPI cards and a full statistics table, with units (variance in short tons²).
- Section B: emissions over time, top emitters (CO₂, SO₂, NOₓ, and both TRACI categories), heat input vs. CO₂ with a fitted line, and a TRACI impact summary.
- Section C: model comparison table and chart, plus actual vs. predicted for the test facilities.
- Filters for year, state, fuel, dataset, and facility. Everything refreshes together. Each chart has a PNG export button.
- Plotly and Bootstrap load from CDNs. Charts only draw data the API returns.

**Tutorial**
- The "Start tutorial" tour now covers the Data Analytics nav item (step 100), every dashboard section (steps 101–108), the TRACI card on the facility page (step 3), and the new missing-value note on the upload page.

**Startup and data safety**
- `services/db_migrations.py` replaces the old `drop_all()` check. It only adds missing columns. No rows are deleted.
- Uploads and live API pulls store a missing number as NULL, not 0. Defaults for state, fuel, facility, and date are recorded in a new `data_flags` column.
- `setup.bat` installs packages, loads TRACI factors, and trains the model. `run_app.bat` only starts the app.
- `requirements.txt` is trimmed to packages the code imports. Test packages are in `requirements-dev.txt`.
- The `.gitignore` file had been deleted in the working tree. It is restored from HEAD, with `models_saved/` added.

## Tests

`python -m pytest -q` gives **29 passed**. Tests use a temporary database, so the real `instance/epa_data.db` is never touched.

- `tests/test_analytics.py`: hand-checked stats (1 to 5 gives mean 3, sample variance 2.5, Q1 2, Q3 4), missing values excluded, single value gives null variance, filters change the results, grouped stats, trend only with two or more periods, TRACI ranking, trendline on an exact line.
- `tests/test_ml.py`: training and model comparison, facility-level split, saved model loads and predicts, missing heat input gives a null prediction, missing fuel gives a warning, too few rows gives an error, missing artifact gives a clear message, `/api/ml/metrics`.
- `tests/test_routes.py`: dashboard page and nav, filter options, bad parameters return 400, JSON endpoints, NULL CO₂ is not counted as zero, facility detail, impacts endpoint, CSV export, and the schema check keeps rows.

The dashboard was opened in the browser. All five charts drew, there were no JavaScript errors, and the KPI numbers match the API.

## Results from the real database

Run on 2,619 records (all Kentucky, 23 facilities):

| Measure (CO₂ mass) | Value |
|---|---|
| Valid / missing | 2,619 / 0 |
| Mean | 24,285.57 short tons |
| Median | 131.12 short tons |
| Sample variance | 54,480,016,022.5 short tons² |
| Sample std. dev. | 233,409.55 short tons |
| Min / Q1 / Q3 / Max | 0 / 66.86 / 286.65 / 4,250,979.56 short tons |
| IQR | 219.79 short tons |

Model comparison (training: 2,342 rows, 16 facilities; testing: 274 rows, 6 facilities; features: heat input and primary fuel):

| Model | Test MAE | Test RMSE | Test R² | CV RMSE (train) |
|---|---|---|---|---|
| Baseline (mean) | 33,502 | 111,942 | −0.019 | 224,803 |
| Ridge regression | 3,375 | 29,498 | 0.929 | 32,732 |
| Random forest | 4,282 | 43,958 | 0.843 | 55,748 |

Ridge was selected by cross-validation RMSE on the training rows. The test rows were not used for selection. Units are short tons of CO₂ per record.

## Limitations

- **Gross load and operating time are not in the data.** The EPA export has no gross load, so the scatter plot uses heat input. We did not derive gross load from CO₂.
- **Only one state.** Every record is Kentucky, so `state` is dropped as a predictor because it does not vary.
- **Only a few dates.** Most rows are hourly records from June 1 to 3, 2024. A chronological split is not meaningful, so the evaluation is exploratory (held-out facilities), not a forecast.
- **The 2025 rows look like a different granularity.** The 89 rows labelled 2025 add up to about 63 million short tons, while each June 2024 day is about 130 to 160 thousand. They appear to be annual totals, but the file does not say so. They inflate the mean, the variance, and the 2025 bar. We did not remove them. This should be checked against the source before the numbers are presented as typical.
- **Legacy zeros.** 304 older rows have 0 for CO₂ and 3 have 0 for every pollutant and heat input. The old upload code used 0 for missing values, and those rows have no flags, so we cannot tell gaps from real zeros. New uploads store NULL.
- **The model is small.** Six test facilities is a small holdout. Scores will move with a different split.

## Not done yet

- Sensitivity analysis (`/api/sensitivity`) is not started.
- No dataset-level comparison on the dashboard beyond the filter.
- No commit yet. The working tree still has the user's earlier uncommitted changes, so commit on a feature branch once you have reviewed them.
- `setup.bat` was written but not run from start to finish on a clean machine.

## How to run

```bash
python train_model.py
python -m pytest -q
```

Then start the app with `run_app.bat` and open http://127.0.0.1:5000/dashboard.
