import numpy as np
import unittest

from elements.FrameElement import FrameElement
from elements.TrackElement import TrackElement
from nodes.KafkaProducerNode import KafkaProducerNode


class KafkaActiveTrajectoriesTest(unittest.TestCase):
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
