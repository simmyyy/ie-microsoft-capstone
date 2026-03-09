"""
Biodiversity & Infrastructure Report Generator
==============================================
Facade for PDF report generation. Uses the premium report builder
(streamlit.report.build_report) for consultancy-grade output.

Designed to be imported and called from app.py.
"""

from __future__ import annotations

import pandas as pd


def generate_report(
    h3_index: str,
    h3_res: int,
    species_df: pd.DataFrame,
    osm_row: pd.Series,
    cell_metrics: pd.Series | None = None,
    name_col: str = "species_name",
    ai_insights: str | None = None,
    temporal_artifacts: dict | None = None,
    year: int | None = None,
    gee_terrain_row: pd.Series | dict | None = None,
    industry: str | None = None,
) -> bytes:
    """
    Generate a PDF report for the given H3 cell.
    Uses the premium report builder (consultancy-grade layout).

    Args:
        h3_index: H3 cell identifier
        h3_res: H3 resolution
        species_df: Species data for this hex
        osm_row: OSM metrics row for this hex
        cell_metrics: Optional GBIF cell metrics
        name_col: Column name for species display
        ai_insights: Optional AI-generated insights (markdown)
        temporal_artifacts: Optional dict with charts, tables, narrative_text, limitations

    Returns:
        PDF file as bytes
    """
    from report.build_report import build_report

    return build_report(
        h3_index=h3_index,
        h3_res=h3_res,
        species_df=species_df,
        osm_row=osm_row,
        cell_metrics=cell_metrics,
        name_col=name_col,
        ai_insights=ai_insights,
        temporal_artifacts=temporal_artifacts,
        year=year,
        gee_terrain_row=gee_terrain_row,
        industry=industry,
    )
