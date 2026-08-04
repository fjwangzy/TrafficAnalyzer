import json

from scripts.analyze_detection_tracking_coverage import main
from utils_local.detection_tracking_evaluation import evaluate_detection_tracking


def _stats_message(occurred_at, diagnostics):
    return {
        "occurred_at": occurred_at,
        "data": {"recognition_diagnostics": diagnostics},
    }


def _track(
    duration_sec,
    points,
    class_name,
    reason="association_ended",
    serialized_points=None,
):
    return {
        "data": {
            "duration_sec": duration_sec,
            "trajectory_length": points,
            "trajectory_px": [[0, 0]] * (serialized_points or points),
            "yolo_class_name": class_name,
            "termination_reason": reason,
        }
    }


def test_evaluate_detection_tracking_reports_coverage_segments_and_lifetimes():
    stats = [
        _stats_message(
            "2026-01-01T00:00:00+00:00",
            {
                "valid_yolo_detection_count": 4,
                "emitted_image_track_count": 3,
                "invalid_detector_geometry_count": 0,
                "yolo_class_counts": {"car": 2, "motor": 2},
                "emitted_track_class_counts": {"car": 2, "motor": 1},
                "small_yolo_detection_count": 2,
                "small_emitted_track_count": 1,
                "small_yolo_class_counts": {"motor": 2},
                "small_emitted_track_class_counts": {"motor": 1},
            },
        ),
        _stats_message(
            "2026-01-01T00:00:10+00:00",
            {
                "valid_yolo_detection_count": 1,
                "emitted_image_track_count": 0,
                "invalid_detector_geometry_count": 0,
                "yolo_class_counts": {"car": 1},
                "emitted_track_class_counts": {},
                "small_yolo_detection_count": 1,
                "small_emitted_track_count": 0,
                "small_yolo_class_counts": {"car": 1},
                "small_emitted_track_class_counts": {},
            },
        ),
    ]
    tracks = [
        _track(2.0, 5, "motor", serialized_points=4),
        _track(10.0, 20, "car", reason="natural_eof", serialized_points=8),
    ]

    result = evaluate_detection_tracking(
        stats,
        tracks,
        lifecycle_audit={"passed": True, "duplicate_pipeline_track_pairs": 0},
        segments=[
            {"name": "hover", "start_sec": 0, "end_sec": 5},
            {"name": "departure", "start_sec": 5, "end_sec": 20},
        ],
    )

    assert result["schema_version"] == "uav.detection-tracking-evaluation/v1"
    assert result["truth_metrics"] == {
        "status": "not_evaluated",
        "reason": "approved_external_truth_unavailable",
        "precision": None,
        "recall": None,
        "idf1": None,
        "hota": None,
        "formal_id_switches": None,
    }
    assert result["coverage"]["diagnostic_frame_count"] == 2
    assert result["coverage"]["invalid_detector_geometry_count"] == 0
    assert result["data_quality"]["numeric_emitted_class_label_count"] == 0
    assert result["data_quality"]["numeric_completed_class_label_count"] == 0
    assert result["conversion"]["overall"] == {
        "detected": 5,
        "emitted": 3,
        "ratio": 0.6,
    }
    assert result["conversion"]["small_targets"] == {
        "detected": 3,
        "emitted": 1,
        "ratio": 0.3333,
    }
    assert result["conversion"]["by_class"]["car"]["ratio"] == 0.6667
    assert result["conversion"]["frame_ratio_quantiles"]["p50"] == 0.375
    assert result["segments"]["hover"]["overall"]["ratio"] == 0.75
    assert result["segments"]["departure"]["small_targets"]["ratio"] == 0.0
    assert result["track_lifetimes"]["track_count"] == 2
    assert result["track_lifetimes"]["duration_sec_quantiles"]["p50"] == 6.0
    assert (
        result["track_lifetimes"]["observation_count_quantiles"]["p50"]
        == 12.5
    )
    assert (
        result["track_lifetimes"]["serialized_point_count_quantiles"]["p50"]
        == 6.0
    )
    assert result["track_lifetimes"]["duration_bands"] == {
        "lt_2s": 0,
        "2_to_3s": 1,
        "3_to_5s": 0,
        "5_to_10s": 0,
        "10_to_30s": 1,
        "30s_plus": 0,
    }
    assert result["track_lifetimes"]["termination_reason_counts"] == {
        "association_ended": 1,
        "natural_eof": 1,
    }
    assert result["lifecycle_audit"]["passed"] is True


def test_analysis_cli_writes_reproducible_report(tmp_path):
    stats_path = tmp_path / "stats.json"
    tracks_path = tmp_path / "tracks.json"
    output_path = tmp_path / "analysis.json"
    stats_path.write_text(
        json.dumps(
            [
                _stats_message(
                    "2026-01-01T00:00:00+00:00",
                    {
                        "valid_yolo_detection_count": 1,
                        "emitted_image_track_count": 1,
                    },
                )
            ]
        ),
        encoding="utf-8",
    )
    tracks_path.write_text("[]", encoding="utf-8")

    assert (
        main(
            [
                "--stats",
                str(stats_path),
                "--tracks",
                str(tracks_path),
                "--segment",
                "hover:0:5",
                "--output",
                str(output_path),
            ]
        )
        == 0
    )
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["coverage"]["diagnostic_frame_count"] == 1
    assert report["segments"]["hover"]["overall"]["ratio"] == 1.0
