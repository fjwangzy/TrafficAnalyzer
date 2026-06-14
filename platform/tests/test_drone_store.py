import unittest

from app.models import drone_store


class DroneStoreTelemetryHistoryTest(unittest.TestCase):
    def setUp(self):
        drone_store.DRONES.clear()
        drone_store.MISSIONS.clear()
        drone_store._INTERSECTION_DRONE_MAP.clear()
        drone_store._TELEMETRY_HISTORY.clear()

    def test_update_drone_telemetry_records_bounded_history(self):
        for i in range(3):
            drone_store.update_drone_telemetry(
                "drone_1",
                {
                    "lat": 36.7 + i,
                    "lon": 117.0 + i,
                    "alt_agl": 80 + i,
                    "battery_pct": 90 - i,
                    "timestamp": 1_700_000_000 + i,
                    "intersection_id": "INT_camera_1",
                },
            )

        history = drone_store.get_telemetry_history("drone_1", limit=2)

        self.assertEqual([p["timestamp"] for p in history], [1_700_000_001, 1_700_000_002])
        self.assertEqual(history[-1]["lat"], 38.7)
        self.assertEqual(drone_store.get_drone_trajectory("drone_1", limit=1)[0]["lon"], 119.0)


if __name__ == "__main__":
    unittest.main()
