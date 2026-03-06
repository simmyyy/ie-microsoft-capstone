# GBIF Species Predictor

Multi-label deep learning model that predicts which threatened and invasive species are likely present in an H3 hex in Spain.

## Overview

- **Input:** H3 hex (resolution 7) represented by a feature vector (OSM, effort, optional terrain)
- **Output:** Top-N species with probabilities: `[{"species_id": ..., "name": ..., "p": 0.99, "flags": ["threatened"]}, ...]`

## Data Sources

- **gbif_species_h3_mapping** – hex–species occurrence mapping (S3 or Parquet)
- **osm_hex_features** – OSM-derived hex features (road_count, protected_area_pct, etc.)
- **gbif_cell_metrics** – observation counts, DQI (effort/confidence)
- **gbif_species_dim** – species names

## Usage

1. Configure `species_predictor.ipynb` (country, h3_res, year window, thresholds)
2. Run all cells to load data, train, evaluate, and save the model
3. Use `predict_species_for_hex(h3_id, features_row, top_n=10)` for inference

## Design Notes

### Spatial block split
Nearby H3 hexes share similar conditions. Splitting by **parent H3 block** (coarser resolution) avoids leakage and gives realistic generalization estimates.

### GBIF presence-only / sampling bias
GBIF records where species were observed, not where they are absent. Hexes with no records may be under-sampled. The model learns "where we tend to see species X" rather than true absence.

### Effort threshold
Restricting evaluation to hexes with `obs_count_all >= 200` focuses on well-sampled areas where labels are more reliable.

## Outputs

- `output/species_predictor.pt` – model checkpoint
- `output/target_species.csv` – target species mapping
- `output/scaler.pkl` – feature scaler for inference

## Gold layer (batch inference)

Run `03_batch_inference_to_gold.ipynb` to predict species for all res-7 hexes and write to S3:

**Path:** `s3://ie-datalake/gold/species_predictions/country=ES/snapshot=YYYY-MM-DD/h3_resolution=7/`

**Schema:** h3_index, species_id, species_name, probability, rank, is_threatened, is_invasive

## Species showcase (before/after maps)

Run `04_species_showcase_map.ipynb` to visualize the best-performing species:

- **Blue:** Observed (GBIF ground truth)
- **Green:** Correct predictions (TP)
- **Red:** False positives (predicted, not observed)
- **Orange:** Missed (FN – observed, not predicted)

**Requires:** Run `species_predictor.ipynb` first (model + scaler in `output/`). 04 loads data from S3 via `data_loader`.

Outputs: `output/species_showcase_<species_id>.png`
