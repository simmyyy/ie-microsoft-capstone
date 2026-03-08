"""
Biodiversity & Infrastructure Assessment — Premium PDF builder.
=============================================================
Drop-in replacement for report_generator.generate_report.
Same inputs, consultancy-grade output.
"""

from __future__ import annotations

import io
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from . import charts, components, tables
from .theme import DEFAULT_THEME, Theme


# ─────────────────────────────────────────────────────────────────────────────
# MAP IMAGE (reuse from report_generator)
# ─────────────────────────────────────────────────────────────────────────────


def _latlon_to_tile(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    lat_rad = math.radians(lat)
    n = 2.0**zoom
    xtile = int((lon + 180.0) / 360.0 * n)
    ytile = int(
        (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi)
        / 2.0 * n
    )
    return (xtile, ytile)


def _render_map_image(h3_index: str, width: int = 550, height: int = 380) -> bytes | None:
    try:
        import h3
        from PIL import Image, ImageDraw
        import urllib.request
    except ImportError:
        return None
    try:
        lat, lng = h3.cell_to_latlng(h3_index)
        zoom = 12
        tx, ty = _latlon_to_tile(lat, lng, zoom)
        tile_size = 256
        tiles_x, tiles_y = 2, 2
        img_w, img_h = tile_size * tiles_x, tile_size * tiles_y
        canvas = Image.new("RGB", (img_w, img_h), (248, 248, 248))
        for dx in range(tiles_x):
            for dy in range(tiles_y):
                txx, tyy = tx - 1 + dx, ty - 1 + dy
                url = f"https://tile.openstreetmap.org/{zoom}/{txx}/{tyy}.png"
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "BiodiversityReport/1.0"})
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        tile_img = Image.open(io.BytesIO(resp.read())).convert("RGB")
                        canvas.paste(tile_img, (dx * tile_size, dy * tile_size))
                except Exception:
                    pass
        cx, cy = img_w // 2, img_h // 2
        draw = ImageDraw.Draw(canvas)
        r = 24
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline="#0d3b4c", width=4)
        draw.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill="#0d3b4c")
        canvas = canvas.resize((width, height), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        canvas.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# AI INSIGHTS PARSER
# ─────────────────────────────────────────────────────────────────────────────


def _escape_html(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"{{B}}\1{{/B}}", text)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text.replace("{{B}}", "<b>").replace("{{/B}}", "</b>")


def _parse_ai_insights(text: str, elements: list, styles: dict, make_table_fn) -> None:
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, Spacer

    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("###"):
            title = re.sub(r"^#+\s*", "", stripped).strip()
            elements.append(Paragraph(_escape_html(title), styles["section_h1"]))
            elements.append(Spacer(1, 0.2 * cm))
            i += 1
            continue
        if stripped.startswith("|") and "|" in stripped[1:]:
            table_rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                row = lines[i].strip()
                cells = [c.strip() for c in row.split("|")[1:-1]]
                if cells and not all(re.match(r"^[-:]+$", c) for c in cells):
                    table_rows.append(cells)
                i += 1
            if table_rows:
                col_count = len(table_rows[0])
                col_widths = [16.0 / col_count] * col_count
                elements.append(make_table_fn(table_rows, col_widths, "#0d3b4c"))
                elements.append(Spacer(1, 0.3 * cm))
            continue
        if stripped.startswith("- ") or stripped.startswith("• ") or (len(stripped) >= 2 and stripped[0].isdigit() and stripped[1] == "."):
            content = re.sub(r"^[-•]\s+", "", stripped)
            content = re.sub(r"^\d+\.\s+", "", content)
            elements.append(Paragraph(f"• {_escape_html(content)}", styles["body"]))
            i += 1
            continue
        if not stripped:
            i += 1
            continue
        para_lines = [stripped]
        i += 1
        while i < len(lines):
            next_line = lines[i].strip()
            if not next_line or next_line.startswith("|") or next_line.startswith("###") or next_line.startswith("- ") or next_line.startswith("• "):
                break
            if len(next_line) >= 2 and next_line[0].isdigit() and next_line[1] == ".":
                break
            para_lines.append(next_line)
            i += 1
        para_text = " ".join(para_lines).replace("\n", " ")
        if para_text:
            elements.append(Paragraph(_escape_html(para_text), styles["body"]))
            elements.append(Spacer(1, 0.15 * cm))


# ─────────────────────────────────────────────────────────────────────────────
# MAIN BUILDER
# ─────────────────────────────────────────────────────────────────────────────


def build_report(
    h3_index: str,
    h3_res: int,
    species_df: pd.DataFrame,
    osm_row: pd.Series,
    cell_metrics: pd.Series | None = None,
    name_col: str = "species_name",
    ai_insights: str | None = None,
    temporal_artifacts: dict | None = None,
    year: int | None = None,
    confidential: bool = False,
) -> bytes:
    """
    Generate premium PDF report. Same signature as generate_report.
    """
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
        Table as RlTable,
    )

    theme = DEFAULT_THEME
    buf = io.BytesIO()
    page_w, page_h = A4
    margin = 1.8 * cm
    footer_h = 1.0 * cm
    doc_w = page_w - 2 * margin
    doc_h = page_h - 2 * margin - footer_h

    year_range = str(year) if year else "N/A"

    def _draw_page(canvas, doc):
        components.draw_header_footer(canvas, doc, theme, h3_index, year_range)
        if confidential:
            canvas.saveState()
            canvas.setFillColor(colors.HexColor("#e5e7eb"))
            canvas.setFont(theme.font, 40)
            canvas.rotate(45)
            canvas.drawCentredString(page_w / 2, page_h / 2, "Confidential — Draft")
            canvas.restoreState()

    frame = Frame(margin, margin + footer_h, doc_w, doc_h, id="main")
    template = PageTemplate(id="all", frames=[frame], onPage=_draw_page)
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=margin,
        leftMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
    )
    doc.addPageTemplates([template])

    styles = getSampleStyleSheet()
    c = theme.to_reportlab_colors()
    custom_styles = {
        "cover_title": ParagraphStyle(
            "CoverTitle", parent=styles["Heading1"],
            fontName=theme.font_bold, fontSize=theme.cover_title,
            leading=int(theme.cover_title * 1.25), spaceAfter=theme.sm,
            textColor=c["primary"], alignment=1,
        ),
        "cover_subtitle": ParagraphStyle(
            "CoverSubtitle", parent=styles["Normal"],
            fontName=theme.font, fontSize=theme.subhead,
            leading=int(theme.subhead * 1.3), spaceAfter=theme.lg,
            textColor=c["gray_500"], alignment=1,
        ),
        "section_h1": ParagraphStyle(
            "SectionH1", parent=styles["Heading2"],
            fontName=theme.font_bold, fontSize=theme.section_h1,
            leading=int(theme.section_h1 * 1.25), spaceBefore=theme.lg, spaceAfter=theme.sm,
            textColor=c["primary"], alignment=0,
        ),
        "body": ParagraphStyle(
            "Body", parent=styles["Normal"],
            fontName=theme.font, fontSize=theme.body,
            leading=int(theme.body * 1.3), spaceAfter=theme.sm, alignment=0,
        ),
        "caption": ParagraphStyle(
            "Caption", parent=styles["Normal"],
            fontName=theme.font, fontSize=theme.footer,
            leading=int(theme.footer * 1.25), spaceAfter=theme.xs,
            textColor=c["gray_500"], alignment=0,
        ),
    }

    elements = []

    def _mt(data, widths, hdr, numeric=None):
        return tables.make_table(data, widths, hdr, theme, numeric_cols=numeric or set(), align_right_cols=numeric or set())

    # ── A) COVER PAGE ────────────────────────────────────────────────────────
    elements.append(Paragraph("Biodiversity & Infrastructure", custom_styles["cover_title"]))
    elements.append(Paragraph("Screening Report", custom_styles["cover_subtitle"]))

    try:
        import h3
        lat, lng = h3.cell_to_latlng(h3_index)
        loc_line = f"H3 cell {h3_index} · Resolution {h3_res} · {lat:.4f}°N, {lng:.4f}°E"
    except Exception:
        loc_line = f"H3 cell {h3_index} · Resolution {h3_res}"
    elements.append(Paragraph(loc_line, custom_styles["body"]))
    elements.append(Spacer(1, 0.3 * cm))

    n_total = species_df["taxon_key"].nunique() if not species_df.empty else 0
    n_threatened = (
        species_df.loc[species_df["is_threatened"], "taxon_key"].nunique()
        if not species_df.empty and "is_threatened" in species_df.columns else 0
    )
    n_invasive = (
        species_df.loc[species_df["is_invasive"], "taxon_key"].nunique()
        if not species_df.empty and "is_invasive" in species_df.columns else 0
    )
    dqi_val = f"{cell_metrics['dqi']:.2f}" if cell_metrics is not None and "dqi" in cell_metrics.index and pd.notna(cell_metrics.get("dqi")) else "—"

    kpi_row = [
        components.kpi_card("Species richness", str(n_total), theme),
        components.kpi_card("Threatened", str(n_threatened), theme),
        components.kpi_card("Invasive", str(n_invasive), theme),
        components.kpi_card("DQI", dqi_val, theme),
    ]
    kpi_table = RlTable([kpi_row], colWidths=[4 * cm, 4 * cm, 4 * cm, 4 * cm])
    kpi_table.setStyle([("VALIGN", (0, 0), (-1, -1), "TOP")])
    elements.append(kpi_table)
    elements.append(Spacer(1, 0.5 * cm))
    elements.append(Paragraph(
        f"<i>Data: GBIF · IUCN Red List · OpenStreetMap</i>",
        custom_styles["caption"],
    ))
    elements.append(Paragraph(
        f"<i>Generated: {datetime.now().strftime('%d %B %Y, %H:%M')} · v1.0</i>",
        custom_styles["caption"],
    ))
    elements.append(PageBreak())

    # ── B) TABLE OF CONTENTS ─────────────────────────────────────────────────
    elements.append(Paragraph("Table of Contents", custom_styles["section_h1"]))
    toc_items = [
        "1. Executive Summary",
        "2. Location & Context",
        "3. Biodiversity Overview",
        "4. Threatened & Invasive Species",
        "5. Temporal Signals",
        "6. Land Cover & Infrastructure",
        "7. AI Insights",
        "8. Limitations & Methodology",
    ]
    for item in toc_items:
        elements.append(Paragraph(item, custom_styles["body"]))
    elements.append(PageBreak())

    # ── C) EXECUTIVE SUMMARY ──────────────────────────────────────────────────
    elements.append(Paragraph("1. Executive Summary", custom_styles["section_h1"]))

    key_findings = [
        f"Species richness: {n_total} distinct species in this cell.",
        f"Threatened species: {n_threatened} with IUCN CR/EN/VU status.",
        f"Invasive species: {n_invasive} flagged as invasive or introduced.",
        f"Data Quality Index: {dqi_val} (0–1 scale).",
    ]
    if cell_metrics is not None and "avg_coordinate_uncertainty_m" in cell_metrics.index:
        unc = cell_metrics.get("avg_coordinate_uncertainty_m")
        if pd.notna(unc):
            key_findings.append(f"Mean coordinate uncertainty: {float(unc):,.0f} m.")
    key_findings.append("Recommend field verification for high-stakes decisions.")

    for kf in key_findings[:6]:
        elements.append(Paragraph(f"• {kf}", custom_styles["body"]))

    elements.append(Spacer(1, 0.3 * cm))
    hfp = osm_row.get("human_footprint_area_pct")
    hfp_str = f"{float(hfp):.1f}%" if pd.notna(hfp) and hfp is not None else "—"
    kpi_cards = [
        components.kpi_card("Biodiversity", str(n_total), theme),
        components.kpi_card("Threatened", str(n_threatened), theme),
        components.kpi_card("Human footprint", hfp_str, theme, accent=False),
    ]
    elements.append(RlTable([kpi_cards], colWidths=[5 * cm, 5 * cm, 5 * cm]))
    elements.append(Spacer(1, 0.3 * cm))
    elements.append(components.callout_box(
        "Recommended next steps",
        [
            "Review threatened species list and IUCN rationale.",
            "Assess temporal trends for observation pressure and invasive expansion.",
            "Conduct field verification for high-value or sensitive areas.",
        ],
        theme,
        "info",
    ))
    elements.append(PageBreak())

    # ── D) LOCATION & CONTEXT ────────────────────────────────────────────────
    elements.append(Paragraph("2. Location & Context", custom_styles["section_h1"]))

    map_img = _render_map_image(h3_index)
    if map_img:
        elements.append(Image(io.BytesIO(map_img), width=14 * cm, height=9 * cm))
        elements.append(Spacer(1, 0.3 * cm))

    try:
        import h3
        lat, lng = h3.cell_to_latlng(h3_index)
        area_km2 = 0
        try:
            area_km2 = h3.cell_area(h3_index, unit="km^2")
        except Exception:
            pass
        loc_text = (
            f"<b>Coordinates:</b> {lat:.4f}°N, {lng:.4f}°E<br/>"
            f"<b>Area:</b> ~{area_km2:.1f} km²"
        )
    except Exception:
        loc_text = f"<b>Hex ID:</b> {h3_index}"
    elements.append(Paragraph(loc_text, custom_styles["body"]))
    elements.append(components.divider(theme))
    elements.append(components.spacer(0.5))

    # ── E) BIODIVERSITY OVERVIEW ─────────────────────────────────────────────
    elements.append(Paragraph("3. Biodiversity Overview", custom_styles["section_h1"]))

    if species_df.empty:
        elements.append(Paragraph("No species data available for this cell.", custom_styles["body"]))
    else:
        agg_df = species_df.groupby("taxon_key", as_index=False).agg(
            {name_col: "first", "occurrence_count": "sum"}
        )
        if "is_threatened" in species_df.columns:
            agg_df = agg_df.merge(
                species_df[["taxon_key", "is_threatened"]].drop_duplicates("taxon_key"),
                on="taxon_key", how="left",
            )
        if "is_invasive" in species_df.columns:
            agg_df = agg_df.merge(
                species_df[["taxon_key", "is_invasive"]].drop_duplicates("taxon_key"),
                on="taxon_key", how="left",
            )

        top20 = agg_df.nlargest(20, "occurrence_count")
        top_data = [["Species", "Occurrences", "Threatened", "Invasive"]]
        for _, row in top20.iterrows():
            name = str(row.get(name_col, "?"))[:45]
            occ = int(row.get("occurrence_count", 0))
            thr = "Yes" if row.get("is_threatened") else "—"
            inv = "Yes" if row.get("is_invasive") else "—"
            top_data.append([name, occ, thr, inv])
        elements.append(Paragraph("<b>Top 20 species by occurrence count</b>", custom_styles["body"]))
        elements.append(_mt(top_data, [8, 2.5, 2, 2], theme.primary_light, {1}))
        elements.append(components.spacer(0.5))

    # ── F) THREATENED & INVASIVE ──────────────────────────────────────────────
    elements.append(Paragraph("4. Threatened & Invasive Species", custom_styles["section_h1"]))

    if not species_df.empty and "is_threatened" in species_df.columns:
        threatened = species_df[species_df["is_threatened"]].drop_duplicates("taxon_key")
        if not threatened.empty:
            thr_data = [["Species", "Occurrences", "IUCN", "Invasive"]]
            for _, row in threatened.iterrows():
                name = str(row.get(name_col, "?"))[:45]
                occ = int(row.get("occurrence_count", 0))
                iucn = str(row.get("iucn_category", "—")) if pd.notna(row.get("iucn_category")) else "—"
                inv = "Yes" if row.get("is_invasive") else "—"
                thr_data.append([name, occ, iucn, inv])
            elements.append(Paragraph("<b>Threatened species (IUCN CR/EN/VU)</b>", custom_styles["body"]))
            elements.append(tables.make_iucn_table(thr_data, [8, 2.5, 2, 2], 2, theme))
            elements.append(components.spacer(0.3))

            # IUCN rationale — condensed 2-column feel (left: name+badge, right: rationale)
            elements.append(Paragraph("<b>IUCN rationale (condensed)</b>", custom_styles["body"]))
            elements.append(Paragraph(
                "<i>Disclaimer: IUCN text may be truncated for readability.</i>",
                custom_styles["caption"],
            ))
            for _, row in threatened.head(10).iterrows():
                name = row.get(name_col, "?")
                iucn = row.get("iucn_category", "")
                rationale = row.get("rationale")
                if rationale and pd.notna(rationale):
                    txt = str(rationale)[:400].replace("\n", " ") + ("…" if len(str(rationale)) > 400 else "")
                else:
                    txt = "No rationale available."
                elements.append(Paragraph(
                    f"<b>{name}</b> ({iucn}) — {txt}",
                    custom_styles["body"],
                ))
                elements.append(Spacer(1, 0.15 * cm))

    if not species_df.empty and "is_invasive" in species_df.columns:
        invasive = species_df[species_df["is_invasive"]].drop_duplicates("taxon_key")
        if not invasive.empty:
            elements.append(Paragraph("<b>Invasive species</b>", custom_styles["body"]))
            inv_data = [["Species", "Occurrences", "Threatened"]]
            for _, row in invasive.iterrows():
                name = str(row.get(name_col, "?"))[:45]
                occ = int(row.get("occurrence_count", 0))
                thr = "Yes" if row.get("is_threatened") else "—"
                inv_data.append([name, occ, thr])
            elements.append(_mt(inv_data, [8, 2.5, 2], "#d97706", {1}))

    elements.append(PageBreak())

    # ── G) TEMPORAL SIGNALS ───────────────────────────────────────────────────
    elements.append(Paragraph("5. Temporal Signals", custom_styles["section_h1"]))

    if temporal_artifacts and temporal_artifacts.get("charts"):
        for title, chart_bytes in temporal_artifacts.get("charts", []):
            elements.append(Paragraph(f"<b>{title}</b>", custom_styles["body"]))
            elements.append(Image(io.BytesIO(chart_bytes), width=14 * cm, height=7 * cm))
            elements.append(Spacer(1, 0.3 * cm))
        for table_title, table_rows in temporal_artifacts.get("tables", []):
            if table_rows:
                elements.append(Paragraph(f"<b>{table_title}</b>", custom_styles["body"]))
                col_count = len(table_rows[0])
                col_widths = [16.0 / col_count] * col_count
                elements.append(_mt(table_rows, col_widths, theme.primary_light, {1, 2} if col_count > 2 else {1}))
                elements.append(Spacer(1, 0.3 * cm))
        if temporal_artifacts.get("narrative_text"):
            for line in temporal_artifacts["narrative_text"].split("\n"):
                if line.strip():
                    elements.append(Paragraph(_escape_html(line.strip()), custom_styles["body"]))
        if temporal_artifacts.get("limitations"):
            elements.append(components.callout_box("Limitations", [temporal_artifacts["limitations"]], theme, "warning"))
    else:
        elements.append(Paragraph("No temporal data available for this cell.", custom_styles["body"]))

    elements.append(PageBreak())

    # ── H) LAND COVER & INFRASTRUCTURE ────────────────────────────────────────
    elements.append(Paragraph("6. Land Cover & Infrastructure", custom_styles["section_h1"]))

    land_cover_chart = charts.render_land_cover_bar(osm_row)
    if land_cover_chart:
        elements.append(Image(io.BytesIO(land_cover_chart), width=14 * cm, height=8 * cm))
        elements.append(Spacer(1, 0.3 * cm))

    pct_metrics = [
        ("waterbody_area_pct", "Waterbody"), ("waterway_area_pct", "Waterway"),
        ("wetland_area_pct", "Wetland"), ("road_area_pct", "Roads"),
        ("building_area_pct", "Buildings"), ("residential_area_pct", "Residential"),
        ("agri_area_pct", "Agriculture"), ("natural_habitat_area_pct", "Natural habitat"),
        ("protected_area_pct", "Protected"),
    ]
    pct_items = [(l, min(float(osm_row.get(c, 0) or 0), 100)) for c, l in pct_metrics if c in osm_row.index and pd.notna(osm_row.get(c)) and float(osm_row.get(c, 0) or 0) > 0]
    pct_items.sort(key=lambda x: x[1], reverse=True)
    if pct_items:
        pct_data = [["Land cover", "%"]] + [[l, f"{v:.1f}%"] for l, v in pct_items]
        elements.append(_mt(pct_data, [10, 3], theme.gray_500, {1}))

    human_pct = osm_row.get("human_footprint_area_pct")
    urban_pct = osm_row.get("urban_footprint_area_pct")
    if pd.notna(human_pct) or pd.notna(urban_pct):
        parts = []
        if pd.notna(human_pct):
            parts.append(f"Human footprint: {float(human_pct):.1f}%")
        if pd.notna(urban_pct):
            parts.append(f"Urban footprint: {float(urban_pct):.1f}%")
        elements.append(Paragraph(f"<i>{' | '.join(parts)}</i>", custom_styles["caption"]))

    transport_metrics = [
        ("road_count", "Roads"), ("major_road_count", "Major roads"),
        ("rail_count", "Rail"), ("building_count", "Buildings"),
        ("waterway_count", "Waterways"), ("dam_count", "Dams"),
        ("power_substation_count", "Substations"),
    ]
    transport_data = [["Infrastructure", "Count"]]
    for col, label in transport_metrics:
        if col in osm_row.index and pd.notna(osm_row.get(col)):
            transport_data.append([label, f"{int(osm_row.get(col)):,}"])
    if len(transport_data) > 1:
        elements.append(Paragraph("<b>Infrastructure counts</b>", custom_styles["body"]))
        elements.append(_mt(transport_data, [8, 4], theme.success, {1}))

    elements.append(PageBreak())

    # ── I) AI INSIGHTS ───────────────────────────────────────────────────────
    elements.append(Paragraph("7. AI Insights", custom_styles["section_h1"]))

    if ai_insights and ai_insights.strip():
        _parse_ai_insights(ai_insights.strip(), elements, custom_styles, _mt)
    else:
        elements.append(Paragraph("No AI insights available.", custom_styles["body"]))

    elements.append(PageBreak())

    # ── J) LIMITATIONS & METHODOLOGY ─────────────────────────────────────────
    elements.append(Paragraph("8. Limitations & Methodology", custom_styles["section_h1"]))

    limitations = [
        "GBIF data bias: Observations reflect sampling effort and citizen science coverage; absence of records does not imply species absence.",
        "OSM snapshot lag: Land cover and infrastructure reflect OSM state at snapshot date; may lag real-world changes.",
        "Coordinate uncertainty: Many records have high coordinate uncertainty; use DQI and uncertainty metrics for interpretation.",
        "IUCN coverage: Not all species have IUCN assessments; threatened count may underestimate conservation concern.",
    ]
    for lim in limitations:
        elements.append(Paragraph(f"• {lim}", custom_styles["body"]))

    elements.append(Spacer(1, 0.3 * cm))
    elements.append(Paragraph(
        "<b>Data provenance:</b> GBIF occurrence API, IUCN Red List API, OpenStreetMap Overpass. "
        "Report for screening only; recommend field verification for decisions.",
        custom_styles["body"],
    ))

    doc.build(elements)
    return buf.getvalue()
