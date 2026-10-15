from collections import deque
import json
import threading

from services.SrtTelemetryParser import SrtTelemetryParser
from services.TelemetryFileReader import TelemetryFileReader
from services.TelemetrySubscriber import TelemetrySubscriber


def test_srt_and_json_do_not_invent_zero_motion_when_speed_is_absent(tmp_path):
    parser = object.__new__(SrtTelemetryParser)
    srt = parser._extract_fields(
        "[latitude: 36.7] [longitude: 117.0] [rel_alt: 100 abs_alt: 120] "
        "[gb_yaw: 10 gb_pitch: -90 gb_roll: 0]",
        1.0,
    )
    telemetry_file = tmp_path / "telemetry.json"
    telemetry_file.write_text(json.dumps([
        {"timestamp": 1.0, "latitude": 36.7, "longitude": 117.0, "height": 100}
    ]))
    reader = TelemetryFileReader(str(telemetry_file))
    json_record = reader.get_nearest(1.0)

    assert srt["horizontal_speed"] is None
    assert srt["vertical_speed"] is None
    assert json_record["horizontal_speed"] is None
    assert json_record["vertical_speed"] is None


def test_mqtt_nearest_rejects_record_outside_sync_tolerance():
    subscriber = object.__new__(TelemetrySubscriber)
    subscriber.sync_tolerance_sec = 0.1
    subscriber._lock = threading.Lock()
    subscriber._buffer = deque([{"timestamp": 1.0, "latitude": 36.7}])

    assert subscriber.get_nearest(1.05) is not None
    assert subscriber.get_nearest(1.2) is None
