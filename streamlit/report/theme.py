"""
Report Style Spec — Consultancy-grade design system.
====================================================
Typography, colors, spacing, grid. Single source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# TYPOGRAPHY
# ─────────────────────────────────────────────────────────────────────────────

# Helvetica (built-in) with bold variant; Inter/Source Sans would require TTF
FONT_FAMILY = "Helvetica"
FONT_BOLD = "Helvetica-Bold"

# Sizes (pt)
COVER_TITLE = 30
SECTION_H1 = 17
SUBHEAD = 12
BODY = 10
TABLE_TEXT = 9
FOOTER = 8
CAPTION = 8

# Line height multipliers
LINE_HEIGHT_BODY = 1.3
LINE_HEIGHT_TITLE = 1.25

# ─────────────────────────────────────────────────────────────────────────────
# SPACING (pt) — 8/12/16 token system
# ─────────────────────────────────────────────────────────────────────────────

SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24

# ─────────────────────────────────────────────────────────────────────────────
# COLORS (hex)
# ─────────────────────────────────────────────────────────────────────────────

# Primary accent — dark blue/teal (headers, KPI bars)
PRIMARY = "#0d3b4c"
PRIMARY_LIGHT = "#1a5276"

# Neutral grayscale
GRAY_900 = "#1a1a1a"
GRAY_700 = "#4a4a4a"
GRAY_500 = "#6b7280"
GRAY_300 = "#d1d5db"
GRAY_100 = "#f3f4f6"
GRAY_300 = "#d1d5db"
WHITE = "#ffffff"

# Semantic
WARNING = "#d97706"   # Amber — limitations, low confidence
RISK = "#b91c1c"     # Red — threatened, invasive highlights
SUCCESS = "#047857"  # Green — positive metrics

# IUCN category badges
IUCN_CR = "#7f1d1d"   # Dark red
IUCN_EN = "#b91c1c"   # Red
IUCN_VU = "#c2410c"   # Orange
IUCN_NT = "#a16207"   # Amber
IUCN_LC = "#166534"   # Green
IUCN_DD = "#4b5563"   # Gray

# ─────────────────────────────────────────────────────────────────────────────
# PAGE LAYOUT
# ─────────────────────────────────────────────────────────────────────────────

MARGIN_CM = 1.8
FOOTER_HEIGHT_CM = 1.0
HEADER_HEIGHT_CM = 0.8

# 12-column grid feel — content width ~16cm on A4
CONTENT_WIDTH_CM = 16.5

# ─────────────────────────────────────────────────────────────────────────────
# THEME OBJECT (for ReportLab)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Theme:
    """Theme object passed to report builders."""

    font: str = FONT_FAMILY
    font_bold: str = FONT_BOLD
    primary: str = PRIMARY
    primary_light: str = PRIMARY_LIGHT
    gray_900: str = GRAY_900
    gray_500: str = GRAY_500
    gray_100: str = GRAY_100
    gray_300: str = GRAY_300
    warning: str = WARNING
    risk: str = RISK
    success: str = SUCCESS
    white: str = WHITE

    # Sizes
    cover_title: int = COVER_TITLE
    section_h1: int = SECTION_H1
    subhead: int = SUBHEAD
    body: int = BODY
    table_text: int = TABLE_TEXT
    footer: int = FOOTER

    # Spacing
    xs: int = SPACE_XS
    sm: int = SPACE_SM
    md: int = SPACE_MD
    lg: int = SPACE_LG
    xl: int = SPACE_XL

    def to_reportlab_colors(self) -> dict[str, Any]:
        """Return dict of colors for ReportLab HexColor."""
        from reportlab.lib import colors
        return {
            "primary": colors.HexColor(self.primary),
            "primary_light": colors.HexColor(self.primary_light),
            "gray_900": colors.HexColor(self.gray_900),
            "gray_500": colors.HexColor(self.gray_500),
            "gray_100": colors.HexColor(self.gray_100),
            "warning": colors.HexColor(self.warning),
            "risk": colors.HexColor(self.risk),
            "success": colors.HexColor(self.success),
            "white": colors.HexColor(self.white),
        }


DEFAULT_THEME = Theme()
