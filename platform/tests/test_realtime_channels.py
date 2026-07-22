import json
import unittest

from app.kafka.consumer import KafkaConsumerService
from app.kafka.ws_manager import WSManager
from app.services.alert_engine import AlertEngine


class _FakeWebSocket:
    def __init__(self):
        self.sent = []
        self.accepted = False
        self.closed = False

    async def accept(self):
        self.accepted = True

    async def send_text(self, text):
        self.sent.append(json.loads(text))

    async def close(self):
        self.closed = True


class _RecordingWS:
    def __init__(self):
        self.messages = []

    async def broadcast(self, channel, message):
        self.messages.append((channel, message))


class RealtimeChannelTest(unittest.IsolatedAsyncioTestCase):
    async def test_ws_manager_accepts_single_channel_and_channels_array(self):
        manager = WSManager()
        ws = _FakeWebSocket()
        await manager.connect(ws)

        await manager.handle_message(
            ws,
            json.dumps({
                "action": "subscribe",
                "channels": ["uav_intersection:INT_camera_1", "uav_alerts", "uav_system"],
            }),
        )
        await manager.handle_message(
            ws,
            json.dumps({"action": "subscribe", "channel": "uav_telemetry:drone_001"}),
        )

        self.assertTrue(ws.accepted)
        self.assertEqual(manager.channel_stats["uav_intersection:INT_camera_1"], 1)
        self.assertEqual(manager.channel_stats["uav_alerts"], 1)
        self.assertEqual(manager.channel_stats["uav_system"], 1)
        self.assertEqual(manager.channel_stats["uav_telemetry:drone_001"], 1)
        self.assertEqual(
            [msg["channel"] for msg in ws.sent],
            ["uav_intersection:INT_camera_1", "uav_alerts", "uav_system", "uav_telemetry:drone_001"],
        )

    async def test_ws_manager_rejects_legacy_channels_and_message_types(self):
        manager = WSManager()
        ws = _FakeWebSocket()
        await manager.connect(ws)

        with self.assertRaisesRegex(ValueError, "unsupported WebSocket channel"):
            await manager.subscribe(ws, "intersection:INT_camera_1")
        with self.assertRaisesRegex(ValueError, "unsupported WebSocket message type"):
            await manager.broadcast(
                "uav_intersection:INT_camera_1",
                {"channel": "uav_intersection:INT_camera_1", "type": "stats", "data": {}},
            )

        await manager.handle_message(
            ws,
            json.dumps({
                "action": "publish",
                "channel": "uav_intersection:INT_camera_1",
                "type": "stats",
                "data": {},
            }),
        )
        self.assertEqual(ws.sent[-1], {"error": "unsupported_action"})

    async def test_ws_manager_rejects_client_publish(self):
        manager = WSManager()
        publisher = _FakeWebSocket()
        subscriber = _FakeWebSocket()
        await manager.connect(publisher)
        await manager.connect(subscriber)
        await manager.subscribe(subscriber, "uav_system")

        await manager.handle_message(
            publisher,
            json.dumps({
                "action": "publish",
                "channel": "uav_system",
                "type": "uav_system_metrics",
                "data": {"fps": 15},
            }),
        )

        self.assertEqual(subscriber.sent, [])
        self.assertEqual(publisher.sent[-1], {"error": "unsupported_action"})

    async def test_kafka_handlers_broadcast_realtime_business_channels(self):
        ws = _RecordingWS()
        service = KafkaConsumerService(
            bootstrap_servers="localhost:9092",
            group_id="test",
            topics_pattern="(uav_(statistics|track_complete|conflicts|telemetry)_.*|uav_system_metrics)",
            ws_manager=ws,
        )

        await service._handle_stats(
            {
                "msg_type": "uav_stats",
                "cars": 12,
                "road_1": 3.0,
                "direction_flow": {"straight": {"count": 5, "avg_speed_kmh": 20.0}},
                "queue_count": 2,
                "avg_speed_kmh": 18.5,
                "drone_position": {"anchor_lat": 36.7, "anchor_lon": 117.0},
                "conflict_count": 1,
            },
            "INT_camera_1",
        )
        await service._handle_track_complete(
            {
                "msg_type": "uav_track_complete",
                "track_id": 7,
                "trajectory_px": [[1, 2]],
                "trajectory_enu_m": [[0.1, 0.2]],
                "turn_behavior": "right_turn",
                "avg_speed_kmh": 12.3,
                "entry_point_m": [0.0, 0.0],
                "exit_point_m": [1.0, 1.0],
            },
            "INT_camera_1",
        )
        await service._handle_conflict(
            {
                "msg_type": "uav_conflict",
                "motor_id": 96,
                "non_motor_id": 88,
                "severity": "critical",
                "ttc_sec": 1.2,
                "pet_sec": 0.4,
                "distance_m": 0.8,
                "conflict_scene": "suspected_right_turn_mv_nmv",
                "evidence": ["hard_ttc_or_pet"],
            },
            "INT_camera_1",
        )
        await service._handle_telemetry({"msg_type": "uav_telemetry", "drone_id": "drone_001"})
        await service._handle_system_metrics({"msg_type": "uav_system_metrics", "fps": 14.0})

        broadcasts = [(channel, message["type"]) for channel, message in ws.messages]
        self.assertIn(("uav_intersection:INT_camera_1", "uav_stats"), broadcasts)
        self.assertIn(("uav_intersection:INT_camera_1", "uav_track_complete"), broadcasts)
        self.assertIn(("uav_intersection:INT_camera_1", "uav_conflict"), broadcasts)
        self.assertIn(("uav_telemetry:drone_001", "uav_telemetry"), broadcasts)
        self.assertIn(("uav_system", "uav_system_metrics"), broadcasts)

    async def test_alert_engine_broadcasts_alerts_channel(self):
        ws = _RecordingWS()
        alert_engine = AlertEngine(ws)

        await alert_engine._create_alert(
            "INT_camera_1",
            alert_type="conflict",
            severity="P1",
            title="机非冲突",
            description="TTC=1.2s",
            track_ids=[96, 88],
        )

        self.assertEqual(len(ws.messages), 2)
        self.assertEqual(ws.messages[0][0], "uav_alerts")
        self.assertEqual(ws.messages[0][1]["type"], "uav_alert_new")
        self.assertEqual(ws.messages[1][0], "uav_alerts:INT_camera_1")
