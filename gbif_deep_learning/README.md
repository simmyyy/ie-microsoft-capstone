# Invasive Species Image Classifier – Deep Learning

A multiclass deep learning classifier that identifies invasive plant species from photographs using transfer learning on images sourced from the Global Biodiversity Information Facility (GBIF). The model distinguishes six invasive species (each as a separate class) plus one aggregated non-invasive class, achieving ~81% validation accuracy.

---

## Table of Contents

1. [Business Context: Invasive Species](#1-business-context-invasive-species)
2. [GBIF Introduction](#2-gbif-introduction)
3. [GBIF API: Endpoints and Parameters](#3-gbif-api-endpoints-and-parameters)
4. [The Invasive Species Problem](#4-the-invasive-species-problem)
5. [Data Ingestion and Preprocessing](#5-data-ingestion-and-preprocessing)
6. [Deep Learning Pipeline and Model Architecture](#6-deep-learning-pipeline-and-model-architecture)
7. [Results and Evaluation](#7-results-and-evaluation)
8. [Limitations, Use Cases, and Future Work](#8-limitations-use-cases-and-future-work)
9. [Setup and Usage](#9-setup-and-usage)
10. [Project Structure](#10-project-structure)
11. [Package Dependencies](#11-package-dependencies)
12. [Troubleshooting and FAQ](#12-troubleshooting-and-faq)

---

## 1. Business Context: Invasive Species

### What Are Invasive Species?

Invasive species are non-native organisms that, when introduced to a new environment, spread rapidly and cause harm to native biodiversity, ecosystem services, human health, or the economy. Unlike simply "introduced" or "naturalised" species, invasives actively displace native flora and fauna, alter habitats, and can trigger cascading ecological effects.

### Why Does It Matter?

- **Biodiversity loss**: Invasive plants form monocultures that outcompete native species, reducing local diversity.
- **Economic cost**: Management, eradication, and lost agricultural productivity cost billions annually.
- **Human health**: Some invasives (e.g. *Ambrosia artemisiifolia*) trigger severe allergies.
- **Ecosystem services**: Degraded habitats provide fewer benefits (pollination, water regulation, carbon storage).

### Regional Focus: Spain and Galicia

This project focuses on the **Galicia coast (NW Spain)**. Spain maintains a national catalogue of invasive species; *Cortaderia selloana* (pampas grass) is one of the most problematic. It forms dense stands along roadsides and coastal areas, displacing native vegetation and requiring costly control programmes. Early detection via image-based screening can support monitoring and rapid response.

---

## 2. GBIF Introduction

### What Is GBIF?

The **Global Biodiversity Information Facility (GBIF)** is an international network and data infrastructure funded by governments worldwide. It provides free and open access to biodiversity data—occurrence records, species checklists, and taxonomic information—from museums, herbaria, citizen science platforms (e.g. iNaturalist), and research projects.

- **Website**: [gbif.org](https://www.gbif.org)
- **Mission**: Make biodiversity data accessible for science, policy, and conservation.
- **Scale**: Hundreds of millions of occurrence records, thousands of datasets, global coverage.

### Data Model: Darwin Core

GBIF occurrence records follow the [Darwin Core](https://dwc.tdwg.org/) standard. Key fields we use:

- **scientificName**: Latin name (e.g. "Cortaderia selloana (Schult. & Schult.f.) Asch. & Graebn.").
- **speciesKey / taxonKey**: Numeric ID for the species in GBIF's backbone.
- **decimalLatitude, decimalLongitude**: WGS84 coordinates.
- **establishmentMeans**: How the organism arrived (NATIVE, INTRODUCED, INVASIVE, etc.).
- **degreeOfEstablishment**: Persistence level (ESTABLISHED, INVASIVE, CASUAL, etc.).
- **media**: Array of media objects; each has `type` (e.g. StillImage) and `identifier` (URL).

### Key Concepts for Newcomers

| Term | Meaning |
|------|---------|
| **Occurrence** | A record of a species observed at a specific place and time (with optional coordinates, media, etc.). |
| **Taxon key / speciesKey** | A numeric identifier for a species (or higher taxon) in the GBIF backbone taxonomy. |
| **Darwin Core** | A standard for biodiversity data; GBIF uses Darwin Core terms (e.g. `scientificName`, `decimalLatitude`, `establishmentMeans`). |
| **Media** | Images, sounds, or videos linked to an occurrence. We use `StillImage` media. |
| **basisOfRecord** | How the record was created: `HUMAN_OBSERVATION`, `PRESERVED_SPECIMEN`, `MACHINE_OBSERVATION`, etc. |

### Why GBIF for This Project?

- **Large image corpus**: Millions of plant photos from citizen scientists and researchers.
- **Geographic and taxonomic coverage**: We can filter by bounding box (Galicia) and kingdom (Plantae).
- **Open API**: No authentication required for read operations; well-documented REST API.
- **Establishment metadata**: Some records include `establishmentMeans` and `degreeOfEstablishment`, useful for flagging invasive species.

---

## 3. GBIF API: Endpoints and Parameters

### Base URL and Overview

- **Base URL**: `https://api.gbif.org/v1/`
- **Occurrence Search**: `GET https://api.gbif.org/v1/occurrence/search`
- **Species Match**: `GET https://api.gbif.org/v1/species/match`

The API is RESTful, returns JSON, and supports paging via `limit` and `offset`. Maximum 300 records per page; hard limit of 100,000 records per query. For larger downloads, GBIF recommends the asynchronous download service.

### API Calls Used in This Project

#### 3.1 Occurrence Search (Species in Bounding Box) – Notebook 03

**Purpose**: Fetch all Plantae occurrence records within a geographic bounding box (Galicia coast).

**Endpoint**: `GET https://api.gbif.org/v1/occurrence/search`

**Parameters**:

| Parameter | Value | Description |
|-----------|-------|-------------|
| `geometry` | WKT polygon | Bounding box as `POLYGON((lon lat, ...))` in WGS84. Example: `POLYGON((-8.80 43.15, -8.10 43.15, -8.10 43.58, -8.80 43.58, -8.80 43.15))` |
| `kingdomKey` | 6 | Plantae (kingdom key in GBIF backbone). |
| `hasCoordinate` | true | Only records with geographic coordinates. |
| `year` | 2024 | Optional; filter by observation year. |
| `limit` | 300 | Records per page (max 300). |
| `offset` | 0, 300, 600, ... | Pagination offset. |

**Response**: JSON with `results` (array of occurrence objects), `count`, `endOfRecords`, etc. Each occurrence includes `scientificName`, `speciesKey`, `decimalLatitude`, `decimalLongitude`, `establishmentMeans`, `degreeOfEstablishment`, `media`, and other Darwin Core fields.

#### 3.2 Occurrence Search (Invasive Species Facet) – Notebook 03

**Purpose**: Retrieve species keys for all taxa marked as invasive or introduced in Spain (for cross-referencing with bbox records).

**Endpoint**: `GET https://api.gbif.org/v1/occurrence/search`

**Parameters**:

| Parameter | Value | Description |
|-----------|-------|-------------|
| `country` | ES | Spain. |
| `kingdomKey` | 6 | Plantae. |
| `hasCoordinate` | true | Records with coordinates. |
| `degreeOfEstablishment` | invasive | Or `establishmentMeans` = introduced. |
| `facet` | speciesKey | Request facet counts by species. |
| `facetLimit` | 2000 | Max species in facet. |
| `limit` | 0 | No occurrence records; only facets. |

**Note**: Using `geometry` + `facet` for a small bbox can return empty facets; we therefore use `country=ES` for the invasive list and apply it to bbox records.

#### 3.3 Occurrence Search (Image URLs by Taxon) – Notebook 01 / download_worker

**Purpose**: Collect image URLs for a given species (or list of species) to download training images.

**Endpoint**: `GET https://api.gbif.org/v1/occurrence/search`

**Parameters**:

| Parameter | Value | Description |
|-----------|-------|-------------|
| `taxonKey` | e.g. 2704523 | GBIF species (or genus) key. |
| `mediaType` | StillImage | Only occurrences with images. |
| `basisOfRecord` | HUMAN_OBSERVATION | Field photos; excludes specimens and machine observations for better quality. |
| `occurrenceStatus` | PRESENT | Actual sightings, not absences. |
| `limit` | 300 | Records per page. |
| `offset` | 0, 300, ... | Pagination. |

**Response**: Each occurrence may have a `media` array. We extract `identifier` (image URL) for items with `type` = `StillImage`.

#### 3.4 Species Match – Notebook 01

**Purpose**: Resolve a scientific name to a GBIF `usageKey` (taxon key) when `speciesKey` is missing from the CSV.

**Endpoint**: `GET https://api.gbif.org/v1/species/match`

**Parameters**:

| Parameter | Value | Description |
|-----------|-------|-------------|
| `name` | e.g. "Cortaderia selloana" | Scientific name to match. |

**Response**: JSON with `usageKey`, `speciesKey`, `scientificName`, and match quality metrics.

### Example API Request (cURL)

```bash
# Occurrence search for Cortaderia selloana with images
curl "https://api.gbif.org/v1/occurrence/search?taxonKey=2704523&mediaType=StillImage&basisOfRecord=HUMAN_OBSERVATION&occurrenceStatus=PRESENT&limit=10"
```

### Rate Limits and Best Practices

- GBIF may rate-limit rapid queries (HTTP 429). We use `REQUEST_DELAY` (e.g. 0.25 s) between requests.
- Set `User-Agent` to a URL or email when integrating; GBIF can contact you if needed.
- For bulk downloads (>15 min of paging), prefer the [download API](https://techdocs.gbif.org/en/data-use/api-downloads).

---

## 4. The Invasive Species Problem

### EstablishmentMeans and DegreeOfEstablishment

GBIF uses Darwin Core terms to describe how a species arrived and persists in a location:

- **establishmentMeans**: `NATIVE`, `INTRODUCED`, `INVASIVE`, `NATURALISED`, `UNCERTAIN`, etc.
- **degreeOfEstablishment**: `ESTABLISHED`, `INVASIVE`, `NATURALISED`, `CASUAL`, etc.

Coverage is sparse: many records lack these fields. We therefore combine:

1. **Record-level**: If `degreeOfEstablishment` = invasive or `establishmentMeans` ∈ {INVASIVE, INTRODUCED, NATURALISED}, mark as invasive.
2. **Facet-level**: Species keys from Spain-wide facet for `degreeOfEstablishment=invasive` and `establishmentMeans=introduced`.
3. **Known list**: A curated set (e.g. Cortaderia selloana, Ailanthus altissima) from national catalogues and GRIIS.

### Visually Similar Species: Cortaderia vs Miscanthus

*Cortaderia selloana* (pampas grass) and *Miscanthus sinensis* (Chinese silver grass) are both Poaceae with similar silvery inflorescences. Distinguishing them in the field is difficult for non-experts. This is exactly the kind of problem where a deep learning model adds value—learning subtle visual differences from thousands of labelled images.

*Miscanthus sinensis* is invasive in some regions (e.g. parts of the US) and ornamental elsewhere. In our model it is treated as a separate invasive-like class for training purposes.

---

## 5. Data Ingestion and Preprocessing

### 5.1 Pipeline Overview

```
03_species_in_bbox.ipynb   →  species_for_training.csv
         │
         ▼
01_data_collection.ipynb   →  data/raw/, data/train/, data/val/
         │
         ▼
02_train_classifier.ipynb  →  models/best_model.pth + evaluation
```

### 5.2 Step 1: Species Selection (Notebook 03)

1. **Fetch occurrences** in the Galicia bbox (geometry, kingdomKey=6, hasCoordinate=true, optional year).
2. **Classify each record** as invasive or not via `is_invasive_record()` using `degreeOfEstablishment` and `establishmentMeans`.
3. **Fetch invasive species keys** from Spain-wide facets (`degreeOfEstablishment=invasive`, `establishmentMeans=introduced`).
4. **Aggregate by species** with `aggregate_by_species()`: total count, invasive count, speciesKey, and combined invasive flag (record OR facet OR known list).
5. **Export** `species_for_training.csv` with columns: `scientificName`, `speciesKey`, `total_count`, `invasive_count`, `is_invasive`, `invasive_source`, `has_establishment_data`, `establishment_info`.
6. **Save** `species_for_training.csv` for use by notebook 01.

### 5.3 Step 2: Image Download (Notebook 01)

**Species selection**:

- **Invasive**: Top 5 by `total_count`, excluding cortaderia and miscanthus if already present.
- **Non-invasive**: 5 random species (excluding miscanthus), combined into one `non_invasive` class.

**Download process** (parallel via `ProcessPoolExecutor` and `download_worker.py`):

1. For each species (or taxon key list for non_invasive), call GBIF occurrence search with `taxonKey`, `mediaType=StillImage`, `basisOfRecord=HUMAN_OBSERVATION`, `occurrenceStatus=PRESENT`.
2. Extract image URLs from `media[].identifier` where `type` = `StillImage`.
3. Shuffle URLs to avoid ordering bias.
4. Download each image, run quality checks, save as JPEG if passed.

**Quality filters** (in `download_worker._image_quality_ok`):

| Filter | Threshold | Reason |
|--------|-----------|--------|
| **Minimum size** | min(width, height) ≥ 224 px | Reject thumbnails and icons. |
| **Aspect ratio** | max(w,h)/min(w,h) ≤ 4.0 | Reject extreme panoramas and banners. |
| **Sharpness** | Laplacian variance ≥ 60 | Reject blurry or featureless images. |

**Sharpness (Laplacian variance)**:

- 4-neighbour Laplacian on greyscale: Δ = up + down + left + right − 4×center.
- Variance of the Laplacian indicates edge density; low values indicate blur or uniform regions (sky, out-of-focus).
- Typical ranges: sky &lt; 5, blurry 5–40, acceptable 40–80, sharp plant close-ups 80+.
- Implementation: `np.roll` for neighbour access; no extra dependencies beyond NumPy.

**Rejection reasons** (tracked per download run):

- `too_small`: Minimum dimension below 224 px.
- `bad_aspect`: Aspect ratio exceeds 4.0 (e.g. 1920×200).
- `blurry`: Laplacian variance below 60.
- `not_image`: Content-Type not image, URL not image extension.
- `error:<Exception>`: Download or decode failure.

**Output**: Images saved to `data/raw/<class_name>/` as `00000.jpg`, `00001.jpg`, etc.

**Train/val split**: 80% train, 20% val per class. Images copied to `data/train/<class>/` and `data/val/<class>/`.

### 5.4 Optional: Extra Non-Invasive Download

A cell at the bottom of notebook 01 allows downloading additional non-invasive species (`N_EXTRA_NON_INVASIVE_SPECIES`, `IMAGES_PER_EXTRA_SPECIES`). Images are fetched in parallel, merged into `non_invasive`, and the train/val split should be re-run.

### 5.5 Cleaning Step (Optional)

A "cleaning" cell applies the same quality filters to already-downloaded images and **deletes** those that fail. Use with caution; deleted images are not recoverable.

---

## 6. Deep Learning Pipeline and Model Architecture

### 6.1 Why Transfer Learning?

With ~300 images per class, training a CNN from scratch would overfit. Transfer learning reuses a model pre-trained on ImageNet (1.2M images, 1000 classes) and fine-tunes only the later layers for our plant classification task.

### 6.2 Architecture: EfficientNet-B0

**EfficientNet-B0** is a CNN designed for efficiency (accuracy vs. parameters). It uses compound scaling of depth, width, and resolution.

- **Backbone**: 7 MBConv (mobile inverted bottleneck) stages.
- **Input**: 224×224 RGB.
- **Output**: 1280-dimensional feature vector before the classifier head.

**Our modifications**:

- **Frozen**: `features[0:6]` (early stages)—retain generic edge/texture detectors.
- **Trained**: `features[6:8]` (last stage) + classifier head—adapt to plant morphology.
- **Classifier**: `Dropout(0.4)` + `Linear(1280 → N)`, where N = number of classes (typically 7).

### 6.3 Data Loading

- **FilteredImageFolder** (`dataset_utils.py`): Subclass of `torchvision.datasets.ImageFolder` that excludes specified class folders (e.g. duplicate cortaderia with long scientific name). Required for pickling when `DataLoader` uses `num_workers > 0`.
- **Classes**: Inferred from subdirectory names in `data/train/`.

### 6.4 Augmentation (Training Only)

| Transform | Parameters | Purpose |
|-----------|------------|---------|
| RandomResizedCrop | 224, scale=(0.5, 1.0) | Vary scale and crop. |
| RandomHorizontalFlip | — | Common augmentation. |
| RandomVerticalFlip | p=0.3 | Plants have no canonical orientation. |
| ColorJitter | brightness=0.4, contrast=0.4, saturation=0.3, hue=0.06 | Lighting and camera variation. |
| RandomRotation | ±25° | Slight rotation invariance. |
| ToTensor + Normalize | ImageNet mean/std | Standardisation. |

**Validation**: Resize(256), CenterCrop(224), ToTensor, Normalize—no augmentation.

**ImageNet normalisation**: mean = [0.485, 0.456, 0.406], std = [0.229, 0.224, 0.225].

### 6.5 Training Configuration

| Parameter | Value |
|-----------|-------|
| Optimiser | Adam |
| Learning rate | 1e-4 |
| Weight decay | 1e-4 |
| Scheduler | CosineAnnealingLR |
| Epochs | 15 |
| Batch size | 32 |
| Loss | CrossEntropyLoss |
| Early stopping | Best checkpoint by validation accuracy |

### 6.6 Grad-CAM (Interpretability)

**Gradient-weighted Class Activation Mapping (Grad-CAM)** highlights image regions that most influence the model's prediction. We use the last convolutional layer, weight activations by gradients for the predicted class, and overlay a heatmap. This helps verify that the model focuses on plant structures rather than background.

---

## 7. Results and Evaluation

### 7.1 Example Metrics

| Metric | Value |
|--------|-------|
| Validation accuracy | ~81% |
| Classes | 7 (6 invasive + non_invasive) |
| Best per-class F1 | Oenothera rosea ~0.93 |
| Weakest | non-invasive recall ~0.63 |

### 7.2 Per-Class Performance (Typical)

- **Oenothera rosea**: F1 ~0.93 (easiest).
- **Arctotheca, Tradescantia, Laurus**: F1 ~0.84–0.88.
- **Cortaderia, Miscanthus**: F1 ~0.75–0.76 (visually similar).
- **non_invasive**: Recall ~0.63 (many false alarms).

### 7.3 Output Artifacts

- `models/best_model.pth`: Best checkpoint.
- `models/model_metadata.json`: Architecture, classes, accuracy, normalisation.
- `models/training_curves.png`: Loss and accuracy over epochs.
- `models/confusion_matrix.png`: Per-class confusion.
- `models/gradcam.png`: Grad-CAM examples.
- `models/confidence_distribution.png`: Confidence histograms per class.

---

## 8. Limitations, Use Cases, and Future Work

### Limitations

- Low recall for non-invasive (false alarms).
- Miscanthus vs Cortaderia confusion (similar grasses).
- Data limited to GBIF; possible misidentifications and geographic bias.
- Invasive status is region-dependent (e.g. Miscanthus).

### Use Cases

- **Screening tool** for field staff or citizen scientists.
- **Pre-filter** for expert review.
- **Not** a replacement for expert verification.

### Future Work

- Add a test set (e.g. 70/15/15 split).
- More non-invasive data and class weighting.
- Try other architectures (e.g. Vision Transformers).
- External validation on independent datasets.

---

## 9. Setup and Usage

### Prerequisites

- Python 3.10+
- Jupyter (or compatible environment)

### Installation

```bash
cd gbif_deep_learning
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
jupyter notebook .
```

**Important**: Run notebooks from the `gbif_deep_learning/` directory so `download_worker` and `dataset_utils` import correctly.

### Run Order

1. **03_species_in_bbox.ipynb**: Produces `species_for_training.csv`.
2. **01_data_collection.ipynb**: Downloads images, applies quality filters, creates train/val split.
3. **02_train_classifier.ipynb**: Trains model, evaluates, saves checkpoint and plots.

### Inference

After training, use the `predict_image()` function from notebook 02:

```python
result = predict_image("path/to/photo.jpg")
# result = {
#   "predicted_class": "cortaderia_selloana",
#   "label": "INVASIVE (cortaderia_selloana)",
#   "confidence_pct": 94.3,
#   "probabilities": {...}
# }
```

---

## 10. Project Structure

```
gbif_deep_learning/
├── 03_species_in_bbox.ipynb   # GBIF bbox query → species_for_training.csv
├── 01_data_collection.ipynb   # Download images, quality filter, train/val split
├── 02_train_classifier.ipynb  # Train EfficientNet-B0, evaluate, Grad-CAM
├── download_worker.py         # ProcessPoolExecutor worker for parallel downloads
├── dataset_utils.py           # FilteredImageFolder for DataLoader pickling
├── species_for_training.csv   # Output of 03, input to 01
├── requirements.txt
├── README.md
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

---

## 11. Package Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| torch | ≥2.1.0 | Deep learning framework |
| torchvision | ≥0.16.0 | Models, datasets, transforms |
| Pillow | ≥10.0.0 | Image loading and processing |
| requests | ≥2.31.0 | HTTP requests to GBIF API |
| tqdm | ≥4.66.0 | Progress bars |
| numpy | ≥1.26.0 | Numerical operations, Laplacian sharpness |
| pandas | ≥2.0.0 | CSV handling, species selection |
| scikit-learn | ≥1.4.0 | classification_report, confusion_matrix |
| matplotlib | ≥3.8.0 | Plots |
| seaborn | ≥0.13.0 | Confusion matrix heatmap |
| opencv-python-headless | ≥4.9.0 | Grad-CAM heatmap overlay |

---

## 12. Troubleshooting and FAQ

### Common Issues

**ModuleNotFoundError: No module named 'cv2'**  
Install OpenCV: `pip install opencv-python-headless`

**ModuleNotFoundError: No module named 'download_worker'**  
Run notebooks from the `gbif_deep_learning/` directory (e.g. `jupyter notebook .` from that folder).

**AttributeError: Can't get attribute 'FilteredImageFolder'**  
`FilteredImageFolder` must be in a separate module (`dataset_utils.py`) so it can be pickled when `DataLoader` uses `num_workers > 0`. Ensure `dataset_utils.py` exists and is imported.

**HTTP 429 from GBIF**  
Reduce request rate: increase `REQUEST_DELAY` in the config (e.g. to 0.5 or 1.0 seconds).

### FAQ

**Q: Can I use a different bounding box?**  
Yes. Edit `BBOX` in notebook 03 and regenerate `species_for_training.csv`. Re-run 01 and 02.

**Q: How do I add more species?**  
Modify the species selection logic in notebook 01 (top invasive count, non-invasive sample size) or use the extra non-invasive download cell.

**Q: What if GBIF returns duplicate images for different species?**  
We deduplicate by URL within each species. Cross-species duplicates are possible but rare; they could cause minor label noise.

---

## References

- [GBIF Developer Documentation](https://www.gbif.org/developer/summary)
- [GBIF Occurrence API](https://techdocs.gbif.org/en/openapi/v1/occurrence)
- [EfficientNet Paper](https://arxiv.org/abs/1905.11946)
- [Grad-CAM Paper](https://arxiv.org/abs/1610.02391)
