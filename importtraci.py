from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine


BASE_DIR = Path(__file__).resolve().parent
SOURCE = BASE_DIR / "data" / "traci_2_2.xlsx"
DATABASE = BASE_DIR / "instance" / "epa_data.db"


def load_factors(source=SOURCE, database=DATABASE):
    columns = {
        "Substance Name": "substance_name",
        "Global Climate Air (kg CO2 eq / kg substance)": "global_climate_kg_co2_eq_per_kg",
        "Acidification Air (kg SO2 eq / kg substance)": "acidification_kg_so2_eq_per_kg",
    }
    factors = pd.read_excel(source, sheet_name="Substances", usecols=list(columns))
    factors = factors.rename(columns=columns)
    factors = factors[factors["substance_name"].isin(
        ["CARBON DIOXIDE", "SULFUR DIOXIDE", "NITROGEN OXIDES"]
    )].copy()
    factors = factors.drop_duplicates(subset="substance_name")
    for column in list(columns.values())[1:]:
        factors[column] = pd.to_numeric(factors[column], errors="coerce")
    if set(factors["substance_name"]) != {
        "CARBON DIOXIDE", "SULFUR DIOXIDE", "NITROGEN OXIDES"
    }:
        raise ValueError("TRACI workbook is missing required emission factors")
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    factors.to_sql("traci_factors", con=engine, if_exists="replace", index=False)
    return len(factors)


if __name__ == "__main__":
    print(f"Loaded {load_factors()} TRACI emission factors.")
