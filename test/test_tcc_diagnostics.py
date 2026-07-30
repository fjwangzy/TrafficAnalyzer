import numpy as np

from elements.FrameElement import FrameElement
from elements.TrackElement import TrackElement
from nodes.ConflictDetectionNode import ConflictDetectionNode
from nodes.KafkaProducerNode import KafkaProducerNode


def _config(**overrides):
    return {
        "conflict_detection": {
            "enabled": True,
            "prediction_horizon_sec": 5.0,
            "critical_horizon_sec": 3.0,
            "hard_ttc_sec": 2.0,
            "hard_pet_sec": 1.0,
            "sample_interval_sec": 0.2,
            "collision_radius_m": 2.0,
            "same_time_collision_radius_m": 0.8,
            "arrival_time_tolerance_sec": 1.0,
            "relative_speed_min_ms": 0.5,
            "min_history_points": 4,
            "min_conflict_angle_deg": 30.0,
            "max_conflict_angle_deg": 150.0,
            "turn_angle_threshold_deg": 45.0,
            "min_turn_leg_m": 2.0,
            "straight_angle_threshold_deg": 25.0,
            "hard_deceleration_ms2": -3.0,
            "hard_heading_change_deg": 60.0,
            "stop_speed_ms": 1.0,
            "moving_speed_ms": 2.0,
            **overrides,
        }
    }


def _track(
    track_id,
    vehicle_class,
    velocity,
    history,
    speed_kmh,
    *,
    trajectory_output_eligible=True,
):
    track = TrackElement(id=track_id, timestamp_first=history[0][2])
    track.vehicle_class = vehicle_class
    track.avg_speed_kmh = speed_kmh
    track.max_speed_kmh = speed_kmh
    track.velocity_ms = np.asarray(velocity, dtype=np.float64)
    track.position_history = history
    track.position_history_enu_m = history.copy()
    track.current_position_enu_m = list(history[-1][:2])
    track.trajectory_points = [(x, y) for x, y, _ in history]
    track.trajectory_output_eligible = trajectory_output_eligible
    return track


def _frame(motor, non_motor, homography=np.eye(3)):
    frame = FrameElement("test", np.zeros((32, 32, 3), dtype=np.uint8), 20.0, 600, {})
    frame.id_list = [motor.id, non_motor.id]
    frame.tracked_xyxy = [
        [motor.position_history[-1][0] - 1, motor.position_history[-1][1] - 1,
         motor.position_history[-1][0] + 1, motor.position_history[-1][1] + 1],
        [non_motor.position_history[-1][0] - 1, non_motor.position_history[-1][1] - 1,
         non_motor.position_history[-1][0] + 1, non_motor.position_history[-1][1] + 1],
    ]
    frame.homography_matrix = homography
    frame.pixel_to_world_enu = homography
    frame.tcc_analytics_eligible = True
    frame.drone_displacement_m = np.array([0.0, 0.0])
    frame.buffer_tracks = {motor.id: motor, non_motor.id: non_motor}
    return frame


def _right_turn_pair():
    motor = _track(
        303, "motor", [0.0, -3.0],
        [(-5.0, 0.0, 0.0), (-2.0, 0.0, 1.0), (0.0, -1.0, 2.0), (0.0, -2.0, 3.0)],
        10.8,
    )
    non_motor = _track(
        404, "non_motor", [4.0, 0.0],
        [(-12.0, -6.0, 0.0), (-10.0, -6.0, 1.0), (-8.0, -6.0, 2.0), (-6.0, -6.0, 3.0)],
        14.4,
    )
    return motor, non_motor


def test_tcc_diagnostics_explain_the_full_positive_funnel():
    motor, non_motor = _right_turn_pair()

    result = ConflictDetectionNode(_config()).process(_frame(motor, non_motor))

    assert len(result.conflict_events) == 1
    assert result.tcc_diagnostics == {
        "enabled": True,
        "calibration_valid": True,
        "motor_tracks": 1,
        "non_motor_tracks": 1,
        "eligible_motor_tracks": 1,
        "eligible_non_motor_tracks": 1,
        "candidate_pairs": 1,
        "association_immature": 0,
        "speed_missing": 0,
        "speed_below_min": 0,
        "history_insufficient": 0,
        "displacement_insufficient": 0,
        "distance_filtered": 0,
        "prediction_failed": 0,
        "scene_filtered": 0,
        "evidence_failed": 0,
        "severity_filtered": 0,
        "prediction_candidates": 1,
        "evidence_passed": 1,
        "deduplicated": 0,
        "events_emitted": 1,
        "business_events_emitted": 1,
        "experimental_events_emitted": 0,
        "status": "events_emitted",
    }


def test_tcc_diagnostics_counts_speed_rejections():
    motor, non_motor = _right_turn_pair()
    motor.max_speed_kmh = None
    non_motor.max_speed_kmh = 4.0

    result = ConflictDetectionNode(_config()).process(_frame(motor, non_motor))

    assert result.conflict_events == []
    assert result.tcc_diagnostics["speed_missing"] == 1
    assert result.tcc_diagnostics["speed_below_min"] == 1
    assert result.tcc_diagnostics["status"] == "no_eligible_candidates"


def test_tcc_rejects_world_tracks_until_image_association_is_mature():
    motor, non_motor = _right_turn_pair()
    non_motor.trajectory_output_eligible = False

    result = ConflictDetectionNode(_config()).process(_frame(motor, non_motor))

    assert result.conflict_events == []
    assert result.tcc_diagnostics["association_immature"] == 1
    assert result.tcc_diagnostics["eligible_motor_tracks"] == 1
    assert result.tcc_diagnostics["eligible_non_motor_tracks"] == 0
    assert result.tcc_diagnostics["status"] == "no_eligible_candidates"


def test_tcc_world_result_is_identical_with_or_without_lane_and_link_fields():
    motor, non_motor = _right_turn_pair()
    roadless = ConflictDetectionNode(_config()).process(_frame(motor, non_motor))

    motor, non_motor = _right_turn_pair()
    for track, lane_id, link_id in (
        (motor, "motor-lane", "motor-link"),
        (non_motor, "non-motor-lane", "non-motor-link"),
    ):
        track.source_lane_id = lane_id
        track.matched_link_id = link_id
        track.map_match_confidence = 0.99
    mapped_frame = _frame(motor, non_motor)
    mapped_frame.road_analytics_eligible = True
    mapped_frame.runtime_map_bundle = {"map_version_id": "CMV-road-only"}
    mapped = ConflictDetectionNode(_config()).process(mapped_frame)

    assert mapped.conflict_events == roadless.conflict_events
    assert mapped.tcc_diagnostics == roadless.tcc_diagnostics


def test_tcc_diagnostics_counts_distance_and_prediction_rejections():
    motor, non_motor = _right_turn_pair()
    non_motor.position_history = [
        (30.0, -6.0, 0.0),
        (32.0, -6.0, 1.0),
        (34.0, -6.0, 2.0),
        (36.0, -6.0, 3.0),
    ]
    non_motor.position_history_enu_m = non_motor.position_history.copy()
    non_motor.current_position_enu_m = [36.0, -6.0]
    far = ConflictDetectionNode(_config(max_pair_distance_m=15.0)).process(
        _frame(motor, non_motor)
    )
    assert far.tcc_diagnostics["distance_filtered"] == 1

    motor, non_motor = _right_turn_pair()
    node = ConflictDetectionNode(_config())
    node._predict_collision = lambda *args: None
    diverging = node.process(_frame(motor, non_motor))
    assert diverging.tcc_diagnostics["prediction_failed"] == 1
    assert diverging.tcc_diagnostics["status"] == "no_prediction_candidates"


def test_tcc_diagnostics_explain_missing_calibration():
    motor, non_motor = _right_turn_pair()

    result = ConflictDetectionNode(_config()).process(_frame(motor, non_motor, None))

    assert result.conflict_events == []
    assert result.tcc_diagnostics["enabled"] is True
    assert result.tcc_diagnostics["calibration_valid"] is False
    assert result.tcc_diagnostics["status"] == "missing_calibration"


def test_tcc_missing_geo_quality_safely_degrades_without_map_or_crash():
    motor, non_motor = _right_turn_pair()
    frame = _frame(motor, non_motor)
    frame.tcc_analytics_eligible = False
    frame.geo_reference_quality = None
    frame.runtime_map_bundle = None

    result = ConflictDetectionNode(_config()).process(frame)

    assert result.conflict_events == []
    assert result.tcc_diagnostics["status"] == "quality_gate_blocked"
    assert result.tcc_diagnostics["quality_reasons"] == ["geo_quality_missing"]


def test_same_time_cpa_is_disabled_by_default():
    node = ConflictDetectionNode(_config())

    prediction = node._predict_collision(
        np.array([0.0, 0.0]),
        np.array([0.4, 1.0]),
        np.array([0.0, 1.0]),
        np.array([1.0, 0.0]),
    )

    assert prediction is None


def test_uav_stats_exposes_diagnostics_and_counts_only_business_tcc():
    node = KafkaProducerNode.__new__(KafkaProducerNode)
    node.camera_id = "1"
    node.drone_id = "UAV-1"
    node.intersection_id = "INT-1"
    node.inter_id = "INT-1"
    node.topic_name = "uav_statistics_1"
    node.track_complete_topic = "uav_track_complete_1"
    node.conflicts_topic = "uav_conflicts_1"
    node.telemetry_topic = "uav_telemetry_1"
    node.last_send_time = None
    node.how_often_sec = 1.0
    node.buffer_analytics_sec = 0.0
    node._capacity_veh_per_min = 30.0
    node._queue_threshold_m = 80.0
    node._free_flow_speed_kmh = 40.0
    node._hover_annotation_snapshot_enabled = False
    node._congestion_snapshot_count = 0
    node._event_snapshot_congestion_threshold = 4.0
    node._event_snapshot_consecutive_samples = 30
    node._last_telemetry_time = 0.0
    node._fps_window_sec = 2.0
    node._fps_timestamps = []
    enqueued = []
    node._enqueue = lambda topic, payload, **kwargs: enqueued.append((topic, payload))

    frame = FrameElement("test", np.zeros((32, 32, 3), dtype=np.uint8), 20.0, 1, {})
    frame.id_list = []
    frame.buffer_tracks = {}
    frame.info = {"cars_amount": 0, "roads_activity": {}}
    frame.tcc_diagnostics = {"status": "events_emitted", "events_emitted": 2}
    frame.conflict_events = [
        {"motor_id": 1, "non_motor_id": 2, "prediction_type": "path_intersection", "distance_m": 0.0},
        {"motor_id": 3, "non_motor_id": 4, "prediction_type": "same_time_cpa", "distance_m": 0.4},
    ]

    node.process(frame)

    stats = next(payload for topic, payload in enqueued if topic == "uav_statistics_1")
    assert stats["data"]["conflict_count"] == 1
    assert stats["data"]["tcc_diagnostics"] == frame.tcc_diagnostics
