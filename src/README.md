# GBIF Biodiversity ETL Pipeline

This directory contains notebooks that form a **Bronze → Silver → Gold** data lakehouse pipeline for GBIF (Global Biodiversity Information Facility) species occurrence data. Raw exports are downloaded from the GBIF API, cleaned, spatially indexed, and aggregated into ready-to-query cell-level biodiversity metrics stored in S3. Additional pipelines produce species dimension tables, H3–species mappings, and IUCN Red List profiles for the Streamlit Biodiversity Explorer app.

---

## Table of Contents

1. [Architecture overview](#architecture-overview)
2. [Data source – GBIF](#data-source--gbif)
3. [Layer descriptions](#layer-descriptions)
   - [Bronze – `gbif_etl_job.ipynb`](#bronze--gbif_etl_jobipynb)
   - [Silver – `gbif_bronze_to_silver.ipynb`](#silver--gbif_bronze_to_silveripynb)
   - [Gold – `gbif_silver_to_gold.ipynb`](#gold--gbif_silver_to_goldipynb)
   - [Gold – `gbif_silver_to_gold_dim.ipynb`](#gold--gbif_silver_to_gold_dimipynb)
4. [IUCN enrichment pipeline](#iucn-enrichment-pipeline)
   - [Silver – `iucn_species_enrichment.ipynb`](#silver--iucn_species_enrichmentipynb)
   - [Gold – `iucn_silver_to_gold.ipynb`](#gold--iucn_silver_to_goldipynb)
5. [Streamlit Biodiversity Explorer](#streamlit-biodiversity-explorer)
6. [H3 spatial indexing](#h3-spatial-indexing)
7. [Key enrichment columns](#key-enrichment-columns)
8. [Gold metrics reference](#gold-metrics-reference)
9. [Running the pipeline](#running-the-pipeline)
10. [Credentials & AWS setup](#credentials--aws-setup)
11. [Performance notes](#performance-notes)

---

## Architecture overview

```
GBIF API
   │
   │  SIMPLE_PARQUET download (per country × year)
   ▼
┌─────────────────────────────────────────────────────────────┐
│  BRONZE  s3://ie-datalake/bronze/gbif/country=XX/year=YYYY/ │
│  Raw occurrence records + IUCN threat flags + invasive flags│
└────────────────────────────┬────────────────────────────────┘
                             │  coordinate cleaning + H3 index
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  SILVER  s3://ie-datalake/silver/gbif/country=XX/year=YYYY/ │
│  Clean coordinates, h3_9 / h3_8 / h3_7 / h3_6 columns      │
└────────────────────────────┬────────────────────────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │  cell-level       │  species-level     │
         │  aggregation      │  dimension + H3    │
         ▼                   ▼                    │
┌─────────────────────┐  ┌─────────────────────────────────────────────┐
│  GOLD               │  │  GOLD                                        │
│  gbif_cell_metrics  │  │  gbif_species_dim + gbif_species_h3_mapping  │
│  ~20 metrics/cell   │  │  Species lookup + per-species occurrence map │
└─────────────────────┘  └─────────────────────────────────────────────┘

IUCN Red List API
   │
   │  Per-species assessment (rationale, habitat, threats…)
   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  SILVER  s3://ie-datalake/silver/iucn_species_profiles/.../             │
│  species_profiles.json (from iucn_species_enrichment.ipynb)              │
└────────────────────────────┬────────────────────────────────────────────┘
                             │  Parquet conversion
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  GOLD  s3://ie-datalake/gold/iucn_species_profiles/country=XX/year=YYYY/│
│  Rich IUCN profiles for threatened species (Streamlit Species map tab) │
└─────────────────────────────────────────────────────────────────────────┘
```

All layers are stored as **snappy-compressed Parquet**, partitioned by `country` and `year` (and additionally by `h3_resolution` in gold where applicable). Both partition keys are also embedded as regular columns inside each file so queries without a partition filter still work.

---

## Data source – GBIF

**GBIF (Global Biodiversity Information Facility)** is an open international network that aggregates biodiversity data from thousands of institutions worldwide. Each **occurrence record** describes:

- **What** was observed – species, taxonomy, IUCN status
- **Where** – decimal coordinates (WGS84), country, locality
- **When** – event date, year, month
- **How** – basis of record (human observation, preserved specimen, etc.), dataset provenance

Data is downloaded using GBIF's asynchronous bulk-download API (`SIMPLE_PARQUET` format). This produces a ZIP containing an `occurrence.parquet/` directory of column-store part files – typically 0.5–2 GB compressed per country-year for active European countries.

> GBIF occurrence counts reflect *records in the database*, not animal population sizes. Large step-changes in counts usually indicate publisher changes, not ecological events.

---

## Layer descriptions

### Bronze – `gbif_etl_job.ipynb`

**Purpose:** Download raw GBIF occurrence data and enrich it with threatened species and invasive/introduced status flags.

**Key configuration parameters:**

| Parameter | Description |
|---|---|
| `COUNTRIES` | List of ISO-2 country codes to process (e.g. `["ES", "PT", "FR"]`) |
| `YEAR_START` / `YEAR_END` | Inclusive year range |
| `MAX_CONCURRENT_JOBS` | Max simultaneous GBIF download jobs (GBIF limit: 3 per account) |
| `GBIF_POLL_INTERVAL_S` | Seconds between job status polls (default: 30s) |
| `THREATENED_CATS` | IUCN categories considered threatened: `["VU", "EN", "CR"]` |

**What the pipeline does:**

1. **Builds a job plan** – all `(country, year)` pairs, ordered newest-first so the most recent data is available first if the run is interrupted.
2. **Submits GBIF download jobs** – up to `MAX_CONCURRENT_JOBS` at a time using `pygbif.occurrences.download`. Each job filters by `country`, `year`, and `hasCoordinate=True`.
3. **Round-robin polling** – all active jobs are polled concurrently. As soon as any job reaches `SUCCEEDED`, it is immediately processed (download + enrich + upload) without waiting for the rest of the batch.
4. **Extracts Parquet** – downloads the ZIP, unpacks `occurrence.parquet/`, filters out 0-byte part files (a known GBIF export artefact), and reads with PyArrow.
5. **Enriches with IUCN threat data** – queries `occurrences.search` facets for `speciesKey` values with `iucnRedListCategory` in `[VU, EN, CR]` for the same country. Adds `iucn_cat` column. Result is cached per country to avoid duplicate API calls across years.
6. **Enriches with invasive/introduced flags** – combines:
   - Export columns `establishmentMeans` and `degreeOfEstablishment` (Darwin Core fields)
   - GBIF search API facets for `degreeOfEstablishment=invasive` and `establishmentMeans=introduced`
   - Produces boolean columns: `is_invasive_any`, `is_introduced`, `is_naturalized`, `is_invasive_doe`, `is_invasive_api`, `is_introduced_api`
7. **Writes to S3** – partitioned Parquet with `existing_data_behavior="delete_matching"` (safe re-run / overwrite semantics).
8. **Cleans up** local temp files.

**Output S3 path:**
```
s3://ie-datalake/bronze/gbif/country={XX}/year={YYYY}/part-XXXXX.parquet
```

---

### Silver – `gbif_bronze_to_silver.ipynb`

**Purpose:** Clean coordinates and add H3 spatial index columns at four resolutions.

**Key configuration parameters:**

| Parameter | Description |
|---|---|
| `COUNTRIES` / `YEAR_START` / `YEAR_END` | Scope of data to process |
| `H3_RESOLUTIONS` | Resolutions to add: `[9, 8, 7, 6]` |
| `DROP_NULL_ISLAND` | Drop records at exactly `(0, 0)` – usually GPS artefacts |

**Pipeline functions:**

| Function | What it does |
|---|---|
| `read_input(country, year)` | Reads bronze partition with column projection (only needed columns) |
| `clean_coordinates(df)` | Drops rows with null lat/lon, lat outside `[-90, 90]`, lon outside `[-180, 180]`, and `(0.0, 0.0)` |
| `add_h3(df)` | Computes `h3_9` from `(lat, lon)` using `h3.latlng_to_cell`, then derives `h3_8`, `h3_7`, `h3_6` via `h3.cell_to_parent` |
| `write_silver(df, country, year)` | Writes partitioned Parquet to silver layer |

**New columns added in silver:**

| Column | Type | Description |
|---|---|---|
| `h3_9` | string | H3 cell index at resolution 9 (~0.1 km²) |
| `h3_8` | string | H3 cell index at resolution 8 (~0.7 km²) |
| `h3_7` | string | H3 cell index at resolution 7 (~5 km²) |
| `h3_6` | string | H3 cell index at resolution 6 (~36 km²) |

**Output S3 path:**
```
s3://ie-datalake/silver/gbif/country={XX}/year={YYYY}/part-XXXXX.parquet
```

---

### Gold – `gbif_silver_to_gold.ipynb`

**Purpose:** Aggregate silver records into one row per `(country, year, h3_resolution, h3_index)` with ~20 biodiversity and data-quality metrics.

**Key configuration parameters:**

| Parameter | Description |
|---|---|
| `COUNTRIES` / `YEAR_START` / `YEAR_END` | Scope of data to process |
| `H3_RESOLUTIONS` | Resolutions to aggregate: `[9, 8, 7, 6]` |

**Pipeline functions:**

| Function | What it does |
|---|---|
| `read_input(country, year)` | Reads silver with projection pushdown using PyArrow native C++ S3 client |
| `compute_metrics(df, country, year, h3_resolution)` | Full aggregation for one resolution (see metrics table below) |
| `write_gold(agg, country, year, h3_resolution)` | Writes partitioned Parquet to gold layer |

**Output S3 path:**
```
s3://ie-datalake/gold/gbif_cell_metrics/country={XX}/year={YYYY}/h3_resolution={N}/part-XXXXX.parquet
```

---

### Gold – `gbif_silver_to_gold_dim.ipynb`

**Purpose:** Build species dimension and H3–species mapping tables for the Streamlit app (Analysis tab, Species map tab).

| Table | S3 path | Description |
|-------|---------|-------------|
| **gbif_species_dim** | `s3://ie-datalake/gold/gbif_species_dim/country=XX/year=YYYY/` | One row per species per (country, year): taxon_key, species_name, occurrence_count, is_threatened, is_invasive |
| **gbif_species_h3_mapping** | `s3://ie-datalake/gold/gbif_species_h3_mapping/country=XX/year=YYYY/h3_resolution=N/` | Mapping: which species occur in which H3 cell – for fast region lookups and per-species maps |

**Key configuration parameters:**

| Parameter | Description |
|---|---|
| `COUNTRIES` / `YEAR_START` / `YEAR_END` | Scope of data to process |
| `H3_RESOLUTIONS` | Resolutions to build: `[9, 8, 7, 6]` |

**Pipeline functions:**

| Function | What it does |
|---|---|
| `build_species_dim(df, country, year)` | Aggregates by taxon_key: occurrence_count, is_threatened, is_invasive, species_name |
| `build_h3_mapping(df, country, year, h3_resolution)` | Groups by (h3_index, taxon_key) with occurrence_count, is_threatened, is_invasive |

**Output columns:**

| Table | Columns |
|---|---|
| gbif_species_dim | taxon_key, species_name, occurrence_count, is_threatened, is_invasive, country, year |
| gbif_species_h3_mapping | h3_index, taxon_key, occurrence_count, is_threatened, is_invasive, h3_resolution, country, year |

**Required:** Silver GBIF layer must exist. Run `gbif_bronze_to_silver.ipynb` first.

---

## IUCN enrichment pipeline

### Silver – `iucn_species_enrichment.ipynb`

**Purpose:** Enrich threatened (and optionally invasive) species from the GBIF silver layer with full IUCN Red List assessments via the [IUCN Red List API v4](https://api.iucnredlist.org/api-docs/index.html).

**Flow:**
1. Reads unique threatened species (CR, EN, VU) from GBIF silver
2. For each species: `GET /taxa/scientific_name` → `GET /assessment/{id}` to fetch full narrative (rationale, habitat, threats, conservation)
3. Writes `species_profiles.json` to S3 silver and local `iucn_enrichment/`

**Output locations:**

| Location | Content |
|----------|---------|
| S3 `s3://ie-datalake/silver/iucn_species_profiles/country=XX/year=YYYY/` | species_profiles.json – array of enriched profiles |
| Local `iucn_enrichment/species_profiles.json` | Same – ready for LLM/agentic pipeline |
| Local `iucn_enrichment/iucn_cache.json` | API call cache (saves quota on re-runs) |

**Note:** IUCN Red List covers *threatened species* (extinction risk). Invasive species often have LC/NE status → lower hit rate when querying IUCN for invasive-only lists.

---

### Gold – `iucn_silver_to_gold.ipynb`

**Purpose:** Convert IUCN species profiles from JSON (silver) to Parquet (gold) for efficient querying in the Streamlit app.

| Layer | S3 path |
|-------|---------|
| Silver in | `s3://ie-datalake/silver/iucn_species_profiles/country=XX/year=YYYY/species_profiles.json` |
| Gold out | `s3://ie-datalake/gold/iucn_species_profiles/country=XX/year=YYYY/` |

**Key columns in gold:** scientific_name, rationale, habitat_ecology, population, range_description, threats_text, conservation_text, iucn_category, iucn_category_description, population_trend.

---

## Streamlit Biodiversity Explorer

The app (`streamlit/app.py`) provides three tabs:

| Tab | Description |
|-----|--------------|
| **Map** | Folium map with H3 hex overlay; click hexes to add to selection; top-N or viewport snapshot modes |
| **Analysis** | Species per selected hex, threatened vs not, IUCN rationale for threatened species |
| **Species map** | Search any species by name → Folium map of H3 cells where it occurs; IUCN panel when threatened |

**Species map tab (new):**
- Search by partial name (e.g. `Cortaderia`, `invasive`, `Abies pinsapo`)
- Uses `gbif_species_dim` (species lookup) + `gbif_species_h3_mapping` (occurrence hexes)
- H3 resolution selector (6, 7, 8, 9) – finer resolutions show more detail
- Fallback: if no data at selected resolution, tries others automatically
- IUCN panel for threatened species: rationale, habitat, population, threats, conservation (from `iucn_species_profiles` gold)
- Map uses `returned_objects=[]` so pan/zoom does not trigger reruns

**Required gold tables:** `gbif_cell_metrics`, `gbif_species_dim`, `gbif_species_h3_mapping`, `iucn_species_profiles` (for IUCN panel).

**Run:** `streamlit run streamlit/app.py` (from repo root).

---

## H3 spatial indexing

The pipeline uses [Uber H3](https://h3geo.org/) – a hierarchical hexagonal grid system – to assign every occurrence record to spatial cells at multiple zoom levels.

```
Resolution 9  ──▶  ~0.1 km²   fine-grained point lookup, individual habitat patches
Resolution 8  ──▶  ~0.7 km²   neighbourhood scale
Resolution 7  ──▶  ~5 km²     local area (e.g. a municipality)
Resolution 6  ──▶  ~36 km²    regional scale (e.g. a county / comarca)
```

**Parent derivation:** `h3_9` is computed from raw coordinates. Coarser resolutions are derived using `h3.cell_to_parent(h3_9, resolution)` – no re-projection needed. This means each record has a consistent hierarchy: `h3_6 ⊃ h3_7 ⊃ h3_8 ⊃ h3_9`.

**Why four resolutions in gold?** The gold layer is intended to power a scrollable interactive map. At low zoom levels (whole-country view) resolution 6 or 7 is appropriate; zooming in progressively switches to 8 and 9. Pre-aggregating all four resolutions avoids on-the-fly re-aggregation in the application layer.

---

## Key enrichment columns

These columns are added during the bronze ETL and flow through to silver and gold.

### IUCN Red List categories

| Value | Meaning |
|---|---|
| `LC` | Least Concern |
| `NT` | Near Threatened |
| `VU` | Vulnerable *(threatened)* |
| `EN` | Endangered *(threatened)* |
| `CR` | Critically Endangered *(threatened)* |
| `EW` | Extinct in the Wild |
| `EX` | Extinct |
| `DD` | Data Deficient |
| `NE` | Not Evaluated |

Column added: **`iucn_cat`** – the highest-severity IUCN category for the record's species as reported in the GBIF search API.

### Invasive / introduced status

| Column | Source | Meaning |
|---|---|---|
| `is_invasive_doe` | `degreeOfEstablishment` export column | Record flagged as invasive via Darwin Core field |
| `is_invasive_em` | `establishmentMeans` export column | Record flagged via `establishmentMeans` |
| `is_introduced` | `establishmentMeans` export column | Species introduced (non-native) |
| `is_naturalized` | `establishmentMeans` export column | Species naturalized (established non-native) |
| `is_invasive_api` | GBIF search API facet | `speciesKey` found in GBIF's `degreeOfEstablishment=invasive` list |
| `is_introduced_api` | GBIF search API facet | `speciesKey` found in GBIF's `establishmentMeans=introduced` list |
| **`is_invasive_any`** | Combined | `True` if any of the above flags is `True` |

> **Note on GBIF invasive data completeness:** GBIF's own occurrence records often have sparse `establishmentMeans`/`degreeOfEstablishment` coverage. The `_api` flags (fetched via search facets) capture species known to be invasive even when the individual record lacks the field. For a more authoritative invasive species list, cross-reference with external checklists such as [GRIIS](https://www.griis.org/).

---

## Gold metrics reference

Each row in the gold table represents a unique `(country, year, h3_resolution, h3_index)` combination.

### Observation metrics

| Column | Description |
|---|---|
| `h3_index` | H3 cell identifier |
| `h3_resolution` | Resolution (6, 7, 8, or 9) |
| `country` | ISO-2 country code |
| `year` | Observation year |
| `observation_count` | Total occurrence records in the cell |
| `species_richness_cell` | Distinct species (uses `speciesKey` → `taxonKey` → species string, whichever is available) |
| `unique_datasets` | Distinct `datasetKey` values (data source diversity) |
| `avg_coordinate_uncertainty_m` | Mean `coordinateUncertaintyInMeters` for records in the cell |
| `pct_uncertainty_gt_10km` | Share of records with coordinate uncertainty > 10 000 m |

### IUCN / Threat metrics

All IUCN metrics are computed over **distinct species** within the cell, not raw record counts. A species present in 1000 records still counts as 1.

| Column | Description |
|---|---|
| `n_assessed_species` | Distinct species with any IUCN category |
| `n_sp_cr` | Distinct Critically Endangered species |
| `n_sp_en` | Distinct Endangered species |
| `n_sp_vu` | Distinct Vulnerable species |
| `n_sp_nt` | Distinct Near Threatened species |
| `n_sp_lc` | Distinct Least Concern species |
| `n_sp_dd` | Distinct Data Deficient species |
| `n_sp_ne` | Distinct Not Evaluated species |
| `n_threatened_species` | Distinct CR + EN + VU species |
| `threat_score_weighted` | Σ weight per distinct species: CR=5, EN=4, VU=3, NT=2, else=0 |

### Diversity metrics

Both indices are computed on the **species observation count table** (aggregated per cell × species), not on raw records. This keeps memory usage low for large partitions.

| Column | Formula | Interpretation |
|---|---|---|
| `shannon_H` | H = −Σ pᵢ · ln(pᵢ) | Higher = more evenly distributed species. 0 = single species. |
| `simpson_1_minus_D` | 1 − Σ pᵢ² | Probability that two random records belong to different species. 0 = one species, 1 = max diversity. |

Where pᵢ = (observations of species i) / (total observations in cell).

### Data Quality Index (DQI)

A composite 0–1 score reflecting how trustworthy the cell's data is for analysis. Higher is better.

```
DQI = mean of available components:
  c1 = share of records with a valid species identifier
  c2 = 1 − pct_uncertainty_gt_10km  (if uncertainty column present)
  c3 = share of records with IUCN category present  (if iucn_cat column present)
```

| Column | Description |
|---|---|
| `dqi` | Composite data quality score (0–1) |

---

## Running the pipeline

### Core GBIF pipeline

Run the notebooks **in order**:

```
1. gbif_etl_job.ipynb          →  Bronze (downloads from GBIF, ~hours for large countries)
2. gbif_bronze_to_silver.ipynb →  Silver (coordinate cleaning + H3, ~minutes)
3. gbif_silver_to_gold.ipynb   →  Gold   (cell metrics, ~minutes)
4. gbif_silver_to_gold_dim.ipynb → Gold (species dim + H3 mapping, ~minutes)
```

### IUCN enrichment (for Species map IUCN panel)

```
5. iucn_species_enrichment.ipynb → Silver (IUCN API → species_profiles.json)
6. iucn_silver_to_gold.ipynb    → Gold   (JSON → Parquet)
```

**Note:** `iucn_species_enrichment` reads threatened species from GBIF silver. Run steps 1–2 first.

### Streamlit app

```
streamlit run streamlit/app.py
```

Requires gold tables: `gbif_cell_metrics`, `gbif_species_dim`, `gbif_species_h3_mapping`. For IUCN panel in Analysis and Species map tabs, also run `iucn_silver_to_gold`.

---

Each notebook has a **Configuration cell at the top** – edit `COUNTRIES`, `YEAR_START`, and `YEAR_END` there before running. The cells below are self-contained and can be re-run safely: all writes use `existing_data_behavior="delete_matching"` so existing S3 partitions are overwritten cleanly.

**Processing order in bronze:** Jobs are submitted newest-year-first (`YEAR_END` → `YEAR_START`). If you stop mid-run you can check S3 for what's already been written and restart with an adjusted year range.

**Partial re-runs:** Because every layer is partitioned by `country` and `year`, you can process individual partitions independently. For example, to reprocess only France 2023:

```python
COUNTRIES   = ["FR"]
YEAR_START  = 2023
YEAR_END    = 2023
```

---

## Credentials & AWS setup

### GBIF credentials

Required for submitting download jobs. Set in a `.env` file in the repo root:

```
GBIF_USER=your_gbif_username
GBIF_PWD=your_gbif_password
GBIF_EMAIL=your_email@example.com
```

### IUCN Red List API (optional)

Required for `iucn_species_enrichment.ipynb`. Get a token at [IUCN Red List API](https://apiv3.iucnredlist.org/api/v3/token). Add to `.env`:

```
IUCN_API_KEY=your_iucn_api_token
```

### AWS credentials (SSO)

All S3 operations use the profile `486717354268_PowerUserAccess`. Authenticate with:

```bash
aws sso login --profile 486717354268_PowerUserAccess
```

If you get a `Token has expired` error mid-run, re-login and then clear the cached filesystem client in the notebook:

```python
import s3fs
s3fs.S3FileSystem.clear_instance_cache()
fs = s3fs.S3FileSystem(profile=AWS_PROFILE)
```

---

## Performance notes

| Notebook | Typical runtime (ES 2024 ~7M records) | Main bottleneck |
|---|---|---|
| Bronze | 15–45 min per country-year | GBIF server-side export generation |
| Silver | 2–5 min | H3 vectorized computation |
| Gold (cell metrics) | 1–3 min | Groupby aggregation (fully vectorized) |
| Gold (species dim) | 2–5 min | Species + H3 mapping aggregation |
| IUCN enrichment | 10–60 min | IUCN API rate limits (cached locally) |
| IUCN silver→gold | <1 min | JSON→Parquet conversion |

**Silver and Gold are memory-bounded.** For a 1 GB compressed Parquet file (~7M rows × 14 projected columns), expect ~2–4 GB RAM usage during processing. Only one `(country, year)` partition is held in memory at a time.

**Gold uses PyArrow's native C++ S3 filesystem** (`pyarrow.fs.S3FileSystem`) for reads instead of `s3fs`. This enables parallel row-group pre-fetching, which is significantly faster when reading columnar data from S3 over high-latency connections.

**Diversity metrics** (Shannon, Simpson) are computed on the already-aggregated `(cell, species)` count table, not on the full record DataFrame, reducing the working-set size by several orders of magnitude.
