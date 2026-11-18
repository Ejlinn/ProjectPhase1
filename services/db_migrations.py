"""Non-destructive schema check that runs at startup.

The old startup code called db.drop_all() whenever a column was missing, which deleted
every emissions record. This version only adds columns that are missing. It never drops
or rewrites existing rows.
"""

from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

# column name -> SQL type, for columns added after the first release
ADDED_COLUMNS = {
    "facility_records": {
        "dataset_id": "INTEGER",
        "record_hour": "INTEGER",
        "gross_load": "FLOAT",
        "data_flags": "VARCHAR(255)",
    },
}


# index name -> (table, columns).
# One covering index holding every column the dashboard filters, groups or sums. With about
# 700k daily CAMPD rows, each chart query used to read the whole wide table (names, flags and
# all). With this index SQLite reads only the narrow index, which is 3 to 10 times faster.
INDEXES = {
    "ix_records_dashboard": (
        "facility_records",
        "state, primary_fuel, facility_id, record_date, dataset_id, "
        "co2_mass, so2_mass, nox_mass, heat_input, gross_load",
    ),
}


def ensure_schema(db):
    """Create missing tables and add missing columns. Returns a list of what was changed."""
    changes = []
    db.create_all()  # creates new tables such as model_runs and traci_factors if needed
    inspector = inspect(db.engine)
    for table, columns in ADDED_COLUMNS.items():
        if not inspector.has_table(table):
            continue
        existing = {col["name"] for col in inspector.get_columns(table)}
        for name, sql_type in columns.items():
            if name not in existing:
                with db.engine.begin() as connection:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))
                changes.append(f"added {table}.{name}")
    # indexes last, because they use columns that may have just been added
    inspector = inspect(db.engine)
    for name, (table, columns) in INDEXES.items():
        if inspector.has_table(table) and name not in {i["name"] for i in inspector.get_indexes(table)}:
            try:
                with db.engine.begin() as connection:
                    connection.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})"))
                changes.append(f"added index {name}")
            except OperationalError:
                # another program (for example a second copy of the app) has the database locked.
                # The app still works without the index, just slower; it is retried next start.
                print(f"Could not create index {name} because the database is busy. Close other copies of the app and restart.")
    return changes
