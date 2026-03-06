"""
Styled matplotlib charts for PDF — clean, consultancy-grade.
White background, light grid, consistent colors, readable fonts.
"""

from __future__ import annotations

import io
from typing import Any

# Chart color palette — grayscale + one accent (max 4 colors)
CHART_COLORS = ["#4a4a4a", "#6b7280", "#9ca3af", "#0d3b4c"]  # gray, gray, gray, accent
CHART_ACCENT = "#0d3b4c"
CHART_RISK = "#b91c1c"
CHART_WARNING = "#d97706"


def _apply_style(ax, fig):
    """Apply consistent styling to matplotlib axes."""
    import matplotlib.pyplot as plt

    ax.set_facecolor("white")
    fig.patch.set_facecolor("white")
    ax.grid(True, alpha=0.25, linestyle="-")
    ax.tick_params(axis="both", labelsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Helvetica", "DejaVu Sans", "Arial"]


def render_land_cover_bar(osm_row: Any, width: int = 500, height: int = 300) -> bytes | None:
    """Horizontal bar chart of land cover % (ranked) — cleaner than pie."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    pct_cols = [
        ("waterbody_area_pct", "Waterbody"),
        ("waterway_area_pct", "Waterway"),
        ("wetland_area_pct", "Wetland"),
        ("road_area_pct", "Roads"),
        ("building_area_pct", "Buildings"),
        ("residential_area_pct", "Residential"),
        ("commercial_area_pct", "Commercial"),
        ("industrial_area_pct", "Industrial"),
        ("parks_green_area_pct", "Parks & green"),
        ("agri_area_pct", "Agriculture"),
        ("managed_forest_area_pct", "Forest"),
        ("natural_habitat_area_pct", "Natural habitat"),
        ("protected_area_pct", "Protected"),
        ("restricted_area_pct", "Restricted"),
    ]

    items: list[tuple[str, float]] = []
    for col, label in pct_cols:
        if col in osm_row.index:
            val = osm_row.get(col)
            if val is not None and hasattr(val, "__float__") and float(val) > 0:
                items.append((label, min(float(val), 100.0)))

    if not items:
        return None

    items.sort(key=lambda x: x[1], reverse=True)
    labels = [x[0] for x in items[:12]]
    values = [x[1] for x in items[:12]]

    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    y_pos = range(len(labels))
    bars = ax.barh(y_pos, values, color=CHART_ACCENT, height=0.6, alpha=0.85)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel("% of hex area", fontsize=10)
    ax.set_title("Land cover (% of hex area)", fontsize=12, fontweight="bold")
    ax.set_xlim(0, max(values) * 1.15 if values else 100)
    _apply_style(ax, fig)
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="PNG", bbox_inches="tight", dpi=100, facecolor="white")
    plt.close()
    return buf.getvalue()


def render_observation_pressure(years: list[int], obs_by_year: dict[int, int], width: int = 500, height: int = 220) -> bytes | None:
    """Line chart: observation pressure over time."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    vals = [obs_by_year.get(y, 0) for y in years]
    if not vals:
        return None

    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    ax.plot(years, vals, "o-", color=CHART_ACCENT, linewidth=2, markersize=6)
    ax.set_xlabel("Year", fontsize=10)
    ax.set_ylabel("Observations", fontsize=10)
    ax.set_title("Observation pressure", fontsize=12, fontweight="bold")
    ax.ticklabel_format(style="plain", axis="y")
    _apply_style(ax, fig)
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="PNG", bbox_inches="tight", dpi=100, facecolor="white")
    plt.close()
    return buf.getvalue()


def render_richness_threatened(years: list[int], richness_by_year: dict, threatened_by_year: dict, width: int = 500, height: int = 220) -> bytes | None:
    """Two lines: richness + threatened count."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    r_vals = [richness_by_year.get(y, 0) for y in years]
    t_vals = [threatened_by_year.get(y, 0) for y in years]
    if not r_vals and not t_vals:
        return None

    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    ax.plot(years, r_vals, "o-", color=CHART_COLORS[0], linewidth=2, label="Species richness")
    ax.plot(years, t_vals, "s-", color=CHART_RISK, linewidth=2, label="Threatened")
    ax.set_xlabel("Year", fontsize=10)
    ax.set_ylabel("Count", fontsize=10)
    ax.set_title("Biodiversity intensity", fontsize=12, fontweight="bold")
    ax.legend(loc="best", fontsize=9)
    _apply_style(ax, fig)
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="PNG", bbox_inches="tight", dpi=100, facecolor="white")
    plt.close()
    return buf.getvalue()


def render_dqi_over_time(years: list[int], dqi_by_year: dict, width: int = 500, height: int = 220) -> bytes | None:
    """Line chart: DQI over time."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    vals = [dqi_by_year.get(y, 0) for y in years]
    if not vals:
        return None

    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    ax.plot(years, vals, "o-", color=CHART_ACCENT, linewidth=2, markersize=6)
    ax.set_xlabel("Year", fontsize=10)
    ax.set_ylabel("DQI (0–1)", fontsize=10)
    ax.set_title("Data quality index over time", fontsize=12, fontweight="bold")
    ax.set_ylim(0, 1.05)
    _apply_style(ax, fig)
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="PNG", bbox_inches="tight", dpi=100, facecolor="white")
    plt.close()
    return buf.getvalue()
