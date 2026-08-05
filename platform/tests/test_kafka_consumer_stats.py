import unittest
from unittest.mock import patch

from app.kafka.consumer import KafkaConsumerService
from app.services.alert_engine import AlertEngine
from app.services.metric_store import PersistResult


class _RecordingWS:
    def __init__(self):
        self.messages = []

    async def broadcast(self, channel, message):
        self.messages.append((channel, message))


class _FailingLaneAnnotationStore:
    def observe_stats(self, intersection_id, data):
        raise OSError("[Errno 30] Read-only file system: '/calibration'")


class _FailingAlertEngine:
    async def check_stats(self, intersection_id, data):
        raise TypeError("broken alert rule")


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


class _StartingKafkaConsumer:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.subscribed_pattern = None

    def subscribe(self, pattern=None, topics=None):
        self.subscribed_pattern = pattern

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True


class _ReplayStore:
    def __init__(self):
        self.dispatched = []

    async def persist(self, envelope):
        return PersistResult(
            False,
            envelope.payload["message_id"],
            envelope.payload["msg_type"],
            envelope.payload,
            ("replay:1",),
            "pending",
        )

    async def mark_dispatched(self, source_system, message_id):
        self.dispatched.append((source_system, message_id))


class KafkaConsumerStatsTest(unittest.IsolatedAsyncioTestCase):
    async def test_replay_consumer_persists_without_broadcasting_into_live_monitoring(self):
        ws = _RecordingWS()
        store = _ReplayStore()
        service = KafkaConsumerService(
            bootstrap_servers="localhost:9092",
            group_id="uav-platform-replay-v2",
            topics_pattern=r"uav_replay_v2_.*",
            ws_manager=ws,
            metric_store=store,
            dispatch_realtime=False,
        )
        payload = {
            "message_id": "replay-track-1",
            "msg_type": "uav_track_complete",
            "schema_version": "uav_track_complete/replay-v2",
            "source_system": "uav_traffic_analyzer_ai",
            "data": {"mission_id": "MSN-1", "track_id": "J-1"},
        }

        await service._process_message(
            payload,
            "uav_replay_v2_track_complete_SRC-1",
            0,
            1,
        )

        self.assertEqual(ws.messages, [])
        self.assertEqual(store.dispatched, [("uav_traffic_analyzer_ai", "replay-track-1")])

    def test_extract_intersection_rejects_legacy_topic(self):
        service = KafkaConsumerService(
            bootstrap_servers="localhost:9092",
            group_id="test",
            topics_pattern="uav_statistics_.*",
            ws_manager=_RecordingWS(),
        )

        self.assertEqual(service._extract_intersection("uav_statistics_3"), "INT_camera_3")
        with self.assertRaisesRegex(ValueError, "unsupported canonical topic"):
            service._extract_intersection("statistics_3")

    async def test_start_failure_closes_consumer_and_enters_degraded_mode(self):
        ws = _RecordingWS()
        fake_consumer = _FailingKafkaConsumer()
        service = KafkaConsumerService(
            bootstrap_servers="missing-kafka:9092",
            group_id="test",
            topics_pattern="uav_statistics_.*",
            ws_manager=ws,
        )

        with patch("app.kafka.consumer.AIOKafkaConsumer", return_value=fake_consumer):
            await service.start()
            await service.stop()

        self.assertTrue(fake_consumer.stopped)
        self.assertIsNone(service._consumer)
        self.assertFalse(service._running)

    async def test_consumer_allows_one_slow_durable_message_without_rebalance(self):
        fake_consumer = _StartingKafkaConsumer()
        service = KafkaConsumerService(
            bootstrap_servers="localhost:9092",
            group_id="test",
            topics_pattern="uav_statistics_.*",
            ws_manager=_RecordingWS(),
        )

        with patch(
            "app.kafka.consumer.AIOKafkaConsumer",
            return_value=fake_consumer,
        ) as constructor:
            created = await service._create_consumer()

        self.assertIs(created, fake_consumer)
        self.assertTrue(fake_consumer.started)
        kwargs = constructor.call_args.kwargs
        self.assertEqual(kwargs["max_poll_records"], 1)
        self.assertGreaterEqual(kwargs["max_poll_interval_ms"], 1_800_000)

    async def test_stats_broadcast_continues_when_lane_annotation_store_fails(self):
        ws = _RecordingWS()
        service = KafkaConsumerService(
            bootstrap_servers="localhost:9092",
            group_id="test",
            topics_pattern="uav_statistics_.*",
            ws_manager=ws,
            lane_annotation_store=_FailingLaneAnnotationStore(),
        )

        await service._handle_stats(
            {
                "msg_type": "uav_stats",
                "lane_stats": {"1": {"count": 2}},
                "active_trajectories": [{"track_id": 7, "trajectory_enu_m": [[0, 0]]}],
            },
            "INT_camera_1",
        )

        self.assertEqual(len(ws.messages), 1)
        channel, message = ws.messages[0]
        self.assertEqual(channel, "uav_intersection:INT_camera_1")
        self.assertEqual(message["type"], "uav_stats")
        self.assertEqual(message["data"]["active_trajectories"][0]["track_id"], 7)
        self.assertEqual(message["data"]["lanes"][0]["vehicle_count"], 2)

    async def test_stats_with_null_optional_metrics_reaches_realtime_channel(self):
        ws = _RecordingWS()
        alert_engine = AlertEngine(ws)
        service = KafkaConsumerService(
            bootstrap_servers="localhost:9092",
            group_id="test",
            topics_pattern="uav_statistics_.*",
            ws_manager=ws,
            alert_engine=alert_engine,
        )

        await service._handle_stats(
            {
                "msg_type": "uav_stats",
                "lanes": [{"lane_id": 1, "queue_length_m": None}],
                "congestion_index": None,
                "lane_match_rate": None,
                "avg_speed_kmh": None,
                "active_trajectories": [{"track_id": 7, "trajectory_gcj02": [[117.0, 36.7]]}],
            },
            "INT_camera_1",
        )

        self.assertEqual(len(ws.messages), 1)
        self.assertEqual(ws.messages[0][1]["data"]["active_trajectories"][0]["track_id"], 7)
        self.assertEqual(alert_engine.get_alerts_list(), [])

    async def test_stats_broadcast_continues_when_alert_evaluation_fails(self):
        ws = _RecordingWS()
        service = KafkaConsumerService(
            bootstrap_servers="localhost:9092",
            group_id="test",
            topics_pattern="uav_statistics_.*",
            ws_manager=ws,
            alert_engine=_FailingAlertEngine(),
        )

        with self.assertLogs("app.kafka.consumer", level="WARNING") as logs:
            await service._handle_stats(
                {
                    "msg_type": "uav_stats",
                    "active_trajectories": [{"track_id": 8, "trajectory_gcj02": [[117.0, 36.7]]}],
                },
                "INT_camera_1",
            )

        self.assertEqual(len(ws.messages), 1)
        self.assertIn("continuing realtime stats dispatch", " ".join(logs.output))

    async def test_conflict_events_are_upserted_by_motor_non_motor_pair(self):
        ws = _RecordingWS()
        service = KafkaConsumerService(
            bootstrap_servers="localhost:9092",
            group_id="test",
            topics_pattern="uav_conflicts_.*",
            ws_manager=ws,
        )

        first = {
            "msg_type": "uav_conflict",
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
            topics_pattern="uav_conflicts_.*",
            ws_manager=ws,
        )

        warning = {
            "msg_type": "uav_conflict",
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
