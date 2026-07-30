"""Canonical four-layer runtime capability reporting helpers."""

from __future__ import annotations

from typing import Any

CAPABILITY_KEYS = ("trajectory", "geo", "road", "tcc")


def pending_capability_report() -> tuple[dict[str, None], dict[str, list[str]]]:
    """Return an explicit pre-sample state without guessing from road context."""
    return (
        {key: None for key in CAPABILITY_KEYS},
        {key: ["runtime_sample_pending"] for key in CAPABILITY_KEYS},
    )


def capability_report_from_stats(
    data: dict[str, Any],
    geo_quality: dict[str, Any],
) -> tuple[dict[str, bool], dict[str, list[str]]]:
    """Build independent capability flags/reasons from one canonical stats frame."""
    capabilities = {
        "trajectory": bool(data.get("trajectory_output_eligible", False)),
        "geo": bool(data.get("geo_analytics_eligible", False)),
        "road": bool(data.get("road_analytics_eligible", False)),
        "tcc": bool(data.get("tcc_analytics_eligible", False)),
    }
    general_reasons = list(geo_quality.get("reasons") or [])
    reason_candidates = {
        "trajectory": list(data.get("trajectory_quality_reasons") or []),
        "geo": list(geo_quality.get("geo_reasons") or []),
        "road": list(geo_quality.get("road_reasons") or []),
        "tcc": list(geo_quality.get("tcc_reasons") or []),
    }
    default_reason = {
        "trajectory": "trajectory_not_mature",
        "geo": "geo_quality_unavailable",
        "road": "road_quality_unavailable",
        "tcc": "tcc_quality_unavailable",
    }
    reasons: dict[str, list[str]] = {}
    for key in CAPABILITY_KEYS:
        if capabilities[key]:
            reasons[key] = []
            continue
        candidates = reason_candidates[key]
        if not candidates and key in {"geo", "road", "tcc"}:
            candidates = general_reasons
        reasons[key] = list(dict.fromkeys(candidates or [default_reason[key]]))
    return capabilities, reasons


def capability_report_from_runtime_quality(
    runtime_quality: dict[str, Any] | None,
) -> tuple[dict[str, bool | None], dict[str, list[str]]]:
    """Read a persisted report, retaining an honest pending state before stats."""
    runtime_quality = runtime_quality if isinstance(runtime_quality, dict) else {}
    stored = runtime_quality.get("capabilities")
    if not isinstance(stored, dict) or any(key not in stored for key in CAPABILITY_KEYS):
        return pending_capability_report()
    capabilities = {key: bool(stored[key]) for key in CAPABILITY_KEYS}
    stored_reasons = runtime_quality.get("capability_reasons")
    stored_reasons = stored_reasons if isinstance(stored_reasons, dict) else {}
    reasons = {
        key: list(stored_reasons.get(key) or [])
        for key in CAPABILITY_KEYS
    }
    return capabilities, reasons
