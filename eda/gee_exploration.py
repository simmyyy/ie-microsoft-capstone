# eda/gee_exploration.py
import os
import math
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import ee


# =========================
# CONFIG
# =========================
COUNTRIES = ["Spain", "Portugal"]
GRID_KM = 15
START_DATE = "2024-01-01"
END_DATE = "2025-12-31"
MAX_CELLS = 500

# Resolutions (meters) for faster EDA
NDVI_SCALE_M = 250
WC_SCALE_M = 250
DEM_SCALE_M = 250

# Save inside repo
BASE_DIR = Path(__file__).resolve().parents[1]  # repo root
FEATURES_DIR = BASE_DIR / "data" / "gee" / "features"
PLOTS_DIR = BASE_DIR / "data" / "gee" / "plots"


# =========================
# HELPERS
# =========================
def ensure_dirs():
    FEATURES_DIR.mkdir(parents=True, exist_ok=True)
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)


def km_to_degrees_lat(km: float) -> float:
    return km / 111.0


def km_to_degrees_lon(km: float, lat_deg: float) -> float:
    return km / (111.0 * math.cos(math.radians(lat_deg)) + 1e-9)


def ee_init(project_id: str):
    """
    Usa TU project_id actual (no necesitas crear otro proyecto).
    """
    try:
        ee.Initialize(project=project_id)
    except Exception:
        ee.Authenticate()
        ee.Initialize(project=project_id)


def get_aoi():
    countries_fc = ee.FeatureCollection("FAO/GAUL/2015/level0")
    return countries_fc.filter(ee.Filter.inList("ADM0_NAME", COUNTRIES)).geometry()


def make_grid(bounds_geom: ee.Geometry, grid_km: float) -> ee.FeatureCollection:
    """
    SERVER-SIDE grid to avoid >10MB payload.
    No Python loops creating thousands of ee.Feature objects client-side.
    """
    # bounds_geom is rectangle; safe small getInfo
    coords = bounds_geom.coordinates().getInfo()[0]
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)

    step_lat = km_to_degrees_lat(grid_km)
    mid_lat = (min_lat + max_lat) / 2
    step_lon = km_to_degrees_lon(grid_km, mid_lat)

    lat_vals = ee.List.sequence(min_lat, max_lat - step_lat, step_lat)
    lon_vals = ee.List.sequence(min_lon, max_lon - step_lon, step_lon)

    n_lon = lon_vals.length()
    lat_idx = ee.List.sequence(0, lat_vals.length().subtract(1))
    lon_idx = ee.List.sequence(0, lon_vals.length().subtract(1))

    def make_row(i):
        i = ee.Number(i)
        lat = ee.Number(lat_vals.get(i))

        def make_cell(j):
            j = ee.Number(j)
            lon = ee.Number(lon_vals.get(j))

            rect = ee.Geometry.Rectangle(
                [lon, lat, lon.add(step_lon), lat.add(step_lat)],
                proj=None,
                geodesic=False
            )
            cen = rect.centroid(1).coordinates()
            cell_id = i.multiply(n_lon).add(j)

            return ee.Feature(rect, {
                "cell_id": cell_id,
                "centroid_lon": cen.get(0),
                "centroid_lat": cen.get(1),
                "min_lon": lon,
                "min_lat": lat,
                "max_lon": lon.add(step_lon),
                "max_lat": lat.add(step_lat),
            })

        return lon_idx.map(make_cell)

    grid_list = lat_idx.map(make_row).flatten()
    return ee.FeatureCollection(grid_list)


def s2_ndvi_mean(aoi: ee.Geometry, start_date: str, end_date: str) -> ee.Image:
    s2 = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
          .filterBounds(aoi)
          .filterDate(start_date, end_date)
          .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 30)))

    def mask_clouds(img):
        qa = img.select("QA60")
        cloud_bit = 1 << 10
        cirrus_bit = 1 << 11
        mask = qa.bitwiseAnd(cloud_bit).eq(0).And(qa.bitwiseAnd(cirrus_bit).eq(0))
        return img.updateMask(mask)

    s2 = s2.map(mask_clouds)

    ndvi = (s2
            .map(lambda img: img.normalizedDifference(["B8", "B4"]).rename("NDVI"))
            .mean()
            .select("NDVI")
            .clip(aoi))
    return ndvi


def worldcover(aoi: ee.Geometry) -> ee.Image:
    return ee.ImageCollection("ESA/WorldCover/v200").first().select("Map").clip(aoi)


def elevation_slope(aoi: ee.Geometry):
    dem = ee.Image("USGS/SRTMGL1_003").select("elevation").rename("elevation").clip(aoi)
    slope = ee.Terrain.slope(dem).rename("slope").clip(aoi)
    return dem, slope


def reduce_mean(grid_fc, img, band_name, scale_m):
    """
    grid_fc ya debe venir filtrado por AOI (así evitamos filterBounds redundante aquí).
    """
    fc = img.select([band_name]).reduceRegions(
        collection=grid_fc,
        reducer=ee.Reducer.mean(),
        scale=scale_m,
        tileScale=4
    )

    def _fix(f):
        f = ee.Feature(f)
        return f.set(f"{band_name}_mean", f.get("mean")).setGeometry(None)

    fc = fc.map(_fix)

    keep = ["cell_id", "centroid_lon", "centroid_lat", "min_lon", "min_lat", "max_lon", "max_lat", f"{band_name}_mean"]
    return fc.select(keep)


def reduce_mode(grid_fc, img, band_name, scale_m):
    fc = img.select([band_name]).reduceRegions(
        collection=grid_fc,
        reducer=ee.Reducer.mode(),
        scale=scale_m,
        tileScale=4
    )

    def _fix(f):
        f = ee.Feature(f)
        return f.set(f"{band_name}_mode", f.get("mode")).setGeometry(None)

    fc = fc.map(_fix)
    return fc.select(["cell_id", f"{band_name}_mode"])


def fc_to_df(fc: ee.FeatureCollection, page_size: int = 200) -> pd.DataFrame:
    """
    Robust download of a FeatureCollection using ee.data.computeFeatures pagination.
    Avoids getInfo() payload limits (~10MB) and timeouts.
    """
    fc = fc.map(lambda f: f.setGeometry(None))

    rows = []
    req = {"expression": fc, "pageSize": page_size}

    while True:
        resp = ee.data.computeFeatures(req)
        feats = resp.get("features", [])
        for f in feats:
            rows.append(f.get("properties", {}))

        token = resp.get("nextPageToken")
        if not token:
            break
        req["pageToken"] = token

    return pd.DataFrame(rows)


# =========================
# PLOTS
# =========================
def save_hist(df, col, filename, title, bins=50):
    x = df[col].dropna().values
    plt.figure()
    plt.hist(x, bins=bins)
    plt.title(title)
    plt.xlabel(col)
    plt.ylabel("Count")
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / filename, dpi=200)
    plt.close()


def save_geo_scatter(df, value_col, filename, title):
    sub = df.dropna(subset=["centroid_lon", "centroid_lat", value_col])
    plt.figure()
    sc = plt.scatter(sub["centroid_lon"], sub["centroid_lat"], c=sub[value_col], s=8)
    plt.colorbar(sc, label=value_col)
    plt.title(title)
    plt.xlabel("Longitude")
    plt.ylabel("Latitude")
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / filename, dpi=200)
    plt.close()


def save_scatter(df, xcol, ycol, filename, title):
    sub = df.dropna(subset=[xcol, ycol])
    plt.figure()
    plt.scatter(sub[xcol], sub[ycol], s=8, alpha=0.35)
    plt.title(title)
    plt.xlabel(xcol)
    plt.ylabel(ycol)
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / filename, dpi=200)
    plt.close()


def save_bar_counts(df, col, filename, title, topn=20):
    vc = df[col].value_counts(dropna=True).head(topn)
    plt.figure(figsize=(10, 4))
    plt.bar(vc.index.astype(str), vc.values)
    plt.title(title)
    plt.xlabel(col)
    plt.ylabel("Count")
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / filename, dpi=200)
    plt.close()


# =========================
# MAIN
# =========================
def main():
    ensure_dirs()

    print("1) Initializing Earth Engine...")
    ee_init(project_id="gen-lang-client-0247261745")  # TU MISMO project_id

    print("2) Building AOI (Spain + Portugal)...")
    aoi = get_aoi()
    bounds = aoi.bounds()

    print(f"3) Creating {GRID_KM}km grid over bounds...")
    grid = make_grid(bounds, GRID_KM)

    # Filter first (important)
    grid = grid.filterBounds(aoi)

    # Limit immediately to keep the expression small
    if MAX_CELLS and MAX_CELLS > 0:
        print(f"   Limiting to first {MAX_CELLS} cells (AFTER AOI filter)...")
        grid = ee.FeatureCollection(grid.toList(MAX_CELLS))

    # Now it's safe to request size
    print("   Final grid size:", grid.size().getInfo())

    
    print("4) Preparing datasets (NDVI, LandCover, DEM, Slope)...")
    ndvi_img = s2_ndvi_mean(aoi, START_DATE, END_DATE).rename("NDVI")
    wc_img = worldcover(aoi).rename("LC")
    dem_img, slope_img = elevation_slope(aoi)

    print("5) Reducing NDVI mean to grid...")
    fc_ndvi = reduce_mean(grid, ndvi_img, "NDVI", NDVI_SCALE_M)

    print("6) Reducing LandCover mode to grid...")
    fc_wc = reduce_mode(grid, wc_img, "LC", WC_SCALE_M)

    print("7) Reducing Elevation mean to grid...")
    fc_dem = reduce_mean(grid, dem_img, "elevation", DEM_SCALE_M)

    print("8) Reducing Slope mean to grid...")
    fc_slope = reduce_mean(grid, slope_img, "slope", DEM_SCALE_M)

    print("9) Downloading results to pandas (paged)...")
    df_ndvi = fc_to_df(fc_ndvi, page_size=200)
    df_wc = fc_to_df(fc_wc, page_size=500)
    df_dem = fc_to_df(fc_dem, page_size=200)[["cell_id", "elevation_mean"]]
    df_slope = fc_to_df(fc_slope, page_size=200)[["cell_id", "slope_mean"]]

    print("10) Merging tables...")
    df = (df_ndvi
          .merge(df_wc, on="cell_id", how="left")
          .merge(df_dem, on="cell_id", how="left")
          .merge(df_slope, on="cell_id", how="left"))

    run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_csv = FEATURES_DIR / f"gee_features_sp_pt_grid{GRID_KM}km_{START_DATE}_to_{END_DATE}_{run_id}.csv"
    df.to_csv(out_csv, index=False)

    print("\n=== EDA SUMMARY ===")
    print("Rows (grid cells):", len(df))
    print("Columns:", list(df.columns))
    for col in ["NDVI_mean", "LC_mode", "elevation_mean", "slope_mean"]:
        if col in df.columns:
            print(f"Missing {col}: {df[col].isna().mean():.2%}")

    print("\nSaved CSV:", out_csv)
    print("Saved plots to:", PLOTS_DIR)

    print("\n11) Generating plots...")
    if "NDVI_mean" in df.columns:
        save_hist(df, "NDVI_mean", "ndvi_hist.png", "NDVI distribution (mean) - Spain+Portugal")
        save_geo_scatter(df, "NDVI_mean", "ndvi_map.png", "NDVI spatial pattern (grid centroids)")
    if "elevation_mean" in df.columns:
        save_hist(df, "elevation_mean", "elevation_hist.png", "Elevation distribution (mean) - Spain+Portugal")
    if "slope_mean" in df.columns:
        save_hist(df, "slope_mean", "slope_hist.png", "Slope distribution (mean) - Spain+Portugal")
    if "LC_mode" in df.columns:
        save_bar_counts(df, "LC_mode", "landcover_mode_counts.png", "Dominant land cover classes (mode) - Top 20")
    if all(c in df.columns for c in ["elevation_mean", "NDVI_mean"]):
        save_scatter(df, "elevation_mean", "NDVI_mean", "elevation_vs_ndvi.png", "Elevation vs NDVI")
    if all(c in df.columns for c in ["slope_mean", "NDVI_mean"]):
        save_scatter(df, "slope_mean", "NDVI_mean", "slope_vs_ndvi.png", "Slope vs NDVI")

    print("Done ✅")


if __name__ == "__main__":
    main()