"""
GetNeighborHexes: Return k-ring neighbors for an H3 cell.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import h3

from .validation import validate_h3_id, validate_h3_resolution, validate_k_ring

logger = logging.getLogger(__name__)


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
    GetNeighborHexes tool handler.
    Input: h3_id, h3_res, k_ring (default 1, max 3)
    Output: list of neighbor h3_ids + neighbor_set_id for caching
    """
    p = _parse_params(params or [], body)
    h3_id = validate_h3_id(p.get("h3_id") or p.get("h3Id") or "")
    h3_res = validate_h3_resolution(p.get("h3_res") or p.get("h3Res"))
    k = validate_k_ring(p.get("k_ring") or p.get("kRing"))

    # Ensure we have the right resolution cell
    try:
        res_actual = h3.get_resolution(h3_id)
        if res_actual != h3_res:
            parent = h3.cell_to_parent(h3_id, h3_res)
            h3_id = parent
    except Exception:
        pass

    ring = h3.grid_disk(h3_id, k)
    neighbors = sorted(list(set(ring) - {h3_id}))

    # neighbor_set_id: deterministic hash for caching
    payload = f"{h3_id}:{h3_res}:{k}"
    neighbor_set_id = hashlib.sha256(payload.encode()).hexdigest()[:16]

    return {
        "h3_id": h3_id,
        "h3_resolution": h3_res,
        "k_ring": k,
        "neighbor_count": len(neighbors),
        "neighbor_h3_ids": neighbors,
        "neighbor_set_id": neighbor_set_id,
    }
