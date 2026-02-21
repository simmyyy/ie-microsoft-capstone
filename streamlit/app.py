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

import json
import warnings
from typing import Any

import streamlit as st

# ── Dependency check ──────────────────────────────────────────────────────────
# Run BEFORE any other import so the error message is readable, not a traceback.
_REQUIRED = {
    "boto3":            "boto3",
    "folium":           "folium",
    "h3":               "h3>=4.0.0",
    "pandas":           "pandas",
    "s3fs":             "s3fs",
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
import boto3          # noqa: E402
import folium         # noqa: E402
import h3             # noqa: E402
import pandas as pd   # noqa: E402
import s3fs           # noqa: E402
from streamlit_folium import st_folium  # noqa: E402

# duckdb is optional – we fall back to s3fs+pandas if it's not installed
try:
    import duckdb
    _DUCKDB_AVAILABLE = True
except ImportError:
    duckdb = None          # type: ignore[assignment]
    _DUCKDB_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

S3_BUCKET    = "ie-datalake"
GOLD_PREFIX  = "gold/gbif_cell_metrics"
AWS_PROFILE  = "486717354268_PowerUserAccess"
COUNTRY      = "ES"

# ── Demo / hardcoded settings ─────────────────────────────────────────────────
DEMO_YEAR        = 2024          # hardcoded for demo; change to unlock year selector
DEMO_H3_OPTIONS  = [6, 7]        # resolutions available in demo (6 ≈ 36 km², 7 ≈ 5 km²)
AVAILABLE_YEARS  = [2024, 2023, 2022, 2021, 2020]

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
    (0.0,  "#ffffb2"),
    (0.2,  "#fed976"),
    (0.4,  "#feb24c"),
    (0.6,  "#fd8d3c"),
    (0.8,  "#f03b20"),
    (1.0,  "#bd0026"),
]

MAP_CENTER        = [40.3, -3.7]   # centre of Spain
MAP_ZOOM          = 6
MAX_HEXES_DEFAULT = 20_000
MAX_HEXES_CAP     = 20_000


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
    creds   = session.get_credentials().get_frozen_credentials()
    region  = session.region_name or "eu-west-1"

    con.execute(f"SET s3_region='{region}';")
    con.execute(f"SET s3_access_key_id='{creds.access_key}';")
    con.execute(f"SET s3_secret_access_key='{creds.secret_key}';")
    if creds.token:
        con.execute(f"SET s3_session_token='{creds.token}';")

    return con


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
            schema=None,        # let pyarrow infer per-file, then unify
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
            latlngs  = np.array([h3.cell_to_latlng(c) for c in h3_cells])
            lat_arr, lng_arr = latlngs[:, 0], latlngs[:, 1]

            mask = (
                (lat_arr >= lat_min) & (lat_arr <= lat_max) &
                (lng_arr >= lng_min) & (lng_arr <= lng_max)
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
    values     = df[metric_col].fillna(0).astype(float)
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

        val   = float(record.get(metric_col) or 0)
        color = _metric_to_color(val, vmin, vmax)

        props: dict[str, Any] = {k: _safe_scalar(v) for k, v in record.items()}
        props["_color"]        = color
        props["_metric_value"] = val

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                # GeoJSON coordinates are [lon, lat]; boundary is [[lat, lon], ...]
                "coordinates": [[[lng, lat] for lat, lng in boundary]],
            },
            "properties": props,
        })

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

def make_map(
    geojson: dict[str, Any],
    show_overlay: bool,
    color_metric: str,
    center: list[float] = MAP_CENTER,
    zoom: int = MAP_ZOOM,
) -> folium.Map:
    """
    Build a Folium map with an optional H3 hex GeoJSON overlay.

    Click capture is handled via streamlit-folium's last_clicked mechanism:
    the JS onclick adds a marker but the actual cell lookup is done server-side
    by converting lat/lon → h3_index.
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
                "fillColor":   feature["properties"]["_color"],
                "color":       "#444444",
                "weight":      0.4,
                "fillOpacity": 0.65,
            },
            highlight_function=lambda feature: {
                "weight":      2,
                "color":       "#000000",
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


def render_sidebar() -> tuple[bool, int, str, int, int]:
    """
    Render sidebar controls only (no cell-detail panel – that lives in the
    right column of the main area).

    Returns:
        (show_overlay, h3_res, color_metric, max_hexes, selected_year)
    """
    st.sidebar.title("🌿 Biodiversity Explorer")
    st.sidebar.markdown("Spain · GBIF Gold Layer")
    st.sidebar.caption(
        "⚠️ **Demo mode** – year locked to 2024, "
        "resolutions limited to 6 & 7, max hexes fixed at 20 000."
    )
    st.sidebar.divider()

    show_overlay = st.sidebar.checkbox("Show H3 overlay", value=True)

    # Year – locked to 2024 for the demo
    st.sidebar.selectbox(
        "Year *(hardcoded – demo)*",
        options=[DEMO_YEAR],
        index=0,
        disabled=True,
    )
    selected_year = DEMO_YEAR

    h3_res = st.sidebar.select_slider(
        "H3 resolution",
        options=DEMO_H3_OPTIONS,   # [6, 7] only for demo
        value=DEMO_H3_OPTIONS[0],
        help=(
            "Res 6 ≈ 36 km² per cell (country overview). "
            "Res 7 ≈ 5 km² per cell (regional detail). "
            "Resolutions 8 & 9 disabled in demo mode."
        ),
    )

    color_metric = st.sidebar.selectbox(
        "Colour metric",
        options=COLOR_METRICS,
        index=0,
        format_func=lambda m: m.replace("_", " ").title(),
        disabled=not show_overlay,
    )

    # Max hexes – fixed for demo, shown as info only
    max_hexes = MAX_HEXES_DEFAULT
    st.sidebar.caption(f"Max hexes: **{max_hexes:,}** *(fixed for demo)*")

    return show_overlay, h3_res, color_metric, max_hexes, selected_year


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
        cols = [c for c in ["h3_index", "species_richness_cell", "n_threatened_species"]
                if c in df_full.columns]
        top5 = (
            df_full.nlargest(5, "species_richness_cell")[cols]
            .reset_index(drop=True)
        )
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
    col_map, col_stats = st.columns([3, 1], gap="medium")

    # ── Right column: cell stats ───────────────────────────────────────────────
    with col_stats:
        render_cell_panel(
            st.session_state.get("selected_cell"),
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

        # ── STABLE map key – only resets when year changes ────────────────────
        # Crucially, h3_res is NOT in the key.  That means switching resolution
        # reuses the same Leaflet component instance → map zoom & pan are
        # preserved.  New hexagon data is passed as props and the layer updates
        # in-place without unmounting.
        #
        # returned_objects strategy:
        #   "top_n" / "viewport_snapshot" → only last_clicked  (no zoom reruns)
        #   "request_bounds"              → last_clicked + bounds  (one shot)
        view_mode = st.session_state.get("view_mode", "top_n")
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

        # ── Capture bounds on the "request_bounds" cycle ──────────────────────
        # This runs immediately after the component reports back with bounds.
        # We snapshot them, switch to viewport_snapshot mode, and stop
        # requesting bounds (no more zoom-triggered reruns).
        if view_mode == "request_bounds" and map_data and map_data.get("bounds"):
            st.session_state["snapshot_bounds"] = map_data["bounds"]
            st.session_state["view_mode"] = "viewport_snapshot"
            st.rerun()

        # ── Buttons ───────────────────────────────────────────────────────────
        if show_overlay:
            in_vp = (view_mode == "viewport_snapshot")
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
                    # Transition: request one bounds snapshot on the next render
                    st.session_state["view_mode"] = "request_bounds"
                    st.rerun()
            with btn_col2:
                if st.button(
                    "↩ Reset to top-N",
                    use_container_width=True,
                    disabled=not in_vp,
                    help="Back to showing the top-N cells by metric.",
                ):
                    st.session_state["view_mode"]      = "top_n"
                    st.session_state["snapshot_bounds"] = None
                    st.rerun()

    # ── Below: Top 10 + summary ───────────────────────────────────────────────
    if not df_full.empty:
        st.divider()
        t_col, s_col = st.columns([1, 1], gap="large")

        with t_col:
            st.subheader("🏆 Top 10 by species richness")
            cols_to_show = [c for c in [
                "h3_index", "species_richness_cell", "observation_count",
                "shannon_H", "n_threatened_species", "threat_score_weighted", "dqi",
            ] if c in df_full.columns]
            if "species_richness_cell" in df_full.columns:
                top10 = (
                    df_full.nlargest(10, "species_richness_cell")[cols_to_show]
                    .reset_index(drop=True)
                )
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
            st.caption(
                f"**{len(df_full):,}** cells · res **{h3_res}** · {COUNTRY}"
            )

    return map_data


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="GBIF Biodiversity Explorer",
        page_icon="🌿",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # ── Session state defaults ────────────────────────────────────────────────
    ss = st.session_state
    ss.setdefault("selected_cell",  None)
    ss.setdefault("prev_h3_res",    None)
    ss.setdefault("prev_year",      None)
    # view_mode state machine: "top_n" | "request_bounds" | "viewport_snapshot"
    ss.setdefault("view_mode",      "top_n")
    ss.setdefault("snapshot_bounds", None)

    # ── Sidebar: controls only ────────────────────────────────────────────────
    show_overlay, h3_res, color_metric, max_hexes, selected_year = render_sidebar()

    # Clear selected cell + reset view mode when year changes.
    # Resolution change does NOT reset (stable map key preserves position).
    if selected_year != ss["prev_year"]:
        ss["selected_cell"]  = None
        ss["view_mode"]      = "top_n"
        ss["snapshot_bounds"] = None
        ss["prev_year"]      = selected_year
    ss["prev_h3_res"] = h3_res  # track but don't reset

    # ── Load data (cached) ────────────────────────────────────────────────────
    df_full = load_data(h3_res, selected_year)

    # ── Prepare rendering layer ───────────────────────────────────────────────
    df_layer, was_sampled, mode_used = prepare_layer(
        df_full,
        color_metric,
        max_hexes,
        mode            = ss["view_mode"],
        snapshot_bounds = ss["snapshot_bounds"],
    )

    # ── Build GeoJSON + Folium map ────────────────────────────────────────────
    if show_overlay and not df_layer.empty:
        geojson = build_geojson_layer(df_layer, color_metric)
    else:
        geojson = {"type": "FeatureCollection", "features": []}

    folium_map = make_map(geojson, show_overlay, color_metric)

    # ── Render ────────────────────────────────────────────────────────────────
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

    # ── Click handler: lat/lon → H3 index → row lookup ────────────────────────
    if map_data and map_data.get("last_clicked"):
        click = map_data["last_clicked"]
        lat, lon = float(click["lat"]), float(click["lng"])
        h3_idx   = resolve_click_to_cell(lat, lon, h3_res)
        cell_row = lookup_cell(df_full, h3_idx)

        if cell_row is not None and (
            ss["selected_cell"] is None
            or ss["selected_cell"].get("h3_index") != h3_idx
        ):
            ss["selected_cell"] = cell_row
            st.rerun()


if __name__ == "__main__":
    main()
