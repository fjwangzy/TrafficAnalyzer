import subprocess
import sys
import json
from pathlib import Path

from utils_local.cruise_evaluation import evaluate_cruise_dataset
from utils_local.cruise_acceptance_package import audit_cruise_acceptance_package


def _perfect_dataset():
    frames = []
    for frame_index in range(3):
        frames.append({
            "mission_id": "M-1",
            "intersection_id": "I-1",
            "timestamp_sec": frame_index * 0.1,
            "agl_m": 90.0,
            "ground_truth": [
                {"track_id": "G-1", "enu_m": [frame_index, 0], "speed_kmh": 18, "lane_id": "L-1"},
                {"track_id": "G-2", "enu_m": [frame_index, 10], "speed_kmh": 36, "lane_id": "L-2"},
            ],
            "predictions": [
                {"track_id": "P-1", "enu_m": [frame_index, 0], "speed_kmh": 18, "lane_id": "L-1", "quality_status": "verified", "formal_analytics_eligible": True},
                {"track_id": "P-2", "enu_m": [frame_index, 10], "speed_kmh": 36, "lane_id": "L-2", "quality_status": "verified", "formal_analytics_eligible": True},
            ],
        })
    return {"schema_version": "uav.cruise-eval/v1", "frames": frames}


def test_perfect_tracking_has_perfect_metrics_but_incomplete_dataset_gate():
    report = evaluate_cruise_dataset(_perfect_dataset())

    assert report["metrics"]["idf1"] == 1.0
    assert report["metrics"]["hota"] == 1.0
    assert report["metrics"]["position_rmse_m"] == 0.0
    assert report["metrics"]["speed_mae_kmh"] == 0.0
    assert report["metrics"]["lane_accuracy"] == 1.0
    assert report["metrics"]["quality_leak_count"] == 0
    assert report["gate"]["status"] == "production_signoff_blocked"
    assert "dataset_intersections_below_3" in report["gate"]["failures"]


def test_id_switch_and_degraded_formal_leak_are_counted():
    dataset = _perfect_dataset()
    dataset["frames"][2]["predictions"][0]["track_id"] = "P-3"
    dataset["frames"][1]["predictions"][1]["quality_status"] = "degraded"
    dataset["frames"][1]["predictions"][1]["formal_analytics_eligible"] = True

    report = evaluate_cruise_dataset(dataset)

    assert report["metrics"]["idf1"] < 1.0
    assert report["metrics"]["id_switches"] == 1
    assert report["metrics"]["quality_leak_count"] == 1
    assert "degraded_formal_leak_nonzero" in report["gate"]["failures"]


def test_evaluator_cli_is_runnable_from_repository_root():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/evaluate_cruise_tracking.py", "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "uav.cruise-eval/v1" in result.stdout


def test_package_audit_names_missing_manifest_and_truth_provenance():
    audit = audit_cruise_acceptance_package(_perfect_dataset())

    assert audit["status"] == "production_evidence_blocked"
    assert "mission_manifest_missing" in audit["failures"]
    assert "identity_truth_provenance_missing" in audit["failures"]
    assert "position_truth_provenance_missing" in audit["failures"]
    assert "speed_truth_provenance_missing" in audit["failures"]


def test_package_audit_requires_three_intersections_two_complete_missions_each():
    dataset = _perfect_dataset()
    dataset["mission_manifest"] = [
        {
            "mission_id": "M-1",
            "intersection_id": "I-1",
            "phases": ["entry_cruise", "hover_verified"],
        }
    ]
    dataset["ground_truth_provenance"] = {
        "identity": {"source": "manual"},
        "position": {"source": "rtk_vehicle"},
        "speed": {"source": "radar"},
    }

    audit = audit_cruise_acceptance_package(dataset)

    assert "manifest_intersections_below_3" in audit["failures"]
    assert "manifest_missions_per_intersection_below_2" in audit["failures"]
    assert "mission_M-1_required_phases_missing" in audit["failures"]


def test_package_audit_requires_capture_profiles_and_scenario_coverage():
    dataset = _perfect_dataset()
    dataset["mission_manifest"] = [
        {
            "mission_id": f"M-{intersection}-{repeat}",
            "intersection_id": f"I-{intersection}",
            "phases": ["entry_cruise", "hover_verified", "exit_cruise"],
        }
        for intersection in range(1, 4)
        for repeat in range(1, 3)
    ]
    dataset["ground_truth_provenance"] = {
        "identity": {"source": "manual"},
        "position": {"source": "rtk_vehicle"},
        "speed": {"source": "radar"},
    }

    audit = audit_cruise_acceptance_package(dataset)

    assert "required_scenarios_missing" in audit["failures"]
    assert "mission_M-1-1_capture_profile_missing" in audit["failures"]


def test_package_audit_rejects_unreviewed_or_unverifiable_truth_sources():
    dataset = _perfect_dataset()
    dataset["ground_truth_provenance"] = {
        "identity": {"source": "model_prediction", "independently_reviewed": False},
        "position": {"source": "current_frame_h_reprojection"},
        "speed": {"source": "video_prediction", "calibration_valid": False},
    }

    audit = audit_cruise_acceptance_package(dataset)

    assert "identity_truth_not_independently_reviewed" in audit["failures"]
    assert "identity_truth_source_not_manual" in audit["failures"]
    assert "position_truth_source_unapproved" in audit["failures"]
    assert "speed_truth_source_unapproved" in audit["failures"]


def test_package_audit_requires_traceable_calibrated_truth_references():
    dataset = _perfect_dataset()
    dataset["ground_truth_provenance"] = {
        "identity": {
            "source": "manual",
            "independently_reviewed": True,
        },
        "position": {
            "source": "rtk_vehicle",
            "reference_id": "RTK-RUN-001",
            "calibration_valid": False,
        },
        "speed": {
            "source": "radar",
            "calibration_valid": True,
        },
    }

    audit = audit_cruise_acceptance_package(dataset)

    assert "identity_truth_reference_id_missing" in audit["failures"]
    assert "position_truth_calibration_invalid" in audit["failures"]
    assert "speed_truth_reference_id_missing" in audit["failures"]


def test_package_audit_verifies_video_and_telemetry_content_hashes(tmp_path):
    (tmp_path / "mission.mp4").write_bytes(b"video-evidence")
    (tmp_path / "mission.srt").write_bytes(b"telemetry-evidence")
    dataset = _perfect_dataset()
    dataset["mission_manifest"] = [
        {
            "mission_id": "M-1",
            "intersection_id": "I-1",
            "phases": ["entry_cruise", "hover_verified", "exit_cruise"],
            "capture_profile": {
                "agl_target_m": 100,
                "ground_speed_target_mps": 5,
                "gimbal_pitch_deg": -90,
                "resolution": "3840x2160",
                "fps": 30,
            },
            "video": {"path": "mission.mp4", "sha256": "0" * 64},
            "telemetry": {"path": "mission.srt", "sha256": "1" * 64},
        }
    ]

    audit = audit_cruise_acceptance_package(dataset, asset_root=tmp_path)

    assert "mission_M-1_video_sha256_mismatch" in audit["failures"]
    assert "mission_M-1_telemetry_sha256_mismatch" in audit["failures"]


def test_package_audit_rejects_capture_profile_outside_supported_envelope():
    dataset = _perfect_dataset()
    dataset["mission_manifest"] = [
        {
            "mission_id": "M-1",
            "intersection_id": "I-1",
            "phases": ["entry_cruise", "hover_verified", "exit_cruise"],
            "capture_profile": {
                "agl_target_m": 155,
                "ground_speed_target_mps": 13,
                "gimbal_pitch_deg": -75,
                "resolution": "1920x1080",
                "fps": 25,
            },
        }
    ]

    audit = audit_cruise_acceptance_package(dataset)

    assert "mission_M-1_agl_out_of_supported_range" in audit["failures"]
    assert "mission_M-1_ground_speed_out_of_supported_range" in audit["failures"]
    assert "mission_M-1_gimbal_pitch_out_of_supported_range" in audit["failures"]
    assert "mission_M-1_video_profile_below_4k30" in audit["failures"]


def test_package_audit_accepts_standard_2997fps_as_4k30_profile():
    dataset = _perfect_dataset()
    dataset["mission_manifest"] = [
        {
            "mission_id": "M-1",
            "intersection_id": "I-1",
            "phases": ["entry_cruise", "hover_verified", "exit_cruise"],
            "capture_profile": {
                "agl_target_m": 130,
                "ground_speed_target_mps": 5,
                "gimbal_pitch_deg": -90,
                "resolution": "3840x2160",
                "fps": 29.97,
            },
        }
    ]

    audit = audit_cruise_acceptance_package(dataset)

    assert "mission_M-1_video_profile_below_4k30" not in audit["failures"]


def test_metric_report_merges_evidence_audit_blockers():
    report = evaluate_cruise_dataset(_perfect_dataset())

    assert report["evidence_audit"]["status"] == "production_evidence_blocked"
    assert "mission_manifest_missing" in report["gate"]["failures"]


def test_evaluator_cli_can_audit_capture_package_before_annotations(tmp_path):
    dataset_path = tmp_path / "capture-package.json"
    dataset_path.write_text(
        json.dumps({"schema_version": "uav.cruise-eval/v1"}),
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [
            sys.executable,
            "scripts/evaluate_cruise_tracking.py",
            str(dataset_path),
            "--audit-only",
            "--allow-gate-failure",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["schema_version"] == "uav.cruise-acceptance-audit/v1"
    assert report["status"] == "production_evidence_blocked"


def test_speed_band_uses_uav_ground_speed_not_vehicle_speed():
    dataset = _perfect_dataset()
    for frame, uav_speed_mps in zip(dataset["frames"], (5.0, 5.0, 7.0)):
        frame["uav_ground_speed_mps"] = uav_speed_mps
        frame["ground_truth"] = [
            {"track_id": "G-1", "enu_m": [frame["timestamp_sec"], 0], "speed_kmh": 36.0}
        ]
        frame["predictions"] = [
            {"track_id": "P-1", "enu_m": [frame["timestamp_sec"], 0], "speed_kmh": 36.0}
        ]

    report = evaluate_cruise_dataset(dataset)

    assert report["dataset"]["speed_band_tracks"]["3-6"] == 1
    assert report["dataset"]["speed_band_tracks"].get("9-12", 0) == 0


def test_package_audit_blocks_frames_without_uav_speed_stratum():
    audit = audit_cruise_acceptance_package(_perfect_dataset())

    assert "frame_uav_ground_speed_mps_missing" in audit["failures"]


def test_package_audit_blocks_frames_without_agl_stratum():
    dataset = _perfect_dataset()
    dataset["frames"][1]["agl_m"] = None
    for frame in dataset["frames"]:
        frame["uav_ground_speed_mps"] = 5.0

    audit = audit_cruise_acceptance_package(dataset)

    assert "frame_agl_m_missing" in audit["failures"]


def test_package_audit_cross_checks_frame_mission_and_intersection_lineage():
    dataset = _perfect_dataset()
    dataset["mission_manifest"] = [
        {
            "mission_id": "M-1",
            "intersection_id": "I-1",
            "phases": ["entry_cruise", "hover_verified", "exit_cruise"],
        }
    ]
    dataset["frames"][0]["mission_id"] = "M-UNKNOWN"
    dataset["frames"][1]["intersection_id"] = "I-WRONG"
    for frame in dataset["frames"]:
        frame["uav_ground_speed_mps"] = 5.0

    audit = audit_cruise_acceptance_package(dataset)

    assert "frame_0_mission_not_in_manifest" in audit["failures"]
    assert "frame_1_intersection_mismatch" in audit["failures"]


def test_package_audit_requires_runtime_and_model_lineage_per_mission():
    dataset = _perfect_dataset()
    dataset["mission_manifest"] = [
        {
            "mission_id": "M-1",
            "intersection_id": "I-1",
            "phases": ["entry_cruise", "hover_verified", "exit_cruise"],
            "capture_profile": {
                "agl_target_m": 100,
                "ground_speed_target_mps": 5,
                "gimbal_pitch_deg": -90,
                "resolution": "3840x2160",
                "fps": 30,
            },
            "video": {"path": "mission.mp4", "sha256": "0" * 64},
            "telemetry": {"path": "mission.srt", "sha256": "1" * 64},
        }
    ]

    audit = audit_cruise_acceptance_package(dataset)

    assert "mission_M-1_source_profile_id_missing" in audit["failures"]
    assert "mission_M-1_map_version_id_missing" in audit["failures"]
    assert "mission_M-1_runtime_bundle_sha256_missing" in audit["failures"]
    assert "mission_M-1_model_id_missing" in audit["failures"]
    assert "mission_M-1_config_sha256_missing" in audit["failures"]


def test_package_audit_rejects_malformed_runtime_and_config_hashes():
    dataset = _perfect_dataset()
    dataset["mission_manifest"] = [
        {
            "mission_id": "M-1",
            "intersection_id": "I-1",
            "source_profile_id": "SRC-1",
            "map_version_id": "MAP-1",
            "runtime_bundle_sha256": "not-a-runtime-hash",
            "model_id": "model.pt@0123456789ab",
            "config_sha256": "not-a-config-hash",
            "phases": ["entry_cruise", "hover_verified", "exit_cruise"],
        }
    ]

    audit = audit_cruise_acceptance_package(dataset)

    assert "mission_M-1_runtime_bundle_sha256_invalid" in audit["failures"]
    assert "mission_M-1_config_sha256_invalid" in audit["failures"]


def test_complete_capture_manifest_and_truth_provenance_are_evidence_ready():
    dataset = _perfect_dataset()
    for frame in dataset["frames"]:
        frame["mission_id"] = "M-1-1"
        frame["intersection_id"] = "I-1"
        frame["uav_ground_speed_mps"] = 5.0
    scenarios = [
        "motor",
        "non_motor",
        "dense_traffic",
        "crossing",
        "occlusion",
        "low_confidence_small_target",
    ]
    dataset["mission_manifest"] = [
        {
            "mission_id": f"M-{intersection}-{repeat}",
            "intersection_id": f"I-{intersection}",
            "source_profile_id": f"SRC-{intersection}",
            "map_version_id": f"MAP-{intersection}",
            "runtime_bundle_sha256": "2" * 64,
            "model_id": "model.pt@0123456789ab",
            "config_sha256": "3" * 64,
            "phases": ["entry_cruise", "hover_verified", "exit_cruise"],
            "scenario_tags": scenarios if intersection == repeat == 1 else [],
            "capture_profile": {
                "agl_target_m": 100,
                "ground_speed_target_mps": 5,
                "gimbal_pitch_deg": -90,
                "resolution": "3840x2160",
                "fps": 30,
            },
            "video": {
                "path": f"M-{intersection}-{repeat}.mp4",
                "sha256": "0" * 64,
            },
            "telemetry": {
                "path": f"M-{intersection}-{repeat}.srt",
                "sha256": "1" * 64,
            },
        }
        for intersection in range(1, 4)
        for repeat in range(1, 3)
    ]
    dataset["ground_truth_provenance"] = {
        "identity": {
            "source": "manual",
            "independently_reviewed": True,
            "reference_id": "ANNOTATION-REVIEW-001",
        },
        "position": {
            "source": "rtk_vehicle",
            "reference_id": "RTK-RUN-001",
            "calibration_valid": True,
        },
        "speed": {
            "source": "radar",
            "reference_id": "RADAR-RUN-001",
            "calibration_valid": True,
        },
    }

    audit = audit_cruise_acceptance_package(dataset)

    assert audit["status"] == "production_evidence_ready"
    assert audit["failures"] == []
