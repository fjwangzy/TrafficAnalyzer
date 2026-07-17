import json
from pathlib import Path

from services.TelemetryFileReader import TelemetryFileReader


def test_offset_is_applied_before_tolerance_check(tmp_path):
    path = tmp_path / "telemetry.txt"
    path.write_text(
        json.dumps(
            [
                {"timestamp": 0.0, "latitude": 36.0, "longitude": 117.0},
                {"timestamp": 10.0, "latitude": 36.1, "longitude": 117.1},
            ]
        ),
        encoding="utf-8",
    )
    reader = TelemetryFileReader(str(path), sync_tolerance_sec=1.0, time_offset_sec=5.0)

    matched = reader.get_nearest(5.0)

    assert matched is not None
    assert matched["timestamp"] == 10.0


def test_gap_larger_than_tolerance_returns_no_telemetry(tmp_path):
    path = tmp_path / "telemetry.json"
    path.write_text(
        json.dumps(
            [
                {"timestamp": 0.0, "latitude": 36.0, "longitude": 117.0},
                {"timestamp": 10.0, "latitude": 36.1, "longitude": 117.1},
            ]
        ),
        encoding="utf-8",
    )
    reader = TelemetryFileReader(str(path), sync_tolerance_sec=2.5)

    assert reader.get_nearest(5.0) is None


def test_mp4new_lishi_0624_known_gap_is_not_filled():
    path = Path("test_videos/mp4new/srt/解放东路-礼士路0624晚高峰srt文件.txt")
    reader = TelemetryFileReader(
        str(path), sync_tolerance_sec=2.5, time_offset_sec=179.115
    )

    assert reader.get_nearest(800.0) is not None
    assert reader.get_nearest(820.0) is None
