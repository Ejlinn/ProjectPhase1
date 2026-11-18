from sqlalchemy import func, inspect, text

SHORT_TON_KG = 907.18474
EMISSIONS = {
    "co2_mass": ("CARBON DIOXIDE", "global_climate_kg_co2_eq_per_kg", "global_climate_kg_co2_eq"),
    "so2_mass": ("SULFUR DIOXIDE", "acidification_kg_so2_eq_per_kg", "acidification_kg_so2_eq"),
    "nox_mass": ("NITROGEN OXIDES", "acidification_kg_so2_eq_per_kg", "acidification_kg_so2_eq"),
}


def calculate_impacts(records, engine):
    records = list(records)
    totals = {"global_climate_kg_co2_eq": 0.0, "acidification_kg_so2_eq": 0.0}
    warnings = []
    factors = {}
    if inspect(engine).has_table("traci_factors"):
        with engine.connect() as connection:
            factors = {
                row.substance_name: row._mapping
                for row in connection.execute(text("SELECT * FROM traci_factors"))
            }
    else:
        warnings.append("TRACI factors have not been imported.")

    for mass_field, (substance, factor_field, result_field) in EMISSIONS.items():
        values = [getattr(record, mass_field, None) for record in records]
        present = [value for value in values if value is not None]
        if len(present) != len(values):
            warnings.append(f"{mass_field}: {len(values) - len(present)} missing emission values excluded.")
        factor = factors.get(substance, {}).get(factor_field)
        if factor is None:
            warnings.append(f"Missing {factor_field} factor for {substance}.")
            continue
        totals[result_field] += sum(present) * SHORT_TON_KG * factor

    return {"record_count": len(records), "impacts": totals, "warnings": warnings}


def aggregate_impacts(query, engine):
    """Same totals and warnings as calculate_impacts, but the database does the sums.
    Loading every record as an object is far too slow on the full CAMPD set."""
    factors = {}
    warnings = []
    if inspect(engine).has_table("traci_factors"):
        with engine.connect() as connection:
            factors = {
                row.substance_name: row._mapping
                for row in connection.execute(text("SELECT * FROM traci_factors"))
            }
    else:
        warnings.append("TRACI factors have not been imported.")

    columns = [func.count().label("n")]
    for mass_field in EMISSIONS:
        column = getattr(query.column_descriptions[0]["entity"], mass_field)
        columns.append(func.sum(column).label(f"{mass_field}_sum"))
        columns.append(func.count(column).label(f"{mass_field}_present"))
    row = query.with_entities(*columns).one()
    record_count = int(row.n or 0)

    totals = {"global_climate_kg_co2_eq": 0.0, "acidification_kg_so2_eq": 0.0}
    for mass_field, (substance, factor_field, result_field) in EMISSIONS.items():
        present = int(getattr(row, f"{mass_field}_present") or 0)
        if present != record_count:
            warnings.append(f"{mass_field}: {record_count - present} missing emission values excluded.")
        factor = factors.get(substance, {}).get(factor_field)
        if factor is None:
            warnings.append(f"Missing {factor_field} factor for {substance}.")
            continue
        total_mass = float(getattr(row, f"{mass_field}_sum") or 0.0)
        totals[result_field] += total_mass * SHORT_TON_KG * factor

    return {"record_count": record_count, "impacts": totals, "warnings": warnings}
