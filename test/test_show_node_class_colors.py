import unittest

import cv2
import numpy as np

from elements.FrameElement import FrameElement
from elements.TrackElement import TrackElement
from nodes.ShowNode import ShowNode


class ShowNodeClassColorsTest(unittest.TestCase):
    @staticmethod
    def _make_node():
        return ShowNode({
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
        })

    def test_class_color_indices_are_stable_and_type_specific(self):
        node = object.__new__(ShowNode)
        node.class_color_idx = {
            class_name: idx
            for idx, class_name in enumerate(ShowNode.CLASS_COLOR_KEYS)
        }

        indices = node._class_color_indices(np.array([
            "people",
            "pedestrian",
            "car",
            "truck",
            "motor",
            "motorcycle",
            "awning_tricycle",
            "unknown-label",
        ], dtype=object))

        self.assertEqual(indices[0], indices[1])
        self.assertNotEqual(indices[2], indices[3])
        self.assertEqual(indices[4], indices[5])
        self.assertEqual(indices[6], node.class_color_idx["awning-tricycle"])
        self.assertEqual(indices[7], node.class_color_idx["unknown"])

    def test_formal_trace_color_preserves_track_palette_mode(self):
        node = self._make_node()
        node.show_class_different_colors = False
        node.show_track_id_different_colors = True

        color = node._formal_trace_color("car", 7, None)

        self.assertEqual(color, node.sv_box_annotator.color.by_idx(7).as_bgr())

    def test_candidate_box_uses_amber_dashes_and_explicit_non_formal_label(self):
        frame = np.zeros((100, 140, 3), dtype=np.uint8)

        ShowNode._draw_candidate_box(frame, [10, 20, 120, 80], 7, "car")

        self.assertTrue(np.array_equal(frame[20, 10], np.array([0, 191, 255])))
        self.assertGreater(np.count_nonzero(frame), 100)

    def test_warning_tcc_prompt_uses_red_instead_of_amber(self):
        node = self._make_node()
        motor = TrackElement(id=82, timestamp_first=0.0)
        motor.trajectory_points = [(80.0, 100.0)]
        non_motor = TrackElement(id=3289, timestamp_first=0.0)
        non_motor.trajectory_points = [(220.0, 100.0)]
        frame_element = FrameElement(
            source="tcc-warning",
            frame=np.zeros((240, 320, 3), dtype=np.uint8),
            timestamp=1.0,
            frame_num=1,
            roads_info={},
            id_list=[82, 3289],
            buffer_tracks={82: motor, 3289: non_motor},
        )
        frame_element.conflict_events = [{
            "motor_id": 82,
            "non_motor_id": 3289,
            "severity": "warning",
            "ttc_sec": 2.4,
        }]

        rendered = node.process(frame_element).frame_result

        self.assertTrue(np.array_equal(rendered[100, 80], np.array([0, 0, 255])))
        rendered_int = rendered.astype(np.int16)
        orange_pixels = (
            (rendered_int[:, :, 2] > 180)
            & (rendered_int[:, :, 1] > 100)
            & (rendered_int[:, :, 1] > rendered_int[:, :, 0] * 2)
        )
        self.assertFalse(np.any(orange_pixels))

    def test_process_renders_candidate_trajectory_as_amber_trail(self):
        node = self._make_node()
        frame_element = FrameElement(
            source="candidate-preview",
            frame=np.zeros((100, 140, 3), dtype=np.uint8),
            timestamp=1.0,
            frame_num=1,
            roads_info={},
            tracked_conf=[0.8],
            tracked_cls=["car"],
            tracked_xyxy=[[70, 50, 90, 70]],
            id_list=[7],
            buffer_tracks={},
        )
        frame_element.formal_track_ids = []
        frame_element.candidate_trajectories = [{
            "track_id": 7,
            "trajectory_px": [[10, 10], [120, 80]],
            "trajectory_display_px": [[20, 70], [50, 70], [80, 70]],
        }]

        result = node.process(frame_element)

        trail_corridor = result.frame_result[67:74, 20:61]
        amber_pixels = np.all(trail_corridor == np.array([0, 191, 255]), axis=2)
        self.assertTrue(
            np.any(amber_pixels),
            "candidate ID moved but the detector output contains no candidate trail",
        )

    def test_process_renders_formal_and_candidate_trails_together(self):
        node = self._make_node()
        first = FrameElement(
            source="mixed-preview",
            frame=np.zeros((110, 170, 3), dtype=np.uint8),
            timestamp=1.0,
            frame_num=1,
            roads_info={},
            tracked_conf=[0.9, 0.8],
            tracked_cls=["car", "car"],
            tracked_xyxy=[[10, 10, 30, 30], [70, 50, 90, 70]],
            id_list=[1, 7],
            buffer_tracks={},
        )
        first.formal_track_ids = [1]
        first.candidate_trajectories = [{
            "track_id": 7,
            "trajectory_px": [[80, 70]],
        }]
        node.process(first)

        formal_track = TrackElement(id=1, timestamp_first=1.0)
        formal_track.ground_contact_points_px = [(20.0, 30.0), (50.0, 30.0)]
        formal_track.trajectory_enu_m = [(20.0, 30.0), (50.0, 30.0)]
        second = FrameElement(
            source="mixed-preview",
            frame=np.zeros((110, 170, 3), dtype=np.uint8),
            timestamp=2.0,
            frame_num=2,
            roads_info={},
            tracked_conf=[0.9, 0.8],
            tracked_cls=["car", "car"],
            tracked_xyxy=[[40, 10, 60, 30], [100, 50, 120, 70]],
            id_list=[1, 7],
            buffer_tracks={1: formal_track},
        )
        second.pixel_to_map_enu = np.eye(3)
        second.formal_track_ids = [1]
        second.candidate_trajectories = [{
            "track_id": 7,
            "trajectory_px": [[80, 70], [110, 70]],
        }]

        result = node.process(second)

        formal_corridor = result.frame_result[27:34, 20:41]
        candidate_corridor = result.frame_result[67:74, 80:101]
        self.assertGreater(np.count_nonzero(formal_corridor), 0)
        self.assertTrue(np.any(np.all(
            candidate_corridor == np.array([0, 191, 255]), axis=2
        )))

    def test_formal_trace_uses_visual_display_history_and_ignores_current_h(self):
        node = self._make_node()
        track = TrackElement(id=2, timestamp_first=0.0)
        track.ground_contact_points_px = [(30.0, 70.0), (30.0, 70.0), (60.0, 70.0)]
        track.trajectory_enu_m = [(30.0, 70.0), (50.0, 70.0), (80.0, 70.0)]
        frame = FrameElement(
            source="moving-camera",
            frame=np.zeros((100, 180, 3), dtype=np.uint8),
            timestamp=1.0,
            frame_num=2,
            roads_info={},
            tracked_conf=[0.9],
            tracked_cls=["car"],
            tracked_xyxy=[[145, 10, 165, 30]],
            id_list=[1],
            buffer_tracks={2: track},
        )
        frame.formal_track_ids = [1]
        frame.formal_track_id_by_association = {1: 2}
        frame.association_trajectories = [{
            "association_id": 1,
            "trajectory_display_px": [[10.0, 70.0], [30.0, 70.0], [60.0, 70.0]],
        }]
        frame.pixel_to_map_enu = np.array([
            [1.0, 0.0, 100.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ])

        rendered = node.process(frame).frame_result

        assert np.count_nonzero(rendered[67:74, 9:61]) > 0
        assert np.count_nonzero(rendered[67:74, 80:100]) == 0
        assert track.ground_contact_points_px == [
            (30.0, 70.0),
            (30.0, 70.0),
            (60.0, 70.0),
        ]

    def test_formal_trace_without_display_history_uses_bbox_centers(self):
        node = self._make_node()
        track = TrackElement(id=1, timestamp_first=0.0)
        track.trajectory_points = [(20.0, 70.0), (60.0, 70.0), (110.0, 70.0)]
        track.ground_contact_points_px = [
            (20.0, 80.0),
            (60.0, 80.0),
            (110.0, 80.0),
        ]
        frame = FrameElement(
            source="legacy-display-anchor",
            frame=np.zeros((120, 140, 3), dtype=np.uint8),
            timestamp=1.0,
            frame_num=1,
            roads_info={},
            tracked_conf=[0.9],
            tracked_cls=["car"],
            tracked_xyxy=[[100, 60, 120, 80]],
            id_list=[1],
            buffer_tracks={1: track},
        )
        frame.formal_track_ids = [1]

        rendered = node.process(frame).frame_result

        assert np.count_nonzero(rendered[67:74, 20:81]) > 0
        assert np.count_nonzero(rendered[77:84, 20:81]) == 0

    def test_stationary_candidate_bbox_jitter_does_not_draw_scribble(self):
        node = self._make_node()
        frame = FrameElement(
            source="stationary-jitter",
            frame=np.zeros((120, 220, 3), dtype=np.uint8),
            timestamp=1.0,
            frame_num=10,
            roads_info={},
            tracked_conf=[0.8],
            tracked_cls=["car"],
            tracked_xyxy=[[170, 20, 200, 50]],
            id_list=[7],
            buffer_tracks={},
        )
        frame.formal_track_ids = []
        frame.candidate_trajectories = [{
            "track_id": 7,
            "trajectory_display_px": [
                [40, 90], [42, 89], [39, 91], [41, 90], [40, 89], [42, 91]
            ],
        }]

        rendered = node.process(frame).frame_result

        assert np.count_nonzero(rendered[82:98, 30:55]) == 0

    def test_process_ignores_invalid_candidate_points_and_single_point_history(self):
        node = self._make_node()
        frame_element = FrameElement(
            source="invalid-candidate-preview",
            frame=np.zeros((100, 180, 3), dtype=np.uint8),
            timestamp=1.0,
            frame_num=1,
            roads_info={},
            tracked_conf=[0.8],
            tracked_cls=["car"],
            tracked_xyxy=[[130, 20, 160, 50]],
            id_list=[7],
            buffer_tracks={},
        )
        frame_element.formal_track_ids = []
        frame_element.candidate_trajectories = [{
            "track_id": 7,
            "trajectory_px": [
                None,
                [float("nan"), 70],
                [-10, 70],
                [20, 70],
                [200, 70],
            ],
        }]

        result = node.process(frame_element)

        self.assertEqual(np.count_nonzero(result.frame_result[66:75, 5:80]), 0)

    def test_process_bounds_candidate_trace_to_latest_thirty_points(self):
        node = self._make_node()
        frame_element = FrameElement(
            source="bounded-candidate-preview",
            frame=np.zeros((100, 400, 3), dtype=np.uint8),
            timestamp=1.0,
            frame_num=1,
            roads_info={},
            tracked_conf=[0.8],
            tracked_cls=["car"],
            tracked_xyxy=[[350, 20, 380, 50]],
            id_list=[7],
            buffer_tracks={},
        )
        frame_element.formal_track_ids = []
        frame_element.candidate_trajectories = [{
            "track_id": 7,
            "trajectory_px": [[index * 10, 80] for index in range(31)],
        }]

        result = node.process(frame_element)

        self.assertEqual(np.count_nonzero(result.frame_result[76:85, 0:5]), 0)
        self.assertGreater(np.count_nonzero(result.frame_result[76:85, 10:301]), 0)

    def test_process_breaks_candidate_trace_at_large_display_jump(self):
        node = self._make_node()
        frame_element = FrameElement(
            source="discontinuous-candidate-preview",
            frame=np.zeros((100, 180, 3), dtype=np.uint8),
            timestamp=1.0,
            frame_num=1,
            roads_info={},
            tracked_conf=[0.8],
            tracked_cls=["car"],
            tracked_xyxy=[[145, 50, 165, 70]],
            id_list=[7],
            buffer_tracks={},
        )
        frame_element.formal_track_ids = []
        frame_element.candidate_trajectories = [{
            "track_id": 7,
            "trajectory_px": [[20, 70], [130, 70], [155, 70]],
            "trajectory_display_px": [[20, 70], [130, 70], [155, 70]],
        }]

        result = node.process(frame_element)

        self.assertEqual(np.count_nonzero(result.frame_result[66:75, 50:100]), 0)
        self.assertGreater(np.count_nonzero(result.frame_result[66:75, 130:141]), 0)

    def test_candidate_overlay_remains_readable_at_delivery_viewport(self):
        node = self._make_node()
        frame_element = FrameElement(
            source="xqh-delivery-preview",
            frame=np.zeros((2160, 3840, 3), dtype=np.uint8),
            timestamp=880.0,
            frame_num=1,
            roads_info={},
            tracked_conf=[0.8],
            tracked_cls=["car"],
            tracked_xyxy=[[1800, 900, 2100, 1200]],
            id_list=[7],
            buffer_tracks={},
        )
        frame_element.formal_track_ids = []
        frame_element.candidate_trajectories = [{
            "track_id": 7,
            "trajectory_px": [[1500, 1200], [1650, 1200], [1800, 1200]],
            "trajectory_display_px": [[1500, 1200], [1650, 1200], [1800, 1200]],
        }]

        rendered = node.process(frame_element).frame_result
        viewport = cv2.resize(rendered, (1280, 720), interpolation=cv2.INTER_AREA)
        label_roi = viewport[270:299, 590:1050]
        label_amber = (
            (label_roi[:, :, 2] > 100)
            & (label_roi[:, :, 1] > 70)
            & (label_roi[:, :, 2] > label_roi[:, :, 1])
        )
        label_rows = np.flatnonzero(label_amber.any(axis=1))
        label_height = (
            int(label_rows[-1] - label_rows[0] + 1)
            if label_rows.size
            else 0
        )

        trail_roi = viewport[394:407, 495:598]
        trail_amber = (
            (trail_roi[:, :, 2] > 100)
            & (trail_roi[:, :, 1] > 70)
            & (trail_roi[:, :, 2] > trail_roi[:, :, 1])
        )
        trail_columns = trail_amber.any(axis=0)
        strong_trail_pixels = np.count_nonzero(
            (trail_roi[:, :, 2] > 220)
            & (trail_roi[:, :, 1] > 150)
            & (trail_roi[:, :, 0] < 40)
        )
        legend_roi = viewport[8:55, 700:1272]
        legend_amber_pixels = np.count_nonzero(
            (legend_roi[:, :, 2] > 220)
            & (legend_roi[:, :, 1] > 150)
            & (legend_roi[:, :, 0] < 40)
        )
        longest_dash = 0
        current_dash = 0
        for visible in trail_columns:
            current_dash = current_dash + 1 if visible else 0
            longest_dash = max(longest_dash, current_dash)

        self.assertGreaterEqual(label_height, 12)
        self.assertGreaterEqual(longest_dash, 7)
        self.assertGreaterEqual(strong_trail_pixels, 80)
        self.assertGreaterEqual(legend_amber_pixels, 1000)


if __name__ == "__main__":
    unittest.main()
