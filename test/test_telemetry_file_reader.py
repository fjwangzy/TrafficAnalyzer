import json
from pathlib import Path

from services.TelemetryFileReader import TelemetryFileReader
from services.SrtTelemetryParser import SrtTelemetryParser
from services.dji_telemetry import extract_dji_telemetry


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


def test_file_telemetry_interpolates_position_at_frame_time(tmp_path):
    path = tmp_path / "telemetry.json"
    path.write_text(
        json.dumps(
            [
                {
                    "timestamp": 0.0,
                    "latitude": 36.659700,
                    "longitude": 117.118800,
                    "height": 226.0,
                },
                {
                    "timestamp": 2.0,
                    "latitude": 36.659710,
                    "longitude": 117.118900,
                    "height": 228.0,
                },
            ]
        ),
        encoding="utf-8",
    )
    reader = TelemetryFileReader(
        str(path),
        sync_tolerance_sec=2.5,
        max_interpolation_gap_sec=2.5,
    )

    record = reader.get_nearest(1.0)

    assert record is not None
    assert record["timestamp"] == 1.0
    assert record["telemetry_interpolated"] is True
    assert record["telemetry_left_timestamp_sec"] == 0.0
    assert record["telemetry_right_timestamp_sec"] == 2.0
    assert record["telemetry_interpolation_ratio"] == 0.5
    assert record["height"] == 227.0
    assert record["latitude"] == 36.659705
    assert record["longitude"] == 117.11885


def test_file_telemetry_interpolates_heading_across_wraparound(tmp_path):
    path = tmp_path / "telemetry.json"
    path.write_text(
        json.dumps(
            [
                {"timestamp": 0.0, "attitude_head": 179.0, "gimbal_yaw": 179.0},
                {"timestamp": 2.0, "attitude_head": -179.0, "gimbal_yaw": -179.0},
            ]
        ),
        encoding="utf-8",
    )
    reader = TelemetryFileReader(
        str(path),
        sync_tolerance_sec=2.5,
        max_interpolation_gap_sec=2.5,
    )

    record = reader.get_nearest(1.0)

    assert record is not None
    assert abs(abs(record["attitude_head"]) - 180.0) < 1e-9
    assert abs(abs(record["gimbal_yaw"]) - 180.0) < 1e-9


def test_dji_file_preserves_recorded_time_for_offline_event_time(tmp_path):
    path = tmp_path / "dji-telemetry.json"
    path.write_text(
        json.dumps(
            {
                "data": [
                    {
                        "time": "2026-08-13 18:00:00.000",
                        "value": json.dumps(_mp4820_payload()),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    record = TelemetryFileReader(str(path), agl_policy="laser_target").get_nearest(0.0)

    assert record is not None
    assert record["recorded_at"] == "2026-08-13T10:00:00+00:00"


def test_dji_file_interpolates_recorded_time_to_video_frame(tmp_path):
    path = tmp_path / "dji-telemetry.json"
    path.write_text(
        json.dumps(
            {
                "data": [
                    {
                        "time": "2026-08-13 18:00:00.000",
                        "value": json.dumps(_mp4820_payload()),
                    },
                    {
                        "time": "2026-08-13 18:00:02.000",
                        "value": json.dumps(_mp4820_payload()),
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    reader = TelemetryFileReader(
        str(path),
        sync_tolerance_sec=2.5,
        max_interpolation_gap_sec=2.5,
        agl_policy="laser_target",
    )

    record = reader.get_nearest(1.0)

    assert record is not None
    assert record["recorded_at"] == "2026-08-13T10:00:01+00:00"


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


def _mp4820_payload(*, laser_state=0, camera_zoom=1.0):
    return {
        "height": 226.6,
        "elevation": 115.0,
        "latitude": 36.65,
        "longitude": 117.10,
        "99-0-0": {
            "payload_index": "99-0-0",
            "gimbal_pitch": -90.0,
            "gimbal_roll": 0.0,
            "measure_target_altitude": 92.6,
            "measure_target_distance": 134.0,
            "measure_target_error_state": laser_state,
            "zoom_factor": 0.56,
        },
        "cameras": [{
            "payload_index": "99-0-0",
            "video_storage_settings": ["vision"],
            "zoom_factor": camera_zoom,
        }],
    }


def test_laser_target_policy_uses_verified_target_height_not_height_or_elevation():
    record = extract_dji_telemetry(_mp4820_payload(), 12.0, agl_policy="laser_target")

    assert record["altitude_ellipsoid_m"] == 226.6
    assert record["altitude_takeoff_relative_m"] == 115.0
    assert record["altitude_agl"] == 134.0
    assert record["altitude_agl_source"] == "laser_target_altitude"
    assert record["altitude_agl_residual_m"] == 0.0
    assert record["zoom_factor"] == 1.0
    assert record["camera_lens_verified"] is True


def test_laser_target_policy_fails_closed_for_bad_laser_or_ambiguous_lens():
    bad_laser = extract_dji_telemetry(
        _mp4820_payload(laser_state=1), 12.0, agl_policy="laser_target"
    )
    ambiguous_lens = extract_dji_telemetry(
        _mp4820_payload(camera_zoom=7.0),
        12.0,
        agl_policy="laser_target",
        camera_lens_policy="auto_from_telemetry",
    )

    assert bad_laser["altitude_agl"] is None
    assert bad_laser["altitude_agl_source"] == "unavailable"
    assert ambiguous_lens["zoom_factor"] is None
    assert ambiguous_lens["camera_lens_verified"] is False


def test_declared_standard_lens_group_sets_verified_wide_1x_lineage():
    record = extract_dji_telemetry(
        _mp4820_payload(camera_zoom=7.0),
        12.0,
        agl_policy="legacy_height",
    )

    assert record["camera_stream"] == "vision"
    assert record["camera_lens_verified"] is True
    assert record["zoom_factor"] == 1.0
    assert record["zoom_factor_source"] == "source_profile_standard_wide_1x"
