from pathlib import Path
import os
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]

SILVER_DIR = REPO_ROOT / "data" / "gee" / "silver" / "gee_features"
GOLD_DIR   = REPO_ROOT / "data" / "gee" / "gold" / "gee_hex_features"

COUNTRY = os.environ.get("GEE_COUNTRY", "ES_PT")
YEAR = int(os.environ.get("GEE_YEAR", "2024"))

# Which H3 resolutions to publish (match teammate: 6–9)
H3_RESOLUTIONS = [6, 7, 8, 9]


def mode_series(s: pd.Series):
    s = s.dropna()
    if s.empty:
        return np.nan
    return s.value_counts().idxmax()


def read_silver(country: str, year: int) -> pd.DataFrame:
    in_dir = SILVER_DIR / f"country={country}" / f"year={year}"
    # simplest: read all parquet files in partition
    files = sorted(in_dir.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"No parquet files found in {in_dir}")
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    return df


def aggregate_for_res(df_silver: pd.DataFrame, res: int) -> pd.DataFrame:
    h3_col = f"h3_{res}"
    if h3_col not in df_silver.columns:
        raise ValueError(f"Missing {h3_col} in silver data.")

    # 1 row per hex
    agg = df_silver.groupby(h3_col).agg(
        ndvi_mean=("NDVI_mean", "mean"),
        elevation_mean=("elevation_mean", "mean"),
        slope_mean=("slope_mean", "mean"),
        landcover_mode=("LC_mode", mode_series),

        # QA / debugging
        n_samples=("cell_id", "count"),
        pct_missing_ndvi=("NDVI_mean", lambda x: x.isna().mean()),
    ).reset_index().rename(columns={h3_col: "h3_index"})

    # add join keys + metadata
    agg["h3_resolution"] = res
    agg["country"] = df_silver["country"].iloc[0] if "country" in df_silver.columns else COUNTRY
    agg["year"] = df_silver["year"].iloc[0] if "year" in df_silver.columns else YEAR

    # keep period & snapshot metadata if present (take first, they should be constant)
    for col in ["snapshot_date", "period_start", "period_end"]:
        if col in df_silver.columns:
            agg[col] = df_silver[col].iloc[0]

    # reorder columns (nice for downstream)
    front = ["country", "year", "h3_resolution", "h3_index"]
    rest = [c for c in agg.columns if c not in front]
    agg = agg[front + rest]

    return agg


def write_gold_partition(df_gold: pd.DataFrame, country: str, year: int, res: int):
    out_dir = GOLD_DIR / f"country={country}" / f"year={year}" / f"h3_resolution={res}"
    out_dir.mkdir(parents=True, exist_ok=True)
    # mimic lakehouse style: multiple files possible; start with one
    out_path = out_dir / "part-00000.parquet"
    df_gold.to_parquet(out_path, index=False)
    return out_path


def main():
    print(f"Reading silver: country={COUNTRY}, year={YEAR}")
    df = read_silver(COUNTRY, YEAR)
    print("Silver rows:", len(df), "| cols:", len(df.columns))

    total_hex_rows = 0
    for res in H3_RESOLUTIONS:
        df_gold = aggregate_for_res(df, res)
        out_path = write_gold_partition(df_gold, COUNTRY, YEAR, res)
        total_hex_rows += len(df_gold)
        print(f"Wrote gold res={res}: rows(hexes)={len(df_gold)} -> {out_path}")

    print("Total gold rows across resolutions:", total_hex_rows)
    print("Done ✅")


if __name__ == "__main__":
    main()