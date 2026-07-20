from pathlib import Path

from scripts.run_native_mps_replays import (
    PlatformClient,
    hydra_string,
    inference_summary,
    source_catalog,
    validate_tcc_events,
)

ROOT = Path(__file__).resolve().parents[2]


def test_native_mps_runner_selects_exactly_eight_mp4new_sources():
    catalog = source_catalog()
    assert len(catalog) == 8
    assert all(profile_id.startswith(("SRC-MP4NEW-", "SRC-MP4NEW2-")) for profile_id in catalog)
    assert "SRC-INTER-XQH-0403-PM" not in catalog


def test_strict_tcc_validation_accepts_zero_events_and_path_intersections():
    assert validate_tcc_events([]) == []
    assert validate_tcc_events(
        [
            {
                "message_id": "evt-1",
                "data": {"prediction_type": "path_intersection", "distance_m": 0.0},
            }
        ]
    ) == []


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


def test_hydra_string_quotes_spaces_cjk_and_single_quotes():
    assert hydra_string("测试 data/o'clock.txt") == "'测试 data/o\\'clock.txt'"


def test_batch_runner_disables_repeated_hover_jpeg_but_keeps_interactive_default():
    config = (ROOT / "configs/app_config.yaml").read_text(encoding="utf-8")
    runner = (ROOT / "scripts/run_native_mps_replays.py").read_text(encoding="utf-8")
    producer = (ROOT / "nodes/KafkaProducerNode.py").read_text(encoding="utf-8")
    assert "hover_annotation_snapshot_enabled: true" in config
    assert '"kafka_producer_node.hover_annotation_snapshot_enabled=false"' in runner
    assert 'data["is_hovering"] and self._hover_annotation_snapshot_enabled' in producer


def test_native_runner_forces_empty_lane_annotation_parameters():
    runner = (ROOT / "scripts/run_native_mps_replays.py").read_text(encoding="utf-8")
    assert '"roads_json": ""' in runner
    assert '"ROADS_JSON": ""' in runner


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
                    "active_trajectories": [{"trajectory": list(range(1000))}],
                },
            }
        },
    )()
    assert _capture_message(buckets, message, "pipe-1") is True
    assert buckets["stats"][0]["data"]["inference_ms"] == 88.0
    assert "active_trajectories" not in buckets["stats"][0]["data"]
