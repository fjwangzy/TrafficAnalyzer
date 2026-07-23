import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from elements.VideoEndBreakElement import VideoEndBreakElement
from nodes.VideoReader import VideoReader


class VideoReaderFrameStrideTest(unittest.TestCase):
    def test_frame_stride_emits_every_nth_source_frame(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / "stride_test.avi"
            writer = cv2.VideoWriter(
                str(video_path),
                cv2.VideoWriter_fourcc(*"MJPG"),
                10.0,
                (32, 24),
            )
            self.assertTrue(writer.isOpened())
            for i in range(10):
                frame = np.full((24, 32, 3), i, dtype=np.uint8)
                writer.write(frame)
            writer.release()

            reader = VideoReader(
                {
                    "src": str(video_path),
                    "skip_secs": 0,
                    "frame_stride": 3,
                    "roads_info": "",
                }
            )

            frame_nums = []
            for frame_element in reader.process():
                if isinstance(frame_element, VideoEndBreakElement):
                    break
                frame_nums.append(frame_element.frame_num)
            reader.stream.release()

        self.assertEqual(frame_nums, [1, 4, 7, 10])


if __name__ == "__main__":
    unittest.main()
