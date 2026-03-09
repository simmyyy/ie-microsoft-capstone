"""
GBIF Brazil – Experimental ML Dataset
Lightweight, temporally balanced, migration-ready
"""

import requests
import pandas as pd
from time import sleep

BASE_URL = "https://api.gbif.org/v1/occurrence/search"

COUNTRY = "BR"
LIMIT = 300
RECORDS_PER_YEAR = 600
START_YEAR = 2010
END_YEAR = 2025

all_rows = []

print("Starting balanced experimental download...")

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

        for r in results:
            if (
                r.get("species") is not None and
                r.get("decimalLatitude") is not None and
                r.get("decimalLongitude") is not None
            ):
                row = {
                    "species": r.get("species"),
                    "year": r.get("year"),
                    "month": r.get("month"),
                    "decimalLatitude": r.get("decimalLatitude"),
                    "decimalLongitude": r.get("decimalLongitude"),
                    "coordinateUncertaintyInMeters": r.get("coordinateUncertaintyInMeters")
                }
                all_rows.append(row)

        year_count += len(results)
        offset += LIMIT

        print(f"Year {year}: {year_count} records")

        sleep(0.2)

print("Download complete.")

df = pd.DataFrame(all_rows)

# Limpieza adicional
df = df.dropna(subset=["species", "decimalLatitude", "decimalLongitude", "year"])
df["year"] = pd.to_numeric(df["year"], errors="coerce")
df["month"] = pd.to_numeric(df["month"], errors="coerce")

df.to_parquet("gbif_brazil_experiment.parquet", index=False)

print("Saved gbif_brazil_experiment.parquet")
print("Total rows:", len(df))
print("Unique years:", df["year"].nunique())
print("Unique species:", df["species"].nunique())

##### Verificación rápida del dataset guardado 

df = pd.read_parquet("gbif_brazil_experiment.parquet")

print(df.shape)
print(df["year"].value_counts().sort_index())
print("Unique species:", df["species"].nunique())
