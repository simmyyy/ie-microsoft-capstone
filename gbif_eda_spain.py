# %%
import pandas as pd

df = pd.read_parquet("gbif_spain_experiment.parquet")
print("Shape:", df.shape)

# %%
# %%
species_counts = df["species"].value_counts()

print("Species with >= 10 observations:",
      (species_counts >= 10).sum())

print("Species with >= 20 observations:",
      (species_counts >= 20).sum())

# %%
# %%
valid_species = species_counts[species_counts >= 20].index
df_filtered = df[df["species"].isin(valid_species)]

print("Filtered shape:", df_filtered.shape)
print("Remaining species:", df_filtered["species"].nunique())

# %%
# %%
centroids = (
    df_filtered
    .groupby(["species", "year"])
    .agg({
        "decimalLatitude": "mean",
        "decimalLongitude": "mean"
    })
    .reset_index()
)

print("Centroids shape:", centroids.shape)
centroids.head()

# %%
# %%
import numpy as np

def yearly_displacement(group):
    group = group.sort_values("year")
    
    group["lat_shift"] = group["decimalLatitude"].diff()
    group["lon_shift"] = group["decimalLongitude"].diff()
    
    group["step_distance"] = np.sqrt(
        group["lat_shift"]**2 +
        group["lon_shift"]**2
    )
    
    return group

centroids_steps = (
    centroids
    .groupby("species")
    .apply(yearly_displacement)
)

centroids_steps["step_distance"].describe()

# %%
