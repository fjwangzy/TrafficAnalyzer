"""Runtime source-georegistration loading independent from road matching."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import numpy as np

from utils_local.runtime_map import select_runtime_visual_registration


def _canonical_checksum(payload: dict) -> str:
    value = {
        "schema_version": "uav.source-geo-registration/v1",
        "source_profile_id": payload.get("source_profile_id"),
        "coordinate_system": payload.get("coordinate_system"),
        "coordinate_transform_version": payload.get(
            "coordinate_transform_version"
        ),
        "anchor_gcj02": payload.get("anchor_gcj02"),
        "homography_pixel_to_enu": payload.get("homography_pixel_to_enu"),
        "registration_pose": payload.get("registration_pose") or {},
        "camera_calibration": payload.get("camera_calibration") or {},
        "coverage_enu_m": (
            payload.get("coverage_enu_m")
            or payload.get("map_coverage_enu_m")
            or {}
        ),
        "residuals": payload.get("residuals") or {},
        "provenance": payload.get("provenance") or {},
    }
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_runtime_geo_registration(
    raw: dict,
    *,
    source_profile_id: str | None = None,
    inherited: dict | None = None,
) -> dict:
    """Validate and freeze one verified source-scoped geographic registration."""

    inherited = inherited or {}
    registration = dict(raw)
    source = registration.get("source_profile_id")
    if source_profile_id and source != source_profile_id:
        raise ValueError(
            f"runtime geo registration source mismatch: {source}@{source_profile_id}"
        )
    if registration.get("status", "verified") != "verified":
        raise ValueError("runtime geo registration must be verified")
    coordinate_system = registration.get("coordinate_system") or inherited.get(
        "coordinate_system"
    )
    if coordinate_system != "GCJ02":
        raise ValueError("runtime geo registration coordinate_system must be GCJ02")
    anchor = registration.get("anchor_gcj02") or inherited.get("anchor_gcj02")
    if not isinstance(anchor, (list, tuple)) or len(anchor) != 2:
        raise ValueError("runtime geo registration anchor_gcj02 is required")
    matrix = np.asarray(
        registration.get("homography_pixel_to_enu"), dtype=np.float64
    )
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        raise ValueError(
            "runtime geo registration homography must be a finite 3x3 matrix"
        )

    coverage = (
        registration.get("coverage_enu_m")
        or registration.get("map_coverage_enu_m")
        or inherited.get("coverage_enu_m")
        or inherited.get("map_coverage_enu_m")
        or {}
    )
    registration.update(
        {
            "source_profile_id": source,
            "status": "verified",
            "coordinate_system": "GCJ02",
            "coordinate_transform_version": (
                registration.get("coordinate_transform_version")
                or inherited.get("coordinate_transform_version")
            ),
            "anchor_gcj02": [float(anchor[0]), float(anchor[1])],
            "homography_pixel_to_enu": matrix.tolist(),
            # ``coverage_enu_m`` is the SourceGeoRegistration v1 contract.
            # Keep the legacy alias while old detector nodes are being retired.
            "coverage_enu_m": coverage,
            "map_coverage_enu_m": coverage,
        }
    )
    registration["checksum"] = registration.get("checksum") or _canonical_checksum(
        registration
    )
    return registration


def load_runtime_geo_registration(
    config: dict | None = None,
    *,
    runtime_map_bundle: dict | None = None,
) -> dict | None:
    """Load an explicit registration or derive it from a legacy map bundle."""

    config = config or {}
    cfg: dict[str, Any] = config.get("geo_reference", {})
    raw: Any = os.environ.get("RUNTIME_GEO_REGISTRATION_JSON") or cfg.get(
        "runtime_geo_registration"
    )
    source_profile_id = os.environ.get("SOURCE_PROFILE_ID")
    if isinstance(raw, str) and raw.strip():
        raw = json.loads(raw)
    if raw:
        return normalize_runtime_geo_registration(
            raw, source_profile_id=source_profile_id
        )

    bundle = runtime_map_bundle
    if not bundle:
        return None
    try:
        legacy = select_runtime_visual_registration(bundle, source_profile_id)
    except ValueError:
        return None
    return normalize_runtime_geo_registration(
        legacy,
        source_profile_id=source_profile_id,
        inherited=bundle,
    )


def runtime_geo_matches_map(registration: dict | None, bundle: dict | None) -> bool:
    if not registration or not bundle:
        return False
    if registration.get("coordinate_system") != bundle.get("coordinate_system"):
        return False
    registration_version = registration.get("coordinate_transform_version")
    map_version = bundle.get("coordinate_transform_version")
    if registration_version and map_version and registration_version != map_version:
        return False
    left = registration.get("anchor_gcj02")
    right = bundle.get("anchor_gcj02")
    if not isinstance(left, (list, tuple)) or not isinstance(right, (list, tuple)):
        return False
    return bool(np.allclose(np.asarray(left, dtype=float), np.asarray(right, dtype=float), atol=1e-8))
