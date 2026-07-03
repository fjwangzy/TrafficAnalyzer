from unittest.mock import MagicMock, patch

from app.utils.influx_query import InfluxQuery


class _Result:
    def __init__(self, points):
        self._points = points

    def get_points(self):
        return self._points


def test_influx_query_creates_missing_database_and_switches_to_it():
    client = MagicMock()
    client.get_list_database.return_value = [{"name": "_internal"}]

    with patch("app.utils.influx_query.InfluxDBClient", return_value=client):
        InfluxQuery(host="influxdb", port=8086, database="influx")

    client.create_database.assert_called_once_with("influx")
    client.switch_database.assert_called_once_with("influx")


def test_influx_query_switches_without_creating_existing_database():
    client = MagicMock()
    client.get_list_database.return_value = [{"name": "influx"}]

    with patch("app.utils.influx_query.InfluxDBClient", return_value=client):
        InfluxQuery(host="influxdb", port=8086, database="influx")

    client.create_database.assert_not_called()
    client.switch_database.assert_called_once_with("influx")


def test_query_stats_merges_dynamic_road_fields_from_mean_query():
    client = MagicMock()
    client.get_list_database.return_value = [{"name": "influx"}]
    client.query.side_effect = [
        _Result([{"time": "2026-07-01T00:00:00Z", "cars": 3.0}]),
        _Result([{"time": "2026-07-01T00:00:00Z", "mean_road_1": 4.5}]),
    ]

    with patch("app.utils.influx_query.InfluxDBClient", return_value=client):
        influx = InfluxQuery(host="influxdb", port=8086, database="influx")
        points = influx.query_stats("INT_smoke", period="5m", granularity="1s")

    assert points == [
        {"time": "2026-07-01T00:00:00Z", "cars": 3.0, "road_1": 4.5}
    ]
    assert "SELECT mean(*)" in client.query.call_args_list[1].args[0]


def test_query_stats_returns_base_points_when_road_query_fails():
    client = MagicMock()
    client.get_list_database.return_value = [{"name": "influx"}]
    client.query.side_effect = [
        _Result([{"time": "2026-07-01T00:00:00Z", "cars": 3.0}]),
        RuntimeError("GROUP BY requires aggregate"),
    ]

    with patch("app.utils.influx_query.InfluxDBClient", return_value=client):
        influx = InfluxQuery(host="influxdb", port=8086, database="influx")
        points = influx.query_stats("INT_smoke", period="5m", granularity="1s")

    assert points == [{"time": "2026-07-01T00:00:00Z", "cars": 3.0}]


def test_write_conflict_event_persists_replay_evidence_fields():
    client = MagicMock()
    client.get_list_database.return_value = [{"name": "influx"}]

    with patch("app.utils.influx_query.InfluxDBClient", return_value=client):
        influx = InfluxQuery(host="influxdb", port=8086, database="influx")
        influx.write_conflict_event({
            "intersection_id": "INT_camera_1",
            "timestamp": 1_780_000_000.0,
            "motor_id": 96,
            "non_motor_id": 88,
            "prediction_type": "path_intersection",
            "distance_m": 0.0,
            "ttc_sec": 1.2,
            "pet_sec": 0.3,
            "arrival_time_delta_sec": 0.3,
            "motor_arrival_ttc_sec": 1.1,
            "non_motor_arrival_ttc_sec": 1.4,
            "severity": "critical",
            "conflict_scene": "suspected_right_turn_mv_nmv",
            "conflict_angle_deg": 92.5,
            "evidence": ["hard_ttc_or_pet", "hard_pet"],
            "risk_score": 70,
            "motor_speed_kmh": 25.0,
            "motor_position_m": [10.1, 20.2],
            "non_motor_position_m": [10.1, 20.2],
            "world_anchor_lat_lon": [36.7029, 117.0223],
        })

    point = client.write_points.call_args.args[0][0]
    assert point["measurement"] == "conflict_events"
    assert point["tags"] == {
        "intersection_id": "INT_camera_1",
        "severity": "critical",
        "prediction_type": "path_intersection",
        "conflict_scene": "suspected_right_turn_mv_nmv",
    }
    assert point["fields"]["pet_sec"] == 0.3
    assert point["fields"]["arrival_time_delta_sec"] == 0.3
    assert point["fields"]["motor_arrival_ttc_sec"] == 1.1
    assert point["fields"]["non_motor_arrival_ttc_sec"] == 1.4
    assert point["fields"]["conflict_angle_deg"] == 92.5
    assert point["fields"]["risk_score"] == 70
    assert point["fields"]["motor_speed_kmh"] == 25.0
    assert point["fields"]["evidence"] == '["hard_ttc_or_pet", "hard_pet"]'
    assert point["fields"]["motor_position_m"] == "[10.1, 20.2]"
    assert point["fields"]["non_motor_position_m"] == "[10.1, 20.2]"
    assert point["fields"]["world_anchor_lat_lon"] == "[36.7029, 117.0223]"
    assert point["time"] == 1_780_000_000_000_000_000


def test_query_conflict_events_deserializes_replay_json_fields():
    client = MagicMock()
    client.get_list_database.return_value = [{"name": "influx"}]
    client.query.return_value = _Result([{
        "time": "2026-07-01T00:00:00Z",
        "motor_id": 96,
        "non_motor_id": 88,
        "evidence": '["hard_ttc_or_pet"]',
        "motor_position_m": "[10.1, 20.2]",
        "non_motor_position_m": "[10.1, 20.2]",
        "world_anchor_lat_lon": "[36.7029, 117.0223]",
    }])

    with patch("app.utils.influx_query.InfluxDBClient", return_value=client):
        influx = InfluxQuery(host="influxdb", port=8086, database="influx")
        points = influx.query_conflict_events("INT_camera_1", period="1h")

    assert points[0]["evidence"] == ["hard_ttc_or_pet"]
    assert points[0]["motor_position_m"] == [10.1, 20.2]
    assert points[0]["non_motor_position_m"] == [10.1, 20.2]
    assert points[0]["world_anchor_lat_lon"] == [36.7029, 117.0223]
