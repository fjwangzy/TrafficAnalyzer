from elements.VideoEndBreakElement import VideoEndBreakElement
import main_optimized


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
    monkeypatch.setattr(main_optimized, "DetectionTrackingNodes", FakeDetectionNode)
    monkeypatch.setattr(main_optimized, "_setup_logging_in_subprocess", lambda: None)
    queue = RecordingQueue()

    main_optimized.proc_frame_reader_and_detection(
        queue,
        {"video_reader": {}, "telemetry": {}},
        time_sleep_start=0,
    )

    assert queue.items == [sentinel]
