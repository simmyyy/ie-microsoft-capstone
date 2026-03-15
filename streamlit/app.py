#app.py
"""
GBIF Biodiversity Explorer – Streamlit app
==========================================
Visualises H3-based biodiversity metrics for Spain from the Gold layer.

Data path (S3):
  s3://ie-datalake/gold/gbif_cell_metrics/
    country=ES/year=YYYY/h3_resolution=N/*.parquet

Run:
  cd streamlit/
  streamlit run app.py
"""

from __future__ import annotations

import base64
import json
import warnings
from typing import Any
from pathlib import Path

from ui.styles_v2 import inject_css
from ui.components import header

import streamlit as st

# ── Dependency check ──────────────────────────────────────────────────────────
# Run BEFORE any other import so the error message is readable, not a traceback.
_REQUIRED = {
    "boto3": "boto3",
    "folium": "folium",
    "h3": "h3>=4.0.0",
    "pandas": "pandas",
    "s3fs": "s3fs",
    "streamlit_folium": "streamlit-folium",
}
_missing = []
for _mod, _pkg in _REQUIRED.items():
    try:
        __import__(_mod)
    except ImportError:
        _missing.append(_pkg)

if _missing:
    st.error(
        "**Missing dependencies** – install them and restart Streamlit:\n\n"
        f"```\npip install {' '.join(_missing)}\n```\n\n"
        "Or install everything at once:\n\n"
        "```\npip install -r streamlit/requirements.txt\n```"
    )
    st.stop()

# ── Standard imports (all deps confirmed present) ─────────────────────────────
import os
import boto3  # noqa: E402
from botocore.config import Config  # noqa: E402
import folium  # noqa: E402
import h3  # noqa: E402
import pandas as pd  # noqa: E402
import s3fs  # noqa: E402
from streamlit_folium import st_folium  # noqa: E402

# duckdb is optional – we fall back to s3fs+pandas if it's not installed
try:
    import duckdb

    _DUCKDB_AVAILABLE = True
except ImportError:
    duckdb = None  # type: ignore[assignment]
    _DUCKDB_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

S3_BUCKET = "ie-datalake"
GOLD_PREFIX = "gold/gbif_cell_metrics"
GOLD_H3_MAPPING = "gold/gbif_species_h3_mapping"
GOLD_SPECIES_DIM = "gold/gbif_species_dim"
GOLD_IUCN_PROFILES = "gold/iucn_species_profiles"
GOLD_OSM_HEX = "gold/osm_hex_features"
GOLD_NATURE2000 = "gold/nature2000_cell_protection"
GOLD_GEE_TERRAIN = "gold/gee_hex_terrain"
GEE_TERRAIN_SNAPSHOT = "2019"
NATURE2000_SNAPSHOT_DATE = "2026-02-27"
MAX_PROTECTED_HEXES_DISPLAY = 50_000
AWS_PROFILE = os.getenv("AWS_PROFILE", "") #"486717354268_PowerUserAccess"
COUNTRY = "ES"
MAX_CHOSEN_HEXES = 6
ENABLE_LANDING = True

# ── Demo / hardcoded settings ─────────────────────────────────────────────────
DEMO_YEAR = 2024  # hardcoded for demo; change to unlock year selector
DEMO_H3_OPTIONS = [6, 7]  # resolutions available in demo (6 ≈ 36 km², 7 ≈ 5 km²)
AVAILABLE_YEARS = [2024, 2023, 2022, 2021, 2020]

# Colorable metrics
COLOR_METRICS: list[str] = [
    "species_richness_cell",
    "observation_count",
    "shannon_H",
    "simpson_1_minus_D",
    "n_threatened_species",
]

# Metrics shown in the sidebar cell-detail panel (additional ones added if present)
DETAIL_METRICS: list[str] = [
    "h3_index",
    "observation_count",
    "species_richness_cell",
    "shannon_H",
    "simpson_1_minus_D",
    "n_threatened_species",
    "threat_score_weighted",
    "n_assessed_species",
    "avg_coordinate_uncertainty_m",
    "pct_uncertainty_gt_10km",
    "dqi",
]

# Choropleth colour scale (colorbrewer YlOrRd)
COLOR_SCALE: list[tuple[float, str]] = [
    (0.0, "#ffffb2"),
    (0.2, "#fed976"),
    (0.4, "#feb24c"),
    (0.6, "#fd8d3c"),
    (0.8, "#f03b20"),
    (1.0, "#bd0026"),
]

MAP_CENTER = [40.3, -3.7]  # centre of Spain
MAP_ZOOM = 6
MAX_HEXES_DEFAULT = 20_000
MAX_HEXES_CAP = 20_000

# Bedrock Agent (biodiversity risk analysis)
BEDROCK_AGENT_ID = "1XGKFMJE8D"
BEDROCK_AGENT_ALIAS_ID = "LFOSLYI9QF"  # ie-bio-agent alias ID
BEDROCK_REGION = "eu-west-2"


# ─────────────────────────────────────────────────────────────────────────────
# AWS / S3 helpers
# ─────────────────────────────────────────────────────────────────────────────


@st.cache_resource
def get_s3fs() -> s3fs.S3FileSystem:
    """Return a cached s3fs filesystem using the configured AWS profile."""
    s3fs.S3FileSystem.clear_instance_cache()
    return s3fs.S3FileSystem(profile=AWS_PROFILE)

@st.cache_resource
def get_duckdb_con():
    """
    Return an in-process DuckDB connection with the httpfs / S3 extension
    configured to use the current AWS SSO credentials.
    Returns None when duckdb is not installed (s3fs fallback will be used).
    """
    if not _DUCKDB_AVAILABLE:
        return None

    con = duckdb.connect(database=":memory:")
    con.execute("INSTALL httpfs; LOAD httpfs;")

    # Resolve credentials from the boto3 SSO profile (never hardcoded)
    session = boto3.Session(profile_name=AWS_PROFILE)
    creds = session.get_credentials().get_frozen_credentials()
    region = session.region_name or "eu-west-1"

    con.execute(f"SET s3_region='{region}';")
    con.execute(f"SET s3_access_key_id='{creds.access_key}';")
    con.execute(f"SET s3_secret_access_key='{creds.secret_key}';")
    if creds.token:
        con.execute(f"SET s3_session_token='{creds.token}';")

    return con


# ─────────────────────────────────────────────────────────────────────────────
# BEDROCK AGENT
# ─────────────────────────────────────────────────────────────────────────────


@st.cache_resource
def _get_bedrock_agent_client():
    """Return Bedrock Agent Runtime client."""
    session = boto3.Session(profile_name=AWS_PROFILE)
    cfg = Config(read_timeout=300, connect_timeout=30, retries={"mode": "adaptive"})
    return session.client(
        "bedrock-agent-runtime",
        region_name=BEDROCK_REGION,
        config=cfg,
    )


def invoke_bedrock_agent(
    prompt: str,
    session_id: str = "streamlit-session",
) -> str:
    """
    Invoke the biodiversity Bedrock agent and return the full response.
    """
    try:
        client = _get_bedrock_agent_client()
        response = client.invoke_agent(
            agentId=BEDROCK_AGENT_ID,
            agentAliasId=BEDROCK_AGENT_ALIAS_ID,
            sessionId=session_id,
            inputText=prompt,
        )
        completion = ""
        for event in response.get("completion", []):
            if "chunk" in event:
                completion += event["chunk"]["bytes"].decode("utf-8", errors="replace")
        return completion.strip() or "(No response)"
    except Exception as e:
        return f"*Error calling AI agent: {e}*"


# ─────────────────────────────────────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────────────────────────────────────


@st.cache_data(ttl=600, show_spinner="Loading gold data from S3…")
def load_data(h3_res: int, year: int) -> pd.DataFrame:
    """
    Load one (country, year, h3_resolution) partition from the gold layer.

    Primary path: DuckDB httpfs (fast, streaming scan from S3).
    Fallback: pyarrow.dataset with unify_schemas=True, which handles the common
    ArrowTypeError where the same column is encoded as dictionary<string> in
    one Parquet file and large_string in another (Hive partition schema drift).
    """
    import pyarrow.dataset as pa_ds
    import pyarrow as pa

    s3_path = (
        f"s3://{S3_BUCKET}/{GOLD_PREFIX}"
        f"/country={COUNTRY}/year={year}/h3_resolution={h3_res}/*.parquet"
    )

    con = get_duckdb_con()
    try:
        if con is None:
            raise RuntimeError("duckdb not available")
        df = con.execute(
            f"SELECT * FROM read_parquet('{s3_path}', hive_partitioning=true)"
        ).df()
    except Exception as exc:
        warnings.warn(f"DuckDB read failed ({exc}), falling back to pyarrow.dataset.")
        fs = get_s3fs()
        raw_path = (
            f"{S3_BUCKET}/{GOLD_PREFIX}"
            f"/country={COUNTRY}/year={year}/h3_resolution={h3_res}"
        )
        files = fs.glob(f"{raw_path}/*.parquet")
        if not files:
            return pd.DataFrame()

        # pyarrow.dataset with unify_schemas=True resolves schema mismatches
        # between Parquet files (e.g. large_string vs dictionary<string>).
        dataset = pa_ds.dataset(
            files,
            filesystem=fs,
            format="parquet",
            schema=None,  # let pyarrow infer per-file, then unify
        )
        # Cast every dictionary-encoded column to plain string before converting
        # to pandas – this is the root cause of the ArrowTypeError.
        table = dataset.to_table()
        cast_fields = []
        for field in table.schema:
            if pa.types.is_dictionary(field.type):
                cast_fields.append((field.name, pa.string()))
            elif field.type == pa.large_string():
                cast_fields.append((field.name, pa.string()))
        for col_name, target_type in cast_fields:
            col_idx = table.schema.get_field_index(col_name)
            table = table.set_column(
                col_idx, col_name, table.column(col_name).cast(target_type)
            )
        df = table.to_pandas()

    # Inject partition keys if they were stripped by Hive partitioning
    if "country" not in df.columns:
        df["country"] = COUNTRY
    if "year" not in df.columns:
        df["year"] = year
    if "h3_resolution" not in df.columns:
        df["h3_resolution"] = h3_res

    return df


@st.cache_data(ttl=600, show_spinner="Loading species H3 mapping…")
def _load_h3_mapping_full(h3_res: int, year: int) -> pd.DataFrame:
    """Load full gbif_species_h3_mapping partition (cached)."""
    s3_path = (
        f"s3://{S3_BUCKET}/{GOLD_H3_MAPPING}"
        f"/country={COUNTRY}/year={year}/h3_resolution={h3_res}/*.parquet"
    )
    con = get_duckdb_con()
    try:
        if con:
            return con.execute(
                f"SELECT * FROM read_parquet('{s3_path}', hive_partitioning=true)"
            ).df()
    except Exception:
        pass
    fs = get_s3fs()
    files = fs.glob(
        f"{S3_BUCKET}/{GOLD_H3_MAPPING}/country={COUNTRY}/year={year}/h3_resolution={h3_res}/*.parquet"
    )
    if not files:
        return pd.DataFrame()
    dfs = []
    for path in files:
        with fs.open(path, "rb") as fh:
            dfs.append(pd.read_parquet(fh))
    return pd.concat(dfs, ignore_index=True)


def load_h3_mapping(h3_res: int, year: int, h3_indexes: list[str]) -> pd.DataFrame:
    """Load gbif_species_h3_mapping filtered to given hexes."""
    df = _load_h3_mapping_full(h3_res, year)
    if df.empty or not h3_indexes:
        return df
    return df[df["h3_index"].isin(h3_indexes)]


@st.cache_data(ttl=600, show_spinner="Loading multi-year metrics…")
def load_multiyear_metrics_hex(
    h3_res: int, h3_index: str, years: list[int] | None = None
) -> pd.DataFrame:
    """Load gbif_cell_metrics for a single hex across multiple years."""
    years = years or AVAILABLE_YEARS
    dfs = []
    for y in years:
        df = load_data(h3_res, y)
        if df.empty or "h3_index" not in df.columns:
            continue
        m = df[df["h3_index"] == h3_index]
        if not m.empty:
            dfs.append(m)
    if not dfs:
        return pd.DataFrame()
    out = pd.concat(dfs, ignore_index=True).sort_values("year")
    return out


@st.cache_data(ttl=600, show_spinner="Loading multi-year species mapping…")
def load_multiyear_species_h3_mapping_hex(
    h3_res: int, h3_index: str, years: list[int] | None = None
) -> pd.DataFrame:
    """Load gbif_species_h3_mapping for a single hex across multiple years."""
    years = years or AVAILABLE_YEARS
    dfs = []
    for y in years:
        df = _load_h3_mapping_full(h3_res, y)
        if df.empty:
            continue
        m = df[df["h3_index"] == h3_index]
        if not m.empty:
            m = m.copy()
            m["year"] = y
            dfs.append(m)
    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)


def load_h3_mapping_by_taxon(h3_res: int, year: int, taxon_key: int) -> pd.DataFrame:
    """Load gbif_species_h3_mapping filtered to a single species (taxon_key)."""
    df = _load_h3_mapping_full(h3_res, year)
    if df.empty or "taxon_key" not in df.columns:
        return df
    # Robust comparison: parquet may have int32/int64/Int64
    tk = pd.to_numeric(df["taxon_key"], errors="coerce")
    mask = (tk == int(taxon_key)) & tk.notna()
    return df.loc[mask]


@st.cache_data(ttl=600, show_spinner="Loading Natura 2000 protected areas…")
def load_nature2000_protected_areas(h3_res: int) -> pd.DataFrame:
    """Load gold nature2000_cell_protection for country=ES at given resolution."""
    fs = get_s3fs()
    raw_path = (
        f"{S3_BUCKET}/{GOLD_NATURE2000}"
        f"/country={COUNTRY}/h3_resolution={h3_res}/snapshot_date={NATURE2000_SNAPSHOT_DATE}"
    )
    files = fs.glob(f"{raw_path}/*.parquet")
    if not files:
        return pd.DataFrame()
    dfs = []
    for path in files:
        with fs.open(path, "rb") as fh:
            dfs.append(pd.read_parquet(fh))
    df = pd.concat(dfs, ignore_index=True)
    return df


@st.cache_data(ttl=600, show_spinner="Loading GEE terrain…")
def load_gee_terrain(h3_res: int) -> pd.DataFrame:
    """Load gold gee_hex_terrain: elevation_mean, slope_mean, lc_*_pct (land cover %)."""
    fs = get_s3fs()
    raw_path = (
        f"{S3_BUCKET}/{GOLD_GEE_TERRAIN}"
        f"/country={COUNTRY}/snapshot={GEE_TERRAIN_SNAPSHOT}/h3_resolution={h3_res}"
    )
    files = fs.glob(f"{raw_path}/*.parquet")
    if not files:
        return pd.DataFrame()
    dfs = []
    for path in files:
        with fs.open(path, "rb") as fh:
            dfs.append(pd.read_parquet(fh))
    df = pd.concat(dfs, ignore_index=True)
    if "h3_id" in df.columns and "h3_index" not in df.columns:
        df = df.rename(columns={"h3_id": "h3_index"})
    return df


@st.cache_data(ttl=600, show_spinner="Loading species dim…")
def load_species_dim(year: int) -> pd.DataFrame:
    """Load gbif_species_dim for species names."""
    s3_path = (
        f"s3://{S3_BUCKET}/{GOLD_SPECIES_DIM}/country={COUNTRY}/year={year}/*.parquet"
    )
    con = get_duckdb_con()
    try:
        if con:
            return con.execute(
                f"SELECT * FROM read_parquet('{s3_path}', hive_partitioning=true)"
            ).df()
    except Exception:
        pass
    fs = get_s3fs()
    files = fs.glob(
        f"{S3_BUCKET}/{GOLD_SPECIES_DIM}/country={COUNTRY}/year={year}/*.parquet"
    )
    if not files:
        return pd.DataFrame()
    dfs = []
    for path in files:
        with fs.open(path, "rb") as fh:
            dfs.append(pd.read_parquet(fh))
    return pd.concat(dfs, ignore_index=True)


@st.cache_data(ttl=600, show_spinner="Loading IUCN profiles…")
def load_iucn_profiles(year: int) -> pd.DataFrame:
    """Load iucn_species_profiles for rationale (scientific_name, rationale)."""
    s3_path = (
        f"s3://{S3_BUCKET}/{GOLD_IUCN_PROFILES}/country={COUNTRY}/year={year}/*.parquet"
    )
    con = get_duckdb_con()
    try:
        if con:
            df = con.execute(
                f"SELECT scientific_name, rationale, iucn_category FROM read_parquet('{s3_path}', hive_partitioning=true)"
            ).df()
            return df
    except Exception:
        pass
    fs = get_s3fs()
    files = fs.glob(
        f"{S3_BUCKET}/{GOLD_IUCN_PROFILES}/country={COUNTRY}/year={year}/*.parquet"
    )
    if not files:
        return pd.DataFrame()
    try:
        dfs = []
        for path in files:
            with fs.open(path, "rb") as fh:
                dfs.append(pd.read_parquet(fh))
        df = pd.concat(dfs, ignore_index=True)
    except Exception:
        return pd.DataFrame()
    cols = [
        c for c in ["scientific_name", "rationale", "iucn_category"] if c in df.columns
    ]
    return df[cols] if cols else pd.DataFrame()


@st.cache_data(ttl=600, show_spinner="Loading IUCN profiles (full)…")
def load_iucn_profiles_full(year: int) -> pd.DataFrame:
    """Load iucn_species_profiles with all rich text columns for species map tab."""
    iucn_cols = [
        "scientific_name",
        "rationale",
        "habitat_ecology",
        "population",
        "range_description",
        "threats_text",
        "conservation_text",
        "iucn_category",
        "iucn_category_description",
        "population_trend",
    ]
    s3_path = (
        f"s3://{S3_BUCKET}/{GOLD_IUCN_PROFILES}/country={COUNTRY}/year={year}/*.parquet"
    )
    con = get_duckdb_con()
    try:
        if con:
            cols_str = ", ".join(iucn_cols)
            return con.execute(
                f"SELECT {cols_str} FROM read_parquet('{s3_path}', hive_partitioning=true)"
            ).df()
    except Exception:
        pass
    fs = get_s3fs()
    files = fs.glob(
        f"{S3_BUCKET}/{GOLD_IUCN_PROFILES}/country={COUNTRY}/year={year}/*.parquet"
    )
    if not files:
        return pd.DataFrame()
    try:
        dfs = []
        for path in files:
            with fs.open(path, "rb") as fh:
                dfs.append(pd.read_parquet(fh))
        df = pd.concat(dfs, ignore_index=True)
    except Exception:
        return pd.DataFrame()
    cols = [c for c in iucn_cols if c in df.columns]
    return df[cols] if cols else pd.DataFrame()


@st.cache_data(ttl=600, show_spinner="Loading OSM hex features…")
def load_osm_hex_features(h3_res: int, h3_indexes: list[str]) -> pd.DataFrame:
    """
    Load OSM gold layer (osm_hex_features) for selected hexes.
    Path: s3://ie-datalake/gold/osm_hex_features/country=ES/h3_resolution=N/
    """
    import pyarrow.dataset as pa_ds
    import pyarrow as pa

    if not h3_indexes:
        return pd.DataFrame()

    s3_path = (
        f"s3://{S3_BUCKET}/{GOLD_OSM_HEX}"
        f"/country={COUNTRY}/h3_resolution={h3_res}/*.parquet"
    )

    con = get_duckdb_con()
    try:
        if con is not None:
            placeholders = ", ".join([f"'{h}'" for h in h3_indexes])
            df = con.execute(
                f"SELECT * FROM read_parquet('{s3_path}', hive_partitioning=true) "
                f"WHERE h3_index IN ({placeholders})"
            ).df()
            return df
    except Exception:
        pass

    # Fallback: load full partition, filter in pandas
    fs = get_s3fs()
    raw_path = f"{S3_BUCKET}/{GOLD_OSM_HEX}/country={COUNTRY}/h3_resolution={h3_res}"
    files = fs.glob(f"{raw_path}/*.parquet")
    if not files:
        return pd.DataFrame()

    dataset = pa_ds.dataset(files, filesystem=fs, format="parquet")
    table = dataset.to_table()
    # Cast dict/large_string to string (schema drift)
    cast_fields = []
    for field in table.schema:
        if pa.types.is_dictionary(field.type) or field.type == pa.large_string():
            cast_fields.append((field.name, pa.string()))
    for col_name, target_type in cast_fields:
        col_idx = table.schema.get_field_index(col_name)
        table = table.set_column(
            col_idx, col_name, table.column(col_name).cast(target_type)
        )
    df = table.to_pandas()

    if "h3_index" in df.columns and h3_indexes:
        df = df[df["h3_index"].isin(h3_indexes)]
    return df


# ─────────────────────────────────────────────────────────────────────────────
# LAYER PREPARATION
# ─────────────────────────────────────────────────────────────────────────────


def _metric_to_color(value: float, vmin: float, vmax: float) -> str:
    """Map a scalar metric value to a hex colour using the COLOR_SCALE."""
    if vmax == vmin:
        t = 0.0
    else:
        t = max(0.0, min(1.0, (value - vmin) / (vmax - vmin)))

    # Linear interpolation between colour stops
    for i in range(len(COLOR_SCALE) - 1):
        t0, c0 = COLOR_SCALE[i]
        t1, c1 = COLOR_SCALE[i + 1]
        if t <= t1:
            frac = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            r = int(int(c0[1:3], 16) + frac * (int(c1[1:3], 16) - int(c0[1:3], 16)))
            g = int(int(c0[3:5], 16) + frac * (int(c1[3:5], 16) - int(c0[3:5], 16)))
            b = int(int(c0[5:7], 16) + frac * (int(c1[5:7], 16) - int(c0[5:7], 16)))
            return f"#{r:02x}{g:02x}{b:02x}"
    return COLOR_SCALE[-1][1]


def prepare_layer(
    df: pd.DataFrame,
    color_metric: str,
    max_hexes: int,
    mode: str = "top_n",
    snapshot_bounds: dict | None = None,
) -> tuple[pd.DataFrame, bool, str]:
    """
    Select rows for rendering.

    mode="top_n"             – top-N by the colour metric (capped at max_hexes).
    mode="request_bounds"    – transient: same as top_n while we wait for one
                               bounds snapshot to come back from the browser.
    mode="viewport_snapshot" – ALL cells whose H3 centre falls inside the
                               snapshot bounds captured on button click.

    Returns: (df_layer, was_sampled, mode_used)
    """
    import numpy as np

    if df.empty:
        return df, False, mode

    if color_metric not in df.columns:
        color_metric = "observation_count"

    df = df.copy()
    df[color_metric] = pd.to_numeric(df[color_metric], errors="coerce").fillna(0)

    # ── Viewport snapshot: filter to cells inside the captured bounds ─────────
    if mode == "viewport_snapshot" and snapshot_bounds:
        sw = snapshot_bounds.get("_southWest", {})
        ne = snapshot_bounds.get("_northEast", {})
        if sw and ne:
            lat_min, lat_max = float(sw["lat"]), float(ne["lat"])
            lng_min, lng_max = float(sw["lng"]), float(ne["lng"])

            h3_cells = df["h3_index"].to_numpy(dtype=str)
            latlngs = np.array([h3.cell_to_latlng(c) for c in h3_cells])
            lat_arr, lng_arr = latlngs[:, 0], latlngs[:, 1]

            mask = (
                (lat_arr >= lat_min)
                & (lat_arr <= lat_max)
                & (lng_arr >= lng_min)
                & (lng_arr <= lng_max)
            )
            df_vp = df[mask]
            if not df_vp.empty:
                return df_vp, False, "viewport_snapshot"
        # fell through (no bounds or empty result) → fall back to top_n

    # ── Top-N (default and request_bounds transient state) ────────────────────
    was_sampled = len(df) > max_hexes
    if was_sampled:
        df = df.nlargest(max_hexes, color_metric)
    return df, was_sampled, "top_n"


def _h3_boundary_latlon(h3_index: str) -> list[list[float]]:
    """
    Return H3 cell boundary as [[lat, lon], ...] for Folium.
    h3-py ≥4 returns (lat, lng) tuples from h3.cell_to_boundary().
    """
    boundary = h3.cell_to_boundary(h3_index)  # list of (lat, lng)
    # Close the polygon ring for GeoJSON
    coords = [[lat, lng] for lat, lng in boundary]
    coords.append(coords[0])
    return coords


def build_geojson_from_h3_cells(
    df: pd.DataFrame,
    occurrence_col: str = "occurrence_count",
    fill_color: str = "#2e86ab",
) -> dict[str, Any]:
    """
    Build GeoJSON from H3 cells (e.g. species occurrence map).
    Colors by occurrence_count if present, else uniform fill_color.
    """
    if df.empty or "h3_index" not in df.columns:
        return {"type": "FeatureCollection", "features": []}

    occ = occurrence_col if occurrence_col in df.columns else None
    if occ:
        values = df[occurrence_col].fillna(0).astype(float)
        vmin, vmax = float(values.min()), float(values.max())

    features: list[dict] = []
    for _, row in df.iterrows():
        h3_idx = str(row.get("h3_index", ""))
        if not h3_idx:
            continue
        try:
            boundary = _h3_boundary_latlon(h3_idx)
        except Exception:
            continue

        if occ:
            val = float(row.get(occurrence_col) or 0)
            color = _metric_to_color(val, vmin, vmax)
        else:
            color = fill_color

        props: dict[str, Any] = {"h3_index": h3_idx, "_color": color}
        if occ:
            props[occurrence_col] = float(row.get(occurrence_col) or 0)
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[lng, lat] for lat, lng in boundary]],
                },
                "properties": props,
            }
        )

    return {"type": "FeatureCollection", "features": features}


def build_geojson_layer(
    df: pd.DataFrame,
    color_metric: str,
) -> dict[str, Any]:
    """
    Convert a DataFrame of H3 cells into a GeoJSON FeatureCollection.

    Each feature carries ALL metric columns as properties so the click handler
    can display a rich info panel without a second lookup.
    """
    if df.empty:
        return {"type": "FeatureCollection", "features": []}

    metric_col = color_metric if color_metric in df.columns else "observation_count"
    values = df[metric_col].fillna(0).astype(float)
    vmin, vmax = float(values.min()), float(values.max())

    features: list[dict] = []
    # Use to_dict("records") – works with any column name, no getattr fragility
    for record in df.to_dict("records"):
        h3_idx = str(record.get("h3_index", ""))
        if not h3_idx:
            continue
        try:
            boundary = _h3_boundary_latlon(h3_idx)
        except Exception:
            continue

        val = float(record.get(metric_col) or 0)
        color = _metric_to_color(val, vmin, vmax)

        props: dict[str, Any] = {k: _safe_scalar(v) for k, v in record.items()}
        props["_color"] = color
        props["_metric_value"] = val

        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    # GeoJSON coordinates are [lon, lat]; boundary is [[lat, lon], ...]
                    "coordinates": [[[lng, lat] for lat, lng in boundary]],
                },
                "properties": props,
            }
        )

    return {"type": "FeatureCollection", "features": features}


def _safe_scalar(v: Any) -> Any:
    """
    Convert any scalar to a plain Python type safe for json.dumps().
    Handles: pd.NA, pd.NaT, np.integer, np.floating, np.bool_, float NaN/Inf.
    """
    # Catch pd.NA, pd.NaT, and any other pandas NA sentinel
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass  # pd.isna raises on non-scalar iterables

    import numpy as np

    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        f = float(v)
        return None if (f != f or f == float("inf") or f == float("-inf")) else f
    if isinstance(v, np.bool_):
        return bool(v)
    # Plain Python int/float edge cases
    if isinstance(v, float) and (v != v or v == float("inf") or v == float("-inf")):
        return None
    return v


# ─────────────────────────────────────────────────────────────────────────────
# MAP CONSTRUCTION
# ─────────────────────────────────────────────────────────────────────────────


def build_geojson_protected_areas(df: pd.DataFrame) -> dict[str, Any]:
    """
    Build GeoJSON from nature2000 gold: green = protected, yellow = near protected.
    Each feature carries all columns as properties for click popup.
    """
    if df.empty or "h3_id" not in df.columns:
        return {"type": "FeatureCollection", "features": []}

    COLOR_PROTECTED = "#22c55e"  # green
    COLOR_NEAR = "#eab308"  # yellow

    features: list[dict] = []
    for record in df.to_dict("records"):
        h3_idx = str(record.get("h3_id", ""))
        if not h3_idx:
            continue
        try:
            boundary = _h3_boundary_latlon(h3_idx)
        except Exception:
            continue

        is_prot = str(record.get("is_protected_area", "")).lower() == "yes"
        color = COLOR_PROTECTED if is_prot else COLOR_NEAR

        props: dict[str, Any] = {k: _safe_scalar(v) for k, v in record.items()}
        props["_color"] = color

        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[lng, lat] for lat, lng in boundary]],
                },
                "properties": props,
            }
        )

    return {"type": "FeatureCollection", "features": features}


def make_map_protected_areas(
    geojson: dict[str, Any],
    center: list[float] = MAP_CENTER,
    zoom: int = MAP_ZOOM,
) -> folium.Map:
    """Folium map for protected areas: green/yellow hexes with tooltip."""
    m = folium.Map(
        location=center,
        zoom_start=zoom,
        tiles="OpenStreetMap",
        prefer_canvas=True,
    )

    if geojson["features"]:
        folium.GeoJson(
            data=json.dumps(geojson),
            name="Protected Areas",
            style_function=lambda f: {
                "fillColor": f["properties"].get("_color", "#cccccc"),
                "color": "#444444",
                "weight": 0.4,
                "fillOpacity": 0.65,
            },
            highlight_function=lambda f: {
                "weight": 2,
                "color": "#000000",
                "fillOpacity": 0.85,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=[
                    "is_protected_area",
                    "nearest_protected_distance",
                    "site_name",
                    "nearest_site_name",
                ],
                aliases=["Status", "Distance (hexes)", "Site", "Nearest site"],
                localize=True,
            ),
        ).add_to(m)

        legend_html = """
        <div style="
            position: fixed; bottom: 30px; right: 30px; z-index: 9999;
            background: white; padding: 10px 14px; border-radius: 6px;
            box-shadow: 0 2px 6px rgba(0,0,0,.35); font-size: 12px;
        ">
            <b>Protected Areas</b><br>
            <span style="color:#22c55e">●</span> protected<br>
            <span style="color:#eab308">●</span> near protected
        </div>
        """
        m.get_root().html.add_child(folium.Element(legend_html))

    return m


def make_map(
    geojson: dict[str, Any],
    show_overlay: bool,
    color_metric: str,
    center: list[float] = MAP_CENTER,
    zoom: int = MAP_ZOOM,
) -> folium.Map:
    """
    Build a Folium map with an optional H3 hex GeoJSON overlay.

    No highlight on selection – chosen hexes are only in the list, map does not re-style.
    Click capture is handled via streamlit-folium's last_clicked mechanism.
    """
    m = folium.Map(
        location=center,
        zoom_start=zoom,
        tiles="OpenStreetMap",
        prefer_canvas=True,
    )

    if show_overlay and geojson["features"]:
        folium.GeoJson(
            data=json.dumps(geojson),
            name="H3 Cells",
            style_function=lambda feature: {
                "fillColor": feature["properties"].get("_color", "#cccccc"),
                "color": "#444444",
                "weight": 0.4,
                "fillOpacity": 0.65,
            },
            highlight_function=lambda feature: {
                "weight": 2,
                "color": "#000000",
                "fillOpacity": 0.85,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=[color_metric],
                aliases=[color_metric.replace("_", " ").title()],
                localize=True,
            ),
        ).add_to(m)

        # Colour legend (simple HTML)
        _add_legend(m, color_metric)

    return m


def _add_legend(m: folium.Map, metric_name: str) -> None:
    """Inject a simple gradient HTML legend into the Folium map."""
    gradient = ", ".join(c for _, c in COLOR_SCALE)
    html = f"""
    <div style="
        position: fixed; bottom: 30px; right: 30px; z-index: 9999;
        background: white; padding: 10px 14px; border-radius: 6px;
        box-shadow: 0 2px 6px rgba(0,0,0,.35); font-size: 12px;
    ">
      <b>{metric_name.replace("_", " ").title()}</b><br>
      <div style="
        width: 160px; height: 14px; margin-top: 4px;
        background: linear-gradient(to right, {gradient});
        border-radius: 3px;
      "></div>
      <div style="display:flex; justify-content:space-between; margin-top:2px;">
        <span>low</span><span>high</span>
      </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(html))


# ─────────────────────────────────────────────────────────────────────────────
# CLICK RESOLUTION
# ─────────────────────────────────────────────────────────────────────────────


def resolve_click_to_cell(
    click_lat: float,
    click_lon: float,
    h3_res: int,
) -> str:
    """
    Convert a map click (lat, lon) to the H3 cell index at the given resolution.

    This fallback guarantees that clicks always produce a cell lookup even when
    GeoJSON polygon click events are not captured by streamlit-folium.
    """
    return h3.latlng_to_cell(click_lat, click_lon, h3_res)


def lookup_cell(df: pd.DataFrame, h3_index: str) -> pd.Series | None:
    """Return the row for a given h3_index, or None if not found."""
    if df.empty or "h3_index" not in df.columns:
        return None
    mask = df["h3_index"] == h3_index
    if mask.any():
        return df[mask].iloc[0]
    return None


def lookup_protected_cell(df: pd.DataFrame, h3_id: str) -> pd.Series | None:
    """Return the row for a given h3_id in nature2000 gold, or None if not found."""
    if df.empty or "h3_id" not in df.columns:
        return None
    mask = df["h3_id"].astype(str) == str(h3_id)
    if mask.any():
        return df[mask].iloc[0]
    return None


# ─────────────────────────────────────────────────────────────────────────────
# STREAMLIT UI
# ─────────────────────────────────────────────────────────────────────────────


def format_metric(value: Any) -> str:
    """Format a metric value for sidebar display."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    if isinstance(value, float):
        return f"{value:,.4f}" if abs(value) < 10 else f"{value:,.1f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)

def render_app_navbar():
    ss = st.session_state

    # Logo
    logo_path = Path(__file__).parent / "ui" / "assets" / "logo_white.png"
    if not logo_path.exists():
        logo_path = Path(__file__).parent / "ui" / "assets" / "logo_mini.png"

    logo_b64 = ""
    if logo_path.exists():
        logo_b64 = base64.b64encode(logo_path.read_bytes()).decode("utf-8")

    NAV_H = 76  # px, ajusta si cambias padding/tamaño de logo

    st.markdown(
        f"""
        <style>
        :root{{
          --stroke: rgba(255,255,255,0.12);
          --text: rgba(255,255,255,0.92);
          --muted: rgba(255,255,255,0.72);
          --card: rgba(255,255,255,0.06);
          --accent1: rgba(223, 135, 79, 0.75);
          --accent2: rgba(159, 196, 53, 0.65);
        }}

        header[data-testid="stHeader"] {{ display: none; }}

        /* Full-width page so navbar reaches edges */
        .block-container {{
          max-width: 100% !important;
          padding-left: 0 !important;
          padding-right: 0 !important;
          padding-top: 0 !important;
        }}

        /* Sticky/fixed glass navbar */
        .topnav {{
          position: fixed;
          top: 0; left: 0; right: 0;
          z-index: 1000000;
          height: 120px;

          padding: 20px 22px;
          display: flex;
          align-items: center;
          justify-content: space-between;

          background: rgba(8, 12, 20, 0.55);
          backdrop-filter: blur(10px);
          -webkit-backdrop-filter: blur(10px);

          border-bottom: 1px solid rgba(255,255,255,0.10);
          border-radius: 0 !important;
          margin: 0 !important;
        }}

        .brand {{
          display:flex;
          align-items:center;
          gap: 12px;
          color: var(--text);
          font-weight: 800;
          letter-spacing: -0.02em;
          font-size: 17px;
          padding-left: 18px;
          min-width: 0;
        }}

        .brand-logo {{
          height: 80px;
          width: auto;
          display:block;
        }}

        .navlinks {{
          display:flex;
          gap: 18px;
          align-items:center;
          color: var(--muted);
          font-size: 14px;
        }}

        .navlinks a {{
          color: var(--muted);
          text-decoration: none;
          font-size: 16px;
          padding: 4px 4px;
          border-radius: 10px;
        }}
        .navlinks a:hover {{
          background: rgba(255,255,255,0.06);
          color: var(--text);
        }}

        .nav-actions {{
          display:flex;
          gap: 10px;
          align-items:center;
          padding-right: 18px;
        }}

        /* Make Streamlit buttons look like landing pills */
        .nav-actions .stButton>button {{
          padding: 9px 14px !important;
          border-radius: 999px !important;
          font-size: 18px !important;
          line-height: 1 !important;
          font-weight: 650 !important;
          border: 1px solid var(--stroke) !important;
          background: var(--card) !important;
          color: var(--text) !important;
          width: auto !important;
        }}
        .nav-actions .home-btn .stButton>button {{
          border: none !important;
          background: linear-gradient(90deg, var(--accent1), var(--accent2)) !important;
          color: rgba(6,18,26,0.95) !important;
          font-weight: 850 !important;
        }}
        .btn {{
            padding: 9px 14px; border-radius: 999px;
            border: 1px solid var(--stroke);
            background: var(--card);
            color: var(--text);
            font-weight: 650;
            font-size: 18px;
        }}
        .btn-primary {{
            border: none;
            background: linear-gradient(90deg, var(--accent1), var(--accent2));
        }}

        /* Spacer so content starts below fixed navbar */
        .nav-spacer {{
          height: {NAV_H}px;
        }}

        /* Optional: subtle top fade line like premium apps */
        .nav-glow {{
          position: fixed;
          top: {NAV_H}px; left: 0; right: 0;
          height: 16px;
          pointer-events: none;
          background: linear-gradient(to bottom, rgba(0,0,0,0.22), rgba(0,0,0,0));
          z-index: 9999;
        }}
        </style>

        <div class="topnav">
          <div class="brand">
            <img class="brand-logo" src="data:image/png;base64,{logo_b64}" />
            <span>GBIF Biodiversity Explorer</span>
          </div>

          <div class="navlinks">
            <a href="#services">Services</a>
            <a href="#data">Data</a>
            <a href="#resources">Resources</a>
            <a href="#about">About</a>
          </div>

          <div class="nav-actions">
            <div class="btn">Login</div>
            <div class="btn btn-primary">Home</div>
          </div>
        </div>
        <div class="nav-glow"></div>
        <div class="nav-spacer"></div>
        """,
        unsafe_allow_html=True,
    )

    # Real buttons (so Home works)
    # We place them immediately after; CSS makes them look like they are in the bar.
    c1, c2, c3 = st.columns([0.76, 0.12, 0.12])


def render_sidebar() -> tuple[bool, int, str, int, int]:
    st.sidebar.markdown("### 🌿 Biodiversity Explorer")
    st.sidebar.markdown("<div class='muted'>Spain • GBIF Gold layer</div>", unsafe_allow_html=True)
    st.sidebar.divider()

    st.sidebar.markdown("**Controls**")
    show_overlay = st.sidebar.checkbox("Show H3 overlay", value=True)

    st.sidebar.selectbox("Year", options=[DEMO_YEAR], disabled=True)
    selected_year = DEMO_YEAR

    h3_res = st.sidebar.select_slider(
        "H3 resolution",
        options=DEMO_H3_OPTIONS,
        value=DEMO_H3_OPTIONS[0],
    )

    color_metric = st.sidebar.selectbox(
        "Colour metric",
        options=COLOR_METRICS,
        format_func=lambda m: m.replace("_", " ").title(),
        disabled=not show_overlay,
    )

    max_hexes = MAX_HEXES_DEFAULT
    st.sidebar.caption(f"Max hexes: **{MAX_HEXES_DEFAULT:,}** (demo)")

    st.sidebar.divider()
    st.sidebar.markdown("**AI**")
    chat_open = st.sidebar.checkbox("Enable AI chat", value=False, key="chat_panel_open")

    with st.sidebar.expander("Data status", expanded=False):
        st.write(f"AWS_PROFILE: `{AWS_PROFILE or 'default'}`")
        st.write(f"DuckDB: `{'available' if _DUCKDB_AVAILABLE else 'fallback'}`")

    with st.sidebar.expander("Demo limitations", expanded=False):
        st.caption("Year locked to 2024 • Resolutions limited to 6–7 • Max hexes fixed.")
    
    return show_overlay, h3_res, color_metric, max_hexes, selected_year, chat_open


def render_chat_panel(_h3_res: int, _chosen_hexes: set[str]) -> None:
    """Render collapsible chat panel with Bedrock biodiversity agent."""
    st.markdown("#### 💬 AI Biodiversity Assistant")
    st.caption("Ask about biodiversity risk, species, or hex analysis.")

    ss = st.session_state
    if "chat_messages" not in ss:
        ss["chat_messages"] = []
    if "chat_session_id" not in ss:
        import uuid

        ss["chat_session_id"] = str(uuid.uuid4())[:8]

    for msg in ss["chat_messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Ask about biodiversity…"):
        ss["chat_messages"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                response = invoke_bedrock_agent(
                    prompt,
                    session_id=f"streamlit-{ss['chat_session_id']}",
                )
            st.markdown(response)
            ss["chat_messages"].append({"role": "assistant", "content": response})


def render_chosen_card(chosen_hexes: set[str], h3_res: int) -> None:
    import streamlit as st
    from html import escape

    ss = st.session_state
    hex_list = sorted(list(chosen_hexes))
    n = len(hex_list)
    MAX_SLOTS = MAX_CHOSEN_HEXES

    st.markdown(
        """
        <style>
        div[data-testid="stVerticalBlock"]:has(#chosen-card-anchor) {
          padding: 16px 18px !important;
          border-radius: 38px !important;
          background: linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.01)) !important;
          border: 1px solid rgba(255,255,255,0.07) !important;
          box-shadow: 0 10px 32px rgba(0,0,0,0.45) !important;
          backdrop-filter: blur(8px) !important;
          -webkit-backdrop-filter: blur(8px) !important;
          margin-bottom: 16px !important;
        }

        #chosen-card-anchor { display:none; }

        .chosen-h-title{
          font-size: 22px; font-weight: 850; color: rgba(255,255,255,0.94);
          margin: 0 0 2px 0;
        }
        .chosen-h-desc{
          font-size: 16px; color: rgba(255,255,255,0.68);
          margin: 0 0 10px 0;
        }

        .chips { display:flex; gap:10px; flex-wrap:wrap; margin-top: 10px; }
        .chip{
          display:inline-flex; gap:8px; align-items:center;
          padding: 8px 10px; border-radius: 999px;
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.07);
          color: rgba(255,255,255,0.92);
          font-size: 12px;
        }
        .chip .idx{
          width: 20px; height: 20px; border-radius: 999px;
          display:inline-flex; align-items:center; justify-content:center;
          background: linear-gradient(90deg, rgba(223,135,79,0.85), rgba(159,196,53,0.75));
          color: rgba(6,18,26,0.95);
          font-weight: 900; font-size: 12px;
          flex: 0 0 auto;
        }
        .chip code{
          font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, "Roboto Mono", "Courier New", monospace;
          font-size: 11px; background: transparent; padding: 0;
          color: rgba(255,255,255,0.92);
        }

        .chosen-meta{
          margin-top: 10px;
          font-size: 13px;
          color: rgba(255,255,255,0.66);
        }

        div[data-testid="stVerticalBlock"]:has(#chosen-card-anchor) .stButton>button{
          border-radius: 999px !important;
          padding: 10px 14px !important;
          border: 1px solid rgba(255,255,255,0.12) !important;
          background: rgba(255,255,255,0.05) !important;
          color: rgba(255,255,255,0.92) !important;
          font-weight: 800 !important;
        }
        div[data-testid="stVerticalBlock"]:has(#chosen-card-anchor) .stButton>button[kind="primary"]{
          border: none !important;
          background: linear-gradient(90deg, rgba(223,135,79,0.85), rgba(159,196,53,0.75)) !important;
          color: rgba(6,18,26,0.95) !important;
          font-weight: 950 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.container():
        st.markdown('<div id="chosen-card-anchor"></div>', unsafe_allow_html=True)

        st.markdown('<div class="chosen-h-title">Selected hexes</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="chosen-h-desc">Select up to 6 hexagons on the map to generate analysis, reports, and quick inspections.</div>',
            unsafe_allow_html=True,
        )

        chips_html = '<div class="chips">'
        for i in range(MAX_SLOTS):
            if i < n:
                hx = escape(hex_list[i])
                chips_html += f'<div class="chip"><div class="idx">{i+1}</div><code>{hx}</code></div>'
            else:
                chips_html += f'<div class="chip" style="opacity:0.45"><div class="idx">{i+1}</div><code>—</code></div>'
        chips_html += "</div>"
        st.markdown(chips_html, unsafe_allow_html=True)

        st.markdown(
            f'<div class="chosen-meta">Selected: <b>{n}</b> / {MAX_SLOTS} · H3 res <b>{h3_res}</b></div>',
            unsafe_allow_html=True,
        )

        b1, b2 = st.columns([1, 1], gap="medium")
        with b1:
            if st.button("Clear all", key="chosen_clear_all", use_container_width=True, disabled=(n == 0)):
                ss["chosen_hexes"] = set()
                ss["last_processed_click"] = None
                ss["selected_cell"] = None
                ss["pending_report_hex"] = None
                ss["trigger_generate_report"] = False
                st.rerun()

        with b2:
            if st.button(
                "Generate report",
                key="chosen_generate_report",
                type="primary",
                use_container_width=True,
                disabled=(n == 0),
            ):
                report_hex = None

                sel = ss.get("selected_cell")
                if sel is not None:
                    try:
                        report_hex = sel.get("h3_index") if isinstance(sel, dict) else sel.get("h3_index")
                    except Exception:
                        report_hex = None

                report_hex = report_hex or (hex_list[0] if hex_list else None)

                if report_hex:
                    ss["pending_report_hex"] = report_hex
                    ss["trigger_generate_report"] = True
                    ss["report_status"] = f"Generating report for {report_hex}..."

                st.rerun()

        # Global visible status / download
        if ss.get("report_status"):
            st.info(ss["report_status"])

        if ss.get("report_pdf") and ss.get("report_hex"):
            st.success(f"Report ready for {ss['report_hex']}")
            st.download_button(
                "📥 Download PDF",
                data=ss["report_pdf"],
                file_name=f"biodiversity_report_{ss['report_hex']}.pdf",
                mime="application/pdf",
                key="download_report_btn_global",
                use_container_width=True,
            )

    

                
def render_analysis_tab(
    chosen_hexes: set[str],
    h3_res: int,
    year: int,
) -> None:
    """Render analysis: species per hex, threatened vs not, rationale for threatened."""
    if len(chosen_hexes) < 1:
        st.info(
            "Select 1–6 hexes on the map (Map tab) to enable analysis. "
            "Click hexes to add. Use Clear all to remove."
        )
        return

    st.caption("Switch back to **Map** tab to change selection.")
    hex_list = sorted(chosen_hexes)
    with st.spinner("Loading species data…"):
        h3_df = load_h3_mapping(h3_res, year, hex_list)
        species_dim = load_species_dim(year)
        iucn_df = load_iucn_profiles(year)

    if h3_df.empty:
        st.warning(
            "No species data found for selected hexes. "
            "Ensure `gbif_silver_to_gold_dim.ipynb` has been run for this country/year."
        )
        return

    # Join with species_dim for names
    if not species_dim.empty and "taxon_key" in species_dim.columns:
        h3_df = h3_df.merge(
            species_dim[["taxon_key", "species_name"]].drop_duplicates("taxon_key"),
            on="taxon_key",
            how="left",
        )
        name_col = "species_name"
    else:
        h3_df["species_name"] = h3_df["taxon_key"].astype(str)
        name_col = "species_name"

    # Join with IUCN for rationale (on scientific_name = species_name, normalized)
    if not iucn_df.empty and "scientific_name" in iucn_df.columns:
        iucn_sub = iucn_df[
            ["scientific_name", "rationale", "iucn_category"]
        ].drop_duplicates("scientific_name")
        iucn_sub["_sci_norm"] = (
            iucn_sub["scientific_name"].astype(str).str.strip().str.lower()
        )
        h3_df["_sci_norm"] = h3_df[name_col].astype(str).str.strip().str.lower()
        h3_df = h3_df.merge(
            iucn_sub[["_sci_norm", "rationale", "iucn_category"]],
            on="_sci_norm",
            how="left",
        ).drop(columns=["_sci_norm"], errors="ignore")
    else:
        h3_df["rationale"] = None
        h3_df["iucn_category"] = None

    st.subheader("Species by hex")
    for h3_idx in hex_list:
        cell_df = h3_df[h3_df["h3_index"] == h3_idx]
        if cell_df.empty:
            continue
        n_total = cell_df["taxon_key"].nunique()
        n_threatened = (
            cell_df.loc[cell_df["is_threatened"], "taxon_key"].nunique()
            if "is_threatened" in cell_df.columns
            else 0
        )

        with st.expander(
            f"**{h3_idx}** — {n_total} species ({n_threatened} threatened)"
        ):
            display_df = cell_df.groupby("taxon_key", as_index=False).agg(
                {
                    name_col: "first",
                    "occurrence_count": "sum",
                    "is_threatened": "any",
                    "is_invasive": "any",
                }
            )
            if "rationale" in cell_df.columns:
                r_df = cell_df[["taxon_key", "rationale"]].drop_duplicates("taxon_key")
                display_df = display_df.merge(r_df, on="taxon_key", how="left")
            st.dataframe(display_df, use_container_width=True, hide_index=True)

            # Rationale for threatened species
            threatened = cell_df[cell_df["is_threatened"]].drop_duplicates("taxon_key")
            if not threatened.empty and "rationale" in threatened.columns:
                st.markdown("**Rationale (threatened species):**")
                for _, row in threatened.iterrows():
                    name = row.get(name_col, row.get("taxon_key", "?"))
                    rationale = row.get("rationale")
                    if rationale and pd.notna(rationale):
                        st.markdown(f"- **{name}**")
                        txt = str(rationale)
                        st.caption(txt[:600] + ("…" if len(txt) > 600 else ""))
                        st.divider()


# Resolutions available in gbif_species_h3_mapping (dim creates 6,7,8,9)
SPECIES_MAP_H3_RESOLUTIONS = [6, 7, 8, 9]


def render_species_map_tab(h3_res: int, year: int) -> None:
    """Map per species: search by name, show occurrence hexes + IUCN info if threatened."""
    st.subheader("🔍 Map per species")
    st.caption("Enter a species name (scientific or common) to see where it occurs.")

    species_dim = load_species_dim(year)
    if species_dim.empty or "species_name" not in species_dim.columns:
        st.warning(
            "Species dimension not available. Run `gbif_silver_to_gold_dim` first."
        )
        return

    query = st.text_input(
        "Species name",
        placeholder="e.g. invasive, Abies pinsapo, Cortaderia…",
        key="species_map_query",
    ).strip()

    if not query:
        st.info("Type a species name above to search.")
        return

    # Case-insensitive partial match
    mask = (
        species_dim["species_name"]
        .astype(str)
        .str.lower()
        .str.contains(query.lower(), na=False, regex=False)
    )
    matches = species_dim[mask].drop_duplicates("taxon_key")
    if matches.empty:
        st.warning(f"No species matching '{query}' found.")
        return

    # If multiple matches, let user pick
    if len(matches) > 1:
        options = matches["species_name"].tolist()
        if len(options) <= 20:
            selected_name = st.selectbox(
                "Multiple matches – select species",
                options=options,
                key="species_map_select",
            )
        else:
            selected_name = options[0]
            st.caption(f"Showing first of {len(matches)} matches. Refine your search.")
    else:
        selected_name = matches["species_name"].iloc[0]

    rows_with_name = matches[matches["species_name"] == selected_name]
    row = rows_with_name.iloc[0]
    taxon_keys_to_try = [int(r["taxon_key"]) for _, r in rows_with_name.iterrows()]
    is_threatened = bool(row.get("is_threatened", False))
    is_invasive = bool(row.get("is_invasive", False))

    # Resolution selector for species map (can be finer than main map)
    species_h3_res = st.selectbox(
        "H3 resolution",
        options=SPECIES_MAP_H3_RESOLUTIONS,
        index=SPECIES_MAP_H3_RESOLUTIONS.index(h3_res)
        if h3_res in SPECIES_MAP_H3_RESOLUTIONS
        else 0,
        format_func=lambda r: (
            f"{r} (~{36 if r == 6 else 5 if r == 7 else 0.7 if r == 8 else 0.1} km²/cell)"
        ),
        key="species_map_h3_res",
    )

    with st.spinner("Loading occurrence data…"):
        occ_df = pd.DataFrame()
        for tk in taxon_keys_to_try:
            occ_df = load_h3_mapping_by_taxon(species_h3_res, year, tk)
            if not occ_df.empty:
                break
        # If still empty, try other resolutions (any taxon_key for this species)
        if occ_df.empty:
            for r in SPECIES_MAP_H3_RESOLUTIONS:
                if r == species_h3_res:
                    continue
                for tk in taxon_keys_to_try:
                    occ_df = load_h3_mapping_by_taxon(r, year, tk)
                    if not occ_df.empty:
                        species_h3_res = r
                        st.info(
                            f"No data at requested resolution. Showing at resolution **{r}** instead."
                        )
                        break
                if not occ_df.empty:
                    break

    if occ_df.empty:
        occ_total = sum(
            int(r.get("occurrence_count", 0)) for _, r in rows_with_name.iterrows()
        )
        tk_str = ", ".join(str(t) for t in taxon_keys_to_try)
        st.warning(
            f"No occurrence data for **{selected_name}** (taxon_key={tk_str}) in "
            f"country={COUNTRY}, year={year}. "
            + (
                f"Species dim reports {occ_total:,} total occurrences – "
                if occ_total
                else ""
            )
            + "H3 mapping may be missing. Try re-running `gbif_silver_to_gold_dim`."
        )
        return

    # Aggregate by h3_index (in case of duplicates)
    occ_agg = occ_df.groupby("h3_index", as_index=False).agg(
        {"occurrence_count": "sum"}
    )

    geojson = build_geojson_from_h3_cells(occ_agg, occurrence_col="occurrence_count")
    m = make_map(
        geojson,
        show_overlay=True,
        color_metric="occurrence_count",
        center=MAP_CENTER,
        zoom=MAP_ZOOM,
    )
    st_folium(
        m,
        key="species_map_folium",
        use_container_width=True,
        height=500,
        returned_objects=[],  # no rerun on pan/zoom – map stays stable
    )
    st.caption(
        f"**{len(occ_agg):,}** H3 cells (res {species_h3_res}) · "
        f"**{int(occ_agg['occurrence_count'].sum()):,}** occurrences"
    )

    # IUCN panel when threatened
    if is_threatened:
        st.divider()
        st.subheader("🛡️ IUCN Red List")
        iucn_df = load_iucn_profiles_full(year)
        if not iucn_df.empty and "scientific_name" in iucn_df.columns:
            sci_norm = selected_name.strip().lower()
            iucn_df["_sci_norm"] = (
                iucn_df["scientific_name"].astype(str).str.strip().str.lower()
            )
            profile = iucn_df[iucn_df["_sci_norm"] == sci_norm]
            if not profile.empty:
                p = profile.iloc[0]
                cols = [
                    ("iucn_category", "Category"),
                    ("iucn_category_description", "Description"),
                    ("population_trend", "Population trend"),
                    ("rationale", "Rationale"),
                    ("habitat_ecology", "Habitat & ecology"),
                    ("population", "Population"),
                    ("range_description", "Range"),
                    ("threats_text", "Threats"),
                    ("conservation_text", "Conservation"),
                ]
                for col, label in cols:
                    val = p.get(col)
                    if val is not None and pd.notna(val) and str(val).strip():
                        st.markdown(f"**{label}**")
                        st.caption(
                            str(val)[:1200] + ("…" if len(str(val)) > 1200 else "")
                        )
                        st.divider()
            else:
                st.caption("No detailed IUCN profile for this species.")
        else:
            st.caption("IUCN profiles not available.")
    elif is_invasive:
        st.info("⚠️ This species is flagged as invasive.")


def render_protected_areas_tab(h3_res: int) -> None:
    """Map of Natura 2000 protected areas: green = protected, yellow = near. Click hex for details."""
    st.subheader("🛡️ Protected Areas (Natura 2000)")
    st.caption(
        "Green = inside protected area · Yellow = within k hexes of protected. Click a hex for details."
    )

    with st.spinner("Loading protected areas…"):
        df_full = load_nature2000_protected_areas(h3_res)

    if df_full.empty:
        st.warning(
            "No Natura 2000 protected areas data found. Run `nature2000_silver_to_gold` first."
        )
        return

    # Sample for display if too many (performance)
    df_display = df_full
    if len(df_full) > MAX_PROTECTED_HEXES_DISPLAY:
        df_display = df_full.sample(n=MAX_PROTECTED_HEXES_DISPLAY, random_state=42)
        st.info(
            f"Showing **{MAX_PROTECTED_HEXES_DISPLAY:,}** of **{len(df_full):,}** cells for performance. "
            "Zoom in or use a coarser resolution for full coverage."
        )

    geojson = build_geojson_protected_areas(df_display)
    m = make_map_protected_areas(geojson)

    map_data = st_folium(
        m,
        key="protected_areas_map",
        use_container_width=True,
        height=500,
        returned_objects=["last_clicked"],
    )

    n_prot = (df_full["is_protected_area"].astype(str).str.lower() == "yes").sum()
    n_near = len(df_full) - n_prot
    st.caption(
        f"**{len(df_full):,}** cells (res {h3_res}) · "
        f"**{n_prot:,}** protected · **{n_near:,}** near protected"
    )

    # Click handler: show cell info
    ss = st.session_state
    ss.setdefault("protected_last_click", None)
    ss.setdefault("protected_selected_row", None)

    if map_data and map_data.get("last_clicked"):
        click = map_data["last_clicked"]
        lat, lon = float(click["lat"]), float(click["lng"])
        click_key = (round(lat, 6), round(lon, 6))

        if ss["protected_last_click"] != click_key:
            ss["protected_last_click"] = click_key
            h3_id = h3.latlng_to_cell(lat, lon, h3_res)
            row = lookup_protected_cell(df_full, h3_id)
            if row is not None:
                ss["protected_selected_row"] = dict(row)
            else:
                ss["protected_selected_row"] = {"_not_found": True, "h3_id": h3_id}

    if ss.get("protected_selected_row"):
        row = ss["protected_selected_row"]
        if row.get("_not_found"):
            st.divider()
            st.subheader("📍 Selected hex info")
            st.info(
                f"**H3 ID** `{row.get('h3_id', '—')}` · "
                "No Natura 2000 protected area within k hexes of this cell."
            )
        else:
            st.divider()
            st.subheader("📍 Selected hex info")

            h3_id = row.get("h3_id", "—")
            is_prot = str(row.get("is_protected_area", "")).lower() == "yes"

            st.markdown(
                f"**H3 ID** `{h3_id}` · **Status** {'🟢 Protected' if is_prot else '🟡 Near protected'}"
            )

            if is_prot:
                st.markdown("#### Protected area")
                cols = [
                    ("site_code", "Site code"),
                    ("site_name", "Site name"),
                    ("AC", "AC"),
                    ("TIPO", "TIPO"),
                    ("overlap_fraction", "Overlap fraction"),
                    ("site_cover_fraction", "Site cover %"),
                    ("overlap_area_km2", "Overlap (km²)"),
                    ("is_core_cell", "Core cell"),
                ]
            else:
                dist = row.get("nearest_protected_distance")
                st.markdown(
                    f"**Distance to nearest protected:** {dist} hex{'es' if dist != 1 else ''}"
                )
                st.markdown("#### Nearest protected area")
                cols = [
                    ("nearest_site_code", "Site code"),
                    ("nearest_site_name", "Site name"),
                    ("nearest_AC", "AC"),
                    ("nearest_TIPO", "TIPO"),
                    ("nearest_overlap_fraction", "Overlap fraction"),
                    ("nearest_site_cover_fraction", "Site cover %"),
                    ("nearest_overlap_area_km2", "Overlap (km²)"),
                ]

            for col, label in cols:
                val = row.get(col)
                if val is not None and (not (isinstance(val, float) and pd.isna(val))):
                    st.markdown(f"**{label}** {val}")
    else:
        st.caption("Click a hex on the map to see details.")


# Land cover class IDs → human-readable labels (Copernicus Level 1)
LC_CLASS_LABELS: dict[int, str] = {
    0: "Unknown",
    20: "Shrubs",
    30: "Herbaceous",
    40: "Crops",
    50: "Urban",
    60: "Bare",
    70: "Snow/ice",
    80: "Water (permanent)",
    90: "Wetland",
    100: "Moss",
    111: "Forest (evergreen needle)",
    112: "Forest (evergreen broad)",
    113: "Forest (deciduous needle)",
    114: "Forest (deciduous broad)",
    115: "Forest (mixed)",
    116: "Forest (other)",
    121: "Open forest (needle)",
    122: "Open forest (broad)",
    123: "Open forest (deciduous needle)",
    124: "Open forest (deciduous broad)",
    125: "Open forest (mixed)",
    126: "Open forest (other)",
    200: "Ocean",
}


def render_terrain_tab(chosen_hexes: set[str], h3_res: int) -> None:
    """Terrain summary for chosen hexes (elevation, slope, land cover %). No map – like Analysis tab."""
    if len(chosen_hexes) < 1:
        st.info(
            "Select 1–6 hexes on the **Map** tab to see terrain summary. "
            "Click hexes to add. Use Clear all to remove."
        )
        return

    st.caption("Switch back to **Map** tab to change selection.")
    hex_list = sorted(chosen_hexes)

    with st.spinner("Loading terrain data…"):
        df_full = load_gee_terrain(h3_res)

    if df_full.empty:
        st.warning(
            "No GEE terrain data found. Run `gee_hex_terrain.ipynb` to populate gold/gee_hex_terrain."
        )
        return

    skip_cols = {"h3_index", "h3_resolution"}
    elev_col = "elevation_mean" if "elevation_mean" in df_full.columns else None
    slope_col = "slope_mean" if "slope_mean" in df_full.columns else None
    lc_cols = sorted(
        [c for c in df_full.columns if c.startswith("lc_") and c.endswith("_pct")]
    )

    for h3_idx in hex_list:
        row_df = df_full[df_full["h3_index"] == h3_idx]
        if row_df.empty:
            with st.expander(f"**{h3_idx}** — no terrain data"):
                st.caption("No GEE terrain data for this hex.")
            continue

        row = row_df.iloc[0].to_dict()
        table_rows: list[tuple[str, str]] = []

        if elev_col:
            val = row.get(elev_col)
            if val is not None and not (isinstance(val, float) and pd.isna(val)):
                fval = float(val)
                table_rows.append(("Elevation (mean)", f"{fval:.0f} m"))
        if slope_col:
            val = row.get(slope_col)
            if val is not None and not (isinstance(val, float) and pd.isna(val)):
                fval = float(val)
                table_rows.append(("Slope (mean)", f"{fval:.1f}°"))

        lc_entries = []
        for c in lc_cols:
            val = row.get(c)
            if val is None or (isinstance(val, float) and pd.isna(val)):
                continue
            try:
                fval = float(val)
            except (TypeError, ValueError):
                continue
            cid_str = c.replace("lc_", "").replace("_pct", "")
            try:
                cid = int(cid_str)
                label = LC_CLASS_LABELS.get(cid, c)
            except ValueError:
                label = c
            lc_entries.append((f"Land cover: {label}", f"{fval * 100:.1f}%", fval))
        for label, pct_str, _ in sorted(lc_entries, key=lambda x: -x[2]):
            table_rows.append((label, pct_str))

        # Any other numeric columns (e.g. from future gold schema)
        shown = {elev_col, slope_col} | set(lc_cols)
        for c in df_full.columns:
            if c in skip_cols or c in shown:
                continue
            val = row.get(c)
            if val is None or (isinstance(val, float) and pd.isna(val)):
                continue
            try:
                fval = float(val)
            except (TypeError, ValueError):
                continue
            table_rows.append((c.replace("_", " ").title(), f"{fval:.2f}"))

        elev_val = next((v for k, v in table_rows if "Elevation" in k), "—")
        slope_val = next((v for k, v in table_rows if "Slope" in k), "—")

        with st.expander(f"**{h3_idx}** — elev {elev_val} · slope {slope_val}"):
            if table_rows:
                df_summary = pd.DataFrame(table_rows, columns=["Metric", "Value"])
                st.dataframe(df_summary, use_container_width=True, hide_index=True)
            else:
                st.caption("No terrain data.")


# OSM report: metrics to show (excludes coastline_count, port/airport, amenity, admin_boundary, etc.)
OSM_REPORT_METRICS: list[tuple[str, str, str]] = [
    # (col, label, fmt: "pct" | "int" | "float" | "area_km2")
    ("hex_area_km2", "Hex area (km²)", "float"),
    ("waterbody_area_pct", "Waterbody %", "pct"),
    ("waterway_area_pct", "Waterway (riverbank) %", "pct"),
    ("wetland_area_pct", "Wetland %", "pct"),
    ("water_wetland_area_pct", "Water surface (body+way+wetland) %", "pct"),
    ("residential_area_pct", "Residential %", "pct"),
    ("commercial_area_pct", "Commercial %", "pct"),
    ("road_area_pct", "Road (est.) %", "pct"),
    ("parking_area_pct", "Parking %", "pct"),
    ("building_area_pct", "Building %", "pct"),
    ("industrial_area_pct", "Industrial %", "pct"),
    ("parks_green_area_pct", "Parks & green %", "pct"),
    ("cemetery_area_pct", "Cemetery %", "pct"),
    ("construction_area_pct", "Construction %", "pct"),
    ("retention_basin_area_pct", "Retention basin %", "pct"),
    ("agri_area_pct", "Agriculture %", "pct"),
    ("managed_forest_area_pct", "Managed forest %", "pct"),
    ("natural_habitat_area_pct", "Natural habitat %", "pct"),
    ("protected_area_pct", "Protected %", "pct"),
    ("restricted_area_pct", "Restricted %", "pct"),
    ("human_footprint_area_pct", "Human footprint %", "pct"),
    ("urban_footprint_area_pct", "Urban footprint %", "pct"),
    ("road_count", "Roads", "int"),
    ("major_road_count", "Major roads", "int"),
    ("road_count_per_km2", "Roads / km²", "float"),
    ("rail_count", "Rail segments", "int"),
    ("power_plant_count", "Power plants", "int"),
    ("solar_plant_count", "Solar plants", "int"),
    ("wind_plant_count", "Wind plants", "int"),
    ("hydro_plant_count", "Hydro plants", "int"),
    ("power_line_count", "Power lines", "int"),
    ("power_substation_count", "Substations", "int"),
    ("fuel_station_count", "Fuel stations", "int"),
    ("waterway_count", "Waterways", "int"),
    ("waterbody_count", "Waterbodies", "int"),
    ("wetland_count", "Wetlands", "int"),
    ("dam_count", "Dams", "int"),
    ("building_count", "Buildings", "int"),
    ("building_count_per_km2", "Buildings / km²", "float"),
    ("industrial_area_count", "Industrial areas", "int"),
    ("waste_site_count", "Waste sites", "int"),
]


def _fmt_osm_val(val: Any, fmt: str) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "—"
    if fmt == "pct":
        pct = min(
            float(val), 100.0
        )  # cap: OSM polygons overlap (e.g. residential > 100%)
        return f"{pct:.1f}%"
    if fmt == "int":
        return f"{int(val):,}"
    if fmt == "float":
        return f"{float(val):.2f}"
    return str(val)


def render_osm_report_tab(chosen_hexes: set[str], h3_res: int, year: int) -> None:
    """Render OSM infrastructure report for selected hexes."""
    import io
    import traceback

    if len(chosen_hexes) < 1:
        st.info(
            "Select 1–6 hexes on the **Map** tab to see the OSM infrastructure report. "
            "Click hexes to add. Use Clear all to remove."
        )
        return

    ss = st.session_state
    st.caption("Switch back to **Map** tab to change selection.")
    hex_list = sorted(chosen_hexes)

    with st.spinner("Loading OSM hex data…"):
        osm_df = load_osm_hex_features(h3_res, tuple(hex_list))

    if osm_df.empty:
        st.warning(
            "No OSM data found for selected hexes. "
            "Ensure `osm_silver_to_gold.ipynb` has been run for this country."
        )
        return

    st.subheader("🏗️ OSM Infrastructure Report")

    display_cols = ["h3_index"]
    for col, label, _ in OSM_REPORT_METRICS:
        if col in osm_df.columns:
            display_cols.append(col)

    report_df = osm_df[display_cols].copy()
    report_df = report_df.set_index("h3_index")

    fmt_map = {
        col: fmt for col, _, fmt in OSM_REPORT_METRICS if col in report_df.columns
    }
    for col in report_df.columns:
        fmt = fmt_map.get(col, "float")
        report_df[col] = report_df[col].apply(lambda v, f=fmt: _fmt_osm_val(v, f))

    st.dataframe(report_df.T, use_container_width=True, hide_index=False)

    st.divider()
    st.markdown("**Per-hex details**")
    for h3_idx in hex_list:
        row = osm_df[osm_df["h3_index"] == h3_idx]
        if row.empty:
            continue
        r = row.iloc[0]
        hex_km2 = r.get("hex_area_km2")
        hex_km2_str = (
            f"{float(hex_km2):.1f} km²"
            if hex_km2 is not None and pd.notna(hex_km2)
            else "—"
        )

        with st.expander(f"**{h3_idx}** — {hex_km2_str}"):
            cols = st.columns(3)
            sections = [
                (
                    "Land cover (%)",
                    [
                        "waterbody_area_pct",
                        "waterway_area_pct",
                        "wetland_area_pct",
                        "residential_area_pct",
                        "commercial_area_pct",
                        "road_area_pct",
                        "building_area_pct",
                        "industrial_area_pct",
                        "parks_green_area_pct",
                        "parking_area_pct",
                        "cemetery_area_pct",
                        "construction_area_pct",
                        "retention_basin_area_pct",
                        "agri_area_pct",
                        "managed_forest_area_pct",
                        "natural_habitat_area_pct",
                        "protected_area_pct",
                        "restricted_area_pct",
                        "human_footprint_area_pct",
                        "urban_footprint_area_pct",
                    ],
                ),
                (
                    "Transport & energy",
                    [
                        "road_count",
                        "major_road_count",
                        "rail_count",
                        "fuel_station_count",
                        "power_plant_count",
                        "solar_plant_count",
                        "wind_plant_count",
                        "hydro_plant_count",
                        "power_line_count",
                        "power_substation_count",
                    ],
                ),
                (
                    "Water & built",
                    [
                        "waterway_count",
                        "waterbody_count",
                        "wetland_count",
                        "dam_count",
                        "building_count",
                        "industrial_area_count",
                        "waste_site_count",
                    ],
                ),
            ]
            for i, (title, metric_cols) in enumerate(sections):
                with cols[i % 3]:
                    st.markdown(f"*{title}*")
                    for col in metric_cols:
                        if col not in r.index:
                            continue
                        val = r[col]
                        _, _, fmt = next(
                            (m for m in OSM_REPORT_METRICS if m[0] == col),
                            (col, col, "float"),
                        )
                        st.caption(
                            f"{col.replace('_', ' ').title()}: {_fmt_osm_val(val, fmt)}"
                        )

    st.divider()
    st.subheader("📄 Generate report")
    st.caption(
        "Create a PDF report with location map, species data (threatened/invasive), "
        "IUCN rationale, terrain (elevation, land cover), and OSM infrastructure summary."
    )

    industry = (
        st.text_input(
            "Industry (optional)",
            placeholder="e.g. Agriculture, Mining, Renewable energy, Tourism",
            key="report_industry",
        ).strip()
        or None
    )

    pending_report_hex = ss.get("pending_report_hex")
    default_report_hex = pending_report_hex if pending_report_hex in hex_list else hex_list[0]
    default_index = hex_list.index(default_report_hex)

    # OJO: usamos index, no escribimos en session_state después
    if len(hex_list) > 1:
        report_hex = st.selectbox(
            "Select hex for report",
            options=hex_list,
            index=default_index,
            format_func=lambda x: x,
            key="report_hex_select",
        )
    else:
        report_hex = hex_list[0]
        st.selectbox(
            "Select hex for report",
            options=hex_list,
            index=0,
            format_func=lambda x: x,
            key="report_hex_select",
            disabled=True,
        )

    clicked = st.button("Generate report", type="primary", key="generate_report_btn")
    triggered = ss.get("trigger_generate_report", False)

    pending_report_hex = ss.get("pending_report_hex")
    if pending_report_hex and pending_report_hex in hex_list:
        report_hex = pending_report_hex

    if clicked or triggered:
        ss["trigger_generate_report"] = False
        ss["report_status"] = f"Generating report for {report_hex}..."

        with st.spinner("Generating PDF…"):
            try:
                import io
                import traceback
                from report_generator import generate_report

                ai_insights = None
                try:
                    with st.spinner("Fetching AI insights…"):
                        industry_ctx = (
                            f" Industry context: {industry}." if industry else ""
                        )
                        prompt = (
                            f"Analyze biodiversity risk for hex {report_hex}, resolution {h3_res}.{industry_ctx} "
                            "Provide a structured report in English with: "
                            "1. Executive Summary (2-4 sentences, risk tier: LOW/MODERATE/HIGH/CRITICAL), "
                            "2. Key Metrics (table: Metric | Value | Interpretation), "
                            "3. Neighbor context, 4. Species overview, "
                            "5. Industry insights (if relevant), 6. Recommended actions (numbered list), "
                            "7. Data limitations. Use markdown: ### for section headings, **bold** for emphasis, "
                            "| for tables, - or • for bullet points."
                        )
                        ai_insights = invoke_bedrock_agent(
                            prompt,
                            session_id=f"report-{report_hex}-{h3_res}",
                        )
                except Exception as e:
                    ai_insights = f"*Failed to fetch AI Insights: {e}*"

                h3_df = load_h3_mapping(h3_res, year, [report_hex])
                species_dim = load_species_dim(year)
                iucn_df = load_iucn_profiles(year)

                if not species_dim.empty and "taxon_key" in species_dim.columns:
                    h3_df = h3_df.merge(
                        species_dim[["taxon_key", "species_name"]].drop_duplicates("taxon_key"),
                        on="taxon_key",
                        how="left",
                    )
                    name_col = "species_name"
                else:
                    h3_df["species_name"] = h3_df["taxon_key"].astype(str)
                    name_col = "species_name"

                if not iucn_df.empty and "scientific_name" in iucn_df.columns:
                    iucn_sub = iucn_df[
                        ["scientific_name", "rationale", "iucn_category"]
                    ].drop_duplicates("scientific_name")
                    iucn_sub["_sci_norm"] = (
                        iucn_sub["scientific_name"].astype(str).str.strip().str.lower()
                    )
                    h3_df["_sci_norm"] = (
                        h3_df[name_col].astype(str).str.strip().str.lower()
                    )
                    h3_df = h3_df.merge(
                        iucn_sub[["_sci_norm", "rationale", "iucn_category"]],
                        on="_sci_norm",
                        how="left",
                    ).drop(columns=["_sci_norm"], errors="ignore")
                else:
                    h3_df["rationale"] = None
                    h3_df["iucn_category"] = None

                osm_row = osm_df[osm_df["h3_index"] == report_hex]
                osm_row = osm_row.iloc[0] if not osm_row.empty else pd.Series(dtype=object)

                gee_terrain_df = load_gee_terrain(h3_res)
                gee_terrain_row = None
                if not gee_terrain_df.empty and "h3_index" in gee_terrain_df.columns:
                    gt = gee_terrain_df[gee_terrain_df["h3_index"] == report_hex]
                    gee_terrain_row = gt.iloc[0] if not gt.empty else None

                species_for_hex = h3_df[h3_df["h3_index"] == report_hex]

                cell_metrics = None
                try:
                    metrics_df = load_data(h3_res, year)
                    if not metrics_df.empty and "h3_index" in metrics_df.columns:
                        m = metrics_df[metrics_df["h3_index"] == report_hex]
                        cell_metrics = m.iloc[0] if not m.empty else None
                except Exception:
                    pass

                temporal_artifacts = None
                try:
                    from temporal_analysis import (
                        compute_temporal_analysis,
                        get_temporal_tables,
                        render_temporal_charts,
                    )

                    hex_metrics = load_multiyear_metrics_hex(h3_res, report_hex)
                    hex_species = load_multiyear_species_h3_mapping_hex(h3_res, report_hex)
                    species_dim_by_year = {}
                    for y in AVAILABLE_YEARS:
                        try:
                            sd = load_species_dim(y)
                            if not sd.empty:
                                species_dim_by_year[y] = sd
                        except Exception:
                            pass

                    data = compute_temporal_analysis(
                        hex_metrics,
                        hex_species,
                        species_dim_by_year=species_dim_by_year or None,
                    )
                    charts = render_temporal_charts(data)
                    tables = get_temporal_tables(data)
                    if charts or tables:
                        temporal_artifacts = {
                            "charts": charts,
                            "tables": tables,
                            "narrative_text": data.get("narrative_text", ""),
                            "limitations": data.get("limitations", ""),
                        }
                except Exception:
                    temporal_artifacts = None

                pdf_bytes = generate_report(
                    h3_index=report_hex,
                    h3_res=h3_res,
                    species_df=species_for_hex,
                    osm_row=osm_row,
                    cell_metrics=cell_metrics,
                    name_col=name_col,
                    ai_insights=ai_insights,
                    temporal_artifacts=temporal_artifacts,
                    year=year,
                    gee_terrain_row=gee_terrain_row,
                    industry=industry,
                )

                if isinstance(pdf_bytes, io.BytesIO):
                    pdf_bytes = pdf_bytes.getvalue()

                if not isinstance(pdf_bytes, (bytes, bytearray)):
                    raise RuntimeError(
                        f"generate_report returned {type(pdf_bytes)} instead of bytes"
                    )

                ss["report_pdf"] = pdf_bytes
                ss["report_hex"] = report_hex
                ss["pending_report_hex"] = None
                ss["report_status"] = f"Report ready for {report_hex}"
                st.success("Report generated successfully.")

            except Exception as e:
                ss["report_status"] = f"Report failed for {report_hex}"
                st.error(f"Failed to generate report: {e}")
                st.code(traceback.format_exc())

    if "report_pdf" in ss and ss.get("report_hex") == report_hex:
        st.download_button(
            "📥 Download PDF",
            data=ss["report_pdf"],
            file_name=f"biodiversity_report_{report_hex}.pdf",
            mime="application/pdf",
            key="download_report_btn",
        )


def render_cell_panel(selected_cell: pd.Series | None, df_full: pd.DataFrame) -> None:
    """
    Render the selected-cell stats panel + Top-5 table in the right column.
    """
    st.markdown("### 📍 Selected cell")

    if selected_cell is None:
        st.info("Click a hex on the map.")
    else:
        rows: list[dict] = []
        for col in DETAIL_METRICS:
            val = selected_cell.get(col, None)
            if val is None:
                lc = {k.lower(): v for k, v in selected_cell.items()}
                val = lc.get(col.lower(), None)
            rows.append({"Metric": col, "Value": format_metric(val)})
        # Extra columns not in DETAIL_METRICS
        for col in selected_cell.index:
            if col not in DETAIL_METRICS and not col.startswith("_"):
                rows.append({"Metric": col, "Value": format_metric(selected_cell[col])})

        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
            height=min(480, 35 * len(rows) + 40),
        )

    st.divider()
    st.markdown("### 🏆 Top 5 richness")
    if not df_full.empty and "species_richness_cell" in df_full.columns:
        cols = [
            c
            for c in ["h3_index", "species_richness_cell", "n_threatened_species"]
            if c in df_full.columns
        ]
        top5 = df_full.nlargest(5, "species_richness_cell")[cols].reset_index(drop=True)
        top5.index += 1
        st.dataframe(top5, use_container_width=True, hide_index=False)


def render_main(
    df_full: pd.DataFrame,
    folium_map: folium.Map,
    was_sampled: bool,
    mode_used: str,
    color_metric: str,
    h3_res: int,
    show_overlay: bool,
    n_layer: int,
    selected_year: int,
) -> dict[str, Any] | None:
    """
    Two-column layout: map (left 3/4) | cell stats (right 1/4).
    Below: Top-10 table + summary stats.
    Returns the raw st_folium output dict.
    """
    ss = st.session_state

    col_map, col_stats = st.columns([3, 1], gap="medium")

    # ── Right column: cell stats ───────────────────────────────────────────────
    with col_stats:
        render_cell_panel(
            ss.get("selected_cell"),
            df_full,
        )

    # ── Left column: map ──────────────────────────────────────────────────────
    with col_map:
        if df_full.empty:
            st.error("No data found for the selected country / year / resolution.")
            return None

        if mode_used == "viewport_snapshot" and n_layer > 10_000:
            st.warning(
                f"Rendering **{n_layer:,}** hexagons. This may be slow at high resolutions."
            )

        # Status caption
        status_parts = [f"**{n_layer:,}** hexagons drawn  ·  res **{h3_res}**"]
        if mode_used == "viewport_snapshot":
            status_parts.append("📍 all cells in captured viewport")
        elif mode_used == "request_bounds":
            status_parts.append("⏳ capturing viewport…")
        elif was_sampled:
            status_parts.append(
                f"top-{n_layer:,} by *{color_metric.replace('_', ' ')}* "
                "— zoom in then click **📍 Add hexagons here** for full local coverage"
            )
        st.caption(" · ".join(status_parts))

        # Returned objects strategy
        view_mode = ss.get("view_mode", "top_n")
        if view_mode == "request_bounds":
            returned_objs = ["last_clicked", "bounds"]
        else:
            returned_objs = ["last_clicked"]

        map_key = f"main_map_{selected_year}"
        map_data = st_folium(
            folium_map,
            key=map_key,
            use_container_width=True,
            height=580,
            returned_objects=returned_objs,
        )

        # Capture bounds for viewport_snapshot
        if view_mode == "request_bounds" and map_data and map_data.get("bounds"):
            ss["snapshot_bounds"] = map_data["bounds"]
            ss["view_mode"] = "viewport_snapshot"
            st.rerun()

        # Buttons
        if show_overlay:
            in_vp = view_mode == "viewport_snapshot"
            btn_col1, btn_col2 = st.columns([1, 1])
            with btn_col1:
                if st.button(
                    "📍 Add hexagons here",
                    use_container_width=True,
                    disabled=(view_mode == "request_bounds"),
                    help=(
                        "Captures the current viewport bounds and renders ALL "
                        "H3 cells visible in that area."
                    ),
                ):
                    ss["view_mode"] = "request_bounds"
                    st.rerun()
            with btn_col2:
                if st.button(
                    "↩ Reset to top-N",
                    use_container_width=True,
                    disabled=not in_vp,
                    help="Back to showing the top-N cells by metric.",
                ):
                    ss["view_mode"] = "top_n"
                    ss["snapshot_bounds"] = None
                    st.rerun()

        # ✅ IMPORTANT: Click handler MUST live right after st_folium (tabs-safe)
        if map_data and map_data.get("last_clicked"):
            click = map_data["last_clicked"]
            lat, lon = float(click["lat"]), float(click["lng"])
            click_key = (round(lat, 6), round(lon, 6))

            if ss.get("last_processed_click") != click_key:
                ss["last_processed_click"] = click_key

                h3_idx = resolve_click_to_cell(lat, lon, h3_res)
                cell_row = lookup_cell(df_full, h3_idx)

                chosen = set(ss.get("chosen_hexes", set()))
                if len(chosen) < MAX_CHOSEN_HEXES and h3_idx not in chosen:
                    chosen.add(h3_idx)
                ss["chosen_hexes"] = chosen  # reasignación (no in-place)

                ss["selected_cell"] = cell_row
                st.rerun()

    # ── Below: Top 10 + summary ───────────────────────────────────────────────
    if not df_full.empty:
        st.divider()
        t_col, s_col = st.columns([1, 1], gap="large")

        with t_col:
            st.subheader("🏆 Top 10 by species richness")
            cols_to_show = [
                c
                for c in [
                    "h3_index",
                    "species_richness_cell",
                    "observation_count",
                    "shannon_H",
                    "n_threatened_species",
                    "threat_score_weighted",
                    "dqi",
                ]
                if c in df_full.columns
            ]
            if "species_richness_cell" in df_full.columns:
                top10 = df_full.nlargest(10, "species_richness_cell")[
                    cols_to_show
                ].reset_index(drop=True)
                top10.index += 1
                st.dataframe(top10, use_container_width=True, height=360)

        with s_col:
            st.subheader("📊 Dataset summary")
            numeric_cols = [c for c in COLOR_METRICS if c in df_full.columns]
            if numeric_cols:
                summary = (
                    df_full[numeric_cols]
                    .agg(["count", "min", "mean", "max"])
                    .T.rename(columns={"count": "n"})
                )
                summary["n"] = summary["n"].astype(int)
                st.dataframe(
                    summary.style.format("{:.3f}", subset=["min", "mean", "max"]),
                    use_container_width=True,
                )
            st.caption(f"**{len(df_full):,}** cells · res **{h3_res}** · {COUNTRY}")

    return map_data


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────


def main() -> None:
    favicon_path = Path(__file__).parent / "ui" / "assets" / "logo_mini.png"
    st.set_page_config(
        page_title="GBIF Biodiversity Explorer",
        page_icon=str(favicon_path),
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    ss = st.session_state
    ss.setdefault("route", "landing")  # landing | app

    # ✅ LANDING primero, SIN inject_css()
    if ENABLE_LANDING and ss["route"] == "landing":
        from ui.landing import render_landing
        render_landing()
        return

    # ✅ ya en la app normal, sí metemos CSS global
    inject_css()

    # ── Session state defaults ────────────────────────────────────────────────
    ss = st.session_state
    ss.setdefault("trigger_generate_report", False)
    ss.setdefault("pending_report_hex", None)
    ss.setdefault("selected_cell", None)
    ss.setdefault("report_pdf", None)
    ss.setdefault("report_hex", None)
    ss.setdefault("report_status", None)
    ss.setdefault("chosen_hexes", set())  # set of h3_index, max 6
    ss.setdefault(
        "last_processed_click", None
    )  # (lat, lon) to avoid infinite rerun loop
    ss.setdefault("prev_h3_res", None)
    ss.setdefault("prev_year", None)
    # view_mode state machine: "top_n" | "request_bounds" | "viewport_snapshot"
    ss.setdefault("view_mode", "top_n")
    ss.setdefault("snapshot_bounds", None)

    # ── Sidebar: controls only ────────────────────────────────────────────────
    show_overlay, h3_res, color_metric, max_hexes, selected_year, chat_open = (
        render_sidebar()
    )

    # Clear selected cell + chosen hexes + reset view mode when year or resolution changes.
    if selected_year != ss["prev_year"] or h3_res != ss["prev_h3_res"]:
        ss["selected_cell"] = None
        ss["chosen_hexes"] = set()
        ss["last_processed_click"] = None
        ss["view_mode"] = "top_n"
        ss["snapshot_bounds"] = None
        ss["prev_year"] = selected_year
        ss["prev_h3_res"] = h3_res

    # ── Load data (cached) ────────────────────────────────────────────────────
    df_full = load_data(h3_res, selected_year)

    # ── Prepare rendering layer ───────────────────────────────────────────────
    df_layer, was_sampled, mode_used = prepare_layer(
        df_full,
        color_metric,
        max_hexes,
        mode=ss["view_mode"],
        snapshot_bounds=ss["snapshot_bounds"],
    )

    # ── Build GeoJSON + Folium map ────────────────────────────────────────────
    if show_overlay and not df_layer.empty:
        geojson = build_geojson_layer(df_layer, color_metric)
    else:
        geojson = {"type": "FeatureCollection", "features": []}

    folium_map = make_map(geojson, show_overlay, color_metric)

    # ── Top bar + chosen hexes ────────────────────────────────────────────────
    render_app_navbar()
    render_chosen_card(ss["chosen_hexes"], h3_res)

    if chat_open:
        main_col, chat_col = st.columns([3, 1], gap="medium")
    else:
        main_col = st.container()
        chat_col = None

    with main_col:
        tab_map, tab_analysis, tab_species, tab_protected, tab_terrain, tab_osm = (
            st.tabs(
                [
                    "🗺️ Map",
                    "📊 Analysis",
                    "🔍 Species map",
                    "🛡️ Protected Areas",
                    "⛰️ Terrain summary",
                    "🏗️ OSM Report",
                ]
            )
        )

        with tab_map:
            map_data = render_main(
                df_full,
                folium_map,
                was_sampled,
                mode_used,
                color_metric,
                h3_res,
                show_overlay,
                n_layer=len(df_layer),
                selected_year=selected_year,
            )
        with tab_analysis:
            render_analysis_tab(ss["chosen_hexes"], h3_res, selected_year)
        with tab_species:
            render_species_map_tab(h3_res, selected_year)
        with tab_protected:
            render_protected_areas_tab(h3_res)
        with tab_terrain:
            render_terrain_tab(ss["chosen_hexes"], h3_res)
        with tab_osm:
            render_osm_report_tab(ss["chosen_hexes"], h3_res, selected_year)

    if chat_open and chat_col is not None:
        with chat_col:
            render_chat_panel(h3_res, ss["chosen_hexes"])

    



if __name__ == "__main__":
    main()
