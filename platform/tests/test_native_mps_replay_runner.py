from pathlib import Path
import os
import subprocess
import sys

from scripts.run_native_mps_replays import (
    PlatformClient,
    hydra_string,
    inference_summary,
    source_result_passed,
    source_catalog,
    tcc_diagnostics_summary,
    validate_tcc_events,
)

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


def test_native_mps_runner_selects_all_nine_registered_replay_sources():
    catalog = source_catalog()
    assert len(catalog) == 9
    assert "SRC-INTER-XQH-0403-PM" in catalog
    assert all(item["inter_id"].startswith("011") for item in catalog.values())
    assert all(item["road_data_version"] == "20260501-IMAGERY-FIT-V1" for item in catalog.values())


def test_strict_tcc_validation_accepts_zero_events_and_path_intersections():
    assert validate_tcc_events([]) == []
    assert validate_tcc_events(
        [
            {
                "message_id": "evt-1",
                "data": {
                    "prediction_type": "path_intersection",
                    "distance_m": 0.0,
                    "evidence_images": [
                        {"kind": "conflict_original_frame", "jpeg_base64": "a"},
                        {"kind": "conflict_detector_frame", "jpeg_base64": "b"},
                        {"kind": "conflict_trajectory_reconstruction", "jpeg_base64": "c"},
                    ],
                },
            }
        ]
    ) == []


def test_strict_tcc_validation_rejects_event_without_synchronized_three_image_evidence():
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
        {"data": {"inference_ms": value, "fps": fps}}
        for value, fps in [(80.0, 4.0), (100.0, 5.0), (120.0, 6.0)]
    ]
    summary = inference_summary(messages)
    assert summary == {
        "samples": 3,
        "inference_ms": {"min": 80.0, "median": 100.0, "p95": 120.0, "max": 120.0},
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


def test_hydra_string_quotes_spaces_cjk_and_single_quotes():
    assert hydra_string("测试 data/o'clock.txt") == "'测试 data/o\\'clock.txt'"


def test_batch_runner_disables_repeated_hover_jpeg_but_keeps_interactive_default():
    config = (ROOT / "configs/app_config.yaml").read_text(encoding="utf-8")
    runner = (ROOT / "scripts/run_native_mps_replays.py").read_text(encoding="utf-8")
    producer = (ROOT / "nodes/KafkaProducerNode.py").read_text(encoding="utf-8")
    assert "hover_annotation_snapshot_enabled: true" in config
    assert '"kafka_producer_node.hover_annotation_snapshot_enabled=false"' in runner
    assert 'data["is_hovering"] and self._hover_annotation_snapshot_enabled' in producer


def test_native_runner_requires_immutable_lane_verified_runtime_bundle():
    runner = (ROOT / "scripts/run_native_mps_replays.py").read_text(encoding="utf-8")
    assert '"RUNTIME_MAP_BUNDLE_JSON"' in runner
    assert "stage-1 gate blocked: no lane_verified map" in runner
    assert "ROADS_JSON" not in runner


def test_native_runner_registers_browser_reachable_detector_stream_address():
    client = object.__new__(PlatformClient)
    captured = {}

    def request(method, path, body):
        captured.update({"method": method, "path": path, "body": body})
        return {"pipeline_id": "pipe-native"}

    client.request = request
    result = client.register(
        {"drone_id": "UAV-1", "inter_id": "INT-1", "video": "test_videos/demo.mp4"},
        camera_id=5701,
        video_port=15701,
        runtime_bundle={"map_version_id": "CMV-1", "road_data_version": "20260501"},
    )

    assert result == {"pipeline_id": "pipe-native"}
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/pipelines/register"
    assert captured["body"]["video_stream_url"] == "http://127.0.0.1:15701/video"
    assert captured["body"]["map_version_id"] == "CMV-1"


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
    from scripts.run_native_mps_replays import _capture_message

    buckets = {"stats": [], "tracks": [], "conflicts": []}
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
    assert buckets["stats"][0]["data"]["tcc_diagnostics"] == {
        "status": "no_prediction_candidates",
        "candidate_pairs": 12,
    }
    assert "active_trajectories" not in buckets["stats"][0]["data"]
