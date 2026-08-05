from elements.VideoEndBreakElement import VideoEndBreakElement
from elements.FrameElement import FrameElement
import main_optimized
import numpy as np
import signal
import pytest


class RecordingQueue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


def test_reader_detection_process_forwards_eof_without_accessing_frame(monkeypatch):
    sentinel = VideoEndBreakElement("fixture.mp4", 1.0)

    class FakeVideoReader:
        def __init__(self, *_args, **_kwargs):
            pass

        def process(self):
            yield sentinel

    class FakeDetectionNode:
        def __init__(self, _config):
            pass

        def process(self, frame_element):
            return frame_element

    monkeypatch.setattr(main_optimized, "VideoReader", FakeVideoReader)
    monkeypatch.setattr(main_optimized, "DetectionNode", FakeDetectionNode)
    monkeypatch.setattr(main_optimized, "_setup_logging_in_subprocess", lambda: None)
    queue = RecordingQueue()

    main_optimized.proc_frame_reader_and_detection(
        queue,
        {"video_reader": {}, "telemetry": {}},
        time_sleep_start=0,
    )

    assert queue.items == [sentinel]


def test_tracker_process_flushes_completed_tracks_before_terminal_outputs(monkeypatch):
    sentinel = VideoEndBreakElement("fixture.mp4", 4.2)
    events = []

    class InputQueue:
        def get(self, timeout):
            assert timeout > 0
            return sentinel

    class PassthroughNode:
        def __init__(self, _config):
            pass

        def process(self, frame_element):
            return frame_element

    class FakeGroundTracker(PassthroughNode):
        def process(self, frame_element):
            return frame_element

    class FakeWorldProjection(PassthroughNode):
        last_flush_result = None

        def process(self, frame_element):
            self.last_flush_result = {
                "termination_reason": "natural_eof",
                "terminated_track_ids": [7],
            }
            return frame_element

    flushed_frame = object()

    class FakeTrackerInfo(PassthroughNode):
        def flush(self, timestamp, reason, terminated_track_ids):
            events.append(("flush", timestamp, reason, terminated_track_ids))
            return flushed_frame

    class FakeGeoJson(PassthroughNode):
        def process(self, frame_element):
            events.append(
                "geojson_eof"
                if isinstance(frame_element, VideoEndBreakElement)
                else "geojson_completed"
            )
            return frame_element

    class FakeKafka(PassthroughNode):
        def publish_completed_tracks(self, frame_element):
            assert frame_element is flushed_frame
            events.append("kafka_completed")

        def seal_replay_mission(self, frame_element, *, termination_reason):
            assert frame_element is sentinel
            events.append(("kafka_sealed", termination_reason))

        def process(self, frame_element):
            events.append("kafka_eof")
            return frame_element

    for name in (
        "ImageMotionEstimationNode",
        "HomographyCalibrationNode",
        "MotionCompensationNode",
        "FlightGeoReferenceNode",
        "SpeedEstimationNode",
        "DirectionFlowNode",
        "LaneDetectionNode",
        "LaneAnalysisNode",
        "TrajectoryNode",
        "RoadMapMatchingNode",
        "AutoLaneInferenceNode",
        "ConflictDetectionNode",
        "CalcStatisticsNode",
    ):
        monkeypatch.setattr(main_optimized, name, PassthroughNode)
    monkeypatch.setattr(main_optimized, "GroundTrajectoryTrackerNode", FakeGroundTracker)
    monkeypatch.setattr(
        main_optimized, "PostTrackingWorldProjectionNode", FakeWorldProjection
    )
    monkeypatch.setattr(main_optimized, "TrackerInfoUpdateNode", FakeTrackerInfo)
    monkeypatch.setattr(main_optimized, "GeoJsonExportNode", FakeGeoJson)
    monkeypatch.setattr(main_optimized, "KafkaProducerNode", FakeKafka)
    monkeypatch.setattr(main_optimized, "_setup_logging_in_subprocess", lambda: None)
    queue_out = RecordingQueue()

    main_optimized.proc_tracker_update_and_calc(
        InputQueue(),
        queue_out,
        {
            "tracking_profile": "hover_cruise_v1",
            "pipeline": {"send_info_kafka": True},
        },
        reader_pid=123,
    )

    assert events == [
        ("flush", 4.2, "natural_eof", [7]),
        "geojson_completed",
        "kafka_completed",
        ("kafka_sealed", "natural_eof"),
        "geojson_eof",
        "kafka_eof",
    ]
    assert queue_out.items == [sentinel]


def test_tracker_marks_replay_mission_incomplete_when_reader_dies_without_eof(monkeypatch):
    events = []

    class EmptyInputQueue:
        def get(self, timeout):
            raise main_optimized.Empty

    class PassthroughNode:
        def __init__(self, _config):
            pass

        def process(self, frame_element):
            return frame_element

    class FakeKafka(PassthroughNode):
        def mark_replay_mission_incomplete(self, *, failure_reason):
            events.append(("incomplete", failure_reason))

    for name in (
        "ImageMotionEstimationNode", "GroundTrajectoryTrackerNode",
        "HomographyCalibrationNode", "MotionCompensationNode",
        "FlightGeoReferenceNode", "PostTrackingWorldProjectionNode",
        "TrackerInfoUpdateNode", "SpeedEstimationNode", "DirectionFlowNode",
        "LaneDetectionNode", "TrajectoryNode", "RoadMapMatchingNode",
        "LaneAnalysisNode", "AutoLaneInferenceNode", "ConflictDetectionNode",
        "CalcStatisticsNode", "GeoJsonExportNode",
    ):
        monkeypatch.setattr(main_optimized, name, PassthroughNode)
    monkeypatch.setattr(main_optimized, "KafkaProducerNode", FakeKafka)
    monkeypatch.setattr(main_optimized, "_setup_logging_in_subprocess", lambda: None)
    monkeypatch.setattr(main_optimized, "_is_pid_alive", lambda _pid: False)

    main_optimized.proc_tracker_update_and_calc(
        EmptyInputQueue(),
        RecordingQueue(),
        {
            "tracking_profile": "hover_cruise_v1",
            "pipeline": {"send_info_kafka": True},
        },
        reader_pid=123,
    )

    assert events == [("incomplete", "reader_process_died")]


def test_tracker_sigterm_marks_incomplete_before_process_exit():
    events = []
    kafka = type(
        "Kafka",
        (),
        {
            "mark_replay_mission_incomplete": lambda self, *, failure_reason: events.append(
                failure_reason
            )
        },
    )()

    with pytest.raises(SystemExit) as exited:
        main_optimized._terminate_tracker_with_incomplete(kafka, signal.SIGTERM)

    assert events == ["signal_sigterm"]
    assert exited.value.code == 128 + signal.SIGTERM


def test_tracker_process_associates_image_ids_before_world_projection(monkeypatch):
    frame = FrameElement(
        "fixture.mp4", np.zeros((4, 4, 3), dtype=np.uint8), 1.0, 1, {}
    )
    sentinel = VideoEndBreakElement("fixture.mp4", 1.0)
    events = []

    class InputQueue:
        def __init__(self):
            self.items = [frame, sentinel]

        def get(self, timeout):
            assert timeout > 0
            return self.items.pop(0)

    def named_node(label):
        class Node:
            last_flush_result = {
                "termination_reason": "natural_eof",
                "terminated_track_ids": [],
            }

            def __init__(self, _config):
                pass

            def process(self, frame_element):
                if not isinstance(frame_element, VideoEndBreakElement):
                    events.append(label)
                return frame_element

        return Node

    class TrackerInfo(named_node("tracker_info")):
        def flush(self, timestamp, reason, terminated_track_ids):
            return None

    order = {
        "ImageMotionEstimationNode": "image_motion",
        "GroundTrajectoryTrackerNode": "image_bytetrack",
        "HomographyCalibrationNode": "homography",
        "MotionCompensationNode": "motion_compensation",
        "FlightGeoReferenceNode": "flight_georeference",
        "PostTrackingWorldProjectionNode": "post_id_world_projection",
        "SpeedEstimationNode": "speed",
        "DirectionFlowNode": "direction",
        "LaneDetectionNode": "lane_detection",
        "TrajectoryNode": "trajectory",
        "RoadMapMatchingNode": "map_matching",
        "LaneAnalysisNode": "lane_analysis",
        "AutoLaneInferenceNode": "auto_lane",
        "ConflictDetectionNode": "conflict",
        "CalcStatisticsNode": "statistics",
        "GeoJsonExportNode": "geojson",
    }
    for class_name, label in order.items():
        monkeypatch.setattr(main_optimized, class_name, named_node(label))
    monkeypatch.setattr(main_optimized, "TrackerInfoUpdateNode", TrackerInfo)
    monkeypatch.setattr(main_optimized, "_setup_logging_in_subprocess", lambda: None)

    main_optimized.proc_tracker_update_and_calc(
        InputQueue(),
        RecordingQueue(),
        {
            "tracking_profile": "hover_cruise_v1",
            "pipeline": {"send_info_kafka": False},
        },
        reader_pid=123,
    )

    assert events[:6] == [
        "image_motion",
        "image_bytetrack",
        "homography",
        "motion_compensation",
        "flight_georeference",
        "post_id_world_projection",
    ]


def test_show_process_renders_pending_tcc_before_evidence_publication(monkeypatch):
    frame = FrameElement(
        "fixture.mp4",
        np.full((8, 8, 3), 7, dtype=np.uint8),
        1.0,
        1,
        {},
    )
    frame.pending_tcc_envelopes = [{"msg_type": "uav_conflict", "data": {}}]
    sentinel = VideoEndBreakElement("fixture.mp4", 1.0)
    events = []

    class InputQueue:
        def __init__(self):
            self.items = [frame, sentinel]

        def get(self, timeout):
            assert timeout > 0
            return self.items.pop(0)

    class FakeShowNode:
        def __init__(self, _config):
            pass

        def process(self, frame_element):
            events.append("show")
            assert np.all(frame_element.frame == 7)
            frame_element.frame[:, :] = 19
            frame_element.frame_result = frame_element.frame
            return frame_element

    class FakeTccEvidencePublisher:
        def __init__(self, _config):
            pass

        def process(self, frame_element):
            if isinstance(frame_element, VideoEndBreakElement):
                events.append("tcc_eof")
                return frame_element
            events.append("tcc")
            assert np.all(frame_element.frame == 7)
            assert np.all(frame_element.frame_result == 19)
            return frame_element

    monkeypatch.setattr(main_optimized, "ShowNode", FakeShowNode)
    monkeypatch.setattr(
        main_optimized,
        "TccEvidencePublisherNode",
        FakeTccEvidencePublisher,
        raising=False,
    )
    monkeypatch.setattr(main_optimized, "_setup_logging_in_subprocess", lambda: None)

    main_optimized.proc_show_node(
        InputQueue(),
        {
            "pipeline": {
                "save_video": False,
                "show_in_web": False,
                "send_info_kafka": True,
            },
            "video_saver_node": {"save_conflict_clips": False},
            "show_node": {"imshow": False},
        },
        tracker_pid=123,
    )

    assert events == ["show", "tcc", "tcc_eof"]
