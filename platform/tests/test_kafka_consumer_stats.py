import unittest
from unittest.mock import patch

from app.kafka.consumer import KafkaConsumerService


class _RecordingWS:
    def __init__(self):
        self.messages = []

    async def broadcast(self, channel, message):
        self.messages.append((channel, message))


class _FailingLaneAnnotationStore:
    def observe_stats(self, intersection_id, data):
        raise OSError("[Errno 30] Read-only file system: '/calibration'")


class _FailingKafkaConsumer:
    def __init__(self):
        self.stopped = False
        self.subscribed_pattern = None

    def subscribe(self, pattern=None, topics=None):
        self.subscribed_pattern = pattern

    async def start(self):
        raise OSError("broker unavailable")

    async def stop(self):
        self.stopped = True


class KafkaConsumerStatsTest(unittest.IsolatedAsyncioTestCase):
    async def test_start_failure_closes_consumer_and_enters_degraded_mode(self):
        ws = _RecordingWS()
        fake_consumer = _FailingKafkaConsumer()
        service = KafkaConsumerService(
            bootstrap_servers="missing-kafka:9092",
            group_id="test",
            topics_pattern="statistics_.*",
            ws_manager=ws,
        )

        with patch("app.kafka.consumer.AIOKafkaConsumer", return_value=fake_consumer):
            await service.start()
            await service.stop()

        self.assertTrue(fake_consumer.stopped)
        self.assertIsNone(service._consumer)
        self.assertFalse(service._running)

    async def test_stats_broadcast_continues_when_lane_annotation_store_fails(self):
        ws = _RecordingWS()
        service = KafkaConsumerService(
            bootstrap_servers="localhost:9092",
            group_id="test",
            topics_pattern="statistics_.*",
            ws_manager=ws,
            lane_annotation_store=_FailingLaneAnnotationStore(),
        )

        await service._handle_stats(
            {
                "msg_type": "stats",
                "lane_stats": {"1": {"count": 2}},
                "active_trajectories": [{"track_id": 7, "trajectory_world_m": [[0, 0]]}],
            },
            "INT_camera_1",
        )

        self.assertEqual(len(ws.messages), 1)
        channel, message = ws.messages[0]
        self.assertEqual(channel, "uav_intersection:INT_camera_1")
        self.assertEqual(message["type"], "uav_stats")
        self.assertEqual(message["data"]["active_trajectories"][0]["track_id"], 7)
        self.assertEqual(message["data"]["lanes"][0]["vehicle_count"], 2)

    async def test_conflict_events_are_upserted_by_motor_non_motor_pair(self):
        ws = _RecordingWS()
        service = KafkaConsumerService(
            bootstrap_servers="localhost:9092",
            group_id="test",
            topics_pattern="conflicts_.*",
            ws_manager=ws,
        )

        first = {
            "msg_type": "conflict",
            "motor_id": 96,
            "non_motor_id": 88,
            "severity": "critical",
            "ttc_sec": 2.6,
            "distance_m": 1.8,
        }
        duplicate = {**first, "ttc_sec": 2.5}

        await service._handle_conflict(first, "INT_camera_1")
        await service._handle_conflict(duplicate, "INT_camera_1")

        self.assertEqual(len(service._latest_conflicts["INT_camera_1"]), 1)
        self.assertEqual(service._latest_conflicts["INT_camera_1"][0]["ttc_sec"], 2.6)
        self.assertEqual(len(ws.messages), 1)

    async def test_conflict_events_allow_warning_to_critical_upgrade(self):
        ws = _RecordingWS()
        service = KafkaConsumerService(
            bootstrap_servers="localhost:9092",
            group_id="test",
            topics_pattern="conflicts_.*",
            ws_manager=ws,
        )

        warning = {
            "msg_type": "conflict",
            "motor_id": 96,
            "non_motor_id": 88,
            "severity": "warning",
            "ttc_sec": 3.5,
            "distance_m": 1.9,
        }
        critical = {
            **warning,
            "severity": "critical",
            "ttc_sec": 2.6,
            "distance_m": 1.8,
        }

        await service._handle_conflict(warning, "INT_camera_1")
        await service._handle_conflict(critical, "INT_camera_1")

        stored = service._latest_conflicts["INT_camera_1"]
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["severity"], "critical")
        self.assertEqual(stored[0]["ttc_sec"], 2.6)
        self.assertEqual(len(ws.messages), 2)
