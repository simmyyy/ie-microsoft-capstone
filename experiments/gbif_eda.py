import pandas as pd

df = pd.read_parquet("gbif_brazil_experiment.parquet")

print("Shape:", df.shape)
print("\nYears distribution:")
print(df["year"].value_counts().sort_index())

print("\nUnique species:", df["species"].nunique())

print("\nMissing values %:")
print(df.isna().mean())

species_counts = df["species"].value_counts()

print("Species with >= 10 observations:",
      (species_counts >= 10).sum())

print("Species with >= 20 observations:",
      (species_counts >= 20).sum())


# %%
import pandas as pd

df = pd.read_parquet("gbif_brazil_experiment.parquet")
print("Dataset loaded:", df.shape)

# %%

#%%

species_counts = df["species"].value_counts()

print("Species with >= 10 observations:",
      (species_counts >= 10).sum())

print("Species with >= 20 observations:",
      (species_counts >= 20).sum())

# %%
species_counts = df["species"].value_counts()

valid_species = species_counts[species_counts >= 20].index

df_filtered = df[df["species"].isin(valid_species)]

print("Filtered shape:", df_filtered.shape)
print("Remaining species:", df_filtered["species"].nunique())


# %%
# %% calcular centroides por especie y año
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

# %%  calcular desplazamiento total por especie (euclidean distances, not geodesic)
import numpy as np

def total_displacement(group):
    first = group.sort_values("year").iloc[0]
    last = group.sort_values("year").iloc[-1]
    
    return np.sqrt(
        (last["decimalLatitude"] - first["decimalLatitude"])**2 +
        (last["decimalLongitude"] - first["decimalLongitude"])**2
    )

movement = (
    centroids
    .groupby("species")
    .apply(total_displacement)
    .reset_index(name="total_displacement")
)

movement.sort_values("total_displacement", ascending=False).head()


# %% gradual migration? calculation YoY

# %%
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


# %%# %%
import pandas as pd

df = pd.read_parquet("gbif_brazil_experiment.parquet")
print("Dataset loaded:", df.shape)

# %%
# %%
species_counts = df["species"].value_counts()
valid_species = species_counts[species_counts >= 20].index
df_filtered = df[df["species"].isin(valid_species)]

print("Filtered shape:", df_filtered.shape)

# %%

# %% calcular la variabilidad espacial (desviación estándar) por especie y año
spread = (
    df_filtered
    .groupby(["species", "year"])
    .agg({
        "decimalLatitude": "std",
        "decimalLongitude": "std"
    })
    .reset_index()
)

spread.describe()

# %%

# %%
