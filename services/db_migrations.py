"""Non-destructive schema check that runs at startup.

The old startup code called db.drop_all() whenever a column was missing, which deleted
every emissions record. This version only adds columns that are missing. It never drops
or rewrites existing rows.
"""

from sqlalchemy import inspect, text

# column name -> SQL type, for columns added after the first release
ADDED_COLUMNS = {
    "facility_records": {
        "dataset_id": "INTEGER",
        "record_hour": "INTEGER",
        "gross_load": "FLOAT",
        "data_flags": "VARCHAR(255)",
    },
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
    return changes
