"""
Biodiversity & Infrastructure Report Generator
==============================================
Generates a formatted PDF report for a selected H3 cell, combining:
- Location map (static image)
- Species data (threatened, invasive, IUCN rationale)
- OSM infrastructure metrics (land cover %, counts, pie chart)

Designed to be imported and called from app.py.
"""

from __future__ import annotations

import io
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# MAP IMAGE (OSM tile fallback – works without py-staticmaps)
# ─────────────────────────────────────────────────────────────────────────────


def _latlon_to_tile(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    """Convert lat/lon to OSM tile x, y at given zoom."""
    lat_rad = math.radians(lat)
    n = 2.0**zoom
    xtile = int((lon + 180.0) / 360.0 * n)
    ytile = int(
        (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi)
        / 2.0
        * n
    )
    return (xtile, ytile)


def _render_map_image(h3_index: str, width: int = 500, height: int = 350) -> bytes | None:
    """
    Render a static map image showing the H3 hex location.
    Uses OSM tiles + PIL (no external map lib required). Fetches 2x2 tile grid.
    """
    try:
        import h3
        from PIL import Image
    except ImportError:
        return None

    try:
        import urllib.request
    except ImportError:
        return None

    try:
        lat, lng = h3.cell_to_latlng(h3_index)
        zoom = 12
        tx, ty = _latlon_to_tile(lat, lng, zoom)

        tile_size = 256
        tiles_x, tiles_y = 2, 2
        img_w = tile_size * tiles_x
        img_h = tile_size * tiles_y

        canvas = Image.new("RGB", (img_w, img_h), (240, 240, 240))

        for dx in range(tiles_x):
            for dy in range(tiles_y):
                txx, tyy = tx - 1 + dx, ty - 1 + dy
                url = f"https://tile.openstreetmap.org/{zoom}/{txx}/{tyy}.png"
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "BiodiversityExplorer/1.0"})
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        tile_img = Image.open(io.BytesIO(resp.read())).convert("RGB")
                        canvas.paste(tile_img, (dx * tile_size, dy * tile_size))
                except Exception:
                    pass

        # Draw hex outline (approximate – center marker)
        try:
            from PIL import ImageDraw

            cx, cy = img_w // 2, img_h // 2
            draw = ImageDraw.Draw(canvas)
            r = 20
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline="#2e86ab", width=3)
            draw.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill="#2e86ab")
        except Exception:
            pass

        canvas = canvas.resize((width, height), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        canvas.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# LAND COVER PIE CHART (max 5 top + Others)
# ─────────────────────────────────────────────────────────────────────────────


def _render_land_cover_chart(osm_row: pd.Series, width: int = 400, height: int = 280) -> bytes | None:
    """Create a pie chart of land cover percentages. Max 5 top, rest as Others."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    pct_cols = [
        ("waterbody_area_pct", "Water", "#3498db"),
        ("waterway_area_pct", "Waterways", "#5dade2"),
        ("wetland_area_pct", "Wetlands", "#85c1e9"),
        ("road_area_pct", "Roads", "#7f8c8d"),
        ("building_area_pct", "Buildings", "#95a5a6"),
        ("residential_area_pct", "Residential", "#e74c3c"),
        ("commercial_area_pct", "Commercial", "#c0392b"),
        ("industrial_area_pct", "Industrial", "#bdc3c7"),
        ("parks_green_area_pct", "Parks & green", "#27ae60"),
        ("agri_area_pct", "Agriculture", "#f1c40f"),
        ("managed_forest_area_pct", "Forest", "#2ecc71"),
        ("natural_habitat_area_pct", "Natural habitat", "#1abc9c"),
        ("protected_area_pct", "Protected", "#9b59b6"),
        ("restricted_area_pct", "Restricted", "#8e44ad"),
    ]

    items: list[tuple[str, float, str]] = []
    for col, label, color in pct_cols:
        if col in osm_row.index:
            val = osm_row.get(col)
            if val is not None and pd.notna(val) and float(val) > 0:
                raw = float(val)
                items.append((label, min(raw, 100.0), color))  # cap at 100% (OSM overlap)

    if not items:
        return None

    items.sort(key=lambda x: x[1], reverse=True)
    top5 = items[:5]
    others_sum = sum(x[1] for x in items[5:])

    labels = [x[0] for x in top5]
    sizes = [x[1] for x in top5]
    colors = [x[2] for x in top5]

    if others_sum > 0:
        labels.append("Others")
        sizes.append(others_sum)
        colors.append("#bdc3c7")

    # Normalize so pie sums to 100% (raw values can exceed 100% due to OSM overlap)
    total = sum(sizes)
    if total > 0:
        sizes = [s / total * 100 for s in sizes]

    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    ax.pie(sizes, labels=labels, colors=colors, autopct="%1.1f%%", startangle=90)
    ax.axis("equal")
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="PNG", bbox_inches="tight", dpi=100)
    plt.close()
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# TABLE HELPER
# ─────────────────────────────────────────────────────────────────────────────


def _make_table(
    data: list[list[str]],
    col_widths: list[float],
    header_color: str,
) -> Any:
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import Table, TableStyle

    t = Table(data, colWidths=[w * cm for w in col_widths])
    t.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_color)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ("BACKGROUND", (0, 1), (-1, -1), colors.white),
            ("TEXTCOLOR", (0, 1), (-1, -1), colors.black),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
        ])
    )
    return t


# ─────────────────────────────────────────────────────────────────────────────
# PDF GENERATION
# ─────────────────────────────────────────────────────────────────────────────


SPECIES_RICHNESS_EXPLANATION = """
<b>Species richness indices</b> — biodiversity metrics computed from GBIF occurrence records in this hex.<br/>
<br/>
• <b>Observation count</b> — total number of GBIF occurrence records (individual observations) in the cell<br/>
• <b>Species richness</b> — number of distinct species observed; uses speciesKey → taxonKey → species string<br/>
• <b>Unique datasets</b> — number of distinct GBIF datasets contributing records (data provenance)<br/>
• <b>Shannon H</b> — Shannon-Wiener entropy; measures diversity (species count + evenness). Higher = more diverse and even. Formula: −Σ(p_i × ln p_i) where p_i = proportion of species i<br/>
• <b>Simpson (1−D)</b> — Simpson diversity index; probability that two random individuals are different species. Range 0–1; higher = more diverse<br/>
• <b>Threatened species</b> — count of species with IUCN CR, EN, or VU<br/>
• <b>Threat score (weighted)</b> — sum of IUCN weights per distinct species: CR=5, EN=4, VU=3, NT=2. Higher = more conservation concern<br/>
• <b>Assessed species</b> — count of species with any IUCN Red List assessment<br/>
• <b>Data Quality Index (DQI)</b> — composite 0–1: species-id completeness, coordinate uncertainty quality, IUCN coverage. Higher = better data quality<br/>
• <b>Avg coordinate uncertainty (m)</b> — mean coordinateUncertaintyInMeters of records; lower = more precise locations<br/>
• <b>% uncertainty > 10 km</b> — share of records with coordinate uncertainty exceeding 10 000 m
"""

REPORT_SUMMARY = """
This report summarises biodiversity and infrastructure data for a single H3 hexagonal cell.
<br/><br/>
<b>Data sources</b><br/>
• <b>GBIF</b> – species occurrence records (Global Biodiversity Information Facility)<br/>
• <b>IUCN Red List</b> – threat status and conservation rationale<br/>
• <b>OpenStreetMap</b> – land cover and infrastructure features<br/>
<br/>
<b>APIs</b><br/>
• GBIF Occurrence API (bulk downloads)<br/>
• IUCN Red List API<br/>
• OSM Overpass & tile services<br/>
<br/>
<b>Metrics</b><br/>
• Species richness, occurrence counts, threatened/invasive flags<br/>
• Land cover % (area share per hex)<br/>
• Infrastructure counts (roads, rail, buildings, water features)<br/>
<br/>
<b>References</b> — gbif.org · iucnredlist.org · openstreetmap.org · h3geo.org
"""

IUCN_EXPLANATION = """
<b>IUCN Red List categories</b><br/>
• <b>CR</b> — Critically Endangered: extremely high risk of extinction in the wild<br/>
• <b>EN</b> — Endangered: high risk of extinction<br/>
• <b>VU</b> — Vulnerable: high risk of extinction in the medium term<br/>
• <b>NT</b> — Near Threatened: may become threatened if conditions worsen<br/>
• <b>LC</b> — Least Concern: does not qualify for threatened categories<br/>
• <b>DD</b> — Data Deficient: insufficient data to assess; does not mean the species is safe
"""

LAND_COVER_EXPLANATION = """
<b>Land cover</b> — share of hex area covered by each OSM-mapped land use type.<br/>
• <b>Waterbody</b> — lakes, ponds, reservoirs, pools<br/>
• <b>Waterway</b> — riverbanks, canal banks, stream corridors<br/>
• <b>Wetland</b> — marshes, peatlands, bogs<br/>
• <b>Forest</b> — managed forest (landuse=forest)<br/>
• <b>Natural habitat</b> — woods, heath, scrub, grassland, bare rock, sand, beaches<br/>
• <b>Agriculture</b> — farmland, farmyard, orchard, vineyard, meadow<br/>
• <b>Parks & green</b> — parks, gardens, golf courses, sports pitches<br/>
• <b>Residential / Commercial / Industrial</b> — OSM landuse polygons<br/>
• <b>Protected / Restricted</b> — protected areas, nature reserves; military zones
"""

TRANSPORT_EXPLANATION = """
<b>Counts</b> — number of OSM features (points, lines, polygons) intersecting the hex.<br/>
• <b>Roads</b> — all highway types (motorway, trunk, primary, secondary, tertiary, residential, etc.)<br/>
• <b>Major roads</b> — motorway, trunk, primary, secondary, tertiary only<br/>
• <b>Rail</b> — rail, light_rail, subway, tram segments<br/>
• <b>Fuel stations</b> — amenity=fuel<br/>
• <b>Power plants</b> — all types; solar/wind/hydro are subsets<br/>
• <b>Power lines / substations</b> — power=line, power=substation
"""

WATER_BUILT_EXPLANATION = """
<b>Counts</b> — number of OSM features in the hex.<br/>
• <b>Waterways</b> — rivers, streams, canals, ditches<br/>
• <b>Waterbodies</b> — lakes, ponds, reservoirs<br/>
• <b>Wetlands</b> — marshes, peatlands<br/>
• <b>Dams</b> — man_made=dam or waterway=dam<br/>
• <b>Buildings</b> — building=* (all types)<br/>
• <b>Industrial areas</b> — landuse=industrial polygons<br/>
• <b>Waste sites</b> — landfills, wastewater treatment plants
"""


def generate_report(
    h3_index: str,
    h3_res: int,
    species_df: pd.DataFrame,
    osm_row: pd.Series,
    cell_metrics: pd.Series | None = None,
    name_col: str = "species_name",
) -> bytes:
    """
    Generate a PDF report for the given H3 cell.

    Args:
        h3_index: H3 cell identifier
        h3_res: H3 resolution
        species_df: Species data for this hex (species_name, occurrence_count, is_threatened, is_invasive, rationale)
        osm_row: OSM metrics row for this hex
        cell_metrics: Optional GBIF cell metrics (species_richness_cell, etc.)
        name_col: Column name for species display

    Returns:
        PDF file as bytes
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            BaseDocTemplate,
            Frame,
            Image,
            PageBreak,
            PageTemplate,
            Paragraph,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as e:
        raise RuntimeError(
            "ReportLab is required for PDF generation. Install with: pip install reportlab"
        ) from e

    buf = io.BytesIO()
    page_w, page_h = A4
    margin = 2 * cm
    footer_h = 1.2 * cm
    doc_w = page_w - 2 * margin
    doc_h = page_h - 2 * margin - footer_h

    def _draw_footer(canvas, _doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#1a5276"))
        canvas.rect(0, 0, page_w, footer_h, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica", 9)
        canvas.drawString(margin, 0.35 * cm, "Biodiversity & Infrastructure Assessment · GBIF · IUCN · OpenStreetMap")
        canvas.drawRightString(page_w - margin, 0.35 * cm, f"Page {_doc.page}")
        canvas.restoreState()

    frame = Frame(margin, margin + footer_h, doc_w, doc_h, id="main")
    template = PageTemplate(id="all", frames=[frame], onPage=_draw_footer)
    doc = BaseDocTemplate(buf, pagesize=A4, rightMargin=margin, leftMargin=margin, topMargin=margin, bottomMargin=margin)
    doc.addPageTemplates([template])
    styles = getSampleStyleSheet()
    elements = []

    # Typography: Helvetica for clean professional look; left-aligned body (better readability than justified)
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=28,
        spaceAfter=12,
        textColor=colors.HexColor("#1a5276"),
        alignment=0,  # left
    )
    summary_style = ParagraphStyle(
        "Summary",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        spaceAfter=10,
        leftIndent=0,
        rightIndent=0,
        alignment=0,
    )
    h2_style = ParagraphStyle(
        "CustomH2",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        spaceBefore=16,
        spaceAfter=8,
        textColor=colors.HexColor("#1a5276"),
        alignment=0,
    )
    body_style = ParagraphStyle(
        "CustomBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=12,
        spaceAfter=6,
        alignment=0,
    )
    explanation_style = ParagraphStyle(
        "Explanation",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        spaceAfter=8,
        leftIndent=0,
        alignment=0,
    )
    small_style = ParagraphStyle(
        "Small",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=11,
        spaceAfter=4,
        alignment=0,
    )

    def _divider():
        t = Table([[""]], colWidths=[16 * cm], rowHeights=[0.15 * cm])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#2e86ab"))]))
        return t

    # ── Page 1: Logo + title (full page) ─────────────────────────────────────
    logo_path = Path(__file__).parent / "assessment_logo.png"
    if logo_path.exists():
        elements.append(Image(str(logo_path), width=14 * cm, height=9 * cm))
    elements.append(Spacer(1, 0.8 * cm))
    elements.append(Paragraph("Biodiversity & Infrastructure Assessment", title_style))
    elements.append(Paragraph(REPORT_SUMMARY, summary_style))
    elements.append(Spacer(1, 0.4 * cm))
    elements.append(Paragraph(f"<i>Report generated: {datetime.now().strftime('%d %B %Y, %H:%M')}</i>", small_style))
    elements.append(Spacer(1, 1 * cm))  # small spacer – avoid overflow to blank page 2
    elements.append(PageBreak())

    # ── 1. Location ──────────────────────────────────────────────────────────
    elements.append(Paragraph("1. Location", h2_style))

    map_img = _render_map_image(h3_index)
    if map_img:
        img = Image(io.BytesIO(map_img), width=12 * cm, height=8 * cm)
        elements.append(img)
        elements.append(Spacer(1, 0.3 * cm))

    try:
        import h3
        lat, lng = h3.cell_to_latlng(h3_index)
        loc_text = (
            f"<b>Hex ID:</b> {h3_index}<br/>"
            f"<b>Resolution:</b> {h3_res}<br/>"
            f"<b>Coordinates:</b> {lat:.4f}°N, {lng:.4f}°E"
        )
    except Exception:
        loc_text = f"<b>Hex ID:</b> {h3_index}<br/><b>Resolution:</b> {h3_res}"

    elements.append(Paragraph(loc_text, body_style))
    elements.append(Spacer(1, 0.5 * cm))
    elements.append(_divider())
    elements.append(Spacer(1, 0.5 * cm))

    # ── 2. Species Overview ──────────────────────────────────────────────────
    elements.append(Paragraph("2. Species Overview", h2_style))

    if species_df.empty:
        elements.append(Paragraph("No species data available for this cell.", body_style))
    else:
        n_total = species_df["taxon_key"].nunique()
        n_threatened = (
            species_df.loc[species_df["is_threatened"], "taxon_key"].nunique()
            if "is_threatened" in species_df.columns
            else 0
        )
        n_invasive = (
            species_df.loc[species_df["is_invasive"], "taxon_key"].nunique()
            if "is_invasive" in species_df.columns
            else 0
        )

        summary = f"Total species: {n_total}  |  Threatened: {n_threatened}  |  Invasive: {n_invasive}"
        elements.append(Paragraph(summary, body_style))
        elements.append(Spacer(1, 0.3 * cm))

        agg_df = species_df.groupby("taxon_key", as_index=False).agg(
            {name_col: "first", "occurrence_count": "sum"}
        )
        if "is_threatened" in species_df.columns:
            agg_df = agg_df.merge(
                species_df[["taxon_key", "is_threatened"]].drop_duplicates("taxon_key"),
                on="taxon_key",
                how="left",
            )
        if "is_invasive" in species_df.columns:
            agg_df = agg_df.merge(
                species_df[["taxon_key", "is_invasive"]].drop_duplicates("taxon_key"),
                on="taxon_key",
                how="left",
            )

        # Table 1: Top 30 by occurrence count
        elements.append(Paragraph("<b>Top 30 species by occurrence count</b>", body_style))
        elements.append(Paragraph("<i>Occurrences = number of GBIF records for this species in the hex.</i>", small_style))
        top30 = agg_df.nlargest(30, "occurrence_count")
        top_data = [["Species", "Occurrences", "Threatened", "Invasive"]]
        for _, row in top30.iterrows():
            name = str(row.get(name_col, "?"))[:45]
            occ = int(row.get("occurrence_count", 0))
            thr = "Yes" if row.get("is_threatened") else "—"
            inv = "Yes" if row.get("is_invasive") else "—"
            top_data.append([name, str(occ), thr, inv])
        elements.append(_make_table(top_data, [8, 2.5, 2, 2], "#2e86ab"))
        elements.append(Spacer(1, 0.5 * cm))

        # Table 3: All threatened species
        if "is_threatened" in agg_df.columns:
            threatened_df = agg_df[agg_df["is_threatened"]].copy()
            if not threatened_df.empty:
                if "iucn_category" not in threatened_df.columns and "iucn_category" in species_df.columns:
                    iucn_merge = species_df[["taxon_key", "iucn_category"]].drop_duplicates("taxon_key")
                    threatened_df = threatened_df.merge(iucn_merge, on="taxon_key", how="left")
                elements.append(Paragraph("<b>All threatened species</b>", body_style))
                elements.append(Paragraph("<i>Species with IUCN category VU, EN, or CR.</i>", small_style))
                thr_data = [["Species", "Occurrences", "IUCN", "Invasive"]]
                for _, row in threatened_df.iterrows():
                    name = str(row.get(name_col, "?"))[:45]
                    occ = int(row.get("occurrence_count", 0))
                    iucn = str(row.get("iucn_category", "—")) if "iucn_category" in row.index and pd.notna(row.get("iucn_category")) else "—"
                    inv = "Yes" if row.get("is_invasive") else "—"
                    thr_data.append([name, str(occ), iucn, inv])
                elements.append(_make_table(thr_data, [8, 2.5, 2, 2], "#c0392b"))
                elements.append(Spacer(1, 0.5 * cm))

        # Table 4: All invasive species
        if "is_invasive" in agg_df.columns:
            invasive_df = agg_df[agg_df["is_invasive"]]
            if not invasive_df.empty:
                elements.append(Paragraph("<b>All invasive species</b>", body_style))
                elements.append(Paragraph("<i>Species flagged as invasive or introduced (establishmentMeans, degreeOfEstablishment).</i>", small_style))
                inv_data = [["Species", "Occurrences", "Threatened"]]
                for _, row in invasive_df.iterrows():
                    name = str(row.get(name_col, "?"))[:45]
                    occ = int(row.get("occurrence_count", 0))
                    thr = "Yes" if row.get("is_threatened") else "—"
                    inv_data.append([name, str(occ), thr])
                elements.append(_make_table(inv_data, [8, 2.5, 2], "#e67e22"))
                elements.append(Spacer(1, 0.5 * cm))

    elements.append(Spacer(1, 0.5 * cm))

    # ── 3. Threatened species dossier ────────────────────────────────────────
    if not species_df.empty and "is_threatened" in species_df.columns:
        threatened = species_df[species_df["is_threatened"]].drop_duplicates("taxon_key")
        if not threatened.empty:
            elements.append(Paragraph("3. Threatened Species – IUCN Rationale", h2_style))
            elements.append(Paragraph(IUCN_EXPLANATION, explanation_style))
            elements.append(Spacer(1, 0.3 * cm))
            for _, row in threatened.iterrows():
                name = row.get(name_col, row.get("taxon_key", "?"))
                rationale = row.get("rationale")
                iucn = row.get("iucn_category", "")
                elements.append(Paragraph(f"<b>{name}</b> {f'({iucn})' if iucn else ''}", body_style))
                if rationale and pd.notna(rationale):
                    txt = str(rationale)[:800] + ("…" if len(str(rationale)) > 800 else "")
                    elements.append(Paragraph(txt.replace("\n", "<br/>"), body_style))
                elements.append(Spacer(1, 0.2 * cm))
            elements.append(Spacer(1, 0.5 * cm))
    elements.append(_divider())
    elements.append(Spacer(1, 0.5 * cm))

    # ── 4. Species richness indices ────────────────────────────────────────────
    CELL_METRICS_DISPLAY = [
        ("observation_count", "Observation count", "int"),
        ("species_richness_cell", "Species richness", "int"),
        ("unique_datasets", "Unique datasets", "int"),
        ("shannon_H", "Shannon H", "float2"),
        ("simpson_1_minus_D", "Simpson (1−D)", "float2"),
        ("n_threatened_species", "Threatened species", "int"),
        ("threat_score_weighted", "Threat score (weighted)", "int"),
        ("n_assessed_species", "Assessed species", "int"),
        ("dqi", "Data Quality Index", "float2"),
        ("avg_coordinate_uncertainty_m", "Avg coord. uncertainty (m)", "float0"),
        ("pct_uncertainty_gt_10km", "% uncertainty > 10 km", "pct"),
    ]
    if cell_metrics is not None and not cell_metrics.empty:
        elements.append(Paragraph("4. Species richness indices", h2_style))
        elements.append(Paragraph(SPECIES_RICHNESS_EXPLANATION, explanation_style))
        elements.append(Spacer(1, 0.3 * cm))
        metrics_data = [["Metric", "Value"]]
        for col, label, fmt in CELL_METRICS_DISPLAY:
            if col in cell_metrics.index:
                val = cell_metrics.get(col)
                if val is not None and pd.notna(val):
                    if fmt == "int":
                        metrics_data.append([label, f"{int(val):,}"])
                    elif fmt == "float2":
                        metrics_data.append([label, f"{float(val):.2f}"])
                    elif fmt == "float0":
                        metrics_data.append([label, f"{float(val):.0f}"])
                    elif fmt == "pct":
                        metrics_data.append([label, f"{float(val) * 100:.1f}%"])
                    else:
                        metrics_data.append([label, str(val)])
        if len(metrics_data) > 1:
            elements.append(_make_table(metrics_data, [8, 4], "#2e86ab"))
        elements.append(Spacer(1, 0.5 * cm))
        elements.append(_divider())
        elements.append(Spacer(1, 0.5 * cm))

    # ── 5. OSM Infrastructure ───────────────────────────────────────────────────
    elements.append(Paragraph("5. OSM Infrastructure", h2_style))

    chart_img = _render_land_cover_chart(osm_row)
    if chart_img:
        elements.append(Paragraph(LAND_COVER_EXPLANATION, explanation_style))
        elements.append(Spacer(1, 0.2 * cm))
        img = Image(io.BytesIO(chart_img), width=12 * cm, height=8 * cm)
        elements.append(img)
        elements.append(Spacer(1, 0.3 * cm))

    # Land cover % table (sorted by % descending)
    pct_metrics = [
        ("waterbody_area_pct", "Waterbody"),
        ("waterway_area_pct", "Waterway"),
        ("wetland_area_pct", "Wetland"),
        ("road_area_pct", "Road"),
        ("building_area_pct", "Building"),
        ("residential_area_pct", "Residential"),
        ("commercial_area_pct", "Commercial"),
        ("industrial_area_pct", "Industrial"),
        ("parks_green_area_pct", "Parks & green"),
        ("parking_area_pct", "Parking"),
        ("cemetery_area_pct", "Cemetery"),
        ("construction_area_pct", "Construction"),
        ("retention_basin_area_pct", "Retention basin"),
        ("agri_area_pct", "Agriculture"),
        ("managed_forest_area_pct", "Forest"),
        ("natural_habitat_area_pct", "Natural habitat"),
        ("protected_area_pct", "Protected"),
        ("restricted_area_pct", "Restricted"),
    ]

    pct_items: list[tuple[str, float]] = []
    for col, label in pct_metrics:
        if col in osm_row.index:
            val = osm_row.get(col)
            if val is not None and pd.notna(val) and float(val) > 0:
                raw = float(val)
                # Cap at 100% for display – OSM polygons overlap (e.g. residential contains buildings)
                pct_items.append((label, min(raw, 100.0)))

    pct_items.sort(key=lambda x: x[1], reverse=True)
    pct_data = [["Land cover", "%"]]
    for label, val in pct_items:
        pct_data.append([label, f"{val:.1f}%"])

    if len(pct_data) > 1:
        elements.append(Paragraph("<b>Land cover (% of hex area)</b>", body_style))
        elements.append(Paragraph(
            "<i>Share of hex area covered by each OSM land use type. "
            "Values capped at 100% for display; raw OSM polygons often overlap (e.g. building inside residential), "
            "so uncapped sums can exceed 100%. Human footprint and urban footprint are composite metrics "
            "and are shown separately below.</i>",
            small_style,
        ))
        elements.append(_make_table(pct_data, [6, 3], "#95a5a6"))
        # Composite metrics (not additive with table above)
        human_pct = osm_row.get("human_footprint_area_pct")
        urban_pct = osm_row.get("urban_footprint_area_pct")
        if (human_pct is not None and pd.notna(human_pct)) or (urban_pct is not None and pd.notna(urban_pct)):
            comp_parts = []
            if human_pct is not None and pd.notna(human_pct):
                comp_parts.append(f"Human footprint: {float(human_pct):.1f}%")
            if urban_pct is not None and pd.notna(urban_pct):
                comp_parts.append(f"Urban footprint: {float(urban_pct):.1f}%")
            elements.append(Paragraph(
                f"<i>Composite (do not add to table): {' | '.join(comp_parts)}</i>",
                small_style,
            ))
        elements.append(Spacer(1, 0.5 * cm))

    # Transport & energy table
    transport_metrics = [
        ("road_count", "Roads"),
        ("major_road_count", "Major roads"),
        ("rail_count", "Rail segments"),
        ("fuel_station_count", "Fuel stations"),
        ("power_plant_count", "Power plants"),
        ("solar_plant_count", "Solar plants"),
        ("wind_plant_count", "Wind plants"),
        ("hydro_plant_count", "Hydro plants"),
        ("power_line_count", "Power lines"),
        ("power_substation_count", "Substations"),
    ]

    transport_data = [["Metric", "Value"]]
    for col, label in transport_metrics:
        if col in osm_row.index:
            val = osm_row.get(col)
            if val is not None and pd.notna(val):
                transport_data.append([label, f"{int(val):,}"])

    if len(transport_data) > 1:
        elements.append(Paragraph("<b>Transport & energy</b>", body_style))
        elements.append(Paragraph(TRANSPORT_EXPLANATION, explanation_style))
        elements.append(_make_table(transport_data, [6, 4], "#27ae60"))
        elements.append(Spacer(1, 0.5 * cm))

    # Water & built table
    water_built_metrics = [
        ("waterway_count", "Waterways"),
        ("waterbody_count", "Waterbodies"),
        ("wetland_count", "Wetlands"),
        ("dam_count", "Dams"),
        ("building_count", "Buildings"),
        ("industrial_area_count", "Industrial areas"),
        ("waste_site_count", "Waste sites"),
    ]

    water_data = [["Metric", "Value"]]
    for col, label in water_built_metrics:
        if col in osm_row.index:
            val = osm_row.get(col)
            if val is not None and pd.notna(val):
                water_data.append([label, f"{int(val):,}"])

    if len(water_data) > 1:
        elements.append(Paragraph("<b>Water & built</b>", body_style))
        elements.append(Paragraph(WATER_BUILT_EXPLANATION, explanation_style))
        elements.append(_make_table(water_data, [6, 4], "#3498db"))

    elements.append(Spacer(1, 1 * cm))

    doc.build(elements)
    return buf.getvalue()
