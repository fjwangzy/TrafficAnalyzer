import numpy as np
import unittest
import json

from elements.FrameElement import FrameElement
from elements.TrackElement import TrackElement
from nodes.KafkaProducerNode import KafkaProducerNode


class KafkaActiveTrajectoriesTest(unittest.TestCase):
    def _producer_without_kafka(self):
        producer = object.__new__(KafkaProducerNode)
        producer.topic_name = "uav_statistics_7"
        producer.track_complete_topic = "uav_track_complete_7"
        producer.conflicts_topic = "uav_conflicts_7"
        producer.telemetry_topic = "uav_telemetry_7"
        producer.intersection_id = "INT_camera_7"
        producer.camera_id = 7
        producer.how_often_sec = 1.0
        producer.last_send_time = None
        producer.buffer_analytics_sec = 0.0
        producer._fps_window_sec = 2.0
        producer._fps_timestamps = []
        producer._capacity_veh_per_min = 30.0
        producer._queue_threshold_m = 80.0
        producer._free_flow_speed_kmh = 40.0
        producer._active_trajectory_tail_points = 30
        producer._telemetry_interval = 0.2
        producer._last_telemetry_time = 0.0
        return producer

    def test_process_enqueues_stats_tracks_conflicts_and_telemetry_topics(self):
        frame = np.zeros((20, 20, 3), dtype=np.uint8)
        frame_element = FrameElement("test", frame, 2.0, 1, {"1": [0, 0, 1, 0, 1, 1, 0, 1]})
        frame_element.info = {"cars_amount": 4, "roads_activity": {1: 2.5}}
        frame_element.id_list = [101, 202]
        frame_element.tracked_xyxy = [[2, 2, 8, 8], [11, 10, 18, 18]]
        frame_element.tracked_cls = ["car", "bicycle"]
        motor_track = TrackElement(id=101, timestamp_first=1.0)
        motor_track.trajectory_points = [(2.0, 3.0), (5.0, 6.0), (7.0, 8.0)]
        non_motor_track = TrackElement(id=202, timestamp_first=1.0)
        non_motor_track.trajectory_points = [(15.0, 18.0), (13.0, 15.0), (12.0, 12.0)]
        frame_element.buffer_tracks = {101: motor_track, 202: non_motor_track}
        frame_element.direction_stats = {"straight": {"count": 2, "avg_speed_kmh": 18.0}}
        frame_element.queue_count = 1
        frame_element.completed_tracks = [{
            "track_id": 101,
            "trajectory_px": [[1, 2], [3, 4]],
            "trajectory_enu_m": [[0.1, 0.2], [0.3, 0.4]],
            "turn_behavior": "straight",
            "avg_speed_kmh": 18.0,
            "entry_point_m": [0.1, 0.2],
            "exit_point_m": [0.3, 0.4],
        }]
        frame_element.conflict_events = [{
            "motor_id": 101,
            "non_motor_id": 202,
            "prediction_type": "path_intersection",
            "distance_m": 0.0,
            "ttc_sec": 1.2,
            "pet_sec": 0.3,
            "severity": "critical",
            "conflict_scene": "suspected_right_turn_mv_nmv",
            "evidence": ["hard_ttc_or_pet"],
        }]
        frame_element.telemetry = {"latitude": 36.7, "longitude": 117.0, "height": 120.0}
        frame_element.source_frame_stride = 3
        frame_element.inference_context = {
            "metric_scope": "yolo_predict_single_processed_frame",
            "device": "mps",
            "precision": "fp16",
            "model": "test-model",
            "effective_imgsz": 960,
            "agl_tier": "medium",
        }

        producer = self._producer_without_kafka()
        sent = []
        producer._enqueue = lambda topic, data, **_kwargs: sent.append((topic, data))

        out = producer.process(frame_element)

        topics = [topic for topic, _ in sent]
        self.assertIs(out, frame_element)
        self.assertEqual(
            topics,
            ["uav_statistics_7", "uav_track_complete_7", "uav_telemetry_7"],
        )
        stats = sent[0][1]
        self.assertEqual(stats["msg_type"], "uav_stats")
        self.assertEqual(stats["intersection_id"], "INT_camera_7")
        self.assertEqual(stats["source_system"], "uav_traffic_analyzer_ai")
        self.assertEqual(stats["schema_version"], "uav_stats/v1")
        self.assertEqual(stats["time_quality"], "ingest_only")
        self.assertEqual(stats["data"]["cars"], 4)
        self.assertEqual(stats["data"]["road_1"], 2.5)
        self.assertEqual(stats["data"]["direction_flow"], frame_element.direction_stats)
        self.assertEqual(stats["data"]["queue_count"], 1)
        self.assertEqual(stats["data"]["conflict_count"], 1)
        self.assertEqual(stats["data"]["inference_context"]["effective_imgsz"], 960)
        self.assertEqual(stats["data"]["inference_context"]["frame_stride"], 3)
        self.assertGreaterEqual(stats["data"]["pipeline_processing_ms"], 0.0)

        self.assertEqual(sent[1][1]["msg_type"], "uav_track_complete")
        self.assertEqual(sent[1][1]["data"]["track_id"], 101)
        self.assertEqual(sent[2][1]["msg_type"], "uav_telemetry")
        self.assertEqual(sent[2][1]["drone_id"], "drone_7")
        self.assertEqual(sent[2][1]["data"]["height"], 120.0)
        self.assertEqual(len(frame_element.pending_tcc_envelopes), 1)
        pending_conflict = frame_element.pending_tcc_envelopes[0]
        self.assertEqual(pending_conflict["msg_type"], "uav_conflict")
        self.assertEqual(pending_conflict["quality_status"], "unverified")
        self.assertEqual(
            pending_conflict["data"]["conflict_scene"],
            "suspected_right_turn_mv_nmv",
        )
        self.assertNotIn("evidence_files", pending_conflict["data"])

    def test_topic_builder_rejects_unsafe_camera_id(self):
        self.assertEqual(
            KafkaProducerNode._canonical_topics("10"),
            ("uav_statistics_10", "uav_track_complete_10", "uav_conflicts_10", "uav_telemetry_10"),
        )
        with self.assertRaises(ValueError):
            KafkaProducerNode._canonical_topics("../10")

    def test_conflict_publication_waits_for_actual_show_output(self):
        frame_element = FrameElement(
            "test",
            np.zeros((20, 20, 3), dtype=np.uint8),
            2.0,
            1,
            {},
        )
        frame_element.info = {"cars_amount": 0, "roads_activity": {}}
        frame_element.buffer_tracks = {}
        frame_element.conflict_events = [{
            "motor_id": 101,
            "non_motor_id": 202,
            "prediction_type": "path_intersection",
            "distance_m": 0.0,
            "ttc_sec": 1.2,
            "severity": "critical",
        }]
        producer = self._producer_without_kafka()
        sent = []
        producer._enqueue = lambda topic, data, **_kwargs: sent.append((topic, data))

        producer.process(frame_element)

        assert all(message["msg_type"] != "uav_conflict" for _, message in sent)
        assert len(frame_element.pending_tcc_envelopes) == 1
        pending = frame_element.pending_tcc_envelopes[0]
        assert pending["msg_type"] == "uav_conflict"
        assert "evidence_files" not in pending["data"]

    def test_degraded_frame_sets_dynamic_quality_and_does_not_emit_formal_counts(self):
        frame = np.zeros((20, 20, 3), dtype=np.uint8)
        frame_element = FrameElement("test", frame, 2.0, 1, {})
        frame_element.info = {"cars_amount": None, "roads_activity": {}}
        frame_element.id_list = [101]
        frame_element.tracked_xyxy = [[2, 2, 8, 8]]
        frame_element.buffer_tracks = {}
        frame_element.flight_phase = "unsupported_pose"
        frame_element.geo_reference_quality = {
            "status": "degraded",
            "reasons": ["gimbal_pitch_out_of_range"],
        }
        frame_element.tracking_diagnostics = {
            "tracking_quality": "degraded",
            "shadow_comparison": {"legacy_track_count": 1},
        }
        frame_element.formal_analytics_eligible = False
        frame_element.candidate_trajectories = [{"track_id": 101}]

        producer = self._producer_without_kafka()
        sent = []
        producer._enqueue = lambda topic, data, **_kwargs: sent.append((topic, data))
        producer.process(frame_element)

        message = sent[0][1]
        self.assertEqual(message["quality_status"], "degraded")
        self.assertIsNone(message["data"]["cars"])
        self.assertEqual(message["data"]["active_tracks"], 0)
        self.assertEqual(message["data"]["candidate_tracks"], 1)
        self.assertFalse(message["data"]["formal_analytics_eligible"])
        self.assertNotIn(
            "shadow_comparison", message["data"]["tracking_diagnostics"]
        )

    def test_roadless_frame_keeps_non_lane_congestion_statistics(self):
        frame_element = FrameElement(
            "test",
            np.zeros((20, 20, 3), dtype=np.uint8),
            2.0,
            1,
            {},
        )
        frame_element.info = {"cars_amount": 10, "roads_activity": {}}
        frame_element.buffer_tracks = {}
        frame_element.geo_reference_quality = {
            "status": "degraded",
            "geo_status": "verified",
            "road_status": "missing",
            "reasons": ["lane_verified_map_required"],
        }
        frame_element.geo_analytics_eligible = True
        frame_element.road_analytics_eligible = False
        frame_element.formal_analytics_eligible = False
        frame_element.direction_stats = {
            "straight": {"count": 0, "avg_speed_kmh": None}
        }

        producer = self._producer_without_kafka()
        sent = []
        producer._enqueue = lambda topic, data, **_kwargs: sent.append((topic, data))

        producer.process(frame_element)

        stats = sent[0][1]["data"]
        self.assertEqual(stats["cars"], 10)
        self.assertEqual(stats["congestion_index"], 1.3)
        self.assertIsNone(stats["avg_speed_kmh"])

    def test_realtime_device_event_time_is_verified(self):
        frame = FrameElement(
            "Processing of rtsp://camera/live",
            np.zeros((20, 20, 3), dtype=np.uint8),
            2.0,
            1,
            {},
        )
        frame.source_is_realtime = True
        frame.telemetry = {"recorded_at": "2026-07-23T03:00:00+00:00"}
        frame.geo_reference_quality = {"status": "verified"}
        producer = self._producer_without_kafka()

        message = producer._canonical_envelope("uav_stats", {}, frame)

        self.assertEqual(message["source_time_semantics"], "event_time")
        self.assertEqual(message["time_quality"], "verified")
        self.assertEqual(message["quality_status"], "verified")

    def test_offline_recorded_time_remains_reconstructed(self):
        frame = FrameElement(
            "Processing of replay.mp4",
            np.zeros((20, 20, 3), dtype=np.uint8),
            2.0,
            1,
            {},
        )
        frame.telemetry = {"recorded_at": "2026-07-23T03:00:00+00:00"}
        frame.geo_reference_quality = {"status": "verified"}
        producer = self._producer_without_kafka()

        message = producer._canonical_envelope("uav_conflict", {}, frame)

        self.assertEqual(message["source_time_semantics"], "reconstructed")
        self.assertEqual(message["time_quality"], "reconstructed")
        self.assertEqual(message["quality_status"], "verified")

    def test_build_active_trajectories_includes_world_points_and_track_metadata(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        frame_element = FrameElement("test", frame, 3.0, 90, {})
        frame_element.homography_matrix = np.eye(3, dtype=np.float64)
        # Deliberately wrong current-frame pose: active history must use the ENU
        # points captured with each source frame, never reproject old pixels here.
        frame_element.drone_displacement_m = np.array([999.0, 999.0], dtype=np.float64)
        frame_element.anchor_gcj02 = (117.0223, 36.7029)

        track = TrackElement(id=7, timestamp_first=1.0)
        track.association_id = 42
        track.trajectory_output_eligible = True
        track.timestamp_last = 3.0
        track.vehicle_class = "motor"
        track.yolo_class_id = 3
        track.yolo_class_name = "car"
        track.yolo_model_id = "yolo11s-visdrone.pt@0123456789ab"
        track.class_mapping_version = "visdrone-business/v1"
        track.direction_class = "straight"
        track.turn_behavior = "left_turn"
        track.avg_speed_kmh = 18.4
        track.max_speed_kmh = 27.6
        track.trajectory_points = [(10.0, 20.0), (12.0, 24.0), (14.0, 28.0)]
        track.ground_contact_points_px = [(10.0, 30.0), (12.0, 34.0), (14.0, 38.0)]
        track.trajectory_enu_m = [(110.0, 220.0), (112.0, 224.0), (114.0, 228.0)]
        frame_element.buffer_tracks = {7: track}

        producer = object.__new__(KafkaProducerNode)

        active = producer._build_active_trajectories(frame_element)

        self.assertEqual(len(active), 1)
        self.assertEqual(active[0], {
                "track_id": 7,
                "association_id": 42,
                "vehicle_class": "motor",
                "yolo_class_id": 3,
                "yolo_class_name": "car",
                "yolo_model_id": "yolo11s-visdrone.pt@0123456789ab",
                "class_mapping_version": "visdrone-business/v1",
                "direction_class": "straight",
                "turn_behavior": "left_turn",
                "duration_sec": 2.0,
                "avg_speed_kmh": 18.4,
                "max_speed_kmh": 27.6,
                "trajectory_px": [[10.0, 30.0], [12.0, 34.0], [14.0, 38.0]],
                "trajectory_bbox_center_px": [[10.0, 20.0], [12.0, 24.0], [14.0, 28.0]],
                "trajectory_point_count": 3,
                "trajectory_tail_start": 0,
                "is_trajectory_tail": False,
                "trajectory_enu_m": [[110.0, 220.0], [112.0, 224.0], [114.0, 228.0]],
                "current_point_enu_m": [114.0, 228.0],
                "anchor_gcj02": [117.0223, 36.7029],
                "trajectory_gcj02": active[0]["trajectory_gcj02"],
                "map_version_id": None,
                "matched_lane_key": None,
                "source_lane_id": None,
                "matched_link_id": None,
                "movement_key": None,
                "map_match_confidence": None,
                "timestamp_first": 1.0,
                "timestamp_last": 3.0,
                "trajectory_output_eligible": True,
                "geo_analytics_eligible": False,
                "road_analytics_eligible": False,
                "tcc_analytics_eligible": False,
                "formal_analytics_eligible": False,
                "road_context_status": "missing",
                "quality_status": "degraded",
                "quality_reasons": [],
            })
        self.assertEqual(len(active[0]["trajectory_gcj02"]), 3)

    def test_stats_carries_candidate_trajectories_only_as_diagnostics(self):
        frame = np.zeros((20, 20, 3), dtype=np.uint8)
        frame_element = FrameElement("test", frame, 2.0, 1, {})
        frame_element.info = {"cars_amount": None, "roads_activity": {}}
        frame_element.id_list = [44]
        frame_element.buffer_tracks = {}
        frame_element.geo_reference_quality = {
            "status": "degraded",
            "reasons": ["telemetry_gap"],
        }
        frame_element.formal_analytics_eligible = False
        frame_element.candidate_trajectories = [{
            "track_id": 44,
            "tracking_method": "motion_compensated_image_v2",
            "tracking_quality": "degraded",
            "quality_reasons": ["telemetry_gap"],
            "trajectory_px": [[10.0, 20.0], [11.0, 20.0]],
            "trajectory_display_px": [[9.0, 20.0], [11.0, 20.0]],
        }]

        producer = self._producer_without_kafka()
        sent = []
        producer._enqueue = lambda topic, data, **_kwargs: sent.append((topic, data))
        producer.process(frame_element)

        stats = next(message for topic, message in sent if topic.startswith("uav_statistics_"))
        self.assertEqual(
            stats["data"]["candidate_trajectories"],
            [{
                "track_id": 44,
                "tracking_method": "motion_compensated_image_v2",
                "tracking_quality": "degraded",
                "quality_reasons": ["telemetry_gap"],
                "trajectory_px": [[10.0, 20.0], [11.0, 20.0]],
            }],
        )
        self.assertEqual(stats["data"]["active_trajectories"], [])
        self.assertEqual(stats["data"]["active_tracks"], 0)
        self.assertEqual(stats["data"]["candidate_tracks"], 1)

    def test_complete_runtime_map_does_not_repeat_hover_annotation_snapshot(self):
        producer = self._producer_without_kafka()
        producer.road_context_status = "complete"
        frame_element = FrameElement(
            "test",
            np.zeros((20, 20, 3), dtype=np.uint8),
            2.0,
            1,
            {},
        )
        frame_element.is_hovering = True
        frame_element.road_context_status = "missing"

        self.assertFalse(producer._needs_hover_annotation_snapshot(frame_element))

    def test_missing_runtime_map_keeps_hover_annotation_snapshot_available(self):
        producer = self._producer_without_kafka()
        producer.road_context_status = "missing"
        frame_element = FrameElement(
            "test",
            np.zeros((20, 20, 3), dtype=np.uint8),
            2.0,
            1,
            {},
        )
        frame_element.is_hovering = True

        self.assertTrue(producer._needs_hover_annotation_snapshot(frame_element))

    def test_candidate_realtime_contract_drops_internal_lineage_and_keeps_all_targets(self):
        producer = self._producer_without_kafka()
        frame_element = FrameElement(
            "test",
            np.zeros((20, 20, 3), dtype=np.uint8),
            2.0,
            1,
            {},
        )
        points = [[float(index), float(index * 2)] for index in range(40)]
        frame_element.candidate_trajectories = [
            {
                "track_id": track_id,
                "tracking_quality": "degraded",
                "quality_reasons": ["hover_not_verified"],
                "trajectory_px": points,
                "trajectory_enu_m": points,
                "trajectory_gcj02": points,
                "point_quality_lineage": [{"large": "internal"}] * 40,
                "trajectory_display_px": points,
            }
            for track_id in (101, 102)
        ]

        candidates = producer._build_candidate_trajectories(frame_element)

        self.assertEqual([item["track_id"] for item in candidates], [101, 102])
        self.assertEqual(len(candidates[0]["trajectory_px"]), 30)
        self.assertEqual(candidates[0]["trajectory_px"][0], [10.0, 20.0])
        self.assertNotIn("point_quality_lineage", candidates[0])
        self.assertNotIn("trajectory_display_px", candidates[0])

    def test_realtime_trajectory_contract_caps_targets_before_kafka_serialization(self):
        producer = self._producer_without_kafka()
        producer._realtime_trajectory_max_tracks = 2
        frame_element = FrameElement(
            "test", np.zeros((20, 20, 3), dtype=np.uint8), 2.0, 1, {}
        )
        frame_element.candidate_trajectories = [
            {"track_id": track_id, "trajectory_px": [[1.0, 2.0]]}
            for track_id in (101, 102, 103)
        ]

        candidates = producer._build_candidate_trajectories(frame_element)

        self.assertEqual([item["track_id"] for item in candidates], [101, 102])

    def test_dense_stats_payload_stays_below_kafka_default_request_limit(self):
        frame_element = FrameElement(
            "test", np.zeros((20, 20, 3), dtype=np.uint8), 2.0, 1, {}
        )
        frame_element.info = {"cars_amount": 400, "roads_activity": {}}
        frame_element.anchor_gcj02 = (117.0, 36.7)
        frame_element.id_list = []
        frame_element.tracked_xyxy = []
        frame_element.tracked_cls = []
        frame_element.buffer_tracks = {}
        for track_id in range(400):
            track = TrackElement(id=track_id, timestamp_first=0.0)
            track.timestamp_last = 2.0
            track.trajectory_output_eligible = True
            track.trajectory_points = [
                (float(point), float(point + track_id)) for point in range(30)
            ]
            track.trajectory_timestamps_sec = [point / 10.0 for point in range(30)]
            track.trajectory_frame_nums = list(range(30))
            track.trajectory_enu_m = [
                (float(point), float(point + track_id)) for point in range(30)
            ]
            track.trajectory_gcj02 = [
                (117.0 + point / 1_000_000.0, 36.7 + point / 1_000_000.0)
                for point in range(30)
            ]
            frame_element.buffer_tracks[track_id] = track

        producer = self._producer_without_kafka()
        producer._realtime_trajectory_max_tracks = 200
        sent = []
        producer._enqueue = lambda topic, data, **_kwargs: sent.append((topic, data))

        producer.process(frame_element)

        stats = next(payload for topic, payload in sent if topic == "uav_statistics_7")
        self.assertEqual(len(stats["data"]["active_trajectories"]), 200)
        self.assertEqual(stats["data"]["active_trajectories_truncated"], 200)
        self.assertLess(len(json.dumps(stats).encode("utf-8")), 1_000_000)

    def test_build_active_trajectories_limits_realtime_payload_to_tail_points(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        frame_element = FrameElement("test", frame, 5.0, 150, {})
        frame_element.homography_matrix = np.eye(3, dtype=np.float64)
        frame_element.drone_displacement_m = np.array([0.0, 0.0], dtype=np.float64)

        track = TrackElement(id=9, timestamp_first=1.0)
        track.trajectory_output_eligible = True
        track.timestamp_last = 5.0
        track.trajectory_points = [(float(i), float(i * 2)) for i in range(5)]
        track.trajectory_enu_m = [(float(i), float(i * 2)) for i in range(5)]
        frame_element.buffer_tracks = {9: track}

        producer = object.__new__(KafkaProducerNode)
        producer._active_trajectory_tail_points = 2

        active = producer._build_active_trajectories(frame_element)

        self.assertEqual(active[0]["trajectory_px"], [[3.0, 6.0], [4.0, 8.0]])
        self.assertEqual(active[0]["trajectory_enu_m"], [[3.0, 6.0], [4.0, 8.0]])
        self.assertEqual(active[0]["trajectory_point_count"], 5)
        self.assertEqual(active[0]["trajectory_tail_start"], 3)
        self.assertTrue(active[0]["is_trajectory_tail"])


if __name__ == "__main__":
    unittest.main()
