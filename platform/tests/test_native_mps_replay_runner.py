import asyncio
import os
import subprocess
import sys
from pathlib import Path

from scripts.run_native_mps_replays import (
    PlatformClient,
    _capture_message,
    _reconcile_road9_once,
    candidate_isolation_summary,
    completed_trajectory_summary,
    formal_business_leakage,
    hydra_string,
    inference_summary,
    resolve_replay_imgsz,
    source_catalog,
    source_result_passed,
    tcc_diagnostics_summary,
    telemetry_overrides,
    validate_source_assets,
    validate_tcc_events,
)


def test_replay_imgsz_defaults_preserve_fixed_history_and_production_fallback():
    assert resolve_replay_imgsz(None, adaptive_imgsz=False) == 640
    assert resolve_replay_imgsz(None, adaptive_imgsz=True) == 960
    assert resolve_replay_imgsz(1280, adaptive_imgsz=True) == 1280

ROOT = Path(__file__).resolve().parents[2]


def test_native_mps_runner_is_directly_executable_from_the_repository_root():
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/run_native_mps_replays.py"), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "OMP_NUM_THREADS": "1", "KMP_INIT_AT_FORK": "FALSE"},
    )
    assert completed.returncode == 0, completed.stderr
    assert "Run mp4new/mp4new2 sources serially" in completed.stdout


def test_native_mps_runner_selects_all_thirteen_registered_replay_sources():
    catalog = source_catalog()
    assert len(catalog) == 13
    assert "SRC-INTER-XQH-0403-PM" in catalog
    assert "SRC-MP4728-JS-0728-7MS" in catalog
    mapped = [item for item in catalog.values() if item["inter_id"].startswith("011")]
    assert all(item["road_data_version"] == "20260501-IMAGERY-FIT-V1" for item in mapped)
    assert catalog["SRC-MP4728-JS-0728-7MS"]["road_data_version"] is None


def test_strict_tcc_validation_accepts_zero_events_and_path_intersections():
    assert validate_tcc_events([]) == []
    assert validate_tcc_events(
        [
            {
                "message_id": "evt-1",
                "data": {
                    "prediction_type": "path_intersection",
                    "distance_m": 0.0,
                    "evidence_status": "complete",
                    "evidence_files": [
                        {
                            "kind": "conflict_original_frame",
                            "storage_backend": "managed",
                            "storage_key": f"objects/aa/{'a' * 64}",
                            "sha256": "a" * 64,
                            "size_bytes": 10,
                        },
                        {
                            "kind": "conflict_detector_frame",
                            "storage_backend": "managed",
                            "storage_key": f"objects/bb/{'b' * 64}",
                            "sha256": "b" * 64,
                            "size_bytes": 20,
                        },
                    ],
                },
            }
        ]
    ) == []


def test_strict_tcc_validation_rejects_event_without_synchronized_two_file_evidence():
    invalid = validate_tcc_events(
        [
            {
                "message_id": "evt-no-evidence",
                "data": {"prediction_type": "path_intersection", "distance_m": 0.0},
            }
        ]
    )
    assert [item["message_id"] for item in invalid] == ["evt-no-evidence"]


def test_strict_tcc_validation_rejects_legacy_cpa_or_nonzero_distance():
    invalid = validate_tcc_events(
        [
            {
                "message_id": "evt-cpa",
                "data": {"prediction_type": "same_time_cpa", "distance_m": 0.0},
            },
            {
                "message_id": "evt-gap",
                "data": {"prediction_type": "path_intersection", "distance_m": 0.8},
            },
        ]
    )
    assert [item["message_id"] for item in invalid] == ["evt-cpa", "evt-gap"]


def test_inference_summary_reports_distribution_without_warmup_assumptions():
    messages = [
        {
            "data": {
                "inference_ms": value,
                "pipeline_processing_ms": pipeline_ms,
                "fps": fps,
                "inference_context": {"effective_imgsz": imgsz},
            }
        }
        for value, pipeline_ms, fps, imgsz in [
            (80.0, 130.0, 4.0, 640),
            (100.0, 170.0, 5.0, 960),
            (120.0, 210.0, 6.0, 960),
        ]
    ]
    summary = inference_summary(messages)
    assert summary == {
        "samples": 3,
        "inference_ms": {"min": 80.0, "median": 100.0, "p95": 120.0, "max": 120.0},
        "pipeline_processing_ms": {
            "min": 130.0,
            "median": 170.0,
            "p95": 210.0,
            "max": 210.0,
        },
        "imgsz_counts": {"640": 1, "960": 2},
        "fps_median": 5.0,
    }


def test_tcc_diagnostics_summary_proves_the_detector_funnel_ran():
    messages = [
        {
            "data": {
                "tcc_diagnostics": {
                    "status": "no_prediction_candidates",
                    "candidate_pairs": 12,
                    "prediction_candidates": 0,
                    "distance_filtered": 7,
                    "prediction_failed": 5,
                    "business_events_emitted": 0,
                }
            }
        },
        {
            "data": {
                "tcc_diagnostics": {
                    "status": "events_emitted",
                    "candidate_pairs": 9,
                    "prediction_candidates": 2,
                    "evidence_failed": 1,
                    "business_events_emitted": 1,
                }
            }
        },
        {"data": {"tcc_diagnostics": None}},
    ]
    assert tcc_diagnostics_summary(messages) == {
        "samples": 2,
        "status_counts": {"events_emitted": 1, "no_prediction_candidates": 1},
        "frames_with_candidate_pairs": 2,
        "frames_with_predictions": 1,
        "business_events_emitted": 1,
        "funnel_rejections": {
            "distance_filtered": 7,
            "evidence_failed": 1,
            "prediction_failed": 5,
        },
    }


def test_source_result_requires_tcc_funnel_observation_even_when_zero_events_are_valid():
    result = {
        "return_code": 0,
        "error": None,
        "stats_count": 4,
        "trajectory_count": 2,
        "invalid_tcc_events": [],
        "tcc_diagnostics": {"samples": 0},
    }
    assert source_result_passed(result) is False
    result["tcc_diagnostics"] = {"samples": 4}
    assert source_result_passed(result) is True


def test_each_road9_reconciliation_disposes_loop_bound_connections(monkeypatch):
    events = []

    async def fake_wait(source_profile_id, pipeline_id, expected):
        events.append((source_profile_id, pipeline_id, expected))
        return {"matched": True}

    async def fake_close_db():
        events.append("closed")

    monkeypatch.setattr("scripts.run_native_mps_replays._wait_for_road9", fake_wait)
    monkeypatch.setattr("app.core.database.close_db", fake_close_db)
    result = asyncio.run(_reconcile_road9_once("SRC-1", "pipe-1", {"stats": 3}))
    assert result == {"matched": True}
    assert events == [("SRC-1", "pipe-1", {"stats": 3}), "closed"]


def test_roadless_acceptance_requires_completed_pixel_tracks_and_zero_road_leakage():
    result = {
        "acceptance_mode": "roadless_trajectory",
        "return_code": 0,
        "natural_eof": True,
        "error": None,
        "stats_count": 4,
        "trajectory_count": 1,
        "tcc_event_count": 0,
        "invalid_tcc_events": [],
        "tcc_diagnostics": {"samples": 4, "business_events_emitted": 0},
        "candidate_isolation": {
            "active_formal_tracks_peak": 3,
            "candidate_point_alignment_failures": 0,
        },
        "trajectory_output": {
            "eligible_completed_tracks": 1,
            "point_alignment_failures": 0,
        },
        "road9_reconciliation": {"matched": True},
    }
    result["formal_business_leakage"] = formal_business_leakage(result)
    assert source_result_passed(result) is True
    result["trajectory_output"]["point_alignment_failures"] = 1
    result["formal_business_leakage"] = formal_business_leakage(result)
    assert source_result_passed(result) is False


def test_generic_vehicle_counts_are_not_road_business_leakage():
    result = {
        "candidate_isolation": {
            "formal_frames": 0,
            "cars_peak": 23,
            "road_activity_frames": 0,
        },
        "tcc_diagnostics": {"business_events_emitted": 4},
        "tcc_event_count": 4,
    }

    leakage = formal_business_leakage(result)

    assert leakage["cars_peak"] == 23
    assert leakage["road_activity_frames"] == 0
    assert leakage["total"] == 0


def test_completed_trajectory_summary_requires_pixel_time_frame_and_nullable_world_alignment():
    summary = completed_trajectory_summary([
        {
            "message_id": "track-1",
            "data": {
                "trajectory_output_eligible": True,
                "trajectory_px": [[1, 2], [3, 4]],
                "trajectory_timestamps_sec": [0.0, 0.1],
                "trajectory_frame_nums": [1, 4],
                "trajectory_enu_m": [None, None],
                "trajectory_gcj02": [None, None],
            },
        }
    ])
    assert summary["eligible_completed_tracks"] == 1
    assert summary["pixel_trajectory_count"] == 1
    assert summary["point_alignment_failures"] == 0


def test_hydra_string_quotes_spaces_cjk_and_single_quotes():
    assert hydra_string("测试 data/o'clock.txt") == "'测试 data/o\\'clock.txt'"


def test_telemetry_overrides_disable_mismatched_mp4728_osd_instead_of_reusing_it():
    assert telemetry_overrides(
        {
            "telemetry_enabled": False,
            "telemetry": "must-not-be-used.txt",
            "time_offset_sec": 0.0,
        }
    ) == ["telemetry.enabled=false"]
    assert telemetry_overrides(
        {
            "telemetry_enabled": True,
            "telemetry": "经十路7米每秒.txt",
            "time_offset_sec": 74.373,
        }
    ) == [
        "telemetry.enabled=true",
        "telemetry.source=file",
        "telemetry.file_path='经十路7米每秒.txt'",
        "telemetry.time_offset_sec=74.373",
        "telemetry.sync_tolerance_sec=2.5",
    ]


def test_batch_runner_disables_repeated_hover_jpeg_but_keeps_interactive_default():
    config = (ROOT / "configs/app_config.yaml").read_text(encoding="utf-8")
    runner = (ROOT / "scripts/run_native_mps_replays.py").read_text(encoding="utf-8")
    producer = (ROOT / "nodes/KafkaProducerNode.py").read_text(encoding="utf-8")
    assert "hover_annotation_snapshot_enabled: true" in config
    assert '"kafka_producer_node.hover_annotation_snapshot_enabled=false"' in runner
    assert "self._needs_hover_annotation_snapshot(frame_element)" in producer
    assert 'return "complete" not in {frame_status, pipeline_status}' in producer


def test_native_runner_keeps_map_verified_and_roadless_trajectory_modes():
    runner = (ROOT / "scripts/run_native_mps_replays.py").read_text(encoding="utf-8")
    assert '"RUNTIME_MAP_BUNDLE_JSON"' in runner
    assert "stage-1 gate blocked: no lane_verified map" in runner
    assert '"candidate_only": False' in runner
    assert '"ROAD_CONTEXT_STATUS": "lane_verified" if runtime_bundle else "missing"' in runner
    assert "ROADS_JSON" not in runner


def test_runtime_bundle_selects_latest_lane_verified_map_without_source_registration():
    client = object.__new__(PlatformClient)
    requested_paths = []

    def request(method, path):
        requested_paths.append(path)
        if path.startswith("/api/v1/calibration/channelized-maps?"):
            return [
                {
                    "id": "CMV-OLD",
                    "status": "retired",
                    "version_no": 1,
                    "road_data_version": "OLD",
                },
                {
                    "id": "CMV-UNBOUND",
                    "status": "lane_verified",
                    "version_no": 3,
                    "road_data_version": "V3",
                },
                {
                    "id": "CMV-XQH",
                    "status": "lane_verified",
                    "version_no": 2,
                    "road_data_version": "V2",
                },
            ]
        if path.endswith("/CMV-UNBOUND/runtime-bundle"):
            return {
                "map_version_id": "CMV-UNBOUND",
                "road_data_version": "V3",
                "visual_registrations": [],
            }
        if path.endswith("/CMV-XQH/runtime-bundle"):
            return {
                "map_version_id": "CMV-XQH",
                "road_data_version": "V2",
                "visual_registrations": [
                    {
                        "source_profile_id": "SRC-INTER-XQH-0403-PM",
                        "status": "verified",
                        "homography_pixel_to_enu": [
                            [1.0, 0.0, 0.0],
                            [0.0, 1.0, 0.0],
                            [0.0, 0.0, 1.0],
                        ],
                    }
                ],
            }
        raise AssertionError(path)

    client.request = request
    bundle = client.runtime_bundle(
        {
            "inter_id": "011wwe0z19700001",
            "profile_id": "SRC-INTER-XQH-0403-PM",
            "road_data_version": "OLD",
        }
    )

    assert bundle["map_version_id"] == "CMV-UNBOUND"
    assert bundle["road_data_version"] == "V3"
    assert requested_paths[-1] == (
        "/api/v1/calibration/channelized-maps/CMV-UNBOUND/runtime-bundle"
    )


def test_native_runner_registers_browser_reachable_detector_stream_address():
    client = object.__new__(PlatformClient)
    captured = {}

    def request(method, path, body):
        captured.update({"method": method, "path": path, "body": body})
        return {"pipeline_id": "pipe-native"}

    client.request = request
    result = client.register(
        {
            "drone_id": "UAV-1",
            "inter_id": "INT-1",
            "profile_id": "SRC-1",
            "video": "test_videos/demo.mp4",
        },
        camera_id=5701,
        video_port=15701,
        runtime_bundle={"map_version_id": "CMV-1", "road_data_version": "20260501"},
        tracking_profile="hover_only_legacy",
    )

    assert result == {"pipeline_id": "pipe-native"}
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/pipelines/register"
    assert captured["body"]["video_stream_url"] == "http://127.0.0.1:15701/video"
    assert captured["body"]["map_version_id"] == "CMV-1"
    assert captured["body"]["tracking_profile"] == "hover_only_legacy"
    assert captured["body"]["candidate_only"] is False
    assert captured["body"]["source_profile_id"] == "SRC-1"
    assert captured["body"]["inter_id"] == "INT-1"


def test_native_runner_registers_roadless_pipeline_without_claiming_a_map():
    client = object.__new__(PlatformClient)
    captured = {}

    def request(method, path, body):
        captured.update({"method": method, "path": path, "body": body})
        return {"pipeline_id": "pipe-candidate"}

    client.request = request
    result = client.register(
        {
            "drone_id": "UAV-C",
            "inter_id": "INT-C",
            "profile_id": "SRC-C",
            "video": "test_videos/demo.mp4",
        },
        camera_id=5701,
        video_port=15701,
        runtime_bundle=None,
        tracking_profile="hover_cruise_v1",
    )

    assert result == {"pipeline_id": "pipe-candidate"}
    assert captured["body"]["candidate_only"] is False
    assert captured["body"]["source_profile_id"] == "SRC-C"
    assert captured["body"]["inter_id"] == "INT-C"
    assert captured["body"]["map_version_id"] is None
    assert captured["body"]["road_data_version"] is None


def test_stale_cleanup_only_stops_runner_reserved_registrations():
    client = object.__new__(PlatformClient)
    stopped = []
    client.request = lambda method, path: [
        {"pipeline_id": "ours", "status": "running", "camera_id": 5701, "video_port": 15701},
        {"pipeline_id": "business", "status": "running", "camera_id": 10, "video_port": 8101},
        {"pipeline_id": "old", "status": "stopped", "camera_id": 5702, "video_port": 15702},
    ]
    client.stop = stopped.append
    assert client.stop_stale_reserved() == ["ours"]
    assert stopped == ["ours"]


def test_stats_capture_keeps_performance_fields_without_large_trajectory_snapshots():
    buckets = {"stats": [], "tracks": [], "conflicts": [], "telemetry": []}
    message = type(
        "Message",
        (),
        {
            "value": {
                "message_id": "m1",
                "msg_type": "uav_stats",
                "data": {
                    "pipeline_id": "pipe-1",
                    "source_profile_id": "SRC-1",
                    "inference_ms": 88.0,
                    "pipeline_processing_ms": 140.0,
                    "inference_context": {
                        "effective_imgsz": 960,
                        "agl_tier": "medium",
                    },
                    "fps": 3.0,
                    "active_tracks": 7,
                    "cars": 8,
                    "tcc_diagnostics": {
                        "status": "no_prediction_candidates",
                        "candidate_pairs": 12,
                    },
                    "active_trajectories": [{"trajectory": list(range(1000))}],
                },
            }
        },
    )()
    assert _capture_message(buckets, message, "pipe-1") is True
    assert buckets["stats"][0]["data"]["inference_ms"] == 88.0
    assert buckets["stats"][0]["data"]["pipeline_processing_ms"] == 140.0
    assert buckets["stats"][0]["data"]["inference_context"] == {
        "effective_imgsz": 960,
        "agl_tier": "medium",
    }
    assert buckets["stats"][0]["data"]["tcc_diagnostics"] == {
        "status": "no_prediction_candidates",
        "candidate_pairs": 12,
    }
    assert "active_trajectories" not in buckets["stats"][0]["data"]


def test_stats_capture_summarizes_candidate_alignment_quality_without_large_paths():
    buckets = {"stats": [], "tracks": [], "conflicts": [], "telemetry": []}
    message = type(
        "Message",
        (),
        {
            "value": {
                "message_id": "candidate-1",
                "msg_type": "uav_stats",
                "data": {
                    "pipeline_id": "pipe-c",
                    "candidate_trajectories": [
                        {
                            "quality_reasons": ["lane_verified_map_required"],
                            "trajectory_px": [[1, 2], [2, 3]],
                            "trajectory_timestamps_sec": [0.0],
                        }
                    ],
                    "geo_reference_quality": {
                        "telemetry": {"status": "verified"},
                        "reasons": ["map_coverage_not_verified"],
                    },
                    "formal_analytics_eligible": False,
                    "tcc_diagnostics": {"status": "quality_blocked"},
                },
            }
        },
    )()
    assert _capture_message(buckets, message, "pipe-c") is True
    data = buckets["stats"][0]["data"]
    assert data["candidate_tracks"] == 1
    assert data["candidate_alignment_failures"] == 1
    assert data["quality_reasons"] == [
        "lane_verified_map_required",
        "map_coverage_not_verified",
    ]
    summary = candidate_isolation_summary(buckets["stats"])
    assert summary["frames_with_candidates"] == 1
    assert summary["telemetry_coverage_ratio"] == 1.0
    assert summary["telemetry_verified_ratio"] == 1.0
    assert summary["candidate_point_alignment_failures"] == 1


def test_mp4728_manifest_integrity_is_verified(tmp_path):
    video = tmp_path / "video.mp4"
    telemetry = tmp_path / "telemetry.txt"
    video.write_bytes(b"video")
    telemetry.write_bytes(b"telemetry")
    source = {
        "profile_id": "SRC-TEST",
        "video": str(video),
        "telemetry": str(telemetry),
        "source_manifest": {
            "video_sha256": "0cab1c9617404faf2b24e221e189ca5945813e14d3f766345b09ca13bbe28ffc",
            "video_size_bytes": 5,
            "telemetry_sha256": "16091175048ac6014be4712b1640c0e3a3272f4fc944e0bee3248f8861b234be",
        },
    }
    checked = validate_source_assets(source)
    assert checked["video_sha256"] == source["source_manifest"]["video_sha256"]
    assert checked["telemetry_sha256"] == source["source_manifest"]["telemetry_sha256"]
