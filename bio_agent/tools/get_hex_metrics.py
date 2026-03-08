"""
GetHexMetrics: Fetch biodiversity metrics for a single H3 cell.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import db
from .validation import validate_h3_id, validate_h3_resolution, validate_year, validate_last_n_months

logger = logging.getLogger(__name__)
SCHEMA = db.schema()


def _parse_params(params: list[dict], body: dict | None) -> dict[str, Any]:
    p = {x["name"]: x.get("value") for x in params if x.get("name")}
    if body and isinstance(body, dict):
        props = body.get("content", {}).get("application/json", {}).get("properties", [])
        if isinstance(props, list):
            for x in props:
                if isinstance(x, dict) and x.get("name"):
                    p[x["name"]] = x.get("value", p.get(x["name"]))
        elif isinstance(props, dict):
            p.update(props)
    return p


def _get_year_filter(params: dict) -> tuple[int | None, int | None]:
    """Resolve year filter from time_range or last_n_months."""
    start = params.get("time_start") or params.get("start_year")
    end = params.get("time_end") or params.get("end_year")
    last_n = params.get("last_n_months")

    if last_n is not None:
        try:
            n = int(last_n)
            if n <= 0:
                return None, None
            from datetime import date
            end_year = date.today().year
            start_year = end_year - (n // 12) - 1
            return max(2000, start_year), end_year
        except (TypeError, ValueError):
            pass

    if start is not None or end is not None:
        try:
            s = int(start) if start else 2000
            e = int(end) if end else datetime.now().year
            return s, e
        except (TypeError, ValueError):
            pass
    return None, None


def handler(params: list[dict], body: dict | None = None) -> dict[str, Any]:
    """
    GetHexMetrics tool handler.
    Input: h3_id, h3_res, optional time_range (time_start, time_end) or last_n_months
    Output: metrics for the hex + trend if multiple years
    """
    p = _parse_params(params or [], body)
    h3_id = validate_h3_id(p.get("h3_id") or p.get("h3Id") or "")
    h3_res = validate_h3_resolution(p.get("h3_res") or p.get("h3Res"))
    year_start, year_end = _get_year_filter(p)

    with db.get_connection() as conn:
        cur = conn.cursor()

        year_clause = ""
        args: list[Any] = [h3_id, h3_res]
        if year_start is not None and year_end is not None:
            year_clause = " AND year BETWEEN %s AND %s"
            args.extend([year_start, year_end])

        q = f"""
            SELECT *
            FROM {SCHEMA}.gbif_cell_metrics
            WHERE h3_index = %s AND h3_resolution = %s
            """ + year_clause + """
            ORDER BY year
        """
        cur.execute(q, args)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]

        result: dict[str, Any] = {
            "h3_id": h3_id,
            "h3_resolution": h3_res,
            "metrics": [],
            "trend": None,
        }

        def _to_json_val(v):
            if v is None:
                return None
            if isinstance(v, float) and v != v:
                return None
            if isinstance(v, (int, str, bool, float)):
                return v
            return str(v)

        for row in rows:
            r = dict(zip(cols, row))
            result["metrics"].append({k: _to_json_val(v) for k, v in r.items()})

        if len(result["metrics"]) >= 2:
            first = result["metrics"][0]
            last = result["metrics"][-1]
            result["trend"] = {
                "species_richness_change": (last.get("species_richness_cell") or 0) - (first.get("species_richness_cell") or 0),
                "threatened_change": (last.get("n_threatened_species") or 0) - (first.get("n_threatened_species") or 0),
                "dqi_change": round(float(last.get("dqi") or 0) - float(first.get("dqi") or 0), 4),
            }

        cur.close()
        return result
