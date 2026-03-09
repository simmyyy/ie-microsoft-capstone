"""
GBIF Brazil Extended Download
For robust EDA and temporal validation
"""

import requests
import pandas as pd
from time import sleep

BASE_URL = "https://api.gbif.org/v1/occurrence/search"

COUNTRY = "BR"
LIMIT = 300
MAX_RECORDS = 20000   # puedes subir luego
OFFSET = 0

all_data = []

print("Starting GBIF extended download...")

while OFFSET < MAX_RECORDS:
    params = {
        "country": COUNTRY,
        "limit": LIMIT,
        "offset": OFFSET,
        "hasCoordinate": "true"  # importante para análisis espacial
    }

    response = requests.get(BASE_URL, params=params)
    data = response.json()
    results = data.get("results", [])

    if not results:
        break

    all_data.extend(results)

    print(f"Retrieved {len(all_data)} records...")
    
    OFFSET += LIMIT
    sleep(1)  # evitar rate limit

print("Download complete.")

df = pd.json_normalize(all_data)

# Guardar bruto
df.to_parquet("gbif_brazil_raw_extended.parquet", index=False)

print("Saved gbif_brazil_raw_extended.parquet")
print("Final rows:", len(df))

