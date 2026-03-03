"""
Standalone worker for ProcessPoolExecutor – downloads GBIF images for one species.
Must be a separate module so it can be pickled for multiprocessing.
"""

import random
import time
from io import BytesIO
from pathlib import Path

import numpy as np
import requests
from PIL import Image


def _sharpness(img: Image.Image) -> float:
    g = np.array(img.convert("L"), dtype=np.float32)
    lap = (
        np.roll(g, -1, axis=0) + np.roll(g, 1, axis=0)
        + np.roll(g, -1, axis=1) + np.roll(g, 1, axis=1)
        - 4.0 * g
    )
    return float(lap.var())


def _image_quality_ok(
    img: Image.Image,
    min_side_px: int,
    max_aspect: float,
    sharpness_min: float,
) -> tuple[bool, str]:
    if min(img.size) < min_side_px:
        return False, f"too_small ({min(img.size)}px)"
    w, h = img.size
    ratio = max(w, h) / max(min(w, h), 1)
    if ratio > max_aspect:
        return False, f"bad_aspect ({w}x{h})"
    sharp = _sharpness(img)
    if sharp < sharpness_min:
        return False, f"blurry (sharpness={sharp:.1f}<{sharpness_min})"
    return True, "ok"


def _download_image(
    url: str,
    save_path: Path,
    timeout: int,
    min_side_px: int,
    max_aspect: float,
    sharpness_min: float,
) -> tuple[bool, str]:
    try:
        resp = requests.get(url, timeout=timeout, stream=True)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "image" not in content_type and not url.lower().endswith(
            (".jpg", ".jpeg", ".png", ".webp", ".gif")
        ):
            return False, "not_image"
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        ok, reason = _image_quality_ok(img, min_side_px, max_aspect, sharpness_min)
        if not ok:
            return False, reason
        img.save(save_path, format="JPEG", quality=85, optimize=True)
        return True, "ok"
    except Exception as e:
        return False, f"error:{type(e).__name__}"


def _collect_urls(
    taxon_key: int,
    max_urls: int,
    gbif_page_size: int,
    request_delay: float,
    timeout: int,
) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    offset = 0
    while len(urls) < max_urls:
        params = {
            "taxonKey": taxon_key,
            "mediaType": "StillImage",
            "basisOfRecord": "HUMAN_OBSERVATION",
            "occurrenceStatus": "PRESENT",
            "limit": gbif_page_size,
            "offset": offset,
        }
        try:
            resp = requests.get(
                "https://api.gbif.org/v1/occurrence/search",
                params=params,
                timeout=timeout,
            )
            resp.raise_for_status()
        except requests.RequestException:
            break
        data = resp.json()
        results = data.get("results", [])
        if not results:
            break
        for occ in results:
            for media in occ.get("media", []):
                if media.get("type") != "StillImage":
                    continue
                url = (media.get("identifier") or "").strip()
                if url and url not in seen:
                    seen.add(url)
                    urls.append(url)
                    if len(urls) >= max_urls:
                        break
            if len(urls) >= max_urls:
                break
        if data.get("endOfRecords", False):
            break
        offset += gbif_page_size
        time.sleep(request_delay)
    return urls


def download_species_worker(args: tuple) -> tuple[str, Path, int, dict]:
    """
    Worker for ProcessPoolExecutor. Downloads images for one species.
    Args: (class_name, taxon_key, target, data_dir, config, progress_dict=None)
    progress_dict: optional Manager().dict() - updated every 20 downloads for live progress
    Returns: (class_name, out_dir, downloaded_count, rejected_dict)
    """
    if len(args) == 6:
        class_name, taxon_key, target, data_dir, config, progress_dict = args
    else:
        class_name, taxon_key, target, data_dir, config = args
        progress_dict = None
    data_dir = Path(data_dir)
    keys = [taxon_key] if isinstance(taxon_key, int) else taxon_key
    out_dir = data_dir / "raw" / class_name
    out_dir.mkdir(parents=True, exist_ok=True)

    existing = list(out_dir.glob("*.jpg"))
    already = len(existing)
    if already >= target:
        if progress_dict is not None:
            progress_dict[class_name] = already
        return (class_name, out_dir, 0, {"skipped": already})

    still_needed = target - already
    max_urls = (still_needed * 4) // len(keys)
    urls = []
    for tk in keys:
        urls.extend(
            _collect_urls(
                tk,
                max_urls,
                config["gbif_page_size"],
                config["request_delay"],
                config["timeout"],
            )
        )
        if len(urls) >= still_needed * 4:
            break
    random.shuffle(urls)

    if progress_dict is not None:
        progress_dict[class_name] = already
    downloaded = 0
    rejected: dict[str, int] = {}
    idx = already
    min_side = config["min_side_px"]
    max_aspect = config["max_aspect"]
    sharpness_min = config["sharpness_min"]
    timeout = config["timeout"]

    for url in urls:
        if downloaded >= still_needed:
            break
        fname = out_dir / f"{idx:05d}.jpg"
        ok, reason = _download_image(
            url, fname, timeout, min_side, max_aspect, sharpness_min
        )
        if ok:
            downloaded += 1
            idx += 1
            if progress_dict is not None and downloaded % 20 == 0:
                progress_dict[class_name] = already + downloaded
        else:
            rejected[reason] = rejected.get(reason, 0) + 1
        time.sleep(0.02)

    if progress_dict is not None:
        progress_dict[class_name] = already + downloaded
    return (class_name, out_dir, downloaded, rejected)
