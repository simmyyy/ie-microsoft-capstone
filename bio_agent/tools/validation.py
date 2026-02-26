"""
Input validation for biodiversity agent tools.
"""
from __future__ import annotations

import re
from typing import Any

import h3


def validate_h3_id(h3_id: str) -> str:
    """Validate H3 cell ID format."""
    if not h3_id or not isinstance(h3_id, str):
        raise ValueError("h3_id must be a non-empty string")
    h3_id = str(h3_id).strip()
    if not re.match(r"^[0-9a-fA-F]{8,15}$", h3_id):
        raise ValueError(f"Invalid H3 ID format: {h3_id}")
    try:
        h3.get_resolution(h3_id)
    except Exception as e:
        raise ValueError(f"Invalid H3 ID format: {h3_id}") from e
    return h3_id


def validate_h3_resolution(res: Any) -> int:
    """Validate H3 resolution (6-9)."""
    try:
        r = int(res) if res is not None else 7
    except (TypeError, ValueError):
        raise ValueError("h3_res must be an integer")
    if not 6 <= r <= 9:
        raise ValueError("h3_res must be between 6 and 9")
    return r


def validate_k_ring(k: Any) -> int:
    """Validate k_ring (1-3)."""
    try:
        k_val = int(k) if k is not None else 1
    except (TypeError, ValueError):
        raise ValueError("k_ring must be an integer")
    if not 1 <= k_val <= 3:
        raise ValueError("k_ring must be between 1 and 3")
    return k_val


def validate_top_k(top_k: Any) -> int:
    """Validate top_k (1-50)."""
    try:
        t = int(top_k) if top_k is not None else 10
    except (TypeError, ValueError):
        raise ValueError("top_k must be an integer")
    if not 1 <= t <= 50:
        raise ValueError("top_k must be between 1 and 50")
    return t


def validate_year(year: Any) -> int | None:
    """Validate year (2000-2100)."""
    if year is None:
        return None
    try:
        y = int(year)
    except (TypeError, ValueError):
        raise ValueError("year must be an integer")
    if not 2000 <= y <= 2100:
        raise ValueError("year must be between 2000 and 2100")
    return y


def validate_last_n_months(n: Any) -> int | None:
    """Validate last_n_months (1-60)."""
    if n is None:
        return None
    try:
        m = int(n)
    except (TypeError, ValueError):
        raise ValueError("last_n_months must be an integer")
    if not 1 <= m <= 60:
        raise ValueError("last_n_months must be between 1 and 60")
    return m


def validate_species_list(ids_or_names: Any) -> list[str]:
    """Validate list of species IDs or names."""
    if ids_or_names is None:
        return []
    if isinstance(ids_or_names, str):
        ids_or_names = [ids_or_names]
    if not isinstance(ids_or_names, list):
        raise ValueError("species_ids_or_names must be a list or string")
    out = []
    for x in ids_or_names:
        s = str(x).strip()
        if s:
            out.append(s)
    if not out:
        raise ValueError("At least one species ID or name required")
    if len(out) > 20:
        raise ValueError("Maximum 20 species per request")
    return out


def validate_h3_id_list(h3_ids: Any) -> list[str]:
    """Validate list of H3 IDs."""
    if h3_ids is None:
        return []
    if isinstance(h3_ids, str):
        h3_ids = [h3_ids]
    if not isinstance(h3_ids, list):
        raise ValueError("h3_ids must be a list or string")
    out = []
    for h in h3_ids:
        s = str(h).strip()
        if s:
            try:
                validate_h3_id(s)
                out.append(s)
            except ValueError:
                pass  # skip invalid
    if len(out) > 100:
        raise ValueError("Maximum 100 H3 cells per request")
    return out
