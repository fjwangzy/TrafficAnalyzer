"""Runtime helpers for one immutable lane-verified road-map bundle."""

from __future__ import annotations

import json
import os
from typing import Any

import numpy as np


def load_runtime_map_bundle(config: dict | None = None) -> dict | None:
    """Load and validate the canonical runtime map from env or node config."""
    cfg = (config or {}).get("road_map_matching", {})
    raw: Any = os.environ.get("RUNTIME_MAP_BUNDLE_JSON") or cfg.get(
        "runtime_map_bundle"
    )
    bundle = json.loads(raw) if isinstance(raw, str) and raw.strip() else (raw or None)
    if bundle is None:
        return None
    if bundle.get("map_status") != "lane_verified":
        raise ValueError("runtime road map must be lane_verified")
    if bundle.get("coordinate_system") != "GCJ02":
        raise ValueError("runtime road map coordinate_system must be GCJ02")
    anchor = bundle.get("anchor_gcj02")
    if not isinstance(anchor, (list, tuple)) or len(anchor) != 2:
        raise ValueError("runtime road map anchor_gcj02 must be [longitude, latitude]")
    return bundle


def select_runtime_visual_registration(
    bundle: dict,
    source_profile_id: str | None = None,
) -> dict:
    """Select the exact verified registration for an opaque source profile id."""
    source_profile_id = source_profile_id or os.environ.get("SOURCE_PROFILE_ID")
    registrations = bundle.get("visual_registrations") or []
    if source_profile_id:
        registration = next(
            (
                item
                for item in registrations
                if item.get("source_profile_id") == source_profile_id
                and item.get("status", "verified") == "verified"
            ),
            None,
        )
        if registration is None:
            fallback = bundle.get("visual_registration") or {}
            if (
                not registrations
                and fallback.get("source_profile_id") == source_profile_id
                and fallback.get("status", "verified") == "verified"
            ):
                registration = fallback
        if registration is None:
            raise ValueError(
                f"verified visual registration is missing for source {source_profile_id}"
            )
    else:
        registration = bundle.get("visual_registration") or (
            registrations[0] if len(registrations) == 1 else None
        )
        if not registration:
            raise ValueError("runtime road map has no unambiguous visual registration")

    matrix = np.asarray(registration.get("homography_pixel_to_enu"), dtype=np.float64)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        raise ValueError("runtime visual registration homography must be a finite 3x3 matrix")
    return registration


def runtime_registration_homography(registration: dict) -> np.ndarray:
    return np.asarray(registration["homography_pixel_to_enu"], dtype=np.float64)

