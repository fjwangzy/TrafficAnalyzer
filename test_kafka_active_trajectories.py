import numpy as np
import unittest

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
        frame_element.buffer_tracks = {}
        frame_element.direction_stats = {"straight": {"count": 2, "avg_speed_kmh": 18.0}}
        frame_element.queue_count = 1
        frame_element.completed_tracks = [{
            "track_id": 101,
            "trajectory_px": [[1, 2], [3, 4]],
            "trajectory_world_m": [[0.1, 0.2], [0.3, 0.4]],
            "turn_behavior": "straight",
            "avg_speed_kmh": 18.0,
            "entry_point_m": [0.1, 0.2],
            "exit_point_m": [0.3, 0.4],
        }]
        frame_element.conflict_events = [{
            "motor_id": 101,
            "non_motor_id": 202,
            "prediction_type": "path_intersection",
            "ttc_sec": 1.2,
            "pet_sec": 0.3,
            "severity": "critical",
            "conflict_scene": "suspected_right_turn_mv_nmv",
            "evidence": ["hard_ttc_or_pet"],
        }]
        frame_element.telemetry = {"latitude": 36.7, "longitude": 117.0, "height": 120.0}

        producer = self._producer_without_kafka()
        sent = []
        producer._enqueue = lambda topic, data, **_kwargs: sent.append((topic, data))

        out = producer.process(frame_element)

        topics = [topic for topic, _ in sent]
        self.assertIs(out, frame_element)
        self.assertEqual(
            topics,
            ["uav_statistics_7", "uav_track_complete_7", "uav_conflicts_7", "uav_telemetry_7"],
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

        self.assertEqual(sent[1][1]["msg_type"], "uav_track_complete")
        self.assertEqual(sent[1][1]["data"]["track_id"], 101)
        self.assertEqual(sent[2][1]["msg_type"], "uav_conflict")
        self.assertEqual(sent[2][1]["data"]["conflict_scene"], "suspected_right_turn_mv_nmv")
        self.assertTrue(sent[2][1]["data"]["evidence_snapshot_jpeg"])
        self.assertEqual(sent[2][1]["data"]["evidence_snapshot_width"], 20)
        self.assertEqual(sent[2][1]["data"]["evidence_snapshot_height"], 20)
        self.assertEqual(sent[3][1]["msg_type"], "uav_telemetry")
        self.assertEqual(sent[3][1]["drone_id"], "drone_7")
        self.assertEqual(sent[3][1]["data"]["height"], 120.0)

    def test_topic_builder_rejects_unsafe_camera_id(self):
        self.assertEqual(
            KafkaProducerNode._canonical_topics("10"),
            ("uav_statistics_10", "uav_track_complete_10", "uav_conflicts_10", "uav_telemetry_10"),
        )
        with self.assertRaises(ValueError):
            KafkaProducerNode._canonical_topics("../10")

    def test_build_active_trajectories_includes_world_points_and_track_metadata(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        frame_element = FrameElement("test", frame, 3.0, 90, {})
        frame_element.homography_matrix = np.eye(3, dtype=np.float64)
        frame_element.drone_displacement_m = np.array([100.0, 200.0], dtype=np.float64)
        frame_element.world_anchor_lat_lon = (36.7029, 117.0223)

        track = TrackElement(id=7, timestamp_first=1.0)
        track.timestamp_last = 3.0
        track.vehicle_class = "motor"
        track.yolo_class_id = 3
        track.direction_class = "straight"
        track.turn_behavior = "left_turn"
        track.avg_speed_kmh = 18.4
        track.max_speed_kmh = 27.6
        track.trajectory_points = [(10.0, 20.0), (12.0, 24.0), (14.0, 28.0)]
        frame_element.buffer_tracks = {7: track}

        producer = object.__new__(KafkaProducerNode)

        active = producer._build_active_trajectories(frame_element)

        self.assertEqual(active, [
            {
                "track_id": 7,
                "vehicle_class": "motor",
                "yolo_class_id": 3,
                "direction_class": "straight",
                "turn_behavior": "left_turn",
                "duration_sec": 2.0,
                "avg_speed_kmh": 18.4,
                "max_speed_kmh": 27.6,
                "trajectory_px": [[10.0, 20.0], [12.0, 24.0], [14.0, 28.0]],
                "trajectory_point_count": 3,
                "trajectory_tail_start": 0,
                "is_trajectory_tail": False,
                "trajectory_world_m": [[110.0, 220.0], [112.0, 224.0], [114.0, 228.0]],
                "current_point_m": [114.0, 228.0],
                "world_anchor_lat_lon": [36.7029, 117.0223],
                "timestamp_first": 1.0,
                "timestamp_last": 3.0,
            }
        ])

    def test_build_active_trajectories_limits_realtime_payload_to_tail_points(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        frame_element = FrameElement("test", frame, 5.0, 150, {})
        frame_element.homography_matrix = np.eye(3, dtype=np.float64)
        frame_element.drone_displacement_m = np.array([0.0, 0.0], dtype=np.float64)

        track = TrackElement(id=9, timestamp_first=1.0)
        track.timestamp_last = 5.0
        track.trajectory_points = [(float(i), float(i * 2)) for i in range(5)]
        frame_element.buffer_tracks = {9: track}

        producer = object.__new__(KafkaProducerNode)
        producer._active_trajectory_tail_points = 2

        active = producer._build_active_trajectories(frame_element)

        self.assertEqual(active[0]["trajectory_px"], [[3.0, 6.0], [4.0, 8.0]])
        self.assertEqual(active[0]["trajectory_world_m"], [[3.0, 6.0], [4.0, 8.0]])
        self.assertEqual(active[0]["trajectory_point_count"], 5)
        self.assertEqual(active[0]["trajectory_tail_start"], 3)
        self.assertTrue(active[0]["is_trajectory_tail"])


if __name__ == "__main__":
    unittest.main()
