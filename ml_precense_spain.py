"""
ML Model A (v2): Next-year presence classifier (Spain, GBIF)

Goal:
Predict presence of a single species in a spatial grid cell for year t+1
using features from year t (and lag t-1).

Key improvements vs v1:
- Coarser grid (GRID_DEG = 1.0) to reduce extreme imbalance
- Grid built ONLY over cells observed at least once (any year), not the full bbox mesh
"""

import os
import numpy as np
import pandas as pd

from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    roc_auc_score,
    balanced_accuracy_score
)

# ----------------------------
# Parameters
# ----------------------------
DATA_FILE = "gbif_spain_experiment.parquet"

GRID_DEG = 1.0          # grid resolution in degrees (1.0 ~ 111 km latitude)
MIN_OBS_SPECIES = 30    # choose a species with >= this many occurrences
TEST_YEARS = 3          # hold out last N feature-years for testing (time split)
RANDOM_STATE = 42


def pick_species(df: pd.DataFrame, min_obs: int) -> str:
    counts = df["species"].value_counts()
    candidates = counts[counts >= min_obs]
    if candidates.empty:
        raise ValueError(
            f"No species found with >= {min_obs} observations. "
            "Lower MIN_OBS_SPECIES or download more data."
        )
    # pick the most frequent among candidates
    return candidates.index[0]


def build_presence_grid(df_sp: pd.DataFrame, grid_deg: float) -> pd.DataFrame:
    df_sp = df_sp.copy()

    # cell indexes
    df_sp["cell_lat"] = np.floor(df_sp["decimalLatitude"] / grid_deg).astype(int)
    df_sp["cell_lon"] = np.floor(df_sp["decimalLongitude"] / grid_deg).astype(int)

    # presence table (species-specific): 1 if any observation in that cell-year
    presence = (
        df_sp.groupby(["year", "cell_lat", "cell_lon"])
        .size()
        .reset_index(name="n_obs")
    )
    presence["presence"] = 1

    min_year = int(presence["year"].min())
    max_year = int(presence["year"].max())
    years = np.arange(min_year, max_year + 1)

    # IMPORTANT: build grid only over cells observed at least once (any year)
    cells = presence[["cell_lat", "cell_lon"]].drop_duplicates()

    grid = (
        cells.assign(_k=1)
        .merge(pd.DataFrame({"year": years, "_k": 1}), on="_k")
        .drop(columns=["_k"])
    )
    grid = grid[["year", "cell_lat", "cell_lon"]]

    # merge presence onto grid
    grid = grid.merge(
        presence[["year", "cell_lat", "cell_lon", "presence"]],
        on=["year", "cell_lat", "cell_lon"],
        how="left"
    )
    grid["presence"] = grid["presence"].fillna(0).astype(int)

    # cell center coordinates as features
    grid["lat_center"] = (grid["cell_lat"] + 0.5) * grid_deg
    grid["lon_center"] = (grid["cell_lon"] + 0.5) * grid_deg

    # sort for time lag operations
    grid = grid.sort_values(["cell_lat", "cell_lon", "year"]).reset_index(drop=True)

    # lag feature: presence at t-1 for same cell
    grid["presence_lag1"] = (
        grid.groupby(["cell_lat", "cell_lon"])["presence"]
        .shift(1)
        .fillna(0)
        .astype(int)
    )

    # target: presence at t+1 for same cell
    grid["target_presence_next_year"] = (
        grid.groupby(["cell_lat", "cell_lon"])["presence"]
        .shift(-1)
    )

    # drop last year (no label)
    grid = grid.dropna(subset=["target_presence_next_year"]).copy()
    grid["target_presence_next_year"] = grid["target_presence_next_year"].astype(int)

    return grid


def time_split(grid_ml: pd.DataFrame, test_years: int):
    # grid_ml['year'] is feature-year t; label refers to t+1
    max_feat_year = int(grid_ml["year"].max())
    cutoff = max_feat_year - test_years + 1

    train = grid_ml[grid_ml["year"] < cutoff].copy()
    test = grid_ml[grid_ml["year"] >= cutoff].copy()
    return train, test


def safe_roc_auc(y_true, y_score):
    # ROC AUC requires both classes in y_true
    if pd.Series(y_true).nunique() < 2:
        return None
    return roc_auc_score(y_true, y_score)


def evaluate_model(name: str, model, X_train, y_train, X_test, y_test):
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)

    auc = None
    if hasattr(model, "predict_proba"):
        y_proba = model.predict_proba(X_test)[:, 1]
        auc = safe_roc_auc(y_test, y_proba)

    bal_acc = balanced_accuracy_score(y_test, y_pred)

    print("\n" + "=" * 70)
    print(f"Model: {name}")
    print(f"Balanced Accuracy: {bal_acc:.4f}")
    if auc is not None:
        print(f"ROC AUC: {auc:.4f}")
    else:
        print("ROC AUC: not available (only one class in y_test)")

    print("\nConfusion matrix [ [TN FP], [FN TP] ]:")
    print(confusion_matrix(y_test, y_pred))

    print("\nClassification report:")
    print(classification_report(y_test, y_pred, digits=4))


def main():
    # robust path (same folder as script)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(base_dir, DATA_FILE)

    if not os.path.exists(data_path):
        raise FileNotFoundError(
            f"Could not find {DATA_FILE} in: {base_dir}\n"
            "Make sure gbif_spain_experiment.parquet is in the same folder as this script."
        )

    df = pd.read_parquet(data_path)

    # sanitation
    df = df.dropna(subset=["species", "year", "decimalLatitude", "decimalLongitude"]).copy()
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df = df.dropna(subset=["year"]).copy()
    df["year"] = df["year"].astype(int)

    # pick species
    species_name = pick_species(df, MIN_OBS_SPECIES)
    print("Chosen species:", species_name)

    df_sp = df[df["species"] == species_name].copy()
    print("Occurrences for chosen species:", len(df_sp))
    print("Year range:", int(df_sp["year"].min()), "-", int(df_sp["year"].max()))

    # build ML table
    grid_ml = build_presence_grid(df_sp, GRID_DEG)
    print("ML grid rows:", len(grid_ml))
    print("Positive rate (target=1):", grid_ml["target_presence_next_year"].mean())

    feature_cols = ["year", "lat_center", "lon_center", "presence", "presence_lag1"]
    train, test = time_split(grid_ml, TEST_YEARS)

    X_train = train[feature_cols]
    y_train = train["target_presence_next_year"]
    X_test = test[feature_cols]
    y_test = test["target_presence_next_year"]

    print("\nTrain years:", int(train["year"].min()), "-", int(train["year"].max()))
    print("Test years:", int(test["year"].min()), "-", int(test["year"].max()))
    print("Train size:", len(train), "Test size:", len(test))
    print("Test positives:", int(y_test.sum()), "out of", len(y_test))

    # models
    lr = LogisticRegression(
        max_iter=2000,
        class_weight="balanced",
        random_state=RANDOM_STATE
    )

    rf = RandomForestClassifier(
        n_estimators=500,
        random_state=RANDOM_STATE,
        class_weight="balanced",
        n_jobs=-1
    )

    evaluate_model("LogisticRegression (baseline)", lr, X_train, y_train, X_test, y_test)
    evaluate_model("RandomForest (baseline)", rf, X_train, y_train, X_test, y_test)


if __name__ == "__main__":
    main()