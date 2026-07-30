import numpy as np

from elements.FrameElement import FrameElement


def test_xqh_acceptance_summarizes_adaptive_imgsz_tiers_and_switches():
    from scripts.accept_xqh_hover_departure import _adaptive_imgsz_summary

    summary = _adaptive_imgsz_summary([
        {"effective_imgsz": 960, "tier": "medium", "switch_count": 0},
        {"effective_imgsz": 960, "tier": "medium", "switch_count": 0},
    ])

    assert summary == {
        "samples": 2,
        "imgsz_counts": {"960": 2},
        "tier_counts": {"medium": 2},
        "max_switch_count": 0,
        "all_effective_imgsz_960": True,
    }


def _show_config():
    return {
        "general": {
            "colors_of_roads": {1: [102, 204, 255]},
            "buffer_analytics": 0.5,
            "min_time_life_track": 3,
        },
        "show_node": {
            "scale": 1.0,
            "fps_counter_N_frames_stat": 15,
            "draw_fps_info": False,
            "show_roi": False,
            "overlay_transparent_mask": False,
            "imshow": False,
            "show_only_yolo_detections": False,
            "show_track_id_different_colors": False,
            "show_class_different_colors": True,
            "show_info_statistics": False,
            "show_trace_trails": True,
        },
        "video_saver_node": {"fps": 24},
    }


def test_xqh_acceptance_measures_candidate_trail_through_production_show_node():
    from scripts.accept_xqh_hover_departure import _render_show_node_evidence

    frame = np.zeros((100, 160, 3), dtype=np.uint8)
    element = FrameElement(
        source="xqh-acceptance",
        frame=frame,
        timestamp=901.2,
        frame_num=27010,
        roads_info={},
        tracked_conf=[0.8],
        tracked_cls=["car"],
        tracked_xyxy=[[100, 50, 120, 70]],
        id_list=[7],
        buffer_tracks={},
    )
    element.formal_track_ids = []
    element.candidate_trajectories = [{
        "track_id": 7,
        "trajectory_px": [[20, 70], [60, 70], [110, 70]],
        "trajectory_display_px": [[20, 70], [60, 70], [110, 70]],
    }]

    rendered, candidate_trace_pixels = _render_show_node_evidence(
        frame,
        element,
        _show_config(),
    )

    assert rendered.shape == frame.shape
    assert candidate_trace_pixels > 0


def test_xqh_acceptance_checks_candidate_pixel_world_display_alignment():
    from scripts.accept_xqh_hover_departure import _candidate_geometry_metrics

    element = FrameElement(
        source="xqh-acceptance",
        frame=np.zeros((100, 160, 3), dtype=np.uint8),
        timestamp=1.0,
        frame_num=10,
        roads_info={},
        tracked_xyxy=[[50, 40, 70, 70]],
        id_list=[7],
    )
    element.pixel_to_world_enu = np.array([
        [1.0, 0.0, 20.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ])
    element.candidate_trajectories = [{
        "track_id": 7,
        "trajectory_px": [[30.0, 70.0], [60.0, 70.0]],
        "trajectory_enu_m": [[50.0, 70.0], [80.0, 70.0]],
        "trajectory_display_px": [[30.0, 70.0], [60.0, 70.0]],
        "trajectory_timestamps_sec": [0.9, 1.0],
        "trajectory_frame_nums": [9, 10],
        "point_quality_lineage": [{}, {}],
    }]

    metrics = _candidate_geometry_metrics(element)

    assert metrics == {
        "alignment_failures": 0,
        "endpoint_bbox_residual_px": [0.0],
    }


def test_xqh_acceptance_resolves_candidate_bbox_by_association_id():
    from scripts.accept_xqh_hover_departure import _candidate_geometry_metrics

    element = FrameElement(
        source="xqh-acceptance",
        frame=np.zeros((100, 160, 3), dtype=np.uint8),
        timestamp=3.0,
        frame_num=30,
        roads_info={},
        tracked_xyxy=[[50, 40, 70, 70]],
        id_list=[7],
    )
    element.association_trajectories = [{
        "association_id": 7,
        "track_id": 70,
        "trajectory_px": [[30.0, 70.0], [60.0, 70.0]],
        "trajectory_display_px": [[30.0, 70.0], [60.0, 70.0]],
        "trajectory_timestamps_sec": [2.9, 3.0],
        "trajectory_frame_nums": [29, 30],
        "point_quality_lineage": [{}, {}],
    }]
    element.candidate_trajectories = [{
        "track_id": 70,
        "association_id": 7,
        "trajectory_px": [[30.0, 70.0], [60.0, 70.0]],
        "trajectory_enu_m": [None, None],
        "trajectory_gcj02": [None, None],
        "trajectory_timestamps_sec": [2.9, 3.0],
        "trajectory_frame_nums": [29, 30],
    }]

    metrics = _candidate_geometry_metrics(element)

    assert metrics == {
        "alignment_failures": 0,
        "endpoint_bbox_residual_px": [0.0],
    }


def test_xqh_acceptance_allows_pixel_tracks_but_blocks_road_and_tcc_leaks():
    from scripts.accept_xqh_hover_departure import _capability_leak_counts

    element = FrameElement(
        source="xqh-capability-gates",
        frame=np.zeros((100, 160, 3), dtype=np.uint8),
        timestamp=3.0,
        frame_num=30,
        roads_info={},
        id_list=[7],
        buffer_tracks={70: object()},
    )
    element.info = {"cars_amount": 1}
    element.formal_track_ids = []
    element.road_analytics_eligible = False
    element.tcc_analytics_eligible = False

    assert _capability_leak_counts(element) == {
        "road": 0,
        "tcc": 0,
    }

    element.formal_track_ids = [70]
    element.conflict_events = [{"motor_id": 70, "non_motor_id": 71}]

    assert _capability_leak_counts(element) == {
        "road": 1,
        "tcc": 1,
    }


def test_xqh_acceptance_uses_ground_point_for_candidate_geometry():
    from scripts.accept_xqh_hover_departure import _candidate_geometry_metrics

    element = FrameElement(
        source="xqh-candidate-ground-point",
        frame=np.zeros((100, 160, 3), dtype=np.uint8),
        timestamp=3.0,
        frame_num=30,
        roads_info={},
        tracked_xyxy=[[50, 40, 70, 70]],
        id_list=[7],
    )
    element.candidate_trajectories = [{
        "track_id": 70,
        "association_id": 7,
        "trajectory_px": [[30.0, 70.0], [60.0, 70.0]],
        "trajectory_enu_m": [None, None],
        "trajectory_gcj02": [None, None],
        "trajectory_timestamps_sec": [2.9, 3.0],
        "trajectory_frame_nums": [29, 30],
    }]

    metrics = _candidate_geometry_metrics(element)

    assert metrics == {
        "alignment_failures": 0,
        "endpoint_bbox_residual_px": [0.0],
    }


def test_xqh_acceptance_does_not_mix_association_lineage_into_candidate_history():
    from scripts.accept_xqh_hover_departure import _candidate_geometry_metrics

    element = FrameElement(
        source="xqh-candidate-independent-lineage",
        frame=np.zeros((100, 160, 3), dtype=np.uint8),
        timestamp=3.0,
        frame_num=30,
        roads_info={},
        tracked_xyxy=[[50, 40, 70, 70]],
        id_list=[7],
    )
    element.association_trajectories = [{
        "association_id": 7,
        "trajectory_display_px": [
            [40.0, 55.0],
            [50.0, 55.0],
            [60.0, 55.0],
        ],
        "point_quality_lineage": [{}],
    }]
    element.candidate_trajectories = [{
        "track_id": 70,
        "association_id": 7,
        "trajectory_px": [[30.0, 70.0], [60.0, 70.0]],
        "trajectory_enu_m": [None, None],
        "trajectory_gcj02": [None, None],
        "trajectory_timestamps_sec": [2.9, 3.0],
        "trajectory_frame_nums": [29, 30],
    }]

    metrics = _candidate_geometry_metrics(element)

    assert metrics["alignment_failures"] == 0
