import unittest

from app.services.alert_engine import AlertEngine


class _RecordingWS:
    def __init__(self):
        self.messages = []

    async def broadcast(self, channel, message):
        self.messages.append((channel, message))


class _MemoryAlertStore:
    def __init__(self):
        self.records = {}

    async def list_alerts(self):
        return list(self.records.values())

    async def save_alert(self, alert):
        self.records[alert["id"]] = dict(alert)

    async def update_alert(self, alert):
        self.records[alert["id"]] = dict(alert)


class AlertEnginePersistenceTest(unittest.IsolatedAsyncioTestCase):
    async def test_alerts_are_saved_loaded_and_acknowledged_through_store(self):
        store = _MemoryAlertStore()
        first_engine = AlertEngine(_RecordingWS(), alert_store=store)

        await first_engine._create_alert(
            "INT_camera_1",
            alert_type="conflict",
            severity="P1",
            title="机非冲突",
            description="TTC=1.2s",
            track_ids=[96, 88],
        )

        saved = store.records.copy()
        self.assertEqual(len(saved), 1)
        alert_id = next(iter(saved))
        self.assertEqual(saved[alert_id]["status"], "open")

        restarted_engine = AlertEngine(_RecordingWS(), alert_store=store)
        await restarted_engine.load_persisted_alerts()

        restored = restarted_engine.get_alert(alert_id)
        self.assertIsNotNone(restored)
        self.assertEqual(restored["title"], "机非冲突")
        self.assertEqual(restored["track_ids"], [96, 88])

        acknowledged = await restarted_engine.acknowledge_alert(alert_id, "operator")
        self.assertEqual(acknowledged["status"], "acknowledged")
        self.assertEqual(store.records[alert_id]["acknowledged_by"], "operator")


if __name__ == "__main__":
    unittest.main()
