# OSM Pipeline: Bronze → Silver → Gold

This document describes the OSM (OpenStreetMap) data pipeline: **Bronze → Silver** (feature extraction) and **Silver → Gold** (hex-level aggregation). It covers input data, execution environments, feature types, and how metrics are computed.

---

## Pipeline Overview

```
Bronze (OSM PBF)                    Silver (Parquet)                      Gold (Parquet)
┌─────────────────────────┐        ┌──────────────────────────────┐       ┌─────────────────────────────┐
│ bbox_00.osm.pbf ..      │        │ features_energy/             │       │ osm_hex_features/           │
│ bbox_19.osm.pbf         │  ───►  │ country=XX/                  │  ───► │ country=XX/                 │
│ (pre-split bboxes)      │        │ snapshot_date=YYYY-MM-DD/   │       │ h3_resolution=N/            │
│                         │        │ feature_type=<TYPE>/         │       │                             │
└─────────────────────────┘        └──────────────────────────────┘       └─────────────────────────────┘
         │                                      │
         │  osm_bronze_to_silver.ipynb          │  osm_silver_to_gold.ipynb
         │  (SageMaker Studio)                  │  (AWS Glue / Spark)
         └──────────────────────────────────────┘
```

| Stage | Notebook | Execution | Input | Output |
|-------|----------|-----------|-------|--------|
| **Bronze → Silver** | `osm_bronze_to_silver.ipynb` / `osm_bronze_to_silver_sage.ipynb` | **AWS SageMaker** (Studio) | OSM PBF bboxes in S3 | Parquet per feature_type |
| **Silver → Gold** | `osm_silver_to_gold.ipynb` | **AWS Glue** (Spark) | Silver Parquet | Hex-level metrics Parquet |

---

## 1. Bronze → Silver: `osm_bronze_to_silver`

### Execution environment

Runs on **AWS SageMaker Studio**. Uses `ProcessPoolExecutor` for parallel processing of multiple bbox files. Dependencies: `osmium`, `geopandas`, `pyarrow`, `s3fs`, `h3`, `pyproj`, `shapely`.

### Input data

| Source | Path | Description |
|--------|------|-------------|
| Bronze OSM | `s3://ie-datalake/bronze/osm/bboxes/bbox_00.osm.pbf` … `bbox_19.osm.pbf` | Pre-split OSM PBF files (country bounding box divided into tiles) |

### Processing logic

1. **Download** each bbox PBF from S3 to a temp directory.
2. **Parse** using `osmium` handler (`EnergyFeaturesHandler`): nodes, ways, areas.
3. **Classify** each OSM object into a `feature_type` via `match_feature_type(tags)` – first matching rule wins.
4. **Compute geometry**:
   - `length_m` – length in metres (EPSG:25830) for lines.
   - `area_m2` – area in m² for polygons; for lines (e.g. roads) estimated as `length_m × ROAD_WIDTH_M[highway]` when `area_m2 == 0`.
5. **Assign H3** – centroid → `h3_6`, `h3_7`, `h3_8`, `h3_9` via `h3.latlng_to_cell` and `h3.cell_to_parent`.
6. **Write** Parquet to Silver, partitioned by `country`, `snapshot_date`, `feature_type`.

### Output

| Path | Format |
|------|--------|
| `s3://ie-datalake/silver/osm/features_energy/country=XX/snapshot_date=YYYY-MM-DD/feature_type=<TYPE>/` | Snappy Parquet |

Columns: `osm_id`, `osm_type`, `feature_type`, `geometry` (WKB), `length_m`, `area_m2`, `centroid_lat`, `centroid_lon`, `h3_6` … `h3_9`, `tags_json`, promoted keys (`highway`, `waterway`, `power`, etc.).

---

## 2. Silver → Gold: `osm_silver_to_gold`

### Execution environment

Runs on **AWS Glue** (Spark). Uses PySpark with optional `GlueContext`. Single Spark job: read Silver, aggregate, write Gold.

### Input data

| Source | Path | Description |
|--------|------|-------------|
| Silver | `s3://ie-datalake/silver/osm/features_energy/` | Parquet with `feature_type`, `length_m`, `area_m2`, `h3_6` … `h3_9` |

### Processing logic

1. **Read** Silver partition(s) with explicit schema (avoids BINARY/dict conflicts).
2. **Explode** `h3_6` … `h3_9` into rows per `(country, h3_resolution, h3_index)` via `stack(4, 6, h3_6, 7, h3_7, 8, h3_8, 9, h3_9)`.
3. **Aggregate** per `(country, h3_resolution, h3_index)`:
   - **Counts** – `SUM(1)` when `feature_type == X` (or when highway/power/etc. matches).
   - **Area sums** – `SUM(area_m2)` when `feature_type == X`.
4. **Derived metrics**:
   - `hex_area_m2` – constant per resolution (6: 36.1M, 7: 5.2M, 8: 737k, 9: 105k m²).
   - `*_area_pct` = `*_area_m2 / hex_area_m2 × 100`.
   - `human_footprint_area_m2` = building + industrial + parks_green + waste_site.
   - `urban_footprint_area_m2` = human_footprint + residential + commercial + parking + road + cemetery + construction.
   - `road_count_per_km2`, `building_count_per_km2`, `power_plant_count_per_km2`, `protected_area_count_per_km2`.

### Output

| Path | Format |
|------|--------|
| `s3://ie-datalake/gold/osm_hex_features/country=XX/h3_resolution=N/` | Snappy Parquet |

---

## 3. Feature Types (Silver) – Definitions and Extraction

Each feature type is assigned in `osm_bronze_to_silver` based on OSM tags. **Order matters** – the first matching type wins.

### A) Energy & Infrastructure

| feature_type | OSM Tags (condition) | What it includes |
|--------------|----------------------|------------------|
| **PIPELINES** | `man_made=pipeline` OR `pipeline=*` OR `substance=*` OR `location` in (underground, overground) | Pipelines (gas, oil, water, chemicals) – lines and areas |
| **POWER_LINES** | `power` in (line, minor_line, cable) | Power lines (overhead, underground cables) |
| **POWER_SUBSTATIONS** | `power=substation` | Substations, switchyards |
| **POWER_PLANTS** | `power` in (plant, generator) | Power plants and generators – all types (coal, gas, nuclear, solar, wind, hydro, etc.) |
| **INDUSTRIAL_AREAS** | `landuse=industrial` OR `industrial=*` OR `man_made=works` | Industrial areas, factories |
| **STORAGE_TANKS** | `man_made=storage_tank` OR `landuse=depot` OR `industrial` in (oil, chemical) | Storage tanks, fuel/chemical depots |
| **FUEL_STATIONS** | `amenity=fuel` | Fuel stations |

### B) Transport

| feature_type | OSM Tags (condition) | What it includes |
|--------------|----------------------|------------------|
| **PORTS_TERMINALS** | `harbour=*` OR `landuse=port` OR `man_made=pier` OR `amenity=ferry_terminal` | Ports, terminals, piers, ferries |
| **AIRPORTS** | `aeroway` in (aerodrome, terminal, runway, taxiway) | Airports, terminals, runways, taxiways |
| **TRAILS_TRACKS** | `highway` in (path, track, footway, bridleway, cycleway) | Paths, tracks, footways, bridleways, cycleways – matched before ROADS |
| **ROADS** | `highway=*` (all remaining) | Roads: motorway, trunk, primary, secondary, tertiary, residential, service, etc. |
| **RAIL** | `railway` in (rail, light_rail, subway, tram) | Rail lines, tramways, metro |

### C) Water & Wetness

| feature_type | OSM Tags (condition) | What it includes |
|--------------|----------------------|------------------|
| **WATER_BARRIERS** | `waterway` in (dam, weir, lock_gate) OR `man_made=dam` | Dams, weirs, locks – matched before WATERWAYS |
| **WATERWAYS** | `waterway=*` (remaining) | Rivers, streams, canals, ditches, drains |
| **WATERBODIES** | `natural=water` OR `water=*` OR `landuse=reservoir` | Lakes, ponds, reservoirs, pools |
| **WETLANDS** | `natural=wetland` OR `wetland=*` | Marshes, wetlands, peatlands |
| **COASTLINE** | `natural=coastline` | Coastline |
| **WATER_INFRA_POI** | `man_made=water_tower` OR `amenity=drinking_water` OR `emergency=water_tank` | Water towers, drinking water points, emergency tanks |

### D) Administrative & Constraints

| feature_type | OSM Tags (condition) | What it includes |
|--------------|----------------------|------------------|
| **ADMIN_BOUNDARIES** | `boundary=administrative` | Administrative boundaries (municipalities, counties, regions) |
| **PROTECTED_AREAS** | `boundary=protected_area` OR `leisure=nature_reserve` | Protected areas, nature reserves |
| **RESTRICTED_AREAS** | `military=*` OR `landuse=military` OR `boundary=military` | Military areas, restricted zones |

### E) Urban Landuse (added in recent batches)

| feature_type | OSM Tags (condition) | What it includes |
|--------------|----------------------|------------------|
| **RESIDENTIAL_AREAS** | `landuse=residential` | Residential zones |
| **COMMERCIAL_AREAS** | `landuse` in (commercial, retail) | Commercial and retail zones |
| **PARKING_AREAS** | `amenity=parking` OR `landuse=garages` | Parking lots, garages |
| **CEMETERIES** | `landuse=cemetery` | Cemeteries |
| **CONSTRUCTION** | `landuse=construction` | Construction sites |
| **RETENTION_BASIN** | `landuse=basin` | Retention basins |

### F) Human Footprint

| feature_type | OSM Tags (condition) | What it includes |
|--------------|----------------------|------------------|
| **BUILDINGS** | `building=*` | Buildings (all types) |
| **AMENITIES_POI** | `amenity` in (school, hospital, university, marketplace, prison, waste_disposal, recycling) | Schools, hospitals, universities, marketplaces, prisons, recycling points |
| **WASTE_POLLUTION** | `landuse=landfill` OR `man_made=wastewater_plant` | Landfills, wastewater treatment plants |

### G) Landuse / Habitat

| feature_type | OSM Tags (condition) | What it includes |
|--------------|----------------------|------------------|
| **LANDUSE_AGRICULTURE** | `landuse` in (farmland, farmyard, orchard, vineyard, meadow) | Farmland, orchards, vineyards, meadows |
| **FORESTRY_MANAGED** | `landuse=forest` OR `forest=*` | Managed forests |
| **NATURAL_HABITATS** | `natural` in (wood, heath, scrub, grassland, bare_rock, sand, beach, cliff) | Natural woods, heathland, scrub, grassland, bare rock, sand, beaches, cliffs |

### H) Barriers & Fragmentation

| feature_type | OSM Tags (condition) | What it includes |
|--------------|----------------------|------------------|
| **TREE_ROWS_HEDGEROWS** | `natural=tree_row` OR `barrier=hedge` | Tree rows, hedgerows – matched before BARRIERS |
| **BARRIERS** | `barrier` in (fence, wall, hedge, gate, bollard) | Fences, walls, gates, bollards |
| **LINEAR_DISTURBANCE** | `man_made` in (cutline, embankment) OR `barrier=ditch` | Cutlines, embankments, linear ditches |

### I) Green / Urban Ecology

| feature_type | OSM Tags (condition) | What it includes |
|--------------|----------------------|------------------|
| **PARKS_GREEN_URBAN** | `leisure` in (park, garden, common, golf_course, pitch) OR `landuse=recreation_ground` | Parks, gardens, recreation grounds, sports pitches |

---

## 4. Gold Metrics – How They Are Computed

Each gold row = one H3 hex (`h3_index`) at a given resolution (`h3_resolution`) and country (`country`). Features include **counts**, **area (m²)**, and **area %** (share of hex covered).

### Hex area constants (m²)

| h3_resolution | hex_area_m2 | hex_area_km2 |
|---------------|-------------|--------------|
| 6 | 36 129 062.16 | 36.13 |
| 7 | 5 161 293.36 | 5.16 |
| 8 | 737 327.60 | 0.74 |
| 9 | 105 332.51 | 0.11 |

### Count metrics

| Metric | Formula |
|--------|---------|
| `road_count` | `SUM(1)` where `feature_type == "ROADS"` |
| `major_road_count` | `SUM(1)` where `feature_type == "ROADS"` AND `highway` IN (motorway, trunk, primary, secondary, tertiary) |
| `trail_count` | `SUM(1)` where `feature_type == "TRAILS_TRACKS"` |
| `rail_count` | `SUM(1)` where `feature_type == "RAIL"` |
| `fuel_station_count` | `SUM(1)` where `feature_type == "FUEL_STATIONS"` |
| `solar_plant_count` | `SUM(1)` where `feature_type == "POWER_PLANTS"` AND `plant_source`/`generator_source` RLIKE "solar\|photovoltaic" |
| `wind_plant_count` | `SUM(1)` where `feature_type == "POWER_PLANTS"` AND source RLIKE "wind" |
| `hydro_plant_count` | `SUM(1)` where `feature_type == "POWER_PLANTS"` AND source RLIKE "hydro\|water" |
| `dam_count` | `SUM(1)` where `man_made == "dam"` (any feature_type) |
| `weir_count` | `SUM(1)` where `waterway == "weir"` |
| `lock_count` | `SUM(1)` where `waterway == "lock_gate"` |

### Area metrics

| Metric | Formula |
|--------|---------|
| `*_area_m2` | `SUM(area_m2)` where `feature_type == X` (e.g. `waterbody_area_m2`, `building_area_m2`, `residential_area_m2`) |
| `*_area_pct` | `*_area_m2 / hex_area_m2 × 100` |

### Composite metrics (do not sum with base categories)

| Metric | Formula |
|--------|---------|
| `human_footprint_area_m2` | `building_area_m2 + industrial_area_m2 + parks_green_area_m2 + waste_site_area_m2` |
| `human_footprint_area_pct` | `human_footprint_area_m2 / hex_area_m2 × 100` |
| `urban_footprint_area_m2` | `human_footprint_area_m2 + residential_area_m2 + commercial_area_m2 + parking_area_m2 + road_area_m2 + cemetery_area_m2 + construction_area_m2` |
| `urban_footprint_area_pct` | `urban_footprint_area_m2 / hex_area_m2 × 100` |

### Density metrics

| Metric | Formula |
|--------|---------|
| `road_count_per_km2` | `road_count / hex_area_km2` |
| `building_count_per_km2` | `building_count / hex_area_km2` |
| `power_plant_count_per_km2` | `power_plant_count / hex_area_km2` |
| `protected_area_count_per_km2` | `protected_area_count / hex_area_km2` |

---

## 5. Gold Layer Features – Reference

### Transport / Connectivity

| Feature | Description |
|---------|-------------|
| `road_count` | Number of road segments (ROADS) in the hex |
| `major_road_count` | Number of major road segments: motorway, trunk, primary, secondary, tertiary |
| `trail_count` | Number of paths and tracks (path, track, footway, bridleway, cycleway) |
| `rail_count` | Number of rail / tram / metro segments |
| `port_feature_count` | Number of port features (ports, piers, ferries) |
| `airport_feature_count` | Number of airport features (airports, runways, terminals) |
| `road_count_per_km2` | `road_count / hex_area_km2` – road density |

### Energy

| Feature | Description |
|---------|-------------|
| `pipeline_count` | Number of pipeline segments |
| `power_line_count` | Number of power line segments |
| `power_substation_count` | Number of substations |
| `power_plant_count` | Number of power plants and generators (all types) |
| `solar_plant_count` | Number of solar plants (plant_source/generator_source ~ solar\|photovoltaic) |
| `wind_plant_count` | Number of wind plants |
| `hydro_plant_count` | Number of hydro plants |
| `industrial_area_count` | Number of industrial areas |
| `industrial_area_m2`, `industrial_area_pct` | Total industrial area (m²) and % of hex |
| `storage_tank_count` | Number of storage tanks |
| `fuel_station_count` | Number of fuel stations |
| `power_plant_count_per_km2` | `power_plant_count / hex_area_km2` |

### Hydro & Wetness

| Feature | Description |
|---------|-------------|
| `waterway_count` | Number of waterway segments (rivers, streams, canals, ditches) |
| `waterbody_count` | Number of water bodies (lakes, ponds, pools) |
| `waterbody_area_m2`, `waterbody_area_pct` | Total area of water bodies in the hex (m²) and % |
| `wetland_count` | Number of wetland areas |
| `wetland_area_m2`, `wetland_area_pct` | Total area of wetlands in the hex (m²) and % |
| `waterway_area_m2`, `waterway_area_pct` | Riverbank/canal area (m²) and % |
| `water_wetland_area_pct` | % of hex covered by water + wetlands combined |
| `coastline_count` | Number of coastline segments |
| `dam_count` | Number of dams (`man_made=dam`) |
| `weir_count` | Number of weirs (`waterway=weir`) |
| `lock_count` | Number of locks (`waterway=lock_gate`) |
| `water_barrier_count_total` | Number of WATER_BARRIERS (dams, weirs, locks) |
| `water_infra_poi_count` | Number of water infrastructure points (water towers, drinking water) |

### Built Footprint / Human Pressure

| Feature | Description |
|---------|-------------|
| `building_count` | Number of buildings |
| `building_area_m2`, `building_area_pct` | Total building footprint area (m²) and % of hex |
| `amenity_count_total` | Number of amenity POIs (schools, hospitals, universities, marketplaces, prisons, recycling points) |
| `parks_green_count` | Number of parks and urban green areas |
| `parks_green_area_m2`, `parks_green_area_pct` | Total area of parks and green urban space (m²) and % |
| `tree_rows_hedgerow_count` | Number of tree rows and hedgerows |
| `building_count_per_km2` | `building_count / hex_area_km2` |
| `human_footprint_area_m2`, `human_footprint_area_pct` | Buildings + industrial + parks/green + waste sites (m²) and % – **composite** |
| `urban_footprint_area_m2`, `urban_footprint_area_pct` | human_footprint + residential + commercial + parking + road + cemetery + construction – **composite** |

### Residential / Commercial / Urban Landuse (added in recent batches)

| Feature | Description |
|---------|-------------|
| `residential_area_m2`, `residential_area_pct` | Residential zones (landuse=residential) |
| `commercial_area_m2`, `commercial_area_pct` | Commercial and retail zones |
| `parking_area_m2`, `parking_area_pct` | Parking lots, garages |
| `cemetery_area_m2`, `cemetery_area_pct` | Cemeteries |
| `construction_area_m2`, `construction_area_pct` | Construction sites |
| `retention_basin_area_m2`, `retention_basin_area_pct` | Retention basins |

### Landuse / Habitat

| Feature | Description |
|---------|-------------|
| `landuse_agriculture_count` | Number of agricultural areas (farmland, farmyard, orchard, vineyard, meadow) |
| `agri_area_m2`, `agri_area_pct` | Total agricultural area (m²) and % of hex |
| `managed_forest_count` | Number of managed forest areas |
| `managed_forest_area_m2`, `managed_forest_area_pct` | Total managed forest area (m²) and % |
| `natural_habitat_count` | Number of natural habitat areas (wood, heath, scrub, grassland, bare_rock, sand, beach, cliff) |
| `natural_habitat_area_m2`, `natural_habitat_area_pct` | Total natural habitat area (m²) and % |

### Constraints

| Feature | Description |
|---------|-------------|
| `protected_area_count` | Number of protected areas and nature reserves |
| `protected_area_m2`, `protected_area_pct` | Total protected area (m²) and % of hex |
| `restricted_area_count` | Number of military / restricted areas |
| `restricted_area_m2`, `restricted_area_pct` | Total restricted area (m²) and % |
| `admin_boundary_count` | Number of administrative boundaries |
| `protected_area_count_per_km2` | `protected_area_count / hex_area_km2` |

### Fragmentation / Barriers

| Feature | Description |
|---------|-------------|
| `barrier_count` | Number of barriers (fences, walls, gates, bollards) |
| `linear_disturbance_count` | Number of linear disturbances (cutlines, embankments, ditches) |

### Pollution / Waste

| Feature | Description |
|---------|-------------|
| `waste_site_count` | Number of landfills and wastewater treatment plants |
| `waste_site_area_m2` | Total area of waste sites (m²) |

### Hex Metadata

| Feature | Description |
|---------|-------------|
| `h3_index` | H3 cell identifier |
| `h3_resolution` | H3 resolution (6, 7, 8, 9) |
| `country` | Country code (ISO-2) |
| `hex_area_m2` | Approximate hex area in m² (constant per resolution) |
| `hex_area_km2` | `hex_area_m2 / 1e6` |

---

## 6. S3 Paths

| Layer | Path |
|-------|------|
| Bronze in | `s3://ie-datalake/bronze/osm/bboxes/bbox_NN.osm.pbf` |
| Silver in | `s3://ie-datalake/silver/osm/features_energy/country=XX/snapshot_date=YYYY-MM-DD/feature_type=<TYPE>/` |
| Gold out | `s3://ie-datalake/gold/osm_hex_features/country=XX/h3_resolution=N/` |

---

## 7. Running the Notebooks

### Bronze → Silver (SageMaker)

1. Open `osm_bronze_to_silver_sage.ipynb` in SageMaker Studio.
2. Run the first cell to install dependencies (`osmium`, `geopandas`, etc.).
3. Restart the kernel.
4. Set `DRY_RUN = False` to process all bboxes (or `True` for 1 bbox).
5. Run the full notebook.

### Silver → Gold (Glue)

1. Deploy `osm_silver_to_gold.ipynb` as a Glue job (or run in a Glue Spark environment).
2. Run the full cell – no Shapely or kernel restart required.
3. Silver schema is read explicitly (StringType) to avoid BINARY vs INT conflicts in Parquet.

**Requirement:** Silver must have `length_m` and `area_m2` columns (from `osm_bronze_to_silver`). Re-run the bronze→silver pipeline if your Silver was created before these columns were added.
