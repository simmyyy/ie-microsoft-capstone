import requests
import pandas as pd

BASE_URL = "https://api.gbif.org/v1/occurrence/search"

params = {
    "country": "BR",
    "limit": 300,
    "offset": 0
}

print("Requesting data from GBIF API...")

response = requests.get(BASE_URL, params=params)
data = response.json()

results = data["results"]

df = pd.json_normalize(results)

print("Rows retrieved:", len(df))
print(df[["species", "decimalLatitude", "decimalLongitude", "year"]].head())

df.to_parquet("gbif_brazil_sample.parquet", index=False)

print("Saved locally ✅")
