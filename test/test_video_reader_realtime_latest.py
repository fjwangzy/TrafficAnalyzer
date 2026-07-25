import numpy as np

from nodes.VideoReader import _LatestFrameStream


class _FiniteFastStream:
    def __init__(self, frames=5):
        self.frames = frames
        self.index = 0

    def read(self):
        if self.index >= self.frames:
            return False, None
        self.index += 1
        return True, np.full((2, 2, 3), self.index, dtype=np.uint8)


def test_realtime_decoder_keeps_only_latest_frame_and_reports_superseded_count():
    latest = _LatestFrameStream(_FiniteFastStream(frames=5))
    latest.start()

    ok, frame, sequence, _captured_at, dropped = latest.read_latest(0)

    assert ok is True
    assert sequence >= 1
    assert int(frame[0, 0, 0]) == sequence
    assert dropped == sequence - 1
