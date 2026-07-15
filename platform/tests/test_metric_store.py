import unittest
from datetime import UTC, datetime

from app.kafka.consumer import KafkaConsumerService
from app.services.metric_store import (
    InMemoryMetricStoreAdapter,
    MessageEnvelope,
    MetricContractError,
    PostgresMetricStoreAdapter,
)


class _RecordingWS:
    def __init__(self):
        self.messages = []

    async def broadcast(self, channel, message):
        self.messages.append((channel, message))


class MetricStoreContractTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.adapter = PostgresMetricStoreAdapter(None)

    def test_canonical_contract_requires_matching_v1_schema(self):
        now = datetime.now(UTC).isoformat()
        payload = {
            "message_id": "msg-1",
            "msg_type": "uav_stats",
            "schema_version": "uav_stats/v2",
            "occurred_at": now,
            "produced_at": now,
            "source_system": "uav_traffic_analyzer_ai",
            "data": {},
        }
        with self.assertRaises(MetricContractError):
            self.adapter._normalize(MessageEnvelope(payload, "uav_statistics_1", 0, 1))

    def test_legacy_relative_time_is_not_treated_as_unix_event_time(self):
        normalized = self.adapter._normalize(MessageEnvelope(
            {"msg_type": "track_complete", "timestamp_last": 12.5, "track_id": 7},
            "track_complete_1",
            0,
            3,
        ))
        self.assertEqual(normalized["msg_type"], "uav_track_complete")
        self.assertEqual(normalized["time_quality"], "ingest_only")
        self.assertEqual(normalized["source_time_raw"], {"value": 12.5})
        self.assertGreater(normalized["occurred_at"].year, 2020)

    async def test_consumer_does_not_rebroadcast_duplicate_message(self):
        ws = _RecordingWS()
        store = InMemoryMetricStoreAdapter()
        service = KafkaConsumerService(
            bootstrap_servers="localhost:9092",
            group_id="test",
            topics_pattern="uav_statistics_.*",
            ws_manager=ws,
            metric_store=store,
        )
        payload = {"message_id": "stable-1", "msg_type": "stats", "cars": 2}

        await service._process_message(payload, "statistics_1", 0, 10)
        await service._process_message(payload, "statistics_1", 0, 11)

        self.assertEqual(len(ws.messages), 1)
        self.assertEqual(ws.messages[0][0], "uav_intersection:INT_camera_1")
        self.assertEqual(ws.messages[0][1]["type"], "uav_stats")

    async def test_consumer_quarantines_permanent_contract_error_without_broadcast(self):
        ws = _RecordingWS()
        store = InMemoryMetricStoreAdapter()
        service = KafkaConsumerService(
            bootstrap_servers="localhost:9092",
            group_id="test",
            topics_pattern="uav_statistics_.*",
            ws_manager=ws,
            metric_store=store,
        )
        invalid = {
            "message_id": "poison-1",
            "msg_type": "uav_stats",
            "schema_version": "uav_stats/v2",
            "source_system": "uav_traffic_analyzer_ai",
            "data": {},
        }

        await service._process_message(invalid, "uav_statistics_1", 2, 99)

        self.assertEqual(ws.messages, [])
        self.assertEqual(len(store.dead_letters), 1)
        dead_letter = store.dead_letters[("uav_statistics_1", 2, 99)]
        self.assertEqual(dead_letter["reason_code"], "MetricContractError")

    async def test_identity_conflict_is_quarantined(self):
        ws = _RecordingWS()
        store = InMemoryMetricStoreAdapter()
        service = KafkaConsumerService(
            bootstrap_servers="localhost:9092",
            group_id="test",
            topics_pattern="statistics_.*",
            ws_manager=ws,
            metric_store=store,
        )
        first = {"message_id": "stable-2", "msg_type": "stats", "cars": 2}
        conflicting = {**first, "cars": 9}

        await service._process_message(first, "statistics_1", 0, 10)
        await service._process_message(conflicting, "statistics_1", 0, 11)

        self.assertEqual(len(ws.messages), 1)
        self.assertEqual(len(store.dead_letters), 1)
        self.assertEqual(
            store.dead_letters[("statistics_1", 0, 11)]["reason_code"],
            "MessageIdentityConflict",
        )


if __name__ == "__main__":
    unittest.main()
