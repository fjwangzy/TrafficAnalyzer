import unittest
from types import SimpleNamespace

from app.api.v1 import alerts


class _AsyncAlertEngine:
    def __init__(self):
        self.called_with = None

    async def acknowledge_alert(self, alert_id: str, user: str = "admin"):
        self.called_with = (alert_id, user)
        return {
            "id": alert_id,
            "status": "acknowledged",
            "acknowledged_by": user,
        }


class AlertsApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_acknowledge_alert_awaits_engine_result(self):
        engine = _AsyncAlertEngine()
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(alert_engine=engine)),
            state=SimpleNamespace(user=SimpleNamespace(username="operator")),
        )

        payload = await alerts.acknowledge_alert("alert_1", request)

        self.assertEqual(payload["status"], "acknowledged")
        self.assertEqual(payload["acknowledged_by"], "operator")
        self.assertEqual(engine.called_with, ("alert_1", "operator"))

    async def test_acknowledge_alert_reads_actor_from_auth_claim_dict(self):
        engine = _AsyncAlertEngine()
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(alert_engine=engine)),
            state=SimpleNamespace(user={"username": "operator"}),
        )
        payload = await alerts.acknowledge_alert("alert_2", request)
        self.assertEqual(payload["acknowledged_by"], "operator")


if __name__ == "__main__":
    unittest.main()
