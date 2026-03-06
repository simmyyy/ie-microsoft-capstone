import math
from pathlib import Path
from datetime import datetime

import pandas as pd
import matplotlib.pyplot as plt
import ee

# =========================
# CONFIG
# =========================
COUNTRIES = ["Spain", "Portugal"]

GRID_KM = 15                 # prueba 15 o 10 si quieres más densidad
MAX_CELLS = 800              # se aplica DESPUÉS de filtrar por AOI

START_DATE = "2024-01-01"
END_DATE   = "2024-12-31"

SCALE_M = 250                # resolución de reducción (no es el tamaño del grid)

# Ajusta esto a tu proyecto de GEE (si no sabes cuál, deja None y te autentica igual)
EE_PROJECT_ID = None  # e.g. "tu-proyecto-id"

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "data" / "gee"
FEATURES_DIR = OUT_DIR / "features"
PLOTS_DIR = OUT_DIR / "plots"

# =========================
# HELPERS
# =========================
def ensure_dirs():
    FEATURES_DIR.mkdir(parents=True, exist_ok=True)
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

def ee_init():
    try:
        if EE_PROJECT_ID:
            ee.Initialize(project=EE_PROJECT_ID)
        else:
            ee.Initialize()
    except Exception:
        ee.Authenticate()
        if EE_PROJECT_ID:
            ee.Initialize(project=EE_PROJECT_ID)
        else:
            ee.Initialize()

def get_aoi():
    countries_fc = ee.FeatureCollection("FAO/GAUL/2015/level0")
    return countries_fc.filter(ee.Filter.inList("ADM0_NAME", COUNTRIES)).geometry()

def km_to_deg_lat(km):
    return km / 111.0

def km_to_deg_lon(km, lat_deg):
    return km / (111.0 * math.cos(math.radians(lat_deg)) + 1e-9)

def make_grid(bounds_geom: ee.Geometry, grid_km: float) -> ee.FeatureCollection:
    """
    Crea una grilla rectangular server-side.
    OJO: bounds_geom es un rectángulo; sacamos coords con getInfo() porque es pequeño.
    """
    coords = bounds_geom.coordinates().getInfo()[0]
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)

    step_lat = km_to_deg_lat(grid_km)
    mid_lat = (min_lat + max_lat) / 2
    step_lon = km_to_deg_lon(grid_km, mid_lat)

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
            centroid = rect.centroid(1).coordinates()
            cell_id = i.multiply(n_lon).add(j)

            return ee.Feature(rect, {
                "cell_id": cell_id,
                "centroid_lon": centroid.get(0),
                "centroid_lat": centroid.get(1),
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

    ndvi = (s2.map(lambda img: img.normalizedDifference(["B8", "B4"]).rename("NDVI"))
              .mean()
              .clip(aoi))
    return ndvi

def worldcover(aoi: ee.Geometry) -> ee.Image:
    return ee.ImageCollection("ESA/WorldCover/v200").first().select("Map").rename("LC").clip(aoi)

def elevation_slope(aoi: ee.Geometry):
    dem = ee.Image("USGS/SRTMGL1_003").select("elevation").rename("elevation").clip(aoi)
    slope = ee.Terrain.slope(dem).rename("slope").clip(aoi)
    return dem, slope

def reduce_mean(grid_fc, img, band, scale_m):
    fc = img.select([band]).reduceRegions(
        collection=grid_fc,
        reducer=ee.Reducer.mean(),
        scale=scale_m,
        tileScale=4
    )
    # quitamos geometría para evitar payload pesado
    return fc.map(lambda f: f.set(f"{band}_mean", f.get("mean")).setGeometry(None))

def reduce_mode(grid_fc, img, band, scale_m):
    fc = img.select([band]).reduceRegions(
        collection=grid_fc,
        reducer=ee.Reducer.mode(),
        scale=scale_m,
        tileScale=4
    )
    return fc.map(lambda f: f.set(f"{band}_mode", f.get("mode")).setGeometry(None))

def fc_to_df(fc: ee.FeatureCollection, page_size=400) -> pd.DataFrame:
    """
    Descarga paginada: evita el típico error de payload grande.
    """
    fc = fc.map(lambda f: f.setGeometry(None))
    req = {"expression": fc, "pageSize": page_size}
    rows = []

    while True:
        resp = ee.data.computeFeatures(req)
        feats = resp.get("features", [])
        rows.extend([f.get("properties", {}) for f in feats])

        token = resp.get("nextPageToken")
        if not token:
            break
        req["pageToken"] = token

    return pd.DataFrame(rows)

def save_plot_hist(df, col, out_name, title):
    x = df[col].dropna()
    plt.figure()
    plt.hist(x, bins=50)
    plt.title(title)
    plt.xlabel(col)
    plt.ylabel("count")
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / out_name, dpi=200)
    plt.close()

def save_plot_map(df, col, out_name, title):
    sub = df.dropna(subset=["centroid_lon", "centroid_lat", col])
    plt.figure()
    sc = plt.scatter(sub["centroid_lon"], sub["centroid_lat"], c=sub[col], s=8)
    plt.colorbar(sc, label=col)
    plt.title(title)
    plt.xlabel("lon")
    plt.ylabel("lat")
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / out_name, dpi=200)
    plt.close()

def main():
    ensure_dirs()

    print("1) EE init...")
    ee_init()

    print("2) AOI Spain+Portugal...")
    aoi = get_aoi()
    bounds = aoi.bounds()

    print(f"3) Build grid {GRID_KM} km (server-side)...")
    grid = make_grid(bounds, GRID_KM)

    # CLAVE: filtrar ANTES de limitar
    grid = grid.filterBounds(aoi)
    size_after = grid.size().getInfo()
    print("   Grid cells after filterBounds(AOI):", size_after)

    if MAX_CELLS:
        grid = ee.FeatureCollection(grid.toList(MAX_CELLS))
        print("   Grid cells after limit:", grid.size().getInfo())

    print("4) Datasets...")
    ndvi = s2_ndvi_mean(aoi, START_DATE, END_DATE).rename("NDVI")
    lc = worldcover(aoi)  # LC
    dem, slope = elevation_slope(aoi)

    print("5) Reduce NDVI mean...")
    fc_ndvi = reduce_mean(grid, ndvi, "NDVI", SCALE_M)

    print("6) Reduce LandCover mode...")
    fc_lc = reduce_mode(grid, lc, "LC", SCALE_M)

    print("7) Reduce elevation mean...")
    fc_dem = reduce_mean(grid, dem, "elevation", SCALE_M)

    print("8) Reduce slope mean...")
    fc_slope = reduce_mean(grid, slope, "slope", SCALE_M)

    print("9) Download paged...")
    df_ndvi = fc_to_df(fc_ndvi, page_size=250)
    df_lc = fc_to_df(fc_lc, page_size=600)
    df_dem = fc_to_df(fc_dem, page_size=250)
    df_slope = fc_to_df(fc_slope, page_size=250)

    print("10) Merge...")
    df = (df_ndvi[["cell_id", "centroid_lon", "centroid_lat", "NDVI_mean"]]
          .merge(df_lc[["cell_id", "LC_mode"]], on="cell_id", how="left")
          .merge(df_dem[["cell_id", "elevation_mean"]], on="cell_id", how="left")
          .merge(df_slope[["cell_id", "slope_mean"]], on="cell_id", how="left"))

    run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_csv = FEATURES_DIR / f"gee_sp_pt_grid{GRID_KM}km_{START_DATE}_to_{END_DATE}_{run_id}.csv"
    df.to_csv(out_csv, index=False)

    print("\nSaved CSV:", out_csv)
    print("Rows:", len(df))
    print("Missing NDVI:", df["NDVI_mean"].isna().mean())

    print("\n11) Plots...")
    save_plot_hist(df, "NDVI_mean", "ndvi_hist.png", "NDVI mean (S2) - Spain+Portugal")
    save_plot_map(df, "NDVI_mean", "ndvi_map.png", "NDVI mean map - Spain+Portugal")
    save_plot_hist(df, "elevation_mean", "elevation_hist.png", "Elevation mean - Spain+Portugal")
    save_plot_hist(df, "slope_mean", "slope_hist.png", "Slope mean - Spain+Portugal")

    print("Saved plots in:", PLOTS_DIR)
    print("Done ✅")

if __name__ == "__main__":
    main()