"""
Reusable PDF components: header, footer, section titles, KPI cards, callouts.
"""

from __future__ import annotations

from typing import Any

from .theme import DEFAULT_THEME, Theme


def _get_styles(theme: Theme):
    """Build ReportLab paragraph styles from theme."""
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    styles = getSampleStyleSheet()
    c = theme.to_reportlab_colors()

    return {
        "cover_title": ParagraphStyle(
            "CoverTitle",
            parent=styles["Heading1"],
            fontName=theme.font_bold,
            fontSize=theme.cover_title,
            leading=int(theme.cover_title * 1.25),
            spaceAfter=theme.sm,
            textColor=c["primary"],
            alignment=1,  # center
        ),
        "cover_subtitle": ParagraphStyle(
            "CoverSubtitle",
            parent=styles["Normal"],
            fontName=theme.font,
            fontSize=theme.subhead,
            leading=int(theme.subhead * 1.3),
            spaceAfter=theme.lg,
            textColor=c["gray_500"],
            alignment=1,
        ),
        "section_h1": ParagraphStyle(
            "SectionH1",
            parent=styles["Heading2"],
            fontName=theme.font_bold,
            fontSize=theme.section_h1,
            leading=int(theme.section_h1 * 1.25),
            spaceBefore=theme.lg,
            spaceAfter=theme.sm,
            textColor=c["primary"],
            alignment=0,
        ),
        "subhead": ParagraphStyle(
            "Subhead",
            parent=styles["Normal"],
            fontName=theme.font_bold,
            fontSize=theme.subhead,
            leading=int(theme.subhead * 1.3),
            spaceAfter=theme.xs,
            textColor=c["gray_900"],
            alignment=0,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=styles["Normal"],
            fontName=theme.font,
            fontSize=theme.body,
            leading=int(theme.body * 1.3),
            spaceAfter=theme.sm,
            alignment=0,
        ),
        "caption": ParagraphStyle(
            "Caption",
            parent=styles["Normal"],
            fontName=theme.font,
            fontSize=theme.footer,
            leading=int(theme.footer * 1.25),
            spaceAfter=theme.xs,
            textColor=c["gray_500"],
            alignment=0,
        ),
        "footer": ParagraphStyle(
            "Footer",
            parent=styles["Normal"],
            fontName=theme.font,
            fontSize=theme.footer,
            leading=theme.footer + 2,
            textColor=colors.white,
            alignment=0,
        ),
    }


def draw_header_footer(canvas, doc, theme: Theme, h3_index: str, year_range: str):
    """Draw header (top bar) and footer on every page."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm

    page_w, page_h = A4
    margin = theme.md / 72 * 2.54 * 10  # approx
    margin_cm = 1.8 * cm
    footer_h = 1.0 * cm
    header_h = 0.5 * cm

    canvas.saveState()

    # Footer bar
    canvas.setFillColor(colors.HexColor(theme.primary))
    canvas.rect(0, 0, page_w, footer_h, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont(theme.font, theme.footer)
    canvas.drawString(margin_cm, 0.35 * cm, f"{h3_index} · {year_range} · Biodiversity & Infrastructure Assessment")
    canvas.drawRightString(page_w - margin_cm, 0.35 * cm, f"Page {doc.page}")

    # Header line (subtle)
    canvas.setStrokeColor(colors.HexColor(getattr(theme, "gray_300", "#d1d5db")))
    canvas.setLineWidth(0.5)
    canvas.line(margin_cm, page_h - header_h, page_w - margin_cm, page_h - header_h)

    canvas.restoreState()


def section_title(text: str, theme: Theme = DEFAULT_THEME):
    """Section H1 with consistent styling."""
    from reportlab.platypus import Paragraph

    styles = _get_styles(theme)
    return Paragraph(text, styles["section_h1"])


def kpi_card(label: str, value: str, theme: Theme = DEFAULT_THEME, accent: bool = True):
    """Single KPI card (label + value) for at-a-glance row."""
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import Table, TableStyle

    bg = colors.HexColor(theme.primary) if accent else colors.HexColor(theme.gray_100)
    fg = colors.white if accent else colors.HexColor(theme.gray_900)

    t = Table([[label, value]], colWidths=[4 * cm, 2.5 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("TEXTCOLOR", (0, 0), (-1, -1), fg),
        ("FONTNAME", (0, 0), (0, -1), theme.font),
        ("FONTNAME", (1, 0), (1, -1), theme.font_bold),
        ("FONTSIZE", (0, 0), (-1, -1), theme.table_text),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def callout_box(title: str, bullets: list[str], theme: Theme = DEFAULT_THEME, box_type: str = "info"):
    """Callout box with title + bullet list. box_type: info, warning, risk."""
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, Table, TableStyle

    colors_map = {"info": theme.primary_light, "warning": theme.warning, "risk": theme.risk}
    border_color = colors.HexColor(colors_map.get(box_type, theme.primary_light))

    styles = _get_styles(theme)
    content = [Paragraph(f"<b>{title}</b>", styles["subhead"])]
    for b in bullets:
        content.append(Paragraph(f"• {b}", styles["body"]))

    from reportlab.platypus import Table
    inner = Table([[c] for c in content], colWidths=[14 * cm])
    inner.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    wrapper = Table([[inner]], colWidths=[15 * cm])
    wrapper.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1, border_color),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(theme.gray_100)),
    ]))
    return wrapper


def divider(theme: Theme = DEFAULT_THEME):
    """Thin horizontal divider line."""
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import Table, TableStyle

    t = Table([[""]], colWidths=[16 * cm], rowHeights=[0.12 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(theme.primary)),
    ]))
    return t


def spacer(height_cm: float = 0.5):
    """Vertical spacer."""
    from reportlab.lib.units import cm
    from reportlab.platypus import Spacer
    return Spacer(1, height_cm * cm)
