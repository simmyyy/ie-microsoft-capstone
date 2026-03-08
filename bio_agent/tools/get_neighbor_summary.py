"""
GetNeighborSummary: Aggregated stats for a set of neighbor H3 cells.
"""
from __future__ import annotations

import logging
from typing import Any

import db
from .validation import validate_h3_id_list, validate_h3_resolution, validate_year

logger = logging.getLogger(__name__)
SCHEMA = db.schema()


def _parse_params(params: list[dict], body: dict | None) -> dict[str, Any]:
    p = {x["name"]: x.get("value") for x in (params or []) if x.get("name")}
    if body and isinstance(body, dict):
        props = body.get("content", {}).get("application/json", {}).get("properties", [])
        if isinstance(props, list):
            for x in props:
                if isinstance(x, dict) and x.get("name"):
                    p[x["name"]] = x.get("value", p.get(x["name"]))
        elif isinstance(props, dict):
            p.update(props)
    # Handle h3_ids as JSON string
    h3_ids_raw = p.get("h3_ids") or p.get("h3Ids")
    if isinstance(h3_ids_raw, str):
        try:
            import json
            p["h3_ids"] = json.loads(h3_ids_raw)
        except json.JSONDecodeError:
            p["h3_ids"] = [x.strip() for x in h3_ids_raw.split(",") if x.strip()]
    return p


def handler(params: list[dict], body: dict | None = None) -> dict[str, Any]:
    """
    GetNeighborSummary tool handler.
    Input: h3_ids (list), h3_res, optional year
    Output: aggregated stats (mean/median richness, total threatened, mean DQI, top risky neighbors)
    """
    p = _parse_params(params or [], body)
    h3_ids = validate_h3_id_list(p.get("h3_ids") or p.get("h3Ids"))
    h3_res = validate_h3_resolution(p.get("h3_res") or p.get("h3Res"))
    year = validate_year(p.get("year"))

    if not h3_ids:
        return {
            "h3_ids": [],
            "h3_resolution": h3_res,
            "summary": None,
            "message": "No valid H3 IDs provided",
        }

    placeholders = ", ".join(["%s"] * len(h3_ids))
    args: list[Any] = list(h3_ids) + [h3_res]
    year_clause = ""
    if year is not None:
        year_clause = " AND year = %s"
        args.append(year)

    with db.get_connection() as conn:
        cur = conn.cursor()

        # If no year, use latest year in data
        if year is None:
            cur.execute(
                f"SELECT MAX(year) FROM {SCHEMA}.gbif_cell_metrics "
                f"WHERE h3_index IN ({placeholders}) AND h3_resolution = %s",
                list(h3_ids) + [h3_res],
            )
            row = cur.fetchone()
            if row and row[0]:
                year = row[0]
                year_clause = " AND year = %s"
                args = list(h3_ids) + [h3_res, year]

        q = f"""
            SELECT *
            FROM {SCHEMA}.gbif_cell_metrics
            WHERE h3_index IN ({placeholders}) AND h3_resolution = %s
            """ + year_clause + """
            ORDER BY threat_score_weighted DESC NULLS LAST
        """
        cur.execute(q, args)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]

        def _to_json_val(v):
            if v is None:
                return None
            if isinstance(v, float) and v != v:
                return None
            if isinstance(v, (int, str, bool, float)):
                return v
            return str(v)

        cells = [{k: _to_json_val(v) for k, v in dict(zip(cols, r)).items()} for r in rows]

        if not cells:
            cur.close()
            return {
                "h3_ids": h3_ids,
                "h3_resolution": h3_res,
                "year": year,
                "summary": None,
                "top_risky_neighbors": [],
                "message": "No metrics found for given H3 cells",
            }

        # Aggregate
        richness = [c.get("species_richness_cell") for c in cells if c.get("species_richness_cell") is not None]
        threatened = [c.get("n_threatened_species") for c in cells if c.get("n_threatened_species") is not None]
        dqi_vals = [c.get("dqi") for c in cells if c.get("dqi") is not None]
        threat_vals = [c.get("threat_score_weighted") for c in cells if c.get("threat_score_weighted") is not None]

        def mean(v):
            return sum(v) / len(v) if v else None

        def median(v):
            if not v:
                return None
            s = sorted(v)
            mid = len(s) // 2
            return (s[mid] + s[mid - 1]) / 2 if len(s) % 2 == 0 else s[mid]

        summary = {
            "mean_richness": round(mean(richness), 2) if richness else None,
            "median_richness": round(median(richness), 2) if richness else None,
            "total_threatened": sum(threatened) if threatened else 0,
            "mean_dqi": round(mean(dqi_vals), 4) if dqi_vals else None,
            "mean_threat_score": round(mean(threat_vals), 2) if threat_vals else None,
            "cell_count": len(cells),
        }

        # All neighbors ordered by threat (risky first), full row data
        top_risky = cells

        cur.close()
        return {
            "h3_ids": h3_ids,
            "h3_resolution": h3_res,
            "year": year,
            "summary": summary,
            "top_risky_neighbors": top_risky,
        }
