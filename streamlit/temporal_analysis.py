"""
Temporal Signals (In-Time Analysis) for biodiversity report.
==========================================================
Produces yearly trends from hex_metrics and hex_species for a single H3 cell.
Adapted from prompt: observation pressure, biodiversity intensity, threatened
pressure, invasive early-warning, confidence over time.

Data: gold tables are yearly (no monthly). Uses last 4–5 years.
"""

from __future__ import annotations

import io
from typing import Any

import pandas as pd


def _safe_int(x: Any) -> int:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return 0
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return 0


def _safe_float(x: Any) -> float:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return 0.0
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def compute_temporal_analysis(
    hex_metrics: pd.DataFrame,
    hex_species: pd.DataFrame,
    species_dim_by_year: dict[int, pd.DataFrame] | None = None,
) -> dict[str, Any]:
    """
    Compute temporal signals from multi-year hex metrics and species mapping.

    Returns:
        dict with:
        - obs_by_year: {year: obs_count}
        - richness_by_year: {year: richness}
        - threatened_by_year: {year: n_threatened_species}
        - threat_score_by_year: {year: threat_score_weighted}
        - dqi_by_year: {year: dqi}
        - cr_en_vu_by_year: {year: {cr, en, vu}}
        - new_threatened: list of {species_name, first_seen_year, count}
        - invasive_accel: list of {species_name, accel, recent, baseline, taxon_key}
        - invasive_by_year: {year: {taxon_key: count}}
        - narrative_text: str
        - limitations: str
    """
    result: dict[str, Any] = {
        "obs_by_year": {},
        "richness_by_year": {},
        "threatened_by_year": {},
        "threat_score_by_year": {},
        "dqi_by_year": {},
        "cr_en_vu_by_year": {},
        "new_threatened": [],
        "invasive_accel": [],
        "invasive_by_year": {},
        "narrative_text": "",
        "limitations": "",
    }

    if hex_metrics.empty:
        result["limitations"] = (
            "No multi-year metrics available. Temporal analysis requires "
            "gbif_cell_metrics for at least 2 years."
        )
        return result

    # Sort by year
    hex_metrics = hex_metrics.sort_values("year").reset_index(drop=True)
    years = hex_metrics["year"].unique().tolist()
    if len(years) < 2:
        result["limitations"] = (
            "Only one year of data available. Temporal trends require at least 2 years."
        )
        return result

    # 1) Observation pressure
    for _, row in hex_metrics.iterrows():
        y = int(row["year"])
        result["obs_by_year"][y] = _safe_int(row.get("observation_count"))

    # 2) Biodiversity intensity (richness)
    for _, row in hex_metrics.iterrows():
        y = int(row["year"])
        result["richness_by_year"][y] = _safe_int(row.get("species_richness_cell"))

    # 3) Threatened pressure
    for _, row in hex_metrics.iterrows():
        y = int(row["year"])
        result["threatened_by_year"][y] = _safe_int(row.get("n_threatened_species"))
        result["threat_score_by_year"][y] = _safe_int(row.get("threat_score_weighted"))
        result["cr_en_vu_by_year"][y] = {
            "cr": _safe_int(row.get("n_sp_cr")),
            "en": _safe_int(row.get("n_sp_en")),
            "vu": _safe_int(row.get("n_sp_vu")),
        }

    # 4) DQI
    for _, row in hex_metrics.iterrows():
        y = int(row["year"])
        result["dqi_by_year"][y] = _safe_float(row.get("dqi"))

    # New threatened species (last 2 years vs previous 2–3 years)
    if not hex_species.empty and "is_threatened" in hex_species.columns:
        threatened = hex_species[hex_species["is_threatened"]].copy()
        if not threatened.empty:
            recent_years = sorted(years)[-2:] if len(years) >= 2 else years
            baseline_years = [y for y in years if y not in recent_years]
            baseline_taxa = set()
            if baseline_years:
                baseline_taxa = set(
                    threatened[threatened["year"].isin(baseline_years)]["taxon_key"]
                    .astype(str)
                    .unique()
                )
            for _, row in threatened.iterrows():
                tk = row.get("taxon_key")
                y = row.get("year")
                if tk is None or pd.isna(tk) or y is None:
                    continue
                tk_str = str(int(tk))
                if tk_str in baseline_taxa:
                    continue
                if y in recent_years:
                    name = "Unknown"
                    if species_dim_by_year and int(y) in species_dim_by_year:
                        dim = species_dim_by_year[int(y)]
                        match = dim[dim["taxon_key"].astype(str) == tk_str]
                        if not match.empty and "species_name" in match.columns:
                            name = str(match.iloc[0]["species_name"])
                    result["new_threatened"].append({
                        "species_name": name,
                        "first_seen_year": int(y),
                        "count": _safe_int(row.get("occurrence_count")),
                    })

    # Invasive acceleration (recent 2 years vs baseline 2–3 years)
    if not hex_species.empty and "is_invasive" in hex_species.columns:
        invasive = hex_species[hex_species["is_invasive"]].copy()
        if not invasive.empty:
            recent_years = sorted(years)[-2:] if len(years) >= 2 else years
            baseline_years = [y for y in years if y not in recent_years]
            baseline_taxa = set(
                invasive[invasive["year"].isin(baseline_years)]["taxon_key"]
                .astype(str)
                .unique()
            ) if baseline_years else set()

            for taxon_key in invasive["taxon_key"].unique():
                sub = invasive[invasive["taxon_key"] == taxon_key]
                recent_count = sub[sub["year"].isin(recent_years)]["occurrence_count"].sum()
                baseline_count = sub[sub["year"].isin(baseline_years)]["occurrence_count"].sum()
                recent_rate = _safe_int(recent_count) + 1
                baseline_rate = _safe_int(baseline_count) + 1
                accel = recent_rate / baseline_rate
                name = "Unknown"
                latest_year = sub["year"].max()
                if species_dim_by_year and latest_year in species_dim_by_year:
                    dim = species_dim_by_year[int(latest_year)]
                    match = dim[dim["taxon_key"].astype(str) == str(taxon_key)]
                    if not match.empty and "species_name" in match.columns:
                        name = str(match.iloc[0]["species_name"])
                result["invasive_accel"].append({
                    "species_name": name,
                    "accel": round(accel, 2),
                    "recent": _safe_int(recent_count),
                    "baseline": _safe_int(baseline_count),
                    "taxon_key": taxon_key,
                })
                result["invasive_by_year"][taxon_key] = {
                    int(y): _safe_int(sub[sub["year"] == y]["occurrence_count"].sum())
                    for y in years
                    if y in sub["year"].values
                }

            result["invasive_accel"].sort(key=lambda x: x["accel"], reverse=True)
            result["invasive_accel"] = result["invasive_accel"][:5]

    # Build narrative
    result["narrative_text"] = _build_narrative(result, years)
    result["limitations"] = (
        "GBIF data reflects sampling effort and publisher activity, not "
        "true population changes. Temporal trends can be biased by dataset "
        "additions, coordinate uncertainty, and species identification gaps. "
        "Interpret with caution."
    )
    return result


def _build_narrative(data: dict[str, Any], years: list[int]) -> str:
    lines = []
    obs = data["obs_by_year"]
    richness = data["richness_by_year"]
    threatened = data["threatened_by_year"]
    dqi = data["dqi_by_year"]

    if len(years) >= 2:
        last = years[-1]
        prev = years[-2]
        obs_delta = obs.get(last, 0) - obs.get(prev, 0)
        obs_pct = (obs_delta / obs.get(prev, 1)) * 100 if obs.get(prev) else 0
        lines.append(f"• Observation count: {obs.get(last, 0):,} in {last} "
                    f"({obs_delta:+,} vs {prev}, {obs_pct:+.1f}%)")
        lines.append(f"• Species richness: {richness.get(last, 0):,} in {last} "
                    f"({richness.get(last, 0) - richness.get(prev, 0):+} vs {prev})")
        lines.append(f"• Threatened species: {threatened.get(last, 0)} in {last} "
                    f"(threat score: {data['threat_score_by_year'].get(last, 0)})")
        if dqi.get(last) is not None:
            lines.append(f"• Data Quality Index: {dqi.get(last):.2f} in {last}")

    if data["new_threatened"]:
        lines.append(f"• New threatened species (last 2 years): {len(data['new_threatened'])}")
        for s in data["new_threatened"][:3]:
            lines.append(f"  - {s['species_name']} (first seen {s['first_seen_year']})")

    if data["invasive_accel"]:
        top = data["invasive_accel"][0]
        lines.append(f"• Top invasive acceleration: {top['species_name']} "
                    f"(accel={top['accel']:.1f}x, recent={top['recent']}, baseline={top['baseline']})")

    lines.append("")
    lines.append("**What this means for decision-making:**")
    lines.append(
        "Temporal trends can signal changes in sampling effort, biodiversity "
        "pressure, or data quality. Rising observation counts may indicate "
        "increased monitoring or new data publishers. Declining threatened species "
        "counts could reflect improved status or reduced coverage. Use "
        "alongside spatial context and IUCN status for risk assessment."
    )
    return "\n".join(lines)


def render_temporal_charts(
    data: dict[str, Any],
    width: int = 500,
    height: int = 280,
) -> list[tuple[str, bytes]]:
    """
    Generate matplotlib charts for temporal analysis.
    Returns list of (title, png_bytes).
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []

    charts = []
    years = sorted(data["obs_by_year"].keys())
    if len(years) < 2:
        return charts

    # 1) Observation count
    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    obs_vals = [data["obs_by_year"].get(y, 0) for y in years]
    ax.plot(years, obs_vals, "o-", color="#2e86ab", linewidth=2, markersize=8)
    ax.set_title("Observation pressure (yearly)")
    ax.set_xlabel("Year")
    ax.set_ylabel("Observation count")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="PNG", bbox_inches="tight", dpi=100)
    plt.close()
    charts.append(("Observation pressure", buf.getvalue()))

    # 2) Species richness + threatened
    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    rich_vals = [data["richness_by_year"].get(y, 0) for y in years]
    thr_vals = [data["threatened_by_year"].get(y, 0) for y in years]
    ax.plot(years, rich_vals, "o-", color="#27ae60", label="Species richness", linewidth=2)
    ax.plot(years, thr_vals, "s-", color="#c0392b", label="Threatened species", linewidth=2)
    ax.set_title("Biodiversity intensity")
    ax.set_xlabel("Year")
    ax.set_ylabel("Count")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="PNG", bbox_inches="tight", dpi=100)
    plt.close()
    charts.append(("Biodiversity intensity", buf.getvalue()))

    # 3) Threatened pressure (stacked CR/EN/VU if available)
    cr_en_vu = data.get("cr_en_vu_by_year", {})
    if cr_en_vu and any(cr_en_vu.get(y, {}).get("cr", 0) or cr_en_vu.get(y, {}).get("en", 0) or cr_en_vu.get(y, {}).get("vu", 0) for y in years):
        fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
        cr = [cr_en_vu.get(y, {}).get("cr", 0) for y in years]
        en = [cr_en_vu.get(y, {}).get("en", 0) for y in years]
        vu = [cr_en_vu.get(y, {}).get("vu", 0) for y in years]
        ax.bar(years, cr, label="CR", color="#c0392b")
        ax.bar(years, en, bottom=cr, label="EN", color="#e74c3c")
        ax.bar(years, vu, bottom=[c + e for c, e in zip(cr, en)], label="VU", color="#e67e22")
        ax.set_title("Threatened species by category")
        ax.set_xlabel("Year")
        ax.set_ylabel("Count")
        ax.legend()
        ax.grid(True, alpha=0.3, axis="y")
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format="PNG", bbox_inches="tight", dpi=100)
        plt.close()
        charts.append(("Threatened by category", buf.getvalue()))
    else:
        # Simple line
        fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
        thr_vals = [data["threatened_by_year"].get(y, 0) for y in years]
        ax.plot(years, thr_vals, "o-", color="#c0392b", linewidth=2)
        ax.set_title("Threatened species pressure")
        ax.set_xlabel("Year")
        ax.set_ylabel("Count")
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format="PNG", bbox_inches="tight", dpi=100)
        plt.close()
        charts.append(("Threatened pressure", buf.getvalue()))

    # 4) Top invasive spatial expansion (occurrence count per year)
    if data["invasive_accel"]:
        fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
        for i, inv in enumerate(data["invasive_accel"][:5]):
            by_year = data.get("invasive_by_year", {}).get(inv["taxon_key"], {})
            vals = [by_year.get(y, 0) for y in years]
            label = inv["species_name"][:25] + ("…" if len(inv["species_name"]) > 25 else "")
            ax.plot(years, vals, "o-", label=label, linewidth=1.5)
        ax.set_title("Top invasive species (occurrence trend)")
        ax.set_xlabel("Year")
        ax.set_ylabel("Occurrence count")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format="PNG", bbox_inches="tight", dpi=100)
        plt.close()
        charts.append(("Invasive expansion", buf.getvalue()))

    # 5) DQI over time
    if data["dqi_by_year"]:
        fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
        dqi_vals = [data["dqi_by_year"].get(y, 0) for y in years]
        ax.plot(years, dqi_vals, "o-", color="#9b59b6", linewidth=2)
        ax.set_title("Data quality index (DQI)")
        ax.set_xlabel("Year")
        ax.set_ylabel("DQI (0–1)")
        ax.set_ylim(0, 1.05)
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format="PNG", bbox_inches="tight", dpi=100)
        plt.close()
        charts.append(("Confidence over time", buf.getvalue()))

    return charts


def get_temporal_tables(data: dict[str, Any]) -> list[tuple[str, list[list[str]]]]:
    """Return tables for PDF: (title, rows)."""
    tables = []

    if data["new_threatened"]:
        rows = [["Species", "First seen", "Occurrences"]]
        for s in data["new_threatened"][:10]:
            rows.append([s["species_name"][:40], str(s["first_seen_year"]), str(s["count"])])
        tables.append(("New threatened species (last 2 years)", rows))

    if data["invasive_accel"]:
        rows = [["Species", "Accel", "Recent", "Baseline"]]
        for inv in data["invasive_accel"]:
            rows.append([
                inv["species_name"][:40],
                f"{inv['accel']:.1f}x",
                str(inv["recent"]),
                str(inv["baseline"]),
            ])
        tables.append(("Top invasive by acceleration", rows))

    return tables
