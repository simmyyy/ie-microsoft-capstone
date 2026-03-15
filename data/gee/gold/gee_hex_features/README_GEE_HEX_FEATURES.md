# GEE Hex Features (Gold)

**Granularity:** 1 row per (country, year, h3_resolution, h3_index)  
**Join keys:** h3_index + h3_resolution + country (+ year when joining time-specific tables)

## Current build
- country: ES
- year: 2024
- h3_resolution: 6
- Source: Google Earth Engine (Sentinel-2 SR Harmonized NDVI, ESA WorldCover v200, SRTM elevation/slope)

## Columns
- country: ISO-2 ("ES")
- year: int (e.g., 2024)
- h3_resolution: int (6)
- h3_index: H3 cell id string
- snapshot_date: date of extraction run (YYYY-MM-DD)
- period_start / period_end: time window used for NDVI aggregation
- ndvi_mean: mean NDVI over the hex (Sentinel-2)
- elevation_mean: mean elevation (SRTM, meters)
- slope_mean: mean slope (degrees)
- landcover_mode: dominant ESA WorldCover class (mode)

## Notes
- NDVI may contain nulls where imagery is fully masked (clouds or no valid pixels in the time window).
- landcover_mode is a categorical code from ESA WorldCover v200.
