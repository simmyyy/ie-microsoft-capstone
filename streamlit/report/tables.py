"""
Table renderer: zebra rows, aligned numbers, IUCN badges, fixed column widths.
"""

from __future__ import annotations

from typing import Any

from .theme import DEFAULT_THEME, Theme, IUCN_CR, IUCN_EN, IUCN_VU, IUCN_NT, IUCN_LC, IUCN_DD


def _iucn_badge_color(cat: str) -> str:
    """Return hex color for IUCN category badge."""
    c = (cat or "").strip().upper()
    if c == "CR":
        return IUCN_CR
    if c == "EN":
        return IUCN_EN
    if c == "VU":
        return IUCN_VU
    if c in ("NT", "LR/NT"):
        return IUCN_NT
    if c in ("LC", "LR/LC"):
        return IUCN_LC
    if c == "DD":
        return IUCN_DD
    return "#6b7280"


def make_table(
    data: list[list[Any]],
    col_widths: list[float],
    header_color: str,
    theme: Theme = DEFAULT_THEME,
    numeric_cols: set[int] | None = None,
    align_right_cols: set[int] | None = None,
) -> Any:
    """
    Build ReportLab Table with zebra striping, header, aligned numbers.

    numeric_cols: 0-based indices for columns that should be right-aligned and formatted
    align_right_cols: 0-based indices for right alignment (numbers, counts)
    """
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import Table, TableStyle

    numeric_cols = numeric_cols or set()
    align_right_cols = align_right_cols or set()

    # Format numeric cells
    formatted = []
    for ri, row in enumerate(data):
        new_row = []
        for ci, cell in enumerate(row):
            if ci in numeric_cols and ri > 0:
                try:
                    v = cell
                    if isinstance(v, (int, float)):
                        if isinstance(v, float) and v == int(v):
                            new_row.append(f"{int(v):,}")
                        elif isinstance(v, float):
                            new_row.append(f"{v:,.2f}")
                        else:
                            new_row.append(f"{int(v):,}")
                    else:
                        new_row.append(str(cell))
                except (TypeError, ValueError):
                    new_row.append(str(cell))
            else:
                new_row.append(str(cell)[:50] + ("…" if len(str(cell)) > 50 else ""))
        formatted.append(new_row)

    t = Table(formatted, colWidths=[w * cm for w in col_widths])
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_color)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), theme.font_bold),
        ("FONTSIZE", (0, 0), (-1, 0), theme.table_text + 1),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor(theme.gray_900)),
        ("FONTSIZE", (0, 1), (-1, -1), theme.table_text),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(theme.gray_100)]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor(getattr(theme, "gray_300", "#d1d5db"))),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]

    for ci in align_right_cols:
        style.append(("ALIGN", (ci, 0), (ci, -1), "RIGHT"))
    for ci in numeric_cols:
        style.append(("ALIGN", (ci, 0), (ci, -1), "RIGHT"))

    t.setStyle(TableStyle(style))
    return t


def make_iucn_table(
    rows: list[list[Any]],
    col_widths: list[float],
    iucn_col_idx: int,
    theme: Theme = DEFAULT_THEME,
) -> Any:
    """
    Table with IUCN category badges (colored cell background for iucn_col_idx).
    """
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import Table, TableStyle

    formatted = []
    for ri, row in enumerate(rows):
        new_row = []
        for ci, cell in enumerate(row):
            s = str(cell)[:45] + ("…" if len(str(cell)) > 45 else "") if cell is not None else "—"
            new_row.append(s)
        formatted.append(new_row)

    t = Table(formatted, colWidths=[w * cm for w in col_widths])
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(theme.risk)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), theme.font_bold),
        ("FONTSIZE", (0, 0), (-1, 0), theme.table_text + 1),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(theme.gray_100)]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor(getattr(theme, "gray_300", "#d1d5db"))),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("ALIGN", (iucn_col_idx, 0), (iucn_col_idx, -1), "CENTER"),
    ]
    for ri in range(1, len(formatted)):
        cell_val = formatted[ri][iucn_col_idx] if iucn_col_idx < len(formatted[ri]) else ""
        if cell_val and cell_val != "—":
            bg = _iucn_badge_color(cell_val)
            style.append(("BACKGROUND", (iucn_col_idx, ri), (iucn_col_idx, ri), colors.HexColor(bg)))
            style.append(("TEXTCOLOR", (iucn_col_idx, ri), (iucn_col_idx, ri), colors.white))
    t.setStyle(TableStyle(style))
    return t
