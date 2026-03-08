from pathlib import Path
from datetime import date
import os

import pandas as pd
import h3

REPO_ROOT = Path(__file__).resolve().parents[2]

# --- Exact CSV path (we'll pass it via env, with a default matching your file name) ---
DEFAULT_CSV = REPO_ROOT / "data" / "gee" / "features" / "gee_sp_pt_grid15km_2024-01-01_to_2024-12-31_20260307_162031.csv"
CSV_PATH = Path(os.environ.get("GEE_CSV_PATH", str(DEFAULT_CSV)))

SILVER_DIR = REPO_ROOT / "data" / "gee" / "silver" / "gee_features"

# Metadata
COUNTRY = os.environ.get("GEE_COUNTRY", "ES_PT")
YEAR = int(os.environ.get("GEE_YEAR", "2024"))  # tag for partitioning; we'll improve later
SNAPSHOT_DATE = os.environ.get("GEE_SNAPSHOT_DATE", str(date.today()))
PERIOD_START = os.environ.get("GEE_PERIOD_START", "2024-01-01")
PERIOD_END = os.environ.get("GEE_PERIOD_END", "2024-12-31")


def add_h3_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["h3_9"] = df.apply(lambda r: h3.latlng_to_cell(float(r["centroid_lat"]), float(r["centroid_lon"]), 9), axis=1)
    df["h3_8"] = df["h3_9"].apply(lambda x: h3.cell_to_parent(x, 8))
    df["h3_7"] = df["h3_9"].apply(lambda x: h3.cell_to_parent(x, 7))
    df["h3_6"] = df["h3_9"].apply(lambda x: h3.cell_to_parent(x, 6))
    return df


def main():
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"CSV not found: {CSV_PATH}")

    print("Reading CSV:", CSV_PATH)
    df = pd.read_csv(CSV_PATH)

    needed = {"cell_id", "centroid_lat", "centroid_lon", "NDVI_mean", "LC_mode", "elevation_mean", "slope_mean"}
    missing = needed - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in CSV: {missing}")

    # Metadata (match teammate pattern)
    df["country"] = COUNTRY
    df["year"] = YEAR
    df["snapshot_date"] = SNAPSHOT_DATE
    df["period_start"] = PERIOD_START
    df["period_end"] = PERIOD_END

    # H3 columns (silver style)
    df = add_h3_cols(df)

    out_dir = SILVER_DIR / f"country={COUNTRY}" / f"year={YEAR}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "part-00000.parquet"
    df.to_parquet(out_path, index=False)

    print("Wrote SILVER parquet:", out_path)
    print("Rows:", len(df), "| Cols:", len(df.columns))
    print("Done ✅")


if __name__ == "__main__":
    main()