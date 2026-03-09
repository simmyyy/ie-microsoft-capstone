"""
GBIF Spain - Extended Raw Download
Balanced temporal sampling for robustness analysis
"""

import requests
import pandas as pd
from time import sleep

BASE_URL = "https://api.gbif.org/v1/occurrence/search"

COUNTRY = "ES"
LIMIT = 300
RECORDS_PER_YEAR = 1000
START_YEAR = 2010
END_YEAR = 2025

all_rows = []

print("Starting Spain extended download...")

for year in range(START_YEAR, END_YEAR + 1):

    offset = 0
    year_count = 0

    while year_count < RECORDS_PER_YEAR:

        params = {
            "country": COUNTRY,
            "year": year,
            "limit": LIMIT,
            "offset": offset,
            "hasCoordinate": "true"
        }

        response = requests.get(BASE_URL, params=params)
        data = response.json()
        results = data.get("results", [])

        if not results:
            break

        all_rows.extend(results)

        year_count += len(results)
        offset += LIMIT

        print(f"Year {year}: {year_count} records")

        sleep(0.2)

print("Download complete.")

df = pd.json_normalize(all_rows)

df.to_parquet("gbif_spain_raw_extended.parquet", index=False)

print("Saved gbif_spain_raw_extended.parquet")
print("Total rows:", len(df))
