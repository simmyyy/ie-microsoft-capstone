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


def _latlon_to_pixel(lat: float, lon: float, zoom: int, tx0: int, ty0: int, tile_size: int = 256) -> tuple[float, float]:
    """Convert lat/lng to pixel coords within a tile grid starting at (tx0, ty0)."""
    lat_rad = math.radians(lat)
    n = 2.0**zoom
    tile_x = (lon + 180.0) / 360.0 * n
    tile_y = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    px = (tile_x - tx0) * tile_size
    py = (tile_y - ty0) * tile_size
    return (px, py)


def _render_map_image(h3_index: str, width: int = 550, height: int = 380) -> bytes | None:
    try:
        import h3
        from PIL import Image, ImageDraw
        import urllib.request
    except ImportError:
        return None
    try:
        boundary = h3.cell_to_boundary(h3_index)
        if not boundary or len(boundary) < 3:
            return None
        # Parse boundary: h3 returns (lat, lng) per vertex
        lats, lngs = [], []
        for pt in boundary:
            if len(pt) == 2:
                plat, plng = pt[0], pt[1]
                if abs(plat) > 90 or abs(plng) > 180:
                    plat, plng = pt[1], pt[0]
                lats.append(plat)
                lngs.append(plng)
        if not lats:
            return None
        min_lat, max_lat = min(lats), max(lats)
        min_lng, max_lng = min(lngs), max(lngs)
        center_lat = (min_lat + max_lat) / 2
        center_lng = (min_lng + max_lng) / 2
        delta_lat = max_lat - min_lat
        delta_lng = max_lng - min_lng
        # Add 40% padding so hex fits with margin
        span_lat = max(delta_lat * 1.4, 0.01)
        span_lng = max(delta_lng * 1.4, 0.01)
        # Pick highest zoom (most zoomed in) where 3x3 tiles still fit the hex
        tiles_n = 3
        zoom = 10
        for z in range(14, 5, -1):
            nz = 2.0**z
            deg_per = 360.0 / nz
            if tiles_n * deg_per >= max(span_lat, span_lng):
                zoom = z
                break
        tile_size = 256
        tx, ty = _latlon_to_tile(center_lat, center_lng, zoom)
        tx0 = tx - tiles_n // 2
        ty0 = ty - tiles_n // 2
        img_w = img_h = tile_size * tiles_n
        canvas = Image.new("RGB", (img_w, img_h), (248, 248, 248))
        for dx in range(tiles_n):
            for dy in range(tiles_n):
                txx, tyy = tx0 + dx, ty0 + dy
                url = f"https://tile.openstreetmap.org/{zoom}/{txx}/{tyy}.png"
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "BiodiversityReport/1.0"})
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        tile_img = Image.open(io.BytesIO(resp.read())).convert("RGB")
                        canvas.paste(tile_img, (dx * tile_size, dy * tile_size))
                except Exception:
                    pass
        draw = ImageDraw.Draw(canvas)
        hex_xy = []
        for plat, plng in zip(lats, lngs):
            px, py = _latlon_to_pixel(plat, plng, zoom, tx0, ty0, tile_size)
            hex_xy.append((px, py))
        # Outline only, no fill — area inside stays visible
        draw.polygon(hex_xy, outline="#0d3b4c", fill=None, width=4)
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
    gee_terrain_row: pd.Series | dict | None = None,
    industry: str | None = None,
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
    if industry and str(industry).strip():
        elements.append(Paragraph(f"<b>Industry:</b> {_escape_html(str(industry).strip())}", custom_styles["body"]))
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
        "1. Location & Context",
        "2. Biodiversity Overview",
        "3. Threatened & Invasive Species",
        "4. Temporal Signals",
        "5. Terrain & Land Cover (GEE)",
        "6. Infrastructure (OSM)",
        "7. AI Insights",
        "8. Limitations & Methodology",
    ]
    for item in toc_items:
        elements.append(Paragraph(item, custom_styles["body"]))
    elements.append(PageBreak())

    # ── C) LOCATION & CONTEXT ────────────────────────────────────────────────
    elements.append(Paragraph("1. Location & Context", custom_styles["section_h1"]))

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

    # ── D) BIODIVERSITY OVERVIEW ─────────────────────────────────────────────
    elements.append(Paragraph("2. Biodiversity Overview", custom_styles["section_h1"]))

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

    # ── E) THREATENED & INVASIVE ──────────────────────────────────────────────
    elements.append(Paragraph("3. Threatened & Invasive Species", custom_styles["section_h1"]))

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

    # ── F) TEMPORAL SIGNALS ───────────────────────────────────────────────────
    elements.append(Paragraph("4. Temporal Signals", custom_styles["section_h1"]))

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

    # ── G) TERRAIN & LAND COVER (GEE) ─────────────────────────────────────────
    elements.append(Paragraph("5. Terrain & Land Cover (GEE)", custom_styles["section_h1"]))

    if gee_terrain_row is not None:
        gee = gee_terrain_row if hasattr(gee_terrain_row, "get") else dict(gee_terrain_row)
        elev = gee.get("elevation_mean")
        slope = gee.get("slope_mean")
        if pd.notna(elev) and elev is not None:
            elements.append(Paragraph(f"<b>Elevation (mean):</b> {float(elev):.0f} m a.s.l.", custom_styles["body"]))
        if pd.notna(slope) and slope is not None:
            elements.append(Paragraph(f"<b>Slope (mean):</b> {float(slope):.1f}°", custom_styles["body"]))
        if pd.notna(elev) or pd.notna(slope):
            elements.append(Spacer(1, 0.2 * cm))

        gee_pie = charts.render_gee_land_cover_pie(gee)
        if gee_pie:
            elements.append(Paragraph("<b>Land cover (Copernicus 100m)</b>", custom_styles["body"]))
            elements.append(Image(io.BytesIO(gee_pie), width=14 * cm, height=9 * cm))
            elements.append(Spacer(1, 0.3 * cm))

        lc_items = []
        cols_iter = sorted(gee.keys()) if isinstance(gee, dict) else sorted(gee.index)
        for col in cols_iter:
            if not (str(col).startswith("lc_") and str(col).endswith("_pct")):
                continue
            val = gee.get(col, None) if isinstance(gee, dict) else gee.get(col, None)
            if val is None or (hasattr(val, "__float__") and float(val) <= 0):
                continue
            try:
                pct = float(val) * 100
            except (TypeError, ValueError):
                continue
            cid_str = str(col).replace("lc_", "").replace("_pct", "")
            try:
                cid = int(cid_str)
                label = charts.GEE_LC_LABELS.get(cid, col)
            except ValueError:
                label = col
            lc_items.append((label, f"{pct:.1f}%", pct))
        lc_items.sort(key=lambda x: -x[2])
        if lc_items:
            lc_data = [["Land cover type", "%"]] + [[l, p] for l, p, _ in lc_items]
            elements.append(Paragraph("<b>Land cover breakdown</b>", custom_styles["body"]))
            elements.append(_mt(lc_data, [10, 3], theme.primary_light, {1}))
    else:
        elements.append(Paragraph("No GEE terrain data available for this cell.", custom_styles["body"]))

    elements.append(PageBreak())

    # ── H) INFRASTRUCTURE (OSM) ───────────────────────────────────────────────
    elements.append(Paragraph("6. Infrastructure (OSM)", custom_styles["section_h1"]))

    # Build infrastructure table: counts + per-km² where meaningful
    hex_km2 = osm_row.get("hex_area_km2")
    area_km2 = float(hex_km2) if pd.notna(hex_km2) and hex_km2 else None
    infra_rows: list[list[str]] = []
    infra_defs = [
        ("hex_area_km2", "Hex area (km²)", "float"),
        ("road_count", "Road segments", "int"),
        ("road_count_per_km2", "Roads per km²", "float"),
        ("major_road_count", "Major roads", "int"),
        ("building_count", "Buildings", "int"),
        ("building_count_per_km2", "Buildings per km²", "float"),
        ("rail_count", "Rail segments", "int"),
        ("waterway_count", "Waterways", "int"),
        ("waterbody_count", "Waterbodies", "int"),
        ("wetland_count", "Wetlands", "int"),
        ("dam_count", "Dams", "int"),
        ("power_plant_count", "Power plants", "int"),
        ("power_substation_count", "Substations", "int"),
        ("fuel_station_count", "Fuel stations", "int"),
        ("industrial_area_count", "Industrial areas", "int"),
        ("waste_site_count", "Waste sites", "int"),
    ]
    for col, label, fmt in infra_defs:
        val = osm_row.get(col)
        if val is None or (hasattr(val, "__float__") and pd.isna(val)):
            continue
        if fmt == "int":
            infra_rows.append([label, f"{int(val):,}"])
        elif fmt == "float":
            infra_rows.append([label, f"{float(val):.2f}"])
        else:
            infra_rows.append([label, str(val)])
    if infra_rows:
        infra_data = [["Infrastructure", "Value"]] + infra_rows
        elements.append(_mt(infra_data, [10, 2], theme.success, {1}))
    else:
        elements.append(Paragraph("No OSM infrastructure data for this cell.", custom_styles["body"]))

    elements.append(PageBreak())

    # ── I) AI INSIGHTS ────────────────────────────────────────────────────────
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
