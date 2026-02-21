# GBIF Biodiversity Explorer – Streamlit App

Interactive map for exploring H3-based biodiversity metrics over Spain, built on top of the GBIF Gold layer stored in S3.

---

## What it does

The app reads pre-aggregated biodiversity data from `s3://ie-datalake/gold/gbif_cell_metrics/` and renders it as a hexagonal grid (H3) on top of an OpenStreetMap base layer.

Each hexagon represents a spatial cell at a chosen H3 resolution and is coloured by a selected biodiversity metric. Clicking any hexagon shows its full metric profile in the right-hand panel.

### Available metrics

| Metric | Description |
|---|---|
| `species_richness_cell` | Number of distinct species observed |
| `observation_count` | Total occurrence records |
| `shannon_H` | Shannon-Wiener diversity index |
| `simpson_1_minus_D` | Simpson diversity index (1 − D) |
| `n_threatened_species` | Distinct CR / EN / VU species |
| `threat_score_weighted` | Weighted threat score (CR=5, EN=4, VU=3, NT=2) |
| `dqi` | Data Quality Index (0–1) |

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | [Streamlit](https://streamlit.io) |
| Map | [Folium](https://python-visualization.github.io/folium/) + [streamlit-folium](https://github.com/randyzwitch/streamlit-folium) |
| Spatial indexing | [H3](https://h3geo.org/) (Uber hexagonal grid) |
| Data reading | [DuckDB](https://duckdb.org/) httpfs (primary) · s3fs + PyArrow (fallback) |
| Cloud storage | AWS S3 |
| AWS auth | boto3 SSO profile (no hardcoded keys) |

---

## Prerequisites

- Python 3.10+
- AWS SSO configured and active session (see below)
- Access to `s3://ie-datalake/gold/gbif_cell_metrics/`

---

## Setup

```bash
# From the repo root – activate your virtual environment first
source .venv/bin/activate   # or: conda activate <env>

# Install dependencies
pip install -r streamlit/requirements.txt
```

### AWS authentication

The app uses the `486717354268_PowerUserAccess` AWS SSO profile. Log in before starting:

```bash
aws sso login --profile 486717354268_PowerUserAccess
```

If you see an expired-token error while the app is running, re-run the command above and restart the app.

---

## Running the app

Always launch via `python -m streamlit` to ensure the same Python interpreter as your active virtual environment is used:

```bash
python -m streamlit run streamlit/app.py
```

The app opens automatically at `http://localhost:8501`.

---

## UI overview

```
┌─────────────────┬──────────────────────────────┬───────────────────┐
│   SIDEBAR       │   MAP  (3/4 width)           │  STATS  (1/4)     │
│                 │                              │                   │
│ ⚠️ Demo mode    │  OpenStreetMap base layer    │ 📍 Selected cell  │
│                 │  + H3 hex overlay            │  metrics table    │
│ □ Show overlay  │                              │                   │
│                 │  [📍 Add hexagons here]      │ 🏆 Top 5 richness │
│ Year: 2024*     │  [↩ Reset to top-N]          │                   │
│                 │                              │                   │
│ H3 resolution   ├──────────────────────────────┴───────────────────┤
│  slider (6 / 7) │  🏆 Top 10 by species richness                   │
│                 │  📊 Dataset summary                              │
│ Colour metric   │                                                  │
│  selector       └──────────────────────────────────────────────────┘
│
│ Max hexes: 20 000*
└─────────────
* hardcoded in demo mode
```

### Controls

| Control | Description |
|---|---|
| **Show H3 overlay** | Toggle the hexagonal layer on/off |
| **H3 resolution** | `6` = coarse (~36 km²/cell, full Spain view) · `7` = finer (~5 km²/cell, regional) |
| **Colour metric** | Which metric drives the choropleth colour scale (yellow → red) |
| **📍 Add hexagons here** | Capture current viewport bounds and render **all** H3 cells visible in that area |
| **↩ Reset to top-N** | Return to global top-20 000 cells mode |

### Map interaction

- **Scroll** – zoom in/out (no page reload)
- **Drag** – pan the map (no page reload)
- **Click** – look up the H3 cell under the cursor; metrics appear in the right panel
- **H3 resolution change** – redraws hexagons, **map position is preserved**

---

## Demo mode

The app currently runs in demo mode (hardcoded settings):

| Setting | Demo value | How to unlock |
|---|---|---|
| Year | 2024 | Change `DEMO_YEAR` in `app.py` |
| H3 resolutions | 6, 7 | Change `DEMO_H3_OPTIONS` in `app.py` |
| Max hexes | 20 000 | Change `MAX_HEXES_DEFAULT` / `MAX_HEXES_CAP` |

---

## Data source

Data is produced by the ETL pipeline in `../src/`:

```
GBIF API  →  gbif_etl_job.ipynb       →  s3://ie-datalake/bronze/gbif/
          →  gbif_bronze_to_silver.ipynb  →  s3://ie-datalake/silver/gbif/
          →  gbif_silver_to_gold.ipynb    →  s3://ie-datalake/gold/gbif_cell_metrics/
```

See [`../src/README.md`](../src/README.md) for full pipeline documentation.
