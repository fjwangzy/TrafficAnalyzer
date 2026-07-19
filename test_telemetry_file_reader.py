import json
from pathlib import Path

from services.TelemetryFileReader import TelemetryFileReader
from services.SrtTelemetryParser import SrtTelemetryParser


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


def test_srt_offset_is_used_for_tolerance_and_out_of_range_returns_none(tmp_path):
    path = tmp_path / "telemetry.srt"
    path.write_text(
        "1\n00:00:10,000 --> 00:00:10,033\n"
        "FrameCnt: 1 2026-01-01 00:00:10.000\n"
        "[latitude: 36.0] [longitude: 117.0] [rel_alt: 100] [abs_alt: 150]\n",
        encoding="utf-8",
    )
    reader = SrtTelemetryParser(str(path), sync_tolerance_sec=0.1, time_offset_sec=10.0)

    assert reader.get_nearest(0.0) is not None
    assert reader.get_nearest(100.0) is None
