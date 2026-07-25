"""Audit the evidence package required for cruise-tracking production signoff.

The public interface returns facts and named blockers; it never upgrades missing
evidence by inference from predictions or filenames.
"""

from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path
import re
from typing import Any


REQUIRED_MISSION_PHASES = {"entry_cruise", "hover_verified", "exit_cruise"}
REQUIRED_SCENARIOS = {
    "motor",
    "non_motor",
    "dense_traffic",
    "crossing",
    "occlusion",
    "low_confidence_small_target",
}
REQUIRED_CAPTURE_FIELDS = {
    "agl_target_m",
    "ground_speed_target_mps",
    "gimbal_pitch_deg",
    "resolution",
    "fps",
}
REQUIRED_MISSION_LINEAGE_FIELDS = {
    "source_profile_id",
    "map_version_id",
    "runtime_bundle_sha256",
    "model_id",
    "config_sha256",
}
APPROVED_POSITION_TRUTH_SOURCES = {"verified_map_gcp", "rtk_vehicle"}
APPROVED_SPEED_TRUTH_SOURCES = {
    "rtk_vehicle",
    "radar",
    "measured_distance_manual_time",
}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MIN_4K30_FPS = 29.9


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _audit_asset(
    failures: list[str],
    mission_id: str,
    kind: str,
    asset: Any,
    asset_root: Path | None,
) -> None:
    prefix = f"mission_{mission_id}_{kind}"
    if not isinstance(asset, dict):
        failures.append(f"{prefix}_asset_missing")
        return
    relative_path = asset.get("path")
    expected_hash = str(asset.get("sha256") or "").lower()
    if not isinstance(relative_path, str) or not relative_path:
        failures.append(f"{prefix}_path_missing")
    if not SHA256_PATTERN.fullmatch(expected_hash):
        failures.append(f"{prefix}_sha256_invalid")
    if asset_root is None or not isinstance(relative_path, str) or not relative_path:
        return
    root = asset_root.resolve()
    resolved = (root / relative_path).resolve()
    if not resolved.is_relative_to(root):
        failures.append(f"{prefix}_path_outside_asset_root")
        return
    if not resolved.is_file():
        failures.append(f"{prefix}_file_missing")
        return
    if SHA256_PATTERN.fullmatch(expected_hash) and _sha256(resolved) != expected_hash:
        failures.append(f"{prefix}_sha256_mismatch")


def _audit_capture_profile(
    failures: list[str], mission_id: str, capture_profile: Any
) -> None:
    if not isinstance(capture_profile, dict) or not REQUIRED_CAPTURE_FIELDS.issubset(
        capture_profile
    ):
        failures.append(f"mission_{mission_id}_capture_profile_missing")
        return
    try:
        agl_m = float(capture_profile["agl_target_m"])
        speed_mps = float(capture_profile["ground_speed_target_mps"])
        pitch_deg = float(capture_profile["gimbal_pitch_deg"])
        fps = float(capture_profile["fps"])
    except (TypeError, ValueError):
        failures.append(f"mission_{mission_id}_capture_profile_invalid")
        return
    if not 60.0 <= agl_m <= 150.0:
        failures.append(f"mission_{mission_id}_agl_out_of_supported_range")
    if not 0.0 <= speed_mps <= 12.0:
        failures.append(
            f"mission_{mission_id}_ground_speed_out_of_supported_range"
        )
    if pitch_deg > -80.0:
        failures.append(f"mission_{mission_id}_gimbal_pitch_out_of_supported_range")
    resolution = str(capture_profile["resolution"]).lower().replace(" ", "")
    try:
        width, height = (int(value) for value in resolution.split("x", 1))
    except (TypeError, ValueError):
        width = height = 0
    if width < 3840 or height < 2160 or fps < MIN_4K30_FPS:
        failures.append(f"mission_{mission_id}_video_profile_below_4k30")


def audit_cruise_acceptance_package(
    dataset: dict[str, Any], asset_root: Path | None = None
) -> dict[str, Any]:
    """Return production-evidence readiness without calculating accuracy metrics."""

    failures: list[str] = []
    missions = dataset.get("mission_manifest")
    manifest_by_id: dict[str, dict[str, Any]] = {}
    if not isinstance(missions, list) or not missions:
        failures.append("mission_manifest_missing")
        mission_items: list[dict[str, Any]] = []
    else:
        mission_items = [item for item in missions if isinstance(item, dict)]
        manifest_by_id = {
            str(item["mission_id"]): item
            for item in mission_items
            if item.get("mission_id")
        }
        intersection_counts = Counter(
            str(item.get("intersection_id"))
            for item in mission_items
            if item.get("intersection_id")
        )
        if len(intersection_counts) < 3:
            failures.append("manifest_intersections_below_3")
        if not intersection_counts or any(
            count < 2 for count in intersection_counts.values()
        ):
            failures.append("manifest_missions_per_intersection_below_2")
        observed_scenarios: set[str] = set()
        for index, mission in enumerate(mission_items):
            mission_id = str(mission.get("mission_id") or f"index_{index}")
            phases = {str(value) for value in (mission.get("phases") or [])}
            if not REQUIRED_MISSION_PHASES.issubset(phases):
                failures.append(f"mission_{mission_id}_required_phases_missing")
            _audit_capture_profile(
                failures, mission_id, mission.get("capture_profile")
            )
            for field in REQUIRED_MISSION_LINEAGE_FIELDS:
                if not mission.get(field):
                    failures.append(f"mission_{mission_id}_{field}_missing")
            for hash_field in ("runtime_bundle_sha256", "config_sha256"):
                hash_value = str(mission.get(hash_field) or "").lower()
                if hash_value and not SHA256_PATTERN.fullmatch(hash_value):
                    failures.append(
                        f"mission_{mission_id}_{hash_field}_invalid"
                    )
            observed_scenarios.update(
                str(value) for value in (mission.get("scenario_tags") or [])
            )
            _audit_asset(
                failures, mission_id, "video", mission.get("video"), asset_root
            )
            _audit_asset(
                failures,
                mission_id,
                "telemetry",
                mission.get("telemetry"),
                asset_root,
            )
        if not REQUIRED_SCENARIOS.issubset(observed_scenarios):
            failures.append("required_scenarios_missing")

    provenance = dataset.get("ground_truth_provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    for truth_kind in ("identity", "position", "speed"):
        if not isinstance(provenance.get(truth_kind), dict):
            failures.append(f"{truth_kind}_truth_provenance_missing")
    identity_truth = provenance.get("identity")
    if isinstance(identity_truth, dict):
        if identity_truth.get("source") != "manual":
            failures.append("identity_truth_source_not_manual")
        if identity_truth.get("independently_reviewed") is not True:
            failures.append("identity_truth_not_independently_reviewed")
        if not identity_truth.get("reference_id"):
            failures.append("identity_truth_reference_id_missing")
    position_truth = provenance.get("position")
    if isinstance(position_truth, dict) and position_truth.get("source") not in (
        APPROVED_POSITION_TRUTH_SOURCES
    ):
        failures.append("position_truth_source_unapproved")
    if isinstance(position_truth, dict):
        if not position_truth.get("reference_id"):
            failures.append("position_truth_reference_id_missing")
        if position_truth.get("calibration_valid") is not True:
            failures.append("position_truth_calibration_invalid")
    speed_truth = provenance.get("speed")
    if isinstance(speed_truth, dict) and speed_truth.get("source") not in (
        APPROVED_SPEED_TRUTH_SOURCES
    ):
        failures.append("speed_truth_source_unapproved")
    if isinstance(speed_truth, dict):
        if not speed_truth.get("reference_id"):
            failures.append("speed_truth_reference_id_missing")
        if speed_truth.get("calibration_valid") is not True:
            failures.append("speed_truth_calibration_invalid")

    frames = dataset.get("frames")
    frame_items = frames if isinstance(frames, list) else []
    if any(
        not isinstance(frame, dict)
        or frame.get("uav_ground_speed_mps") is None
        for frame in frame_items
    ):
        failures.append("frame_uav_ground_speed_mps_missing")
    if any(
        not isinstance(frame, dict) or frame.get("agl_m") is None
        for frame in frame_items
    ):
        failures.append("frame_agl_m_missing")
    for index, frame in enumerate(frame_items):
        if not isinstance(frame, dict):
            continue
        mission_id = str(frame.get("mission_id") or "")
        mission = manifest_by_id.get(mission_id)
        if mission is None:
            failures.append(f"frame_{index}_mission_not_in_manifest")
            continue
        if str(frame.get("intersection_id") or "") != str(
            mission.get("intersection_id") or ""
        ):
            failures.append(f"frame_{index}_intersection_mismatch")

    return {
        "schema_version": "uav.cruise-acceptance-audit/v1",
        "status": (
            "production_evidence_ready"
            if not failures
            else "production_evidence_blocked"
        ),
        "failures": failures,
        "mission_count": len(mission_items),
        "frame_count": len(frame_items),
    }
