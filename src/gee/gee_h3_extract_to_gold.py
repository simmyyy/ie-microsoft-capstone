import os
from pathlib import Path
from datetime import date
import math

import pandas as pd
import numpy as np
import ee
import h3


# =========================
# CONFIG (via env)
# =========================
REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_GOLD_DIR = REPO_ROOT / "data" / "gee" / "gold" / "gee_hex_features"

# Match gee_hex_terrain.ipynb; override with EE_PROJECT env var if needed
EE_PROJECT = os.environ.get("EE_PROJECT", "ie-microsoft-capstone")

COUNTRY_ISO2 = os.environ.get("GEE_COUNTRY", "ES")   # "ES" or "PT"
YEAR = int(os.environ.get("GEE_YEAR", "2024"))
H3_RES = int(os.environ.get("GEE_H3_RES", "6"))

# time window for that YEAR (recommended)
PERIOD_START = os.environ.get("GEE_PERIOD_START", f"{YEAR}-01-01")
PERIOD_END = os.environ.get("GEE_PERIOD_END", f"{YEAR}-12-31")
SNAPSHOT_DATE = os.environ.get("GEE_SNAPSHOT_DATE", str(date.today()))

# chunking to avoid payload limits
CHUNK_SIZE = int(os.environ.get("GEE_CHUNK_SIZE", "400"))
MAX_HEX = int(os.environ.get("GEE_MAX_HEX", "0"))  # 0 = all hexes

# scales
NDVI_SCALE_M = int(os.environ.get("GEE_NDVI_SCALE_M", "250"))
WC_SCALE_M = int(os.environ.get("GEE_WC_SCALE_M", "250"))
DEM_SCALE_M = int(os.environ.get("GEE_DEM_SCALE_M", "250"))


# =========================
# HELPERS
# =========================
def ee_init():
    try:
        ee.Initialize(project=EE_PROJECT)
    except Exception:
        ee.Authenticate()
        ee.Initialize(project=EE_PROJECT)


def iso2_to_gaul_name(iso2: str) -> str:
    # GAUL uses country names; keep it simple for ES/PT
    m = {"ES": "Spain", "PT": "Portugal"}
    if iso2 not in m:
        raise ValueError("Only ES/PT supported right now. Add mapping if needed.")
    return m[iso2]


def get_aoi_geometry(iso2: str) -> ee.Geometry:
    name = iso2_to_gaul_name(iso2)
    fc = ee.FeatureCollection("FAO/GAUL/2015/level0")
    return fc.filter(ee.Filter.eq("ADM0_NAME", name)).geometry()


def ee_geom_to_geojson_polygon(aoi: ee.Geometry) -> dict:
    # Keep it light to avoid huge payloads.
    # simplify() is enough for polyfill; buffer(0) can fail in EE.
    geom = aoi.simplify(1000)  # meters-ish tolerance in EE (works fine for country outlines)
    return geom.getInfo()


def geojson_to_h3_cells(geojson_geom: dict, res: int) -> list[str]:
    """
    Convert GeoJSON geometry (Polygon/MultiPolygon/GeometryCollection) to H3 cells.
    EE sometimes returns GeometryCollection for country geometries.
    """
    gtype = geojson_geom.get("type")

    def poly_to_cells(coords) -> set[str]:
        # coords: list of rings, each ring list of [lon, lat]
        outer = [(lat, lon) for lon, lat in coords[0]]
        holes = []
        for ring in coords[1:]:
            holes.append([(lat, lon) for lon, lat in ring])
        poly = h3.LatLngPoly(outer, *holes) if holes else h3.LatLngPoly(outer)
        return set(h3.polygon_to_cells(poly, res))

    def multipoly_to_cells(mcoords) -> set[str]:
        cells = set()
        for coords in mcoords:  # each polygon
            cells |= poly_to_cells(coords)
        return cells

    if gtype == "Polygon":
        return list(poly_to_cells(geojson_geom["coordinates"]))

    if gtype == "MultiPolygon":
        return list(multipoly_to_cells(geojson_geom["coordinates"]))

    if gtype == "GeometryCollection":
        cells = set()
        for g in geojson_geom.get("geometries", []):
            t = g.get("type")
            if t == "Polygon":
                cells |= poly_to_cells(g["coordinates"])
            elif t == "MultiPolygon":
                cells |= multipoly_to_cells(g["coordinates"])
            else:
                # ignore non-area geometries (LineString, Point, etc.)
                continue
        if not cells:
            raise ValueError("GeometryCollection contained no Polygon/MultiPolygon geometries.")
        return list(cells)

    raise ValueError(f"Unsupported geometry type: {gtype}")

def h3_cell_to_ee_feature(cell: str) -> ee.Feature:
    # h3 gives boundary as (lat,lon)
    boundary = h3.cell_to_boundary(cell)  # list of (lat, lon)
    # EE polygon expects [lon, lat]
    ring = [[lon, lat] for (lat, lon) in boundary]
    # close ring
    ring.append(ring[0])
    geom = ee.Geometry.Polygon([ring], proj=None, geodesic=False)
    return ee.Feature(geom, {"h3_index": cell})


def chunk_list(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]


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


def reduce_hex_features(hex_fc: ee.FeatureCollection, aoi: ee.Geometry):
    # Prepare images
    ndvi = s2_ndvi_mean(aoi, PERIOD_START, PERIOD_END).rename("NDVI")
    wc = worldcover(aoi).rename("LC")
    dem, slope = elevation_slope(aoi)

    # NDVI mean
    ndvi_fc = ndvi.reduceRegions(hex_fc, ee.Reducer.mean(), NDVI_SCALE_M, tileScale=4)\
                 .map(lambda f: ee.Feature(f).set("ndvi_mean", f.get("mean")).setGeometry(None))\
                 .select(["h3_index", "ndvi_mean"])

    # Elevation mean
    dem_fc = dem.reduceRegions(hex_fc, ee.Reducer.mean(), DEM_SCALE_M, tileScale=4)\
               .map(lambda f: ee.Feature(f).set("elevation_mean", f.get("mean")).setGeometry(None))\
               .select(["h3_index", "elevation_mean"])

    # Slope mean
    slope_fc = slope.reduceRegions(hex_fc, ee.Reducer.mean(), DEM_SCALE_M, tileScale=4)\
                   .map(lambda f: ee.Feature(f).set("slope_mean", f.get("mean")).setGeometry(None))\
                   .select(["h3_index", "slope_mean"])

    # Landcover mode
    lc_fc = wc.reduceRegions(hex_fc, ee.Reducer.mode(), WC_SCALE_M, tileScale=4)\
             .map(lambda f: ee.Feature(f).set("landcover_mode", f.get("mode")).setGeometry(None))\
             .select(["h3_index", "landcover_mode"])

    # Join results on h3_index using inner joins (safe)
    def fc_to_df(fc: ee.FeatureCollection, page_size: int = 500) -> pd.DataFrame:
        fc = fc.map(lambda f: f.setGeometry(None))
        rows = []
        req = {"expression": fc, "pageSize": page_size}
        while True:
            resp = ee.data.computeFeatures(req)
            feats = resp.get("features", [])
            rows.extend([f.get("properties", {}) for f in feats])
            token = resp.get("nextPageToken")
            if not token:
                break
            req["pageToken"] = token
        return pd.DataFrame(rows)

    df_ndvi = fc_to_df(ndvi_fc)
    df_dem = fc_to_df(dem_fc)
    df_slope = fc_to_df(slope_fc)
    df_lc = fc_to_df(lc_fc)

    df = df_ndvi.merge(df_dem, on="h3_index", how="left") \
                .merge(df_slope, on="h3_index", how="left") \
                .merge(df_lc, on="h3_index", how="left")

    return df


def write_gold(df: pd.DataFrame):
    df = df.copy()
    df["country"] = COUNTRY_ISO2
    df["year"] = YEAR
    df["h3_resolution"] = H3_RES
    df["snapshot_date"] = SNAPSHOT_DATE
    df["period_start"] = PERIOD_START
    df["period_end"] = PERIOD_END

    # Column order
    front = ["country", "year", "h3_resolution", "h3_index", "snapshot_date", "period_start", "period_end"]
    rest = [c for c in df.columns if c not in front]
    df = df[front + rest]

    out_dir = OUT_GOLD_DIR / f"country={COUNTRY_ISO2}" / f"year={YEAR}" / f"h3_resolution={H3_RES}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "part-00000.parquet"
    df.to_parquet(out_path, index=False)
    print("Wrote GOLD:", out_path, "| rows:", len(df))


def main():
    print("1) ee init...")
    ee_init()

    print(f"2) AOI for {COUNTRY_ISO2}...")
    aoi = get_aoi_geometry(COUNTRY_ISO2)

    print("3) Build H3 cover...")
    gj = ee_geom_to_geojson_polygon(aoi)
    cells = geojson_to_h3_cells(gj, H3_RES)
    cells = sorted(cells)

    if MAX_HEX and MAX_HEX > 0:
        cells = cells[:MAX_HEX]

    print("   hexes:", len(cells), "| res:", H3_RES)

    print("4) Reduce features by chunks...")
    all_parts = []
    for k, chunk in enumerate(chunk_list(cells, CHUNK_SIZE), start=1):
        print(f"   chunk {k}: {len(chunk)} hexes")
        feats = [h3_cell_to_ee_feature(c) for c in chunk]
        hex_fc = ee.FeatureCollection(feats)

        df_chunk = reduce_hex_features(hex_fc, aoi)
        all_parts.append(df_chunk)

    df = pd.concat(all_parts, ignore_index=True).drop_duplicates(subset=["h3_index"])
    print("5) Final df rows:", len(df))

    write_gold(df)
    print("Done ✅")


if __name__ == "__main__":
    main()