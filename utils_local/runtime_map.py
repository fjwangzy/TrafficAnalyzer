"""Runtime helpers for one immutable lane-verified road-map bundle."""

from __future__ import annotations

import json
import os
from typing import Any

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
