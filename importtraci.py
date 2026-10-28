import os
import pandas as pd
from sqlalchemy import create_engine

base_dir = os.path.abspath(os.path.dirname(__file__))

# Adjust if traci_2_2.xlsx is in the root or a 'data' subfolder
file_path = os.path.join(base_dir, "data", "traci_2_2.xlsx")
instance_dir = os.path.join(base_dir, "instance")
os.makedirs(instance_dir, exist_ok=True)

db_path = os.path.join(instance_dir, "epa_data.db")
engine = create_engine(f"sqlite:///{db_path}")

# Note: If traci_2_2.xlsx has an intro tab, specify the factor sheet:
# traci_df = pd.read_excel(file_path, sheet_name="...", engine='openpyxl')
traci_df = pd.read_excel(file_path, engine='openpyxl')

# Clean column headers for SQL compatibility
traci_df.columns = [str(c).strip().lower().replace(" ", "_") for c in traci_df.columns]

# Write to SQLite
traci_df.to_sql("traci_factors", con=engine, if_exists="replace", index=False)

print(f"Successfully loaded {len(traci_df)} TRACI factors into the database.")