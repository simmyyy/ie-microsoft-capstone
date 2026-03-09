"""
GetTerrainCover: GEE-derived terrain and land cover for an H3 cell.
Reads from gee_hex_terrain (elevation, slope, Copernicus land cover %).
"""
from __future__ import annotations

import logging
from typing import Any

import db
from .validation import validate_h3_id, validate_h3_resolution

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
    return p


def handler(params: list[dict], body: dict | None = None) -> dict[str, Any]:
    """
    GetTerrainCover tool handler.
    Input: h3_id, h3_res
    Output: elevation_mean, slope_mean, land_cover percentages (lc_*_pct)
    """
    p = _parse_params(params or [], body)
    h3_id = validate_h3_id(p.get("h3_id") or p.get("h3Id") or "")
    h3_res = validate_h3_resolution(p.get("h3_res") or p.get("h3Res"))

    with db.get_connection() as conn:
        cur = conn.cursor()

        q = f"""
            SELECT *
            FROM {SCHEMA}.gee_hex_terrain
            WHERE h3_index = %s AND h3_resolution = %s
        """
        cur.execute(q, [h3_id, h3_res])
        row = cur.fetchone()
        cols = [d[0] for d in cur.description] if cur.description else []

        if not row:
            cur.close()
            return {
                "h3_id": h3_id,
                "h3_resolution": h3_res,
                "terrain_cover": None,
                "message": "No terrain/land cover data found for this cell",
            }

        r = dict(zip(cols, row))
        cur.close()

        terrain_cover: dict[str, Any] = {}
        for k, v in r.items():
            if k in ("h3_index", "h3_resolution", "country", "snapshot"):
                continue
            if v is None:
                terrain_cover[k] = None
            elif isinstance(v, (int, str, bool)):
                terrain_cover[k] = v
            elif isinstance(v, float):
                terrain_cover[k] = v if v == v else None  # NaN -> None
            else:
                terrain_cover[k] = str(v)

        return {
            "h3_id": h3_id,
            "h3_resolution": h3_res,
            "terrain_cover": terrain_cover,
        }
