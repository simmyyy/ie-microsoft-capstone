# Invasive Species Classifier – Deep Learning

Multiclass image classifier that identifies **invasive plant species** from photos using transfer learning on GBIF occurrence images. The model distinguishes 6 invasive species (each as a separate class) plus one **non-invasive** class.

## Pipeline Overview

```
03_species_in_bbox.ipynb   →  species_for_training.csv
         │
         ▼
01_data_collection.ipynb   →  data/raw/, data/train/, data/val/
         │
         ▼
02_train_classifier.ipynb  →  models/best_model.pth + evaluation
```

## Run Order

### Step 1 – Species selection (03_species_in_bbox.ipynb)

- Queries GBIF occurrence API for Plantae in a bounding box (Galicia coast, NW Spain)
- Aggregates species by occurrence count, flags invasive status via `establishmentMeans` / GBIF facets / known catalogue
- **Output**: `species_for_training.csv` – species list with `scientificName`, `speciesKey`, `total_count`, `is_invasive`

### Step 2 – Image download (01_data_collection.ipynb)

- Reads `species_for_training.csv`
- Selects **top 5 invasive** (by `total_count`), excluding cortaderia & miscanthus if already present
- Samples **5 random non-invasive** species (one combined `non_invasive` class)
- Downloads images via GBIF API in **parallel** (ProcessPoolExecutor)
- **Quality filters**: min 224px, aspect ≤4, Laplacian sharpness ≥60
- **Output**: `data/raw/<class>/`, then 80/20 split to `data/train/` and `data/val/`

**Config**: `TARGET_PER_CLASS=300`, `VAL_RATIO=0.2`

### Step 3 – Train classifier (02_train_classifier.ipynb)

- Loads images with `FilteredImageFolder` (excludes duplicate cortaderia folder)
- **Augmentation**: RandomResizedCrop, flips, ColorJitter, rotation
- **Model**: EfficientNet-B0 (ImageNet), frozen features[0–5], trained features[6–8] + classifier head
- **Training**: Adam, CosineAnnealingLR, 15 epochs, CrossEntropyLoss
- **Evaluation**: classification report, confusion matrix, Grad-CAM, confidence distribution

**Output**: `models/best_model.pth`, `model_metadata.json`, training curves, confusion matrix, Grad-CAM heatmaps

## Project Structure

```
gbif_deep_learning/
├── 03_species_in_bbox.ipynb   # GBIF bbox query → species_for_training.csv
├── 01_data_collection.ipynb   # Download images (parallel), quality filter, train/val split
├── 02_train_classifier.ipynb  # Train EfficientNet-B0 multiclass classifier
├── download_worker.py         # ProcessPoolExecutor worker for parallel downloads
├── dataset_utils.py           # FilteredImageFolder (excludes duplicate classes)
├── species_for_training.csv   # Output of 03, input to 01
├── requirements.txt
├── data/
│   ├── raw/                   # Raw downloads per class
│   ├── train/                 # 80% per class
│   └── val/                   # 20% per class
└── models/
    ├── best_model.pth
    ├── model_metadata.json
    ├── training_curves.png
    ├── confusion_matrix.png
    ├── gradcam.png
    └── confidence_distribution.png
```

## Model Architecture

```
EfficientNet-B0 (ImageNet weights)
  ├── features[0-5]  ← frozen
  ├── features[6-8]  ← trained
  └── classifier
        Dropout(0.4)
        Linear(1280 → N)   # N = number of classes (6 invasive + 1 non-invasive)
```

## Results (example run)

| Metric | Value |
|--------|-------|
| **Validation accuracy** | 81% |
| **Classes** | 7 (6 invasive + non_invasive) |
| **Best per-class F1** | Oenothera rosea 0.93 |
| **Weakest** | non-invasive recall 0.63 (false alarms) |

**Classes**: arctotheca_calendula, cortaderia_selloana, laurus_nobilis, miscanthus_sinensis, oenothera_rosea, tradescantia_fluminensis, non_invasive

## Setup

```bash
cd gbif_deep_learning
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
jupyter notebook .
```

**Note**: Run notebooks from `gbif_deep_learning/` so `download_worker` and `dataset_utils` import correctly.

## Inference

```python
from pathlib import Path
# After running 02_train_classifier, use predict_image():
result = predict_image("path/to/photo.jpg")
# result = {
#   "predicted_class": "cortaderia_selloana",
#   "label": "INVASIVE (cortaderia_selloana)",
#   "confidence_pct": 94.3,
#   "probabilities": {...}
# }
```

## Key Operations (code summary)

| Notebook | Main operations |
|----------|------------------|
| **03** | GBIF occurrence search (geometry, kingdomKey=6) → aggregate by species → flag invasive (establishmentMeans, facet, KNOWN_INVASIVE_SPECIES) → save CSV |
| **01** | Read CSV → select top 5 invasive + 5 non-invasive → `ProcessPoolExecutor` + `download_species_worker` → collect URLs (GBIF API) → download + quality check (size, aspect, sharpness) → train/val split |
| **02** | `FilteredImageFolder` (exclude duplicate cortaderia) → augment → EfficientNet-B0 + custom head → train 15 epochs → classification_report, confusion_matrix, Grad-CAM |

## Data Source

Images from [GBIF Occurrence Search API](https://www.gbif.org/developer/occurrence) with `mediaType=StillImage`, `basisOfRecord=HUMAN_OBSERVATION`. Quality filters remove thumbnails, blurry images, and extreme panoramas.
