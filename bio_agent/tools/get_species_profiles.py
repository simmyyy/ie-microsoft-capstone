"""
GetSpeciesProfiles: Profile text + sources for species (for agent narrative).
"""
from __future__ import annotations

import logging
from typing import Any

import db
from .validation import validate_species_list

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
    ids_raw = p.get("species_ids") or p.get("species_names") or p.get("speciesIds") or p.get("speciesNames")
    if isinstance(ids_raw, str):
        try:
            import json
            p["species_ids_or_names"] = json.loads(ids_raw)
        except json.JSONDecodeError:
            p["species_ids_or_names"] = [x.strip() for x in ids_raw.split(",") if x.strip()]
    else:
        p["species_ids_or_names"] = ids_raw
    return p


def handler(params: list[dict], body: dict | None = None) -> dict[str, Any]:
    """
    GetSpeciesProfiles tool handler.
    Input: species_ids (taxon_key) OR species_names (scientific name)
    Output: profile_text + sources for each species
    """
    p = _parse_params(params or [], body)
    ids_or_names = validate_species_list(p.get("species_ids_or_names"))

    if not ids_or_names:
        return {
            "profiles": [],
            "message": "At least one species ID or name required",
        }

    with db.get_connection() as conn:
        cur = conn.cursor()

        # Try by taxon_key first (numeric)
        numeric = []
        names = []
        for x in ids_or_names:
            try:
                int(x)
                numeric.append(x)
            except ValueError:
                names.append(x)

        profiles = []

        def _to_json_val(v):
            if v is None:
                return None
            if isinstance(v, float) and v != v:
                return None
            if isinstance(v, (int, str, bool, float)):
                return v
            return str(v)

        if numeric:
            placeholders = ", ".join(["%s"] * len(numeric))
            cur.execute(
                f"""
                SELECT DISTINCT ON (d.taxon_key) d.*
                FROM {SCHEMA}.gbif_species_dim d
                WHERE d.taxon_key::text IN ({placeholders})
                ORDER BY d.taxon_key, d.occurrence_count DESC NULLS LAST
                """,
                numeric,
            )
            cols = [d[0] for d in cur.description]
            for row in cur.fetchall():
                r = dict(zip(cols, row))
                r["source"] = "gbif_species_dim"
                r["is_threatened"] = bool(r.get("is_threatened"))
                r["is_invasive"] = bool(r.get("is_invasive"))
                profiles.append({k: _to_json_val(v) for k, v in r.items()})

        if names:
            for name in names:
                cur.execute(
                    f"""
                    SELECT *
                    FROM {SCHEMA}.iucn_species_profiles
                    WHERE LOWER(scientific_name) = LOWER(%s)
                    """,
                    [name],
                )
                row = cur.fetchone()
                if row:
                    cols = [d[0] for d in cur.description]
                    r = dict(zip(cols, row))
                    r["source"] = "iucn_species_profiles"
                    profiles.append({k: _to_json_val(v) for k, v in r.items()})
                else:
                    cur.execute(
                        f"""
                        SELECT *
                        FROM {SCHEMA}.gbif_species_dim
                        WHERE LOWER(species_name) LIKE LOWER(%s)
                        ORDER BY occurrence_count DESC NULLS LAST
                        """,
                        [f"%{name}%"],
                    )
                    rows = cur.fetchall()
                    if rows:
                        cols = [d[0] for d in cur.description]
                        for row in rows:
                            r = dict(zip(cols, row))
                            r["source"] = "gbif_species_dim"
                            r["is_threatened"] = bool(r.get("is_threatened"))
                            r["is_invasive"] = bool(r.get("is_invasive"))
                            profiles.append({k: _to_json_val(v) for k, v in r.items()})
                    else:
                        profiles.append({
                            "requested": name,
                            "found": False,
                            "message": "Species not found in database",
                        })

        cur.close()

        # Build profile_text for agent narrative
        for p in profiles:
            if p.get("found") is False:
                continue
            parts = []
            if p.get("species_name"):
                parts.append(f"Species: {p['species_name']}")
            if p.get("iucn_category"):
                parts.append(f"IUCN: {p['iucn_category']}")
            if p.get("rationale"):
                parts.append(f"Rationale: {p['rationale']}")
            if p.get("habitat_ecology"):
                parts.append(f"Habitat: {p['habitat_ecology']}")
            if p.get("threats_text"):
                parts.append(f"Threats: {p['threats_text']}")
            if p.get("conservation_text"):
                parts.append(f"Conservation: {p['conservation_text']}")
            if p.get("occurrence_count") is not None:
                parts.append(f"Occurrences: {p['occurrence_count']}")
            p["profile_text"] = "\n".join(parts) if parts else "No profile available"

        return {
            "profiles": profiles,
            "count": len(profiles),
        }
