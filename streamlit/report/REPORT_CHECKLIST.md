# Report Redesign — Before/After Checklist

## Design Goals ✓

- [x] Premium, minimal, consultancy-grade aesthetic
- [x] Strong hierarchy: big titles, clear section headers, consistent spacing
- [x] 12-column grid feel, consistent margins (1.8 cm)
- [x] Clean charts (no default matplotlib blue/orange; white bg, light grid)
- [x] Modern tables: zebra rows, right-aligned numeric columns, fixed widths
- [x] IUCN category badges (colored pills: CR/EN/VU/NT/LC/DD)
- [x] Consistent iconography (simple line icons or none)
- [x] Header and footer on every page

## Typography ✓

- [x] Cover title: 30 pt
- [x] Section H1: 17 pt
- [x] Subhead: 12 pt
- [x] Body: 10 pt
- [x] Table text: 9 pt
- [x] Footer: 8 pt
- [x] Line height 1.25–1.35, spacing tokens (8/12/16)

## Color System ✓

- [x] Dark blue/teal primary (#0d3b4c)
- [x] Neutral grayscale for text/backgrounds
- [x] Amber (#d97706) for warnings/limitations
- [x] Red (#b91c1c) for threatened/invasive
- [x] Max 4 colors in charts; grayscale + one accent

## Report Structure ✓

- [x] A) Cover page — title, KPIs, data sources, timestamp
- [x] B) Table of contents
- [x] C) Executive summary — key findings, KPI cards, recommended next steps
- [x] D) Location & context — map, coordinates, area
- [x] E) Biodiversity overview — top 20 species table
- [x] F) Threatened & invasive — IUCN badges, condensed rationale, disclaimer
- [x] G) Temporal signals — charts from temporal_artifacts
- [x] H) Land cover & infrastructure — horizontal bar chart (not pie), infra table
- [x] I) AI insights — parsed markdown
- [x] J) Limitations & methodology

## Implementation ✓

- [x] ReportLab (not WeasyPrint)
- [x] Theme object (theme.py)
- [x] Reusable components (components.py)
- [x] Chart renderer (charts.py) — styled matplotlib
- [x] Table renderer (tables.py) — zebra, badges, alignment
- [x] Main builder (build_report.py)
- [x] Same inputs as original; drop-in replacement
- [x] Optional confidential watermark

## Usage

```python
from streamlit.report_generator import generate_report

pdf_bytes = generate_report(
    h3_index="8a1f1a2b3c4d5e6f",
    h3_res=7,
    species_df=species_for_hex,
    osm_row=osm_row,
    cell_metrics=cell_metrics,
    name_col="species_name",
    ai_insights=ai_insights,
    temporal_artifacts=temporal_artifacts,
    year=2024,
)
```
