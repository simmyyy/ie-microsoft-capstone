"""Shared data loading for species predictor. Load from S3, build features, split."""
from __future__ import annotations

import logging
import random
import re
from pathlib import Path

import h3
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.fs as pafs
log = logging.getLogger(__name__)


def load_all(
    fs_read,
    config: dict,
) -> dict:
    """
    Load data from S3, build features, split. Returns dict with X, Y, hex_test, X_test, Y_test,
    target_species_ids, species_names, FEATURE_COLS, h3_col, df_feat, scaler.
    """
    COUNTRY = config["COUNTRY"]
    H3_RES = config["H3_RES"]
    PARENT_RES = config["PARENT_RES"]
    S3_BUCKET = config["S3_BUCKET"]
    GOLD_H3_MAPPING = config["GOLD_H3_MAPPING"]
    GOLD_OSM_HEX = config["GOLD_OSM_HEX"]
    GOLD_CELL_METRICS = config["GOLD_CELL_METRICS"]
    GOLD_NATURE2000 = config["GOLD_NATURE2000"]
    GOLD_GEE_TERRAIN = config["GOLD_GEE_TERRAIN"]
    GOLD_SPECIES_DIM = config["GOLD_SPECIES_DIM"]
    GEE_TERRAIN_SNAPSHOT = config["GEE_TERRAIN_SNAPSHOT"]
    NATURE2000_SNAPSHOT_DATE = config["NATURE2000_SNAPSHOT_DATE"]
    TARGET_YEAR = config.get("TARGET_YEAR", 2024)
    FEATURE_YEARS = config.get("FEATURE_YEARS", (2019, 2023))
    PRESENCE_THRESHOLD = config.get("PRESENCE_THRESHOLD", 2)
    N_THREATENED = config.get("N_THREATENED", 20)
    TRAIN_FRAC = config.get("TRAIN_FRAC", 0.70)
    VAL_FRAC = config.get("VAL_FRAC", 0.15)
    TARGET_SPECIES_PATH = config.get("TARGET_SPECIES_PATH")
    target_species_ids_override = config.get("target_species_ids")

    def _read(path: str) -> pd.DataFrame:
        tbl = ds.dataset(path, filesystem=fs_read, format="parquet").scanner().to_table()
        return tbl.to_pandas()

    years = list(range(2015, 2025))
    log.info("Loading data...")
    parts = []
    for year in years:
        try:
            p = _read(f"{S3_BUCKET}/{GOLD_H3_MAPPING}/country={COUNTRY}/year={year}/h3_resolution={H3_RES}")
            parts.append(p)
        except Exception as e:
            log.warning("Skip year %s: %s", year, e)
    df_h3 = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    df_osm = _read(f"{S3_BUCKET}/{GOLD_OSM_HEX}/country={COUNTRY}/h3_resolution={H3_RES}")
    parts = []
    for year in years:
        try:
            p = _read(f"{S3_BUCKET}/{GOLD_CELL_METRICS}/country={COUNTRY}/year={year}/h3_resolution={H3_RES}")
            p["year"] = year
            parts.append(p)
        except Exception:
            pass
    df_cell = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    try:
        df_nature2000 = _read(f"{S3_BUCKET}/{GOLD_NATURE2000}/country={COUNTRY}/h3_resolution={H3_RES}/snapshot_date={NATURE2000_SNAPSHOT_DATE}")
    except Exception:
        df_nature2000 = pd.DataFrame()
    try:
        df_gee_terrain = _read(f"{S3_BUCKET}/{GOLD_GEE_TERRAIN}/country={COUNTRY}/snapshot={GEE_TERRAIN_SNAPSHOT}/h3_resolution={H3_RES}")
    except Exception:
        df_gee_terrain = pd.DataFrame()
    try:
        df_species = _read(f"{S3_BUCKET}/{GOLD_SPECIES_DIM}/country={COUNTRY}/year={2024}")
    except Exception:
        df_species = pd.DataFrame()

    h3_col = "h3_index" if "h3_index" in df_h3.columns else "h3_id"
    species_id_col = "taxon_key" if "taxon_key" in df_h3.columns else "species_id"
    for d in [df_osm, df_cell, df_nature2000, df_gee_terrain]:
        if not d.empty and "h3_id" in d.columns and "h3_index" not in d.columns:
            d.rename(columns={"h3_id": "h3_index"}, inplace=True)

    df_h3 = df_h3[df_h3["country"].astype(str) == COUNTRY]
    df_h3 = df_h3[df_h3["h3_resolution"] == H3_RES]
    if "year_month" in df_h3.columns and "year" not in df_h3.columns:
        df_h3["year"] = df_h3["year_month"].str[:4].astype(int)
    df_h3["year"] = pd.to_numeric(df_h3["year"], errors="coerce").astype("Int64")

    occ = df_h3.groupby(species_id_col).agg({"occurrence_count": "sum", "is_threatened": "max", "is_invasive": "max"}).reset_index()
    if "iucn_category" in df_h3.columns:
        iucn = df_h3.groupby(species_id_col)["iucn_category"].first().reset_index()
        occ = occ.merge(iucn, on=species_id_col, how="left")
    else:
        occ["iucn_category"] = None

    def _threatened(r):
        if pd.notna(r.get("is_threatened")) and r["is_threatened"]:
            return True
        return str(r.get("iucn_category", "")).upper() in ("CR", "EN", "VU")
    occ["_t"] = occ.apply(_threatened, axis=1)
    threatened = occ[occ["_t"]].nlargest(N_THREATENED, "occurrence_count")[species_id_col].tolist()
    if target_species_ids_override is not None:
        target_species_ids = [int(s) for s in target_species_ids_override]
    else:
        target_species_ids = threatened
    species_names = {}
    if not df_species.empty and "species_name" in df_species.columns:
        id_col = "taxon_key" if "taxon_key" in df_species.columns else "species_id"
        species_names = dict(zip(df_species[id_col], df_species["species_name"]))

    df_t = df_h3[(df_h3["year"] == TARGET_YEAR) & (df_h3[species_id_col].isin(target_species_ids)) & (df_h3["occurrence_count"] >= PRESENCE_THRESHOLD)]
    df_f = df_h3[(df_h3["year"].between(FEATURE_YEARS[0], FEATURE_YEARS[1])) & (df_h3[species_id_col].isin(target_species_ids)) & (df_h3["occurrence_count"] >= PRESENCE_THRESHOLD)]

    presence_t = df_t.groupby([h3_col, species_id_col]).size().reset_index(name="_c")
    hexes = np.unique(np.concatenate([df_f[h3_col].unique(), df_t[h3_col].unique()]))
    species_to_idx = {s: i for i, s in enumerate(target_species_ids)}
    hex_to_row = {h: i for i, h in enumerate(hexes)}
    Y = np.zeros((len(hexes), len(target_species_ids)), dtype=np.float32)
    for _, row in presence_t.iterrows():
        if row[h3_col] in hex_to_row:
            Y[hex_to_row[row[h3_col]], species_to_idx[row[species_id_col]]] = 1.0

    presence_f = df_f.groupby([h3_col, species_id_col]).size().reset_index(name="_c")
    Y_last5 = np.zeros((len(hexes), len(target_species_ids)), dtype=np.float32)
    for _, row in presence_f.iterrows():
        if row[h3_col] in hex_to_row:
            Y_last5[hex_to_row[row[h3_col]], species_to_idx[row[species_id_col]]] = 1.0

    df_hexes = pd.DataFrame({h3_col: hexes})
    right = "h3_index" if "h3_index" in df_osm.columns else "h3_id"
    df_feat = df_hexes.merge(df_osm, left_on=h3_col, right_on=right, how="left")
    if right != h3_col and right in df_feat.columns:
        df_feat = df_feat.drop(columns=[right])
    df_feat = df_feat.rename(columns={"h3_index" if "h3_index" in df_feat.columns else "h3_id": h3_col})

    if not df_nature2000.empty:
        nc = "h3_index" if "h3_index" in df_nature2000.columns else "h3_id"
        n2k = df_nature2000[[nc, "is_protected_area", "nearest_protected_distance"]].rename(columns={nc: h3_col})
        n2k["is_protected_area"] = (n2k["is_protected_area"].astype(str).str.lower() == "yes").astype(np.float32)
        n2k["nearest_protected_distance"] = pd.to_numeric(n2k["nearest_protected_distance"], errors="coerce").fillna(-1).astype(np.float32)
        df_feat = df_feat.merge(n2k, on=h3_col, how="left")

    if not df_gee_terrain.empty:
        gc = "h3_index" if "h3_index" in df_gee_terrain.columns else "h3_id"
        gcols = [c for c in df_gee_terrain.columns if c not in (gc, "h3_resolution")]
        df_feat = df_feat.merge(df_gee_terrain[[gc] + gcols].rename(columns={gc: h3_col}), on=h3_col, how="left")

    df_ce = df_cell[df_cell["year"].between(FEATURE_YEARS[0], FEATURE_YEARS[1])] if "year" in df_cell.columns and not df_cell.empty else df_cell
    if not df_ce.empty:
        oc = "observation_count" if "observation_count" in df_ce.columns else "obs_count_all"
        cc = "h3_index" if "h3_index" in df_ce.columns else "h3_id"
        agg = df_ce.groupby(cc).agg({oc: "sum", **({"dqi": "mean"} if "dqi" in df_ce.columns else {})}).reset_index().rename(columns={cc: h3_col})
        if oc in agg.columns:
            agg["log_obs_count"] = np.log1p(agg[oc].fillna(0))
        df_feat = df_feat.merge(agg, on=h3_col, how="left")

    if "log_obs_count" in df_feat.columns:
        om = dict(zip(df_feat[h3_col], df_feat["log_obs_count"].fillna(0)))
        def _nmean(h):
            try:
                nbs = [n for n in h3.grid_disk(h, 1) if n != h]
                return np.mean([om.get(n, 0) for n in nbs]) if nbs else 0.0
            except:
                return 0.0
        df_feat["neighbor_log_obs_mean"] = df_feat[h3_col].map(_nmean)

    def _slug(n, sid, pre):
        b = re.sub(r"[^a-z0-9]+", "_", str(n).lower())[:30].strip("_")
        return f"{pre}_{b}" if b else f"{pre}_{sid}"
    def _mcols(pre):
        cols, seen = [], set()
        for sid in target_species_ids:
            n = species_names.get(sid, str(sid))
            c = _slug(n, sid, pre)
            if c in seen or c in df_feat.columns:
                c = f"{pre}_{sid}"
            seen.add(c)
            cols.append(c)
        return cols
    for pre in ("in_hex_last5y", "in_k1_last5y", "in_k2_last5y"):
        icols = _mcols(pre)
        vals = np.zeros((len(df_feat), len(target_species_ids)), dtype=np.float32)
        for i in range(len(df_feat)):
            h = df_feat.iloc[i][h3_col]
            if h not in hex_to_row:
                continue
            r = hex_to_row[h]
            if pre == "in_hex_last5y":
                vals[i] = Y_last5[r]
            else:
                k1 = set(h3.grid_disk(h, 1)) - {h}
                k2 = set(h3.grid_disk(h, 2)) - k1 - {h}
                s = k1 if "k1" in pre else k2
                for n in s:
                    if n in hex_to_row:
                        vals[i] = np.maximum(vals[i], Y_last5[hex_to_row[n]])
        for j, c in enumerate(icols):
            df_feat[c] = vals[:, j].astype(np.float32)

    OSM_C = ["road_count", "major_road_count", "road_count_per_km2", "port_feature_count", "airport_feature_count", "urban_footprint_area_pct", "building_area_pct", "protected_area_pct", "building_count", "waterbody_area_pct", "wetland_area_pct", "human_footprint_area_pct", "natural_habitat_area_pct", "dist_to_coast_m", "dist_to_major_road_m"]
    osm_a = [c for c in OSM_C if c in df_feat.columns]
    n2k_a = [c for c in ["is_protected_area", "nearest_protected_distance"] if c in df_feat.columns]
    terr = ["elevation_mean", "slope_mean"] + [c for c in df_feat.columns if c.startswith("lc_") and c.endswith("_pct")]
    terr_a = [c for c in terr if c in df_feat.columns]
    extra = ["log_obs_count", "dqi", "neighbor_log_obs_mean"] if "log_obs_count" in df_feat.columns else []
    hist = [c for c in df_feat.columns if c.startswith(("in_hex_last5y_", "in_k1_last5y_", "in_k2_last5y_"))]
    FEATURE_COLS = osm_a + n2k_a + extra + hist + terr_a
    FEATURE_COLS = [c for c in FEATURE_COLS if c in df_feat.columns]
    if not FEATURE_COLS:
        df_feat["_const"] = 1.0
        FEATURE_COLS = ["_const"]

    X_raw = df_feat[FEATURE_COLS].fillna(0).replace([np.inf, -np.inf], 0)
    X_raw = np.clip(X_raw.values.astype(np.float64), -1e15, 1e15).astype(np.float32)

    def _block(h):
        try:
            return h3.cell_to_parent(h, PARENT_RES)
        except:
            return str(hash(h) % 10000)
    df_feat["block_id"] = df_feat[h3_col].map(_block)
    blocks = df_feat["block_id"].unique()
    random.seed(42)
    np.random.seed(42)
    random.shuffle(blocks)
    n = len(blocks)
    t_end = int(n * TRAIN_FRAC)
    v_end = int(n * (TRAIN_FRAC + VAL_FRAC))
    train_b, val_b, test_b = set(blocks[:t_end]), set(blocks[t_end:v_end]), set(blocks[v_end:])
    test_mask = df_feat["block_id"].isin(test_b).values
    X_raw_test = X_raw[test_mask]
    Y_test = Y[test_mask]
    hex_test = df_feat.loc[test_mask, h3_col].values

    return {
        "X_raw": X_raw, "Y": Y, "hex_test": hex_test, "X_raw_test": X_raw_test, "Y_test": Y_test,
        "target_species_ids": target_species_ids, "species_names": species_names,
        "FEATURE_COLS": FEATURE_COLS, "h3_col": h3_col, "df_feat": df_feat,
        "test_mask": test_mask,
    }
