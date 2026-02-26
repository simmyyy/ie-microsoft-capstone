"""
GetHexSpeciesContext: Top species, threatened, and invasive for an H3 cell.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import db
from .validation import validate_h3_id, validate_h3_resolution, validate_year

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
    GetHexSpeciesContext tool handler.
    Input: h3_id, h3_res, optional year
    Output: all species (by occurrence), threatened list, invasive list – no limits
    """
    p = _parse_params(params or [], body)
    h3_id = validate_h3_id(p.get("h3_id") or p.get("h3Id") or "")
    h3_res = validate_h3_resolution(p.get("h3_res") or p.get("h3Res"))
    year = validate_year(p.get("year"))

    with db.get_connection() as conn:
        cur = conn.cursor()

        if year is None:
            cur.execute(
                f"SELECT MAX(year) FROM {SCHEMA}.gbif_species_h3_mapping "
                "WHERE h3_index = %s AND h3_resolution = %s",
                [h3_id, h3_res],
            )
            row = cur.fetchone()
            year = row[0] if row and row[0] else None
            if year is None:
                cur.execute(f"SELECT MAX(year) FROM {SCHEMA}.gbif_species_h3_mapping")
                row = cur.fetchone()
                year = row[0] if row and row[0] else None

        year_clause = "AND m.year = %s" if year else ""
        args: list[Any] = [h3_id, h3_res]
        if year:
            args.append(year)

        q = f"""
            SELECT m.*, COALESCE(d.species_name, 'Unknown') AS species_name
            FROM {SCHEMA}.gbif_species_h3_mapping m
            LEFT JOIN {SCHEMA}.gbif_species_dim d
              ON d.taxon_key = m.taxon_key AND d.country = m.country AND d.year = m.year
            WHERE m.h3_index = %s AND m.h3_resolution = %s {year_clause}
            ORDER BY m.occurrence_count DESC
        """
        cur.execute(q, args)

        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        all_species = [dict(zip(cols, r)) for r in rows]

        top_species = []
        threatened = []
        invasive = []
        seen = set()

        def _to_json_val(v):
            if v is None:
                return None
            if isinstance(v, float) and v != v:
                return None
            if isinstance(v, (int, str, bool, float)):
                return v
            return str(v)

        for s in all_species:
            key = s.get("taxon_key")
            if key in seen:
                continue
            seen.add(key)
            entry = {k: _to_json_val(v) for k, v in s.items()}
            entry["is_threatened"] = bool(s.get("is_threatened"))
            entry["is_invasive"] = bool(s.get("is_invasive"))
            top_species.append(entry)
            if s.get("is_threatened"):
                threatened.append(entry)
            if s.get("is_invasive"):
                invasive.append(entry)

        cur.close()
        return {
            "h3_id": h3_id,
            "h3_resolution": h3_res,
            "year": year,
            "top_species": top_species,
            "threatened_species": threatened,
            "invasive_species": invasive,
        }
