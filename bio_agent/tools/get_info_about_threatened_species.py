"""
GetInfoAboutThreatenedSpecies: IUCN info for threatened species in a hex or list.
"""
from __future__ import annotations

import logging
from typing import Any

import db
from .validation import validate_h3_id, validate_h3_resolution, validate_species_list, validate_year

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
    return p


def handler(params: list[dict], body: dict | None = None) -> dict[str, Any]:
    """
    GetInfoAboutThreatenedSpecies tool handler.
    Input: h3_id + h3_res (to get threatened species from hex) OR species_ids/names
    Output: IUCN info (rationale, habitat, threats, conservation) for each
    """
    p = _parse_params(params or [], body)
    h3_id = p.get("h3_id") or p.get("h3Id")
    h3_res = p.get("h3_res") or p.get("h3Res")
    species_ids_or_names = p.get("species_ids_or_names") or p.get("speciesIdsOrNames")

    species_names: list[str] = []

    if species_ids_or_names:
        try:
            if isinstance(species_ids_or_names, str):
                import json
                try:
                    species_names = json.loads(species_ids_or_names)
                except json.JSONDecodeError:
                    species_names = [s.strip() for s in species_ids_or_names.split(",") if s.strip()]
            else:
                species_names = [str(x).strip() for x in species_ids_or_names if str(x).strip()]
        except Exception:
            species_names = []
    elif h3_id and h3_res:
        h3_id = validate_h3_id(h3_id)
        h3_res = validate_h3_resolution(h3_res)
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT DISTINCT d.species_name
                FROM {SCHEMA}.gbif_species_h3_mapping m
                JOIN {SCHEMA}.gbif_species_dim d ON d.taxon_key = m.taxon_key AND d.country = m.country AND d.year = m.year
                WHERE m.h3_index = %s AND m.h3_resolution = %s AND m.is_threatened = true
                """,
                [h3_id, h3_res],
            )
            species_names = [r[0] for r in cur.fetchall() if r[0]]
            cur.close()
    else:
        return {
            "threatened_species_info": [],
            "message": "Provide either h3_id+h3_res or species_ids_or_names",
        }

    if not species_names:
        return {
            "threatened_species_info": [],
            "message": "No threatened species found",
        }

    with db.get_connection() as conn:
        cur = conn.cursor()
        placeholders = ", ".join(["%s"] * len(species_names))

        names_lower = [n.lower() for n in species_names]
        placeholders = ", ".join(["%s"] * len(names_lower))
        q = f"""
            SELECT *
            FROM {SCHEMA}.iucn_species_profiles
            WHERE LOWER(scientific_name) IN ({placeholders})
        """
        cur.execute(q, names_lower)
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

        result = []
        for row in rows:
            result.append({k: _to_json_val(v) for k, v in dict(zip(cols, row)).items()})

        cur.close()
        return {
            "threatened_species_info": result,
            "count": len(result),
        }
